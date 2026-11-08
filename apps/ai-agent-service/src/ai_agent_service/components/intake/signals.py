"""What the customer's words hint at, by rule: notes for the advisor, never a decision. ``docs/design.md`` 4.1, 4.3.

Each detector reads the turn as intake left it (cleaned, NFC), lower case
and without diacritics, so "khong", "ko" and "không" are one word.

| Signal | Used by |
|---|---|
| ``impatient`` ("hỏi rồi mà", "lâu quá") | the PB-10 note on the lane (section 4.3) |

A word list only adds a note the advisor reads. Nothing here allows or
refuses an action: whether the customer wants a person, agreed to a
deletion or wants one more order is read in context by the PolicyAgent on
the PolicyAgent (``agents/policy.py``, ``INTENTS``). Word lists made those decisions
until 2026-11-01 and got them wrong both ways (a request for a person not
heard, a product question taken for a medical one).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .text import plain

IMPATIENT = re.compile(
    r"\b(hoi roi ma|noi roi ma|noi roi|da noi|hoi roi|lau qua|mat thoi gian|bao nhieu lan|may lan roi|nhac lai mai|"
    r"chan qua|met qua|bo tay|nhanh len)\b")


@dataclass(frozen=True)
class Signals:
    """What one turn of the customer signals."""

    impatient: bool = False

    def as_flags(self) -> dict[str, bool]:
        return asdict(self)


def read(text: str | None) -> Signals:
    """Every signal of *text*; all false for an empty turn."""
    if not text:
        return Signals()
    said = plain(text)
    return Signals(
        impatient=bool(IMPATIENT.search(said)),
    )
