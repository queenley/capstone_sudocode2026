"""Write the reference conversations again for the calls whose transcript no longer serves (spends model money).

Run from the repository root, after build_dev_r4.py / build_test_r1.py and auto_verify.py:
    python evaluation/datasets/ground-truth-review/regenerate_conversations.py --dataset dev --list
    python evaluation/datasets/ground-truth-review/regenerate_conversations.py --dataset dev --only SCN-GEN-0197__call_2
    python evaluation/datasets/ground-truth-review/regenerate_conversations.py --dataset dev

A call is chosen when review/auto_verified.json excludes its conversation for a reason a new transcript can fix:
the validator fails it, its customer words changed in a label revision, the judge found fabrication (J02), it is on
mark_conversations.py's fixed list, or it has no transcript. A call excluded only because the judge has doubts keeps
its transcript. The labels (scenarios/) are not touched: the model writes from them.

Steps: move the chosen conversations/ and judgments/ files to data/.build/regen-backup/<dataset>/ (git also holds
them), generate_dialogue --resume with DATAGEN_REFRESH_CACHE=1 (the cached draft of an unchanged prompt would come
back otherwise), validate_rules, llm_judge --resume, export_manual_review (never --ingest), then record the written
calls in review/regenerated.json, clear the reviewer's approve_conversation of those calls in review/review_sheet.csv
(they judged the old transcript; approve_labels stays), and run mark_conversations.py and auto_verify.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DATAGEN = ROOT / "evaluation" / "data-generation"
PYTHON = DATAGEN / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
FIXABLE = ("validator:", "not_marked:")


def chosen(root: Path) -> list[str]:
    verified = json.loads((root / "review" / "auto_verified.json").read_text(encoding="utf-8"))
    picked = {cid for cid, why in verified["excluded"].items() if any(w.startswith(FIXABLE) for w in why)}
    for path in sorted((root / "scenarios").glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        for call in scenario["calls"]:
            if not (root / "conversations" / f"scenarios_{scenario['scenario_id']}" / f"{call}.json").exists():
                picked.add(f"{scenario['scenario_id']}__{call}")
    return sorted(picked)


def files(root: Path, cid: str) -> list[Path]:
    sid, call = cid.split("__")
    return [root / kind / f"scenarios_{sid}" / f"{call}.json" for kind in ("conversations", "judgments")]


def stage(name: str, module: str, *args: str, refresh: bool = False) -> None:
    env = {**os.environ, "DATAGEN_SEED": name, "PYTHONIOENCODING": "utf-8"}
    if refresh:
        env["DATAGEN_REFRESH_CACHE"] = "1"
    print(f"== {module} {' '.join(args)}", flush=True)
    subprocess.run([str(PYTHON), "-m", module, *args], cwd=DATAGEN, env=env, check=True)


def clear_approvals(root: Path, ids: set[str]) -> int:
    sheet = root / "review" / "review_sheet.csv"
    raw = sheet.read_bytes()
    with sheet.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    cleared = 0
    for row in rows:
        if row["conversation_id"] in ids and row["approve_conversation"]:
            row["approve_conversation"] = ""
            row["notes"] = (f"{row['notes']} " if row["notes"] else "") + \
                f"Hội thoại mẫu sinh lại {date.today():%d/%m/%Y}: quyết định cũ về hội thoại đã xoá, cần duyệt lại."
            cleared += 1
    with sheet.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\r\n" if b"\r\n" in raw else "\n")
        writer.writeheader()
        writer.writerows(rows)
    return cleared


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", choices=("dev", "test"), required=True)
    parser.add_argument("--only", default="", help="comma-separated conversation ids (a trial before the cohort)")
    parser.add_argument("--list", action="store_true", help="print the chosen calls and stop (free)")
    args = parser.parse_args()
    root = ROOT / "data" / args.dataset
    ids = [c.strip() for c in args.only.split(",") if c.strip()] or chosen(root)
    print(f"{args.dataset}: {len(ids)} calls", flush=True)
    if args.list:
        print("\n".join(ids))
        return

    backup = ROOT / "data" / ".build" / "regen-backup" / args.dataset
    for cid in ids:
        for path in files(root, cid):
            if path.exists():
                target = backup / path.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))

    stage(args.dataset, "src.pipeline.generate_dialogue", "--resume", refresh=True)
    stage(args.dataset, "src.pipeline.validate_rules")
    stage(args.dataset, "src.pipeline.llm_judge", "--resume")
    stage(args.dataset, "src.pipeline.export_manual_review")

    written = {cid for cid in ids if files(root, cid)[0].exists()}
    record = root / "review" / "regenerated.json"
    previous = json.loads(record.read_text(encoding="utf-8")) if record.exists() else {"conversation_ids": []}
    all_ids = sorted(set(previous["conversation_ids"]) | written)
    record.write_text(json.dumps({"generated_by": "evaluation/datasets/ground-truth-review/regenerate_conversations.py",
                                  "updated_on": date.today().isoformat(), "conversation_ids": all_ids},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written {len(written)}/{len(ids)}; review_sheet approvals cleared: {clear_approvals(root, written)}", flush=True)
    for script in ("mark_conversations.py", "auto_verify.py"):
        subprocess.run([str(PYTHON), str(HERE / script), *([args.dataset] if script == "auto_verify.py" else [])],
                       cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True)


if __name__ == "__main__":
    sys.exit(main())
