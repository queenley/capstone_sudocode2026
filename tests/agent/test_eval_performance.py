"""``run_eval.py --performance``: read from a run's files, no model and no database."""

import json

import pytest

from ai_agent_service.pipeline.eval import cli, performance


def row(turn, ttft, total, brief=None):
    line = {"scenario_id": "S", "call": "call_1", "turn": turn, "input_mode": "text",
            "latency": {"ttft_ms": ttft, "total_ms": total, "ttfa_ms": None}}
    return {**line, "call_brief_latency_ms": brief} if brief is not None else line


@pytest.fixture
def run(tmp_path):
    rows = [row(1, 1000, 2000, 50), row(2, 2000, 4000)]
    (tmp_path / "full.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "usage.json").write_text(json.dumps({"full": [{
        "turns": {"advisor": {"calls": 2, "input": 1000, "output": 100}, "policy:jev": {"calls": 2, "input": 1000, "output": 0}},
        "after_call": {"memory": {"calls": 1, "input": 500, "output": 50}}}]}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"models": {"advisor": {"provider": "openai", "model": "gpt-4.1-mini"}}}), encoding="utf-8")
    return tmp_path


def test_cost_is_tokens_per_turn_at_each_list_price(run):
    figures = performance.measure(run)
    assert figures["turns"] == 2
    assert figures["tokens_per_turn"]["total"] == 1050
    # 1000 in, 100 out at 0.40/1.60, plus 1000 policy tokens at 0.042, over two turns.
    assert figures["tokens_per_turn"]["cost_usd"]["gpt-4.1-mini"] == pytest.approx(0.000301)
    assert figures["with_after_call"]["total"] == 1325


def test_what_the_run_did_not_measure_is_said_not_zero(run):
    (run / "usage.json").unlink()
    text = performance.table(performance.measure(run))
    assert "TTFA (voice)               chưa đo" in text
    assert "Số phiên đồng thời (demo)  chưa đo" in text
    assert "Token và chi phí           chưa đo" in text


def test_a_load_test_reports_the_largest_level_held():
    levels = [{"sessions": 1, "held": True, "ttft_p95_ms": 900, "total_p95_ms": 2000, "errors": 0},
              {"sessions": 5, "held": False, "ttft_p95_ms": 4000, "total_p95_ms": 9000, "errors": 1}]
    assert performance.sessions_line(levels).startswith("giữ được 1 phiên")


def test_a_finished_run_needs_no_database(run, capsys):
    assert cli.main(["--performance", str(run)]) == 0
    assert "Total Latency" in capsys.readouterr().out


def test_sessions_run_the_agent_so_a_finished_run_refuses_them(run):
    assert cli.main(["--performance", str(run), "--sessions", "1,3"]) == 2
