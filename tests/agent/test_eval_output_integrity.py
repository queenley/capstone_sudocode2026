"""A table must belong to this run and remain readable on Windows pipes."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ai_agent_service.pipeline.eval import cli, report, runner, scenarios


def test_reference_grader_uses_utf8_even_with_a_legacy_parent_encoding(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    source = tmp_path / "scenarios"
    source.mkdir()
    (source / "synthetic.json").write_text(json.dumps({"scenario_id": "SYNTHETIC-UTF8",
        "calls": {"call_1": {"customer_turns": ["Synthetic request"]}}}), encoding="utf-8")
    full = tmp_path / "full.jsonl"
    full.write_text(json.dumps({"run_id": "synthetic", "config": "full", "scenario_id": "SYNTHETIC-UTF8",
        "call": "call_1", "turn": 1, "customer_text": "Synthetic request", "agent_text": "Synthetic reply",
        "questions": [], "claims": [], "facts_used": [], "tool_calls": [], "memory_writes": [],
        "latency": {"ttft_ms": 1, "total_ms": 2, "ttfa_ms": None}}) + "\n", encoding="utf-8")
    code, table = report.grade(source, full=full, baseline=None, out=tmp_path / "report.json")
    assert code == 0, table
    assert "Chỉ số" in table and "Hệ thống" in table
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["n_scenarios"] == 1


@pytest.mark.parametrize("name", ["table.txt", "full.jsonl", "trace_without_suffix"])
def test_cli_refuses_to_overwrite_run_evidence_before_opening_database(tmp_path, monkeypatch, name):
    single = name != "table.txt"
    source = tmp_path / "input"
    source.mkdir()
    (source / "synthetic.json").write_text(json.dumps({"scenario_id": "SYNTHETIC-1",
        "calls": {"call_1": {"customer_turns": ["Synthetic request"]}}}))
    monkeypatch.setattr(cli, "validate_ledger", lambda: None)
    output = tmp_path / "output"
    output.mkdir()
    old = output / name
    old.write_text("previous evidence", encoding="utf-8")
    database = Mock(side_effect=AssertionError("Existing evidence must be checked before DB or model use"))
    monkeypatch.setattr(runner, "use_evaluation_database", database)
    arguments = ["--scenarios", str(source), "--out", str(old if single else output)]
    if single:
        arguments += ["--config", "full"]
    assert cli.main(arguments) == 2
    database.assert_not_called()
    assert old.read_text(encoding="utf-8") == "previous evidence"


def test_root_entrypoint_can_print_vietnamese_to_a_legacy_encoded_pipe(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    missing = tmp_path / "thư mục không có"
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "run_eval.py"), "--scenarios", str(missing)],
                            capture_output=True, encoding="utf-8")
    assert result.returncode == 2, result.stderr
    assert str(missing) in result.stdout and "UnicodeEncodeError" not in result.stderr


def test_single_config_prefix_is_literal_and_preserves_other_configs(tmp_path):
    (tmp_path / "baseline.manifest.json").write_text("other configuration")
    layout = cli.Layout(tmp_path, {"full": tmp_path / "trace[1].jsonl"}, prefix="trace[1].")
    cli.prepare_output(layout)
    (tmp_path / "trace[1].manifest.json").write_text("old partial run")
    with pytest.raises(ValueError, match="Output already contains"):
        cli.prepare_output(layout)


def test_setup_exception_leaves_incomplete_evidence_and_no_table(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "use_evaluation_database", lambda: "synthetic_eval")
    monkeypatch.setattr(cli, "validate_ledger", lambda: None)
    monkeypatch.setattr(cli, "_evaluate_locked", AsyncMock(side_effect=RuntimeError("synthetic MCP startup failure")))
    (tmp_path / "synthetic.json").write_text(json.dumps({"scenario_id": "SYNTHETIC-1",
        "calls": {"call_1": {"customer_turns": ["Synthetic request"]}}}))
    monkeypatch.setenv("MCP_LOG_FILE", "before.log")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    out = tmp_path / "output"
    assert cli.main(["--scenarios", str(tmp_path), "--out", str(out)]) == 1
    assert json.loads((out / "manifest.json").read_text())["status"] == "INCOMPLETE"
    assert "synthetic MCP startup failure" in (out / "evaluation-error.log").read_text()
    assert not (out / "table.txt").exists()


@pytest.mark.asyncio
async def test_failed_scorer_cannot_leave_a_complete_manifest_or_table(tmp_path, monkeypatch):
    from ai_agent_service.llm import jev
    from ai_agent_service.mcp import client

    (tmp_path / "synthetic.json").write_text(json.dumps({"scenario_id": "SYNTHETIC-1",
        "calls": {"call_1": {"customer_turns": ["Synthetic request"]}}}))
    monkeypatch.setattr(runner, "build", AsyncMock(return_value=SimpleNamespace(
        provider="synthetic", advisor=SimpleNamespace(model_name="synthetic"))))
    monkeypatch.setattr(runner, "warm_up", AsyncMock())
    monkeypatch.setattr(runner, "run_scenario", AsyncMock(return_value=runner.ScenarioRun(rows=[{}], diagnostics=[{}])))
    from ai_agent_service.pipeline.eval import trace
    monkeypatch.setattr(trace, "schema_errors", lambda row: [])
    monkeypatch.setattr(cli, "_extractor", lambda: SimpleNamespace(model_name="synthetic", stats=lambda: {}))
    monkeypatch.setattr(cli, "_label", AsyncMock())
    monkeypatch.setattr(cli, "_retrieval", lambda path: "synthetic retrieval")
    monkeypatch.setattr(report, "manifest", lambda **kwargs: {"problems": kwargs["found"]})
    monkeypatch.setattr(report, "freeze", lambda *args: tmp_path)
    monkeypatch.setattr(report, "trace_errors", lambda *args: [])
    monkeypatch.setattr(report, "grade", lambda *args, **kwargs: (1, "synthetic scorer failure"))
    monkeypatch.setattr(client, "close_all", AsyncMock())
    monkeypatch.setattr(jev, "close", AsyncMock())
    layout = cli.Layout(tmp_path, {"full": tmp_path / "full.jsonl", "baseline_no_memory": tmp_path / "baseline.jsonl"})
    args = cli.parser().parse_args(["--scenarios", str(tmp_path), "--warmup", "0"])
    assert await cli._evaluate(args, run_id="synthetic", layout=layout, database="synthetic_eval") == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["status"] == "INCOMPLETE" and manifest["failure"]["stage"] == "scoring"
    assert (tmp_path / "scoring-error.txt").read_text().strip() == "synthetic scorer failure"
    assert not (tmp_path / "table.txt").exists()
