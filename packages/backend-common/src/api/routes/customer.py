import secrets
from fastapi import APIRouter, Request
from sqlalchemy import select, delete
from src.commerce.service import OrderService
from src.db.models import (
    Conversation,
    Message,
    Customer,
    CustomerIdentity,
    CustomerAccess,
    ProfileFact,
    Episode,
    Order,
    Feedback,
    Proposal,
    Handoff,
    TurnTrace,
    Outbox,
    now,
)
from src.memory.service import MemoryService
from src.db.models import Challenge, ToolExecution
from .shared import bearer, resources

router = APIRouter(prefix="/api")


@router.get("/customer/profile")
def profile(request: Request):
    db, security = resources(request)
    with db:
        customer_id = security.customer(db, bearer(request))
        return MemoryService(db).profile(customer_id)


@router.get("/customer/orders")
def customer_orders(request: Request):
    db, security = resources(request)
    with db:
        customer_id = security.customer(db, bearer(request))
        return [
            OrderService(db, security).serialize(o)
            for o in db.scalars(
                select(Order)
                .where(Order.customer_id == customer_id)
                .order_by(Order.created_at.desc())
                .limit(100)
            )
        ]


@router.delete("/customer/data")
def forget(request: Request):
    db, security = resources(request)
    with db:
        customer_id = security.customer(db, bearer(request))
        customer = db.scalar(
            select(Customer).where(Customer.id == customer_id).with_for_update()
        )
        customer.full_name = None
        customer.region = None
        customer.deleted_at = now()
        db.execute(delete(ProfileFact).where(ProfileFact.customer_id == customer_id))
        db.execute(delete(Episode).where(Episode.customer_id == customer_id))
        for ident in db.scalars(
            select(CustomerIdentity).where(CustomerIdentity.customer_id == customer_id)
        ):
            ident.revoked_at = now()
            ident.encrypted_value = None
            ident.identifier_digest = secrets.token_hex(32)
        for access in db.scalars(
            select(CustomerAccess).where(CustomerAccess.customer_id == customer_id)
        ):
            access.revoked_at = now()
        for conv in db.scalars(
            select(Conversation).where(Conversation.customer_id == customer_id)
        ):
            db.execute(delete(Challenge).where(Challenge.conversation_id == conv.id))
            for msg in db.scalars(
                select(Message).where(Message.conversation_id == conv.id)
            ):
                for proposal in db.scalars(
                    select(Proposal).where(Proposal.source_message_id == msg.id)
                ):
                    proposal.candidate = {"deleted": True}
                for trace in db.scalars(
                    select(TurnTrace).where(TurnTrace.message_id == msg.id)
                ):
                    for execution in db.scalars(
                        select(ToolExecution).where(ToolExecution.trace_id == trace.id)
                    ):
                        execution.redacted_arguments = {"deleted": True}
                        execution.redacted_result = {"deleted": True}
                msg.body = "[deleted]"
                msg.normalized_text = None
                msg.asr_text = None
            for handoff in db.scalars(
                select(Handoff).where(Handoff.conversation_id == conv.id)
            ):
                handoff.brief = {"deleted": True}
            for feedback_record in db.scalars(
                select(Feedback).where(Feedback.conversation_id == conv.id)
            ):
                feedback_record.comment = None
            conv.customer_id = None
            conv.anonymous_session_digest = secrets.token_hex(32)
            request.app.state.working.clear(str(conv.id))
        for order in db.scalars(select(Order).where(Order.customer_id == customer_id)):
            order.encrypted_shipping_address = security.encrypt("[deleted]")
        db.add(
            Outbox(
                event_type="identity.customer.deleted",
                aggregate_id=customer.id,
                payload={"customer_id": str(customer.id)},
            )
        )
        db.commit()
        return {
            "status": "personal data deleted; financial records retained without address"
        }
