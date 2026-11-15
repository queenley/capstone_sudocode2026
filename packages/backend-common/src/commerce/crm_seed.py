"""Customers and orders the shop did not take itself: the organisers' CRM, and the orders the AI agent places.

Shared by the storefront's seed (``scripts/seed/btc_customers.py``, run by the ``seed`` service before the shop
starts, so a fresh ``docker compose up`` already has chị Hoa and her order history) and by the agent's order tools
(``apps/ai-agent-service/.../runtime/shop_orders.py``, which keep the agent's orders on the website).

A customer is found by phone, the way the website's accounts find them (``identity/accounts.py``); an order by
the code the customer was told (``orders.order_code``, migration 0007). Running any of it again adds only what is
missing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping

from sqlalchemy import select, update

from src.db.models import Customer, CustomerIdentity, Inventory, Order, OrderItem, SKU, now
from src.security.service import normalize_identifier

logger = logging.getLogger(__name__)

#: The organisers' payment names, as the website's orders allow them (cod | bank_transfer): a wallet is a transfer.
PAYMENTS = {"COD": "cod", "bank": "bank_transfer", "momo": "bank_transfer", "zalopay": "bank_transfer"}
#: The organisers' order statuses (mock and CRM), as the website's orders spell them (migration 0008).
STATUSES = {"created": "confirmed", "processing": "confirmed", "shipping": "shipping", "delivered": "fulfilled",
            "cancelled": "cancelled", "returned": "returned"}


def phone_of(value: str | None) -> str | None:
    """The number in the website's form (+84...), or None when it is not a phone number."""
    try:
        return normalize_identifier("phone", value) if value else None
    except Exception:  # the HTTPException of a malformed number: no customer to find
        return None


def customer_for_phone(db: Any, security: Any, phone: str, *, name: str | None = None,
                       external_id: str | None = None, create: bool) -> Customer | None:
    """The website customer who owns *phone*: the one with an account first, else the only one; or a new one.

    A new one's phone is not verified (nobody proved it); registering with a code on that number later keeps the
    customer and its orders (``AccountService.register_verify``). None when several customers share the number
    and none has an account: not ours to choose."""
    digest = security.digest("phone:" + phone)
    owners = db.scalars(
        select(Customer).join(CustomerIdentity, CustomerIdentity.customer_id == Customer.id)
        .where(CustomerIdentity.kind == "phone", CustomerIdentity.identifier_digest == digest,
               CustomerIdentity.revoked_at.is_(None), Customer.deleted_at.is_(None))
    ).unique().all()
    account = next((c for c in owners if c.password_hash), None)
    if account is not None or len(owners) == 1:
        found = account or owners[0]
        if external_id and not found.external_id and not db.scalar(
                select(Customer).where(Customer.external_id == external_id)):
            found.external_id = external_id
        if name and not found.full_name:
            found.full_name = name
        return found
    if owners or not create:
        return None
    customer = Customer(full_name=name, external_id=external_id)
    db.add(customer)
    db.flush()
    db.add(CustomerIdentity(customer_id=customer.id, kind="phone", identifier_digest=digest,
                            encrypted_value=security.encrypt(phone), consent_at=now()))
    db.flush()
    return customer


def shop_sku(db: Any, code: str) -> SKU | None:
    return db.scalar(select(SKU).where(SKU.sku_code == code))


def place_order(db: Any, security: Any, *, customer: Customer, code: str, source: str,
                lines: Iterable[tuple[str, int, int]], address: str, payment: str, status: str, reserve: bool,
                placed_on: str | None = None, sku_of: Callable[[Any, str], SKU | None] = shop_sku) -> bool:
    """One order under *code* (``(sku, qty, unit price)`` lines), unless one is there already; False when a line's
    product is unknown. A CRM order already kept takes the CRM's status again, as the mapping reads it now."""
    existing = db.scalar(select(Order).where(Order.order_code == code))
    if existing is not None:
        if source == "crm" and existing.source == "crm":
            existing.status = status
        return True
    priced = []
    for sku_code, qty, price in lines:
        sku = sku_of(db, sku_code)
        if sku is None:
            logger.warning("Order %s not kept: %s is not in the catalogue", code, sku_code)
            return False
        priced.append((sku, qty, Decimal(price)))
    if not priced:
        return False
    when = now()
    if placed_on:
        when = datetime.fromisoformat(placed_on[:10]).replace(hour=9, tzinfo=timezone.utc)
    order = Order(customer_id=customer.id, idempotency_key=security.digest(f"{source}:{code}"), status=status,
                  subtotal=sum((price * qty for _, qty, price in priced), Decimal(0)), discount=Decimal(0),
                  encrypted_shipping_address=security.encrypt(address or ""), confirmed_at=when, created_at=when,
                  payment_method=payment, payment_status="paid" if status == "fulfilled" else "unpaid",
                  order_code=code, source=source)
    db.add(order)
    db.flush()
    for sku, qty, price in priced:
        db.add(OrderItem(order_id=order.id, sku_id=sku.id, quantity=qty, unit_price=price, discount=Decimal(0)))
        if reserve:
            # The agent's mock already checked the stock; the shop keeps its own count as close as it can.
            db.execute(update(Inventory).where(Inventory.sku_id == sku.id,
                                               Inventory.quantity_on_hand - Inventory.reserved_quantity >= qty)
                       .values(reserved_quantity=Inventory.reserved_quantity + qty, updated_at=now()))
    return True


def seed_customers(db: Any, security: Any, rows: Iterable[Mapping[str, Any]], *,
                   sku_of: Callable[[Any, str], SKU | None] = shop_sku,
                   demo_password: str | None = None) -> tuple[int, int]:
    """The organisers' CRM customers (``crm_seed*.json`` rows) as website customers, with their order history.
    Returns (customers, orders kept). Not committed: the caller commits.

    *demo_password*, for a local demo only: every CRM customer without an account gets one with this password,
    so the shop can be opened as chị Hoa (0984726714) at once. Customers with an account keep theirs."""
    hashed = None
    if demo_password:
        from src.security.auth import password_hash

        hashed = password_hash(demo_password)
    seen = kept = 0
    for row in rows:
        phone = phone_of(row.get("phone"))
        if phone is None:
            continue
        customer = customer_for_phone(db, security, phone, name=row.get("name"),
                                      external_id=str(row.get("customer_id") or "") or None, create=True)
        if customer is None:
            continue
        seen += 1
        if hashed and not customer.password_hash:
            # A demo account stands for a phone its owner proved, as registering with a code does.
            customer.password_hash, customer.registered_at = hashed, now()
            for identity in db.scalars(select(CustomerIdentity).where(
                    CustomerIdentity.customer_id == customer.id, CustomerIdentity.kind == "phone",
                    CustomerIdentity.verified_at.is_(None))):
                identity.verified_at = now()
        for order in row.get("orders") or []:
            code, sku = order.get("order_id"), order.get("sku") or order.get("variant_sku")
            price = order.get("price_vnd") or order.get("total_vnd")
            if not code or not sku or price is None:
                continue
            if place_order(db, security, customer=customer, code=str(code), source="crm",
                           lines=[(str(sku), int(order.get("qty") or 1), int(price))], address="",
                           payment=PAYMENTS.get(str(order.get("payment") or "COD"), "cod"),
                           status=STATUSES.get(str(order.get("status") or ""), "confirmed"),
                           reserve=False, placed_on=order.get("date"), sku_of=sku_of):
                kept += 1
    return seen, kept
