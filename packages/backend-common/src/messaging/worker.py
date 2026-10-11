import argparse
import json
import logging
import os
import signal
import time
from sqlalchemy import select
from src.core.config import Settings
from src.db.session import Database
from src.db.models import (
    Outbox,
    ProcessedEvent,
    Conversation,
    TurnTrace,
    Message,
    Proposal,
    now,
)
from src.memory.service import MemoryService

log = logging.getLogger("telesales.worker")

EVENT_OWNERS = {
    "order.created": "commerce",
    "order.cancelled": "commerce",
    "identity.customer.verified": "identity",
    "identity.customer.deleted": "identity",
    "identity.staff.created": "identity",
    "identity.staff.disabled": "identity",
    "conversation.created": "sales",
    "conversation.ended": "sales",
    "conversation.claimed": "sales",
    "conversation.transferred": "sales",
    # Written by the AI agent on Sales' behalf when it hands a conversation to staff.
    "handoff.requested": "sales",
    "feedback.created": "sales",
    "improvement.reviewed": "sales",
    "knowledge_gap.created": "ai-agent",
}
SERVICES = tuple(sorted(set(EVENT_OWNERS.values())))


def topic_for_event(event_type):
    owner = EVENT_OWNERS.get(event_type)
    if not owner:
        raise ValueError(f"No Kafka owner configured for event type: {event_type}")
    return f"telesales.{owner}.events"


def process(db, event):
    if db.get(ProcessedEvent, event["id"]):
        return False
    if event["event_type"] == "conversation.ended":
        conv = db.get(Conversation, event["payload"]["conversation_id"])
        if conv:
            MemoryService(db).summarize(conv)
            traces = db.scalars(
                select(TurnTrace)
                .join(Message, Message.id == TurnTrace.message_id)
                .where(Message.conversation_id == conv.id)
            ).all()
            errors = sum(bool(t.errors) for t in traces)
            if errors:
                db.add(
                    Proposal(
                        kind="policy_correction",
                        candidate={
                            "conversation_id": str(conv.id),
                            "tool_error_turns": errors,
                        },
                    )
                )
    db.add(ProcessedEvent(id=event["id"]))
    db.flush()
    return True


def tick(database, producer=None, service="all"):
    if service != "all" and service not in SERVICES:
        raise ValueError(f"Unknown event service: {service}")
    count = 0
    with database.sessions() as db:
        statement = select(Outbox).where(Outbox.published_at.is_(None))
        if service != "all":
            event_types = [
                event_type
                for event_type, owner in EVENT_OWNERS.items()
                if owner == service
            ]
            statement = statement.where(Outbox.event_type.in_(event_types))
        events = db.scalars(
            statement.order_by(Outbox.created_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        ).all()
        for event in events:
            envelope = {
                "id": str(event.id),
                "event_type": event.event_type,
                "aggregate_id": str(event.aggregate_id),
                "payload": event.payload,
                "version": 1,
            }
            if producer:
                errors = []
                producer.produce(
                    topic_for_event(event.event_type),
                    key=str(event.aggregate_id),
                    value=json.dumps(envelope),
                    on_delivery=lambda error, msg: (
                        errors.append(error) if error else None
                    ),
                )
                if os.getenv("KAFKA_LEGACY_TOPIC_MIRROR", "true").lower() == "true":
                    producer.produce(
                        "telesales.domain.events",
                        key=str(event.aggregate_id),
                        value=json.dumps(envelope),
                        on_delivery=lambda error, msg: (
                            errors.append(error) if error else None
                        ),
                    )
                if producer.flush(5) or errors:
                    raise RuntimeError("Kafka delivery not acknowledged")
            else:
                process(db, envelope)
            event.published_at = now()
            count += 1
        db.commit()
    return count


def run(settings=None, once=False, service="all"):
    settings = settings or Settings()
    database = Database(settings.database_url)
    if settings.auto_migrate:
        database.migrate()
    producer = consumer = None
    if settings.kafka_brokers:
        from confluent_kafka import Producer, Consumer

        producer = Producer(
            {"bootstrap.servers": settings.kafka_brokers, "enable.idempotence": True}
        )
        consumer = Consumer(
            {
                "bootstrap.servers": settings.kafka_brokers,
                "group.id": f"telesales-{service}-events-v1",
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        topics = (
            [f"telesales.{service}.events"]
            if service != "all"
            else [f"telesales.{name}.events" for name in SERVICES]
        )
        consumer.subscribe(topics)
    stop = False

    def shutdown(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        while not stop:
            try:
                tick(database, producer, service)
                if consumer:
                    message = consumer.poll(0.5)
                    if message and not message.error():
                        with database.sessions() as db:
                            process(db, json.loads(message.value()))
                            db.commit()
                        consumer.commit(message=message, asynchronous=False)
            except Exception as error:
                log.error("Worker retry: %s", type(error).__name__)
            if once:
                break
            time.sleep(1)
    finally:
        if consumer:
            consumer.close()
        database.engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--service", choices=("all",) + SERVICES, default="all")
    args = parser.parse_args()
    run(once=args.once, service=args.service)
