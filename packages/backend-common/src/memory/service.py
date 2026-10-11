import json
import time
import threading
import os
from sqlalchemy import select
from src.db.models import (
    ProfileFact,
    Customer,
    Episode,
    Conversation,
    Message,
    TurnTrace,
    ToolExecution,
    now,
)


class WorkingMemory:
    def __init__(self, redis_url=""):
        self.local = {}
        self.lock = threading.Lock()
        self.redis = None
        if redis_url:
            import redis

            self.redis = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=2,
                **(
                    {"ssl_ca_certs": os.environ["REDIS_CA_CERTS"]}
                    if redis_url.startswith("rediss://") and os.getenv("REDIS_CA_CERTS")
                    else {}
                ),
            )

    def get(self, conversation_id):
        key = "working:" + conversation_id
        if self.redis:
            raw = self.redis.get(key)
            return json.loads(raw) if raw else {}
        with self.lock:
            value, expiry = self.local.get(key, ({}, 0))
            if expiry < time.time():
                self.local.pop(key, None)
                return {}
            return dict(value)

    def put(self, conversation_id, value):
        key = "working:" + conversation_id
        if self.redis:
            self.redis.setex(key, 3600, json.dumps(value))
        else:
            with self.lock:
                self.local[key] = (dict(value), time.time() + 3600)

    def clear(self, conversation_id):
        key = "working:" + conversation_id
        if self.redis:
            self.redis.delete(key)
        else:
            with self.lock:
                self.local.pop(key, None)


class MemoryService:
    def __init__(self, db):
        self.db = db

    def profile(self, customer_id):
        if not customer_id:
            return {}
        return {
            f.slot: f.value
            for f in self.db.scalars(
                select(ProfileFact).where(
                    ProfileFact.customer_id == customer_id,
                    ProfileFact.valid_to.is_(None),
                )
            )
        }

    def remember(self, customer_id, message, slot, value):
        self.db.scalar(
            select(Customer).where(Customer.id == customer_id).with_for_update()
        )
        conv = self.db.get(Conversation, message.conversation_id)
        if conv.customer_id != customer_id or message.speaker != "customer":
            raise ValueError("Memory source does not belong to customer")
        old = self.db.scalar(
            select(ProfileFact).where(
                ProfileFact.customer_id == customer_id,
                ProfileFact.slot == slot,
                ProfileFact.valid_to.is_(None),
            )
        )
        if old and old.value == value:
            return
        if old:
            old.valid_to = now()
            self.db.flush()
        self.db.add(
            ProfileFact(
                customer_id=customer_id,
                slot=slot,
                value=value,
                source_message_id=message.id,
                confidence=1,
                consent_at=now(),
                supersedes_id=old.id if old else None,
            )
        )
        self.db.flush()

    def brief(self, conversation, working=None):
        profile = self.profile(conversation.customer_id)
        episodes = (
            self.db.scalars(
                select(Episode)
                .where(Episode.customer_id == conversation.customer_id)
                .order_by(Episode.created_at.desc())
                .limit(3)
            ).all()
            if conversation.customer_id
            else []
        )
        quotes = self.db.scalars(
            select(ToolExecution)
            .join(TurnTrace, TurnTrace.id == ToolExecution.trace_id)
            .join(Message, Message.id == TurnTrace.message_id)
            .where(
                Message.conversation_id == conversation.id,
                ToolExecution.tool_name.in_(["catalog.get", "promotion.lookup"]),
                ToolExecution.status == "success",
            )
            .order_by(ToolExecution.observed_at.desc())
            .limit(3)
        ).all()
        verified = [
            {
                "data": q.redacted_result,
                "observed_at": q.observed_at.isoformat(),
                "historical_only": True,
            }
            for q in quotes
        ]
        return {
            "customer_id": str(conversation.customer_id)
            if conversation.customer_id
            else None,
            "preferences": profile,
            "previous_outcomes": [e.structured_context for e in episodes],
            "current_intent": (working or {}).get("route"),
            "active_sku": (working or {}).get("active_sku"),
            "verified_facts": verified,
            "open_questions": [],
            "recommended_next_action": "Refresh current price and stock before making an offer",
        }

    def summarize(self, conversation):
        if not conversation.customer_id or self.db.scalar(
            select(Episode).where(Episode.conversation_id == conversation.id)
        ):
            return
        traces = self.db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.speaker == "assistant",
            )
            .order_by(Message.sequence.desc())
            .limit(3)
        ).all()
        context = {
            "preferences": self.profile(conversation.customer_id),
            "outcome": conversation.status,
        }
        self.db.add(
            Episode(
                customer_id=conversation.customer_id,
                conversation_id=conversation.id,
                summary=" | ".join(m.body[:300] for m in reversed(traces))
                or "No assistant turns",
                structured_context=context,
            )
        )
