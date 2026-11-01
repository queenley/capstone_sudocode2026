"""What the customer's words hint at, by rule: notes for the advisor, never a decision. ``docs/design.md`` 4.1, 4.3.

Each detector reads the turn as intake left it (cleaned, NFC), lower case
and without diacritics, so "khong", "ko" and "không" are one word.

| Signal | Used by |
|---|---|
| ``impatient`` ("hỏi rồi mà", "lâu quá") | the PB-10 note on the lane (section 4.3) |
| ``must_transfer`` (medical, pregnancy, medicine, legal words) | the PB-06 note on the lane |
| ``ORDER_TALK`` | the knowledge search's policy version, by the day the order was placed |

A word list only adds a note the advisor reads. Nothing here allows or
refuses an action: whether the customer wants a person, agreed to a
deletion or wants one more order is read in context by the PolicyAgent on
Jev (``agents/policy.py``, ``INTENTS``). Word lists made those decisions
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

#: PB-06: words of a topic that may have to go to a person. A note for the advisor, never a lane:
#: "máy hút sữa cho con bú" names the topic and is a product question (PB-06 itself says to
#: give the maker's specifications for mother-and-baby products).
#: Whole phrases: without diacritics "thuốc" and "thuộc" look alike.
MUST_TRANSFER = re.compile(
    r"\b(cho con bu|dang bau|ba bau|me bau|mang thai|co thai|benh nhan|bi benh|benh ly|uong thuoc|thuoc men|di ung|"
    r"hen suyen|bac si|y te|phap ly|kien tung|luat su)\b")

#: The turn mentions an order: picks the policy version in force on that order's day for the
#: knowledge search. Not routing: the advisor reads what the turn is about.
ORDER_TALK = re.compile(
    r"\b(don hang|don cua|ma don|od\d+|dang giao|giao chua|giao den dau|den dau roi|khi nao giao|doi size|"
    r"doi sang|doi mau|doi san pham|tra hang|hoan tien|doi dia chi|sua dia chi|trang thai don|nhan hang|"
    r"van don|chat qua|rong qua|bi loi)\b"
)


@dataclass(frozen=True)
class Signals:
    """What one turn of the customer signals."""

    impatient: bool = False
    must_transfer: bool = False

    def as_flags(self) -> dict[str, bool]:
        return asdict(self)


def read(text: str | None) -> Signals:
    """Every signal of *text*; all false for an empty turn."""
    if not text:
        return Signals()
    said = plain(text)
    return Signals(
        impatient=bool(IMPATIENT.search(said)),
        must_transfer=bool(MUST_TRANSFER.search(said)),
    )
