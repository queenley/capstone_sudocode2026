from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from src.commerce.service import OrderService
from src.db.models import (
    Order,
)
from .shared import staff

router = APIRouter(prefix="/api")


@router.get("/seller/orders")
def all_orders(request: Request):
    staff(request, {"admin", "seller"})
    with request.app.state.database.sessions() as db:
        service = OrderService(db, request.app.state.security)
        return [
            service.serialize(o)
            for o in db.scalars(
                select(Order).order_by(Order.created_at.desc()).limit(100)
            )
        ]


@router.post("/seller/orders/{order_id}/cancel")
def cancel(order_id: UUID, request: Request):
    staff(request, {"admin", "seller"})
    with request.app.state.database.sessions() as db:
        order = db.get(Order, str(order_id))
        if not order:
            raise HTTPException(404, "Order not found")
        result = OrderService(db, request.app.state.security).cancel(order)
        db.commit()
        return result
