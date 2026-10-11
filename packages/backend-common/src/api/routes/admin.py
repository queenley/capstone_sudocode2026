from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from src.commerce.schemas import ProductInput, PromotionInput
from src.commerce.service import CatalogService
from src.db.models import (
    Proposal,
    Policy,
    Promotion,
    SKU,
    Inventory,
    Outbox,
    now,
)
from src.security.auth import password_hash
from src.db.models import StaffUser, AuditLog
from .shared import staff
from src.api.schemas import StaffInput, ReviewInput, StockInput

router = APIRouter(prefix="/api")


@router.post("/admin/users", status_code=201)
def add_user(data: StaffInput, request: Request):
    staff(request, {"admin"})
    with request.app.state.database.sessions() as db:
        user = StaffUser(
            username=data.username,
            password_hash=password_hash(data.password),
            role=data.role,
        )
        db.add(user)
        db.flush()
        db.add(
            AuditLog(
                actor_id=request.state.actor_id,
                action="user.created",
                resource_id=str(user.id),
            )
        )
        db.add(
            Outbox(
                event_type="identity.staff.created",
                aggregate_id=user.id,
                payload={"staff_id": str(user.id), "role": user.role},
            )
        )
        db.commit()
        return {
            "id": str(user.id),
            "username": user.username,
            "role": user.role,
            "active": user.active,
        }


@router.get("/admin/users")
def users(request: Request):
    staff(request, {"admin"})
    with request.app.state.database.sessions() as db:
        return [
            {
                "id": str(u.id),
                "username": u.username,
                "role": u.role,
                "active": u.active,
            }
            for u in db.scalars(select(StaffUser).order_by(StaffUser.username))
        ]


@router.delete("/admin/users/{user_id}")
def disable_user(user_id: UUID, request: Request):
    staff(request, {"admin"})
    with request.app.state.database.sessions() as db:
        user = db.get(StaffUser, str(user_id))
        if not user:
            raise HTTPException(404, "User not found")
        if str(user.id) == request.state.actor_id:
            raise HTTPException(409, "You cannot disable your current account")
        user.active = False
        db.add(
            AuditLog(
                actor_id=request.state.actor_id,
                action="user.disabled",
                resource_id=str(user.id),
            )
        )
        db.add(
            Outbox(
                event_type="identity.staff.disabled",
                aggregate_id=user.id,
                payload={"staff_id": str(user.id)},
            )
        )
        db.commit()
        return {"active": False}


@router.post("/admin/catalog", status_code=201)
def add_product(data: ProductInput, request: Request):
    staff(request, {"admin"})
    with request.app.state.database.sessions() as db:
        result = CatalogService(db).create(data)
        db.commit()
        return result


@router.put("/admin/inventory/{sku_code}")
def stock(sku_code: str, data: StockInput, request: Request):
    staff(request, {"admin"})
    with request.app.state.database.sessions() as db:
        sku = db.scalar(select(SKU).where(SKU.sku_code == sku_code))
        if not sku:
            raise HTTPException(404, "SKU not found")
        inventory = db.scalar(
            select(Inventory).where(Inventory.sku_id == sku.id).with_for_update()
        )
        if data.quantity_on_hand < inventory.reserved_quantity:
            raise HTTPException(409, "Stock cannot be below existing reservations")
        inventory.quantity_on_hand = data.quantity_on_hand
        db.commit()
        return CatalogService(db).get(sku_code)


@router.post("/admin/promotions", status_code=201)
def add_promotion(data: PromotionInput, request: Request):
    staff(request, {"admin"})
    try:
        start, end = (
            datetime.fromisoformat(data.starts_at),
            datetime.fromisoformat(data.ends_at),
        )
        if not start.tzinfo or not end.tzinfo or end <= start:
            raise ValueError()
    except ValueError:
        raise HTTPException(
            422, "Use timezone-aware start/end dates with end after start"
        )
    if (
        data.promotion_type == "informational"
        and data.value is not None
        or data.promotion_type != "informational"
        and data.value is None
        or data.promotion_type == "percent"
        and data.value > 100
    ):
        raise HTTPException(422, "Invalid promotion value")
    with request.app.state.database.sessions() as db:
        sku = db.scalar(select(SKU).where(SKU.sku_code == data.sku_code))
        if not sku:
            raise HTTPException(404, "SKU not found")
        promo = Promotion(
            sku_id=sku.id,
            channel=data.channel,
            name=data.name,
            description=data.description,
            promotion_type=data.promotion_type,
            value=data.value,
            starts_at=start,
            ends_at=end,
        )
        db.add(promo)
        db.commit()
        return {"id": str(promo.id)}


@router.get("/admin/proposals")
def proposals(request: Request):
    staff(request, {"admin"})
    with request.app.state.database.sessions() as db:
        return [
            {
                "id": str(p.id),
                "kind": p.kind,
                "candidate": p.candidate,
                "status": p.status,
            }
            for p in db.scalars(
                select(Proposal).order_by(Proposal.created_at.desc()).limit(100)
            )
        ]


@router.post("/admin/proposals/{proposal_id}/review")
def review(proposal_id: UUID, data: ReviewInput, request: Request):
    role = staff(request, {"admin"})
    with request.app.state.database.sessions() as db:
        proposal = db.scalar(
            select(Proposal).where(Proposal.id == str(proposal_id)).with_for_update()
        )
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if proposal.status != "pending":
            raise HTTPException(409, "Proposal has already been reviewed")
        if data.decision == "approved" and not data.knowledge_text.strip():
            raise HTTPException(422, "Approved knowledge requires reviewed text")
        proposal.status = data.decision
        proposal.reviewed_by = request.state.actor_id
        proposal.reviewed_at = now()
        if data.decision == "approved":
            db.add(
                Policy(
                    external_id="approved-" + str(proposal.id),
                    category=data.category,
                    body=data.knowledge_text,
                    effective_at=now(),
                )
            )
        db.add(
            Outbox(
                event_type="improvement.reviewed",
                aggregate_id=proposal.id,
                payload={"proposal_id": str(proposal.id), "status": proposal.status},
            )
        )
        db.add(
            AuditLog(
                actor_id=request.state.actor_id,
                action="proposal." + data.decision,
                resource_id=str(proposal.id),
            )
        )
        db.commit()
        return {"status": proposal.status}
