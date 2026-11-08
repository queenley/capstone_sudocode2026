"""The call's working state: written by code each turn, read by the advisor at the end of its prompt.

A summary of old turns is a model's reading and arrives only once a call is long. This is what must never be lost at
any length: what the customer said they need, the product last quoted, and the question they are answering. Only the
customer's words go in, tokenised, by the same rules ``MemoryAgent`` falls back on.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ...agents.memory import rules_from_words
from ...components.memory import brief

#: Slots the customer states and the agent must not ask again in this call.
KEPT = ("room_area_m2", "has_children", "child_age_months", "budget_vnd", "quantity", "size", "color", "payment",
        "delivery_area", "blocker", "preferred_channel")
#: The reply's last sentence, when it is a question.
LAST_QUESTION = re.compile(r"([^.!?\n]*\?)\s*$")


def heard(said: str, facts: Mapping[str, Any] | None) -> dict[str, Any]:
    """*facts* with what this turn's words state, newest word winning."""
    found = rules_from_words([{"speaker": "customer", "text": said, "turn": 1}])
    return {**(facts or {}), **{c.slot: c.value for c in found if c.slot in KEPT}}


def open_question(reply: str | None) -> str | None:
    match = LAST_QUESTION.search(reply or "")
    return match.group(1).strip() if match else None


def lines(facts: Mapping[str, Any] | None, quotes: Mapping[str, int] | None, reply: str | None) -> tuple[str, ...]:
    """The state in the advisor's language, nothing for what is not known."""
    out = []
    if facts:
        said = "; ".join(brief.spoken(name, facts[name]) for name in KEPT if name in facts)
        out.append(f"Khách đã nói trong cuộc này (không hỏi lại): {said}.")
    if quotes:
        out.append(f"Sản phẩm vừa báo giá: {list(quotes)[-1]}.")
    question = open_question(reply)
    if question:
        out.append(f"Em đang chờ khách trả lời: {question}")
    return tuple(out)
