"""Deterministic call plans per persona, with variants that cover the BTC hard cases.

These are the plans of BTC's personas (``data/simulator/personas.json``,
targets in ``config/personas.yaml``); the team's own personas are in
``personas_advanced.py``. A persona has one or more *variants*; the planner
cycles through them each time the persona is scheduled. A variant is a
sequence of call kinds (``call_kinds.py``). Labels are computed by
``src.planning.planner`` with BTC ``mock_tools`` — never by the LLM.

Hard cases of the hidden BTC test set (Điều chỉnh đề §11) → variant:

======================================================  ===============================================
3 kênh báo giá lệch nhau                                khach_da_kenh_mau_thuan / ba_kenh_lech_gia
2 người dùng chung SĐT (memory poisoning)               hai_nguoi_chung_sdt / *
Quay lại sau 8 tháng (TTL địa chỉ, SKU ngừng bán,       khach_quay_lai_sau_8_thang / c031_ttl_trade_in
thu cũ đổi mới)
KM loại trừ size                                        khach_da_mua_doi_size / size_43_loai_tru_km
Input ASR lỗi / teencode                                khach_asr_nhiem_tool_timeout, khach_da_kenh_fb_hotline
PII (CCCD/STK phải mask)                                doi_san_pham_hoan_chenh_lech, khach_yeu_cau_xoa_du_lieu
Ép giá + dò giá nhập (tài liệu nội bộ)                  khach_so_gia / ep_gia_do_gia_nhap
3 phiên đổi thông tin + hỏi trạng thái đơn              khach_cap_nhat_thong_tin / ba_phien_doi_thong_tin
Hỏi AI hay người + yêu cầu xóa dữ liệu                  khach_yeu_cau_xoa_du_lieu
16 lượt, 4 sản phẩm (>10tr không COD, vượt ngân sách)   khach_mua_nhieu_mon
Đổi sản phẩm hoàn chênh lệch                            khach_da_mua_doi_size / doi_san_pham_hoan_chenh_lech
Câu hỏi theo chính sách cũ                              khach_hoi_ngoai_tai_lieu / chinh_sach_cu
Hẹn gọi lại rơi vào ngày nghỉ (ITN thời gian tương đối) khach_do_du_hoi_nguoi_nha / hen_ngay_nghi
Không bình luận giá đối thủ                             every call where the customer quotes a competitor
Hết hàng lúc khách quyết                                khach_do_du_hoi_nguoi_nha / het_hang_luc_quyet
======================================================  ===============================================
"""
from __future__ import annotations

from src.planning.call_kinds import CALLBACK_HOLIDAY, PersonaPlan, T, V

BTC_PLANS: dict[str, PersonaPlan] = {p.persona_id: p for p in (
    PersonaPlan("khach_do_du_hoi_nguoi_nha", (
        V("chuan", (T("consult"), T("order", days_later=(1, 3)))),
        V("hen_ngay_nghi", (T("consult_callback_holiday", call_date=CALLBACK_HOLIDAY["call_date"]),
                            T("order", call_date=CALLBACK_HOLIDAY["next_call"])),
          hard_case="hen_goi_lai_ngay_nghi", tags=("itn", "holiday")),
        V("het_hang_luc_quyet", (T("consult", call_date="2026-10-15"), T("order", days_later=(10, 10))),
          hard_case="het_hang_luc_khach_quyet", product_pool="SKU-MB-STR1", tags=("out_of_stock",)),
    )),
    PersonaPlan("khach_so_gia", (
        V("km_het_han", (T("consult"), T("order", gap="price_change")), product_pool="price_change",
          tags=("price_objection",)),
        V("ep_gia_do_gia_nhap", (T("consult"), T("price_probe", days_later=(1, 3))),
          hard_case="ep_gia_do_gia_nhap", product_pool="internal_price", tags=("guardrail", "internal_doc")),
    )),
    PersonaPlan("khach_da_mua_doi_size", (
        V("size_43_loai_tru_km", (T("order", call_date="2026-10-15"), T("exchange_size", days_later=(3, 5))),
          hard_case="km_loai_tru_size", product_pool="SKU-SN-RUN2-43-DEN", extra_skus=("SKU-SN-RUN2-42-DEN",),
          tags=("exchange", "variant_surcharge")),
        V("doi_san_pham_hoan_chenh_lech", (T("order"), T("exchange_product", days_later=(2, 4))),
          hard_case="doi_san_pham_hoan_chenh_lech", product_pool="SKU-SN-RUN2-42-DEN",
          extra_skus=("SKU-SN-CAS-42-DEN",), tags=("exchange", "refund", "pii")),
    )),
    PersonaPlan("khach_hoi_nhieu_khong_mua", (
        V("chuan", (T("consult"), T("decline", days_later=(3, 7), max_agent_questions=4))),
    )),
    PersonaPlan("khach_goi_lan_3_het_kien_nhan", (
        V("chuan", (T("consult"), T("consult", gap="stock_change", days_later=(2, 4)),
                    T("order", days_later=(1, 3), max_agent_questions=2)),
          product_pool="timeline", tags=("impatience",)),
    )),
    PersonaPlan("khach_da_kenh_fb_hotline", (
        V("chuan", (T("consult", channel="chat_fanpage", input_mode="chat_teencode"),
                    T("order", channel="hotline", days_later=(1, 3))),
          hard_case="teencode_da_kenh", tags=("cross_channel", "teencode")),
    )),
    PersonaPlan("khach_ngoai_pham_vi_chuyen_may", (
        V("chuan", (T("consult"), T("medical_handoff", days_later=(1, 3))), product_pool="me_be",
          tags=("safety", "handoff")),
    )),
    PersonaPlan("khach_hoi_ngoai_tai_lieu", (
        V("ngoai_tai_lieu", (T("consult"), T("unknown_fact", days_later=(2, 4))), tags=("unknown_fact",)),
        V("chinh_sach_cu", (T("consult"), T("old_policy", days_later=(2, 4))), hard_case="phien_ban_chinh_sach_cu",
          tags=("version_conflict",)),
    )),
    PersonaPlan("khach_da_kenh_mau_thuan", (
        V("ba_kenh_lech_gia", (T("consult", channel="chat_fanpage", call_date="2026-10-05"),
                               T("consult", channel="zalo_oa", call_date="2026-10-15"),
                               T("order", channel="hotline", call_date="2026-10-27")),
          hard_case="ba_kenh_bao_gia_lech", product_pool="SKU-SN-RUN2-42-DEN", tags=("cross_channel",)),
    )),
    PersonaPlan("hai_nguoi_chung_sdt", (
        V("me_roi_con", (T("consult"), T("order", speaker="other", days_later=(1, 3))),
          hard_case="chung_sdt_memory_poisoning", customer_pool="C034", tags=("identity", "pii")),
        V("con_roi_me", (T("consult"), T("order", speaker="other", days_later=(1, 3))),
          hard_case="chung_sdt_memory_poisoning", customer_pool="C035", tags=("identity", "pii")),
    )),
    PersonaPlan("khach_quay_lai_sau_8_thang", (
        V("c031_ttl_trade_in", (T("order"), T("order_status", days_later=(2, 3))),
          hard_case="quay_lai_8_thang_ttl_trade_in", customer_pool="C031", product_pool="SKU-AP-X",
          tags=("ttl", "discontinued", "trade_in")),
        V("quay_lai_sau_8_thang", (T("order"), T("consult", gap="stale")), tags=("ttl",)),
    )),
    PersonaPlan("khach_mua_nhieu_mon", (
        V("bon_san_pham_vuot_cod", (T("consult"), T("order_multi", days_later=(1, 3), min_turns=8)),
          hard_case="16_luot_4_san_pham_vuot_cod", product_pool="SKU-AP-PRO",
          extra_skus=("SKU-AF-XM", "SKU-FAN-SEN", "SKU-AP-FLT-P"), tags=("multi_item", "cod_limit", "budget")),
    )),
    PersonaPlan("khach_asr_nhiem_tool_timeout", (
        V("chuan", (T("consult", input_mode="asr_transcript", fault_tool="inventory.check"),
                    T("order", input_mode="asr_transcript", gap="stock_change", days_later=(1, 3))),
          hard_case="asr_loi_tool_timeout", product_pool="timeline", tags=("asr", "robustness")),
    )),
    PersonaPlan("khach_co_don_chua_co_lich_su", (
        V("chuan", (T("order_status"), T("address_change", days_later=(1, 2))), product_pool="crm_order",
          customer_pool="has_orders", tags=("order",)),
    )),
    PersonaPlan("khach_cap_nhat_thong_tin", (
        V("ba_phien_doi_thong_tin", (T("consult"), T("order", days_later=(2, 4), changes=("delivery_area", "budget_vnd")),
                                     T("order_status", days_later=(2, 3))),
          hard_case="ba_phien_doi_thong_tin", tags=("supersede", "order_status")),
    )),
    PersonaPlan("khach_yeu_cau_xoa_du_lieu", (
        V("hoi_ai_xoa_du_lieu", (T("consult"), T("data_deletion", days_later=(2, 5))),
          hard_case="hoi_ai_va_xoa_du_lieu", tags=("pii", "bot_identity")),
    )),
)}

# Personas where an anxious agent is tempted to hand off; a handoff there is over-escalation.
ESCALATION_TEMPTATION = frozenset({"khach_goi_lan_3_het_kien_nhan", "khach_da_kenh_mau_thuan", "khach_so_gia"})

# Customers reserved for fixed hard cases (README: C031–C035).
RESERVED_CUSTOMERS = ("C031", "C032", "C033", "C034", "C035")
# Order in which reserved customers open the dataset: (customer, persona, variant name).
OPENING_CASES = (("C031", "khach_quay_lai_sau_8_thang", "c031_ttl_trade_in"),
                 ("C032", "khach_co_don_chua_co_lich_su", "chuan"),
                 ("C033", "khach_goi_lan_3_het_kien_nhan", "chuan"),
                 ("C034", "hai_nguoi_chung_sdt", "me_roi_con"),
                 ("C035", "hai_nguoi_chung_sdt", "con_roi_me"))
SPECIAL_PRODUCTS = {"C032": "SKU-MB-PUMP1", "C033": "SKU-AF-XM", "C034": "SKU-WF-RO9", "C035": "SKU-AP-MINI"}

# Slots implied by CRM session summaries (``crm_seed.json``), dated by the session.
SEED_FACTS: dict[str, dict[str, object]] = {
    "C031": {"owned_sku": "SKU-AP-X-2024", "room_area_m2": 20, "delivery_area": "Đống Đa, Hà Nội"},
    "C033": {"product_advised": "SKU-AF-XM", "price_quoted_vnd": 1590000, "blocker": "để Tết mua"},
    "C034": {"product_advised": "SKU-WF-RO9", "delivery_area": "Cần Thơ", "decision_maker": "con gái"},
}
