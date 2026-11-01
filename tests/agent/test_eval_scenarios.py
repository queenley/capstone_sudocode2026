"""Reject invalid evaluation inputs before a paid turn can run."""
import json

import pytest

from ai_agent_service.config.config_manager import btc_data_dir
from ai_agent_service.pipeline.eval import scenarios


def scenario(**spec):
    return {"scenario_id": "SYNTHETIC", "calls": {"call_1": {"customer_turns": ["Synthetic request"], **spec}}}


@pytest.mark.parametrize("data", [
    [], {"scenario_id": "SYNTHETIC", "calls": {"wrong": {}}},
    {"scenario_id": "SYNTHETIC", "calls": {"call_1": None}},
    scenario(customer_turns="This must not become one model call per character"),
    scenario(customer_turns=[1]), scenario(customer_turns=[" "]), scenario(customer_turns=[]),
    scenario(customer_turns_asr=None), scenario(customer_turns_asr=[]),
    {"calls": {"call_1": {"customer_turns": ["Synthetic request"]}}},
])
def test_bad_input_is_a_rejection_instead_of_a_crash_or_paid_turn(tmp_path, data):
    (tmp_path / "synthetic.json").write_text(json.dumps(data), encoding="utf-8")
    ready, rejected = scenarios.load(tmp_path)
    assert not ready and len(rejected) == 1 and rejected[0].reason


def test_duplicate_and_missing_requested_ids_are_reported(tmp_path):
    for name in ("first", "second"):
        (tmp_path / f"{name}.json").write_text(json.dumps(scenario()), encoding="utf-8")
    ready, rejected = scenarios.load(tmp_path, {"SYNTHETIC", "MISSING"})
    assert len(ready) == 1
    assert {item.scenario_id for item in rejected} == {"SYNTHETIC", "MISSING"}
    assert any("duplicate" in item.reason for item in rejected)


@pytest.mark.parametrize("seed", [
    {"date": "2026-10-16", "facts": {"budget_vnd": 123000}},
    {"days_before": -1, "facts": {"budget_vnd": 123000}},
    {"days_before": 1, "channel": "unknown", "facts": {"budget_vnd": 123000}},
    {"days_before": 1, "facts": {"unknown-slot": "value"}},
    {"days_before": 1, "facts": {"budget_vnd": "123000"}},
    {"days_before": 1, "facts": {"budget_vnd": {"value": 123000}}},
])
def test_future_or_unknown_channel_seed_cannot_change_the_measurement(seed):
    with pytest.raises(scenarios.ScenarioError):
        scenarios.plan(scenario(seed_history=[seed]))


def test_organisers_public_inputs_still_plan_without_changes():
    ready, rejected = scenarios.load(btc_data_dir() / "test_set" / "public_sample")
    assert len(ready) == 7 and not rejected


def test_asr_turns_and_original_call_timing_are_preserved():
    data = scenario(customer_turns_asr=["Noisy request"])
    data["calls"]["call_2"] = {"days_later": 2, "customer_turns": ["Return request"]}
    first, second = scenarios.plan(data)
    assert first.turns == ("Noisy request",) and first.trace_input_mode == "asr_transcript"
    assert second.on == "2026-10-17" and second.turns == ("Return request",)


def test_documented_order_history_without_explicit_summary_can_be_seeded():
    plan, = scenarios.plan(scenario(seed_history=[{
        "days_before": 1, "order_id": "SYNTHETIC-ORDER", "sku": "SYNTHETIC-SKU", "status": "done"}]))
    assert plan.seed[0].day == "2026-10-14"
    assert plan.seed[0].summary == "Đơn SYNTHETIC-ORDER: SYNTHETIC-SKU (done)."
