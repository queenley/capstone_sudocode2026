"""``kb:changed``: tell every knowledge server that ``kb_chunks`` changed.

The writer saves to Postgres first, then publishes on the agent's Valkey (``AGENT_REDIS_URL``). Each ``mcp-knowledge``
process listens from its first search and, on a message, marks its index stale: the next search compares
``kb_chunks``' stamp and rebuilds if it moved. Pub/sub keeps no message, so the ten-second stamp check of
``mcp/servers/knowledge.py`` stays as the fallback: a server that was disconnected still catches up. Without
``AGENT_REDIS_URL`` nothing is published and the ten-second check is the only path, as before.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

CHANNEL = "kb:changed"


def _url() -> str | None:
    return os.getenv("AGENT_REDIS_URL") or None


async def publish(reason: str = "") -> bool:
    """Say ``kb_chunks`` changed. Never raises: a missed message costs at most the ten-second check."""
    url = _url()
    if not url:
        return False
    try:
        import redis.asyncio as redis

        client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        try:
            await client.publish(CHANNEL, f"{time.time():.3f} {reason}".strip())
        finally:
            await client.aclose()
        return True
    except Exception as error:  # noqa: BLE001
        logger.warning("Could not publish %s: %s", CHANNEL, type(error).__name__)
        return False


async def listen(on_change: Callable[[], None], *, retry_seconds: float = 5.0, client: Any = None) -> None:
    """Call *on_change* for every message on :data:`CHANNEL`, reconnecting after a failure; forever."""
    url = _url()
    if not url and client is None:
        return
    import redis.asyncio as redis

    while True:
        conn = client or redis.Redis.from_url(url, socket_connect_timeout=1.0, health_check_interval=30)
        try:
            pubsub = conn.pubsub()
            await pubsub.subscribe(CHANNEL)
            on_change()  # changes made while we were not listening
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    on_change()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - the stamp check covers the gap
            logger.info("%s listener reconnecting: %s", CHANNEL, type(error).__name__)
        if client is not None:
            return
        await asyncio.sleep(retry_seconds)
