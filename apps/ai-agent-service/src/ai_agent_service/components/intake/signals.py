"""What the customer's words signal, by rule. ``docs/design.md`` sections 4.1 (the turn's flags) and 4.3.

Each detector reads the turn as intake left it (cleaned, NFC), lower case
and without diacritics, so "khong", "ko" and "không" are one word. They are
cheap, deterministic and explainable, which is why routing and the
before-write checks lean on them rather than on a model:

| Signal | Used by |
|---|---|
| ``impatient`` ("hỏi rồi mà", "lâu quá") | the PB-10 note on the lane (section 4.3) |
| ``wants_person``, ``complaint`` | the only reasons, besides PB-06 and HANDOFF, ``handoff.transfer`` may run (section 4.4) |
| ``asks_if_human`` | the PB-07 reminder |
| ``wants_deletion`` | the QT-06 flow before ``memory.request_deletion`` |
| ``must_transfer`` | route rule 5: medical, pregnancy, medicine, legal (PB-06) |

Each is a category the shop's policy defines, not a reading of what one
customer meant: whether a question is for the documents or for a tool, and
whether the documents answer it, are the advisor's to judge, by its
instructions.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .text import plain

IMPATIENT = re.compile(
    r"\b(hoi roi ma|noi roi ma|noi roi|da noi|hoi roi|lau qua|mat thoi gian|bao nhieu lan|may lan roi|nhac lai mai|"
    r"chan qua|met qua|bo tay|nhanh len)\b")
WANTS_PERSON = re.compile(
    r"\b(chuyen may|gap (nhan vien|nguoi that|quan ly|tu van vien|nguoi phu trach)|"
    r"noi chuyen (voi|cung) (nhan vien|nguoi that|quan ly)|(chuyen|noi) (cho|sang|qua) (nhan vien|nguoi that|quan ly)|"
    r"cho (toi|chi|anh|em|minh) (gap|noi chuyen voi) (nhan vien|nguoi that|quan ly))\b")
COMPLAINT = re.compile(
    r"\b(khieu nai|to cao|lua dao|boi thuong|kien (ra toa|cong ty|shop|ben em)|hang gia|hang dom|chay no|bi thuong|"
    r"nguy hiem|phan anh len|len bao)\b")
ASKS_IF_HUMAN = re.compile(
    r"\b(nguoi hay (la )?may|nguoi that (hay|khong|a)|co phai (la )?(nguoi|may|bot|robot|tro ly ao|ai)\b|"
    r"(em|ban) la (nguoi|may|bot|robot|ai)\b|dang noi chuyen voi (may|bot|nguoi))")
WANTS_DELETION = re.compile(
    r"\b(xoa|huy|go)\b[^.?!]*\b(du lieu|thong tin|so dien thoai|sdt|ho so|tai khoan)\b|"
    r"\bkhong (muon|cho) (luu|giu)\b")
#: PB-06: questions that must go to a person, whatever the documents say.
#: Whole phrases: without diacritics "thuốc" and "thuộc" look alike.
MUST_TRANSFER = re.compile(
    r"\b(cho con bu|dang bau|mang thai|co thai|benh nhan|bi benh|benh ly|uong thuoc|thuoc men|di ung|"
    r"hen suyen|bac si|y te|phap ly|kien tung|luat su)\b")


@dataclass(frozen=True)
class Signals:
    """What one turn of the customer signals."""

    impatient: bool = False
    wants_person: bool = False
    complaint: bool = False
    asks_if_human: bool = False
    wants_deletion: bool = False
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
        wants_person=bool(WANTS_PERSON.search(said)),
        complaint=bool(COMPLAINT.search(said)),
        asks_if_human=bool(ASKS_IF_HUMAN.search(said)),
        wants_deletion=bool(WANTS_DELETION.search(said)),
        must_transfer=bool(MUST_TRANSFER.search(said)),
    )
