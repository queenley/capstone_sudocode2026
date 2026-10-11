from sqlalchemy import select
from src.messaging.worker import tick
from src.db.models import Episode, ProcessedEvent
from src.evaluation.metrics import ratio, speech_metrics
from conftest import conversation, identify


def test_outbox_worker_deduplicates(client):
    c, h = conversation(client)
    identify(client, c, h)
    client.post(f"/api/conversations/{c}/end", headers=h, json={})
    processed = tick(client.app.state.database)
    assert processed >= 1
    assert tick(client.app.state.database) == 0
    with client.app.state.database.sessions() as db:
        assert len(db.scalars(select(ProcessedEvent)).all()) == processed
        assert db.scalar(select(Episode).where(Episode.conversation_id == c))


def test_speech_metrics_and_no_evidence():
    metrics = speech_metrics("SKU A price 100", "SKU B price 100", ["A", "100"])
    assert metrics["wer"]["value"] == 0.25
    assert metrics["entity_accuracy"]["value"] == 0.5
    assert ratio(0, 0)["value"] is None
