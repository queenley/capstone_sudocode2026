"""Stage 8 — human review gate and golden manifest.

Export (default)::

    python -m src.pipeline.export_manual_review
    -> output/review/needs_manual_review.csv   (rule failures, judge doubts, risky personas)

Fill ``approve`` with Y/N in a spreadsheet, then ingest::

    python -m src.pipeline.export_manual_review --ingest
    -> output/review/approved.csv, rejected.csv, output/review/golden_manifest.json

Golden rule: ``validator_pass`` AND (judge pass without review flag OR human Y).
A human can never override a rule failure; a human N always removes the record.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from src.utils.dataset import Dataset
from src.utils.paths import GOLDEN_MANIFEST, REVIEW_DIR, VALIDATION_JSON

DATASET = Dataset()

FIELDS = ["conversation_id", "scenario_id", "call", "persona", "reason", "transcript_preview", "transcript_path",
          "approve", "notes"]
PREVIEW_CHARS = 600


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _judge_ok(verdict: dict[str, Any]) -> bool:
    return bool(verdict.get("overall_pass")) and not verdict.get("needs_manual_review", True)


def export(records: list[dict[str, Any]], target: Path) -> int:
    rows = []
    for item in records:
        cid = item["conversation_id"]
        verdict = _read_json(DATASET.judgment_file(cid))
        if item["validator_pass"] and not item.get("needs_manual_review") and _judge_ok(verdict):
            continue  # automatically golden
        reasons = list(item.get("errors", []))
        if verdict.get("needs_manual_review"):
            reasons.append(verdict.get("reasons") or "judge_requested_manual_review")
        if not verdict:
            reasons.append("judge_missing")
        conversation_path = DATASET.conversation_file(cid)
        conversation = _read_json(conversation_path)
        preview = " | ".join(f"{t.get('speaker', '?')}: {t.get('text', '')}" for t in conversation.get("turns", []))
        scenario = _read_json(DATASET.scenarios_dir / f"{item['scenario_id']}.json")
        rows.append({"conversation_id": cid, "scenario_id": item["scenario_id"], "call": item.get("call", ""),
                     "persona": scenario.get("persona", ""), "reason": "; ".join(reasons) or "risk_persona",
                     "transcript_preview": preview[:PREVIEW_CHARS], "transcript_path": str(conversation_path),
                     "approve": "", "notes": ""})
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def ingest(records: list[dict[str, Any]], target: Path) -> int:
    with target.open(newline="", encoding="utf-8-sig") as stream:
        reviewed = list(csv.DictReader(stream))
    rule_pass = {x["conversation_id"]: x["validator_pass"] for x in records}
    decision = {r["conversation_id"]: r.get("approve", "").strip().upper() for r in reviewed}

    for flag, name in (("Y", "approved.csv"), ("N", "rejected.csv")):
        selected = [r for r in reviewed if decision[r["conversation_id"]] == flag
                    and (flag == "N" or rule_pass.get(r["conversation_id"], False))]
        with (REVIEW_DIR / name).open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(selected)

    golden = []
    for item in records:
        cid = item["conversation_id"]
        if not item["validator_pass"] or decision.get(cid) == "N":
            continue
        if _judge_ok(_read_json(DATASET.judgment_file(cid))) and not item.get("needs_manual_review") \
                or decision.get(cid) == "Y":
            golden.append(cid)
    scenario_ids = sorted({cid.split("__")[0] for cid in golden})
    GOLDEN_MANIFEST.write_text(json.dumps(
        {"conversation_ids": golden, "scenario_ids": scenario_ids}, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(golden)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--validation", type=Path, default=VALIDATION_JSON)
    parser.add_argument("--ingest", action="store_true", help="read Y/N decisions and write the golden manifest")
    args = parser.parse_args()
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    records = json.loads(args.validation.read_text(encoding="utf-8")) if args.validation.exists() else []
    records = [r for r in records if "conversation_id" in r and "call" in r]  # ignore pre-v2 validation rows
    target = REVIEW_DIR / "needs_manual_review.csv"
    if args.ingest:
        if not target.exists():
            parser.error(f"{target} not found; run without --ingest first")
        print(f"Golden manifest: {ingest(records, target)} conversations -> {GOLDEN_MANIFEST}")
    else:
        print(f"Exported {export(records, target)} cases for review -> {target}")


if __name__ == "__main__":
    main()
