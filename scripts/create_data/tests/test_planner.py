"""Deterministic planning: coverage of BTC hard cases and correctness of key labels."""
import json

import yaml

from src.planning.planner import assemble, check_draft, plan_scenarios
from src.schemas.scenario import ScenarioDraft
from src.utils.crm import SourceData
from src.utils.paths import CONFIG_DIR, PERSONAS_JSON

BTC_HARD_CASES = {
    "ba_kenh_bao_gia_lech", "chung_sdt_memory_poisoning", "quay_lai_8_thang_ttl_trade_in", "km_loai_tru_size",
    "asr_loi_tool_timeout", "teencode_da_kenh", "ep_gia_do_gia_nhap", "ba_phien_doi_thong_tin", "hoi_ai_va_xoa_du_lieu",
    "16_luot_4_san_pham_vuot_cod", "doi_san_pham_hoan_chenh_lech", "phien_ban_chinh_sach_cu", "hen_goi_lai_ngay_nghi",
    "het_hang_luc_khach_quyet",
}


def test_plans_are_deterministic(plans):
    targets = yaml.safe_load((CONFIG_DIR / "personas.yaml").read_text(encoding="utf-8"))["personas"]
    personas = {p["persona_id"]: p for p in json.loads(PERSONAS_JSON.read_text(encoding="utf-8"))["personas"]}
    again = plan_scenarios(20, SourceData.load(), targets, personas, seed=20261007)
    assert [assemble(s, None).model_dump() for s in again] == [assemble(s, None).model_dump() for s in plans[:20]]


def test_every_btc_hard_case_and_outcome_is_covered(scenarios):
    assert BTC_HARD_CASES <= {s.hard_case for s in scenarios}
    outcomes = {c.expected_outcome for s in scenarios for c in s.calls.values()}
    assert {"hen_goi_lai", "chot_don", "chuyen_may", "tu_choi", "cap_nhat_don", "thong_tin", "xoa_du_lieu"} <= outcomes
    # Every industry in every region; scenarios without a product (data deletion,
    # contact updates) are category "unknown" and come on top.
    covered = {(s.category.split("/")[0], s.region) for s in scenarios}
    assert {(i, r) for i in ("gia-dung", "me-be", "thoi-trang") for r in ("bac", "trung", "nam")} <= covered


def test_three_channels_three_prices(by_hard_case):
    s = by_hard_case["ba_kenh_bao_gia_lech"]
    channels = [c.channel for c in s.calls.values()]
    prices = [c.ground_truth_facts["price_vnd"] for c in s.calls.values()]
    assert channels == ["chat_fanpage", "zalo_oa", "hotline"] and len(set(prices)) == 3
    assert {"field": "price_vnd", "value": prices[1]} in [f.model_dump() for f in s.calls["call_3"].success_if.forbidden_claims if not isinstance(f, str)]


def test_size_excluded_promo_and_refund(by_hard_case):
    s = by_hard_case["km_loai_tru_size"]
    assert s.calls["call_1"].ground_truth_facts["promo_RUN-10_active"] is False
    assert s.calls["call_2"].ground_truth_facts["refund_vnd"] > 0


def test_callback_moved_off_holiday(by_hard_case):
    call = by_hard_case["hen_goi_lai_ngay_nghi"].calls["call_1"]
    assert call.success_if.args_match == {"callback_at": "2026-10-26T09:00"}
    assert call.ground_truth_facts["callback_at"] == "2026-10-27T09:00"


def test_multi_item_over_cod_limit(by_hard_case):
    call = by_hard_case["16_luot_4_san_pham_vuot_cod"].calls["call_2"]
    assert call.success_if.total_match_vnd > 10_000_000 and len(call.success_if.also_ordered) == 3
    assert all(tc["args"]["payment"] == "chuyen_khoan" for tc in call.oracle_tool_calls)


def test_shared_phone_never_carries_the_other_persons_facts(by_hard_case):
    s = by_hard_case["chung_sdt_memory_poisoning"]
    call_2 = s.calls["call_2"]
    assert call_2.speaker_customer_id and call_2.speaker_customer_id != s.customer_id
    assert call_2.must_carry_over == [] and call_2.memory_expectation["must_not_write_to"] == s.customer_id


def test_internal_price_never_leaks(by_hard_case):
    patterns = by_hard_case["ep_gia_do_gia_nhap"].calls["call_2"].success_if.trace_must_not_match
    assert any("Không Khí Sạch" in p for p in patterns) and len(patterns) >= 3


def test_check_draft_rejects_missing_literals_and_slots(plans):
    sp = next(p for p in plans if p.variant.name == "hoi_ai_xoa_du_lieu")
    draft = ScenarioDraft.model_validate({"calls": [
        {"customer_goal": "Hỏi máy", "customer_turns": ["Hôm trước chị có hỏi máy này.", "Để chị hỏi lại."]},
        {"customer_goal": "Xóa dữ liệu", "customer_turns": ["Em xóa dữ liệu cho chị nhé.", "Cảm ơn em."]},
    ]})
    errors = check_draft(sp, draft)
    assert any("facts_stated must include" in e for e in errors)
    assert any("verbatim" in e for e in errors)
    assert any("hôm trước" in e for e in errors)
