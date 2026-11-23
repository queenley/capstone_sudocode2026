"""What the admin's evaluation dashboard reads beside the four rates: quality counts and one row per scenario."""
import asyncio
import json

from ai_agent_service.pipeline.eval import history
from ai_agent_service.runtime import evaluations


def _run(directory):
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps({
        "run_id": "20261116-020000", "status": "COMPLETE", "started_at": "2026-11-16T02:00:00+00:00",
        "scenarios": {"files": {"A.json": "aa"}}, "models": {"advisor": {"model": "gpt-x"}, "extractor": {}},
        "problems": {"full": {"failed_turns": 1, "after_call_failed": 0, "safe_lines": 3, "turns": 4},
                     "baseline_no_memory": {"failed_turns": 0, "turns": 4}}}), encoding="utf-8")
    section = {
        "task_success_rate": {"value": 50.0, "hard_cases": {"value": 25.0},
                              "failures": [{"scenario": "SCN-2", "call": "call_2", "reasons": ["thiếu must_say_any: X"]}]},
        "guardrail_violations": {"total": 2, "by_type": {"over_escalation": 2, "claims_human": 0}},
        "avg_turns_per_call": 2.0, "calls_to_close": {"value": 1.5},
    }
    (directory / "report.json").write_text(json.dumps({"n_scenarios": 2, "system": section}), encoding="utf-8")
    rows = [
        {"scenario_id": "SCN-1", "call": "call_1", "turn": 1, "latency": {"ttft_ms": 1000}, "tool_calls": [{"name": "catalog.search", "result": {"items": []}}]},
        {"scenario_id": "SCN-2", "call": "call_1", "turn": 1, "latency": {"ttft_ms": 3000}, "tool_calls": [{"name": "pricing.get_quote", "result": {"error": "NOT_FOUND"}}]},
        {"scenario_id": "SCN-2", "call": "call_2", "turn": 1, "latency": {"ttft_ms": 5000}, "tool_calls": []},
    ]
    (directory / "full.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return directory


def test_quality_counts_and_report_figures_join_the_metrics(tmp_path):
    record = history.summary(_run(tmp_path / "r"))
    got = {(m["config"], m["metric"]): m["value"] for m in record["metrics"]}
    assert got[("full", "guardrail_violations")] == 2 and got[("full", "guardrail_over_escalation")] == 2
    assert got[("full", "TSR_hard_cases")] == 25.0 and got[("full", "calls_to_close")] == 1.5
    assert got[("full", "failed_turns")] == 1 and got[("full", "safe_lines")] == 3
    assert ("baseline_no_memory", "failed_turns") not in got  # no baseline section in this report


def test_each_scenario_has_a_verdict_its_reasons_and_what_it_took(tmp_path):
    rows = {r["scenario_id"]: r for r in history.summary(_run(tmp_path / "r"))["scenarios"]}
    assert rows["SCN-1"]["passed"] and rows["SCN-1"]["failures"] == []
    two = rows["SCN-2"]
    assert not two["passed"] and two["failures"][0]["reasons"] == ["thiếu must_say_any: X"]
    assert (two["calls"], two["turns"], two["tool_calls"], two["tool_errors"]) == (2, 2, 1, 1)
    assert two["ttft_p95_ms"] == 5000


class Conn:
    def __init__(self):
        self.sql = []

    def transaction(self):
        conn = self

        class T:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return T()

    async def execute(self, sql, params=None):
        self.sql.append((sql, params))


def test_ingesting_a_run_again_replaces_its_scenarios(tmp_path):
    conn = Conn()
    asyncio.run(evaluations.save_run(conn, history.summary(_run(tmp_path / "r"))))
    statements = [sql for sql, _ in conn.sql]
    assert any(s.startswith("DELETE FROM eval_scenarios") for s in statements)
    inserted = [p for sql, p in conn.sql if sql.startswith("INSERT INTO eval_scenarios")]
    assert sorted(p[2] for p in inserted) == ["SCN-1", "SCN-2"]
