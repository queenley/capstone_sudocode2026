from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
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
            service.serialize(o, include_address=True)
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


@router.post("/seller/orders/{order_id}/paid")
def mark_paid(order_id: UUID, request: Request):
    """A seller confirms the shop received the money (bank transfer, or COD settled)."""
    staff(request, {"admin", "seller"})
    with request.app.state.database.sessions() as db:
        order = db.get(Order, str(order_id))
        if not order:
            raise HTTPException(404, "Order not found")
        result = OrderService(db, request.app.state.security).mark_paid(order)
        db.commit()
        return result


class StatusInput(BaseModel):
    status: Literal["shipping", "fulfilled", "returned"]


@router.post("/seller/orders/{order_id}/status")
def set_status(order_id: UUID, data: StatusInput, request: Request):
    """Sales moves an order on by hand: on its way (shipping), delivered (fulfilled), or a return received
    (returned). The assistant reads the status back to the customer (order.status)."""
    staff(request, {"admin", "seller"})
    with request.app.state.database.sessions() as db:
        order = db.get(Order, str(order_id))
        if not order:
            raise HTTPException(404, "Order not found")
        result = OrderService(db, request.app.state.security).set_status(order, data.status)
        db.commit()
        return result
