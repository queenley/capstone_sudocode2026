"""What the ledger can hold. ``docs/design.md`` section 5.2.

Slot names are exactly the organisers' (the grader matches strings), and
flat. Where the design's names differ from the organisers' scenario format,
the format wins (design, "Nguồn ràng buộc"): the objection slot is
``objection``, and ``alt_suggested`` is the second product an agent offered.

Each slot has a kind, which decides who wins a conflict (section 5.4), a
lifetime (section 5.3: a blocker or purchase intent lasts 30 days, an address
180, needs never), whether it may be read to a customer who is not yet
VERIFIED, and a value type that the write gate checks. ``hint`` is what the
MemoryAgent's model is told the slot means, with the everyday ways customers
say it.

Needs per industry are a block per industry. The design keeps one schema
file per industry so that a new one is a file and no code; until the second
file exists the blocks live here.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal, NamedTuple

from ..intake.itn import money_spans
from ..intake.pii import TOKEN
from ..intake.text import plain

Kind = Literal["preference", "business_event", "past_event", "open_note"]

#: ``int`` and ``bool`` as the organisers write them; ``date`` is ISO; ``code``
#: is one of the slot's ``choices``; ``plain`` is lower case without
#: diacritics, the catalogue's spelling of a colour (``den``); ``size`` is a
#: number for shoes and letters for clothes; ``token`` is a vault token, never
#: the raw value.
ValueType = Literal["str", "int", "bool", "date", "code", "plain", "size", "token", "str_list"]

#: The slot open notes are stored under (section 5.2's "ghi chú mở").
NOTE_SLOT = "note"


class Slot(NamedTuple):
    kind: Kind
    #: Days until the value lapses; None never lapses.
    ttl_days: int | None
    #: A price, an address or an order code: never read below VERIFIED.
    sensitive: bool
    #: How the brief names it, in the advisor's language.
    label: str
    value_type: ValueType = "str"
    choices: tuple[str, ...] = ()
    #: For the MemoryAgent's model: the meaning, and how customers say it.
    hint: str = ""


OBJECTIONS = ("dat_qua", "so_sanh_gia", "can_hoi_nguoi_nha", "chua_tin_tuong", "chua_can", "khac")
SENTIMENTS = ("binh_thuong", "hai_long", "kho_chiu", "gian")
OUTCOMES = ("hen_goi_lai", "chot_don", "tu_choi", "chuyen_may", "khac")
PAYMENTS = ("COD", "bank", "momo", "zalopay")
CHANNELS = ("zalo", "phone", "sms")

CORE: dict[str, Slot] = {
    "product_advised": Slot("business_event", None, False, "sản phẩm đã tư vấn"),
    "alt_suggested": Slot("business_event", None, False, "sản phẩm gợi ý thêm"),
    "variant_sku": Slot("preference", None, False, "biến thể khách chọn"),
    "size": Slot("preference", None, False, "size", "size",
                 hint="Size khách chọn: giày là số (\"size 41\" là 41), áo là chữ (\"size L\" là L)."),
    "color": Slot("preference", None, False, "màu", "plain",
                  hint="Màu khách chọn, viết thường không dấu như catalog: \"màu đen\" là den, \"trắng\" là trang."),
    "price_quoted_vnd": Slot("business_event", None, True, "giá đã báo", "int",
                             hint="Chỉ khi KHÁCH nói giá họ nhớ đã được báo trước đây "
                                  "(\"hôm trước em báo 4 triệu rưỡi\" là 4500000)."),
    "quoted_on": Slot("business_event", None, False, "ngày báo giá", "date"),
    "quoted_sku": Slot("business_event", None, False, "sản phẩm của báo giá đã lưu"),
    "promo_code": Slot("business_event", None, False, "khuyến mãi"),
    "promo_expiry": Slot("business_event", None, False, "hạn khuyến mãi", "date"),
    "budget_vnd": Slot("preference", None, False, "ngân sách", "int",
                       hint="Ngân sách khách nêu, số nguyên VND: \"tầm 5 triệu\" là 5000000, "
                            "\"năm triệu rưỡi\" là 5500000, \"dưới 2 củ\" là 2000000."),
    "blocker": Slot("preference", 30, False, "việc còn dở",
                    hint="Điều khiến khách chưa quyết, cụm ngắn: \"cần hỏi chồng\", \"cần hỏi vợ\", "
                         "\"cần hỏi người nhà\", \"cần suy nghĩ thêm\", \"so sánh giá\", \"chờ lương\". "
                         "\"Để bàn với bà xã\" là \"cần hỏi vợ\"."),
    "decision_maker": Slot("preference", 30, False, "người quyết định",
                           hint="Ai quyết định mua, một từ: chồng, vợ, bố mẹ, con, sếp. "
                                "\"Để chị hỏi ông xã\" là chồng; \"để bàn với bà xã\" là vợ."),
    "callback_at": Slot("past_event", 30, False, "hẹn gọi lại", "str"),
    "outcome": Slot("past_event", 30, False, "kết quả", "code", OUTCOMES),
    "order_id": Slot("past_event", None, True, "mã đơn"),
    "order_ids": Slot("past_event", None, True, "các đơn đã tạo", "str_list"),
    "payment": Slot("preference", None, False, "thanh toán", "code", PAYMENTS,
                    hint="Cách thanh toán khách chọn: COD (nhận hàng trả tiền), bank (chuyển khoản), momo, zalopay."),
    "address_token": Slot("preference", 180, True, "địa chỉ", "token",
                          hint="Chỉ ghi khi lời khách có token địa chỉ dạng <ADDR_1>; không bao giờ chép địa chỉ thô."),
    "delivery_area": Slot("preference", 180, False, "khu vực giao hàng (quận/huyện, tỉnh)",
                          hint="Quận/huyện và tỉnh/thành khách muốn giao tới, không ghi số nhà, tên đường: "
                               "\"giao về quận 7\" là \"quận 7\". Lời khách chỉ có token <ADDR_1> thì bỏ qua."),
    "quantity": Slot("preference", 30, False, "số lượng", "int",
                     hint="Số lượng khách muốn mua, số nguyên: \"lấy 2 cái\" là 2, \"ba đôi\" là 3."),
    "owned_sku": Slot("business_event", None, False, "sản phẩm khách đang dùng"),
    "phone_provided": Slot("preference", None, False, "khách đã cho số điện thoại", "bool",
                           hint="true khi khách đọc số điện thoại của mình trong cuộc (lời khách có token <PHONE_1>); "
                                "không ghi chính số đó."),
    "preferred_channel": Slot("preference", None, False, "kênh liên hệ khách muốn", "code", CHANNELS,
                              hint="Kênh khách muốn được liên hệ: zalo, phone (gọi điện), sms."),
    "callback_time": Slot("preference", 30, False, "giờ khách muốn được gọi lại",
                          hint="Giờ khách muốn được gọi lại, theo lời khách: \"tối mai sau 8 giờ\"."),
    "competitor_price_vnd": Slot("preference", 30, False, "giá bên khác khách nêu", "int",
                                 hint="Giá khách nói thấy ở cửa hàng khác, bằng số nguyên đồng: \"chỗ khác bán 3 triệu 2\" là 3200000."),
    "objection": Slot("preference", 30, False, "phản đối", "code", OBJECTIONS,
                      hint="Loại phản đối của khách: dat_qua (chê đắt, kể cả khi lấy giá nơi khác ra so), so_sanh_gia "
                           "(so với nơi khác mà không chê đắt), can_hoi_nguoi_nha, chua_tin_tuong, chua_can, khac."),
    "objection_handling": Slot("past_event", 30, False, "cách xử lý phản đối",
                               hint="Nhân viên đã xử lý phản đối thế nào, một câu ngắn (nêu bảo hành, quà tặng...)."),
    "sentiment": Slot("preference", 30, False, "thái độ", "code", SENTIMENTS),
    "commitments": Slot("past_event", 30, False, "cam kết",
                        hint="Điều nhân viên đã hứa với khách (gọi lại lúc nào, giữ giá tới ngày nào), ngắn gọn."),
}

#: Needs by industry, from the organisers' catalogue categories.
INDUSTRIES: dict[str, dict[str, Slot]] = {
    "gia-dung": {
        "room_area_m2": Slot("preference", None, False, "diện tích phòng (m²)", "int",
                             hint="Diện tích phòng, số nguyên m²: \"phòng ngủ 5x5\" là 25, \"hai lăm mét vuông\" là 25."),
        "has_children": Slot("preference", None, False, "nhà có trẻ nhỏ", "bool",
                             hint="Nhà có trẻ nhỏ: \"nhà có bé\", \"con còn nhỏ\" là true; \"nhà không có trẻ\" là false."),
    },
    "thoi-trang": {
        "usage_need": Slot("preference", None, False, "mục đích dùng",
                      hint="Khách mua để làm gì: \"chạy bộ\", \"đi làm\", \"đi chơi\"."),
    },
    "me-be": {
        "child_age_months": Slot("preference", None, False, "tuổi của bé (tháng)", "int",
                                hint="Tuổi bé tính bằng tháng: \"bé nhà chị mới 8 tháng\" là 8, \"bé 2 tuổi\" là 24."),
    },
}

#: Needs asked once and never again while they hold (section 5.2), in the
#: order the brief lists them.
NEEDS: tuple[str, ...] = tuple(name for block in INDUSTRIES.values() for name in block) + ("budget_vnd",)

#: What an open question may not ask again once the ledger holds it, the
#: CallBrief's ``must_not_ask``: the needs, the choices made, what the shop
#: already told or recorded, and where to deliver.
ASKED_ONCE = frozenset(NEEDS) | {
    "product_advised", "price_quoted_vnd", "variant_sku", "size", "color", "payment",
    "decision_maker", "competitor_price_vnd", "order_id", "address_token", "delivery_area",
    "owned_sku", "phone_provided",
}
#: The same set, under the name the platform's code and tests use.
PROTECTED = ASKED_ONCE

#: What the MemoryAgent's model may name, from the customer's words or the
#: agent's: never a fact a tool records (the code reads those from the log).
FROM_WORDS: tuple[str, ...] = NEEDS + (
    "size", "color", "payment", "decision_maker", "blocker", "objection", "competitor_price_vnd",
    "address_token", "price_quoted_vnd", "objection_handling", "commitments", "delivery_area", "quantity",
    "phone_provided", "preferred_channel", "callback_time",
)


def slot(name: str) -> Slot | None:
    if name in CORE:
        return CORE[name]
    for block in INDUSTRIES.values():
        if name in block:
            return block[name]
    return None


def is_sensitive(name: str) -> bool:
    spec = slot(name)
    return bool(spec and spec.sensitive)


#: A whole number, with at most the unit its slot is counted in: "25", "25 m²",
#: "8 tháng". Anything more ("5x5 là 25") is a sentence, not a value.
_INTEGER = re.compile(r"\s*(-?\d+)\s*(m2|m²|mét vuông|met vuong|mét|tháng|thang)?\s*", re.IGNORECASE)


def coerce(name: str, raw: Any) -> tuple[bool, Any]:
    """``(True, value)`` with *raw* as a value of the slot's type, or ``(False, raw)``.

    The grader and the brief compare values, so ``"25"`` and ``25`` must not
    both exist for one slot: every value is stored in its type, decided here
    once for the gate and for the extractor.
    """
    spec = slot(name)
    if spec is None or raw is None:
        return False, raw
    kind = spec.value_type
    if kind == "str_list":
        valid = isinstance(raw, list) and all(isinstance(v, str) and 0 < len(v.strip()) <= 160 for v in raw)
        return (True, list(dict.fromkeys(raw))) if valid else (False, raw)
    if kind == "int":
        return _integer(raw, money=name.endswith("_vnd"))
    if kind == "bool":
        if isinstance(raw, bool):
            return True, raw
        text = plain(str(raw)).strip()
        if text in ("true", "co", "yes", "1"):
            return True, True
        if text in ("false", "khong", "no", "0"):
            return True, False
        return False, raw
    if kind == "date":
        try:
            return True, date.fromisoformat(str(raw).strip()[:10]).isoformat()
        except ValueError:
            return False, raw
    if kind == "code":
        wanted = plain(str(raw)).strip().replace(" ", "_")
        for choice in spec.choices:
            if plain(choice) == wanted:
                return True, choice
        if name == "payment" and wanted in ("chuyen_khoan", "ck", "banking", "the"):
            return True, "bank"
        return False, raw
    if kind == "plain":
        text = plain(str(raw)).strip()
        return (True, text) if text else (False, raw)
    if kind == "size":
        if isinstance(raw, int) and not isinstance(raw, bool):
            return True, raw
        text = str(raw).strip().upper().removeprefix("SIZE").strip()
        if text.isdigit():
            return True, int(text)
        return (True, text) if re.fullmatch(r"[XSML0-9]{1,4}", text) else (False, raw)
    if kind == "token":
        text = str(raw).strip()
        return (True, text) if TOKEN.fullmatch(text) and text.startswith("<ADDR_") else (False, raw)
    text = " ".join(str(raw).split())
    return (True, text) if 0 < len(text) <= 160 else (False, raw)


def _integer(raw: Any, *, money: bool) -> tuple[bool, Any]:
    if isinstance(raw, bool):
        return False, raw
    if isinstance(raw, int):
        return True, raw
    if isinstance(raw, float) and raw.is_integer():
        return True, int(raw)
    text = str(raw).strip()
    if money:
        spans = money_spans(text)
        if spans:
            return True, spans[0].value
        digits = re.sub(r"[.,\s]", "", text.removesuffix("đ").removesuffix("VND").strip())
        return (True, int(digits)) if digits.isdigit() else (False, raw)
    match = _INTEGER.fullmatch(text)
    return (True, int(match.group(1))) if match else (False, raw)
