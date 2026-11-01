"""The routing table of ``docs/design.md`` section 4.3, applied. Pure, so every row is a unit test.

| # | Condition | Lane |
|---|---|---|
| 1 | tools failing in a row, or the model failing in a row | HANDOFF |
| 2 | ``asr_low_conf`` | CLARIFY |
| 3 | tier PROBABLE or AMBIGUOUS, while the one confirming question is out | CONFIRM_IDENTITY |
| 4 | VERIFIED with a brief | CONTINUITY |
| 5 | anything else | NEW |

Safe lines are not a reason to hand over: a guard that blocks wrongly twice
would turn its own mistake into a transfer the grader counts as
``over_escalation`` (seen 2026-10-25, SCN-GEN-0007).

Every row reads a state the code knows for certain: the failure counters,
the recogniser's confidence, the identity tier, whether a brief exists. No
row guesses what the customer is talking about. What a turn is about (an
order, a product, a policy, a topic that must go to a person) is read from
the customer's words in context, which is the advisor's job: CONTINUITY and
NEW carry every business tool, and the advisor picks the ones the turn needs.
A lane chosen from the words would take tools away on a wrong guess, and the
turn could not recover from it.

:class:`RouteInput` is everything ``route`` may read: the enforcement is the
signature, since a field that is not here cannot be read.

A lane's instruction gains notes when they apply: PB-10 when the customer is
impatient, PB-11 after three contacts without a close, PB-06 when the words
touch on health, medicine or pregnancy, and on a shared number whose name
question went unanswered, what may not be said (section 4.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Lane = Literal["HANDOFF", "CLARIFY", "CONFIRM_IDENTITY", "CONTINUITY", "NEW"]

#: Rule 1: consecutive infrastructure failures of tools.
TOOL_FAILURES = 2
#: Rule 1: consecutive turns the model could not answer.
MODEL_FAILURES = 2
#: PB-11: contacts without a close before the agent stops pressing.
SESSIONS_WITHOUT_CLOSE = 3

#: The notes a lane's instruction gains, in the advisor's language.
NOTES = {
    "impatient": "Khách đang bực: xin lỗi ngắn một câu, đi thẳng vào việc, tối đa một câu xác nhận (PB-10).",
    "no_close": ("Khách đã liên hệ từ 3 lần mà chưa chốt: không ép, ghi nhận nhu cầu, chỉ hẹn liên hệ lại khi có "
                 "chương trình mới (PB-11)."),
    "pb06": ("Lời khách có nhắc tới sức khỏe, thuốc, thai sản hoặc pháp lý (PB-06). Khách xin lời khuyên y tế, về "
             "thuốc, về an toàn cho mẹ, bé hay người bệnh, hoặc về pháp lý: nói \"Dạ hiện em chưa có thông tin về …\" "
             "rồi gọi handoff_transfer (y tế, thuốc, thai sản: escalation_reason cau_hoi_y_te). Khách chỉ hỏi sản "
             "phẩm (máy hút sữa, đồ cho bé, thông số, giá, tồn kho), kể cả khi kể mình đang mang thai hay cho con bú: "
             "tư vấn bình thường bằng tool, với sản phẩm mẹ và bé chỉ nêu thông số hãng công bố, không chuyển máy."),
    "unconfirmed": ("Số này thuộc nhiều người và khách chưa cho biết là ai: tư vấn chung như khách mới, không đọc "
                    "thông tin riêng của ai, không nói về lần tư vấn trước, không hỏi lại tên; khách hỏi về đơn riêng "
                    "thì nói em chưa xem được khi chưa xác nhận và đề nghị chuyển nhân viên."),
}


@dataclass(frozen=True)
class RouteInput:
    tier: Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
    has_brief: bool
    asr_low_conf: bool
    tool_failures: int
    #: Turns in a row whose draft the model could not produce (an error, a timeout).
    model_failures: int = 0
    #: PB-06: health, pregnancy, medicine, legal words in the turn. A note, never a lane:
    #: "máy hút sữa cho con bú" names the topic and is a product question.
    must_transfer: bool = False
    impatient: bool = False
    #: Previous contacts that ended without an order (PB-11).
    sessions_without_close: int = 0
    #: The confirming question is still to be asked or answered. Once it has
    #: been asked and not answered, the call goes on as a stranger's
    #: (section 4.2: the question is asked once).
    awaiting_identity: bool = True


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
    if view.must_transfer and lane in ("CONTINUITY", "NEW"):
        notes.append(NOTES["pb06"])
    if view.sessions_without_close >= SESSIONS_WITHOUT_CLOSE and lane in ("CONTINUITY", "NEW"):
        notes.append(NOTES["no_close"])
    if view.tier == "AMBIGUOUS" and lane != "CONFIRM_IDENTITY":
        notes.append(NOTES["unconfirmed"])
    return RouteDecision(lane, rule, reason, tuple(notes))


def _table(view: RouteInput) -> tuple[Lane, int, str]:
    if view.tool_failures >= TOOL_FAILURES:
        return "HANDOFF", 1, "tools failing"
    if view.model_failures >= MODEL_FAILURES:
        return "HANDOFF", 1, "the model failing"
    if view.asr_low_conf:
        return "CLARIFY", 2, "the recognition was unclear"
    if view.tier in ("PROBABLE", "AMBIGUOUS") and view.awaiting_identity:
        return "CONFIRM_IDENTITY", 3, f"identity {view.tier.lower()}"
    if view.tier == "VERIFIED" and view.has_brief:
        return "CONTINUITY", 4, "a returning customer with a brief"
    return "NEW", 5, "default"
