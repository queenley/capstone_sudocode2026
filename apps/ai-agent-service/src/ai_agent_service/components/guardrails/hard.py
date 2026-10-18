"""The hard check on a reply: code only, a few milliseconds a sentence. ``docs/design.md`` section 4.5.

It turns the price hallucination threshold (at most 5%) from a hope into a
guarantee, and it can be shown live.

| Check | How |
|---|---|
| money | every amount, in digits or in words (read by the ITN the customer's words go through), must come from a valid source: this turn's tool results, today's quotes earlier in the call, the passages read this turn, the customer's own words, a quantity times a unit price, or the difference of two amounts. A price from the brief only as history ("hôm trước bên em báo"), and only when VERIFIED |
| days, months | "giao trong 2 ngày", "đổi trả 7 ngày", "bảo hành 24 tháng" must match a tool result, a passage of the turn, the customer's words or a rule the prompt states |
| stock | "còn hàng", "hết hàng", "chỉ còn N" need a tool of the turn saying the same (``inventory.check``, or the stock a search returned), or a warning of the brief saying it |
| promotion | a code named must be applied in this turn's quote, said as history, or said to have ended; a promotion not yet started is never named (KM-02) |
| internal | no purchase price, margin, supplier, price floor |
| personal data | no raw phone, ID or account number; no run of 10 to 14 digits; no token that is not this call's |
| tier | below VERIFIED, no price the brief holds, no order code |
| human | no claim to be a person |
| abstaining | a sentence saying the information is missing uses one of the six phrases the organisers' grader reads |
| shape | not empty, at most three sentences unless reading an order back, Vietnamese, no markup |

Every reason is returned, not just the first, so one regeneration can fix
them all. The same check runs on one sentence of a streamed reply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping

from ..intake.itn import amounts, format_vnd
from ..intake.pii import PATTERNS, TOKEN
from ..intake.text import plain
from . import Verdict

MAX_SENTENCES = 3

#: The phrases ``eval/reference_eval.py`` accepts as "not known" (``ABSTAIN_KW``).
ABSTAIN_PHRASES = ("không có thông tin", "chưa có thông tin", "em chưa rõ", "em không chắc", "em sẽ kiểm tra",
                   "chưa nắm được")
#: Durations a rule of the prompt states, not a tool: the 72 hours of a deletion (QT-06).
RULE_DURATIONS = frozenset({72})

HISTORY = re.compile(r"(hôm trước|lần trước|trước đây|hôm qua|đã báo|bên em báo|báo chị|báo anh)", re.IGNORECASE)
INTERNAL = re.compile(r"(giá nhập|giá vốn|biên lợi nhuận|lợi nhuận|nhà cung cấp|giá sàn|price_floor|_internal|chiết khấu nội bộ)", re.IGNORECASE)
HUMAN = re.compile(
    r"(em là người thật|em là nhân viên thật|em không phải (là )?(máy|bot|robot|ai|trợ lý (ảo|tự động))|"
    r"em là con người|không phải trợ lý ảo đâu)",
    re.IGNORECASE,
)
ORDER_CODE = re.compile(r"\bOD\d{5,}\b")
ORDER_SUMMARY = re.compile(r"(tổng (cộng|đơn|tiền)|xác nhận đơn|lên đơn|mã đơn|đặt hàng)", re.IGNORECASE)
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.IGNORECASE)
SENTENCE = re.compile(r"(?<=[.!?…])\s+")
DIGIT_RUN = re.compile(r"(?<!\d)\d{10,14}(?!\d)")
MARKUP = re.compile(r"(\*\*|__|^\s*[-*•]\s|^\s*#{1,6}\s|```)", re.MULTILINE)
DURATION = re.compile(r"(\d+)\s*(?:-|–|đến)?\s*(\d+)?\s*(ngày|tháng|tuần|giờ)\b", re.IGNORECASE)
STOCK = re.compile(r"\b(còn hàng|hết hàng|có sẵn hàng|sẵn hàng|tạm hết|sắp hết hàng|chỉ còn \d+)\b", re.IGNORECASE)
OUT_OF_STOCK = re.compile(r"\b(hết hàng|tạm hết)\b", re.IGNORECASE)
ENDED = re.compile(r"(đã hết|hết hạn|kết thúc|không còn|ngừng)", re.IGNORECASE)
#: The agent saying it does not know: about itself ("em chưa rõ", "bên em không có thông tin"), not
#: about the customer ("nếu chị chưa biết chọn mẫu nào").
ABSTAINING = re.compile(
    r"\b(em|ben em|shop|minh) (hien |hien tai )?(van )?(chua|khong) (co |duoc )?(thong tin|nam|ro|biet|chac)\b"
    r"|\b(chua|khong) co thong tin\b")


@dataclass(frozen=True)
class GuardInput:
    """What the hard check may read (section 3.2)."""

    text: str
    tool_results: tuple[dict[str, Any], ...]
    tier: Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
    #: The customer's own words in this call, tokenised.
    customer_said: tuple[str, ...] = ()
    #: The knowledge passages read this turn.
    policy_texts: tuple[str, ...] = ()
    #: Prices the brief holds: history, never a current price.
    brief_prices: tuple[int, ...] = ()
    #: This call's vault tokens, the only ones the text may carry.
    tokens: frozenset[str] = field(default_factory=frozenset)
    #: Today's price per product from every quote earlier in this call.
    quotes: Mapping[str, int] = field(default_factory=dict)
    #: The brief's freshness warnings: what has ended or run out, stated by ``refresh``.
    warnings: tuple[str, ...] = ()
    #: Every promotion the shop runs, code to ``(start, end)``, and the day of the call (KM-02).
    promotions: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    on: str | None = None


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
    """Every amount the reply may state.

    Arithmetic is allowed on what the tools returned only: a quantity times a
    unit price, the difference of two prices (a discount, a change since the
    last quote). An amount from the customer or a passage stands as written:
    combined with a price it could make almost any number (5.200.000đ less a
    passage's 300.000đ is 4.900.000đ).
    """
    tools: set[int] = set(view.quotes.values())
    for result in view.tool_results:
        tools |= numbers_in(result.get("result"))
    base = {a for a in tools if a >= 1_000}
    found = tools | {a * q for a in base for q in range(2, 6)} | {abs(a - b) for a in base for b in base if a != b}
    for text in (*view.customer_said, *view.policy_texts):
        found.update(amounts(text))
    return found


def allowed_counts(view: GuardInput) -> set[int]:
    """Numbers a duration may state: from the tools, the passages, the customer, the prompt's rules."""
    found: set[int] = set(RULE_DURATIONS)
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
    reasons += _stock(text, view)
    reasons += _promotions(text, view)
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
    if view.tier != "VERIFIED" and ORDER_CODE.search(text):
        reasons.append("Chưa xác minh danh tính nên không được đọc mã đơn.")
    if HUMAN.search(text):
        reasons.append("Không được nhận là người thật.")
    if ABSTAINING.search(plain(text)) and not any(phrase in text.lower() for phrase in ABSTAIN_PHRASES):
        reasons.append("Câu thừa nhận thiếu thông tin phải dùng đúng cụm \"chưa có thông tin\".")
    reasons += _shape(text)
    return Verdict(not reasons, tuple(dict.fromkeys(reasons)))


def _money(text: str, view: GuardInput) -> list[str]:
    reasons = []
    allowed = allowed_amounts(view)
    history = set(view.brief_prices)
    for sentence in SENTENCE.split(text):
        for value in amounts(sentence):
            if value in allowed:
                continue
            if value in history and HISTORY.search(sentence):
                if view.tier != "VERIFIED":
                    reasons.append(f"Chưa xác minh danh tính nên không được nhắc giá đã báo {format_vnd(value)}.")
                continue
            reasons.append(
                f"Số tiền {format_vnd(value)} không có trong kết quả tool của lượt này, lời khách hay chính sách; "
                "gọi tool để lấy số đúng hoặc bỏ con số."
            )
    return reasons


def _durations(text: str, view: GuardInput) -> list[str]:
    allowed = allowed_counts(view)
    reasons = []
    for match in DURATION.finditer(text):
        stated = [int(match.group(1))] + ([int(match.group(2))] if match.group(2) else [])
        if not all(n in allowed for n in stated):
            reasons.append(
                f"Thời hạn \"{match.group(0).strip()}\" không có trong kết quả tool hay tài liệu của lượt này; "
                "lấy từ delivery_estimate, catalog_search hoặc tài liệu, hoặc bỏ con số."
            )
    return reasons


def _stock(text: str, view: GuardInput) -> list[str]:
    """A stock claim needs a tool of the turn that says the same: ``inventory.check``, or the stock a search returned."""
    if not STOCK.search(text):
        return []
    said_out = bool(OUT_OF_STOCK.search(text))
    if any(available != said_out for available in _availability(view.tool_results)):
        return []
    if said_out and any("hết hàng" in w for w in view.warnings):
        return []
    return ["Nói về tồn kho mà kết quả tool của lượt này không nói vậy; gọi inventory_check trước."]


def _availability(results: Iterable[Mapping[str, Any]]) -> list[bool]:
    """Whether each product a tool of the turn reported on is in stock."""
    found: list[bool] = []
    for result in results:
        envelope = result.get("result") or {}
        if not envelope.get("ok"):
            continue
        data = envelope.get("data") or {}
        if "in_stock" in data:
            found.append(bool(data["in_stock"]))
        for item in data.get("items") or []:
            if "in_stock" in item:
                found.append(bool(item["in_stock"]))
            elif "stock" in item:
                found.append(int(item.get("stock") or 0) > 0)
    return found


def _promotions(text: str, view: GuardInput) -> list[str]:
    if not view.promotions:
        return []
    applied = {p.get("promo_code") for r in view.tool_results if r.get("name") == "pricing.get_quote"
               for p in (((r.get("result") or {}).get("data") or {}).get("applied_promos") or [])}
    reasons = []
    for sentence in SENTENCE.split(text):
        for code, (start, _end) in view.promotions.items():
            if not re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", sentence, re.IGNORECASE):
                continue
            if view.on and start > view.on:
                reasons.append(f"Không được nhắc chương trình {code} khi chưa bắt đầu (KM-02).")
            elif code not in applied and not HISTORY.search(sentence) and not ENDED.search(sentence):
                reasons.append(f"Khuyến mãi {code} không có trong báo giá của lượt này; gọi pricing_get_quote trước.")
    return reasons


def _shape(text: str) -> list[str]:
    reasons = []
    sentences = [s for s in SENTENCE.split(text) if len(s.strip()) > 12]
    if len(sentences) > MAX_SENTENCES and not ORDER_SUMMARY.search(text):
        reasons.append(f"Quá dài: {len(sentences)} câu, tối đa {MAX_SENTENCES}.")
    if len(text) > 40 and not VIETNAMESE.search(text):
        reasons.append("Câu trả lời không phải tiếng Việt.")
    if MARKUP.search(text):
        reasons.append("Không dùng markdown, gạch đầu dòng hay in đậm: câu trả lời có thể được đọc thành tiếng.")
    return reasons


def warnings_for(texts: Iterable[str], view: GuardInput) -> list[str]:
    """The same checks on a consultant's text, as warnings rather than a block."""
    return [reason for text in texts for reason in check(GuardInput(**{**view.__dict__, "text": text})).reasons]
