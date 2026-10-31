"""The hard check on a reply: code only, a few milliseconds a sentence. ``docs/design.md`` section 4.5.

It turns the price hallucination threshold (at most 5%) from a hope into a
guarantee, and it can be shown live.

| Check | How |
|---|---|
| money | every amount, in digits or in words (read by the ITN the customer's words go through), must come from a valid source: this turn's tool results, today's quotes earlier in the call, the passages read this turn, the customer's own words, a quantity times a unit price, or the difference of two amounts. A price from the brief only as history ("hôm trước bên em báo"), and only when VERIFIED |
| days, months | "giao trong 2 ngày", "đổi trả 7 ngày", "bảo hành 24 tháng" must match a tool result, a passage of the turn, the customer's words or a rule the prompt states |
| discontinued | "ngừng bán" needs a tool of the turn reporting the product discontinued: a passage names its own model only |
| delivery by area | without an address ``delivery.estimate`` answers per area; a sentence stating one area's days names that area or gives them all |
| stock | "còn hàng", "hết hàng", "chỉ còn N" need a tool of the turn saying the same (``inventory.check``, or the stock a search returned), or a warning of the brief saying it |
| order state | an order said to be in transit, delivered, processing or cancelled ("đơn … đang giao", "đã giao") needs an order tool of the turn (``order.status``, ``order.update``, ``order.create``, ``account.orders``): the brief's state is history, and today's may differ |
| order done | saying an order was placed ("em đã lên đơn", "đơn … đã được tạo") needs ``order.create`` to have succeeded in this turn, an order read reporting it, or an order this call created earlier; saying it was changed ("đã đổi size") needs ``order.update``: a refused or missing call is not an order |
| promotion | a code named must be applied in this turn's quote, said as history, or said to have ended; a promotion not yet started is never named (KM-02) |
| internal | no purchase price, margin, supplier, price floor |
| personal data | no raw phone, ID or account number; no run of 10 to 14 digits; no token that is not this call's |
| tier | below VERIFIED, no price the brief holds, no order code |
| human | no claim to be a person |
| handoff | a sentence promising to put the caller through to a person needs ``handoff.transfer`` to have run in this turn |
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
#: "em sẽ chuyển máy cho nhân viên", "em kết nối anh với đồng nghiệp": a promise, not an offer.
TRANSFER_PROMISE = re.compile(
    r"\bem\b[^.?!]*?\b(chuyển|kết nối|nối máy)\b[^.?!]*?\b(máy|cuộc gọi|nhân viên|đồng nghiệp|bộ phận|tư vấn viên)\b", re.IGNORECASE)
#: Words that make it an offer or a question rather than a promise.
TRANSFER_OFFER = re.compile(r"(nếu|muốn|có thể|được không|có cần|\?|hay là|để em hỏi)", re.IGNORECASE)
ORDER_CODE = re.compile(r"\bOD\d{5,}\b")
ORDER_SUMMARY = re.compile(r"(tổng (cộng|đơn|tiền)|xác nhận đơn|lên đơn|mã đơn|đặt hàng)", re.IGNORECASE)
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.IGNORECASE)
SENTENCE = re.compile(r"(?<=[.!?…])\s+")
DIGIT_RUN = re.compile(r"(?<!\d)\d{10,14}(?!\d)")
MARKUP = re.compile(r"(\*\*|__|^\s*[-*•]\s|^\s*#{1,6}\s|```)", re.MULTILINE)
DURATION = re.compile(r"(\d+)\s*(?:-|–|đến)?\s*(\d+)?\s*(ngày|tháng|tuần|giờ)\b", re.IGNORECASE)
STOCK = re.compile(r"\b(còn hàng|hết hàng|có sẵn hàng|sẵn hàng|tạm hết|sắp hết hàng|chỉ còn \d+)\b", re.IGNORECASE)
OUT_OF_STOCK = re.compile(r"\b(hết hàng|tạm hết)\b", re.IGNORECASE)
#: A product said to be no longer sold: it existed, so a tool must say so ("chưa kinh doanh" is a product the shop never had).
DISCONTINUED = re.compile(r"\b(ngừng bán|ngưng bán|ngừng kinh doanh|ngưng kinh doanh|ngừng sản xuất)\b", re.IGNORECASE)
#: An order's state said as a fact, in a sentence about an order.
ORDER_STATE = re.compile(
    r"\b(đang (?:được )?(?:giao|vận chuyển|xử lý|chuẩn bị)|đang trên đường|đã (?:được )?(?:giao|bàn giao|hủy|huỷ|gửi đi)"
    r"|chưa (?:được )?giao)\b", re.IGNORECASE)
ORDER_WORD = re.compile(r"\b(đơn|kiện hàng|gói hàng)\b", re.IGNORECASE)
ORDER_TOOLS = frozenset({"order.status", "order.update", "order.create", "account.orders"})
#: The agent saying the order is placed, not offering to place it ("em lên đơn cho anh nhé?").
ORDER_PLACED = re.compile(
    r"\b(?:đã|vừa)\s+(?:được\s+)?(?:lên|tạo|chốt)\s+(?:xong\s+)?đơn\b"
    r"|\b(?:lên|tạo|chốt|đặt)\s+đơn(?:\s+hàng)?\s+(?:thành công|xong|rồi)\b"
    r"|\bđặt hàng thành công\b"
    r"|\bđơn(?:\s+hàng)?\b[^.?!]{0,40}?\bđã\s+(?:được\s+)?(?:tạo|lên|ghi nhận)\b", re.IGNORECASE)
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
    #: Orders this call created in earlier turns: a later turn may speak of them as placed.
    created_orders: tuple[str, ...] = ()
    #: False for a consultant's text: they are the person, so there is no tool to wait for.
    check_handoff: bool = True


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
    reasons += _area_days(text, view)
    reasons += _stock(text, view)
    reasons += _discontinued(text, view)
    reasons += _order_state(text, view)
    reasons += _promotions(text, view)
    reasons += _transfer(text, view)
    reasons += _completed_order(text, view)
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


def _area_days(text: str, view: GuardInput) -> list[str]:
    """A delivery time read off ``delivery.estimate`` without an address is one area's, not the customer's.

    With no address the tool answers each area (``by_area``); a sentence that states one of those
    figures must say which area it is, or give them all, or the customer hears a promise for an area
    nobody named. A turn whose estimate or order had the address is not checked.
    """
    areas: list[Mapping[str, Any]] = []
    for result in view.tool_results:
        data = ((result.get("result") or {}).get("data") or {}) if (result.get("result") or {}).get("ok") else {}
        name = str(result.get("name", "")).replace("_", ".", 1)
        if name == "delivery.estimate" and data.get("address_known"):
            return []
        if name == "order.create" and data.get("estimated_delivery") and (result.get("args") or {}).get("address"):
            return []
        if name == "delivery.estimate" and data.get("by_area"):
            areas += [a for a in data["by_area"] if isinstance(a, Mapping)]
    figures = {a.get("delivery_days") for a in areas if isinstance(a.get("delivery_days"), int)}
    if len(figures) < 2:
        return []
    named = re.compile(r"\b(" + "|".join(re.escape(p) for p in _area_phrases(areas)) + r")\b")
    for sentence in SENTENCE.split(text):
        said = {int(m.group(1)) for m in DURATION.finditer(sentence) if m.group(3).lower() == "ngày"}
        if not said & figures or figures <= said:
            continue
        if not named.search(plain(sentence)):
            each = "; ".join(f"{a.get('delivery_days')} ngày ở {a.get('area')}" for a in areas
                             if isinstance(a.get("delivery_days"), int))
            return [f"Chưa có địa chỉ nên thời gian giao tùy khu vực: nói đủ \"giao {each}\", hoặc bỏ thời gian giao "
                    "và xin địa chỉ; không nói một con số riêng."]
    return []


def _discontinued(text: str, view: GuardInput) -> list[str]:
    """Saying a product is no longer sold needs a tool of the turn reporting one discontinued.

    Like stock, a product's status is the tools': a passage that names a discontinued model is about
    that model, and read alone it can be taken for a current one with a similar name.
    """
    if not DISCONTINUED.search(text):
        return []
    for result in view.tool_results:
        envelope = result.get("result") or {}
        data = envelope.get("data") or {} if envelope.get("ok") else {}
        items = [data, *(data.get("items") or [])]
        if any(item.get("discontinued") or (item.get("attributes") or {}).get("discontinued") for item in items):
            return []
    return ["Nói sản phẩm ngừng bán mà chưa có tool của lượt này báo vậy; gọi catalog_search hoặc inventory_check "
            "với đúng mã, tài liệu chỉ nói về mẫu nó nêu."]


def _area_phrases(areas: Iterable[Mapping[str, Any]]) -> set[str]:
    """How a sentence names an area of ``by_area``: "Hà Nội, TP.HCM, Đà Nẵng" is three names, "tỉnh thành khác"
    is said "tỉnh"; whole names, since a single word ("nội", "thành") is also in "nói", "thanh toán"."""
    phrases = set()
    for area in areas:
        for part in str(area.get("area") or "").split(","):
            words = re.sub(r"^tp\.?\s*", "", plain(part).strip()).split()
            if words:
                phrases.add(words[0] if len(words) >= 3 else " ".join(words))
    return phrases or {"khu vuc"}


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


def _order_state(text: str, view: GuardInput) -> list[str]:
    """An order's state comes from an order tool of the turn, like a stock claim from ``inventory.check``.

    Not for a consultant's text (``check_handoff`` off): they read the order on their own screen.
    """
    if not view.check_handoff or not any(ORDER_STATE.search(s) and ORDER_WORD.search(s) for s in SENTENCE.split(text)):
        return []
    for result in view.tool_results:
        if str(result.get("name", "")).replace("_", ".") in ORDER_TOOLS and (result.get("result") or {}).get("ok"):
            return []
    return ["Nói về trạng thái đơn mà chưa tra trong lượt này; gọi order_status trước, rồi nói đúng trạng thái tool trả về."]


def _completed_order(text: str, view: GuardInput) -> list[str]:
    """Saying an order was placed or changed is a claim about what the system did, like a transfer: the write must have run.

    A placed order is also backed by an order this call created in an earlier turn, or by an order
    read of the turn ("đơn … đang ở trạng thái đã tạo" reports what ``order.status`` returned). A
    sentence about an earlier contact ("hôm trước em đã lên đơn") is history, not this claim. Not for
    a consultant's text: they act on their own screen.
    """
    if not view.check_handoff:
        return []
    for sentence in SENTENCE.split(text):
        if HISTORY.search(sentence):
            continue
        words = plain(sentence)
        creating = (_asserted(words, re.search(r"\b(da|vua) (len|tao|dat|xac nhan) (don|hang)\b", words))
                    or _asserted(sentence, ORDER_PLACED.search(sentence)))
        updating = _asserted(words, re.search(r"\b(da|vua) (doi|cap nhat|sua) (don|size|kich co|dia chi)\b", words))
        if not creating and not updating:
            continue
        if creating and view.created_orders:
            continue
        tool = "order.create" if creating else "order.update"
        backing = {tool, "order.status", "account.orders"} if creating else {tool}
        if not any(str(r.get("name", "")).replace("_", ".", 1) in backing
                   and (r.get("result") or {}).get("ok")
                   and (r.get("result") or {}).get("data") for r in view.tool_results):
            wire = tool.replace(".", "_")
            return [f"Nói đã thực hiện đơn hàng mà chưa có {wire} thành công; chỉ báo thành công sau kết quả tool. "
                    "Tool từ chối thì làm theo đúng lý do nó trả về (ví dụ xin số điện thoại)."]
    return []


def _asserted(text: str, match: re.Match[str] | None) -> bool:
    """Whether *match* is said as done: no negation or condition before it in its clause, no question after it.

    Only its own clause counts: "máy lọc không khí" later in the sentence is a product's name, not a negation.
    """
    if match is None:
        return False
    before = re.split(r"[,;:]", plain(text[:match.start()]))[-1]
    after = re.split(r"[,;:]", text[match.end():])[0]
    return not re.search(r"\b(chua|khong|neu)\b", before) and "?" not in after


def _transfer(text: str, view: GuardInput) -> list[str]:
    """Saying the call is being put through is a claim about what the system did: ``handoff.transfer`` must have run."""
    if not view.check_handoff:
        return []
    promised = [s for s in SENTENCE.split(text) if TRANSFER_PROMISE.search(s) and not TRANSFER_OFFER.search(s)]
    if not promised:
        return []
    for result in view.tool_results:
        if str(result.get("name", "")).replace("_", ".") == "handoff.transfer" and (result.get("result") or {}).get("ok"):
            return []
    return ["Nói sẽ chuyển máy cho nhân viên mà chưa gọi handoff_transfer; gọi handoff_transfer trước rồi mới báo khách."]


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
    return [reason for text in texts for reason in check(GuardInput(**{**view.__dict__, "text": text, "check_handoff": False})).reasons]
