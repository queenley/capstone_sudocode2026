"""Seed/infrastructure failures must never become a zero-score evaluation.

All scenarios/replies here are synthetic; no provider, database or BTC labels.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ai_agent_service.pipeline.eval import cli, relabel, report, runner, scenarios


def row(config="full"):
    return {"run_id": "synthetic", "config": config, "scenario_id": "SYNTHETIC-1", "call": "call_1", "turn": 1,
            "customer_text": "Synthetic request", "agent_text": "Synthetic reply", "questions": [], "claims": [],
            "facts_used": [], "tool_calls": [], "memory_writes": [], "customer_input_mode": "clean",
            "latency": {"ttft_ms": 1, "total_ms": 2, "ttfa_ms": None}}


@pytest.mark.parametrize("rows", [[], [row()]])
def test_a_stopped_scenario_blocks_even_without_a_failed_turn(rows):
    found = report.problems(rows, [], schema_errors=0, rejected=0, scenario_errors=1)
    assert found["failed_turns"] == 0
    assert report.blocking({"full": found})["scenarios_stopped"] == 1


def test_a_rejected_member_does_not_silently_shrink_the_cohort():
    found = report.problems([row()], [], schema_errors=0, rejected=1, scenario_errors=0)
    assert report.blocking({"full": found})["scenarios_rejected"] == 1


def test_empty_evidence_has_its_own_blocking_count():
    found = report.problems(iter(()), [], schema_errors=0, rejected=0, scenario_errors=0)
    assert found["turns"] == 0 and found["empty_trace"] == 1
    assert report.blocking({"full": found})["empty_trace"] == 1
    valid = report.problems(iter([row()]), [], schema_errors=0, rejected=0, scenario_errors=0)
    assert valid["turns"] == 1 and valid["empty_trace"] == 0
    assert report.blocking({"full": valid}) == {}


def test_blocking_counts_include_both_configurations():
    found = {config: report.problems([], [], schema_errors=0, rejected=0, scenario_errors=1)
             for config in ("full", "baseline_no_memory")}
    assert report.blocking(found)["scenarios_stopped"] == 2
    assert report.blocking(found)["empty_trace"] == 2


@pytest.mark.asyncio
async def test_seed_timeout_is_saved_without_labelling_baseline_retrieval_or_grading(monkeypatch, tmp_path):
    from ai_agent_service.llm import jev
    from ai_agent_service.mcp import client

    failure = "seed S-SYNTHETIC: memory_commit_facts TIMEOUT before the first turn"
    args = cli.parser().parse_args(["--scenarios", str(tmp_path), "--warmup", "0"])
    monkeypatch.setattr(scenarios, "load", lambda *args: ([SimpleNamespace(scenario_id="SYNTHETIC-1"),
                                                         SimpleNamespace(scenario_id="SYNTHETIC-2")], []))
    monkeypatch.setattr(runner, "build", AsyncMock(return_value=SimpleNamespace(
        provider="synthetic", advisor=SimpleNamespace(model_name="synthetic"))))
    monkeypatch.setattr(runner, "warm_up", AsyncMock())
    run_scenario = AsyncMock(return_value=runner.ScenarioRun(error=failure))
    monkeypatch.setattr(runner, "run_scenario", run_scenario)
    monkeypatch.setattr(cli, "_extractor", lambda: SimpleNamespace(model_name="synthetic", stats=lambda: {}))
    label, grade, retrieval = AsyncMock(), Mock(), Mock()
    monkeypatch.setattr(cli, "_label", label)
    monkeypatch.setattr(report, "grade", grade)
    monkeypatch.setattr(cli, "_retrieval", retrieval)
    monkeypatch.setattr(report, "manifest", lambda **kwargs: {"problems": kwargs["found"]})
    monkeypatch.setattr(client, "close_all", AsyncMock())
    monkeypatch.setattr(jev, "close", AsyncMock())
    layout = cli.Layout(tmp_path, {"full": tmp_path / "full.jsonl", "baseline_no_memory": tmp_path / "baseline.jsonl"})

    assert await cli._evaluate(args, run_id="synthetic", layout=layout, database="synthetic_eval") == 1
    run_scenario.assert_awaited_once()
    label.assert_not_awaited()
    grade.assert_not_called()
    retrieval.assert_not_called()
    assert (tmp_path / "full.jsonl").read_text() == ""
    assert not (tmp_path / "baseline.jsonl").exists()
    assert not (tmp_path / "report.json").exists() and not (tmp_path / "table.txt").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["problems"]["full"]["scenarios_stopped"] == 1
    artifacts = "\n".join(p.read_text() for p in tmp_path.iterdir() if p.suffix in {".json", ".jsonl"})
    assert failure in artifacts


def source_run(tmp_path, *, empty=False):
    source = tmp_path / "source"
    source.mkdir()
    scenarios_dir = source / "scenarios"
    scenarios_dir.mkdir()
    (scenarios_dir / "SYNTHETIC-1.json").write_text(json.dumps({"scenario_id": "SYNTHETIC-1",
        "calls": {"call_1": {"customer_turns": ["Synthetic request"]}}}))
    for config, name in (("full", "full.jsonl"), ("baseline_no_memory", "baseline.jsonl")):
        (source / name).write_text("" if empty else json.dumps(row(config)) + "\n")
    return source


@pytest.fixture
def fake_relabel(monkeypatch):
    label = AsyncMock()
    grade = Mock(return_value=(0, "synthetic grader result"))
    monkeypatch.setattr(cli, "_label", label)
    monkeypatch.setattr(report, "grade", grade)
    monkeypatch.setattr(relabel.trace, "schema_errors", lambda _: [])
    extractor = SimpleNamespace(model_name="synthetic", stats=lambda: {})
    return extractor, label, grade


@pytest.mark.asyncio
async def test_relabel_rejects_empty_source_before_paying_for_labels(tmp_path, fake_relabel):
    extractor, label, grade = fake_relabel
    source = source_run(tmp_path, empty=True)
    original = (source / "full.jsonl").read_bytes()
    out = tmp_path / "relabeled"
    assert await relabel.relabel(source, out, extractor) == 1
    label.assert_not_awaited()
    grade.assert_not_called()
    assert (source / "full.jsonl").read_bytes() == original
    assert not (out / "report.json").exists() and not (out / "table.txt").exists()


@pytest.mark.asyncio
async def test_relabel_does_not_repair_a_seed_failure_by_relabelling_partial_replies(tmp_path, fake_relabel):
    extractor, label, grade = fake_relabel
    source = source_run(tmp_path)
    (source / "manifest.json").write_text(json.dumps({"problems": {
        "full": {"scenarios_stopped": 1, "turns": 1}, "baseline_no_memory": {"turns": 1}}}))
    out = tmp_path / "relabeled"
    assert await relabel.relabel(source, out, extractor) == 1
    label.assert_not_awaited()
    grade.assert_not_called()
    assert not (out / "report.json").exists() and not (out / "table.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [{"error": "synthetic seed failure"}, {"after_call": {"status": "failed"}}])
async def test_relabel_honors_source_execution_failure_diagnostics(tmp_path, fake_relabel, failure):
    extractor, label, grade = fake_relabel
    source = source_run(tmp_path)
    (source / "diagnostics.jsonl").write_text(json.dumps({"config": "full", "scenario_id": "SYNTHETIC-1",
                                                         "call": "call_1", "turn": 1, **failure}) + "\n")
    assert await relabel.relabel(source, tmp_path / "relabeled", extractor) == 1
    label.assert_not_awaited()
    grade.assert_not_called()


@pytest.mark.asyncio
async def test_a_complete_trace_can_repair_only_old_extractor_failures(tmp_path, fake_relabel):
    extractor, label, grade = fake_relabel
    source = source_run(tmp_path)
    (source / "manifest.json").write_text(json.dumps({"problems": {
        "full": {"unlabelled_turns": 1, "turns": 1}, "baseline_no_memory": {"turns": 1}}}))
    (source / "diagnostics.jsonl").write_text(json.dumps({"config": "full", "scenario_id": "SYNTHETIC-1",
        "call": "call_1", "turn": 1, "extraction_error": "synthetic old extractor failure"}) + "\n")
    assert await relabel.relabel(source, tmp_path / "relabeled", extractor) == 0
    assert label.await_count == 2
    grade.assert_called_once()
