"""Deterministic planning: coverage of BTC hard cases and correctness of key labels."""
import pytest
from src.planning.planner import assemble, check_draft
from src.schemas.scenario import ScenarioDraft
from tests.conftest import plan

BTC_HARD_CASES = {
    "ba_kenh_bao_gia_lech", "chung_sdt_memory_poisoning", "quay_lai_8_thang_ttl_trade_in", "km_loai_tru_size",
    "asr_loi_tool_timeout", "teencode_da_kenh", "ep_gia_do_gia_nhap", "ba_phien_doi_thong_tin", "hoi_ai_va_xoa_du_lieu",
    "16_luot_4_san_pham_vuot_cod", "doi_san_pham_hoan_chenh_lech", "phien_ban_chinh_sach_cu", "hen_goi_lai_ngay_nghi",
    "het_hang_luc_khach_quyet",
}


def test_plans_are_deterministic(plans):
    again = plan("btc", 20)
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
    assert all(tc["args"]["payment"] == "bank" for tc in call.oracle_tool_calls if tc["name"] == "order.create")


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


def test_the_writer_answers_in_the_shape_of_the_plan(plans):
    # Free lists let gpt-4o-mini merge two calls (SCN-ADV-0081), drop a different pair of facts on each attempt
    # (SCN-GEN-0076) and write fewer ASR lines than turns (SCN-ADV-0003), four attempts in a row each.
    from pydantic import ValidationError

    from src.schemas.scenario import as_draft, draft_schema

    shape = (("call_1", ("budget_vnd", "room_area_m2"), True), ("call_2", ("payment",), False))
    schema = draft_schema(shape)
    first = {"customer_goal": "Hỏi giá máy", "must_state": {"budget_vnd": 5_000_000, "room_area_m2": 20},
             "turns": [{"text": "Chào em", "asr": "chao em"}, {"text": "Giá sao em", "asr": "gia sao em"}]}
    second = {"customer_goal": "Mua máy nhé", "must_state": {"payment": "COD"}, "customer_turns": ["Chốt em", "COD nhé"]}
    with pytest.raises(ValidationError):
        schema.model_validate({"call_1": first})                                               # a call left out
    with pytest.raises(ValidationError):
        schema.model_validate({"call_1": {**first, "must_state": {"budget_vnd": 5_000_000}}, "call_2": second})
    draft = as_draft(schema.model_validate({"call_1": first, "call_2": second}), shape)
    one, two = draft.calls
    assert [c.call for c in draft.calls] == ["call_1", "call_2"]
    assert one.customer_turns_asr == ["chao em", "gia sao em"] and len(one.customer_turns) == 2
    assert {f.slot: f.value for f in one.facts_stated} == {"budget_vnd": 5_000_000, "room_area_m2": 20}
    assert two.customer_turns_asr == [] and two.facts_stated[0].value == "COD"
    assert draft_schema(shape).__name__ == schema.__name__   # stable: the model cache keys on the schema


def test_the_writer_is_told_which_call_is_the_first_contact(plans):
    from src.planning.planner import first_contact, writer_context

    for sp in plans:
        for pc, entry in zip(sp.calls, writer_context(sp, "")["calls"]):
            assert entry["first_contact"] is first_contact(sp, pc)
    assert any(first_contact(sp, sp.calls[0]) for sp in plans)


def test_a_customer_line_that_contradicts_the_plan_is_rejected(plans):
    # The planned value overrides the draft's, so "trả tiền khi nhận hàng" for a bank transfer reached the labels.
    sp = next(s for s in plans if any(pc.customer_must_state.get("payment") for pc in s.calls))
    calls = []
    for pc in sp.calls:
        facts = [{"slot": k, "value": ("COD" if v != "COD" else "bank") if k == "payment" else v}
                 for k, v in pc.customer_must_state.items()]
        turns = ["Chào em nhé"] * max(2, pc.template.min_turns)
        calls.append({"call": pc.name, "customer_goal": "Mua hàng", "customer_turns": turns, "facts_stated": facts,
                      "customer_turns_asr": turns if pc.input_mode != "text" else []})
    errors = check_draft(sp, ScenarioDraft.model_validate({"calls": calls}))
    assert any("must say payment" in e for e in errors), errors


def test_a_first_calls_day_is_chosen_for_what_it_tests(scenarios, advanced_scenarios, plans):
    from datetime import timedelta

    from src.utils.btc_tools import mock_tools

    mock = mock_tools()
    probes = {}
    for scenario in scenarios + advanced_scenarios:
        probe = next((t.split(":", 1)[1] for t in scenario.tags if t.startswith("date:")), None)
        assert probe is not None, scenario.scenario_id
        probes.setdefault(probe, []).append(scenario)
        day = scenario.calls["call_1"].call_date
        for call in scenario.calls.values():
            assert call.call_date.isoformat() not in mock.HOLIDAYS or call.kind == "consult_callback_holiday", \
                (scenario.scenario_id, call.call_date)          # the hotline is closed on LN-02's days off
        if probe == "sunday":
            assert day.weekday() == 6
        if probe == "promo_last_day":
            assert any(p["end"] == day.isoformat() for p in mock.PROMOS)
        if probe == "after_promo_end":
            assert any(p["end"] == (day - timedelta(days=1)).isoformat() for p in mock.PROMOS)
        if probe == "out_of_stock":
            assert scenario.calls["call_1"].ground_truth_facts["in_stock"] is False
    assert {"ordinary", "sunday", "promo_last_day", "after_promo_end"} <= set(probes)


def test_an_account_number_the_writer_filed_as_a_fact_never_reaches_the_labels():
    # gpt-4o-mini wrote the refund account the customer read out as payment "190157371104" (SCN-GEN-0158).
    from src.planning.planner import _usable_stated
    from src.schemas.scenario import StatedFact

    facts = [StatedFact(slot="payment", value="190157371104"), StatedFact(slot="payment", value="bank"),
             StatedFact(slot="budget_vnd", value=5_000_000), StatedFact(slot="color", value="079201000123")]
    assert _usable_stated(facts) == {"payment": "bank", "budget_vnd": 5_000_000}
