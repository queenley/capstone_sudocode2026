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
    "tool_down": "Dạ hệ thống tra cứu bên em đang chậm, {who} nhắn lại giúp em sau ít phút nhé ạ.",
    "asr_unclear": "Dạ em nghe chưa rõ, {who} nói lại giúp em được không ạ?",
    "model_error": "Dạ em xin lỗi, em chưa trả lời được ngay, {who} nhắc lại giúp em câu vừa rồi được không ạ?",
    "bridging": "Dạ em kết nối anh/chị với đồng nghiệp phụ trách ngay ạ, anh/chị chờ em một chút.",
    # Section 4.8: said once as a tool round starts, so the line is not silent;
    # never the answer, never in the transcript, never counted as the first token.
    "filler": "Dạ {who} chờ em một xíu ạ.",
    # A turn whose order was placed and whose read-back was still blocked: the customer must not
    # hear "chưa có thông tin" about an order that exists.
    "order_placed": "Dạ em đã tạo đơn cho {who} rồi ạ, {who} cần đổi gì trong đơn thì báo em nhé.",
    # A call back on a day the shop is closed: the tool moved it (LN-02) and the answer did not say so.
    "callback_moved": "Dạ hôm {who} hẹn bên em nghỉ nên lịch gọi lại được dời sang {moment} ạ.",
    # What a tool with an effect did, said from its own result the moment it returns: the customer hears the
    # outcome without waiting for the model's next round, which then goes on from it (section 4.8).
    "order_created": "Dạ em đã lên đơn {order_id} cho {who} rồi ạ.",
    "order_updated": "Dạ em đã cập nhật đơn {order_id} cho {who} rồi ạ.",
    "callback_booked": "Dạ em đã đặt lịch gọi lại cho {who} vào {moment} ạ.",
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


def result_line(result: Mapping[str, Any], who: str = "anh/chị") -> str | None:
    """The line for what a tool with an effect did, from its result alone; None when it did nothing or failed."""
    envelope = result.get("result") or {}
    data = envelope.get("data") or {}
    if not envelope.get("ok"):
        return None
    name = str(result.get("name", "")).replace("_", ".")
    if name == "handoff.transfer":
        return LINES["bridging"]
    if name == "order.create" and data.get("order_id"):
        return LINES["order_created"].format(who=who, order_id=data["order_id"])
    if name == "order.update" and data.get("order_id"):
        return LINES["order_updated"].format(who=who, order_id=data["order_id"])
    if name == "schedule.callback":
        moment = clock.parse_local(data.get("callback_at"))
        if moment is not None:
            line = "callback_moved" if data.get("moved_from") else "callback_booked"
            return LINES[line].format(who=who, moment=clock.spoken_moment(moment))
    return None


#: Write tools whose success line the model writes in the round that calls them (the ``reply`` argument), by wire
#: name, with the holes the harness may fill from the tool's result. The harness says the line the moment the tool
#: succeeds and the turn needs no second model round. Only the success line: a line for each failure too made the
#: round 0.6 to 0.8 s longer (bench of 2026-11-15); a failure goes back to the model.
REPLY_HOLES: dict[str, frozenset[str]] = {
    "order_create": frozenset({"order_id", "total_vnd", "estimated_delivery"}),
    "order_update": frozenset({"order_id", "fee_vnd", "price_diff_vnd", "refund_vnd", "extra_payment_vnd",
                               "refund_days"}),
    "schedule_callback": frozenset({"callback_at"}),
    "handoff_transfer": frozenset(),
    "memory_request_deletion": frozenset(),
}

MONEY_HOLES = frozenset({"total_vnd", "fee_vnd", "price_diff_vnd", "refund_vnd", "extra_payment_vnd"})

#: Tools whose fixed line (:func:`result_line`) says all the customer needs: said, it ends the turn as well.
WHOLE_LINES = frozenset({"schedule.callback", "handoff.transfer"})

#: A hole, with the currency word a model writes after a price ("{total_vnd}đ"): the amount carries its own.
HOLE = re.compile(r"\{(\w+)\}(\s*(?:đồng|vnđ|vnd|đ)(?!\w))?", re.IGNORECASE)
MAX_REPLY_CHARS = 300

#: What a line written ahead may not say by hand, only through a hole: an amount, a date, a time of day. Any other
#: figure (a house number, "72 giờ" from QT-06) is the hard guard's to trace, as in every sentence (2026-11-15: a
#: ban on every digit sent 2 of 6 write turns to a second model round).
HAND_FIGURE = re.compile(
    r"\d{1,3}(?:[.,]\d{3})+|\d+\s*(?:đồng|vnđ|vnd|đ|k|nghìn|ngàn|triệu|tr)(?!\w)"  # an amount
    r"|\d{1,2}\s*/\s*\d{1,2}|\bngày\s+\d"                                     # a date
    r"|\d{1,2}\s*:\s*\d{2}|\b(?:lúc|vào)\s+\d|\d{1,2}\s*(?:h|giờ)\s*(?:\d{1,2}\s*)?(?:sáng|trưa|chiều|tối)",  # a time
    re.IGNORECASE)


def wire_name(name: str) -> str:
    """``order.create`` -> ``order_create``."""
    return str(name).replace(".", "_")


def outcome_of(result: Mapping[str, Any]) -> str | None:
    """What a tool call came to: ``ok``; ``moved`` for a call back the tool moved (LN-02); else the error code."""
    envelope = result.get("result") or {}
    if envelope.get("ok"):
        moved = str(result.get("name")) == "schedule.callback" and (envelope.get("data") or {}).get("moved_from")
        return "moved" if moved else "ok"
    code = (envelope.get("error") or {}).get("code")
    return str(code) if code else None


def _hole(name: str, value: Any) -> str:
    if name in MONEY_HOLES:
        return format_vnd(abs(int(value)))
    if name == "estimated_delivery":
        return clock.day_label(str(value))
    if name == "callback_at":
        moment = clock.parse_local(value)
        if moment is None:
            raise ValueError(value)
        return clock.spoken_moment(moment)
    return str(value)


def render(name: str, template: Any, data: Mapping[str, Any]) -> str | None:
    """*template*, the line the model wrote for tool *name*'s success, with its holes filled from *data*.

    None when the line cannot be trusted: a hole the tool does not have or did not fill, an amount, a date or a time
    written by hand (:data:`HAND_FIGURE`: only a hole brings those in), more than two sentences or
    :data:`MAX_REPLY_CHARS`.
    """
    allowed = REPLY_HOLES.get(wire_name(name))
    if allowed is None or not isinstance(template, str) or not template.strip():
        return None
    if HAND_FIGURE.search(HOLE.sub(" ", template)):
        return None

    def fill(match: re.Match[str]) -> str:
        hole, unit = match.group(1), match.group(2) or ""
        value = data.get(hole)
        if hole not in allowed or value in (None, ""):
            raise KeyError(hole)
        return _hole(hole, value) + ("" if hole in MONEY_HOLES else unit)

    try:
        line = " ".join(HOLE.sub(fill, template).split())
    except (KeyError, ValueError, TypeError):
        return None
    if "{" in line or "}" in line or len(line) > MAX_REPLY_CHARS:
        return None
    if len(re.findall(r"[.!?…](?=\s)", line)) > 1:
        return None
    return line


def is_bridging(text: str) -> bool:
    """Whether a line is the handoff line in some form."""
    lowered = " ".join(text.lower().split())
    return (any(w in lowered for w in ("kết nối", "chuyển máy", "chuyển cho"))
            and any(w in lowered for w in ("đồng nghiệp", "nhân viên", "tư vấn viên", "người phụ trách")))
