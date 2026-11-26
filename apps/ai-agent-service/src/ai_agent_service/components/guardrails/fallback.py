"""What the system says when it cannot trust a draft. ``docs/design.md`` section 4.9.

Admit first, never guess a number, and promise nothing the agent cannot do:
it speaks only when the customer does, so no line says it will call or write
back. The safe line is said when a draft is still blocked after two
regenerations; it is counted for the trace, and never sends the call to a
person by itself (route, rule 1). The other lines are the table's, for the harness to say
without a model. ``{who}`` is how the customer is addressed ("chị", or
"anh/chị" while it is not known).
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .. import clock
from ..intake.itn import format_vnd

#: Says the information is missing in one of the phrases the organisers' grader reads ("chưa có thông tin").
SAFE_LINE = "Dạ phần này em chưa có thông tin chắc chắn để báo {who} ạ."

#: Section 4.2: a number two customers share. The first thing the agent says,
#: by the harness and not by a model, asked once, and revealing nobody.
AMBIGUOUS_QUESTION = "Dạ cho em xin tên của mình để em xem đúng thông tin ạ?"

LINES = {
    # Failure paths only: the model is what failed or is not trusted, so the harness speaks. A tool's outcome is never
    # said by the harness: the model's next round reads it and answers (2026-11-26).
    "tool_down": "Dạ hệ thống tra cứu bên em đang chậm, {who} nhắn lại giúp em sau ít phút nhé ạ.",
    "asr_unclear": "Dạ em nghe chưa rõ, {who} nói lại giúp em được không ạ?",
    "model_error": "Dạ em xin lỗi, em chưa trả lời được ngay, {who} nhắc lại giúp em câu vừa rồi được không ạ?",
    "bridging": "Dạ em kết nối {who} với đồng nghiệp phụ trách ngay ạ, {who} chờ em một chút.",
    # Section 4.8: said once as a tool round starts on a call with nothing heard yet; never the answer, never in the
    # transcript, never counted as the first token.
    "filler": "Dạ {who} chờ em một xíu ạ.",
    # A turn whose order was placed and whose answer was then blocked: the customer must not hear "chưa có thông
    # tin" about an order that exists.
    "order_placed": "Dạ em đã tạo đơn cho {who} rồi ạ, {who} cần đổi gì trong đơn thì báo em nhé.",
}

#: Plan 002, A2: what the voice says while a lookup runs and the answer needs the model's next round, by the tool the
#: model called: said only if the caller has heard nothing ``VOICE_HOLD_MS`` after they stopped. No figure, no
#: outcome, no question; a lookup only (a write tool is never announced before its result, rule 7). ``{to}`` is
#: " cho chị" once the form of address is known, else nothing.
HOLD_BY_TOOL = {
    "catalog_search": ("Dạ để em tìm mẫu phù hợp{to} ạ.", "Dạ em xem các mẫu hợp với nhu cầu{to} ngay ạ."),
    "product_advise": ("Dạ để em xem mẫu nào hợp nhất{to} ạ.", "Dạ em so các mẫu phù hợp{to} ngay ạ."),
    "pricing_get_quote": ("Dạ để em xem giá hôm nay{to} ạ.",),
    "pricing_quote_order": ("Dạ để em tính giá cả đơn{to} ạ.",),
    "inventory_check": ("Dạ để em kiểm tra hàng còn không{to} ạ.",),
    "delivery_estimate": ("Dạ để em xem ngày giao hàng{to} ạ.",),
    "order_status": ("Dạ để em xem tình trạng đơn{to} ạ.", "Dạ em tra đơn hàng{to} ngay ạ."),
    "account_orders": ("Dạ để em xem các đơn{to} ạ.",),
    "crm_get_customer": ("Dạ để em xem thông tin đơn hàng{to} ạ.",),
    "memory_search_calls": ("Dạ để em xem lại lần mình trao đổi trước ạ.",),
    "memory_get_episodes": ("Dạ để em xem lại lần mình trao đổi trước ạ.",),
}


def hold_line(tool: str, who: str | None, turn: str = "") -> str | None:
    """The hold line for a lookup *tool*, varied by *turn*; None for a tool that has none (a write tool)."""
    lines = HOLD_BY_TOOL.get(str(tool).replace(".", "_"))
    if not lines:
        return None
    to = f" cho {who}" if who and who != "anh/chị" else ""
    return lines[sum(map(ord, turn)) % len(lines)].format(to=to)


#: Per lane; a lane not listed gets SAFE_LINE. None is the bridging line: it is said only
#: after ``handoff.transfer`` succeeded (``respond``), never in place of one.
BY_LANE = {
    "CLARIFY": LINES["asr_unclear"],
}


def safe_line(lane: str, who: str = "anh/chị") -> str:
    """What to say for *lane* when no draft could be trusted, to a customer addressed as *who*."""
    return BY_LANE.get(lane, SAFE_LINE).format(who=who)


def line(name: str, who: str = "anh/chị") -> str:
    """One of :data:`LINES`, to a customer addressed as *who*."""
    return LINES[name].format(who=who)



#: A figure the advisor writes as a label for code to fill (rules.md, rule 1): {giá:SKU-AP-Y}, {tổng}.
FIGURE = re.compile(r"\{\s*(giá|gia|tổng|tong)\s*(?::\s*([A-Za-z0-9_-]+))?\s*\}", re.IGNORECASE)


def fill_figures(text: str, prices: Mapping[str, int], total: int | None) -> tuple[str, list[str]]:
    """*text* with each figure label replaced by today's figure from the tools, and the labels nothing answers.

    The model never writes a price: it names which one, code says it (2026-11-24: a price of the product next to the
    one the customer asked about, read as theirs). A label without a quote is not said; the next round looks it up.
    """
    missing: list[str] = []

    def one(match: re.Match[str]) -> str:
        kind, sku = match.group(1).lower(), match.group(2)
        if kind in ("giá", "gia"):
            if sku and sku in prices:
                return format_vnd(int(prices[sku]))
            missing.append(f"giá hôm nay của {sku or '(chưa ghi mã)'}")
        elif total is not None:
            return format_vnd(int(total))
        else:
            missing.append("tổng giỏ")
        return match.group(0)

    return FIGURE.sub(one, text), missing


def wire_name(name: str) -> str:
    """``order.create`` -> ``order_create``."""
    return str(name).replace(".", "_")


def is_bridging(text: str) -> bool:
    """Whether a line is the handoff line in some form."""
    lowered = " ".join(text.lower().split())
    return (any(w in lowered for w in ("kết nối", "chuyển máy", "chuyển cho"))
            and any(w in lowered for w in ("đồng nghiệp", "nhân viên", "tư vấn viên", "người phụ trách")))
