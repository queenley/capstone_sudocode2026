"""Where the evaluation keeps its runs, the extractor's cache and the budget ledger."""
from pathlib import Path

from ai_agent_service.config.config_manager import ROOT
from ai_agent_service.pipeline.eval import cli


def test_default_is_evaluation_runs_of_the_repository(monkeypatch):
    monkeypatch.delenv("EVAL_RUNS_DIR", raising=False)
    assert cli.runs_dir() == ROOT.parents[1] / "evaluation" / "runs"
    assert cli.EXTRACTOR_CACHE == cli.RUNS / "cache" / "extractor.json"


def test_the_environment_overrides_it(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_RUNS_DIR", str(tmp_path))
    assert cli.runs_dir() == tmp_path.resolve()


def test_without_an_evaluation_folder_beside_the_service_home_it_is_under_the_home(monkeypatch):
    # An image copies the service to /app/agent: no evaluation/ next to it.
    monkeypatch.delenv("EVAL_RUNS_DIR", raising=False)
    monkeypatch.setattr(cli, "ROOT", Path("/app/agent"))
    assert cli.runs_dir() == Path("/app/agent/runs")
