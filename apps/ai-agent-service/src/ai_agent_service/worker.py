"""The after-call worker: ``python -m ai_agent_service.worker``.

Reads the jobs queue (``JOBS_QUEUE_URL``, SQS) and, for each ended call, runs ``after_call`` (MemoryAgent,
QaAgent) through ``harness.remember``; every minute it also runs the sweep of ``runtime/jobs.py`` (idle and
closed calls hung up, unremembered calls finished). The API process sends the messages and no longer does
either job, so a long memory write never shares a CPU with a customer's turn.

A message is deleted once ``remember`` returns, whatever its status: a failed ``after_call`` is marked on the
call's row and the sweep runs it again, as the API did. Only an error that escapes ``remember`` (the database
gone, the MCP servers down) leaves the message on the queue, to come back after its visibility timeout and go
to the dead-letter queue after the queue's ``maxReceiveCount``. Redelivery is safe: ``remember`` takes a lease
on the row, and a call already remembered is skipped.

Scaling: KEDA on the queue's length (``infra/kubernetes/overlays/production/after-call-worker.yaml``), from one
replica up. Not zero: the sweep lives here, and a call the customer simply left sends no message, so only the
sweep hangs it up.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from types import SimpleNamespace
from typing import Any

from src.core.service_runtime import configure_service

from .mcp import client as mcp_client
from .runtime import db, harness, jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logger = logging.getLogger("ai_agent_service.worker")

# Messages taken per receive and run side by side; the API's model rate limits still apply per process.
BATCH = int(os.getenv("WORKER_BATCH", "5"))
WAIT_SECONDS = 20  # SQS long polling: one empty receive costs one request per 20 s


async def handle(body: str) -> dict[str, Any]:
    """Run one job. Raises only when the job could not run at all (and should come back)."""
    try:
        job = json.loads(body)
        kind, call_id = job["type"], int(job["call_id"])
    except (ValueError, KeyError, TypeError):
        logger.error("Dropping a malformed job: %.200s", body)
        return {"status": "dropped", "reason": "malformed"}
    if kind != jobs.AFTER_CALL:
        logger.error("Dropping a job of unknown type %r", kind)
        return {"status": "dropped", "reason": f"unknown type {kind}"}
    result = await harness.remember(call_id)
    logger.info("after_call %s: %s", call_id, result.get("status", "done"))
    return result


async def _one(sqs: Any, url: str, item: dict[str, Any]) -> None:
    try:
        await handle(item["Body"])
    except Exception:  # noqa: BLE001 - left on the queue: redelivered, then dead-lettered
        logger.exception("Job failed, left on the queue: %.200s", item.get("Body"))
        return
    await asyncio.to_thread(sqs.delete_message, QueueUrl=url, ReceiptHandle=item["ReceiptHandle"])


async def consume(stop: asyncio.Event) -> None:
    """Receive, run and delete until ``stop`` is set; the batch in hand finishes first."""
    sqs, url = jobs.client(), jobs.queue_url()
    while not stop.is_set():
        try:
            reply = await asyncio.to_thread(sqs.receive_message, QueueUrl=url, MaxNumberOfMessages=BATCH,
                                            WaitTimeSeconds=WAIT_SECONDS)
        except Exception:  # noqa: BLE001 - the queue unreachable: wait and try again
            logger.exception("Could not read the jobs queue")
            await asyncio.sleep(5)
            continue
        items = reply.get("Messages") or []
        if items:
            await asyncio.gather(*(_one(sqs, url, item) for item in items))


async def main() -> None:
    if not jobs.queued():
        raise SystemExit("JOBS_QUEUE_URL is not set: without a queue the API runs after_call itself")
    app = SimpleNamespace(state=SimpleNamespace())
    database = configure_service(app)  # the platform tables: which conversations Sales closed
    await db.init_db()
    await db.init_checkpointer()
    await harness.ready()
    logger.info("Worker ready on %s", jobs.queue_url())

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(getattr(signal, name), stop.set)
        except (NotImplementedError, AttributeError, ValueError):  # Windows: Ctrl+C still stops the process
            pass

    sweeping = harness.spawn(_sweep_now_and_forever(app))
    try:
        await consume(stop)
    finally:
        sweeping.cancel()
        await asyncio.gather(sweeping, return_exceptions=True)
        await mcp_client.close_all()
        await db.close_pool()
        database.engine.dispose()
        logger.info("Worker stopped")


async def _sweep_now_and_forever(app: Any) -> None:
    """Once at start (calls left pending while no worker ran), then every minute."""
    try:
        await jobs.sweep(app)
    except Exception:  # noqa: BLE001 - the loop tries again
        logger.exception("Call sweep failed")
    await jobs.sweep_forever(app)


if __name__ == "__main__":
    asyncio.run(main())
