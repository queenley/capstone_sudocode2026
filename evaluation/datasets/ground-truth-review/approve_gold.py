"""The reviewer's sign-off: review/review_sheet.csv -> review/golden_manifest.json. Run by a person, not by Claude.

    python evaluation/datasets/ground-truth-review/approve_gold.py --dataset dev --reviewer <name>
    python evaluation/datasets/ground-truth-review/approve_gold.py --dataset dev --reviewer <name> --accept-suggestions

The reviewer writes Y or N in approve_labels (the call's labels) and approve_conversation (its reference
conversation) of review_sheet.csv; auto_verify.py fills the suggestions and why. --accept-suggestions takes Claude's
suggestion for every cell the reviewer left empty; the manifest says so ("method"), so nobody reads it as call-by-call
review. A conversation the validator fails can never be Y (stage 8 of evaluation/data-generation). official_gt_approved
in conversion-report.json is true only when every call's labels are Y; golden_manifest.json lists the conversations
whose labels and transcript are both Y.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", required=True, choices=("dev", "test"))
    parser.add_argument("--reviewer", required=True, help="who signs (a person)")
    parser.add_argument("--accept-suggestions", action="store_true",
                        help="take Claude's suggestion for every row left empty; recorded in the manifest")
    args = parser.parse_args()
    root = ROOT / "data" / args.dataset
    sheet = root / "review" / "review_sheet.csv"
    auto = json.loads((root / "review" / "auto_verified.json").read_text(encoding="utf-8"))
    with sheet.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    columns = (("approve_labels", "suggest_labels"), ("approve_conversation", "suggest_conversation"))
    empty = [r for r in rows if any(not r[a].strip() for a, _ in columns)]
    if empty and not args.accept_suggestions:
        print(f"{len(empty)} rows miss a decision (e.g. {empty[0]['conversation_id']}); fill approve_labels and "
              "approve_conversation, or pass --accept-suggestions")
        return 2
    taken = 0
    for r in rows:
        for approve, suggest in columns:
            if not r[approve].strip():
                r[approve] = r[suggest]
                taken += 1
        if taken and "(chấp nhận đề xuất" not in r["notes"]:
            r["notes"] = (r["notes"] + " " if r["notes"] else "") + f"(chấp nhận đề xuất nếu ô trống, {args.reviewer})"
    blocked = [r["conversation_id"] for r in rows
               if r["approve_conversation"].strip().upper() == "Y" and "validator:" in r["why_conversation"]]
    if blocked:
        print(f"{len(blocked)} conversations are Y but fail the validator (a person cannot override it): {blocked[:5]}")
        return 2
    labels_y = [r["conversation_id"] for r in rows if r["approve_labels"].strip().upper() == "Y"]
    golden = [r["conversation_id"] for r in rows if r["approve_conversation"].strip().upper() == "Y"
              and r["approve_labels"].strip().upper() == "Y"]
    decisions = 2 * len(rows)
    method = ("call_by_call" if not taken else "accepted_suggestions" if taken == decisions
              else f"call_by_call_and_{taken}_of_{decisions}_accepted_suggestions")
    manifest = {"conversation_ids": golden, "scenario_ids": sorted({c.split("__")[0] for c in golden}),
                "approved_by": args.reviewer, "approved_on": date.today().isoformat(), "method": method,
                "labels_revision": auto.get("labels_revision"), "calls_total": len(rows),
                "labels_approved": len(labels_y), "conversations_approved": len(golden)}
    (root / "review" / "golden_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                                          encoding="utf-8")
    with sheet.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report_path = root / "conversion-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["official_gt_approved"] = len(labels_y) == len(rows)
    report["golden_manifest"] = {k: manifest[k] for k in ("approved_by", "approved_on", "method", "calls_total",
                                                          "labels_approved", "conversations_approved")}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # Scenarios added after the revision (add_scenarios.py): their decision follows the reviewer's labels column.
    added_path = root / "review" / "added.json"
    if added_path.exists():
        added = json.loads(added_path.read_text(encoding="utf-8"))
        verdict = {r["conversation_id"]: r["approve_labels"].strip().upper() for r in rows}
        for row in added["added"]:
            calls = [verdict.get(f"{row['scenario_id']}__{call}") for call in row["calls"]]
            row["decision"] = ("approved" if all(v == "Y" for v in calls)
                               else "rejected" if any(v == "N" for v in calls) else "pending")
            row["reviewer"], row["reviewed_on"] = args.reviewer, date.today().isoformat()
        added_path.write_text(json.dumps(added, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"labels approved {len(labels_y)}/{len(rows)}, golden conversations {len(golden)} ({method})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
