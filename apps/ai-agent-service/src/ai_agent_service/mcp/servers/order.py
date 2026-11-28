"""mcp-order: an order already placed. ``docs/design.md`` section 6.1.

``order.status`` and ``order.update`` under the organisers' names, over the
reference mock (:mod:`.btc`): an exchange checks the new variant's stock,
the first size change is free and later ones cost 60.000đ both ways, a
cheaper replacement is refunded in 3 to 5 working days. The business
lanes offer both (section 4.3). ``order.update`` takes the
``idempotency_key`` the harness sets, as every write tool does (section 6.1).
"""

from __future__ import annotations

import asyncio
import logging

from typing import Any, Literal

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

    try:
        result = await btc.call(
            "order.update", _with_address(m), idempotency_key=idempotency_key,
            order_id=order_id, action=action, new_variant_sku=new_variant_sku, new_address=new_address,
            reason=reason, on=on or btc.reference_date(),
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


@server.tool(roles={"advisor"}, name="order_payment_qr")
async def order_payment_qr(order_id: str, account_id: str | None = None,
                           trusted_orders: list[str] | None = None) -> dict[str, Any]:
    """The QR code to pay one order by bank transfer: the exact amount and the transfer note are in the code.

    Call it when the customer asks to pay by transfer, asks for the QR or the account again, for an order of theirs
    paid by bank transfer, or to switch a COD order to a transfer (order_set_payment does that and shows the QR).
    The web chat, Zalo and a call on the website show the QR with the account under your reply: say the amount and
    ask them to scan it, keep the transfer note unchanged; do not read out the account number. On a voice call, say
    the QR is in the chat on the website; a caller on a phone line opens the website's chat or the shop's Zalo.

    Args:
        order_id: The order's code, e.g. OD600001, or the website's #ABCD1234.
        account_id: Filled in by the system for the logged-in customer; leave it out.
        trusted_orders: Set by the system; leave it out.
    """
    from ...runtime import shop_orders

    if not shop_orders.enabled():
        raise ToolFailure("UNAVAILABLE", "Chưa tạo được mã QR ở kênh này.")
    result = await asyncio.to_thread(shop_orders.payment_qr, order_id, account_id=account_id,
                                     trusted=trusted_orders or ())
    if not result.get("ok"):
        code = str(result.get("code") or "UNAVAILABLE")
        raise ToolFailure(code, shop_orders.QR_REFUSALS.get(code, "Chưa tạo được mã QR lúc này."))
    # What the reply needs; the chat shows the QR and the account itself (api/routes/conversations.py
    # payment_qr_for), so the account number never enters the model's view.
    return {"order_id": result["order_id"], "amount_vnd": result["amount"], "transfer_note": result["content"],
            "bank_name": result["bank_name"], "qr_shown_in_chat": True}


@server.tool(roles={"advisor"}, name="order_set_payment")
async def order_set_payment(order_id: str, payment: Literal["bank", "COD"], account_id: str | None = None,
                            trusted_orders: list[str] | None = None,
                            idempotency_key: str | None = None) -> dict[str, Any]:
    """Change how one of the customer's orders is paid, when they ask: bank transfer instead of cash on delivery,
    or back to COD (at most 10.000.000đ). Only before the order ships and while it is unpaid.

    For a bank transfer the chat shows the QR with the exact amount under your reply: say the amount, ask them to
    scan it and keep the transfer note; do not read out the account number.

    Args:
        order_id: The order's code, e.g. OD600001, or the website's #ABCD1234.
        payment: bank for a bank transfer, COD for cash on delivery.
        account_id: Filled in by the system for the logged-in customer; leave it out.
        trusted_orders: Set by the system; leave it out.
        idempotency_key: Set by the system; leave it out.
    """
    from ...runtime import shop_orders

    if not shop_orders.enabled():
        raise ToolFailure("UNAVAILABLE", "Chưa đổi được cách thanh toán ở kênh này.")
    method = "bank_transfer" if payment == "bank" else "cod"
    changed = await asyncio.to_thread(shop_orders.set_payment, order_id, method, account_id=account_id,
                                      trusted=trusted_orders or ())
    if not changed.get("ok"):
        code = str(changed.get("code") or "UNAVAILABLE")
        raise ToolFailure(code, shop_orders.PAYMENT_REFUSALS.get(code, "Chưa đổi được cách thanh toán lúc này."))
    if changed["changed"]:
        # The organisers' mock keeps its own copy of an order the assistant placed: order_status reads it there.
        await btc.call("order.set_payment", _set_mock_payment(btc.mock()), idempotency_key=idempotency_key,
                       order_id=changed["order_id"], payment=payment)
    result: dict[str, Any] = {"order_id": changed["order_id"], "payment": payment, "changed": changed["changed"]}
    if method == "bank_transfer":
        qr = await asyncio.to_thread(shop_orders.payment_qr, changed["order_id"], trusted=(changed["order_id"],))
        if qr.get("ok"):
            # The chat shows the QR and the account (api/routes/conversations.py payment_qr_for).
            result["payment_qr"] = {"amount_vnd": qr["amount"], "transfer_note": qr["content"],
                                    "qr_shown_in_chat": True}
    return result


def _set_mock_payment(m: Any) -> Any:
    def set_payment(order_id: str, payment: str) -> dict[str, Any]:
        order = m._ORDERS.get(order_id)
        if order is not None:
            order["payment"] = payment
        return {"order_id": order_id, "payment": payment}

    return set_payment


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
