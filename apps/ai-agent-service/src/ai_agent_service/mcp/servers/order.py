"""mcp-order: an order already placed.

``order.status`` and ``order.update`` under the organisers' names, over the
reference mock (:mod:`.btc`): an exchange checks the new variant's stock,
the first size change is free and later ones cost 60.000đ both ways, a
cheaper replacement is refunded in 3 to 5 working days. The business
lanes offer both. ``order.update`` takes the
``idempotency_key`` the harness sets, as every write tool does.
"""

from __future__ import annotations

import asyncio
import logging

from typing import Any, Literal

from ...components.guardrails import actions
from ..server_base import Server, ToolFailure, apply_schema
from . import btc

server = Server("order")
logger = logging.getLogger(__name__)

# What order_status may spend on the website's orders, inside the tool's 2 seconds (mcp/tools.py DEFAULT_TIMEOUT).
WEBSITE_BUDGET = 1.0


@server.tool(roles={"advisor", "harness"}, name="order_status")
async def order_status(order_id: str | None = None, customer_phone: str | None = None) -> dict[str, Any]:
    """Where an order is, by its code or by the customer's phone.

    Args:
        order_id: The order code, e.g. OD600001.
        customer_phone: Set by the system when no order code is given; leave it out.
    """
    m = btc.mock()
    result = await btc.call("order.status", m.order_status, order_id=order_id, customer_phone=customer_phone)
    from ...runtime import shop_orders

    if not shop_orders.enabled() or not isinstance(result, dict):
        return result
    # A live channel also lists the customer's website orders: what they bought on the site, and the orders this
    # assistant placed, which the website keeps under the same code (runtime/shop_orders.py).
    known = list(result.get("orders") or [])
    phone = customer_phone or next((o.get("customer_phone") for o in known if o.get("customer_phone")), None)
    try:
        # The website's orders are an addition: never at the cost of the organisers' answer (2 s for the whole tool).
        website = await asyncio.wait_for(asyncio.to_thread(shop_orders.orders_for_phone, phone), WEBSITE_BUDGET)
    except asyncio.TimeoutError:
        logger.warning("order_status: website orders took over %gs; answered without them", WEBSITE_BUDGET)
        return result
    codes = {o.get("order_id") for o in known}
    extra = [o for o in website if o["order_id"] not in codes and (not order_id or o["order_id"] == order_id)]
    return {**result, "orders": known + extra} if extra else result


@server.tool(roles={"advisor"}, name="order_update")
async def order_update(
    order_id: str,
    action: Literal["exchange_size", "exchange_product", "return", "update_address"],
    new_variant_sku: str | None = None,
    new_address: str | None = None,
    reason: str | None = None,
    on: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Change an order: another size or product, a return, a new address.

    The result carries any fee, the price difference, and a refund with its
    delay; tell the customer exactly those. For a new address it carries the
    address now on the order and the new delivery date.

    Args:
        order_id: The order code.
        action: exchange_size, exchange_product, return or update_address.
        new_variant_sku: The variant or product wanted instead, for an exchange.
        new_address: The delivery address the customer gave, for update_address.
        reason: Why, in the customer's words.
        on: The day of the call. Set by the system; leave it out.
        idempotency_key: Set by the system; leave it out.
    """
    m = btc.mock()
    from ...runtime import shop_orders

    day = on or btc.reference_date()
    if action in actions.WINDOW_ACTIONS:
        # The organisers' mock books a return of any order; DT-01 closes the window 7 days after receipt.
        known = (m.order_status(order_id=order_id) or {}).get("orders") or []
        if any(o.get("order_id") == order_id and actions.past_return_window(o, day) for o in known):
            raise ToolFailure("RETURN_WINDOW_CLOSED",
                              f"Đơn {order_id} đã hết hạn đổi trả {actions.RETURN_DAYS} ngày kể từ khi nhận hàng (DT-01): "
                              "không trả hay đổi được.")
    try:
        result = await btc.call(
            "order.update", _with_address(m), idempotency_key=idempotency_key,
            order_id=order_id, action=action, new_variant_sku=new_variant_sku, new_address=new_address,
            reason=reason, on=day,
        )
    except ToolFailure as failure:
        # Not an order the mock holds: one placed on the website, or the CRM's history the website keeps. A live
        # channel changes it there (runtime/shop_orders.py); otherwise the mock's refusal stands.
        if failure.code != "ORDER_NOT_FOUND" or not shop_orders.enabled():
            raise
        website = await asyncio.to_thread(shop_orders.update_order, order_id, action, new_variant_sku=new_variant_sku,
                                          new_address=new_address, reason=reason)
        if website is None:
            raise
        return btc.unwrap("order.update", website)
    if shop_orders.enabled():
        # The website's copy of an order the agent placed follows the change.
        if action == "update_address" and new_address:
            await asyncio.to_thread(shop_orders.mirror_address, order_id, new_address)
        elif action in ("exchange_size", "exchange_product", "return"):
            await asyncio.to_thread(shop_orders.mirror_update, order_id, action, result, new_variant_sku=new_variant_sku)
    return result


def _with_address(m: Any) -> Any:
    """The organisers' ``order_update`` (read-only pack), plus the address it never took.

    Their ``update_address`` answers ``updated`` and changes nothing: the order kept its old address, so the next
    ``order.status`` read it back and the assistant contradicted the change it had just announced. Here the new
    address goes onto the order (an order placed in this shop, ``_ORDERS``, the state the next read loads) and onto
    the ticket, with the delivery date the mock's own rule gives that address. An order from the CRM's history is
    not in that state: its ticket keeps the address and the result says the order record itself is unchanged.
    """

    def update(order_id: str, action: str, new_variant_sku: str | None = None, reason: str | None = None,
               on: str | None = None, new_address: str | None = None) -> dict[str, Any]:
        if action == "update_address" and not (new_address or "").strip():
            return {"error": "missing_new_address"}
        result = m.order_update(order_id, action, new_variant_sku=new_variant_sku, reason=reason,
                                **({"on": on} if on else {}))
        if action != "update_address" or not isinstance(result, dict) or result.get("error"):
            return result
        address = new_address.strip()
        result["new_address"] = address  # the ticket the mock kept is this dict: it keeps the address too
        order = m._ORDERS.get(order_id)
        if order is None:
            result["order_record_updated"] = False
            return result
        order["address"] = address
        result["estimated_delivery"] = m._eta(on or order.get("created_on") or btc.reference_date(), address)
        return result

    return update


if __name__ == "__main__":
    apply_schema(btc.STATE_SCHEMA)
    # The organisers' mock and the website's database opened now, not inside the first call's 2-second budget.
    btc.mock()
    from ...runtime import shop_orders

    shop_orders.warm()
    server.run()
