"""The model rate limiter shared by every pod, in Valkey/Redis (``docs/deployment/eks-architecture.md`` section 3.1).

:class:`AdvancedTokenRateLimiter` counts requests and tokens in this process, so N pods together send N times the
provider's limit of ``config/models.yaml`` and meet a wall of 429s. This one keeps the same sliding windows in
Valkey, one set of keys per ``provider/model``:

- ``<prefix>:<key>:req``, ``:in``, ``:out``: sorted sets scored by time; a request is one member, a call's tokens one
  member ``<id>:<count>``;
- ``<prefix>:<key>:cool``: the cooldown after a 429, a key with a TTL, so one pod's 429 holds every pod.

Checking and reserving are one Lua script, so two pods can never both take the last slot. On by
``AGENT_REDIS_URL`` (the agent's Valkey, also used by runtime/load.py and the knowledge server); without it, or while Valkey does not answer, the in-process windows apply with the
budgets divided by ``MODEL_LIMITER_PODS`` (the most agent pods there can be), so the fleet still stays under the
provider's limit and customers are still answered (fail open, bounded).

The Valkey calls are synchronous with a 200 ms timeout: inside the VPC one is well under a millisecond, and the
limiter's generator is shared by the sync and the async paths.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any

from .rate_limiter import AdvancedTokenRateLimiter

logger = logging.getLogger(__name__)

PREFIX = "ratelimit"

# KEYS: req, in, out, cool. ARGV: now, window, rpm, input tpm, output tpm, member, wanted in, wanted out.
# Returns 0 when the slot was taken, else the seconds to wait.
ACQUIRE = """
local now, window = tonumber(ARGV[1]), tonumber(ARGV[2])
local rpm, itpm, otpm = tonumber(ARGV[3]), tonumber(ARGV[4]), tonumber(ARGV[5])
local member, want_in, want_out = ARGV[6], tonumber(ARGV[7]), tonumber(ARGV[8])
local cool = redis.call('PTTL', KEYS[4])
if cool > 0 then return tostring(cool / 1000) end
local cutoff = now - window
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', cutoff)
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', cutoff)
local function total(key)
  local sum = 0
  for _, m in ipairs(redis.call('ZRANGE', key, 0, -1)) do
    sum = sum + (tonumber(string.match(m, ':(%d+)$')) or 0)
  end
  return sum
end
local requests, used_in, used_out = redis.call('ZCARD', KEYS[1]), total(KEYS[2]), total(KEYS[3])
local wait = 0
if requests + 1 > rpm then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  if oldest[2] then wait = math.max(wait, window - (now - tonumber(oldest[2]))) end
end
for i, pair in ipairs({{KEYS[2], used_in, itpm, want_in}, {KEYS[3], used_out, otpm, want_out}}) do
  if pair[2] + pair[4] >= pair[3] then
    local oldest = redis.call('ZRANGE', pair[1], 0, 0, 'WITHSCORES')
    if oldest[2] then wait = math.max(wait, window - (now - tonumber(oldest[2]))) end
  end
end
if wait <= 0 then
  -- room, or one request larger than the whole minute: let it go and let the provider refuse it
  redis.call('ZADD', KEYS[1], now, member)
  local ttl = math.ceil(window * 1000) + 1000
  redis.call('PEXPIRE', KEYS[1], ttl)
  return '0'
end
return tostring(wait)
"""


class SharedTokenRateLimiter(AdvancedTokenRateLimiter):
    """The same interface and windows, counted across pods in Valkey."""

    def __init__(self, *args: Any, client: Any, pods: int = 1, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.shared_rpm = self.requests_per_minute
        self.shared_itpm = self.input_tokens_per_minute
        self.shared_otpm = self.output_tokens_per_minute
        # The in-process windows are the fallback: each pod's share of the budget.
        share = max(1, int(pods))
        self.requests_per_minute /= share
        self.input_tokens_per_minute /= share
        self.output_tokens_per_minute /= share
        self._client = client
        self._script = client.register_script(ACQUIRE)
        self._tls = threading.local()
        self._warned = 0.0

    @classmethod
    def from_config_shared(cls, provider: str, config: dict[str, Any], *, client: Any, pods: int) -> "SharedTokenRateLimiter":
        AdvancedTokenRateLimiter.from_config(provider, config)  # the same missing-setting error as in-process
        return cls(provider=provider, requests_per_minute=config["requests_per_minute"],
                   input_tokens_per_minute=config["input_tokens_per_minute"],
                   output_tokens_per_minute=config["output_tokens_per_minute"],
                   input_token_price_per_million=config["input_token_price_per_million"],
                   output_token_price_per_million=config["output_token_price_per_million"],
                   buffer_percentage=config["buffer_percentage"], client=client, pods=pods)

    def _keys(self) -> list[str]:
        # The script touches all four keys, so they share a hash tag ({provider}): on a cluster such as ElastiCache
        # Serverless, keys in different slots in one script fail with CROSSSLOT.
        base = f"{PREFIX}:{{{self.provider}}}"
        return [f"{base}:req", f"{base}:in", f"{base}:out", f"{base}:cool"]

    def _shared_wait(self, wanted_in: int = 0, wanted_out: int = 0) -> float | None:
        """Seconds to wait (0: the slot is ours), or None when Valkey did not answer."""
        try:
            answer = self._script(keys=self._keys(), args=[
                time.time(), self.window_seconds, self.shared_rpm, self.shared_itpm, self.shared_otpm,
                uuid.uuid4().hex, wanted_in, wanted_out])
        except Exception as error:  # noqa: BLE001 - fail open, bounded by this pod's share
            if time.monotonic() - self._warned > 60:
                self._warned = time.monotonic()
                logger.warning("[%s] shared limiter unavailable (%s): this pod's share applies", self.provider,
                               type(error).__name__)
            return None
        return float(answer.decode() if isinstance(answer, bytes) else answer)

    # The parent's acquire paths call _delays, then _reserve_locked. Here _delays reserves in Valkey when it ends
    # with room, and says so to _reserve_locked, which then only counts the attempt.
    def _delays(self, input_tokens: int = 0, estimated_output_tokens: int = 0):
        while True:
            wait = self._shared_wait(input_tokens, estimated_output_tokens)
            if wait is None:
                self._tls.shared = False
                yield from super()._delays(input_tokens, estimated_output_tokens)
                return
            if wait <= 0:
                self._tls.shared = True
                return
            step = min(wait, self.window_seconds)
            logger.info("[%s] shared rate limit reached, waiting %.2fs", self.provider, step)
            with self._lock:
                self.total_waited += step
            yield step

    def _reserve_locked(self) -> None:
        if getattr(self._tls, "shared", False):
            self._tls.shared = False
            self.total_attempts += 1
            return
        super()._reserve_locked()

    def acquire(self, *, blocking: bool = True) -> bool:
        if blocking:
            return super().acquire(blocking=True)
        wait = self._shared_wait()
        if wait is None:
            return super().acquire(blocking=False)
        if wait > 0:
            return False
        with self._lock:
            self.total_attempts += 1
        return True

    def record_request(self, input_tokens: int, output_tokens: int) -> None:
        super().record_request(input_tokens, output_tokens)
        keys, now, member = self._keys(), time.time(), uuid.uuid4().hex
        ttl = int(self.window_seconds * 1000) + 1000
        try:
            pipe = self._client.pipeline(transaction=False)
            pipe.zadd(keys[1], {f"{member}:{int(input_tokens)}": now})
            pipe.zadd(keys[2], {f"{member}:{int(output_tokens)}": now})
            pipe.pexpire(keys[1], ttl)
            pipe.pexpire(keys[2], ttl)
            pipe.execute()
        except Exception:  # noqa: BLE001 - the local window has them
            pass

    def record_rate_limited(self, retry_after: float | None = None) -> None:
        super().record_rate_limited(retry_after)
        wait = retry_after if retry_after and retry_after > 0 else self.window_seconds
        try:
            self._client.set(self._keys()[3], "1", px=int(wait * 1000))
        except Exception:  # noqa: BLE001 - the local cooldown holds this pod
            pass

    def stats(self) -> dict[str, Any]:
        return {**super().stats(), "shared": True}


_client_lock = threading.Lock()
_client: Any = None


def client() -> Any | None:
    """The Valkey client for the limiter, or None when ``AGENT_REDIS_URL`` is not set."""
    global _client
    url = os.getenv("AGENT_REDIS_URL")
    if not url:
        return None
    with _client_lock:
        if _client is None:
            import redis

            _client = redis.Redis.from_url(url, socket_timeout=0.2, socket_connect_timeout=0.2,
                                           health_check_interval=30)
        return _client


def pods() -> int:
    try:
        return max(1, int(os.getenv("MODEL_LIMITER_PODS", "1")))
    except ValueError:
        return 1
