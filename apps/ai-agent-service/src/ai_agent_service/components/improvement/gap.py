"""The Knowledge Gap Loop's gate for an entry a consultant saved. ``docs/design.md`` section 10.2.

A consultant answers a question the agent could not, and saves the answer
from the console. The entry waits, not served, until a person approves it;
approving runs the checks of section 10.2 that code can make:

| Gate | Checked here |
|---|---|
| 2 | no amount of money, no promotion code, no stock status: those always come from a tool (principle 5) |
| 3 | no entry on a topic that must go to a person (PB-06) |
| 7 | a person approves (the call that runs this gate) |

Gates 1 and 4 (every sentence follows from a passage in force, no
contradiction with an entry already there) need reading, and gates 5 and 6
are the evaluation's: they are the reviewer's to judge, and the measured
rounds' (section 10.4).
"""

from __future__ import annotations

import re

from ..intake.signals import MUST_TRANSFER
from ..intake.text import plain
from .lessons import MONEY, promo_codes

#: Stock is the tools' to say, on the plain (unaccented) text.
STOCK = re.compile(r"\b(con hang|het hang|ton kho|sap ve hang|con \d+ (?:cai|chiec|san pham|bo))\b")


def gate(question: str, answer: str) -> tuple[str, ...]:
    """Why an entry may not go live; empty when the checks find nothing."""
    text = f"{question}\n{answer}"
    reasons: list[str] = []
    if MONEY.search(answer):
        reasons.append("Câu trả lời có số tiền hoặc phần trăm: giá và khuyến mãi luôn lấy từ tool, không lưu vào tri thức.")
    codes = sorted(code for code in promo_codes() if code in text)
    if codes:
        reasons.append(f"Có mã khuyến mãi ({', '.join(codes)}): khuyến mãi luôn lấy từ tool.")
    if STOCK.search(plain(answer)):
        reasons.append("Có tình trạng tồn kho: tồn kho luôn lấy từ inventory_check.")
    if MUST_TRANSFER.search(plain(text)):
        reasons.append("Chủ đề y tế, thuốc, thai sản hoặc pháp lý phải chuyển người (PB-06), không lưu thành câu trả lời.")
    return tuple(reasons)
