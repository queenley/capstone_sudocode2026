from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select, func
from src.db.models import (
    Conversation,
    Message,
    ProfileFact,
    Handoff,
    now,
)
from src.memory.service import MemoryService
from src.security.service import mask
from src.db.models import StaffUser, AuditLog, Outbox
from .shared import staff
from src.api.schemas import HumanMessage, TransferInput

router = APIRouter(prefix="/api")


@router.get("/staff/agents")
def available_agents(request: Request):
    staff(request, {"agent", "admin"})
    with request.app.state.database.sessions() as db:
        return [
            {"id": str(u.id), "username": u.username}
            for u in db.scalars(
                select(StaffUser).where(
                    StaffUser.active.is_(True), StaffUser.role == "agent"
                )
            )
        ]


@router.post("/staff/conversations/{conversation_id}/transfer")
def transfer(conversation_id: UUID, data: TransferInput, request: Request):
    role = staff(request, {"agent", "admin"})
    with request.app.state.database.sessions() as db:
        conv = db.scalar(
            select(Conversation)
            .where(Conversation.id == str(conversation_id))
            .with_for_update()
        )
        if (
            not conv
            or conv.status != "handed_off"
            or (conv.assigned_actor_id != request.state.actor_id and role != "admin")
        ):
            raise HTTPException(
                409, "Only the assigned employee can transfer this conversation"
            )
        if data.to_actor_id:
            target = db.get(StaffUser, str(data.to_actor_id))
            if not target or not target.active or target.role != "agent":
                raise HTTPException(422, "Target must be an active telesales employee")
        brief = MemoryService(db).brief(
            conv, request.app.state.working.get(str(conv.id))
        )
        db.add(
            Handoff(
                conversation_id=conv.id,
                from_actor_id=conv.assigned_actor_id,
                to_actor_id=str(data.to_actor_id) if data.to_actor_id else "assistant",
                reason=data.reason,
                brief=brief,
            )
        )
        conv.assigned_actor_id = str(data.to_actor_id) if data.to_actor_id else None
        conv.status = "handed_off" if data.to_actor_id else "open"
        db.add(
            AuditLog(
                actor_id=request.state.actor_id,
                action="conversation.transferred",
                resource_id=str(conv.id),
            )
        )
        db.add(
            Outbox(
                event_type="conversation.transferred",
                aggregate_id=conv.id,
                payload={
                    "conversation_id": str(conv.id),
                    "assigned_actor_id": conv.assigned_actor_id,
                    "status": conv.status,
                },
            )
        )
        db.commit()
        return {"status": conv.status}


@router.get("/staff/conversations")
def inbox(request: Request):
    staff(request, {"admin", "agent"})
    with request.app.state.database.sessions() as db:
        return [
            {
                "id": str(c.id),
                "status": c.status,
                "channel": c.channel,
                "customer_id": c.customer_id,
                "assigned_actor": c.assigned_actor_id,
            }
            for c in db.scalars(
                select(Conversation).order_by(Conversation.started_at.desc()).limit(100)
            )
        ]


@router.get("/staff/conversations/{conversation_id}")
def staff_conversation(conversation_id: UUID, request: Request):
    staff(request, {"admin", "agent"})
    with request.app.state.database.sessions() as db:
        conv = db.get(Conversation, str(conversation_id))
        if not conv:
            raise HTTPException(404, "Conversation not found")
        return {
            "brief": MemoryService(db).brief(
                conv, request.app.state.working.get(str(conv.id))
            ),
            "messages": [
                {"speaker": m.speaker, "text": m.body}
                for m in db.scalars(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.sequence)
                )
            ],
            "memory_timeline": [
                {
                    "slot": f.slot,
                    "value": f.value,
                    "current": f.valid_to is None,
                    "source_message_id": str(f.source_message_id),
                }
                for f in db.scalars(
                    select(ProfileFact)
                    .where(ProfileFact.customer_id == conv.customer_id)
                    .order_by(ProfileFact.valid_from)
                )
            ]
            if conv.customer_id
            else [],
        }


@router.post("/staff/conversations/{conversation_id}/claim")
def claim(conversation_id: UUID, request: Request):
    role = staff(request, {"admin", "agent"})
    with request.app.state.database.sessions() as db:
        conv = db.scalar(
            select(Conversation)
            .where(Conversation.id == str(conversation_id))
            .with_for_update()
        )
        if not conv or conv.status == "closed":
            raise HTTPException(409, "Conversation is unavailable")
        if (
            conv.assigned_actor_id
            and conv.assigned_actor_id != request.state.actor_id
            and role != "admin"
        ):
            raise HTTPException(409, "Conversation is assigned to another employee")
        conv.status = "handed_off"
        conv.assigned_actor_id = request.state.actor_id
        handoff = db.scalar(
            select(Handoff)
            .where(Handoff.conversation_id == conv.id)
            .order_by(Handoff.created_at.desc())
        )
        if handoff:
            handoff.to_actor_id = request.state.actor_id
            handoff.accepted_at = now()
        db.add(
            Outbox(
                event_type="conversation.claimed",
                aggregate_id=conv.id,
                payload={
                    "conversation_id": str(conv.id),
                    "assigned_actor_id": request.state.actor_id,
                },
            )
        )
        db.commit()
        return {"status": conv.status}


@router.post("/staff/conversations/{conversation_id}/messages")
def human_reply(conversation_id: UUID, data: HumanMessage, request: Request):
    role = staff(request, {"admin", "agent"})
    with request.app.state.database.sessions() as db:
        conv = db.scalar(
            select(Conversation)
            .where(Conversation.id == str(conversation_id))
            .with_for_update()
        )
        if (
            not conv
            or conv.status != "handed_off"
            or conv.assigned_actor_id != request.state.actor_id
        ):
            raise HTTPException(409, "Claim the conversation before replying")
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
                speaker="agent",
                body=mask(data.message),
            )
        )
        db.commit()
        return {"sent": True}
