"""Finished runs graded again on today's labels, as run directories the /admin dashboard can ingest. No model call.

    apps/ai-agent-service/.venv/Scripts/python.exe scripts/evaluation/regrade_on_labels.py \\
        --run router=eval_3 --run gaploop=full-dev/gaploop --out evaluation/runs/regrade-dev409-<date>
    python run_eval.py --ingest evaluation/runs/regrade-dev409-<date>/router --purpose dev_full

The replies are the run's own (its trace is copied unchanged); only the grade is new: the organisers'
``eval/reference_eval.py`` on --labels (default data/dev/scenarios), as on 16/11 for eval_3 (RUN-LEDGER.md). This is
not ``run_eval.py --relabel``, which runs the extractor again on the run's own frozen scenarios and so keeps its old
labels. The copied manifest names its source (``regraded``) and lists the label files graded on, so every run graded
on the same labels lands in one cohort of the dashboard. Same caveat as the 16/11 rescore: a scenario whose customer
words changed keeps the reply to the old words.

Output stays in evaluation/runs (not in git: traces hold conversations).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "evaluation" / "runs"
REFERENCE = ROOT / "apps" / "ai-agent-service" / "data" / "btc" / "eval" / "reference_eval.py"
#: What a dashboard row reads beside the trace: performance (usage, diagnostics) and the scenario rows.
KEEP = ("full.jsonl", "baseline.jsonl", "usage.json", "full.usage.json", "diagnostics.jsonl",
        "full.diagnostics.jsonl", "performance.json", "sessions.json")


def regrade(name: str, source: Path, labels: Path, out: Path, tag: str) -> dict:
    target = out / name
    if target.exists():
        raise SystemExit(f"{target} exists: choose a new --out (evidence is never overwritten)")
    target.mkdir(parents=True)
    manifest_name = "manifest.json" if (source / "manifest.json").is_file() else "full.manifest.json"
    manifest = json.loads((source / manifest_name).read_text(encoding="utf-8"))
    manifest["regraded"] = {"source": str(source), "source_run_id": manifest.get("run_id"), "labels": str(labels),
                            "note": "replies unchanged; graded again by reference_eval.py, no model call"}
    manifest["run_id"] = f"{manifest.get('run_id') or source.name}-{tag}"
    manifest["scenarios"] = {"dir": str(labels), "rejected": [],
                             "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in sorted(labels.glob("*.json"))}}
    (target / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    for name_ in KEEP:
        if (source / name_).is_file():
            shutil.copy2(source / name_, target / name_)
    command = [sys.executable, str(REFERENCE), "--scenarios", str(labels), "--trace", str(target / "full.jsonl"),
               "--out", str(target / "report.json")]
    if (target / "baseline.jsonl").is_file():
        command += ["--baseline", str(target / "baseline.jsonl")]
    done = subprocess.run(command, capture_output=True, encoding="utf-8",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    if done.returncode:
        raise SystemExit(f"{name}: reference_eval.py failed\n{done.stdout}{done.stderr}")
    return json.loads((target / "report.json").read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--run", action="append", required=True, metavar="NAME=RUN_DIR",
                   help="a finished run (relative to evaluation/runs or absolute)")
    p.add_argument("--labels", type=Path, default=ROOT / "data" / "dev" / "scenarios")
    p.add_argument("--tag", default="regraded", help="appended to each run_id, e.g. labels-20261124")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    for item in args.run:
        name, _, path = item.partition("=")
        source = Path(path) if Path(path).is_absolute() else RUNS / path
        report = regrade(name, source, args.labels.resolve(), args.out.resolve(), args.tag)
        tsr = (report.get("system") or {}).get("task_success_rate") or {}
        print(f"{name}: {report.get('n_scenarios')} scenarios, TSR {tsr.get('value')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
