import secrets
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select, func
from src.commerce.schemas import OrderInput
from src.commerce.service import OrderService
from src.db.models import (
    Conversation,
    Message,
    Feedback,
    Outbox,
    now,
)
from src.identity.service import IdentityService
from src.memory.service import MemoryService
from src.security.service import mask
from .shared import bearer, resources
from src.api.schemas import (
    NewConversation,
    Identification,
    Verification,
    FeedbackInput,
    HumanMessage,
)

router = APIRouter(prefix="/api")


@router.post("/conversations/{conversation_id}/messages")
def buyer_human_message(conversation_id: UUID, data: HumanMessage, request: Request):
    db, security = resources(request)
    with db:
        conv = security.conversation(
            db, str(conversation_id), bearer(request), lock=True
        )
        if conv.status != "handed_off":
            raise HTTPException(409, "Use the chat turn endpoint while AI is active")
        sequence = (
            db.scalar(
                select(func.max(Message.sequence)).where(
                    Message.conversation_id == conv.id
                )
            )
            or 0
        ) + 1
        db.add(
            Message(
                conversation_id=conv.id,
                sequence=sequence,
                speaker="customer",
                body=mask(data.message),
            )
        )
        db.commit()
        return {"sent": True}


@router.post("/conversations", status_code=201)
def new_conversation(data: NewConversation, request: Request):
    db, security = resources(request)
    with db:
        customer_id = (
            security.customer(db, bearer(request))
            if request.headers.get("Authorization")
            else None
        )
        token = secrets.token_urlsafe(32)
        conv = Conversation(
            customer_id=customer_id,
            channel=data.channel,
            anonymous_session_digest=security.digest(token),
        )
        db.add(conv)
        db.flush()
        db.add(
            Outbox(
                event_type="conversation.created",
                aggregate_id=conv.id,
                payload={"conversation_id": str(conv.id), "channel": conv.channel},
            )
        )
        db.commit()
        return {
            "conversation_id": str(conv.id),
            "conversation_token": token,
            "customer_id": customer_id,
        }


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: UUID, request: Request):
    db, security = resources(request)
    with db:
        conv = security.conversation(db, str(conversation_id), bearer(request))
        messages = db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.sequence)
        ).all()
        return {
            "id": str(conv.id),
            "status": conv.status,
            "customer_id": conv.customer_id,
            "messages": [
                {"speaker": m.speaker, "text": m.body, "id": str(m.id)}
                for m in messages
            ],
        }


@router.post("/conversations/{conversation_id}/identity/challenge")
def identify(conversation_id: UUID, data: Identification, request: Request):
    db, security = resources(request)
    with db:
        conv = security.conversation(
            db, str(conversation_id), bearer(request), lock=True
        )
        result = IdentityService(db, security).challenge(
            conv, data.kind, data.value, data.consent
        )
        db.commit()
        return result


@router.post("/conversations/{conversation_id}/identity/verify")
def verify(conversation_id: UUID, data: Verification, request: Request):
    db, security = resources(request)
    with db:
        conv = security.conversation(
            db, str(conversation_id), bearer(request), lock=True
        )
        result = IdentityService(db, security).verify(
            conv, str(data.challenge_id), data.code, data.full_name, data.customer_token
        )
        db.commit()
        return result


@router.post("/conversations/{conversation_id}/end")
def end(conversation_id: UUID, request: Request):
    db, security = resources(request)
    with db:
        conv = security.conversation(
            db, str(conversation_id), bearer(request), lock=True
        )
        if conv.status != "closed":
            conv.status = "closed"
            conv.ended_at = now()
            db.add(
                Outbox(
                    event_type="conversation.ended",
                    aggregate_id=conv.id,
                    payload={"conversation_id": str(conv.id)},
                )
            )
            MemoryService(db).summarize(conv)
        db.commit()
        request.app.state.working.clear(str(conv.id))
        return {"status": "closed"}


@router.get("/conversations/{conversation_id}/brief")
def brief(conversation_id: UUID, request: Request):
    db, security = resources(request)
    with db:
        conv = security.conversation(db, str(conversation_id), bearer(request))
        return MemoryService(db).brief(
            conv, request.app.state.working.get(str(conv.id))
        )


@router.post("/conversations/{conversation_id}/orders", status_code=201)
def create_order(conversation_id: UUID, data: OrderInput, request: Request):
    db, security = resources(request)
    with db:
        conv = security.conversation(
            db, str(conversation_id), bearer(request), lock=True
        )
        if not conv.customer_id:
            raise HTTPException(403, "Verified customer identity is required")
        if conv.status != "open":
            raise HTTPException(409, "Conversation is not open")
        result = OrderService(db, security).create(
            conv.customer_id, conv.id, conv.channel, data
        )
        db.commit()
        return result


@router.post("/conversations/{conversation_id}/feedback", status_code=201)
def feedback(conversation_id: UUID, data: FeedbackInput, request: Request):
    db, security = resources(request)
    with db:
        conv = security.conversation(db, str(conversation_id), bearer(request))
        record = Feedback(
            conversation_id=conv.id,
            actor_id="buyer",
            rating=data.rating,
            category=data.category,
            comment=mask(data.comment),
        )
        db.add(record)
        db.flush()
        db.add(
            Outbox(
                event_type="feedback.created",
                aggregate_id=record.id,
                payload={"feedback_id": str(record.id)},
            )
        )
        db.commit()
        return {"id": str(record.id)}
