"""Read-only index of product evaluation runs; run folders remain the source of truth."""
import json
from pathlib import Path


#: What a run folder holds: its report once finished, its manifest once prepared, its raw records once started.
RUN_MARKERS = ("execution-report.json", "manifest.json", "raw")


def is_run(path: Path) -> bool:
    return any((path / marker).exists() for marker in RUN_MARKERS)


def run_directories(root: Path) -> list[Path]:
    """The runs under *root*: its subfolders, and the runs inside a subfolder that only groups them.

    A day's work is kept in one folder (``20261024-work/development-r0-M1``, ...) next to its budget ledger and
    scripts. Such a folder is not a run itself, so it is replaced by the runs it holds; a subfolder with neither
    markers nor runs inside is still listed, as a run whose report is missing.
    """
    found = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        nested = [] if is_run(child) else [p for p in sorted(child.iterdir()) if p.is_dir() and is_run(p)]
        found.extend(nested or [child])
    return found


def render_history(runs: Path) -> str:
    lines = [
        "| Run | Calls | TSR baseline → system | CCR baseline → system | RQR baseline → system | Status | Reasons | Report |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    archive = runs.parent / "archive/runs"
    directories = [(root, run) for root in (runs, archive) if root.is_dir() for run in run_directories(root)]
    for root, run in directories:
        report_path = run / "execution-report.json"
        label = ("archive/" if root == archive else "") + run.relative_to(root).as_posix()
        if not report_path.is_file():
            lines.append(f"| {label} | — | — | — | — | INCOMPLETE | EXECUTION_REPORT_MISSING | {run.resolve()} |")
            continue
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            stages = {stage["stage"]: stage for stage in report["stages"]}
            execution = stages.get("run", {})
            score = stages.get("score", {}).get("status", {})
            status = "ERROR" if report.get("pipeline_error") or execution.get("execution_complete") is False else (
                score.get("verdict", "UNDETERMINED") + "/" + score.get("completeness", "INCOMPLETE")
            )
            reasons = score.get("reason_codes") or []
            if report.get("pipeline_error"):
                reasons = [report["pipeline_error"].splitlines()[0]]
            elif execution.get("execution_complete") is False:
                reasons = sorted({error.get("code", "EXECUTION_ERROR") + " (" + str(error.get("phase", "run")) + ")"
                                  for error in execution.get("errors", [])}) or ["EXECUTION_INCOMPLETE"]
            official = run / "scored/official-report.json"
            metrics = json.loads(official.read_text(encoding="utf-8")) if official.is_file() and execution.get("completed_calls") else {}

            def pair(key):
                values = [metrics.get(side, {}).get(key, {}).get("value") for side in ("baseline", "system")]
                return " → ".join("—" if value is None else f"{value:g}%" for value in values)

            cells = [label, str(stages.get("run", {}).get("completed_calls", 0)),
                     pair("task_success_rate"), pair("context_carryover_rate"), pair("repeat_question_rate"),
                     status, ", ".join(reasons) or "—", str(report_path.resolve())]
            lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            lines.append(f"| {label} | — | — | — | — | INVALID | {type(exc).__name__} | {report_path.resolve()} |")
    return "\n".join(lines) if len(lines) > 2 else "No evaluation runs found in " + str(runs.resolve())
