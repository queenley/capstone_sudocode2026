"""How a customer the shop does not know yet calls themselves: anh, chị, cô, chú, bác.

A known customer is addressed as their profile says (``nodes._address_as``).
Someone new is "anh/chị" until they say which, and they usually do, in passing:
"chị muốn hỏi máy lọc nước", "anh cần đặt đơn", or by answering the agent's
one question about it ("Dạ cho em hỏi mình xưng hô là anh hay chị ạ?" -> "chị ạ").
The words they address the shop with do not count: in "chào chị" the customer
calls the assistant chị. "em" is not taken either: a customer who calls
themselves em is still addressed as anh/chị by the shop's staff.
"""

from __future__ import annotations

import re

from .text import plain

#: The forms of address the shop uses, as written plain (no accents) -> as said.
FORMS = {"anh": "anh", "chi": "chị", "co": "cô", "chu": "chú", "bac": "bác"}
_FORM = r"(anh|chi|co|chu|bac)"

#: "chị muốn ...", "anh cần ...": the pronoun opening a clause, then what they do.
_SELF = re.compile(
    rf"(?:^|[,.;!?]\s*|\b(?:thi|vay|ma|nen|con)\s+){_FORM}\s+"
    r"(muon|can|hoi|dang|dinh|mua|dat|lay|chon|thay|co|o|ten|la|chua|da|se|xin|nho|vua|cung|thi|tinh|dung|nghi|thich|o)\b"
)
#: "tôi là chị Lan", "mình là anh Nam".
_IS = re.compile(rf"\b(?:toi|minh)\s+la\s+{_FORM}\b")
#: The agent asked how to address the customer.
ASKED = re.compile(r"\b(anh hay chi|chi hay anh|xung ho)\b")
#: The customer's answer to that question: little more than the form itself.
_ANSWER = re.compile(rf"^(?:da\s+|la\s+|goi\s+)?{_FORM}(?:\s+(?:a|nhe|nha|nhen|ne|day|do|ten\s+\w+))*\s*[.!]?$")


def self_reference(said: str | None, *, agent_asked: str | None = None) -> str | None:
    """The form of address *said* gives for its speaker, or None.

    *agent_asked* is the agent's previous reply: when it asked "anh hay chị",
    a bare "chị ạ" is the answer.
    """
    text = plain(said or "").strip()
    if not text:
        return None
    if agent_asked and ASKED.search(plain(agent_asked)):
        answer = _ANSWER.match(text)
        if answer:
            return FORMS[answer.group(1)]
    found = _IS.search(text) or _SELF.search(text)
    return FORMS[found.group(1)] if found else None
