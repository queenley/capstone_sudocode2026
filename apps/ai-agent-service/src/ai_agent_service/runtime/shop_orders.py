"""The website's customers and orders, for the agent's order tools on a live channel.

The agent's tools price, promote, number and date an order by the organisers' mock (``mcp/servers/btc.py``): the
guardrails and the organisers' grader read that state, so it stays the agent's own. On its own it was a second
order store: an order the agent placed on Zalo (OD600001) never reached the customer's account on the website, and
an order the customer placed on the website was never seen by ``order.status`` (2026-11-14).

With ``SHOP_ORDERS=1`` (set for the ai-agent-service container only, never for an evaluation run) this module:

* :func:`mirror_create`: puts an order the agent placed into ``commerce.orders`` under its code, for the customer
  who owns the phone (created when the website does not know them yet), at the prices the agent quoted;
* :func:`mirror_address`: moves that order's delivery address when the agent changes it;
* :func:`orders_for_phone`: the website's orders of the customer who owns a phone, as ``order.status`` lists them;
* :func:`seed_crm_customers`: the organisers' CRM customers and their order history, as website customers.

Every function is synchronous (SQLAlchemy, backend-common's models), run in a worker thread by its caller, and
never raises: a website that cannot be reached leaves the agent's answer as the mock gave it, with a warning.
"""

from __future__ import annotations

import functools
import logging
import os
from decimal import Decimal
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

#: The mock's payment names, as the website's orders allow them (cod | bank_transfer): a wallet is a transfer.
PAYMENTS = {"COD": "cod", "bank": "bank_transfer", "momo": "bank_transfer", "zalopay": "bank_transfer"}
#: The mock's and the CRM's order statuses, as the website's orders spell them (migration 0008). Sales moves an
#: order on by hand: confirmed -> shipping -> fulfilled; a return the customer asked for -> returned.
STATUSES = {"created": "confirmed", "processing": "confirmed", "shipping": "shipping", "delivered": "fulfilled",
            "cancelled": "cancelled", "returned": "returned"}
#: The website's statuses as the agent's tools say them (the mock's words), for order.status.
SPOKEN = {"pending": "pending", "confirmed": "created", "shipping": "shipping", "fulfilled": "delivered",
          "return_requested": "return_requested", "returned": "returned", "cancelled": "cancelled"}
#: DT-03: the first exchange of an order is free, each later one costs 30.000đ each way.
EXCHANGE_FEE = 60000
#: DT-07: a refund reaches the customer in this many working days.
REFUND_DAYS = "3-5 ngày làm việc"


def enabled() -> bool:
    """On for a live channel only: the switch is set, and the database is not an evaluation one."""
    if os.environ.get("SHOP_ORDERS", "").strip().lower() not in ("1", "true", "yes"):
        return False
    url = os.environ.get("DATABASE_URL", "")
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    return bool(url) and not name.endswith("_eval")


@functools.lru_cache(maxsize=1)
def _resources() -> tuple[Any, Any]:
    from src.core.config import Settings
    from src.db.session import Database
    from src.security.service import Security

    settings = Settings()
    return Database(settings.database_url), Security(settings)


def warm() -> None:
    """Open the website's database now, when an MCP server starts, not inside the first call's 2-second budget.

    The first lookup of a process imports backend-common, builds the engine and opens a connection: 1.8 s on an idle
    machine, over 2 s beside a model call, and ``order_status`` timed out twice, which opened its circuit for 60 s.
    A website that cannot be reached is logged and left for the call to find, never a reason to stop the server."""
    if not enabled():
        return
    try:
        from sqlalchemy import text

        import src.commerce.crm_seed  # noqa: F401 - imported by every lookup

        db, _ = _resources()
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:  # noqa: BLE001 - startup goes on without the website
        logger.warning("Website orders not reachable at start: %s", error)


def _phone(value: str | None) -> str | None:
    from src.commerce.crm_seed import phone_of

    return phone_of(value)


def _customer(db: Any, security: Any, phone: str, *, name: str | None = None, external_id: str | None = None,
              create: bool) -> Any:
    """The website customer who owns *phone* (``src/commerce/crm_seed.py``, shared with the shop's seed)."""
    from src.commerce.crm_seed import customer_for_phone

    return customer_for_phone(db, security, phone, name=name, external_id=external_id, create=create)


def _lines(args: Mapping[str, Any]) -> list[tuple[str, int, int]]:
    """``(sku, qty, unit price)`` of an ``order_create`` call."""
    if args.get("lines"):
        return [(str(line["sku"]), int(line.get("qty") or 1), int(line["price_vnd"])) for line in args["lines"]]
    if args.get("sku") and args.get("price_vnd") is not None:
        return [(str(args["sku"]), int(args.get("qty") or 1), int(args["price_vnd"]))]
    return []


def _place(db: Any, security: Any, *, customer: Any, code: str, source: str, lines: Iterable[tuple[str, int, int]],
           address: str, payment: str, status: str, reserve: bool, placed_on: str | None = None) -> bool:
    """One order under *code* (``src/commerce/crm_seed.py``), a product the shop lacks added as discontinued."""
    from src.commerce.crm_seed import place_order

    return place_order(db, security, customer=customer, code=code, source=source, lines=lines, address=address,
                       payment=payment, status=status, reserve=reserve, placed_on=placed_on, sku_of=_sku)


def _sku(db: Any, code: str) -> Any:
    """The shop's SKU *code*; one the shop lacks but the organisers' catalogue names (a product no longer sold,
    SKU-AP-X-2024) is added as discontinued, so an order of it can still be kept. None when nobody knows it."""
    from sqlalchemy import select
    from src.db.models import Inventory, Product, SKU

    sku = db.scalar(select(SKU).where(SKU.sku_code == code))
    if sku is not None:
        return sku
    from ..mcp.servers import btc

    product, variant = btc.mock()._parent(code)
    if not product:
        return None
    price = Decimal(int(product.get("list_price_vnd") or 0) + int((variant or {}).get("price_delta_vnd") or 0))
    row = Product(name=str(product.get("name") or code), brand=product.get("brand"),
                  category=str(product.get("category") or "khac"), active=False)
    db.add(row)
    db.flush()
    sku = SKU(product_id=row.id, sku_code=code, variant={}, list_price=price, sale_price=price, active=False)
    db.add(sku)
    db.flush()
    db.add(Inventory(sku_id=sku.id, quantity_on_hand=0, reserved_quantity=0))
    db.flush()
    return sku


def _find(db: Any, code: str, *, lock: bool = False) -> Any:
    """The website order the customer knows as *code*: an OD code, or WEB- and its id's first eight characters."""
    from sqlalchemy import String, cast, select
    from src.db.models import Order

    code = (code or "").strip().upper()
    if code.startswith("WEB-") and len(code) == 12:
        query = select(Order).where(cast(Order.id, String).like(code[4:].lower() + "%"), Order.order_code.is_(None))
    else:
        query = select(Order).where(Order.order_code == code)
    found = db.scalars(query.limit(2)).all()
    if len(found) != 1:
        return None
    return db.scalar(select(Order).where(Order.id == found[0].id).with_for_update()) if lock else found[0]


def _exchanges(db: Any, order: Any) -> int:
    from sqlalchemy import func, select
    from src.db.models import Outbox

    return int(db.scalar(select(func.count()).select_from(Outbox).where(
        Outbox.aggregate_id == order.id, Outbox.event_type == "order.exchanged")) or 0)


def _swap(db: Any, order: Any, new_sku: Any, *, reserve_old: bool) -> tuple[int, int]:
    """The order's first line becomes *new_sku*: (old unit price, new unit price). Stock moves with it."""
    from sqlalchemy import select, update
    from src.db.models import Inventory, OrderItem, now

    item = db.scalar(select(OrderItem).where(OrderItem.order_id == order.id).limit(1))
    old_price, new_price = int(item.unit_price), int(new_sku.sale_price)
    held = db.execute(update(Inventory).where(Inventory.sku_id == new_sku.id,
                                              Inventory.quantity_on_hand - Inventory.reserved_quantity >= item.quantity)
                      .values(reserved_quantity=Inventory.reserved_quantity + item.quantity, updated_at=now()))
    if held.rowcount != 1:
        raise LookupError("new_variant_out_of_stock")
    if reserve_old:  # not shipped yet: what was held for the old one goes back
        db.execute(update(Inventory).where(Inventory.sku_id == item.sku_id)
                   .values(reserved_quantity=Inventory.reserved_quantity - item.quantity, updated_at=now()))
    item.sku_id, item.unit_price = new_sku.id, Decimal(new_price)
    order.subtotal = order.subtotal - Decimal(old_price * item.quantity) + Decimal(new_price * item.quantity)
    return old_price, new_price


def update_order(order_id: str, action: str, *, new_variant_sku: str | None = None, new_address: str | None = None,
                 reason: str | None = None) -> dict[str, Any] | None:
    """``order.update`` on an order the website keeps and the mock does not (one placed on the site, or the CRM's).

    The result as the mock words it, ``{"error": ...}`` when the change cannot be made, None when the website has no
    such order either. The mock's policy: the first exchange free, later ones 60.000đ, a refund in 3-5 working days.
    An address moves only before Sales ships the order; a return is asked for once it is delivered, and Sales
    finishes it (returned). An exchange of a delivered order sends the new item, so the order is confirmed again.
    """
    if not enabled():
        return None
    try:
        from src.db.models import Outbox

        database, security = _resources()
        with database.sessions() as db:
            order = _find(db, order_id, lock=True)
            if order is None:
                return None
            if order.status in ("cancelled", "returned", "return_requested"):
                return {"error": f"order_{order.status}", "order_id": order_id}
            if action == "update_address":
                if not (new_address or "").strip():
                    return {"error": "missing_new_address"}
                if order.status != "confirmed":
                    return {"error": "order_already_shipped", "order_id": order_id, "status": SPOKEN[order.status]}
                order.encrypted_shipping_address = security.encrypt(new_address.strip())
                db.add(Outbox(event_type="order.address_changed", aggregate_id=order.id,
                              payload={"order_id": str(order.id)}))
                db.commit()
                return {"order_id": order_id, "action": action, "status": "updated", "new_address": new_address.strip()}
            if action in ("exchange_size", "exchange_product"):
                if not new_variant_sku:
                    return {"error": "missing_new_variant_sku"}
                if order.status == "shipping":
                    return {"error": "order_in_transit", "order_id": order_id, "status": "shipping"}
                new_sku = _sku(db, new_variant_sku)
                if new_sku is None or not new_sku.active:
                    return {"error": "unknown_variant", "new_variant_sku": new_variant_sku}
                delivered = order.status == "fulfilled"
                fee = 0 if _exchanges(db, order) == 0 else EXCHANGE_FEE
                try:
                    old_price, new_price = _swap(db, order, new_sku, reserve_old=not delivered)
                except LookupError:
                    db.rollback()
                    return {"error": "new_variant_out_of_stock", "new_variant_sku": new_variant_sku}
                order.status = "confirmed"
                db.add(Outbox(event_type="order.exchanged", aggregate_id=order.id,
                              payload={"order_id": str(order.id), "new_sku": new_variant_sku, "fee_vnd": fee}))
                db.commit()
                diff = new_price - old_price
                return {"order_id": order_id, "action": action, "new_variant_sku": new_variant_sku, "fee_vnd": fee,
                        "price_diff_vnd": diff, "refund_vnd": -diff if diff < 0 else 0,
                        "extra_payment_vnd": diff if diff > 0 else 0, "refund_days": REFUND_DAYS,
                        "status": "pickup_scheduled" if delivered else "updated"}
            if action == "return":
                if order.status != "fulfilled":
                    return {"error": "order_not_delivered", "order_id": order_id, "status": SPOKEN[order.status]}
                order.status = "return_requested"
                db.add(Outbox(event_type="order.return_requested", aggregate_id=order.id,
                              payload={"order_id": str(order.id), "reason": reason or ""}))
                db.commit()
                return {"order_id": order_id, "action": "return", "reason": reason,
                        "refund_vnd": int(order.subtotal - (order.discount or 0)), "refund_days": REFUND_DAYS,
                        "status": "pickup_scheduled"}
            return {"error": "unknown_action"}
    except Exception:
        logger.warning("Could not change website order %s", order_id, exc_info=True)
        return {"error": "website_unavailable"}


def mirror_update(order_code: str, action: str, result: Any, *, new_variant_sku: str | None = None) -> None:
    """A change the mock made to an order the agent placed, also on the website's copy (exchange, return)."""
    if not enabled() or not isinstance(result, Mapping) or result.get("error") or not order_code:
        return
    try:
        from src.db.models import Outbox

        database, _ = _resources()
        with database.sessions() as db:
            order = _find(db, order_code, lock=True)
            if order is None:
                return
            if action in ("exchange_size", "exchange_product") and new_variant_sku:
                new_sku = _sku(db, new_variant_sku)
                if new_sku is None:
                    return
                try:
                    _swap(db, order, new_sku, reserve_old=order.status == "confirmed")
                except LookupError:
                    # The mock checked its own stock; the line still changes, the shop's count is Sales' to fix.
                    from sqlalchemy import select
                    from src.db.models import OrderItem

                    item = db.scalar(select(OrderItem).where(OrderItem.order_id == order.id).limit(1))
                    item.sku_id = new_sku.id
                order.status = "confirmed"
                db.add(Outbox(event_type="order.exchanged", aggregate_id=order.id,
                              payload={"order_id": str(order.id), "new_sku": new_variant_sku}))
            elif action == "return":
                order.status = "return_requested"
                db.add(Outbox(event_type="order.return_requested", aggregate_id=order.id,
                              payload={"order_id": str(order.id)}))
            else:
                return
            db.commit()
    except Exception:
        logger.warning("Could not mirror the change of order %s to the website", order_code, exc_info=True)


def mirror_create(result: Any, args: Mapping[str, Any]) -> None:
    """An order the agent placed (``order_create``'s result and arguments), now also on the website."""
    if not enabled() or not isinstance(result, Mapping) or not result.get("order_id"):
        return
    phone = _phone(args.get("customer_phone"))
    if phone is None:
        return
    try:
        database, security = _resources()
        with database.sessions() as db:
            customer = _customer(db, security, phone, create=True)
            if customer is None:
                logger.warning("Order %s not mirrored: several website customers share the number", result["order_id"])
                return
            placed = _place(db, security, customer=customer, code=str(result["order_id"]), source="agent",
                            lines=_lines(args), address=str(args.get("address") or ""),
                            payment=PAYMENTS.get(str(args.get("payment") or "COD"), "cod"), status="confirmed",
                            reserve=True)
            if placed:
                db.commit()
    except Exception:
        logger.warning("Could not mirror order %s to the website", result.get("order_id"), exc_info=True)


def mirror_address(order_code: str, address: str) -> None:
    """The new delivery address of an order the website keeps under *order_code*."""
    if not enabled() or not order_code or not address:
        return
    try:
        from sqlalchemy import select
        from src.db.models import Order

        database, security = _resources()
        with database.sessions() as db:
            order = db.scalar(select(Order).where(Order.order_code == order_code).with_for_update())
            if order is not None:
                order.encrypted_shipping_address = security.encrypt(address)
                db.commit()
    except Exception:
        logger.warning("Could not move the address of order %s on the website", order_code, exc_info=True)


def orders_for_phone(phone: str | None) -> list[dict[str, Any]]:
    """The website's orders of the customer who owns *phone*, newest first, as ``order.status`` lists an order."""
    phone = _phone(phone)
    if not enabled() or phone is None:
        return []
    try:
        from sqlalchemy import select
        from src.db.models import Order, OrderItem, Product, SKU

        database, security = _resources()
        with database.sessions() as db:
            customer = _customer(db, security, phone, create=False)
            if customer is None:
                return []
            out = []
            for order in db.scalars(select(Order).where(Order.customer_id == customer.id)
                                    .order_by(Order.created_at.desc()).limit(20)):
                items = [{"sku": sku.sku_code, "name": product.name, "qty": item.quantity,
                          "price_vnd": int(item.unit_price)}
                         for item, sku, product in db.execute(
                             select(OrderItem, SKU, Product).join(SKU, SKU.id == OrderItem.sku_id)
                             .join(Product, Product.id == SKU.product_id).where(OrderItem.order_id == order.id))]
                out.append({
                    "order_id": order.order_code or f"WEB-{str(order.id)[:8].upper()}",
                    "source": order.source or "website",
                    "status": SPOKEN.get(order.status, order.status),
                    "sku": items[0]["sku"] if items else None,
                    "lines": items,
                    "total_vnd": int(order.subtotal - (order.discount or 0)),
                    "payment": order.payment_method,
                    "created_on": order.created_at.date().isoformat() if order.created_at else None,
                })
            return out
    except Exception:
        logger.warning("Could not read the website's orders", exc_info=True)
        return []


def seed_crm_customers(customers: Iterable[Mapping[str, Any]], *, demo_password: str | None = None) -> tuple[int, int]:
    """The organisers' CRM customers as website customers, with their order history. Returns (customers, orders).
    The shop's own seed does the same before the shop starts (``scripts/seed/btc_customers.py``)."""
    from src.commerce.crm_seed import seed_customers

    database, security = _resources()
    with database.sessions() as db:
        counts = seed_customers(db, security, customers, sku_of=_sku, demo_password=demo_password)
        db.commit()
    return counts
