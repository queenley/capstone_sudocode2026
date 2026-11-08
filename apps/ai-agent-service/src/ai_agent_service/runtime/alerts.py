"""Tells the staff console, the moment it happens, that a conversation waits for a person.

The list of who waits is always read from the ``calls`` table; what this module
adds is *when* to read it again. Three signals wake the readers:

- this process changed a handoff (``wake()`` from ``calls`` and the harness);
- another process did, and said so on Kafka: ``handoff.requested`` and
  ``conversation.claimed`` on ``telesales.sales.events``, written through the
  platform's outbox (``KAFKA_BROKERS`` set);
- neither came within ``POLL_SECONDS``: read anyway. Without Kafka this is the
  only way a handoff on another instance is seen, a few seconds late.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
from typing import Any

from .db import connection

logger = logging.getLogger(__name__)

TOPIC = "telesales.sales.events"
EVENTS = {"handoff.requested", "conversation.claimed", "conversation.transferred", "conversation.ended"}
#: How long a reader waits for a signal before it reads the table anyway.
POLL_SECONDS = 5.0


class Hub:
    """A counter that readers wait on; every wake moves it on and releases them all."""

    def __init__(self) -> None:
        self.version = 0
        self.source = "polling"
        self._changed: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _event(self) -> asyncio.Event:
        loop = asyncio.get_running_loop()
        if self._changed is None or self._loop is not loop:
            self._changed = asyncio.Event()
            self._loop = loop
        return self._changed

    def wake(self) -> None:
        self.version += 1
        if self._changed is not None:
            self._changed.set()
            self._changed = None

    def wake_threadsafe(self) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self.wake)

    async def wait(self, seen: int, timeout: float = POLL_SECONDS) -> int:
        """Return once the version passes *seen*, or after *timeout*; the version then."""
        if self.version != seen:
            return self.version
        try:
            await asyncio.wait_for(self._event().wait(), timeout)
        except asyncio.TimeoutError:
            pass
        return self.version


hub = Hub()


def wake() -> None:
    hub.wake()


def is_alert(value: bytes | str | None) -> bool:
    """A Kafka message that changes who waits."""
    try:
        envelope = json.loads(value or b"")
    except (TypeError, ValueError):
        return False
    return isinstance(envelope, dict) and envelope.get("event_type") in EVENTS


def _consume(brokers: str, stop: threading.Event) -> None:
    from confluent_kafka import Consumer

    # A group of its own per process: every console instance hears every event,
    # and none takes messages from the outbox worker's group.
    consumer = Consumer({
        "bootstrap.servers": brokers,
        "group.id": f"telesales-agent-alerts-{socket.gethostname()}-{os.getpid()}",
        "auto.offset.reset": "latest",
        "enable.auto.commit": False,
    })
    consumer.subscribe([TOPIC])
    hub.source = "kafka"
    try:
        while not stop.is_set():
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                logger.warning("Handoff alerts: Kafka error %s", message.error())
                continue
            if is_alert(message.value()):
                hub.wake_threadsafe()
    finally:
        hub.source = "polling"
        consumer.close()


def start(brokers: str | None) -> threading.Event | None:
    """Listen on Kafka when there is one; without it the readers poll. Returns the stop signal."""
    hub._event()  # bind the hub to the service's event loop
    if not brokers:
        logger.info("Handoff alerts: no KAFKA_BROKERS, the console polls every %ss", POLL_SECONDS)
        return None
    try:
        import confluent_kafka  # noqa: F401
    except ImportError:
        logger.warning("Handoff alerts: confluent-kafka is not installed, the console polls")
        return None
    stop = threading.Event()

    def run() -> None:
        try:
            _consume(brokers, stop)
        except Exception:  # noqa: BLE001 - the readers keep polling
            logger.exception("Handoff alerts: Kafka listener stopped, the console polls")

    threading.Thread(target=run, name="handoff-alerts", daemon=True).start()
    return stop


async def waiting() -> list[dict[str, Any]]:
    """Calls that wait for a consultant, the longest wait first."""
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT c.*, (SELECT count(*) FROM turns t WHERE t.call_id = c.id AND t.speaker = 'customer') AS turn_count "
            "FROM calls c WHERE c.handoff_status = 'pending' AND c.ended_at IS NULL "
            "ORDER BY c.handoff_requested_at NULLS LAST, c.started_at LIMIT 50")
        return list(await cursor.fetchall())
