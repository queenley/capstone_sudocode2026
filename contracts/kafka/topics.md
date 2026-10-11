# Kafka topic ownership

The outbox relay routes events to the topic owned by the domain that changed. It can also mirror events to `telesales.domain.events` during consumer migration; set `KAFKA_LEGACY_TOPIC_MIRROR=false` after old consumers move.

| Topic | Event types | Owner |
|---|---|---|
| `telesales.identity.events` | `identity.customer.verified`, `identity.customer.deleted`, `identity.staff.created`, `identity.staff.disabled` | Identity |
| `telesales.sales.events` | `conversation.created`, `conversation.ended`, `conversation.claimed`, `conversation.transferred`, `handoff.requested`, `feedback.created`, `improvement.reviewed` | Sales |
| `telesales.commerce.events` | `order.created`, `order.cancelled` | Commerce |
| `telesales.ai-agent.events` | `knowledge_gap.created` | AI Agent |

Run one relay/consumer process per owner with `python -m src.messaging.worker --service <owner>`. Each process claims only its event types, publishes to its owner's topic, and uses a separate consumer group. The database outbox and `processed_events` table are still shared during this migration phase; the relay already routes topics by owner so they can be moved with each service database later.

All events use the envelope schema in `event-envelope.schema.json`. Consumers must use the event ID for idempotency. The legacy mirror should be disabled only after existing consumers have switched to the domain topics.
