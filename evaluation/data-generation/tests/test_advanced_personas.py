"""The team's personas (config/personas_advanced.yaml) and the on-disk dataset layout."""
import json

from src.planning.call_kinds import HANDOFF_REASONS, NOT_SOLD_PHRASES
from src.planning.persona_config import load_persona_set, load_profiles
from src.utils.btc_tools import mock_tools
from src.utils.dataset import Dataset
from src.utils.paths import DATA_DIR


def by_variant(scenarios, name):
    return next(s for s in scenarios if f"variant:{name}" in s.tags)


def test_every_advanced_persona_is_planned_and_described(advanced_scenarios):
    targets = load_persona_set("advanced").targets
    assert {t["id"] for t in targets} == {s.persona for s in advanced_scenarios}
    profiles = load_profiles()
    assert all(profiles[t["id"]]["style"] and "{goal}" in profiles[t["id"]]["system_prompt"] for t in targets)
    assert all(s.scenario_id.startswith("SCN-ADV-") and s.persona_source == "advanced" for s in advanced_scenarios)


def test_m2_multi_channel_target(all_scenarios):
    channels = {}
    for s in all_scenarios:
        for call in s.calls.values():
            channels.setdefault(call.speaker_customer_id or s.customer_id, set()).add(call.channel)
    assert sum(len(c) >= 2 for c in channels.values()) >= 30


def test_product_not_sold_finds_nothing_and_suggests_another(advanced_scenarios):
    call = by_variant(advanced_scenarios, "khong_ban_roi_tu_van").calls["call_1"]
    search = next(tc for tc in call.oracle_tool_calls if tc["name"] == "catalog.search")
    assert search["result"]["total"] == 0
    assert call.success_if.must_say_any == NOT_SOLD_PHRASES and "order.create" in call.success_if.must_not_call_tools


def test_typing_modes_come_with_their_noisy_lines(advanced_plans):
    modes = {pc.input_mode for sp in advanced_plans for pc in sp.calls}
    assert {"chat_khong_dau", "chat_sai_chinh_ta", "asr_transcript"} <= modes


def test_warranty_in_and_out_of_term(advanced_scenarios):
    inside = by_variant(advanced_scenarios, "loi_trong_han").calls["call_1"]
    outside = by_variant(advanced_scenarios, "loi_het_han").calls["call_1"]
    assert inside.ground_truth_facts["in_warranty"] is True and outside.ground_truth_facts["in_warranty"] is False
    assert "order.update" in outside.success_if.must_not_call_tools
    assert inside.facts_established["order_id"] and inside.customer_turns


def test_return_in_window_refunds_the_price_paid(advanced_scenarios):
    s = by_variant(advanced_scenarios, "tra_hang_7_ngay")
    paid = s.calls["call_1"].success_if.args_match["price_vnd"]
    assert s.calls["call_2"].ground_truth_facts["refund_vnd"] == paid
    assert s.calls["call_2"].success_if.args_match["action"] == "return"


def test_cart_is_quoted_as_a_basket_and_ordered_whole(advanced_scenarios):
    s = by_variant(advanced_scenarios, "gio_hai_may_loc")
    cart, order = s.calls["call_1"], s.calls["call_2"]
    assert cart.ground_truth_facts["total_vnd"] == order.success_if.total_match_vnd
    quotes = [tc for tc in cart.oracle_tool_calls if tc["name"] == "pricing.get_quote"]
    assert all(tc["args"]["basket_skus"] for tc in quotes)


def test_ai_to_human_to_ai(advanced_scenarios):
    s = by_variant(advanced_scenarios, "doi_gap_nguoi_roi_ai_chot")
    handoff, back = s.calls["call_2"], s.calls["call_3"]
    schema = json.loads((DATA_DIR / "schemas" / "handoff_brief.schema.json").read_text(encoding="utf-8"))
    assert handoff.expected_outcome == "chuyen_may"
    assert set(schema["required"]) <= set(handoff.expected_handoff_brief)
    assert handoff.expected_handoff_brief["escalation_reason"] in schema["properties"]["escalation_reason"]["enum"]
    assert set(HANDOFF_REASONS.values()) <= set(schema["properties"]["escalation_reason"]["enum"])
    # Back with the AI: it continues from what was established and asks none of it again.
    assert back.expected_outcome == "chot_don" and back.must_carry_over and back.must_not_ask
    assert back.expected_call_brief["last_session"]["handled_by"] == "nhan_vien"


def test_anonymous_caller_is_unknown_to_the_crm(advanced_scenarios):
    s = by_variant(advanced_scenarios, "goi_tu_so_moi")
    assert mock_tools().crm_get_customer(phone=s.customer_phone)["found"] is False
    assert s.calls["call_1"].expected_call_brief is None and not s.calls["call_1"].seed_history
    assert s.calls["call_2"].expected_call_brief is not None   # the second call knows the first


def test_dataset_round_trip_stores_each_fact_once(tmp_path, advanced_scenarios):
    dataset = Dataset(tmp_path)
    for s in advanced_scenarios[:12]:
        dataset.write_scenario(s)
        assert dataset.load_scenario(s.scenario_id).model_dump() == s.model_dump()
    handoff = by_variant(advanced_scenarios, "doi_gap_nguoi_roi_ai_chot")
    dataset.write_scenario(handoff)
    assert dataset.call_path("handoff_brief", handoff.scenario_id, "call_2").exists()
    assert dataset.call_path("call_brief", handoff.scenario_id, "call_3").exists()
    assert dataset.call_path("tools", handoff.scenario_id, "call_2").exists()
    exported = json.loads((tmp_path / "scenarios" / f"{handoff.scenario_id}.json").read_text(encoding="utf-8"))
    assert "expected_handoff_brief" not in exported["calls"]["call_2"]
