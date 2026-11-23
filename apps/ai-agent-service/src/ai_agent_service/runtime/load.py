"""What this pod is doing, for scaling, and what the model has cost, for early warning.

``docs/deployment/eks-architecture.md`` sections 3.6 and 3.7, in the agent's Valkey (``AGENT_REDIS_URL``):

- **Load** (3.6). This process counts the turns it is taking and the voice WebSockets it holds open; every
  :data:`PUBLISH_SECONDS` it writes them to ``load:turns:<pod>`` and ``load:calls:<pod>`` with a 30-second TTL, so a
  pod that dies leaves no phantom load. ``GET /internal/load`` (any pod) adds the keys of every pod up: KEDA's
  ``metrics-api`` scaler reads it and keeps about N open calls per pod. The agent waits on the model most of the
  time, so CPU says nothing about its load.
- **Spend** (3.7). Each turn's model cost (``llm/token_ledger``, at the prices of ``config/models.yaml``) is added to
  ``spend:day:<UTC date>`` and ``spend:conv:<conversation>`` (7 days). Counted only: the thresholds that would hand a
  conversation to staff or switch to a cheaper model change what the agent does, so they wait for a decision and an
  evaluation run (``docs/plan/README.md``). The provider's invoice stays the real figure; ``EVAL_BUDGET_DB`` is
  evaluation's own.

Without ``AGENT_REDIS_URL`` the counts stay in this process (``/internal/load`` answers for this pod alone) and no
spend is kept.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

logger = logging.getLogger(__name__)

PUBLISH_SECONDS = 10
TTL_SECONDS = 30
SPEND_CONV_TTL = 7 * 24 * 3600

_turns = 0
_calls = 0
_client: Any = None


def pod() -> str:
    return os.getenv("HOSTNAME") or socket.gethostname()


def client() -> Any | None:
    global _client
    url = os.getenv("AGENT_REDIS_URL")
    if not url:
        return None
    if _client is None:
        import redis.asyncio as redis

        _client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5, health_check_interval=30)
    return _client


def set_client(value: Any) -> None:
    """Tests: a stand-in for the Valkey client."""
    global _client
    _client = value


@contextmanager
def turn() -> Iterator[None]:
    """Around one turn: counted while it runs."""
    global _turns
    _turns += 1
    try:
        yield
    finally:
        _turns -= 1


@contextmanager
def voice_call() -> Iterator[None]:
    """Around one voice WebSocket: counted while it is open."""
    global _calls
    _calls += 1
    try:
        yield
    finally:
        _calls -= 1


def here() -> dict[str, int]:
    return {"turns": _turns, "calls": _calls}


async def publish() -> None:
    redis = client()
    if redis is None:
        return
    name = pod()
    pipe = redis.pipeline(transaction=False)
    pipe.set(f"load:turns:{name}", _turns, ex=TTL_SECONDS)
    pipe.set(f"load:calls:{name}", _calls, ex=TTL_SECONDS)
    await pipe.execute()


async def publish_forever(every: float = PUBLISH_SECONDS) -> None:
    while True:
        try:
            await publish()
        except Exception as error:  # noqa: BLE001 - scaling reads a stale value for a few seconds, no more
            logger.debug("Could not publish load: %s", type(error).__name__)
        await asyncio.sleep(every)


async def fleet() -> dict[str, Any]:
    """Every live pod's counts, added up; this pod's alone without Valkey."""
    redis = client()
    if redis is None:
        return {**here(), "pods": 1, "shared": False}
    totals = {"turns": 0, "calls": 0}
    pods: set[str] = set()
    for kind in totals:
        keys = [key async for key in redis.scan_iter(match=f"load:{kind}:*", count=200)]
        # One GET a key, not MGET: ElastiCache Serverless is a cluster, and each pod's key is in its own slot
        # (MGET across slots fails with CROSSSLOT).
        pipe = redis.pipeline(transaction=False)
        for key in keys:
            pipe.get(key)
        values = await pipe.execute() if keys else []
        for key, value in zip(keys, values):
            if value is not None:
                totals[kind] += int(value)
                pods.add((key.decode() if isinstance(key, bytes) else key).split(":", 2)[2])
    return {**totals, "pods": len(pods), "shared": True}


async def add_spend(conversation_id: str | None, cost_usd: float | None) -> None:
    """Add one turn's model cost to the day's and the conversation's spend. Never raises."""
    redis = client()
    if redis is None or not cost_usd:
        return
    day = datetime.now(timezone.utc).date().isoformat()
    try:
        pipe = redis.pipeline(transaction=False)
        pipe.incrbyfloat(f"spend:day:{day}", float(cost_usd))
        pipe.expire(f"spend:day:{day}", 40 * 24 * 3600)
        if conversation_id:
            pipe.incrbyfloat(f"spend:conv:{conversation_id}", float(cost_usd))
            pipe.expire(f"spend:conv:{conversation_id}", SPEND_CONV_TTL)
        await pipe.execute()
    except Exception as error:  # noqa: BLE001 - a warning ledger, not the invoice
        logger.debug("Could not add spend: %s", type(error).__name__)


async def spend_today() -> float | None:
    redis = client()
    if redis is None:
        return None
    try:
        value = await redis.get(f"spend:day:{datetime.now(timezone.utc).date().isoformat()}")
    except Exception:  # noqa: BLE001
        return None
    return float(value) if value is not None else 0.0
