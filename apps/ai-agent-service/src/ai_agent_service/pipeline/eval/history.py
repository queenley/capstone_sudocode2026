"""A finished evaluation run, read from its directory as one record for the evaluation history.

``run_eval.py --ingest`` keeps it in the database (:mod:`ai_agent_service.runtime.evaluations`) so the admin's
dashboard can draw each week's numbers (``docs/plan/001-vong-cai-tien-hang-tuan-va-dashboard.md``, parts B and D).
Nothing here is computed again: the rates are the organisers' ``report.json`` (written by ``reference_eval.py``), the
latency and cost the free reading of :func:`ai_agent_service.pipeline.eval.performance.measure`.

Two layouts are read: a run directory of both configurations (``manifest.json``, ``full.jsonl``, ``report.json``),
and a directory beside one trace (``full.manifest.json``, ``full.jsonl``, ``report.json``), which is what the
improvement loop writes. Points of the history are comparable only on the same scenarios and the same extractor
(``evaluation/README.md``): the record carries both, as ``cohort_sha256`` and ``extractor_version``.
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
    """p95 latency and per-turn tokens and cost of the ``full`` trace; empty when the run has none to read."""
    from . import performance

    try:
        figures = performance.measure(directory)
    except (OSError, ValueError):
        return {}
    found: dict[str, float] = {}
    for name in ("ttft", "total", "call_brief"):
        stats = (figures.get("latency") or {}).get(name)
        if stats and isinstance(stats.get("p95_ms"), (int, float)):
            found[f"{name}_p95_ms"] = float(stats["p95_ms"])
    spent = figures.get("tokens_per_turn") or {}
    if isinstance(spent.get("total"), (int, float)):
        found["tokens_per_turn"] = float(spent["total"])
    model = ((figures.get("advisor") or {}).get("model"))
    cost = (spent.get("cost_usd") or {}).get(model) if model else None
    if isinstance(cost, (int, float)):
        found["cost_per_turn_usd"] = float(cost)
    return found


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
    return {"run": run, "metrics": metrics}
