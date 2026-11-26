"""Work that runs after a call, away from the customer's turns.

Two modes, chosen by ``JOBS_QUEUE_URL``:

- **unset** (local, tests, the evaluation runner): hanging up starts ``after_call`` as a task in the API's own
  process, and the API runs the one-minute sweep itself, as before.
- **set** (a deployment): hanging up sends one message to that SQS queue and returns. ``ai_agent_service.worker``
  reads the queue, runs ``after_call`` (MemoryAgent, QaAgent) and the sweep, and scales on the queue's length
  (KEDA). The API process then only answers turns.

The database stays the source of truth. A call that ended is marked ``memory_status = 'pending'`` before the
message is sent, and ``harness.remember`` takes a lease on the row, so a message sent twice, delivered twice, or
never sent at all leaves the same result: the sweep finds every ended call that is not remembered yet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

AFTER_CALL = "after_call"
SWEEP_SECONDS = 60
# One sweep at a time across all workers (and the API, in the in-process mode): pg_try_advisory_lock's key.
SWEEP_LOCK = 0x7A6A_0001

_client: Any = None


def queue_url() -> str | None:
    return os.getenv("JOBS_QUEUE_URL") or None


def queued() -> bool:
    """Whether after-call work goes to the queue (a deployment) or runs in this process."""
    return queue_url() is not None


def client() -> Any:
    """The SQS client, made on first use; boto3 is needed only where the queue is used."""
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("sqs", region_name=os.getenv("AWS_REGION") or None,
                               endpoint_url=os.getenv("JOBS_QUEUE_ENDPOINT") or None)
    return _client


def set_client(value: Any) -> None:
    """Tests: a stand-in for the SQS client."""
    global _client
    _client = value


def message(call_id: int) -> str:
    return json.dumps({"type": AFTER_CALL, "call_id": int(call_id)})


async def after_call(call_id: int) -> None:
    """Remember an ended call: send it to the worker, or run it here when there is no queue."""
    from . import harness

    if not queued():
        harness.spawn(harness.remember(call_id))
        return
    try:
        await asyncio.to_thread(client().send_message, QueueUrl=queue_url(), MessageBody=message(call_id))
    except Exception:  # noqa: BLE001 - the row stays pending; the worker's sweep picks it up within a minute
        logger.exception("after_call %s: could not reach the queue, left for the sweep", call_id)


async def sweep(app: Any) -> bool:
    """Hang up idle or closed calls, then remember ended calls that are not yet remembered.

    Returns False when another process holds the sweep. Every step is idempotent, so the lock only saves work."""
    from . import calls, harness, platform
    from .db import connection

    async with connection() as conn:
        held = (await (await conn.execute("SELECT pg_try_advisory_lock(%s) AS held", (SWEEP_LOCK,))).fetchone())["held"]
        if not held:
            return False
        try:
            open_ids = await calls.open_conversation_ids()
            closed = await platform.closed_conversations(app, open_ids)
            await calls.reconcile(closed)
            await harness.remember_unfinished()
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (SWEEP_LOCK,))
    return True


async def sweep_forever(app: Any, every: float = SWEEP_SECONDS) -> None:
    while True:
        await asyncio.sleep(every)
        try:
            await sweep(app)
        except Exception:  # noqa: BLE001 - try again next minute
            logger.exception("Call sweep failed")
