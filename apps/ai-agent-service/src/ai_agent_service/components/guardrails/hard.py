"""The hard check on a reply: code only, a few milliseconds a sentence. ``docs/design.md`` section 4.5.

Only what has a fixed shape and must never reach a customer, whatever the
sentence means:

| Check | How |
|---|---|
| personal data | no raw phone, ID or account number; no run of 10 to 14 digits; no token that is not this call's |
| internal | no purchase price, margin, supplier, price floor |
| human | no claim to be a person |
| tier | below VERIFIED, no order code and no price the brief holds that a tool of the turn did not give |
| promotion | a promotion not yet started is never named (KM-02), read from the catalogue of promotions |
| money | every amount, in digits or in words (read by the ITN the customer's words go through), must come from a valid source: this call's tool results, today's quotes earlier in the call, the system's basket total, the organisers' policy passages read this turn, a quantity times a unit price, the difference of two amounts of one object, the customer's own words, or a price the brief holds |
| days, weeks, months | a number of them must come from a tool result, a passage of the turn, the customer's words or the brief's warnings |

These two compare a number with data; they do not read what a sentence means.

What a sentence means (a price stated as the shop's, a stock, an order's
state, a promise) is not read here: it is the PolicyAgent's. Every
reason is returned, not just the first, so one regeneration can fix them all.
The same check runs on one sentence of a streamed reply.
"""

from __future__ import annotations

import re
from itertools import combinations
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping

from .. import clock
from ..intake.itn import amounts, format_vnd
from ..intake.pii import PATTERNS, TOKEN
from . import Verdict
from .actions import COD_LIMIT_VND

MAX_SENTENCES = 3
MAX_BASKET = 8


INTERNAL = re.compile(r"(giá nhập|giá vốn|biên lợi nhuận|lợi nhuận|nhà cung cấp|giá sàn|price_floor|_internal|chiết khấu nội bộ)", re.IGNORECASE)
HUMAN = re.compile(
    r"(em là người thật|em là nhân viên thật|em không phải (là )?(máy|bot|robot|ai|trợ lý (ảo|tự động))|"
    r"em là con người|không phải trợ lý ảo đâu)",
    re.IGNORECASE,
)
ORDER_CODE = re.compile(r"\bOD\d+\b")
#: Allows a reply past :data:`MAX_SENTENCES`: reading an order back takes more.
ORDER_SUMMARY = re.compile(r"(tổng (cộng|đơn|tiền)|xác nhận đơn|lên đơn|mã đơn|đặt hàng)", re.IGNORECASE)
DURATION = re.compile(r"(\d+)\s*(?:-|–|đến)?\s*(\d+)?\s*(ngày|tháng|tuần|giờ)\b", re.IGNORECASE)
#: "7 giờ tối", "lúc 7 giờ": a time of day, not a duration.
TIME_OF_DAY_AFTER = re.compile(r"\s*(sáng|trưa|chiều|tối)\b", re.IGNORECASE)
TIME_OF_DAY_BEFORE = re.compile(r"\b(lúc|vào)\s+$", re.IGNORECASE)
#: Durations the prompt's own rules state: data is erased within 72 hours of a request (QT-06).
RULE_DURATIONS = frozenset({72})
#: A rate of the shop's documents, of a price: "bằng 8% giá sản phẩm".
RATE = re.compile(r"(\d{1,2})\s*%")
#: A customer typing without marks ("500 ngan", "5 trieu ruoi"), put back for the amount reader.
UNMARKED_MONEY = ((re.compile(r"\btrieu\b", re.I), "triệu"), (re.compile(r"\b(?:ngan|nghin)\b", re.I), "nghìn"),
                  (re.compile(r"\bruoi\b", re.I), "rưỡi"), (re.compile(r"\bty\b", re.I), "tỷ"))
DIGIT_RUN = re.compile(r"(?<!\d)\d{10,14}(?!\d)")
#: Markup a voice would read aloud: removed from what is said, never a reason to regenerate.
MARKUP = re.compile(r"(\*\*|__|```|^\s*[-*•]\s+|^\s*#{1,6}\s+)", re.MULTILINE)


@dataclass(frozen=True)
class GuardInput:
    """What the hard check may read (section 3.2)."""

    text: str
    tool_results: tuple[dict[str, Any], ...]
    tier: Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
    #: The customer's own words in this call, tokenised.
    customer_said: tuple[str, ...] = ()
    #: The knowledge passages read this turn: durations and the policy review read them.
    policy_texts: tuple[str, ...] = ()
    #: The passages of the organisers' documents among them: the only passages an amount may come from.
    priced_texts: tuple[str, ...] = ()
    #: Prices the brief holds: private below VERIFIED.
    brief_prices: tuple[int, ...] = ()
    #: This call's vault tokens, the only ones the text may carry.
    tokens: frozenset[str] = field(default_factory=frozenset)
    #: Today's price per product from every quote earlier in this call.
    quotes: Mapping[str, int] = field(default_factory=dict)
    #: Numbers in what quotes and orders returned in earlier turns: a refund told again is still sourced.
    earlier_numbers: frozenset[int] = field(default_factory=frozenset)
    #: Numbers in every result of earlier turns, a search's warranty months included: what a duration may repeat.
    earlier_counts: frozenset[int] = field(default_factory=frozenset)
    #: The total the system added up for the basket the customer is choosing.
    basket_total: int | None = None
    #: The brief's freshness warnings: what has ended or run out, stated by ``refresh``.
    warnings: tuple[str, ...] = ()
    #: Every promotion the shop runs, code to ``(start, end)``, and the day of the call (KM-02).
    promotions: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    on: str | None = None
    #: The codes of the orders this call created: the caller placed them, whoever the number belongs to.
    own_orders: frozenset[str] = field(default_factory=frozenset)


def numbers_in(value: Any) -> set[int]:
    """Every integer amount in a tool result, at any depth, including inside text."""
    found: set[int] = set()
    if isinstance(value, bool):
        return found
    if isinstance(value, int):
        found.add(value)
    elif isinstance(value, float) and value.is_integer():
        found.add(int(value))
    elif isinstance(value, str):
        found.update(amounts(value))
        found.update(int(n) for n in re.findall(r"(?<![\d.,])\d{1,3}(?![\d.,]\d)", value))
    elif isinstance(value, dict):
        for item in value.values():
            found |= numbers_in(item)
    elif isinstance(value, list):
        for item in value:
            found |= numbers_in(item)
    return found


def allowed_amounts(view: GuardInput) -> set[int]:
    """Every amount the reply may state as the shop's.

    Arithmetic is allowed only where the operands belong together: a
    quantity times a unit price, the difference of two amounts of one object
    of a tool result (a quote's list and final price, an order's old and new
    price), and today's quote against the price the brief says was quoted (a
    change since the last call). The difference of any two numbers of a turn
    is not: a search listing eight products would make dozens of numbers
    "derived", a fabricated discount among them. An amount from a passage
    counts only from the organisers' documents: a Knowledge Gap Loop or playbook entry
    written in the console is not a source of prices (section 10.2, gate 2).
    The customer's amounts are not here: :func:`_money` lets them through, and
    the PolicyAgent judges whether a sentence passes one off as the shop's.
    """
    tools: set[int] = set(view.quotes.values()) | {n for n in view.earlier_numbers if n >= 1_000}
    if view.basket_total:
        tools.add(view.basket_total)
    groups: list[set[int]] = []
    for result in view.tool_results:
        tools |= numbers_in(result.get("result"))
        groups += amount_groups(result.get("result"))
    base = {a for a in tools if a >= 1_000}
    found = tools | {a * q for a in base for q in range(2, 6)}
    for group in groups:
        found |= {abs(a - b) for a in group for b in group if a != b}
    found |= {abs(q - b) for q in view.quotes.values() for b in view.brief_prices if q != b}
    for text in view.priced_texts:
        found.update(amounts(text))
        # A rate of the documents applied to a price (a warranty plan at 8% of the product).
        for rate in RATE.findall(text):
            found |= {round(price * int(rate) / 100) for price in base if price >= 100_000}
    # A basket's total: the sum of some of today's quotes (at most a call's few products).
    quoted = list(view.quotes.values())[:MAX_BASKET]
    for size in range(2, len(quoted) + 1):
        found |= {sum(group) for group in combinations(quoted, size)}
    return found


def open_amounts(view: GuardInput) -> tuple[int, ...]:
    """The amounts of the reply with no source of the shop's: what only the customer said, once :func:`_money` passed.

    Whether such a figure is passed off as the shop's is the one thing left for the PolicyAgent to read.
    """
    known = allowed_amounts(view) | set(view.brief_prices)
    return tuple(sorted({value for value in amounts(view.text) if value not in known}))


def customer_amounts(said: str) -> list[int]:
    """The amounts of the customer's words, written with marks or without."""
    marked = said
    for pattern, word in UNMARKED_MONEY:
        marked = pattern.sub(word, marked)
    return [*amounts(said), *amounts(marked)]


def amount_groups(value: Any) -> list[set[int]]:
    """The amounts that belong together: those held directly by one object of a tool result."""
    groups: list[set[int]] = []
    if isinstance(value, dict):
        own = {int(v) for v in value.values()
               if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() and v >= 1_000}
        if len(own) > 1:
            groups.append(own)
        for item in value.values():
            if isinstance(item, (dict, list)):
                groups += amount_groups(item)
    elif isinstance(value, list):
        for item in value:
            groups += amount_groups(item)
    return groups


def allowed_counts(view: GuardInput) -> set[int]:
    """Numbers a duration may state: from the tools, the passages, the customer."""
    found: set[int] = set(view.earlier_counts) | set(RULE_DURATIONS)
    for result in view.tool_results:
        found |= numbers_in(result.get("result"))
    for text in (*view.customer_said, *view.policy_texts, *view.warnings):
        found.update(int(n) for n in re.findall(r"\d+", text))
    return found


def check(view: GuardInput) -> Verdict:
    """Every check in the table; all reasons, not the first."""
    text = view.text.strip()
    if not text:
        return Verdict(False, ("Câu trả lời rỗng.",))
    reasons: list[str] = []
    reasons += _money(text, view)
    reasons += _durations(text, view)
    if INTERNAL.search(text):
        reasons.append("Nhắc tới thông tin nội bộ (giá nhập, biên lợi nhuận, nhà cung cấp, giá sàn).")
    for kind, pattern in PATTERNS:
        if pattern.search(text):
            reasons.append(f"Có dữ liệu cá nhân thô ({kind.lower()}) trong câu trả lời.")
            break
    else:
        if DIGIT_RUN.search(text):
            reasons.append("Có một dãy 10 đến 14 chữ số trong câu trả lời; không đọc mã hay số dài cho khách.")
    strangers = [m.group(0) for m in TOKEN.finditer(text) if m.group(0) not in view.tokens]
    if strangers:
        reasons.append(f"Có mã dữ liệu cá nhân không thuộc cuộc gọi này: {', '.join(strangers)}.")
    if HUMAN.search(text):
        reasons.append("Không được nhận là người thật.")
    reasons += _tier(text, view)
    reasons += _not_started(text, view)
    return Verdict(not reasons, tuple(dict.fromkeys(reasons)))


def _money(text: str, view: GuardInput) -> list[str]:
    """An amount with no source. Whether a sourced amount is stated rightly is a reading of meaning, the PolicyAgent's."""
    allowed = allowed_amounts(view) | set(view.brief_prices) | {COD_LIMIT_VND}
    allowed |= {value for said in view.customer_said for value in customer_amounts(said)}
    return [f"Số tiền {format_vnd(value)} không có trong kết quả tool của cuộc gọi hay tài liệu chính sách; "
            "không tự tính, dùng đúng số đã có hoặc bỏ con số."
            for value in amounts(text) if value not in allowed]


def _durations(text: str, view: GuardInput) -> list[str]:
    allowed = allowed_counts(view)
    reasons = []
    for match in DURATION.finditer(text):
        if match.group(3).lower() == "giờ" and (TIME_OF_DAY_AFTER.match(text[match.end():])
                                                or TIME_OF_DAY_BEFORE.search(text[:match.start()])):
            continue
        stated = [int(match.group(1))] + ([int(match.group(2))] if match.group(2) else [])
        if not all(n in allowed for n in stated):
            reasons.append(
                f"Thời hạn \"{match.group(0).strip()}\" không có trong kết quả tool của cuộc gọi hay tài liệu; "
                "lấy từ delivery_estimate, catalog_search hoặc tài liệu, hoặc bỏ con số."
            )
    return reasons


def _tier(text: str, view: GuardInput) -> list[str]:
    """Below VERIFIED the brief is someone's private record: its prices and its order codes stay unsaid.

    Not private: the code of an order this call created. A code the caller names is still not repeated: a caller
    asking after someone else's order may hold its code. A new customer who places an order is told its code; before 2026-11-12 that sentence was blocked and written again on almost every
    order of an unverified caller (33 times in four small runs), a model round each, and the code was never said."""
    if view.tier == "VERIFIED":
        return []
    reasons = []
    if any(code not in view.own_orders for code in ORDER_CODE.findall(text)):
        reasons.append("Chưa xác minh danh tính nên không được đọc mã đơn.")
    given = set().union(*(numbers_in(r.get("result")) for r in view.tool_results)) if view.tool_results else set()
    for value in amounts(text):
        if value in view.brief_prices and value not in given:
            reasons.append(f"Chưa xác minh danh tính nên không được nhắc giá đã báo {format_vnd(value)}.")
    return reasons


def _not_started(text: str, view: GuardInput) -> list[str]:
    """KM-02: a code in the catalogue of promotions whose first day is after the day of the call."""
    return [f"Không được nhắc chương trình {code} khi chưa bắt đầu (KM-02)."
            for code, (start, _end) in view.promotions.items()
            if view.on and start > view.on and re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", text, re.IGNORECASE)]


def clean(text: str) -> str:
    """The sentence without markup, for a channel that may read it aloud."""
    return MARKUP.sub("", text).strip()


def _booked(result: Mapping[str, Any]) -> bool:
    return str(result.get("name", "")).replace("_", ".") == "schedule.callback" and bool((result.get("result") or {}).get("ok"))


def moved_callback(text: str, results: Iterable[Mapping[str, Any]]) -> str | None:
    """The new time of a call back the tool moved (LN-02), when *text*, the whole answer, does not tell it.

    Not part of :func:`check`: a streamed answer is checked a sentence at a
    time, and a sentence need not say everything the answer must.
    """
    for result in results:
        data = (result.get("result") or {}).get("data") or {}
        moment = clock.parse_local(data.get("callback_at")) if _booked(result) and data.get("moved_from") else None
        if moment is None:
            continue
        said = text.lower()
        day = {f"{moment.day}/{moment.month}", f"{moment.day:02d}/{moment.month:02d}", f"{moment.day} tháng {moment.month}",
               clock.WEEKDAYS[moment.weekday()].lower()}
        if not any(phrase in said for phrase in day):
            return clock.moment_label(moment)
    return None
