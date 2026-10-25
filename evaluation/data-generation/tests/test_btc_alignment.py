"""Our labels and traces must agree with BTC's own reference code (data/eval/)."""
import json

from src.ground_truth.traces import oracle_rows
from src.metrics.btc_metrics import evaluate, group_rows
from src.utils.btc_tools import reference_eval
from src.utils.paths import DATA_DIR


def test_adapter_reproduces_btc_example_report():
    """reference_eval on BTC's public sample + example trace must give BTC's own example numbers."""
    ref = reference_eval()
    scenarios = ref.load_scenarios(str(DATA_DIR / "sample"))
    rows = [json.loads(line) for line in (DATA_DIR / "eval" / "runs" / "full.jsonl").read_text(encoding="utf-8").splitlines()]
    ours = evaluate(scenarios, rows)
    theirs = json.loads((DATA_DIR / "eval" / "runs" / "report_example.json").read_text(encoding="utf-8"))["system"]
    for key in ("repeat_question_rate", "context_carryover_rate", "task_success_rate", "hallucination_rate"):
        assert ours[key]["value"] == theirs[key]["value"], key


def test_oracle_trace_is_perfect_under_official_script(scenarios):
    exported = {s.scenario_id: s.btc_export() for s in scenarios}
    report = evaluate(exported, [row for s in scenarios for row in oracle_rows(s)])
    assert report["repeat_question_rate"]["value"] == 0.0
    assert report["context_carryover_rate"]["value"] == 100.0
    assert report["task_success_rate"]["value"] == 100.0, report["task_success_rate"]["failures"][:5]
    assert report["task_success_rate"]["hard_cases"]["value"] == 100.0
    assert report["hallucination_rate"]["value"] == 0.0
    assert report["guardrail_violations"]["total"] == 0, report["guardrail_violations"]["examples"]
    assert all(m["verdict"] == "likely_ok" for m in report["memory_checks"])


def test_trace_rows_have_btc_fields(scenarios):
    required = {"run_id", "config", "scenario_id", "call", "turn", "customer_text", "agent_text", "questions",
                "claims", "tool_calls", "latency", "facts_used"}
    rows = oracle_rows(scenarios[0])
    assert all(required <= set(row) for row in rows)
    assert list(group_rows(rows)) == [(scenarios[0].scenario_id, name) for name in scenarios[0].calls]


def test_btc_export_shape(scenarios):
    payload = scenarios[0].btc_export()
    call = payload["calls"]["call_1"]
    assert "tool_called" in call["success_if"]
    assert "oracle_tool_calls" not in call and "simulator_persona_key" not in call
    assert isinstance(call.get("memory_expectation", {}), dict)
