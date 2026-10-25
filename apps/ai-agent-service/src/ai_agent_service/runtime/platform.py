"""The agent's touch points with platform-owned data, in one place.

Transitional, as ``docs/architecture/microservices-target-structure.md``
describes: Sales owns conversations, messages and handoffs, and the shared
PostgreSQL still holds them. Until Sales exposes these as APIs/events, the AI
service:

* authorises a turn with the conversation token (backend-common ``Security``);
* appends the customer-visible copy of each turn to ``conversation.messages``
  (masked, as before), so the buyer page and the staff workspace show the chat;
* records an assistant-initiated handoff as a platform ``Handoff`` and moves the
  conversation to ``handed_off``, so the staff queue picks it up;
* reads which conversations Sales has closed, so their calls are remembered.

Everything here is synchronous SQLAlchemy run in a worker thread; the agent's
own state is in its schema (``runtime.db``) and never written here.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from src.db.models import Conversation, Customer, CustomerIdentity, Handoff, Message, Outbox
from src.security.service import mask


@dataclass(frozen=True)
class ConversationView:
    id: str
    status: str
    channel: str
    customer_id: str | None


def _authorize(app: Any, conversation_id: str, token: str) -> ConversationView:
    with app.state.database.sessions() as db:
        conv = app.state.security.conversation(db, conversation_id, token)
        return ConversationView(str(conv.id), conv.status, conv.channel, conv.customer_id)


async def authorize(app: Any, conversation_id: str, token: str) -> ConversationView:
    """The conversation, if the token opens it (404 otherwise, from ``Security``)."""
    return await asyncio.to_thread(_authorize, app, conversation_id, token)


def _open_channel(app: Any, channel: str) -> str:
    with app.state.database.sessions() as db:
        # No browser holds this conversation: its token is never handed out,
        # only its digest is stored (as Sales does for a web conversation).
        conv = Conversation(customer_id=None, channel=channel,
                            anonymous_session_digest=app.state.security.digest(secrets.token_urlsafe(32)))
        db.add(conv)
        db.flush()
        db.add(Outbox(event_type="conversation.created", aggregate_id=conv.id,
                      payload={"conversation_id": str(conv.id), "channel": channel}))
        db.commit()
        return str(conv.id)


async def open_channel_conversation(app: Any, channel: str) -> str:
    """A new platform conversation for a channel the agent serves itself (Zalo)."""
    return await asyncio.to_thread(_open_channel, app, channel)


def _view(app: Any, conversation_id: str) -> ConversationView | None:
    with app.state.database.sessions() as db:
        conv = db.get(Conversation, conversation_id)
        return ConversationView(str(conv.id), conv.status, conv.channel, conv.customer_id) if conv else None


async def view(app: Any, conversation_id: str) -> ConversationView | None:
    """The conversation by id, without a token: only for channels the agent owns."""
    return await asyncio.to_thread(_view, app, conversation_id)


def _verified_phone(app: Any, customer_id: str) -> str | None:
    with app.state.database.sessions() as db:
        identity = db.scalar(
            select(CustomerIdentity)
            .where(CustomerIdentity.customer_id == customer_id, CustomerIdentity.kind == "phone",
                   CustomerIdentity.verified_at.is_not(None), CustomerIdentity.revoked_at.is_(None),
                   CustomerIdentity.encrypted_value.is_not(None))
            .order_by(CustomerIdentity.verified_at.desc())
        )
        return app.state.security.decrypt(identity.encrypted_value) if identity else None


async def verified_phone(app: Any, customer_id: str) -> str | None:
    """The phone number the customer proved with a one-time code (Identity), if any."""
    return await asyncio.to_thread(_verified_phone, app, customer_id)


def _account_name(app: Any, customer_id: str) -> str | None:
    with app.state.database.sessions() as db:
        return db.scalar(select(Customer.full_name).where(Customer.id == customer_id, Customer.deleted_at.is_(None)))


async def account_name(app: Any, customer_id: str) -> str | None:
    """The full name the customer gave their website account (or at the phone check)."""
    return await asyncio.to_thread(_account_name, app, customer_id)


def _customer_region(app: Any, conversation_id: str) -> str | None:
    with app.state.database.sessions() as db:
        conv = db.get(Conversation, conversation_id)
        customer = db.get(Customer, conv.customer_id) if conv and conv.customer_id else None
        return customer.region if customer is not None and customer.deleted_at is None else None


async def customer_region(app: Any, conversation_id: str) -> str | None:
    """bac, trung or nam for the conversation's verified customer: from the delivery
    address of their latest order (Commerce, ``core/regions.py``); None before any."""
    return await asyncio.to_thread(_customer_region, app, conversation_id)


def _append(app: Any, conversation_id: str, lines: list[tuple[str, str]]) -> None:
    with app.state.database.sessions() as db:
        conv = db.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        if conv is None:
            return
        sequence = db.scalar(select(func.max(Message.sequence)).where(Message.conversation_id == conv.id)) or 0
        for speaker, text in lines:
            if not text:
                continue
            sequence += 1
            db.add(Message(conversation_id=conv.id, sequence=sequence, speaker=speaker, body=mask(text)))
        db.commit()


async def append_messages(app: Any, conversation_id: str, *, customer: str | None, assistant: str | None) -> None:
    """The customer-visible transcript, masked like every platform message."""
    lines = [("customer", customer or ""), ("assistant", assistant or "")]
    await asyncio.to_thread(_append, app, conversation_id, lines)


async def append_staff_message(app: Any, conversation_id: str, text: str) -> None:
    """A consultant's reply from the agent console, shown in the chat as the sales team's."""
    await asyncio.to_thread(_append, app, conversation_id, [("agent", text)])


def _handoff(app: Any, conversation_id: str, reason: str, brief: dict[str, Any]) -> None:
    with app.state.database.sessions() as db:
        conv = db.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        if conv is None or conv.status != "open":
            return
        handoff = Handoff(conversation_id=conv.id, from_actor_id="assistant", reason=reason, brief=brief)
        db.add(handoff)
        conv.status = "handed_off"
        db.flush()
        db.add(Outbox(event_type="handoff.requested", aggregate_id=conv.id,
                      payload={"conversation_id": str(conv.id), "handoff_id": str(handoff.id), "from": "assistant"}))
        db.commit()


async def record_handoff(app: Any, conversation_id: str, *, reason: str, brief: dict[str, Any]) -> None:
    """The assistant handed over (``handoff.transfer``): the staff queue must see it."""
    await asyncio.to_thread(_handoff, app, conversation_id, reason, brief)


def _closed(app: Any, conversation_ids: list[str]) -> set[str]:
    if not conversation_ids:
        return set()
    with app.state.database.sessions() as db:
        rows = db.execute(
            select(Conversation.id).where(Conversation.id.in_(conversation_ids), Conversation.status == "closed")
        ).all()
        return {str(row[0]) for row in rows}


async def closed_conversations(app: Any, conversation_ids: list[str]) -> set[str]:
    return await asyncio.to_thread(_closed, app, conversation_ids)
