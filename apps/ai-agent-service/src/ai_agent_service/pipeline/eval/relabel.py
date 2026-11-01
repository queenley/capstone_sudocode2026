"""Label the turns of a finished run again with today's extractor, and grade them as the evaluation does.

``evaluation/runs/`` keeps the trace of every model-backed run: what the
customer said, what the agent answered, the tools it called and the time each
turn took. Paying for the agent again to test the extractor would measure the
same replies twice, so this takes those replies as they are and runs only the
extractor (``cli._label``, the same code an evaluation uses) and the
organisers' ``reference_eval.py`` (``report.grade``) over them::

    python run_eval.py --relabel evaluation/runs/20261024-work/development-r2-v4-M2 --out <dir>

A run directory holds ``evidence/full.jsonl`` and ``evidence/baseline.jsonl``
(or ``full.jsonl`` and ``baseline.jsonl`` at its top, as this command writes)
and the scenarios it ran (``inputs/scenarios/`` or ``scenarios/``). Nothing in
it is changed: the new traces, the diagnostics with every item's quote, and
the organisers' report go to ``--out``.

What the numbers mean: the replies are those of the agent that ran then, so
this measures the extractor, not today's agent. ``facts_used`` is the slots
the extractor saw reused; the slots of the brief lines a reply cited (section
5.5) are not in an old run's trace apart from what its own extractor added,
so they are left out, and CCR is a lower bound of what a live run would get.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from . import report, scenarios, trace

#: Where a run keeps its two traces and its scenarios: a harness run, then a run of this command.
TRACES = (("evidence/full.jsonl", "evidence/baseline.jsonl"), ("full.jsonl", "baseline.jsonl"))
SCENARIOS = ("inputs/scenarios", "scenarios", "full.scenarios", "baseline.scenarios")
#: What an old line's extractor wrote; everything else in a line is what the run did.
LABELS = ("questions", "claims", "facts_used")


def locate(run: Path) -> tuple[dict[str, Path], Path]:
    """The run's trace per configuration and its scenario directory; ``ValueError`` when it has neither."""
    for full, baseline in TRACES:
        if (run / full).is_file():
            traces = {"full": run / full}
            if (run / baseline).is_file():
                traces["baseline_no_memory"] = run / baseline
            break
    else:
        raise ValueError(f"{run} holds no trace ({', '.join(t[0] for t in TRACES)})")
    for name in SCENARIOS:
        if (run / name).is_dir():
            return traces, run / name
    raise ValueError(f"{run} holds no scenarios ({', '.join(SCENARIOS)})")


def unlabelled(path: Path) -> list[dict[str, Any]]:
    """The trace's lines with the old labels emptied, in scenario, call and turn order."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        row.update({key: [] for key in LABELS})
    return sorted(rows, key=lambda r: (r["scenario_id"], r["call"], r["turn"]))


def source_errors(run: Path, traces: dict[str, Path], rows: dict[str, list[dict]]) -> list[str]:
    """Relabelling repairs extraction, never missing replies or failed execution."""
    errors = [f"{config}: empty trace" for config, items in rows.items() if not items]
    fatal = set(report.BLOCKING) - {"unlabelled_turns"}
    sources = {(run, ""), (run / "evidence", "")}
    sources.update((path.parent, f"{path.stem}.") for path in traces.values())
    for parent, prefix in sources:
        path = parent / f"{prefix}manifest.json"
        if path.is_file():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            failure = manifest.get("failure") or {}
            if (failure and failure.get("stage") != "scoring") or (
                    manifest.get("status") == "INCOMPLETE" and "problems" not in manifest
                    and failure.get("stage") != "scoring"):
                errors.append("Source has an unresolved execution failure")
            for config, counts in manifest.get("problems", {}).items():
                errors += [f"{config}: source {key}" for key in fatal if counts.get(key)]
            errors += [f"{config}: missing source trace" for config in manifest.get("configs", {}) if config not in traces]
        for name in ("diagnostics.jsonl", "scenario-errors.jsonl"):
            path = parent / f"{prefix}{name}"
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if (item.get("error") and item.get("stage") != "extraction") or (item.get("after_call") or {}).get("status") == "failed":
                        errors.append(f"Source execution failure in {name}")
                        break
    return errors


async def relabel(run: Path, out: Path, extractor: Any) -> int:
    """Label *run* again into *out* and grade it: 0 when every turn was labelled, 1 when one was not, 2 on bad input."""
    from .cli import Layout, _write_json, prepare_output

    try:
        traces, scenarios_dir = locate(run)
        if out.resolve().is_relative_to(run.resolve()) or run.resolve().is_relative_to(out.resolve()):
            raise ValueError("Relabel output must be separate from the source run")
        prepared = {config: unlabelled(path) for config, path in traces.items()}
        cohort, rejected = scenarios.load(scenarios_dir)
        failures = source_errors(run, traces, prepared)
        for config, rows in prepared.items():
            failures += report.trace_errors(scenarios_dir, rows, config)
        prepare_output(Layout(out, {}))
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
        print(error)
        return 2
    if failures:
        _write_json(out / "relabel.json", {"source": str(run), "status": "INCOMPLETE", "source_errors": failures})
        print("Not scored: " + "; ".join(failures) + ". Relabelling cannot repair execution; no extractor calls.")
        return 1
    record = {"source": str(run), "scenarios": str(scenarios_dir), "status": "INCOMPLETE"}
    _write_json(out / "relabel.json", record)
    try:
        frozen = report.freeze(cohort, rejected, out / "scenarios")
        return await _label_and_grade(prepared, traces, frozen, out, extractor, record)
    except Exception as error:
        (out / "evaluation-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        record.update(status="INCOMPLETE", failure={"type": type(error).__name__})
        _write_json(out / "relabel.json", record)
        print(f"Relabel failed ({type(error).__name__}); see {out / 'evaluation-error.log'}. No table.")
        return 1


async def _label_and_grade(prepared, traces, scenarios_dir, out, extractor, record) -> int:
    from .cli import ConfigRun, _label, _write_json

    found, diagnostics, written = {}, [], {}
    for config, path in traces.items():
        rows = prepared[config]
        done = ConfigRun(rows=rows, diagnostics=[{k: r[k] for k in ("config", "scenario_id", "call", "turn")} for r in rows])
        print(f"{config}: labelling {len(rows)} turns of {path}")
        await _label(done, extractor)
        invalid = sum(1 for row in rows if trace.schema_errors(row))
        found[config] = report.problems(rows, done.diagnostics, schema_errors=invalid, rejected=0, scenario_errors=0)
        written[config] = out / ("full.jsonl" if config == "full" else "baseline.jsonl")
        trace.write_jsonl(written[config], rows)
        diagnostics += done.diagnostics
        if done.stopped:
            break
    trace.write_jsonl(out / "diagnostics.jsonl", diagnostics)
    record.update(extractor={"model": extractor.model_name, **extractor.stats()}, problems=found)
    _write_json(out / "relabel.json", record)
    for config, counts in found.items():
        print(f"{config}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if any(report.blocking(found).values()):
        print(f"Some turns were not labelled; no table. The traces are in {out}; diagnostics.jsonl says why.")
        return 1
    code, table = report.grade(scenarios_dir, full=written["full"], baseline=written.get("baseline_no_memory"),
                               out=out / "report.json")
    if code != 0:
        record.update(failure={"stage": "scoring", "exit_code": code})
        _write_json(out / "relabel.json", record)
        (out / "scoring-error.txt").write_text(table + "\n", encoding="utf-8")
        print(f"Scoring failed (exit {code}); see {out / 'scoring-error.txt'}. No table.")
        return 1
    (out / "table.txt").write_text(table + "\n", encoding="utf-8")
    record["status"] = "COMPLETE"
    _write_json(out / "relabel.json", record)
    print(table)
    return 0 if code == 0 else 1
