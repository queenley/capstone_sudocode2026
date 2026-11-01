"""The extractor is shown each turn and, from the second call, the earlier calls of its own scenario; nothing else."""
import json

import pytest

from ai_agent_service.components.evaluation import scorers
from ai_agent_service.pipeline.eval import trace
from ai_agent_service.pipeline.eval.cli import ConfigRun, _label

SHOWN = {"agent_text", "tool_texts", "consultant_texts", "previous_sessions"}


def row(scenario, call, turn, tool_calls=(), facts=()):
    return {"run_id": "r", "config": "full", "scenario_id": scenario, "call": call, "turn": turn,
            "customer_text": f"{scenario} {call} khach {turn}", "agent_text": f"{scenario} {call} agent {turn}",
            "questions": [], "claims": [], "facts_used": list(facts), "tool_calls": list(tool_calls),
            "latency": {"ttft_ms": 1, "total_ms": 2, "ttfa_ms": None}, "memory_writes": [], "customer_input_mode": "clean"}


def rows():
    # Out of order on purpose: the history follows call and turn, not arrival.
    return [row("S1", "call_2", 2), row("S1", "call_1", 2), row("S1", "call_3", 1), row("S1", "call_1", 1),
            row("S1", "call_2", 1), row("S2", "call_1", 1), row("S2", "call_2", 1)]


def history_of(all_rows, scenario, call, turn):
    index = next(i for i, r in enumerate(all_rows) if (r["scenario_id"], r["call"], r["turn"]) == (scenario, call, turn))
    return scorers.previous_sessions(all_rows).get(index)


def test_the_first_call_has_no_earlier_session():
    assert history_of(rows(), "S1", "call_1", 1) is None and history_of(rows(), "S1", "call_1", 2) is None


def test_a_later_call_sees_every_turn_of_each_earlier_call_in_order():
    sessions = history_of(rows(), "S1", "call_3", 1)
    assert [s["call"] for s in sessions] == ["call_1", "call_2"]
    assert [t["customer"] for t in sessions[0]["turns"]] == ["S1 call_1 khach 1", "S1 call_1 khach 2"]
    assert [t["agent"] for t in sessions[1]["turns"]] == ["S1 call_2 agent 1", "S1 call_2 agent 2"]


def test_every_turn_of_a_call_sees_the_same_history():
    assert history_of(rows(), "S1", "call_2", 1) == history_of(rows(), "S1", "call_2", 2)


def test_scenarios_never_mix():
    assert [t["agent"] for t in history_of(rows(), "S2", "call_2", 1)[0]["turns"]] == ["S2 call_1 agent 1"]


def test_configurations_never_mix_even_if_a_caller_passes_both_traces():
    full = [row("S1", "call_1", 1), row("S1", "call_2", 1)]
    baseline = {**row("S1", "call_1", 1), "config": "baseline_no_memory", "agent_text": "BASELINE ONLY"}
    sessions = scorers.previous_sessions([full[0], baseline, full[1]])[2]
    assert [t["agent"] for t in sessions[0]["turns"]] == ["S1 call_1 agent 1"]


def test_call_order_is_numeric_not_lexicographic():
    history = scorers.previous_sessions([row("S1", "call_10", 1), row("S1", "call_2", 1), row("S1", "call_1", 1)])
    assert [s["call"] for s in history[0]] == ["call_1", "call_2"]
    assert [s["call"] for s in history[1]] == ["call_1"]


def test_the_model_is_never_shown_a_tools_result():
    data = scorers.turn_input("a", [{"name": "order.create", "args": {"sku": "A"}, "result": {"order_id": "SECRET"}}])
    assert set(data) <= SHOWN and "SECRET" not in json.dumps(data)
    assert data["tool_texts"] == ['{"args": {"sku": "A"}, "name": "order.create"}']


def test_history_is_whitelisted_instead_of_passing_labels_from_callers():
    data = scorers.turn_input("a", previous_sessions=[{"call": "call_1", "must_not_ask": ["SECRET"], "turns": [
        {"customer": "c", "agent": "a", "claims": ["SECRET"], "ground_truth_facts": {"SECRET": True}}]}])
    assert data["previous_sessions"] == [{"call": "call_1", "turns": [{"customer": "c", "agent": "a"}]}]
    assert "SECRET" not in json.dumps(data)


def test_facts_used_are_the_extractors_then_the_cited_each_once():
    assert trace.merged_facts_used(["price_quoted_vnd", "blocker"], ["blocker", "product_advised"]) == [
        "price_quoted_vnd", "blocker", "product_advised"]


class Recorder:
    """Stands in for the extractor: records what it was shown, labels one reused fact on later calls."""

    def __init__(self):
        self.shown = []

    async def label(self, data):
        self.shown.append(data)
        facts = ["room_area_m2"] if "previous_sessions" in data else []
        return {"items": [], "questions": [], "claims": [], "facts_used": facts, "dropped": 0, "changed": 0}

    def stats(self):
        return {}


@pytest.mark.asyncio
async def test_label_sends_history_and_merges_facts_into_the_trace():
    run_rows = [row("S1", "call_1", 1), row("S1", "call_2", 1, facts=["product_advised"])]
    run = ConfigRun(rows=run_rows, diagnostics=[{}, {}])
    recorder = Recorder()
    await _label(run, recorder)
    assert ["previous_sessions" in d for d in recorder.shown] == [False, True]
    assert all(set(d) <= SHOWN for d in recorder.shown)
    assert run.rows[1]["facts_used"] == ["room_area_m2", "product_advised"]
    assert run.rows[0]["facts_used"] == []
    assert all(trace.schema_errors(r) == [] for r in run.rows)
    assert run.diagnostics[1]["extraction_items"] == []
