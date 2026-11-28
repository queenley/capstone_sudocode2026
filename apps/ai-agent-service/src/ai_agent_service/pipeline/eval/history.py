"""A finished evaluation run, read from its directory as one record for the evaluation history: the four rates, the
performance (latency, tokens, cost, with and without after_call), the quality counts and one row per scenario.

``run_eval.py --ingest`` keeps it in the database (:mod:`ai_agent_service.runtime.evaluations`) so the admin's
dashboard can draw each week's numbers.
Nothing here is computed again: the rates are the organisers' ``report.json`` (written by ``reference_eval.py``), the
latency and cost the free reading of :func:`ai_agent_service.pipeline.eval.performance.measure`.

Two layouts are read: a run directory of both configurations (``manifest.json``, ``full.jsonl``, ``report.json``),
and a directory beside one trace (``full.manifest.json``, ``full.jsonl``, ``report.json``), which is what the
improvement loop writes. Points of the history are comparable only on the same scenarios and the same extractor:
the record carries both, as ``cohort_sha256`` and ``extractor_version``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

#: Where a run came from; the dashboard draws each purpose as its own series.
PURPOSES = ("weekly_frozen", "weekly_candidate", "dev_full", "adhoc")

#: The organisers' four rates: (metric name, key in report.json, sub-figure). HR is the figure their table prints.
RATES = (
    ("RQR", "repeat_question_rate", None),
    ("CCR", "context_carryover_rate", None),
    ("TSR", "task_success_rate", None),
    ("HR", "hallucination_rate", "price_promo_only"),
)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _manifest(directory: Path) -> dict[str, Any]:
    """The run's manifest. A relabelled run (``relabel.json``) keeps its source's replies, so it is the source's
    manifest with the relabel's extractor and status: the numbers were made by that extractor, not the source's."""
    for name in ("manifest.json", "full.manifest.json", "baseline.manifest.json"):
        found = _json(directory / name)
        if found is not None:
            return found
    relabel = _json(directory / "relabel.json")
    if relabel is not None and relabel.get("source"):
        source = Path(str(relabel["source"]))
        base = _manifest(source) if source.is_dir() else {}
        models = {**(base.get("models") or {}), "extractor": relabel.get("extractor") or {}}
        return {**base, "run_id": f"{base.get('run_id') or source.name}-relabel-{directory.name}",
                "status": relabel.get("status"), "models": models, "relabel_of": str(source)}
    raise ValueError(f"{directory} has no manifest.json: not a run directory")


def cohort_sha256(manifest: Mapping[str, Any]) -> str | None:
    """One hash for the scenario files a run played, by content: renaming their folder keeps the cohort."""
    files = (manifest.get("scenarios") or {}).get("files") if isinstance(manifest.get("scenarios"), Mapping) else None
    if not files:
        return None
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


def week_of(moment: datetime) -> date:
    """The Monday of the ISO week *moment* falls in: the dashboard's x axis."""
    day = moment.astimezone(timezone.utc).date()
    return day - timedelta(days=day.weekday())


def _rate(section: Mapping[str, Any] | None, key: str, sub: str | None) -> float | None:
    metric = (section or {}).get(key)
    if not isinstance(metric, Mapping):
        return None
    part = metric.get(sub) if sub and isinstance(metric.get(sub), Mapping) else metric
    value = part.get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _performance(directory: Path) -> dict[str, float]:
    """p50 and p95 latency, and per-turn tokens and cost of the ``full`` trace, with and without the after-call
    work; empty when the run has none to read."""
    from . import performance

    try:
        figures = performance.measure(directory)
    except (OSError, ValueError):
        return {}
    found: dict[str, float] = {}
    for name in ("ttft", "total", "call_brief"):
        stats = (figures.get("latency") or {}).get(name) or {}
        for cut in ("p50", "p95"):
            if isinstance(stats.get(f"{cut}_ms"), (int, float)):
                found[f"{name}_{cut}_ms"] = float(stats[f"{cut}_ms"])
    model = ((figures.get("advisor") or {}).get("model"))
    for key, suffix in (("tokens_per_turn", ""), ("with_after_call", "_with_after_call")):
        spent = figures.get(key) or {}
        if isinstance(spent.get("total"), (int, float)):
            found[f"tokens_per_turn{suffix}"] = float(spent["total"])
        if isinstance(spent.get("cached_share"), (int, float)):
            found[f"cached_share{suffix}"] = float(spent["cached_share"])
        # Priced only when the advisor's model is in the price table: never another model's price.
        cost = (spent.get("cost_usd") or {}).get(model) if model else None
        if isinstance(cost, (int, float)):
            found[f"cost_per_turn{suffix}_usd"] = float(cost)
    return found


#: Counts of manifest.json ``problems`` kept per configuration (pipeline/eval/report.py, ``problems``).
PROBLEMS = ("failed_turns", "unlabelled_turns", "after_call_failed", "schema_errors", "scenarios_rejected",
            "scenarios_stopped", "safe_lines", "policy_skipped", "extraction_dropped_items", "turns")


def _quality(section: Mapping[str, Any] | None) -> dict[str, float]:
    """The report's figures beside the four rates: guardrail violations by kind, the hard cases' TSR, turns per
    call and calls to close."""
    found: dict[str, float] = {}
    section = section or {}
    guard = section.get("guardrail_violations")
    if isinstance(guard, Mapping):
        if isinstance(guard.get("total"), (int, float)):
            found["guardrail_violations"] = float(guard["total"])
        for kind, count in (guard.get("by_type") or {}).items():
            if isinstance(count, (int, float)):
                found[f"guardrail_{kind}"] = float(count)
    tsr = section.get("task_success_rate")
    hard = tsr.get("hard_cases") if isinstance(tsr, Mapping) else None
    if isinstance(hard, Mapping) and isinstance(hard.get("value"), (int, float)):
        found["TSR_hard_cases"] = float(hard["value"])
    if isinstance(section.get("avg_turns_per_call"), (int, float)):
        found["avg_turns_per_call"] = float(section["avg_turns_per_call"])
    close = section.get("calls_to_close")
    if isinstance(close, Mapping) and isinstance(close.get("value"), (int, float)):
        found["calls_to_close"] = float(close["value"])
    return found


def _problems(manifest: Mapping[str, Any], config: str) -> dict[str, float]:
    counts = (manifest.get("problems") or {}).get(config) or {}
    return {name: float(counts[name]) for name in PROBLEMS if isinstance(counts.get(name), (int, float))}


def _tool_failed(call: Mapping[str, Any]) -> bool:
    result = call.get("result")
    return bool(call.get("error")) or (isinstance(result, Mapping) and (bool(result.get("error")) or result.get("ok") is False))


def scenarios(directory: Path, report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per scenario of each configuration: passed or not (the organisers' TSR), why, and what it took.

    The trace gives the turns, tool calls, failed tool calls and p95 TTFT; the report's ``failures`` the verdict."""
    out: list[dict[str, Any]] = []
    for config, name, section in (("full", "full.jsonl", report.get("system")),
                                  ("baseline_no_memory", "baseline.jsonl", report.get("baseline"))):
        trace = directory / name
        if not trace.is_file():
            continue
        tsr = (section or {}).get("task_success_rate")
        failed: dict[str, list[dict[str, Any]]] = {}
        for item in (tsr.get("failures") if isinstance(tsr, Mapping) else None) or []:
            failed.setdefault(str(item.get("scenario")), []).append(
                {"call": item.get("call"), "reasons": list(item.get("reasons") or []), "hard_case": item.get("hard_case")})
        by: dict[str, dict[str, Any]] = {}
        with trace.open(encoding="utf-8") as lines:
            for line in lines:
                if not line.strip():
                    continue
                row = json.loads(line)
                sid = str(row.get("scenario_id"))
                seen = by.setdefault(sid, {"turns": 0, "calls": set(), "tool_calls": 0, "tool_errors": 0, "ttft": []})
                seen["turns"] += 1
                seen["calls"].add(row.get("call"))
                tools = [t for t in row.get("tool_calls") or [] if isinstance(t, Mapping)]
                seen["tool_calls"] += len(tools)
                seen["tool_errors"] += sum(1 for t in tools if _tool_failed(t))
                ttft = (row.get("latency") or {}).get("ttft_ms")
                if isinstance(ttft, (int, float)):
                    seen["ttft"].append(float(ttft))
        for sid, seen in sorted(by.items()):
            ttft = sorted(seen["ttft"])
            out.append({
                "config": config, "scenario_id": sid, "passed": sid not in failed,
                "failures": failed.get(sid, []), "calls": len(seen["calls"]), "turns": seen["turns"],
                "tool_calls": seen["tool_calls"], "tool_errors": seen["tool_errors"],
                "ttft_p95_ms": ttft[round(0.95 * (len(ttft) - 1))] if ttft else None,
            })
    return out


def _started(manifest: Mapping[str, Any], directory: Path) -> datetime:
    """When the run started: the manifest's ``started_at``; else the time in its run id (``YYYYMMDD-HHMMSS``, local
    time, as ``run_eval.py`` names runs); else when its report was written. Never "now": an old run ingested today
    belongs to the week it ran."""
    if manifest.get("started_at"):
        return datetime.fromisoformat(str(manifest["started_at"]))
    try:
        return datetime.strptime(str(manifest.get("run_id") or "")[:15], "%Y%m%d-%H%M%S").astimezone(timezone.utc)
    except ValueError:
        return datetime.fromtimestamp((directory / "report.json").stat().st_mtime, timezone.utc)


def summary(directory: Path, *, purpose: str = "adhoc", round_name: str | None = None) -> dict[str, Any]:
    """*directory* as ``{"run": {...}, "metrics": [{config, metric, value}]}``; refuses a run that is not scored.

    A run is scored when the organisers' ``report.json`` is beside its trace: an INCOMPLETE run has none, and a
    number from it would be a number from an unfinished run."""
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {', '.join(PURPOSES)}, not {purpose!r}")
    directory = directory.resolve()
    manifest = _manifest(directory)
    report = _json(directory / "report.json")
    if report is None:
        raise ValueError(f"{directory} has no report.json: the run was not scored (status {manifest.get('status')!r})")
    evaluation = manifest.get("evaluation") or {}
    models = manifest.get("models") or {}
    extractor = models.get("extractor") or {}
    started_at = _started(manifest, directory)
    metrics = []
    for config, section in (("full", report.get("system")), ("baseline_no_memory", report.get("baseline"))):
        for name, key, sub in RATES:
            value = _rate(section, key, sub)
            if value is not None:
                metrics.append({"config": config, "metric": name, "value": value})
    metrics += [{"config": "full", "metric": name, "value": value} for name, value in _performance(directory).items()]
    for config, section in (("full", report.get("system")), ("baseline_no_memory", report.get("baseline"))):
        if section is not None:
            found = {**_quality(section), **_problems(manifest, config)}
            metrics += [{"config": config, "metric": name, "value": value} for name, value in found.items()]
    run = {
        "run_id": str(manifest.get("run_id") or directory.name),
        "directory": str(directory),
        "purpose": purpose,
        "round": round_name,
        "profile": evaluation.get("profile") or "router",
        "kb_version": evaluation.get("knowledge_version_override"),
        "skills_version": evaluation.get("skills_version_override"),
        "knowledge_version": (manifest.get("knowledge") or {}).get("version"),
        "cohort_sha256": cohort_sha256(manifest),
        "n_scenarios": report.get("n_scenarios"),
        "extractor_version": extractor.get("extractor_version"),
        "advisor_model": (models.get("advisor") or {}).get("model"),
        "advisor_context": manifest.get("advisor_context"),
        "status": manifest.get("status"),
        "started_at": started_at.isoformat(),
        "finished_at": manifest.get("finished_at"),
        "week": week_of(started_at).isoformat(),
    }
    return {"run": run, "metrics": metrics, "scenarios": scenarios(directory, report)}
