"""After-call work leaves the API: a queue message when JOBS_QUEUE_URL is set, a task here when it is not."""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from ai_agent_service import worker
from ai_agent_service.runtime import calls, db, harness, jobs, platform

URL = "https://sqs.ap-southeast-1.amazonaws.com/000000000000/after-call"


class FakeSqs:
    def __init__(self, batches=(), fail_send=False):
        self.sent, self.deleted, self.batches, self.fail_send = [], [], list(batches), fail_send

    def send_message(self, QueueUrl, MessageBody):
        if self.fail_send:
            raise ConnectionError("queue unreachable")
        self.sent.append((QueueUrl, MessageBody))
        return {"MessageId": "m1"}

    def receive_message(self, QueueUrl, MaxNumberOfMessages, WaitTimeSeconds):
        return {"Messages": self.batches.pop(0)} if self.batches else {}

    def delete_message(self, QueueUrl, ReceiptHandle):
        self.deleted.append(ReceiptHandle)


@pytest.fixture
def queue(monkeypatch):
    monkeypatch.setenv("JOBS_QUEUE_URL", URL)
    yield
    jobs.set_client(None)


def test_without_a_queue_the_api_remembers_the_call_itself(monkeypatch):
    monkeypatch.delenv("JOBS_QUEUE_URL", raising=False)
    started = []

    async def remember(call_id):
        started.append(call_id)

    monkeypatch.setattr(harness, "remember", remember)

    async def go():
        await jobs.after_call(7)
        await asyncio.sleep(0)

    asyncio.run(go())
    assert not jobs.queued() and started == [7]


def test_with_a_queue_hanging_up_sends_one_message_and_runs_nothing_here(monkeypatch, queue):
    sqs = FakeSqs()
    jobs.set_client(sqs)
    monkeypatch.setattr(harness, "remember", lambda call_id: pytest.fail("after_call ran in the API process"))
    asyncio.run(jobs.after_call(7))
    assert sqs.sent == [(URL, json.dumps({"type": "after_call", "call_id": 7}))]


def test_an_unreachable_queue_leaves_the_call_for_the_sweep_without_failing_the_hang_up(queue):
    jobs.set_client(FakeSqs(fail_send=True))
    asyncio.run(jobs.after_call(7))  # no exception: the row is already 'pending'


def test_the_worker_runs_after_call_and_deletes_the_message(monkeypatch, queue):
    ran = []

    async def remember(call_id):
        ran.append(call_id)
        return {"status": "done"}

    monkeypatch.setattr(harness, "remember", remember)
    sqs = FakeSqs()
    asyncio.run(worker._one(sqs, URL, {"Body": jobs.message(7), "ReceiptHandle": "r1"}))
    assert ran == [7] and sqs.deleted == ["r1"]


def test_a_failed_after_call_is_still_deleted_because_the_row_records_it(monkeypatch, queue):
    async def remember(call_id):
        return {"status": "failed", "error": "model timeout"}

    monkeypatch.setattr(harness, "remember", remember)
    sqs = FakeSqs()
    asyncio.run(worker._one(sqs, URL, {"Body": jobs.message(7), "ReceiptHandle": "r1"}))
    assert sqs.deleted == ["r1"]


def test_an_error_that_escapes_leaves_the_message_for_redelivery(monkeypatch, queue):
    async def remember(call_id):
        raise ConnectionError("database gone")

    monkeypatch.setattr(harness, "remember", remember)
    sqs = FakeSqs()
    asyncio.run(worker._one(sqs, URL, {"Body": jobs.message(7), "ReceiptHandle": "r1"}))
    assert sqs.deleted == []


@pytest.mark.parametrize("body", ["not json", json.dumps({"type": "after_call"}), json.dumps({"type": "resize", "call_id": 1})])
def test_malformed_or_unknown_jobs_are_dropped_not_retried(monkeypatch, body):
    monkeypatch.setattr(harness, "remember", lambda call_id: pytest.fail("ran a malformed job"))
    assert asyncio.run(worker.handle(body))["status"] == "dropped"


def test_the_consumer_runs_a_batch_side_by_side_and_stops_when_asked(monkeypatch, queue):
    ran = []
    stop = None

    async def remember(call_id):
        ran.append(call_id)
        if len(ran) == 2:
            stop.set()
        return {"status": "done"}

    monkeypatch.setattr(harness, "remember", remember)
    sqs = FakeSqs(batches=[[{"Body": jobs.message(1), "ReceiptHandle": "a"}, {"Body": jobs.message(2), "ReceiptHandle": "b"}]])
    jobs.set_client(sqs)

    async def go():
        nonlocal stop
        stop = asyncio.Event()
        await asyncio.wait_for(worker.consume(stop), timeout=5)

    asyncio.run(go())
    assert sorted(ran) == [1, 2] and sorted(sqs.deleted) == ["a", "b"]


class Conn:
    def __init__(self, held):
        self.held, self.sql = held, []

    async def execute(self, sql, params=None):
        self.sql.append(sql)
        held = self.held

        class Cursor:
            async def fetchone(self):
                return {"held": held}

        return Cursor()


def _patch_db(monkeypatch, conn):
    @asynccontextmanager
    async def connection():
        yield conn

    monkeypatch.setattr(db, "connection", connection)


def test_only_one_process_sweeps_at_a_time(monkeypatch):
    conn = Conn(held=False)
    _patch_db(monkeypatch, conn)
    monkeypatch.setattr(calls, "reconcile", lambda closed: pytest.fail("swept without the lock"))
    assert asyncio.run(jobs.sweep(object())) is False
    assert not any("unlock" in sql for sql in conn.sql)


def test_the_sweep_hangs_up_closed_calls_finishes_pending_ones_and_releases_the_lock(monkeypatch):
    conn = Conn(held=True)
    _patch_db(monkeypatch, conn)
    seen = {}

    async def open_ids():
        return ["c1", "c2"]

    async def closed(app, ids):
        return {"c2"}

    async def reconcile(closed_ids):
        seen["closed"] = closed_ids

    async def unfinished():
        seen["unfinished"] = True

    monkeypatch.setattr(calls, "open_conversation_ids", open_ids)
    monkeypatch.setattr(platform, "closed_conversations", closed)
    monkeypatch.setattr(calls, "reconcile", reconcile)
    monkeypatch.setattr(harness, "remember_unfinished", unfinished)
    assert asyncio.run(jobs.sweep(object())) is True
    assert seen == {"closed": {"c2"}, "unfinished": True}
    assert "pg_advisory_unlock" in conn.sql[-1]
