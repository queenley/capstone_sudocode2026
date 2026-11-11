"""What one turn needs in its prompt: the brief lines it can use.

A guess from the customer's words may only keep guidance for the turn; it never takes a tool away or decides anything
(``components.orchestration.rules``). So every doubt keeps more, not less: the brief is whole on the call's first turn,
on a turn with no recognised topic and after a block. Otherwise it keeps what is open and what the topic reads, and
drops the history already said. ``must_not_ask`` stays in the lane's instruction either way, and a line's number never
changes, so ``[Bn]`` still traces back to its facts. The rules and every skill are always whole (2026-11-10: the
situational rule packs were removed; they had left the prompt and contradicted the skills).

``ADVISOR_CONTEXT=full`` turns it off: every line, the before of a before/after measurement.
"""

from __future__ import annotations

import os
import re
from typing import Any, Mapping, Sequence

from ..intake.text import plain

#: Most brief lines of a focused turn: what is open is kept beyond it, the rest fills it.
MAX_LINES = 6

TOPICS = {
    "purchase": re.compile(r"\b(mua|lay|dat|chot|len don|giao|ship|thanh toan|cod|chuyen khoan|gia|bao nhieu|size|mau)\b"),
    "orders": re.compile(r"\b(don|van don|giao chua|doi size|doi hang|doi san pham|tra hang|hoan tien|doi dia chi)\b"),
    "callback": re.compile(r"\b(goi lai|hen|lien he lai|bao lai|ban voi|hoi y kien|hoi (chong|vo|ong xa|ba xa|nguoi nha|gia dinh|bo me)"
                           r"|suy nghi|can nhac)\b"),
    "objection": re.compile(r"\b(dat|mac|so sanh|ben khac|cho khac|shop khac|re hon|giam gia|bot|khuyen mai|km|het han|gia cu)\b"),
    "advice": re.compile(r"\b(tu van|san pham|dang tim|can tim|loai nao|mau nao|phong|ngan sach|phu hop|nen chon|goi y|con hang|het hang"
                         r"|mua|lay|dat|gia|size)\b"),
}
#: The brief's lines a topic reads, by ``BriefLine.kind``.
LINES_FOR = {"purchase": ("need", "product", "quote"), "advice": ("need", "product", "quote"),
             "objection": ("product", "quote", "need"), "orders": ("order", "product"), "callback": ("product", "quote")}
#: Kept on every turn: what is unfinished, and what must be checked with the customer.
ALWAYS = ("open", "other")


def full() -> bool:
    return os.environ.get("ADVISOR_CONTEXT", "").strip().lower() == "full"


def topics(text: str | None) -> set[str]:
    words = plain(text or "").lower()
    return {name for name, pattern in TOPICS.items() if pattern.search(words)}


def lines(brief: Sequence[Any], said: str | None, *, first_turn: bool, blocked: bool) -> list[Any]:
    """The brief lines of this turn, in their order and with their numbers."""
    wanted = [kind for topic in sorted(topics(said)) for kind in LINES_FOR.get(topic, ())]
    if full() or first_turn or blocked or not wanted:
        return list(brief)
    keep = {id(line) for line in brief if line.kind in ALWAYS}
    for kind in dict.fromkeys(wanted):
        for line in brief:
            if line.kind == kind and len(keep) < MAX_LINES:
                keep.add(id(line))
    return [line for line in brief if id(line) in keep]


def stats(prompt_tokens: int, cut: Sequence[str], shown: int, held: int) -> Mapping[str, Any]:
    """What a reader of the run needs to see this turn's prompt was whole."""
    return {"tokens": prompt_tokens, "cut": list(cut), "brief_shown": shown, "brief_held": held}
