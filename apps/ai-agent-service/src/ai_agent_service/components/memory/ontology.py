"""What the ledger can hold. ``docs/design.md`` section 5.2.

Slot names are exactly the organisers' (the grader matches strings), and
flat. Each slot has a kind, which decides who wins a conflict (section 5.4),
a lifetime (section 5.3: a blocker or purchase intent lasts 30 days, an
address 180, needs never), and whether it may be read to a customer who is
not yet VERIFIED.

Needs per industry are a block per industry. The design keeps one schema
file per industry so that a new one is a file and no code; until the second
file exists the blocks live here.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

Kind = Literal["preference", "business_event", "past_event", "open_note"]


class Slot(NamedTuple):
    kind: Kind
    #: Days until the value lapses; None never lapses.
    ttl_days: int | None
    #: A price, an address or an order code: never read below VERIFIED.
    sensitive: bool
    #: How the brief names it, in the advisor's language.
    label: str


CORE: dict[str, Slot] = {
    "product_advised": Slot("business_event", None, False, "sản phẩm đã tư vấn"),
    "variant_sku": Slot("preference", None, False, "biến thể"),
    "size": Slot("preference", None, False, "size"),
    "color": Slot("preference", None, False, "màu"),
    "price_quoted_vnd": Slot("business_event", None, True, "giá đã báo"),
    "quoted_on": Slot("business_event", None, False, "ngày báo giá"),
    "promo_code": Slot("business_event", None, False, "khuyến mãi"),
    "promo_expiry": Slot("business_event", None, False, "hạn khuyến mãi"),
    "budget_vnd": Slot("preference", None, False, "ngân sách"),
    "blocker": Slot("preference", 30, False, "rào cản"),
    "decision_maker": Slot("preference", 30, False, "người quyết định"),
    "callback_at": Slot("past_event", 30, False, "hẹn gọi lại"),
    "outcome": Slot("past_event", 30, False, "kết quả"),
    "order_id": Slot("past_event", None, True, "mã đơn"),
    "payment": Slot("preference", None, False, "thanh toán"),
    "address_token": Slot("preference", 180, True, "địa chỉ"),
    "competitor_price_vnd": Slot("preference", 30, False, "giá đối thủ khách nêu"),
    # The organisers' name (SAMPLE-02 must_carry_over); episodes keep their
    # own ``objection_type`` column for the QA situation.
    "objection": Slot("preference", 30, False, "phản đối của khách"),
    "objection_type": Slot("preference", 30, False, "loại phản đối"),
    "owned_sku": Slot("business_event", None, False, "sản phẩm khách đang dùng"),
    "quantity": Slot("preference", 30, False, "số lượng"),
    "delivery_area": Slot("preference", 180, False, "khu vực giao hàng (quận/huyện, tỉnh)"),
    "phone_provided": Slot("preference", None, False, "khách đã cho số điện thoại"),
    "preferred_channel": Slot("preference", None, False, "kênh liên hệ khách muốn"),
    "callback_time": Slot("past_event", 30, False, "giờ khách muốn được gọi lại"),
    "alt_suggested": Slot("business_event", 30, False, "sản phẩm thay thế đã gợi ý"),
    "objection_handling": Slot("past_event", 30, False, "cách xử lý phản đối"),
    "sentiment": Slot("preference", 30, False, "thái độ"),
    "commitments": Slot("past_event", 30, False, "cam kết"),
}

#: Needs by industry, from the organisers' catalogue categories.
INDUSTRIES: dict[str, dict[str, Slot]] = {
    "gia-dung": {
        "room_area_m2": Slot("preference", None, False, "diện tích phòng (m²)"),
        "has_children": Slot("preference", None, False, "nhà có trẻ nhỏ"),
    },
    "thoi-trang": {
        "usage_need": Slot("preference", None, False, "mục đích dùng"),
    },
    "me-be": {
        "child_age_months": Slot("preference", None, False, "tuổi của bé (tháng)"),
    },
}

#: Needs asked once and never again while they hold (section 5.2).
NEEDS = {name for block in INDUSTRIES.values() for name in block} | {"budget_vnd", "size", "color", "decision_maker"}

#: What a returning customer must not be asked openly again while it holds:
#: the CallBrief's ``must_not_ask``. Beyond the needs, the business facts the
#: organisers' scenarios protect (SAMPLE-02..04: product, quoted price, order,
#: payment, colour, competitor price) and where to deliver.
PROTECTED = NEEDS | {
    "product_advised", "variant_sku", "price_quoted_vnd", "order_id", "payment",
    "competitor_price_vnd", "delivery_area", "owned_sku", "phone_provided",
}

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
