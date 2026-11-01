"""Which policy sections a call needs: the ground truth of retrieval (recall@k) for every planned call.

A section is a ``## [XX-nn]`` heading of BTC's ``policy/`` (rag/qa_labeled.json chunk_id_rule). A call's
sections come from three places, in this order:

* its kind (:data:`KIND_POLICIES`): what the situation is about (an order: PB-09 chốt đơn, VC-01 giao hàng);
* the call's state, read from the labels the planner computed with ``mock_tools``: a COD order above
  2.000.000đ needs QT-01 and VC-05, above 10.000.000đ VC-03; a gift KM-07; an expired promotion KM-01;
  a product out of stock FAQ-17; a discontinued one FAQ-16 and CL-05; a returning customer PB-01;
* the customer: a blocker "hỏi chồng / người nhà" PB-03, a price objection PB-02, a competitor's price PB-04,
  an impatient or elderly persona PB-10; and the product's own spec when the call is a consultation.

These are labels for evaluation, derived by rule: like every label of this pipeline they stay diagnostic
until a person reviews them (evaluation/datasets/ground-truth-review/SKILL.md).
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Mapping

from src.utils.paths import POLICY_DIR

COD_CONFIRM_VND = 2_000_000    # VC-05, QT-01
COD_LIMIT_VND = 10_000_000     # VC-03
#: Sections a person must not be told (internal notes, staff rules): their questions are "restricted".
RESTRICTED_PREFIXES = ("NB-", "NQ-")
#: LN-02's days off, which LN-03 says are not working days: a delivery spanning one needs LN-03.
HOLIDAYS = ("2026-10-26", "2027-01-01")
#: A blocker "hỏi / bàn với người nhà" (PB-03). Not a bare "hỏi": "muốn gọi hotline hỏi thêm" asks the shop.
FAMILY = re.compile(r"chồng|vợ|ông xã|bà xã|con cháu|người nhà|gia đình|bố mẹ|hoi (?:chong|vo|nguoi nha)")
#: A price objection (PB-02). "gia" alone would match "gia đình".
PRICE = re.compile(r"đắt|\bgiá\b|\bdat\b|\bgia\b(?!\s*(?:đình|dinh))")

KIND_POLICIES: dict[str, tuple[str, ...]] = {
    "consult": (), "decline": (), "deep_consult": (), "compare": (),
    "consult_callback_holiday": ("LN-01", "LN-02"),
    "price_probe": ("KM-06", "PB-02", "NB-01"),
    "order": ("PB-09", "VC-01"), "order_multi": ("PB-09", "VC-01"), "order_qty": ("PB-09", "VC-01", "KM-05"),
    "order_ewallet": ("PB-09", "VC-01", "VC-04"), "order_split": ("PB-09", "VC-01", "VC-03", "QT-01"),
    "order_readback": ("PB-09", "VC-01"), "consult_ready": (),
    "order_status": ("VC-06",), "address_change": ("VC-06",),
    "exchange_size": ("DT-03", "QT-03"), "exchange_product": ("DT-01", "DT-04", "QT-03", "QT-04"),
    "return_policy": ("DT-01", "DT-02"), "return_request": ("DT-01", "DT-02", "DT-07", "QT-03"),
    "return_expired": ("DT-01", "DT-06"),
    "old_policy": ("CL-01", "DT-01", "DT-03", "DT-OLD-01", "DT-OLD-03"),
    "unknown_fact": ("PB-05",), "not_sold": ("PB-05", "FAQ-15"), "off_topic": ("PB-05", "FAQ-15"),
    "data_deletion": ("QT-06", "PB-07"), "medical_handoff": ("PB-06",),
    "request_human": ("PB-10",), "complaint_handoff": ("PB-10", "VC-06"),
    "warranty_claim": ("BH-01", "BH-02", "BH-03"), "warranty_expired": ("BH-01", "BH-02"),
    "extended_warranty": ("BH-05",), "installment": ("VC-04",), "cart_quote": (),
    "other_customer_info": ("PB-08",), "unverified_identity": ("PB-08",),
    "prompt_injection": ("PB-08", "KM-06", "NB-01"),
    "future_promo": ("KM-02",), "stack_promo": ("KM-03", "KM-04", "KM-09"), "regional_promo": ("KM-08", "VC-02"),
    "gift_to_cash": ("KM-07",), "second_item_promo": ("KM-05", "FAQ-19"),
}
#: Kinds that are a consultation about one product: its spec and FAQ apply.
CONSULTING = frozenset({"consult", "consult_ready", "deep_consult", "compare", "decline", "cart_quote",
                        "consult_callback_holiday", "second_item_promo"})
#: A product's own spec and FAQ, by catalogue category (or SKU prefix within it).
CATEGORY_POLICIES: dict[str, tuple[str, ...]] = {
    "gia-dung/may-loc-khong-khi": ("SP-AIR-01", "SP-AIR-02"),
    "gia-dung/may-loc-nuoc": ("SP-WF-01", "FAQ-05"),
    "gia-dung/quat": ("SP-FAN-01", "FAQ-08"),
    "gia-dung/noi-chien": ("SP-AF-01", "FAQ-07"),
    "gia-dung/phu-kien": ("BH-04",),
    "gia-dung/combo": ("FAQ-18",),
    "thoi-trang/giay": ("SP-SN-01",),
    "thoi-trang/ao-khoac": ("SP-JK-01",),
}
SKU_POLICIES: dict[str, tuple[str, ...]] = {
    "SKU-MB-PUMP": ("SP-MB-01", "FAQ-11"), "SKU-MB-STR": ("SP-MB-02", "FAQ-12"), "SKU-MB-CAR": ("SP-MB-03", "FAQ-13"),
    "SKU-MB-STER": ("SP-MB-03",), "SKU-MB-BOT": ("SP-MB-03",), "SKU-AP-FLT": ("SP-AIR-03", "BH-04"),
    "SKU-XM-FLT": ("SP-AIR-03", "BH-04"), "SKU-WF-CORE": ("SP-WF-02", "BH-04"),
}
#: Personas whose way of calling has its own playbook entry.
PERSONA_POLICIES: dict[str, tuple[str, ...]] = {
    "khach_goi_lan_3_het_kien_nhan": ("PB-10",), "khach_lon_tuoi": ("PB-10",),
    "khach_khieu_nai_giao_cham": ("PB-10", "VC-06"), "khach_hoi_nhieu_khong_mua": ("PB-11",),
    "khach_do_du_hoi_nguoi_nha": ("PB-03",), "khach_so_gia": ("PB-02",),
}


@lru_cache(maxsize=1)
def sections() -> dict[str, str]:
    """Every section id of the policy documents and its title."""
    found: dict[str, str] = {}
    for path in sorted(POLICY_DIR.glob("*.md")):
        for sid, title in re.findall(r"^## \[([A-Z0-9-]+)\]\s*(.*)$", path.read_text(encoding="utf-8"), re.M):
            found[sid] = title.strip()
    return found


def _known(ids: list[str]) -> list[str]:
    unknown = [i for i in ids if i not in sections()]
    if unknown:
        raise ValueError(f"policy sections {unknown} are not headings of {POLICY_DIR}")
    return list(dict.fromkeys(ids))


def for_call(kind: str, *, category: str, sku: str, persona: str, gt: Mapping[str, Any], si: Mapping[str, Any],
             stated: Mapping[str, Any], returning: bool) -> list[str]:
    """The policy sections an ideal agent consults on this call, most specific first."""
    ids: list[str] = list(KIND_POLICIES.get(kind, ()))
    if kind in CONSULTING:
        ids += CATEGORY_POLICIES.get(category, ())
        ids += next((v for prefix, v in SKU_POLICIES.items() if sku.startswith(prefix)), ())
        if category == "gia-dung/may-loc-khong-khi":
            ids += ["FAQ-01"] if "room_area_m2" in stated else []
            ids += ["FAQ-02"] if stated.get("has_children") else []
            ids += ["FAQ-04"] if kind == "compare" else []
        if category == "thoi-trang/giay" and "size" in stated:
            ids.append("FAQ-09")
    # the order: payment and its total (VC-03, VC-05, QT-01)
    args = si.get("args_match") or {}
    if si.get("tool_called") == "order.create":
        payment = args.get("payment") or stated.get("payment")
        total = si.get("total_match_vnd") or int(gt.get("price_vnd") or 0) * int(args.get("qty") or 1)
        if payment == "COD" and total > COD_CONFIRM_VND:
            ids += ["VC-05", "QT-01"]
        if total > COD_LIMIT_VND:
            ids.append("VC-03")
        if payment in ("momo", "zalopay", "bank"):
            ids.append("VC-04")
        if si.get("also_ordered") and category == "gia-dung/may-loc-khong-khi":
            ids += ["FAQ-19", "KM-05"]
        if any(str(gt.get("call_date", "")) < day <= str(gt.get("estimated_delivery", "")) for day in HOLIDAYS):
            ids.append("LN-03")
    if si.get("tool_called") == "schedule.callback":
        ids.append("LN-01")    # a callback inside working hours
    # promotions and stock on the call's day
    if gt.get("gift_sku"):
        ids.append("KM-07")
    forbidden = {f.get("field") if isinstance(f, dict) else getattr(f, "field", None) for f in si.get("forbidden_claims") or []}
    if any(str(field).startswith("promo_") and field.endswith("_active") for field in forbidden):
        ids += ["KM-01", "CL-02"]
    if gt.get("in_stock") is False:
        ids.append("FAQ-17")
    if gt.get("successor_sku"):
        ids += ["FAQ-16", "CL-05"]
    if gt.get("policy_version"):
        ids.append("CL-01")
    # the customer
    blocker = str(stated.get("blocker") or "")
    if FAMILY.search(blocker):
        ids.append("PB-03")
    if PRICE.search(f"{stated.get('objection') or ''} {blocker}"):
        ids.append("PB-02")
    if "trả góp" in blocker:
        ids.append("VC-04")
    if "competitor_price_vnd" in stated:
        ids.append("PB-04")
    if returning:
        ids.append("PB-01")
    ids += PERSONA_POLICIES.get(persona, ())
    return _known(ids)


def question_type(ids: list[str]) -> str:
    """The rag/qa_labeled.json type of a question needing *ids*."""
    if any(i.startswith(RESTRICTED_PREFIXES) for i in ids):
        return "restricted"
    if any(i.startswith("DT-OLD-") for i in ids):
        return "version_conflict"
    return "multi_hop" if len(ids) > 1 else "single"
