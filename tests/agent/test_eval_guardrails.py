"""Synthetic evaluation evidence must fail closed before spend or publication."""
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from ai_agent_service.pipeline.eval import cli, relabel, report, runner, scenarios


def cohort(path):
    path.mkdir(exist_ok=True)
    (path / "synthetic.json").write_text(json.dumps({"scenario_id": "SYNTHETIC-1",
        "calls": {"call_1": {"customer_turns": ["Synthetic request", "Synthetic followup"]}}}))
    return path


def rows(config="full"):
    return [{"run_id": "synthetic", "config": config, "scenario_id": "SYNTHETIC-1", "call": "call_1",
             "turn": index, "customer_text": text, "agent_text": "Synthetic reply", "questions": [],
             "claims": [], "facts_used": [], "tool_calls": [], "memory_writes": [],
             "latency": {"ttft_ms": 1, "total_ms": 2, "ttfa_ms": None}}
            for index, text in enumerate(("Synthetic request", "Synthetic followup"), 1)]


@pytest.mark.parametrize("options", [[], ["--no-extract"], ["--relabel", "SOURCE"]])
def test_model_backed_modes_require_ledger_before_database_or_models(tmp_path, monkeypatch, options):
    source = cohort(tmp_path / "source")
    monkeypatch.delenv("EVAL_BUDGET_DB", raising=False)
    db, extractor = Mock(), Mock()
    monkeypatch.setattr(runner, "use_evaluation_database", db)
    monkeypatch.setattr(cli, "_extractor", extractor)
    arguments = ["--scenarios", str(source), "--out", str(tmp_path / "out"), *options]
    assert cli.main(arguments) == 2
    db.assert_not_called()
    extractor.assert_not_called()
    assert not (tmp_path / "out").exists()


def test_bad_selection_does_not_open_database_or_call_model(tmp_path, monkeypatch):
    source = cohort(tmp_path / "source")
    db = Mock()
    monkeypatch.setattr(runner, "use_evaluation_database", db)
    assert cli.main(["--scenarios", str(source), "--only", "MISSING", "--out", str(tmp_path / "out")]) == 2
    db.assert_not_called()


def test_four_call_scenario_is_rejected_before_producing_out_of_schema_traces():
    with pytest.raises(scenarios.ScenarioError, match="at most three"):
        scenarios.plan({"calls": {f"call_{i}": {"customer_turns": ["Synthetic request"]} for i in range(1, 5)}})


def test_cohort_reservation_blocks_single_config_but_distinct_configs_can_share_parent(tmp_path):
    whole = tmp_path / "whole"
    cli.prepare_output(cli.Layout(whole, {}))
    with pytest.raises(ValueError, match="already contains"):
        cli.prepare_output(cli.Layout(whole, {"full": whole / "full.jsonl"}, prefix="full."))
    paired = tmp_path / "paired"
    for name in ("full", "baseline"):
        cli.prepare_output(cli.Layout(paired, {name: paired / f"{name}.jsonl"}, prefix=f"{name}."))
    with pytest.raises(ValueError, match="already contains"):
        cli.prepare_output(cli.Layout(paired, {}))


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "config", "customer", "run_id", "schema"])
def test_grader_refuses_incomplete_or_mixed_evidence_before_scoring(tmp_path, monkeypatch, corruption):
    source = cohort(tmp_path / "source")
    evidence = rows()
    if corruption == "missing":
        evidence.pop()
    elif corruption == "duplicate":
        evidence.append(evidence[0])
    elif corruption == "config":
        evidence[0]["config"] = "baseline_no_memory"
    elif corruption == "customer":
        evidence[0]["customer_text"] = "Different input"
    elif corruption == "run_id":
        evidence[0]["run_id"] = "another"
    else:
        evidence[0]["latency"]["total_ms"] = None
    full = tmp_path / "full.jsonl"
    full.write_text("\n".join(json.dumps(row) for row in evidence))
    scorer = Mock()
    monkeypatch.setattr(report.subprocess, "run", scorer)
    code, detail = report.grade(source, full=full, baseline=None, out=tmp_path / "report.json")
    assert code == 1 and "Not scored" in detail
    scorer.assert_not_called()


def test_freeze_uses_loaded_scenarios_even_if_source_changes(tmp_path):
    source = cohort(tmp_path / "source")
    ready, rejected = scenarios.load(source)
    before = ready[0].data
    ready[0].path.write_text('{"scenario_id":"changed"}')
    frozen = report.freeze(ready, rejected, tmp_path / "frozen")
    assert json.loads((frozen / "synthetic.json").read_text()) == before


@pytest.mark.asyncio
async def test_relabel_rejects_partial_evidence_without_extractor_calls(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    cohort(source / "scenarios")
    (source / "full.jsonl").write_text(json.dumps(rows()[0]) + "\n")
    label = AsyncMock()
    monkeypatch.setattr(cli, "_label", label)
    assert await relabel.relabel(source, tmp_path / "out", object()) == 1
    label.assert_not_awaited()
    assert not (tmp_path / "out/table.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["scorer", "extractor"])
async def test_relabel_failure_stays_incomplete_and_never_prints_a_table(tmp_path, monkeypatch, capsys, failure):
    from types import SimpleNamespace

    source = tmp_path / "source"
    source.mkdir()
    cohort(source / "scenarios")
    (source / "full.jsonl").write_text("\n".join(json.dumps(row) for row in rows()))
    extractor = SimpleNamespace(model_name="synthetic", stats=lambda: {})
    monkeypatch.setattr(cli, "_label", AsyncMock(side_effect=RuntimeError("synthetic") if failure == "extractor" else None))
    monkeypatch.setattr(report, "grade", Mock(return_value=(1, "synthetic scorer failed")))
    out = tmp_path / "out"
    assert await relabel.relabel(source, out, extractor) == 1
    assert json.loads((out / "relabel.json").read_text())["status"] == "INCOMPLETE"
    assert not (out / "table.txt").exists()
    assert "synthetic scorer failed" not in capsys.readouterr().out


def test_relabel_rejects_unknown_source_execution_failure(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"status": "INCOMPLETE", "failure": {"type": "RuntimeError"}}))
    assert relabel.source_errors(tmp_path, {"full": tmp_path / "full.jsonl"}, {"full": rows()})


@pytest.mark.asyncio
async def test_database_lock_wraps_the_entire_evaluation(monkeypatch):
    events = []

    @asynccontextmanager
    async def locked():
        events.append("acquired")
        try:
            yield
        finally:
            events.append("released")

    async def evaluate(*args, **kwargs):
        assert events == ["acquired"]
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(runner, "evaluation_lock", locked)
    monkeypatch.setattr(cli, "_evaluate", evaluate)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await cli._evaluate_locked(object())
    assert events == ["acquired", "released"]


@pytest.fixture
def evaluation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ai_agent_service.llm import jev
    from ai_agent_service.mcp import client

    source = cohort(tmp_path / "source")
    out = tmp_path / "out"
    out.mkdir()
    args = cli.parser().parse_args(["--scenarios", str(source), "--config", "full", "--warmup", "0"])
    layout = cli.Layout(out, {"full": out / "full.jsonl"})
    run = runner.ScenarioRun(rows=rows(), diagnostics=[{"config": "full", "scenario_id": "SYNTHETIC-1",
        "call": "call_1", "turn": index} for index in (1, 2)])
    monkeypatch.setattr(runner, "build", AsyncMock(return_value=SimpleNamespace(
        provider="synthetic", advisor=SimpleNamespace(model_name="synthetic"))))
    monkeypatch.setattr(runner, "warm_up", AsyncMock())
    monkeypatch.setattr(runner, "run_scenario", AsyncMock(return_value=run))
    monkeypatch.setattr(cli, "_extractor", lambda: SimpleNamespace(model_name="synthetic", stats=lambda: {}))
    monkeypatch.setattr(report, "manifest", lambda **kwargs: {"problems": kwargs["found"]})
    monkeypatch.setattr(client, "close_all", AsyncMock())
    monkeypatch.setattr(jev, "close", AsyncMock())
    return args, layout, run


@pytest.mark.asyncio
async def test_single_config_requires_complete_trace_before_labelling(evaluation, monkeypatch):
    args, layout, run = evaluation
    run.rows.pop()
    run.diagnostics.pop()
    label = AsyncMock()
    monkeypatch.setattr(cli, "_label", label)
    assert await cli._evaluate(args, run_id="synthetic", layout=layout, database="synthetic_eval") == 1
    label.assert_not_awaited()
    assert json.loads(layout.side("manifest.json").read_text())["status"] == "INCOMPLETE"


@pytest.mark.asyncio
async def test_paid_replies_survive_unexpected_extractor_failure(evaluation, monkeypatch):
    args, layout, run = evaluation
    monkeypatch.setattr(cli, "_label", AsyncMock(side_effect=RuntimeError("synthetic extractor failure")))
    with pytest.raises(RuntimeError, match="synthetic extractor failure"):
        await cli._evaluate(args, run_id="synthetic", layout=layout, database="synthetic_eval")
    assert [json.loads(line) for line in layout.traces["full"].read_text().splitlines()] == run.rows
    assert layout.side("diagnostics.jsonl").exists()
    assert json.loads(layout.side("manifest.json").read_text())["status"] == "INCOMPLETE"


@pytest.mark.asyncio
async def test_real_extractor_only_stop_can_be_relabelled(evaluation, monkeypatch):
    from types import SimpleNamespace

    args, layout, _ = evaluation
    empty = {"questions": [], "claims": [], "facts_used": [], "items": [], "dropped": 0, "changed": 0}
    broken = SimpleNamespace(model_name="synthetic", stats=lambda: {},
        label=AsyncMock(return_value={**empty, "error": "synthetic extractor failure"}))
    monkeypatch.setattr(cli, "_extractor", lambda: broken)
    assert await cli._evaluate(args, run_id="synthetic", layout=layout, database="synthetic_eval") == 1
    manifest = json.loads(layout.side("manifest.json").read_text())
    assert manifest["problems"]["full"]["unlabelled_turns"] == 1
    assert manifest["problems"]["full"]["scenarios_stopped"] == 0
    fixed = SimpleNamespace(model_name="synthetic", stats=lambda: {}, label=AsyncMock(return_value=empty))
    out = layout.directory.parent / "relabelled"
    assert await relabel.relabel(layout.directory, out, fixed) == 0
    assert fixed.label.await_count == 2
    assert json.loads((out / "relabel.json").read_text())["status"] == "COMPLETE"


def test_asr_smoke_stdout_keeps_transcript_in_private_evidence(tmp_path, monkeypatch, capsys):
    from ai_agent_service.pipeline.eval import asr

    monkeypatch.setattr(asr, "audio_smoke", lambda *args: {"status": "UNLABELLED", "WER": None,
        "CER": None, "text": "private synthetic transcript"})
    assert cli.main(["--asr-audio", str(tmp_path / "sample.wav"), "--asr-transcribe", "--out", str(tmp_path / "out")]) == 0
    assert "private synthetic transcript" not in capsys.readouterr().out
