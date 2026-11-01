"""mcp-crm: who the customer is, and the three things the advisor may do for them.

``docs/design.md`` section 6.1. ``crm.get_customer``, ``order.create``,
``schedule.callback`` and ``handoff.transfer``, under the organisers' names and
required arguments, each wrapping the reference mock (:mod:`.btc`): the COD
limit, a price that must equal the quote of the day, a callback moved off a
holiday, a Handoff Brief that must carry every required field.

Each write tool takes an ``idempotency_key`` the harness sets: a write is
never retried (section 6.1), and the same key seen twice returns the first
outcome rather than a second order.

The three write tools are the advisor's alone. Before any of them runs, the
harness has already checked its arguments (section 4.4, the guardrail before
act); the mock checks again, so a price that slipped past one is refused by
the other.
"""

from __future__ import annotations

from typing import Any, Literal

from ..server_base import Server, apply_schema
from . import btc

server = Server("crm")


@server.tool(roles={"advisor", "harness"}, name="crm_get_customer")
async def crm_get_customer(
    phone: str | None = None,
    zalo_id: str | None = None,
    fb_id: str | None = None,
) -> dict[str, Any]:
    """Look a customer up by phone number or by a channel identity.

    One number may belong to two people in one household: then ambiguous is
    true and candidates lists both, and nothing about either may be read out
    until the caller has said which one they are.

    Args:
        phone: Ten digits starting with 0.
        zalo_id: The Zalo OA identity of the conversation.
        fb_id: The Facebook fanpage identity of the conversation.
    """
    m = btc.mock()
    return await btc.call("crm.get_customer", m.crm_get_customer, phone=phone, zalo_id=zalo_id, fb_id=fb_id)


@server.tool(roles={"advisor"}, name="order_create")
async def order_create(
    sku: str,
    price_vnd: int,
    qty: int = 1,
    promo_code: str | None = None,
    payment: Literal["COD", "bank", "momo", "zalopay"] = "COD",
    address: str | None = None,
    basket_skus: list[str] | None = None,
    order_group: str | None = None,
    customer_phone: str | None = None,
    on: str | None = None,
    idempotency_key: str | None = None,
    call_id: str | None = None,
    turn_id: str | None = None,
    purchase_authorization: str | None = None,
) -> dict[str, Any]:
    """Place one line of an order once the customer has agreed to buy.

    Several products: one call per product, each with the others in
    basket_skus. price_vnd is the unit price after promotions, exactly the
    final_price_vnd pricing_get_quote gave for this sku today (with the same
    basket_skus); any other number is refused. Cash on delivery (COD) is
    refused when the order's total, every COD line of the call together, is
    above 10.000.000đ: offer a bank transfer, or ask the customer whether to
    split it into two orders, and only once they agree give each line its
    order_group ("1" or "2"), each order at most 10.000.000đ.

    Args:
        sku: The product sku or variant_sku being bought.
        price_vnd: The unit price from pricing_get_quote, in VND.
        qty: How many units.
        promo_code: The promotion applied, as pricing_get_quote named it.
        payment: COD, bank, momo or zalopay: what the customer chose, or what the
            Call Brief records; COD when neither says, read back so the customer
            can change it. Never a reason to wait with the order.
        address: The delivery address the customer gave; leave it out when none was given.
        basket_skus: The other skus in the same order, as when quoting (the second purifier's AIR-2ND-50).
        order_group: Only for an order split with the customer's agreement: which of the orders this line is in.
        customer_phone: Set by the system; leave it out.
        on: The day of the call. Set by the system; leave it out.
        idempotency_key: Set by the system; leave it out.
        call_id: Set by the system; leave it out.
        turn_id: Set by the system; leave it out.
        purchase_authorization: Signed consent supplied by the system; leave it out.
    """
    m = btc.mock()
    # order_group is the team's own: the organisers' mock does not take it (the guard reads it, section 4.4).
    return await btc.call(
        "order.create", m.order_create, idempotency_key=idempotency_key,
        call_id=call_id, turn_id=turn_id, purchase_authorization=purchase_authorization, order_group=order_group,
        customer_phone=customer_phone, sku=sku, qty=qty, price_vnd=price_vnd,
        promo_code=promo_code, payment=payment, address=address, on=on or btc.reference_date(),
        basket_skus=basket_skus or None,
    )


@server.tool(roles={"advisor"}, name="schedule_callback")
async def schedule_callback(
    callback_at: str,
    note: str | None = None,
    customer_phone: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Book a call back at the time the customer asked for.

    A time on a holiday or outside working hours is moved; moved_from is then
    set, and the customer must be told the new time.

    Args:
        callback_at: ISO 8601 date and time with +07:00, e.g. 2026-10-17T19:00+07:00.
        note: What the call back is about.
        customer_phone: Set by the system; leave it out.
        idempotency_key: Set by the system; leave it out.
    """
    m = btc.mock()
    return await btc.call(
        "schedule.callback", m.schedule_callback, idempotency_key=idempotency_key,
        customer_phone=customer_phone, callback_at=callback_at, note=note,
    )


# The harness calls it too: in lane HANDOFF the model may be what is failing (route rule 1).
@server.tool(roles={"advisor", "harness"}, name="handoff_transfer")
async def handoff_transfer(brief: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    """Hand the call to a person, with a brief they can act on in ten seconds.

    Use when the customer asks for a person; asks for medical, medicine,
    pregnancy, child-safety or legal advice; makes a serious complaint; or
    asks what the documents and tools do not answer (escalation_reason
    ngoai_pham_vi_tai_lieu): say you do not have that information first. Not
    for a product question, even about a product for mothers and babies. The
    system fills in the customer's phone, name, the product and price already
    advised, and the time; write the rest.

    Args:
        brief: escalation_reason (cau_hoi_y_te, ngoai_pham_vi_tai_lieu,
            khach_yeu_cau_gap_nguoi, khieu_nai_nghiem_trong, loi_he_thong,
            khach_mat_kien_nhan, khac); escalation_reason_detail;
            conversation_summary (2 to 5 sentences); open_questions (the
            questions not yet answered); next_action (what the person should
            do first).
        idempotency_key: Set by the system; leave it out.
    """
    m = btc.mock()
    return await btc.call("handoff.transfer", m.handoff_transfer, idempotency_key=idempotency_key, brief=brief)


if __name__ == "__main__":
    apply_schema(btc.STATE_SCHEMA)
    # The organisers' mock loaded now, not inside the first call's 2-second budget.
    btc.mock()
    server.run()
