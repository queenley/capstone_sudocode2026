"""Add newly generated scenarios to data/dev or data/test without replanning (and renumbering) the others.

New scenarios come from one persona planned alone, with ids after the dataset's (``run_all --only-persona
<id> --id-start <n> --output evaluation/runs/<folder>``). This copies each scenario's files from that output into
the dataset, records the addition in ``review/added.json`` as **pending** (no reviewer has signed it: the golden
manifest is not touched) and rebuilds the dataset's reports. ``build_dev_r4.install`` keeps added scenarios when a
revision is rebuilt.

    python evaluation/datasets/ground-truth-review/add_scenarios.py --from evaluation/runs/air-units \\
        --dataset dev --only SCN-ADV-0155 SCN-ADV-0156 SCN-ADV-0157 SCN-ADV-0158 SCN-ADV-0159 \\
        --reason "BTC 11/2026: nhiều máy lọc không khí một đơn"

Audio is not copied (the output was made with --skip-audio); ``synthesize_scenario_audio --only <id>`` adds it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATAGEN = ROOT / "evaluation" / "data-generation"
#: Per-scenario files: ``<folder>/<id>.json`` or ``<folder>/scenarios_<id>/``.
FILE_FOLDERS = ("scenarios", "metadata")
CALL_FOLDERS = ("conversations", "judgments", "tools", "call_brief", "handoff_brief", "trace_log", "asr_reference")


def files_of(root: Path, scenario_id: str) -> list[Path]:
    found = [root / f / f"{scenario_id}.json" for f in FILE_FOLDERS if (root / f / f"{scenario_id}.json").exists()]
    for folder in CALL_FOLDERS:
        directory = root / folder / f"scenarios_{scenario_id}"
        if directory.is_dir():
            found += [p for p in directory.rglob("*") if p.is_file()]
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="source", required=True, type=Path, help="the generated output folder")
    parser.add_argument("--dataset", required=True, choices=("dev", "test"))
    parser.add_argument("--only", nargs="+", required=True, help="scenario ids to add")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--replace", action="store_true", help="overwrite ids added before (never a source scenario)")
    args = parser.parse_args()

    source, dest = args.source.resolve(), ROOT / "data" / args.dataset
    added_path = dest / "review" / "added.json"
    record = json.loads(added_path.read_text(encoding="utf-8")) if added_path.exists() else {"added": []}
    earlier = {row["scenario_id"] for row in record["added"]}
    for scenario_id in args.only:
        if not (source / "scenarios" / f"{scenario_id}.json").exists():
            raise SystemExit(f"{scenario_id}: not in {source / 'scenarios'}")
        if (dest / "scenarios" / f"{scenario_id}.json").exists() and not (args.replace and scenario_id in earlier):
            raise SystemExit(f"{scenario_id} is already in {dest}; ids of added scenarios must be new")
    validation = {row["conversation_id"]: row for row in
                  json.loads((source / "reports" / "validation.json").read_text(encoding="utf-8"))
                  if "conversation_id" in row}
    for scenario_id in args.only:
        for old in files_of(dest, scenario_id):
            old.unlink()
        copied = files_of(source, scenario_id)
        for path in copied:
            target = dest / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        scenario = json.loads((source / "scenarios" / f"{scenario_id}.json").read_text(encoding="utf-8"))
        calls = sorted(scenario["calls"])
        record["added"] = [row for row in record["added"] if row["scenario_id"] != scenario_id]
        record["added"].append({
            "scenario_id": scenario_id, "persona": scenario.get("persona"), "calls": calls,
            "added_on": dt.date.today().isoformat(), "reason": args.reason,
            "source": source.relative_to(ROOT).as_posix() if source.is_relative_to(ROOT) else str(source),
            "validator_pass": {c: validation.get(f"{scenario_id}__{c}", {}).get("validator_pass") for c in calls},
            "decision": "pending", "reviewer": None})
        print(f"{scenario_id}: {len(copied)} files -> {dest}")
    record["added"].sort(key=lambda row: row["scenario_id"])
    record["note"] = ("Kịch bản thêm sau revision nhãn, chưa người duyệt ký: không có trong review/golden_manifest.json "
                      "cho tới khi người duyệt chấp nhận (approve_gold.py).")
    added_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # The dataset's reports, as after a revision: oracle traces and tool audit, then the rule validator.
    exe = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    python = next((p for p in (DATAGEN / ".venv" / exe, ROOT / ".venv" / exe,
                               ROOT / "apps" / "ai-agent-service" / ".venv" / exe) if p.exists()), Path("python"))
    env = {**os.environ, "PYTHONUTF8": "1"}
    for stage in ("build_ground_truth", "validate_rules"):
        options = ["--root", str(dest)] + (["--output", str(dest / "reports" / "validation.json")]
                                           if stage == "validate_rules" else [])
        subprocess.run([str(python), "-m", f"src.pipeline.{stage}", *options], cwd=DATAGEN, env=env, check=True)


if __name__ == "__main__":
    main()
