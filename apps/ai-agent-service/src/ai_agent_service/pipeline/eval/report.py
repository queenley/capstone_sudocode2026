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
import re
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
        # Items whose quote was not where they said, and items the vocabularies changed or set aside.
        "extraction_dropped_items": sum(d.get("extraction_dropped_items") or 0 for d in diagnostics),
        "extraction_changed_items": sum(d.get("extraction_changed_items") or 0 for d in diagnostics),
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
        "reference_eval_sha256": hashlib.sha256((btc_data_dir() / "eval/reference_eval.py").read_bytes()).hexdigest(),
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
            "extractor": scorers.prompt_sha() if extractor else None,
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


def team_checks(scenarios_dir: Path, traces: Mapping[str, Path]) -> dict[str, dict[str, Any] | None]:
    """``success_if.say_at_most`` per configuration: the calls with more agent turns matching a pattern than its max.

    The team's key (contracts/scenario/scenario-keys.yaml): "say AIR-2ND-50 once", "never with wrong conditions".
    A diagnostic beside the organisers' numbers, which stay ``reference_eval``'s (evaluation/README.md rule 1).
    A configuration whose trace holds none of the calls that carry the key is None: nothing was checked.
    """
    limits: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for path in sorted(scenarios_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for call, spec in (data.get("calls") or {}).items():
            if (spec.get("success_if") or {}).get("say_at_most"):
                limits[(data["scenario_id"], call)] = spec["success_if"]["say_at_most"]
    checks: dict[str, dict[str, Any] | None] = {}
    for config, path in traces.items():
        said: dict[tuple[str, str], list[str]] = {}
        for line in (path.read_text(encoding="utf-8").splitlines() if path.is_file() else []):
            if line.strip():
                row = json.loads(line)
                said.setdefault((row["scenario_id"], row["call"]), []).append(row.get("agent_text") or "")
        checked = [key for key in limits if key in said]
        failures = [{"scenario": sid, "call": call, "pattern": limit["pattern"], "max": limit["max"], "turns": turns}
                    for sid, call in checked for limit in limits[(sid, call)]
                    if (turns := sum(1 for text in said[(sid, call)] if re.search(limit["pattern"], text))) > limit["max"]]
        checks[config] = {"calls_checked": len(checked),
                          "calls_failed": len({(f["scenario"], f["call"]) for f in failures}),
                          "failures": failures} if checked else None
    return checks


def team_table(checks: Mapping[str, Mapping[str, Any] | None]) -> str:
    """The team's checks as lines under the organisers' table, marked as a diagnostic."""
    lines = ["Team checks (say_at_most, diagnostic, not reference_eval)"]
    for config, result in checks.items():
        lines.append(f"  {config:20} " + ("no call carries say_at_most" if result is None else
                                          f"{result['calls_failed']}/{result['calls_checked']} calls over the limit"))
    return "\n".join(lines)


def rqr_a1(scenarios_dir: Path, traces: Mapping[str, Path]) -> dict[str, Any]:
    """RQR as the brief's A.1 words it, beside ``reference_eval``'s: a question is redundant only when it is OPEN on a
    ``must_not_ask`` slot; a confirmation never is, the second one on a slot included. The organisers' script also
    counts that second confirmation (their answer to question 11), so its number is the official one and this one
    is the team's, reported with the reason (brief, appendix A: a different calculation is stated and explained).

    Same calls (those with ``must_not_ask``), same denominator (every question). ``repeat_confirms`` is what the two
    numbers differ by. The reduction against the baseline is the brief's relative one, (baseline - system) / baseline.
    """
    protected: dict[tuple[str, str], set[str]] = {}
    for path in sorted(scenarios_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for call, spec in (data.get("calls") or {}).items():
            if spec.get("must_not_ask"):
                protected[(data["scenario_id"], call)] = set(spec["must_not_ask"])
    result: dict[str, Any] = {}
    for config, path in traces.items():
        redundant = total = repeats = 0
        confirmed: dict[tuple[str, str], set[str]] = {}
        for line in (path.read_text(encoding="utf-8").splitlines() if path.is_file() else []):
            if not line.strip():
                continue
            row = json.loads(line)
            key = (row["scenario_id"], row["call"])
            if key not in protected:
                continue
            for question in row.get("questions") or []:
                total += 1
                if question.get("type") == "open" and question.get("slot") in protected[key]:
                    redundant += 1
                elif question.get("type") == "confirm":
                    seen = confirmed.setdefault(key, set())
                    repeats += question.get("slot") in seen
                    seen.add(question.get("slot"))
        result[config] = ({"value": round(100 * redundant / total, 1), "redundant": redundant, "total_questions": total,
                           "repeat_confirms": repeats} if total else None)
    base, system = result.get("baseline_no_memory"), result.get("full")
    if base and system and base["value"]:
        result["relative_reduction_pct"] = round((base["value"] - system["value"]) / base["value"] * 100, 1)
    return result


def rqr_a1_table(result: Mapping[str, Any], official: Mapping[str, Any] | None = None) -> str:
    """The A.1 RQR under the organisers' table, with their reduction beside it when the report has it."""
    lines = ["RQR as A.1 words it (confirmations never redundant; team's number, not reference_eval)"]
    for config in ("baseline_no_memory", "full"):
        if config in result:
            r = result[config]
            lines.append(f"  {config:20} " + ("no question on a call with must_not_ask" if r is None else
                                              f"{r['value']}% ({r['redundant']}/{r['total_questions']}), "
                                              f"{r['repeat_confirms']} repeated confirmations not counted"))
    if "relative_reduction_pct" in result:
        theirs = ((official or {}).get("comparison") or {}).get("rqr_relative_reduction_pct")
        lines.append(f"  reduction vs baseline {result['relative_reduction_pct']}% (A.1) · "
                     f"{theirs if theirs is not None else '-'}% (reference_eval) · target ≥ 40%")
    return "\n".join(lines)


def scenario_recall(scenarios_dir: Path, diagnostics: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any] | None]:
    """Retrieval against the scenarios' own labels: each call's ``relevant_policy_ids`` (the team's key, the sections
    an ideal agent consults) against the chunks the agent's knowledge search returned on the turns of that call
    (``diagnose``'s ``knowledge.chunks``), every turn's hits together.

    The words are ``reference_eval.rag_eval``'s, without its cut at k (a call has several searches): ``recall`` is the
    share of calls with at least one labelled section retrieved, ``full_recall`` the share with all of them;
    ``coverage`` is the mean share of a call's sections retrieved. A diagnostic beside the organisers' numbers.
    A turn whose diagnosis has no ``knowledge`` key (an older run) is no evidence; a call without one is left out,
    and a configuration with none of the labelled calls is None.
    """
    labelled: dict[tuple[str, str], set[str]] = {}
    for path in sorted(scenarios_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for call, spec in (data.get("calls") or {}).items():
            if spec.get("relevant_policy_ids"):
                labelled[(data["scenario_id"], call)] = set(spec["relevant_policy_ids"])
    retrieved: dict[str, dict[tuple[str, str], list[str]]] = {}
    for diagnosis in diagnostics:
        key = (diagnosis.get("scenario_id"), diagnosis.get("call"))
        if key not in labelled or "knowledge" not in diagnosis:
            continue
        chunks = retrieved.setdefault(diagnosis["config"], {}).setdefault(key, [])
        for chunk in (diagnosis["knowledge"] or {}).get("chunks") or []:
            if chunk and (chunk := chunk.split("#")[0]) not in chunks:
                chunks.append(chunk)
    result: dict[str, dict[str, Any] | None] = {}
    for config in ("baseline_no_memory", "full"):
        calls = retrieved.get(config)
        if not calls:
            result[config] = None
            continue
        rows = [{"scenario": sid, "call": call, "relevant": sorted(labelled[(sid, call)]), "retrieved": chunks,
                 "missed": sorted(labelled[(sid, call)] - set(chunks))} for (sid, call), chunks in sorted(calls.items())]
        n = len(rows)
        result[config] = {
            "calls": n,
            "recall": round(100 * sum(1 for r in rows if len(r["missed"]) < len(r["relevant"])) / n, 1),
            "full_recall": round(100 * sum(1 for r in rows if not r["missed"]) / n, 1),
            "coverage": round(100 * sum(1 - len(r["missed"]) / len(r["relevant"]) for r in rows) / n, 1),
            "calls_without_search": sum(1 for r in rows if not r["retrieved"]),
            "per_call": rows,
        }
    return result


def scenario_recall_table(result: Mapping[str, Mapping[str, Any] | None]) -> str:
    """The scenario recall under the organisers' table, marked as the team's."""
    lines = ["Retrieval on the scenarios' relevant_policy_ids (agent's searches per call; team's, not reference_eval)"]
    for config, r in result.items():
        lines.append(f"  {config:20} " + ("no labelled call with a knowledge diagnosis" if r is None else
                                          f"recall {r['recall']}% · full_recall {r['full_recall']}% · coverage "
                                          f"{r['coverage']}% over {r['calls']} calls, {r['calls_without_search']} "
                                          f"without a search"))
    return "\n".join(lines)
