"""Canonical slot vocabulary shared by scenarios, transcripts and metrics.

Slot names follow the BTC samples (``test_set/public_sample/SAMPLE-0*.json``). A stable
vocabulary is what makes the metrics computable:

* ``carry``   -> the slot is listed in ``must_carry_over`` of later calls (CCR).
* ``protect`` -> the slot is listed in ``must_not_ask`` of later calls (RQR):
  an *open* question about it is redundant; the first *confirm* question is free.
* ``source``  -> who establishes the value. The LLM may only write ``customer``
  slots; ``agent`` and ``system`` slots are injected from trusted data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SlotSource = Literal["customer", "agent", "system"]


@dataclass(frozen=True)
class Slot:
    name: str
    source: SlotSource
    carry: bool
    protect: bool
    description: str


_SLOTS = [
    # --- Customer needs / profile (stated by the customer) -----------------
    Slot("room_area_m2", "customer", True, True, "Diện tích phòng (m²), số nguyên"),
    Slot("has_children", "customer", False, True, "Nhà có trẻ nhỏ (true/false)"),
    Slot("child_age_months", "customer", False, True, "Tuổi bé (tháng)"),
    Slot("budget_vnd", "customer", False, True, "Ngân sách (VND, số nguyên)"),
    Slot("usage_need", "customer", False, True, "Nhu cầu sử dụng chính (ngắn)"),
    Slot("size", "customer", True, True, "Size giày/áo khách mặc"),
    Slot("color", "customer", False, True, "Màu khách chọn"),
    Slot("quantity", "customer", False, False, "Số lượng muốn mua"),
    Slot("payment", "customer", True, True, "Hình thức thanh toán: COD | bank (chuyển khoản), như tools.schema.json"),
    Slot("delivery_area", "customer", True, True, "Quận/huyện + tỉnh giao hàng (không ghi số nhà)"),
    Slot("phone_provided", "customer", False, True, "Khách đã cung cấp SĐT (true) — không ghi số thật"),
    Slot("decision_maker", "customer", True, True, "Người quyết định mua (chồng, vợ, con gái…)"),
    Slot("blocker", "customer", True, False, "Lý do chưa chốt (cần hỏi chồng, chờ lương…)"),
    Slot("objection", "customer", True, False, "Phản đối chính (giá cao, sợ ồn…)"),
    Slot("competitor_price_vnd", "customer", True, False, "Giá đối thủ khách nêu (VND)"),
    Slot("callback_time", "customer", False, False, "Thời điểm khách hẹn gọi lại"),
    Slot("preferred_channel", "customer", True, False, "Kênh liên hệ ưu tiên: hotline | zalo_oa | chat_fanpage"),
    Slot("issue", "customer", True, True, "Lỗi/vấn đề khách gặp với sản phẩm đã mua (ngắn)"),
    Slot("return_reason", "customer", False, False, "Lý do khách muốn trả hàng (ngắn)"),
    # --- Agent-established (injected from trusted catalog/pricing) --------
    Slot("product_advised", "agent", True, True, "SKU đã tư vấn"),
    Slot("variant_sku", "agent", True, True, "SKU biến thể (size/màu) đã chọn"),
    Slot("price_quoted_vnd", "agent", True, False, "Giá cuối đã báo khách (VND)"),
    Slot("promo_code", "agent", True, False, "Mã KM đã báo khách"),
    Slot("promo_expiry", "agent", False, False, "Ngày hết hạn KM đã báo"),
    Slot("alt_suggested", "agent", False, False, "SKU thay thế đã gợi ý"),
    # --- System records (orders, ownership) -------------------------------
    Slot("order_id", "system", True, True, "Mã đơn hàng"),
    Slot("tracking", "system", False, False, "Mã vận đơn"),
    Slot("owned_sku", "system", True, True, "SKU khách đã sở hữu (từ lịch sử đơn)"),
    Slot("channel", "system", False, False, "Kênh của cuộc gọi"),
]

SLOTS: dict[str, Slot] = {slot.name: slot for slot in _SLOTS}
CUSTOMER_SLOTS = tuple(name for name, slot in SLOTS.items() if slot.source == "customer")
CARRY_SLOTS = frozenset(name for name, slot in SLOTS.items() if slot.carry)
PROTECTED_SLOTS = frozenset(name for name, slot in SLOTS.items() if slot.protect)

# A slot established longer ago than this is "stale": the agent should confirm
# it instead of assuming it (BTC TTL case, persona khach_quay_lai_sau_8_thang).
STALE_AFTER_DAYS = 180

# Expected outcomes used by BTC (first four) plus the pipeline extensions.
OUTCOMES = ("hen_goi_lai", "chot_don", "chuyen_may", "tu_choi", "cap_nhat_don", "thong_tin", "xoa_du_lieu")
Outcome = Literal["hen_goi_lai", "chot_don", "chuyen_may", "tu_choi", "cap_nhat_don", "thong_tin", "xoa_du_lieu"]
ESCALATION_OUTCOME = "chuyen_may"
#: The values BTC uses (scenario_format.md, call_brief.schema.json); the pipeline's finer outcomes are "khac" there.
BTC_OUTCOMES = ("hen_goi_lai", "chot_don", "chuyen_may", "tu_choi", "khac")


#: Input modes BTC names (trace_log customer_input_mode; the agent's and the harness's loaders accept only these).
BTC_INPUT_MODES = ("text", "asr_transcript", "chat_teencode")


def btc_input_mode(mode: str) -> str:
    """*mode* as BTC names it: chat without diacritics or with typos is typed chat, "chat_teencode"."""
    return mode if mode in BTC_INPUT_MODES else "chat_teencode"


def btc_outcome(outcome: str) -> str:
    """*outcome* as BTC names it: cap_nhat_don, thong_tin and xoa_du_lieu are "khac"."""
    return outcome if outcome in BTC_OUTCOMES else "khac"

# Legacy spellings produced by older prompts.
OUTCOME_ALIASES = {"chot": "chot_don", "dat_hang": "chot_don", "hen_lai": "hen_goi_lai"}

Channel = Literal["hotline", "zalo_oa", "chat_fanpage"]
#: How the system receives the customer's words. Every mode but ``text`` comes with ``customer_turns_asr``:
#: speech-recognition errors, chat teencode, chat without diacritics, or chat with typos.
InputMode = Literal["text", "asr_transcript", "chat_teencode", "chat_khong_dau", "chat_sai_chinh_ta"]

# Fields an agent may assert in ``claims`` and that the HR metric checks.
CLAIM_FIELDS = (
    "price_vnd", "list_price_vnd", "active_promo", "in_stock", "stock_qty", "restock_date",
    "gift_sku", "free_shipping", "order_status", "tracking", "return_days", "exchange_fee_vnd",
    "installment_supported", "total_vnd",
)


def normalize_outcome(value: str) -> str:
    value = value.strip().lower()
    return OUTCOME_ALIASES.get(value, value)
