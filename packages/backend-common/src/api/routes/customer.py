import secrets
import hmac
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
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
from src.db.models import CartItem, Challenge, ToolExecution, ProcessedEvent
from src.identity.accounts import AccountService
from .shared import bearer, resources

router = APIRouter(prefix="/api")


# ── storefront accounts (src.identity.accounts) ────────────────────────


class Registration(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=6, max_length=20)
    password: str = Field(max_length=128)
    email: str | None = Field(default=None, max_length=254)


class CodeInput(BaseModel):
    challenge_id: UUID
    code: str = Field(min_length=4, max_length=10)


class LoginInput(BaseModel):
    phone: str = Field(min_length=1, max_length=20)
    password: str = Field(max_length=128)


class PhoneInput(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


class ResetInput(CodeInput):
    password: str = Field(max_length=128)


class ProfileInput(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


class CartLineInput(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(ge=1, le=99)


class CartInput(BaseModel):
    items: list[CartLineInput] = Field(max_length=60)


def _accounts(request, run, *, commit=True):
    db, security = resources(request)
    with db:
        result = run(AccountService(db, security), db, security)
        if commit:
            db.commit()
        return result


@router.post("/customer/register/start")
def register_start(data: Registration, request: Request):
    return _accounts(request, lambda a, db, s: a.register_start(data.full_name, data.phone, data.password, data.email))


@router.post("/customer/register/verify")
def register_verify(data: CodeInput, request: Request):
    return _accounts(request, lambda a, db, s: a.register_verify(data.challenge_id, data.code))


@router.post("/customer/login")
def customer_login(data: LoginInput, request: Request):
    return _accounts(request, lambda a, db, s: a.login(data.phone, data.password))


@router.post("/customer/password/reset/start")
def reset_start(data: PhoneInput, request: Request):
    return _accounts(request, lambda a, db, s: a.reset_start(data.phone))


@router.post("/customer/password/reset/verify")
def reset_verify(data: ResetInput, request: Request):
    return _accounts(request, lambda a, db, s: a.reset_verify(data.challenge_id, data.code, data.password))


@router.post("/customer/logout")
def customer_logout(request: Request):
    return _accounts(request, lambda a, db, s: a.logout(bearer(request)))


@router.get("/customer/me")
def me(request: Request):
    return _accounts(request, lambda a, db, s: a.me(s.customer(db, bearer(request))), commit=False)


@router.patch("/customer/me")
def update_me(data: ProfileInput, request: Request):
    return _accounts(request, lambda a, db, s: a.update_me(s.customer(db, bearer(request)), data.full_name, data.email))


@router.post("/customer/password")
def change_password(data: PasswordChange, request: Request):
    token = bearer(request)
    return _accounts(request, lambda a, db, s: a.change_password(
        s.customer(db, token), data.current_password, data.new_password, token))


@router.get("/customer/cart")
def get_cart(request: Request):
    return _accounts(request, lambda a, db, s: {"items": a.cart(s.customer(db, bearer(request)))}, commit=False)


@router.put("/customer/cart")
def put_cart(data: CartInput, request: Request):
    return _accounts(request, lambda a, db, s: {"items": a.replace_cart(
        s.customer(db, bearer(request)), [line.model_dump() for line in data.items])})


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


@router.get("/customer/orders/by-key/{key}")
def order_by_key(key: str, request: Request):
    """Recover a checkout whose HTTP reply was lost, scoped to the authenticated customer."""
    if not 8 <= len(key) <= 100:
        raise HTTPException(422, "Invalid idempotency key")
    db, security = resources(request)
    with db:
        customer_id = security.customer(db, bearer(request))
        db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
        order = db.scalar(select(Order).where(Order.customer_id == customer_id,
                          Order.idempotency_key == security.digest(customer_id + ":" + key)))
        if order is None:
            raise HTTPException(404, "Order not found")
        return OrderService(db, security).serialize(order)


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
        customer.password_hash = None
        db.execute(delete(CartItem).where(CartItem.customer_id == customer_id))
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
        conversation_ids = []
        for conv in db.scalars(
            select(Conversation).where(Conversation.customer_id == customer_id)
        ):
            conversation_ids.append(str(conv.id))
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
        event = Outbox(
                event_type="identity.customer.deleted",
                aggregate_id=customer.id,
                payload={"customer_id": str(customer.id), "conversation_ids": conversation_ids},
            )
        db.add(event)
        db.commit()
        return {
            "status": "personal data deleted; financial records retained without address",
            "agent_data_status": "pending",
            "deletion_id": str(event.id),
            "deletion_token": security.digest("deletion-status:" + str(event.id)),
        }


@router.get("/customer/deletions/{request_id}")
def deletion_status(request_id: UUID, request: Request):
    db, security = resources(request)
    expected = security.digest("deletion-status:" + str(request_id))
    if not hmac.compare_digest(bearer(request), expected):
        raise HTTPException(403, "Invalid deletion receipt")
    with db:
        event = db.get(Outbox, str(request_id))
        if event is None or event.event_type != "identity.customer.deleted":
            raise HTTPException(404, "Deletion not found")
        done = db.get(ProcessedEvent, str(request_id)) is not None
        return {"status": "deleted" if done else "pending"}
