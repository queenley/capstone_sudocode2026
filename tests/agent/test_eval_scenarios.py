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
    {"days_before": 1, "facts": [{"field": "budget_vnd"}]},
    {"days_before": 1, "facts": [{"field": "budget_vnd", "value": 123000, "as_of": "not a date"}]},
    {"days_before": 1, "facts": "budget 123000"},
])
def test_future_or_unknown_channel_seed_cannot_change_the_measurement(seed):
    with pytest.raises(scenarios.ScenarioError):
        scenarios.plan(scenario(seed_history=[seed]))


def test_the_organisers_seed_history_example_is_seeded():
    """BTC's answers of 11/2026 (part 2, question 2): facts are a list of {field, value, as_of}, channel ``phone``."""
    plan, = scenarios.plan(scenario(seed_history=[{
        "session_id": "S-C031-0917", "date": "2026-09-17", "channel": "phone",
        "summary": "Khách hỏi máy lọc AP-X, hẹn gọi lại sau khi lĩnh lương.", "outcome": "hen_goi_lai",
        "facts": [{"field": "interest_sku", "value": "SKU-AP-X", "as_of": "2026-09-17"},
                  {"field": "address", "value": "12 Nguyễn Trãi, Thanh Xuân, Hà Nội", "as_of": "2026-09-17"}]}]))
    seed, = plan.seed
    assert (seed.session_id, seed.day, seed.channel, seed.outcome) == ("S-C031-0917", "2026-09-17", "hotline", "hen_goi_lai")
    assert seed.facts == {"product_advised": "SKU-AP-X"}
    assert "12 Nguyễn Trãi, Thanh Xuân, Hà Nội" in seed.summary


def test_a_field_no_slot_holds_goes_to_the_summary_instead_of_failing_the_scenario():
    plan, = scenarios.plan(scenario(seed_history=[{"days_before": 1, "summary": "Synthetic session",
                                                   "facts": [{"field": "unknown-slot", "value": "value"},
                                                             {"field": "budget_vnd", "value": {"value": 1}}]}]))
    assert plan.seed[0].facts == {} and "unknown-slot: value" in plan.seed[0].summary


def test_the_latest_as_of_wins_even_from_an_earlier_session():
    """Two values of one field: the later as_of wins (BTC), so an older value recorded later is not written after it."""
    plan, = scenarios.plan(scenario(seed_history=[
        {"date": "2026-09-01", "summary": "First", "facts": [{"field": "room_area_m2", "value": 20, "as_of": "2026-09-01"},
                                                              {"field": "room_area_m2", "value": 15, "as_of": "2026-08-01"}]},
        {"date": "2026-10-01", "summary": "Second", "facts": [{"field": "room_area_m2", "value": 25, "as_of": "2026-08-15"},
                                                               {"field": "budget_vnd", "value": 5000000}]}]))
    first, second = plan.seed
    assert first.facts == {"room_area_m2": 20}
    assert second.facts == {"budget_vnd": 5000000}


def test_a_session_without_facts_keeps_its_summary_for_extraction():
    plan, = scenarios.plan(scenario(seed_history=[{"date": "2026-10-01", "summary": "Hỏi nồi chiên Xiaomi 4.5L", "facts": []}]))
    assert plan.seed[0].facts == {} and plan.seed[0].summary == "Hỏi nồi chiên Xiaomi 4.5L"


def test_facts_are_read_from_the_summary_when_the_seed_gives_none():
    import asyncio

    from ai_agent_service.agents.memory import MemoryAgent
    from ai_agent_service.pipeline.eval import runner

    found = asyncio.run(runner.facts_from_summary(
        MemoryAgent(use_model=False), "Khách hỏi máy lọc AP-X, phòng 20 mét vuông.", on="2026-09-17"))
    assert found["room_area_m2"] == 20
    assert "product_advised" not in found  # no word matching of ours: the product stays in the summary the brief shows


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


def test_a_crm_session_channel_is_seeded_under_the_products_name():
    """The synthetic CRM writes ``fb`` for Facebook; a seed that carries it is that channel, not an unknown one."""
    plan, = scenarios.plan(scenario(seed_history=[
        {"days_before": 1, "channel": "fb", "summary": "Synthetic session"},
        {"days_before": 1, "channel": "web", "summary": "Synthetic session"}]))
    assert [s.channel for s in plan.seed] == ["facebook", "web"]


def test_a_skills_version_asked_for_is_the_one_the_advisor_reads(tmp_path, monkeypatch):
    """--skills-version is read after the skills module was imported: it must be read again (ablation, 2026-11-24)."""
    from ai_agent_service.components.context import skills as skill_book

    folder = tmp_path / "skills"
    folder.mkdir()
    learned = {"place-order": {"description": "d", "done_on": [], "body": "- learned line"}}
    (folder / "v7.yaml").write_text(__import__("yaml").safe_dump(learned, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(skill_book, "versions_dir", lambda: folder)
    monkeypatch.setenv("EVAL_SKILLS_VERSION", "7")
    try:
        assert skill_book.reload() == 7 and skill_book.SKILLS == learned
    finally:
        monkeypatch.delenv("EVAL_SKILLS_VERSION")
        skill_book.reload()
