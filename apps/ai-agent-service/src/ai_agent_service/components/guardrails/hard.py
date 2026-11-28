"""The hard check on a reply: code only, a few milliseconds a sentence.

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

Money compares a number with data; it does not read what a sentence means. Durations are not checked since
2026-11-25: no organisers' metric reads them, and the check blocked sourced answers.

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
from .purchase import units_key

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
ORDER_SUMMARY = re.compile(r"(tổng (cộng|đơn|tiền)|xác nhận đơn|lên đơn|mã đơn|đặt hàng|đọc lại đơn|, tổng )", re.IGNORECASE)
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
    """What the hard check may read."""

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
    #: The total the system added up for the basket the customer is choosing.
    basket_total: int | None = None
    #: The units a ``pricing.quote_order`` of this call priced, units key to ``[[sku, unit price], ...]``. The sum
    #: of standalone quotes over those units is not their price: a second air purifier is at half price (KM-05).
    order_quotes: Mapping[str, Any] = field(default_factory=dict)
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
    written in the console is not a source of prices.
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
    # A basket's total: the sum of some of today's quotes (at most a call's few products), unless a
    # pricing.quote_order priced those very units: then its total is the price, already among the tools' numbers.
    quoted = list(view.quotes.items())[:MAX_BASKET]
    for size in range(2, len(quoted) + 1):
        found |= {sum(price for _, price in group) for group in combinations(quoted, size)
                  if units_key([{"sku": sku} for sku, _ in group]) not in view.order_quotes}
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


def check(view: GuardInput) -> Verdict:
    """Every check in the table; all reasons, not the first."""
    text = view.text.strip()
    if not text:
        return Verdict(False, ("Câu trả lời rỗng.",))
    reasons: list[str] = []
    reasons += _money(text, view)
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


def unsourced_money(text: str, view: GuardInput) -> list[str]:
    """The reasons :func:`check` gives for amounts with no source: not a leak, so the sentence is left out rather
    than the answer rewritten (2026-11-26: guards rewrite only for what must not be said)."""
    return _money(text, view)


def _money(text: str, view: GuardInput) -> list[str]:
    """An amount with no source. Whether a sourced amount is stated rightly is a reading of meaning, the PolicyAgent's."""
    allowed = allowed_amounts(view) | set(view.brief_prices) | {COD_LIMIT_VND}
    allowed |= {value for said in view.customer_said for value in customer_amounts(said)}
    return [f"Số tiền {format_vnd(value)} không có trong kết quả tool của cuộc gọi hay tài liệu chính sách; "
            "không tự tính, dùng đúng số đã có hoặc bỏ con số."
            for value in amounts(text) if value not in allowed]


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


#: A sentence about a promotion: where the first day of one not started yet names it as surely as its code.
PROMOTION_TALK = re.compile(r"chương trình|khuyến mãi|khuyến mại|\bsale\b|giảm giá|ưu đãi|\bdịp\b", re.IGNORECASE)


def _start_day(start: str) -> re.Pattern[str] | None:
    """"11/11", "11-11", "11 tháng 11" for a promotion starting 2026-11-11."""
    try:
        _year, month, day = (int(part) for part in start[:10].split("-"))
    except ValueError:
        return None
    return re.compile(rf"(?<![\d/])0?{day}(?:\s*[/-]\s*0?|\s+tháng\s+){month}(?![\d/])", re.IGNORECASE)


def _not_started(text: str, view: GuardInput) -> list[str]:
    """KM-02: a promotion whose first day is after the day of the call is never named, by its code or, in a sentence
    about a promotion, by its first day ("chương trình 11/11": 2026-11-16, the customer had said the date and the
    agent repeated it while refusing to talk about it)."""
    reasons = []
    for code, (start, _end) in view.promotions.items():
        if not view.on or start <= view.on:
            continue
        named = re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", text, re.IGNORECASE)
        day = _start_day(start)
        dated = day is not None and PROMOTION_TALK.search(text) and day.search(text)
        if named or dated:
            reasons.append(f"Không được nhắc chương trình {code} hay ngày bắt đầu của nó khi chưa bắt đầu (KM-02): "
                           "nói chương trình sắp tới em chưa có thông tin, không lặp lại ngày khách nêu.")
    return reasons


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
            return clock.spoken_moment(moment)
    return None
