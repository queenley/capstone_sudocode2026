"""The guardrail before act: checking a write tool's arguments. ``docs/design.md`` section 4.4.

The brief's figure puts GUARDRAIL before ACT. Before a tool with an effect
runs, the harness checks its arguments; a failure goes back to the model as
a tool error with the reason, and nothing happens in the business.

| Tool | Checked |
|---|---|
| ``order.create`` | a phone to order for; the unit price equals today's ``pricing.get_quote`` for that sku; COD total at most 10.000.000đ; the tier allows it |
| ``order.update`` | the order is one this customer has |
| ``schedule.callback`` | the time is a date and time |
| ``handoff.transfer`` | the brief validates against ``schemas/handoff_brief.schema.json`` itself (required fields, enums, phone pattern, summary length), after the harness filled in what it knows |
| any write tool in copilot mode | refused: the consultant acts, the advisor only suggests (section 4.6) |

A customer the shop has never met may order on their own line: UNKNOWN with
a phone from the connection is allowed; PROBABLE and AMBIGUOUS are not,
because the order would be booked to someone who has not been confirmed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .. import btc_schemas
from ..intake.itn import format_vnd
from . import Verdict

WRITE_TOOLS = frozenset({"order_create", "order_update", "schedule_callback", "handoff_transfer"})

COD_LIMIT_VND = 10_000_000


def check(
    name: str,
    args: Mapping[str, Any],
    *,
    tier: str,
    mode: str,
    has_phone: bool,
    quotes: Mapping[str, int],
    orders: frozenset[str] = frozenset(),
) -> Verdict:
    """Whether a write tool may run with *args*; the reasons if not."""
    if name not in WRITE_TOOLS:
        return Verdict(True)
    if mode == "copilot":
        return Verdict(False, ("Chế độ copilot: tư vấn viên thực hiện thao tác này, trợ lý chỉ gợi ý.",))
    reasons: list[str] = []

    if name == "order_create":
        if not has_phone:
            reasons.append("Chưa có số điện thoại của khách để tạo đơn; xin số điện thoại trước.")
        if tier in ("PROBABLE", "AMBIGUOUS"):
            reasons.append("Danh tính khách chưa được xác nhận; hỏi xác nhận trước khi tạo đơn.")
        sku = args.get("sku")
        price = args.get("price_vnd")
        if not sku or price is None:
            reasons.append("Thiếu sku hoặc price_vnd.")
        elif sku not in quotes:
            reasons.append(f"Chưa có báo giá hôm nay cho {sku}; gọi pricing_get_quote trước.")
        elif int(price) != quotes[sku]:
            reasons.append(
                f"price_vnd {format_vnd(int(price))} khác giá hôm nay của {sku} là {format_vnd(quotes[sku])}."
            )
        qty = int(args.get("qty") or 1)
        if price is not None and (args.get("payment") or "COD") == "COD" and int(price) * qty > COD_LIMIT_VND:
            reasons.append(
                f"Đơn COD {format_vnd(int(price) * qty)} vượt giới hạn {format_vnd(COD_LIMIT_VND)}; "
                "đề nghị chuyển khoản hoặc tách đơn."
            )

    elif name == "order_update":
        order_id = args.get("order_id")
        if not order_id:
            reasons.append("Thiếu order_id.")
        elif orders and order_id not in orders:
            reasons.append(f"Đơn {order_id} không thuộc khách đang nói chuyện; tra order_status trước.")

    elif name == "schedule_callback":
        try:
            datetime.fromisoformat(str(args.get("callback_at")))
        except ValueError:
            reasons.append("callback_at phải là ngày giờ ISO 8601, ví dụ 2026-10-17T19:00+07:00.")

    elif name == "handoff_transfer":
        reasons += handoff_problems(args.get("brief") or {})

    return Verdict(not reasons, tuple(reasons))


def handoff_problems(brief: Mapping[str, Any]) -> list[str]:
    """The brief against ``schemas/handoff_brief.schema.json`` itself, after the harness filled it.

    One exception: a chat customer who never gave a number. The consultant
    answers them in the same chat, so the brief goes without a phone; on the
    hotline a person must be able to call back, so the number is asked for.
    """
    problems: list[str] = []
    for error in btc_schemas.errors("handoff_brief", dict(brief)):
        field = error.split(":", 1)[0]
        if field == "customer_phone" and not brief.get("customer_phone"):
            if brief.get("channel") == "hotline":
                problems.append("Chưa có số điện thoại để tư vấn viên gọi lại; xin số điện thoại của khách trước khi chuyển.")
            continue
        problems.append(f"Handoff Brief sai schema ở {error}")
    # Never more than a few lines back to the model: the first ones say enough.
    return problems[:5]


def fill_handoff(brief: Mapping[str, Any], known: Mapping[str, Any]) -> dict[str, Any]:
    """The model's brief with what the harness already knows filled in.

    The harness's values win for identity and time; the model's win for what
    only the conversation knows (reason, summary, open questions, next step).
    """
    filled = {k: v for k, v in known.items() if v is not None or k in ("product_advised", "price_quoted_vnd", "customer_name")}
    filled.update({k: v for k, v in brief.items() if k not in ("customer_phone", "generated_at", "customer_id")})
    filled.setdefault("open_questions", [])
    filled.setdefault("next_action", "Gọi lại khách và trả lời câu hỏi còn mở.")
    filled.setdefault("escalation_reason", "khac")
    return filled
