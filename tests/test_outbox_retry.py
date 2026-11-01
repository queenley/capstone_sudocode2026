from contextlib import contextmanager
import json
import signal
import sys
from types import SimpleNamespace

from src.core.config import Settings
from src.messaging import worker
from src.identity import deletion


def test_large_erasure_commands_are_signed_and_chunked_without_customer_text(monkeypatch):
    delivered = []
    def post(url, *, content, headers, **options):
        assert headers["X-Deletion-Signature"] == deletion.signature("fixture", content)
        delivered.append(json.loads(content))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"status": "deleted"})
    monkeypatch.setattr(deletion.httpx, "post", post)
    deletion.deliver({"id": "receipt", "payload": {"customer_id": "customer", "conversation_ids": list(range(10001)),
                                                   "private_name": "Must not be forwarded"}}, SimpleNamespace(secret="fixture"))
    assert [len(item["conversation_ids"]) for item in delivered] == [5000, 5000, 1]
    assert "private_name" not in json.dumps(delivered)


def test_worker_retries_the_failed_event_before_polling_or_committing_later_offsets(monkeypatch):
    handlers, polls, attempts, commits = {}, [], [], []
    message = SimpleNamespace(error=lambda: None, value=lambda: json.dumps({"id": "first"}))
    class Consumer:
        def __init__(self, options):
            assert options["enable.auto.commit"] is False
        def subscribe(self, topics): pass
        def poll(self, timeout):
            polls.append(True)
            assert len(polls) == 1, "A failed event must be retried before another offset is polled"
            return message
        def commit(self, *, message, asynchronous):
            commits.append(message)
            handlers[signal.SIGTERM]()
        def close(self): pass
    class Database:
        def __init__(self, url): self.engine = SimpleNamespace(dispose=lambda: None)
        @contextmanager
        def sessions(self): yield SimpleNamespace(commit=lambda: None)
    def process(db, event):
        attempts.append(event["id"])
        if len(attempts) == 1:
            raise ConnectionError("Synthetic dependency failure")
    monkeypatch.setitem(sys.modules, "confluent_kafka", SimpleNamespace(Producer=lambda options: object(), Consumer=Consumer))
    monkeypatch.setattr(worker, "Database", Database)
    monkeypatch.setattr(worker, "tick", lambda *args: None)
    monkeypatch.setattr(worker, "process", process)
    monkeypatch.setattr(worker.signal, "signal", lambda name, handler: handlers.update({name: handler}))
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    worker.run(Settings(kafka_brokers="fixture", auto_migrate=False))
    assert attempts == ["first", "first"]
    assert commits == [message]
