"""What a run leaves beside its trace, and the organisers' grader over it. ``docs/design.md`` sections 9.2, 9.6, 9.10.

- :func:`problems`: what went wrong in a run. The :data:`BLOCKING` ones void
  the numbers, because a table over failed turns or missing labels looks like
  a result and is not one; the rest are reported beside the table.
- :func:`manifest`: Appendix D, as far as this run can state it: what ran, on
  which models, prompts, knowledge and scenarios, with which switches.
- :func:`grade`: ``eval/reference_eval.py``, the organisers' own script, run
  on a frozen copy of the scenarios that were attempted, so the official
  table is computed exactly as the organisers compute it (Appendix A).
- :func:`errors`: every scenario the grader failed, with its reasons and the
  turns to read: the material for the report's analysis of at least ten
  failures (the brief, section F).
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable, Mapping

from ...agents import advisor as advisor_prompts
from ...agents import policy as policy_rules
from ...components import clock
from ...components.evaluation import scorers
from ...components.knowledge import corpus
from ...config.config_manager import LANES_YAML, ROOT, btc_data_dir, get_knowledge_config, get_models_config, kb_dir
from ...llm.factory import limiter_stats
from .scenarios import Rejected, Scenario

#: Counts that make a run's table untrustworthy: no table is printed.
BLOCKING = ("failed_turns", "unlabelled_turns", "after_call_failed", "schema_errors")

#: Packages whose version changes what a run does.
PACKAGES = ("langchain", "langgraph", "langchain-google-genai", "fastmcp", "jsonschema")


def problems(rows: Iterable[Mapping[str, Any]], diagnostics: Iterable[Mapping[str, Any]],
             *, schema_errors: int, rejected: int, scenario_errors: int) -> dict[str, int]:
    """What went wrong in one configuration's run, by kind."""
    diagnostics = list(diagnostics)
    return {
        "failed_turns": sum(1 for d in diagnostics if d.get("error")),
        "unlabelled_turns": sum(1 for d in diagnostics if d.get("extraction_error")),
        "after_call_failed": sum(1 for d in diagnostics if (d.get("after_call") or {}).get("status") == "failed"),
        "schema_errors": schema_errors,
        "scenarios_rejected": rejected,
        "scenarios_stopped": scenario_errors,
        "claims_set_aside": sum(len(d.get("claims_set_aside") or []) for d in diagnostics),
        "policy_skipped": sum(1 for d in diagnostics if str(d.get("policy") or "").startswith("skipped")),
        "safe_lines": sum(1 for d in diagnostics if d.get("fallback")),
        "turns": sum(1 for _ in rows),
    }


def blocking(found: Mapping[str, Mapping[str, int]]) -> dict[str, int]:
    """The blocking counts that are not zero, over every configuration."""
    totals: dict[str, int] = {}
    for counts in found.values():
        for name in BLOCKING:
            if counts.get(name):
                totals[name] = totals.get(name, 0) + counts[name]
    return totals


def manifest(
    *, run_id: str, started: datetime, scenarios_dir: Path, scenarios: list[Scenario], rejected: list[Rejected],
    configs: list[str], advisor: Mapping[str, Any], extractor: Mapping[str, Any] | None, warmup: int,
    database: str, found: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    """Appendix D: what ran, on what, with which models, prompts and switches."""
    models = get_models_config()
    policy = models.evaluator_config("policy")
    return {
        "run_id": run_id,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "machine": platform.node(),
        "python": platform.python_version(),
        "git": _git(),
        "packages": {name: _version(name) for name in PACKAGES},
        "models": {
            "advisor": dict(advisor),
            "policy": {k: policy.get(k) for k in ("provider", "model", "timeout")},
            "extractor": dict(extractor) if extractor else None,
        },
        "prompts_sha256": {
            "advisor": _sha([advisor_prompts.HARD_RULES, advisor_prompts.LANE_NOTES, advisor_prompts.CONFIRM_NOTES,
                             advisor_prompts.OPENING, advisor_prompts.COPILOT_NOTE, advisor_prompts.SPOKEN_NOTE]),
            "lanes_yaml": hashlib.sha256(LANES_YAML.read_bytes()).hexdigest(),
            "policy": _sha([{name: question.model_dump() for name, question in policy_rules.QUESTIONS.items()},
                            policy_rules.THRESHOLDS]),
            "extractor": scorers.PROMPT_SHA,
        },
        "knowledge_sha256": _sha({path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in sorted((btc_data_dir() / "policy").glob("*.md"))}),
        "knowledge": knowledge_record(),
        "scenarios": {
            "dir": str(scenarios_dir),
            "files": {s.path.name: hashlib.sha256(s.path.read_bytes()).hexdigest() for s in scenarios},
            "rejected": [{"file": r.path.name, "scenario_id": r.scenario_id, "reason": r.reason} for r in rejected],
        },
        "configs": {config: {"memory": config == "full"} for config in configs},
        "call_time": clock.CALL_TIME.isoformat(),
        "warmup_turns": warmup,
        "after_call": "synchronous after every call, in both configurations",
        "database": database,
        "problems": dict(found),
        "rate_limiters": limiter_stats(),
    }


def knowledge_record() -> dict[str, Any]:
    """Section 7.5: the version of the approved entries, its file's hash, and how retrieval is set."""
    config = get_knowledge_config()
    version = corpus.version_file(kb_dir(), config.version)
    return {
        "version": config.version,
        "version_sha256": hashlib.sha256(version.read_bytes()).hexdigest() if version.exists() else None,
        "retrieval": config.retrieval.model_dump(),
        "embedding": config.embedding.model_dump() if config.embedding else None,
    }


def freeze(scenarios: list[Scenario], rejected: list[Rejected], into: Path) -> Path:
    """Copy every scenario the run attempted, so the grader scores exactly those.

    A scenario that could not be planned is copied too when it parses: the
    grader then counts it as failed, which is the truth of the run.
    """
    into.mkdir(parents=True, exist_ok=True)
    for path in [s.path for s in scenarios] + [r.path for r in rejected]:
        try:
            if isinstance(json.loads(path.read_text(encoding="utf-8")).get("scenario_id"), str):
                shutil.copy2(path, into / path.name)
        except (OSError, ValueError, AttributeError):
            continue
    return into


def grade(scenarios_dir: Path, *, full: Path, baseline: Path | None, out: Path,
          rag: Path | None = None) -> tuple[int, str]:
    """``eval/reference_eval.py`` on the traces, and on the retrieval results when given: its exit code and table."""
    command = [sys.executable, str(btc_data_dir() / "eval" / "reference_eval.py"), "--scenarios", str(scenarios_dir),
               "--trace", str(full), "--out", str(out)]
    if baseline is not None:
        command += ["--baseline", str(baseline)]
    if rag is not None:
        command += ["--rag", str(rag)]
    finished = subprocess.run(command, capture_output=True, text=True)
    return finished.returncode, (finished.stdout + finished.stderr).strip()


def errors(report: Mapping[str, Any], diagnostics: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every scenario the grader failed, per configuration, with its reasons and the turns behind it."""
    turns: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for d in diagnostics:
        turns.setdefault((d["config"], d["scenario_id"], d["call"]), []).append(
            {k: d.get(k) for k in ("turn", "lane", "tier", "guard_passed", "regenerations", "fallback", "error")})
    found = []
    for section, config in (("system", "full"), ("baseline", "baseline_no_memory")):
        for failure in ((report.get(section) or {}).get("task_success_rate") or {}).get("failures") or []:
            found.append({"config": config, **failure,
                          "turns": turns.get((config, failure["scenario"], failure["call"]), [])})
    return found


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _git() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}


def _version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
