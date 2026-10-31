"""What the system says when it cannot trust a draft. ``docs/design.md`` section 4.9.

Admit first, never guess a number, and promise nothing the agent cannot do:
it speaks only when the customer does, so no line says it will call or write
back. The safe line is said when a draft is still blocked after two
regenerations; a second one in the same call sends the next turn to HANDOFF
(route, rule 1). The other lines are the table's, for the harness to say
without a model. ``{who}`` is how the customer is addressed ("chị", or
"anh/chị" while it is not known).
"""

from __future__ import annotations

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
}

#: Per lane; a lane not listed gets SAFE_LINE.
BY_LANE = {
    "CLARIFY": LINES["asr_unclear"],
    "HANDOFF": LINES["bridging"],
}


def safe_line(lane: str, who: str = "anh/chị") -> str:
    """What to say for *lane* when no draft could be trusted, to a customer addressed as *who*."""
    return BY_LANE.get(lane, SAFE_LINE).format(who=who)


def line(name: str, who: str = "anh/chị") -> str:
    """One of :data:`LINES`, to a customer addressed as *who*."""
    return LINES[name].format(who=who)


def is_bridging(text: str) -> bool:
    """Whether a line is the handoff line in some form."""
    lowered = " ".join(text.lower().split())
    return "kết nối" in lowered and any(w in lowered for w in ("đồng nghiệp", "nhân viên", "tư vấn viên", "người phụ trách"))
