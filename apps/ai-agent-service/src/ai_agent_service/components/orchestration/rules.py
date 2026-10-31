"""The routing table of ``docs/design.md`` section 4.3, applied. Pure, so every row is a unit test.

| # | Condition | Lane |
|---|---|---|
| 1 | tools failing in a row, or ``guard`` fell back to the safe line twice in the call | HANDOFF |
| 2 | ``asr_low_conf`` | CLARIFY |
| 3 | tier PROBABLE or AMBIGUOUS, while the one confirming question is out | CONFIRM_IDENTITY |
| 4 | the customer has an order and the turn is about it, or answers what the agent just asked about it | ORDER_SERVICE |
| 5 | a topic that must go to a person (PB-06) | OUT_OF_SCOPE |
| 6 | VERIFIED with a brief | CONTINUITY |
| 7 | anything else | NEW |

:class:`RouteInput` is everything ``route`` may read: the enforcement is the
signature, since a field that is not here cannot be read.

What needs reading the customer's words in context is not routed: whether
the documents answer a question, whether the caller is the person the brief
is about, how to answer a price objection. Those are the advisor's, by its
instructions, with the turn's passages and the brief in front of it.

A lane's instruction gains notes when they apply: PB-10 when the customer is
impatient, PB-11 after three contacts without a close, and on a shared number
whose name question went unanswered, what may not be said (section 4.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..intake.text import plain

Lane = Literal["HANDOFF", "CLARIFY", "CONFIRM_IDENTITY", "ORDER_SERVICE", "OUT_OF_SCOPE", "CONTINUITY", "NEW"]

#: Rule 1: consecutive infrastructure failures of tools.
TOOL_FAILURES = 2
#: Rule 1: safe lines said in one call.
SAFE_LINES = 2
#: PB-11: contacts without a close before the agent stops pressing.
SESSIONS_WITHOUT_CLOSE = 3

ORDER_TALK = re.compile(
    r"\b(don hang|don cua|ma don|od\d+|dang giao|giao chua|giao den dau|den dau roi|khi nao giao|doi size|"
    r"doi sang|doi mau|doi san pham|tra hang|hoan tien|doi dia chi|sua dia chi|trang thai don|nhan hang|"
    r"van don|chat qua|rong qua|bi loi)\b"
)
ORDER_LOOKUP = re.compile(r"\b(?:tinh trang don|trang thai don|don hang\b[^.!?]*\b(?:o dau|den dau|toi dau|giao chua))\b")

#: The notes a lane's instruction gains, in the advisor's language.
NOTES = {
    "impatient": "Khách đang bực: xin lỗi ngắn một câu, đi thẳng vào việc, tối đa một câu xác nhận (PB-10).",
    "no_close": ("Khách đã liên hệ từ 3 lần mà chưa chốt: không ép, ghi nhận nhu cầu, chỉ hẹn liên hệ lại khi có "
                 "chương trình mới (PB-11)."),
    "unconfirmed": ("Số này thuộc nhiều người và khách chưa cho biết là ai: tư vấn chung như khách mới, không đọc "
                    "thông tin riêng của ai, không nói về lần tư vấn trước, không hỏi lại tên; khách hỏi về đơn riêng "
                    "thì nói em chưa xem được khi chưa xác nhận và đề nghị chuyển nhân viên."),
}


@dataclass(frozen=True)
class RouteInput:
    tier: Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
    has_brief: bool
    has_order: bool
    asr_low_conf: bool
    tool_failures: int
    safe_lines: int
    #: Tokenised, as intake left it. None on the opening turn.
    customer_said: str | None
    #: PB-06: medical, pregnancy, medicine, legal.
    must_transfer: bool = False
    impatient: bool = False
    #: Previous contacts that ended without an order (PB-11).
    sessions_without_close: int = 0
    #: The confirming question is still to be asked or answered. Once it has
    #: been asked and not answered, the call goes on as a stranger's
    #: (section 4.2: the question is asked once).
    awaiting_identity: bool = True
    #: The lane of the previous turn, and whether the agent's reply then asked
    #: the customer something: an answer belongs to the task its question did
    #: ("Địa chỉ mới là Hải Châu" says no "đơn", and is still about the order).
    previous_lane: str | None = None
    answering: bool = False


@dataclass(frozen=True)
class RouteDecision:
    """What was decided, by which row, and the notes for the lane. Kept for the trace and QA."""

    lane: Lane
    rule: int
    reason: str
    notes: tuple[str, ...] = ()


def decide(view: RouteInput) -> RouteDecision:
    """The whole table, first match wins, then the notes."""
    lane, rule, reason = _table(view)
    notes = []
    if view.impatient:
        notes.append(NOTES["impatient"])
    if view.sessions_without_close >= SESSIONS_WITHOUT_CLOSE and lane in ("CONTINUITY", "NEW"):
        notes.append(NOTES["no_close"])
    if view.tier == "AMBIGUOUS" and lane != "CONFIRM_IDENTITY":
        notes.append(NOTES["unconfirmed"])
    return RouteDecision(lane, rule, reason, tuple(notes))


def _table(view: RouteInput) -> tuple[Lane, int, str]:
    said = plain(view.customer_said or "")
    if view.tool_failures >= TOOL_FAILURES or view.safe_lines >= SAFE_LINES:
        return "HANDOFF", 1, "tools failing" if view.tool_failures >= TOOL_FAILURES else "two safe lines in this call"
    if view.asr_low_conf:
        return "CLARIFY", 2, "the recognition was unclear"
    if view.tier in ("PROBABLE", "AMBIGUOUS") and view.awaiting_identity:
        return "CONFIRM_IDENTITY", 3, f"identity {view.tier.lower()}"
    if (view.has_order and ORDER_TALK.search(said)) or (view.tier == "VERIFIED" and ORDER_LOOKUP.search(said)):
        return "ORDER_SERVICE", 4, "about an existing order"
    if view.has_order and view.previous_lane == "ORDER_SERVICE" and view.answering and not view.must_transfer:
        return "ORDER_SERVICE", 4, "answering the agent's question about an order"
    if view.must_transfer:
        return "OUT_OF_SCOPE", 5, "a topic that must go to a person (PB-06)"
    if view.tier == "VERIFIED" and view.has_brief:
        return "CONTINUITY", 6, "a returning customer with a brief"
    return "NEW", 7, "default"
