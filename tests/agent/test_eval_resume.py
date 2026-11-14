"""--resume keeps a stopped run's finished scenarios, reruns the rest under the same run id, and loses nothing."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.pipeline.eval import cli, report, runner, scenarios, trace

RUN_ID = "20261112-110513"


def _cohort(directory, ids):
    directory.mkdir(parents=True, exist_ok=True)
    for sid in ids:
        (directory / f"{sid}.json").write_text(json.dumps({"scenario_id": sid,
            "calls": {"call_1": {"customer_turns": ["Synthetic request"]}}}), encoding="utf-8")
    ready, rejected = scenarios.load(directory)
    assert not rejected
    return ready


def _turns(config, sid, turns=(1, 2), **diagnosis):
    rows = [{"run_id": RUN_ID, "config": config, "scenario_id": sid, "call": "call_1", "turn": turn,
             "customer_text": "Synthetic request" if turn == 1 else "", "agent_text": "reply", "questions": [],
             "claims": [], "facts_used": [], "tool_calls": [], "memory_writes": [],
             "latency": {"ttft_ms": 1, "total_ms": 2, "ttfa_ms": None}} for turn in turns]
    diagnostics = [{"config": config, "scenario_id": sid, "call": "call_1", "turn": turn, **diagnosis}
                   for turn in turns]
    return rows, diagnostics


def _stopped_run(directory):
    """A run killed during full: S1 and S2 done, S3 half written (cannot happen today, but must not be kept)."""
    ready = _cohort(directory / "scenarios", ["S1", "S2", "S3", "S4"])
    rows, diagnostics = [], []
    for sid, turns, extra in (("S1", (1, 2), {"extraction_error": "old"}), ("S2", (1, 2), {}), ("S3", (1,), {})):
        r, d = _turns("full", sid, turns, **extra)
        rows += r
        diagnostics += d
    trace.write_jsonl(directory / "full.jsonl", rows)
    trace.write_jsonl(directory / "diagnostics.jsonl", diagnostics)
    (directory / "usage.json").write_text(json.dumps({"full": [
        {"config": "full", "scenario_id": sid, "call": "call_1"} for sid in ("S1", "S2", "S3")]}))
    (directory / "manifest.json").write_text(json.dumps({"run_id": RUN_ID, "status": "INCOMPLETE",
        "configs": {"full": {"memory": True}, "baseline_no_memory": {"memory": False}},
        "evaluation": {"profile": "router", "knowledge_version_override": None, "skills_version_override": None}}))
    (directory / "run.lock").touch()
    return ready


def _layout(directory):
    return cli.Layout(directory, {"full": directory / "full.jsonl", "baseline_no_memory": directory / "baseline.jsonl"})


def test_load_resume_keeps_only_whole_scenarios_and_backs_everything_up(tmp_path):
    ready = _stopped_run(tmp_path)
    before = (tmp_path / "full.jsonl").read_text(encoding="utf-8")
    runs = cli.load_resume(_layout(tmp_path), ready, RUN_ID)
    assert [r["scenario_id"] for r in runs["full"].rows] == ["S1", "S1", "S2", "S2"]
    assert [u["scenario_id"] for u in runs["full"].usage] == ["S1", "S2"]
    assert all("extraction_error" not in d for d in runs["full"].diagnostics)
    assert runs["baseline_no_memory"].rows == []
    backup, = tmp_path.glob("resume-backup-*")
    assert (backup / "full.jsonl").read_text(encoding="utf-8") == before
    assert {p.name for p in backup.iterdir()} >= {"full.jsonl", "diagnostics.jsonl", "usage.json", "manifest.json"}


def test_load_resume_refuses_a_trace_of_another_run(tmp_path):
    ready = _stopped_run(tmp_path)
    with pytest.raises(ValueError, match="another run"):
        cli.load_resume(_layout(tmp_path), ready, "20990101-000000")


def test_resume_arguments_come_from_the_run(tmp_path):
    _stopped_run(tmp_path)
    args = cli.parser().parse_args(["--resume", str(tmp_path), "--performance"])
    assert cli._resume_arguments(args) is None
    assert args.resume_run_id == RUN_ID and args.out == tmp_path.resolve()
    assert args.scenarios == (tmp_path / "scenarios").resolve() and args.config is None


@pytest.mark.parametrize("extra", [["--out", "elsewhere"], ["--only", "S1"], ["--config", "full"],
                                   ["--profile", "gaploop", "--kb-version", "1"]])
def test_resume_refuses_options_that_would_change_the_run(tmp_path, extra):
    _stopped_run(tmp_path)
    assert cli._resume_arguments(cli.parser().parse_args(["--resume", str(tmp_path), *extra])) == 2


def test_no_baseline_runs_only_full_in_a_run_directory(tmp_path):
    args = cli.parser().parse_args(["--scenarios", str(tmp_path), "--profile", "gaploop", "--kb-version", "1",
                                    "--no-baseline", "--out", str(tmp_path / "gap")])
    assert list(cli._layout(args, RUN_ID).traces) == ["full"]
    assert list(cli._layout(cli.parser().parse_args(["--out", str(tmp_path)]), RUN_ID).traces) == ["full", "baseline_no_memory"]


def test_resume_of_a_full_only_run_stays_full_only(tmp_path):
    _stopped_run(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps({**manifest, "configs": {"full": {"memory": True}}}))
    args = cli.parser().parse_args(["--resume", str(tmp_path)])
    assert cli._resume_arguments(args) is None
    assert args.no_baseline and list(cli._layout(args, RUN_ID).traces) == ["full"]


def test_no_baseline_with_one_configuration_is_refused(capsys):
    assert cli.main(["--config", "full", "--no-baseline", "--out", "x.jsonl"]) == 2


def test_resume_refuses_a_complete_run(tmp_path):
    _stopped_run(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps({**manifest, "status": "COMPLETE"}))
    assert cli._resume_arguments(cli.parser().parse_args(["--resume", str(tmp_path)])) == 2


@pytest.mark.asyncio
async def test_resumed_run_runs_only_the_rest_and_writes_one_run_id(tmp_path, monkeypatch):
    from ai_agent_service.llm import decisions
    from ai_agent_service.mcp import client

    ready = _stopped_run(tmp_path)
    ran = []

    async def run_scenario(rig, scenario, config, *, run_id, progress):
        ran.append((config, scenario.scenario_id))
        rows, diagnostics = _turns(config, scenario.scenario_id)
        assert run_id == RUN_ID
        return runner.ScenarioRun(rows=rows, diagnostics=diagnostics,
                                  usage=[{"config": config, "scenario_id": scenario.scenario_id}])

    monkeypatch.setattr(runner, "build", AsyncMock(return_value=SimpleNamespace(
        provider="synthetic", advisor=SimpleNamespace(model_name="synthetic"))))
    monkeypatch.setattr(runner, "warm_up", AsyncMock())
    monkeypatch.setattr(runner, "run_scenario", run_scenario)
    monkeypatch.setattr(report, "manifest", lambda **kwargs: {"problems": kwargs["found"]})
    monkeypatch.setattr(report, "grade", lambda *args, **kwargs: (1, "stop before the real scorer"))
    monkeypatch.setattr(cli, "_retrieval", lambda path: "synthetic retrieval")
    monkeypatch.setattr(client, "close_all", AsyncMock())
    monkeypatch.setattr(decisions, "close", AsyncMock())

    args = cli.parser().parse_args(["--resume", str(tmp_path), "--warmup", "0", "--no-extract"])
    assert cli._resume_arguments(args) is None
    args.prepared = ready
    args.resumed = cli.load_resume(_layout(tmp_path), ready, RUN_ID)
    await cli._evaluate(args, run_id=RUN_ID, layout=_layout(tmp_path), database="synthetic_eval")

    assert ran == [("full", "S3"), ("full", "S4")] + [("baseline_no_memory", s) for s in ("S1", "S2", "S3", "S4")]
    full = cli._read_jsonl(tmp_path / "full.jsonl")
    assert [r["scenario_id"] for r in full] == ["S1", "S1", "S2", "S2", "S3", "S3", "S4", "S4"]
    assert {r["run_id"] for r in full} == {RUN_ID}
    assert report.trace_errors(tmp_path / "scenarios", full, "full") == []
    assert len(cli._read_jsonl(tmp_path / "diagnostics.jsonl")) == 16
    usage = json.loads((tmp_path / "usage.json").read_text())
    assert [u["scenario_id"] for u in usage["full"]] == ["S1", "S2", "S3", "S4"]
    assert json.loads((tmp_path / "manifest.json").read_text())["resumes"]
