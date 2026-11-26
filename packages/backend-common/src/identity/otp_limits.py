"""How often a verification code may be sent (``docs/deployment/eks-architecture.md`` section 3.3).

Every code is an SMS someone pays for, and nothing stopped one person from asking for code after code. Before a
challenge is made:

| Key | Limit | Over it |
|---|---|---|
| ``{otp}:cooldown:<purpose>:<digest>`` | one code per :func:`cooldown` seconds for one step on a number | 429, with the wait |
| ``{otp}:hour:<digest>`` | :func:`per_hour_identifier` codes an hour for a number, every step together | 429 |
| ``{otp}:ip:<ip>`` | :func:`per_hour_ip` codes an hour from one address | 429 |

The cooldown is per step (``conversation``: identifying in a chat; ``register``; ``reset``), so a shopper who verifies
in the chat and then registers is not made to wait, while pressing "send again" is; the hourly limits count every
step, which is what bounds the bill. The keys hold the identifier's digest (``security.digest``), never the number.

With Redis (``REDIS_URL``, required in production) the counts are shared by every pod. Without it, or while it
does not answer, the number's limits are counted from the ``challenges`` table, which records every code sent; the
per-address limit then has no store and is skipped. The table and the customer tokens stay in Postgres: they are the
record. The three figures are ``OTP_COOLDOWN_SECONDS``, ``OTP_PER_HOUR_IDENTIFIER`` and ``OTP_PER_HOUR_IP``.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from src.db.models import Challenge, now


def _int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def cooldown() -> int:
    return _int("OTP_COOLDOWN_SECONDS", 60)


def per_hour_identifier() -> int:
    return _int("OTP_PER_HOUR_IDENTIFIER", 5)


def per_hour_ip() -> int:
    return _int("OTP_PER_HOUR_IP", 20)


#: A challenge expires this long after it is made (IdentityService.challenge): when it was sent, read back.
LIFETIME = timedelta(minutes=5)

# KEYS: cooldown, hour (identifier), and hour (ip) when the address is known. ARGV: cooldown s, per hour id, per hour ip.
# Every key carries the hash tag {otp}: on a cluster such as ElastiCache Serverless a script's keys must share a slot.
# Returns {0, 0} when allowed (and counts it), else {1, seconds to wait}.
CHECK = """
local cool = redis.call('PTTL', KEYS[1])
if cool > 0 then return {1, math.ceil(cool / 1000)} end
local hour = tonumber(redis.call('GET', KEYS[2]) or '0')
if hour >= tonumber(ARGV[2]) then return {1, redis.call('TTL', KEYS[2])} end
if KEYS[3] then
  local ip = tonumber(redis.call('GET', KEYS[3]) or '0')
  if ip >= tonumber(ARGV[3]) then return {1, redis.call('TTL', KEYS[3])} end
end
if tonumber(ARGV[1]) > 0 then redis.call('SET', KEYS[1], '1', 'EX', ARGV[1]) end
if redis.call('INCR', KEYS[2]) == 1 then redis.call('EXPIRE', KEYS[2], 3600) end
if KEYS[3] and redis.call('INCR', KEYS[3]) == 1 then redis.call('EXPIRE', KEYS[3], 3600) end
return {0, 0}
"""

_clients: dict[str, Any] = {}


def _redis(url: str) -> Any | None:
    if not url:
        return None
    if url not in _clients:
        import redis

        _clients[url] = redis.Redis.from_url(url, socket_timeout=0.3, socket_connect_timeout=0.3)
    return _clients[url]


def refuse(wait: float) -> HTTPException:
    wait = max(1, int(wait))
    return HTTPException(429, f"Vui lòng chờ {wait} giây rồi yêu cầu mã mới.", headers={"Retry-After": str(wait)})


def check(db: Any, *, digest: str, purpose: str, client_ip: str | None, redis_url: str) -> None:
    """Raise 429 if a code for *purpose* on *digest* (or from *client_ip*) may not be sent now; else count it."""
    client = _redis(redis_url)
    if client is not None:
        try:
            keys = [f"{{otp}}:cooldown:{purpose}:{digest}", f"{{otp}}:hour:{digest}"]
            if client_ip:
                keys.append(f"{{otp}}:ip:{client_ip}")
            blocked, wait = client.eval(CHECK, len(keys), *keys, cooldown(), per_hour_identifier(), per_hour_ip())
        except Exception:  # noqa: BLE001 - the table still knows every code sent
            pass
        else:
            if int(blocked):
                raise refuse(int(wait))
            return
    _check_table(db, digest, purpose)


def _check_table(db: Any, digest: str, purpose: str) -> None:
    current, gap = now(), cooldown()
    if gap:
        latest = db.scalar(select(func.max(Challenge.expires_at)).where(
            Challenge.identifier_digest == digest, Challenge.purpose == purpose))
        if latest is not None:
            latest = latest if latest.tzinfo else latest.replace(tzinfo=current.tzinfo)
            since = (current - (latest - LIFETIME)).total_seconds()
            if since < gap:
                raise refuse(gap - since)
    sent = db.scalar(select(func.count()).select_from(Challenge).where(
        Challenge.identifier_digest == digest, Challenge.expires_at > current - timedelta(hours=1) + LIFETIME))
    if (sent or 0) >= per_hour_identifier():
        raise refuse(3600)
