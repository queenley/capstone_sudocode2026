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

from typing_extensions import TypedDict

from ...components import clock
from ..server_base import Server, ToolFailure, apply_schema
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


# Typed, so a strict schema keeps its fields (an untyped object arrives empty, 2026-11-10). The docstring is the
# model's: it is the schema's description.
class OrderLine(TypedDict):
    """One line of the order: the sku, how many, and one unit's price as pricing_quote_order gave it."""

    sku: str
    qty: int
    price_vnd: int


@server.tool(roles={"advisor"}, name="order_create")
async def order_create(
    sku: str | None = None,
    price_vnd: int | None = None,
    qty: int = 1,
    lines: list[OrderLine] | None = None,
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
    """Place one order once the customer has asked to buy it.

    One unit of one product: sku, qty and price_vnd, the final_price_vnd
    pricing_get_quote gave for this sku today. More than one unit (two
    products, or two of one): one call with lines, the prices
    pricing_quote_order gave, one line per unit price (two units of one sku at
    different prices are two lines of qty 1). Any other price is refused.
    Cash on delivery (COD) is
    refused when the order's total, every COD line of the call together, is
    above 10.000.000đ: offer a bank transfer, or ask the customer whether to
    split it into two orders, and only once they agree give each line its
    order_group ("1" or "2"), each order at most 10.000.000đ.

    Args:
        sku: The product sku or variant_sku being bought; leave it out with lines.
        price_vnd: The unit price from pricing_get_quote, in VND; leave it out with lines.
        qty: How many units; leave it out with lines.
        lines: An order of more than one unit: [{"sku", "qty", "price_vnd"}], each price_vnd one unit's
            final_price_vnd from pricing_quote_order.
        promo_code: The promotion applied, as pricing_get_quote named it.
        payment: COD, bank, momo or zalopay: what the customer chose, or what the
            Call Brief records; COD when neither says, read back so the customer
            can change it. Never a reason to wait with the order.
        address: The delivery address the customer gave; leave it out when none was given.
        basket_skus: Only for an order split in two with the customer's agreement (QT-01): the air purifiers
            of the other order, so the second-item promotion is counted once.
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
        customer_phone=customer_phone, sku=None if lines else sku, qty=None if lines else qty,
        price_vnd=None if lines else price_vnd, lines=_lines(lines),
        promo_code=promo_code, payment=payment, address=address, on=on or btc.reference_date(),
        basket_skus=basket_skus or None,
    )


def _lines(lines: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """An order's lines as the organisers' mock takes them: sku, a whole quantity, a whole price."""
    if not lines:
        return None
    return [{"sku": str(line.get("sku")), "qty": int(line.get("qty") or 1),
             **({"price_vnd": int(line["price_vnd"])} if line.get("price_vnd") is not None else {})}
            for line in lines]


@server.tool(roles={"advisor"}, name="schedule_callback")
async def schedule_callback(
    callback_at: str,
    note: str | None = None,
    customer_phone: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Book a call back at the time the customer asked for; it needs the customer's number.

    A time on a holiday or outside working hours is moved; moved_from is then
    set, and the customer must be told the new time.

    Args:
        callback_at: Date and time in Vietnam time, no offset, e.g. 2026-10-17T19:00.
        note: What the call back is about.
        customer_phone: Set by the system; leave it out.
        idempotency_key: Set by the system; leave it out.
    """
    m = btc.mock()

    def book(**args: Any) -> dict[str, Any]:
        booked = m.schedule_callback(**args)
        moment = clock.parse_local(callback_at)
        if booked.get("moved_from") and moment is not None and clock.is_working_time(moment):
            # The mock knows the usual hours, not 11/11's longer ones (LN-02): the time stands.
            booked.update(callback_at=callback_at, moved_from=None)
        return booked

    if not customer_phone:
        raise ToolFailure("BAD_REQUEST", "A call back needs the customer's number: ask for it first")
    return await btc.call(
        "schedule.callback", book, idempotency_key=idempotency_key,
        customer_phone=customer_phone, callback_at=callback_at, note=note,
    )


# The harness calls it too: in lane HANDOFF the model may be what is failing (route rule 1).
@server.tool(roles={"advisor", "harness"}, name="handoff_transfer")
async def handoff_transfer(brief: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    """Hand the call to a person, with a brief they can act on in ten seconds.

    Use when the customer asks for a person; asks for medical, medicine,
    pregnancy, child-safety or legal advice; makes a serious complaint; or
    asks what the documents and tools do not answer (escalation_reason
    ngoai_pham_vi_tai_lieu). Call it first and tell the customer afterwards. Not
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
