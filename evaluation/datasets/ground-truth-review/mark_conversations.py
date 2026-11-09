"""Mark the reference conversations that must not serve as examples, in <dataset>/review/needs_manual_review.csv.

Run from the repository root after build_dev_r4.py / build_test_r1.py:
    python evaluation/datasets/ground-truth-review/mark_conversations.py

The reference conversations (conversations/) are written by a model from the labels. Scoring does not read them, but
they are what a person or a tool would copy as an example, few-shot or improvement-loop data. This writes the
reviewer's "N" (stage 8 of evaluation/data-generation, export_manual_review.py: a human N always removes the record)
with the reason, for:
- the J02_no_fabrication cases (the agent's words state facts the labels do not hold);
- SCN-GEN-0133/call_2 (no order.create) and the call_3 that ask more than max_agent_questions;
- every call whose customer words a label revision changed (conversion-report.json): the transcript no longer
  matches its scenario.
It never writes "Y" and never builds a golden manifest: those stay a person's decision.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIELDS = ["conversation_id", "scenario_id", "call", "persona", "reason", "transcript_preview", "transcript_path",
          "approve", "notes"]
PREVIEW_CHARS = 600  # as export_manual_review.py, so its next export keeps these decisions
DAY = "2026-11-09"
FIXED = {
    "dev": {"SCN-GEN-0133__call_2": "Agent mẫu không gọi order.create dù khách đã chốt (nhãn đúng).",
            "SCN-GEN-0092__call_3": "Agent mẫu hỏi quá max_agent_questions: 2.",
            "SCN-GEN-0126__call_3": "Agent mẫu hỏi quá max_agent_questions: 2.",
            "SCN-GEN-0192__call_3": "Agent mẫu hỏi quá max_agent_questions: 2.",
            "SCN-GEN-0210__call_3": "Agent mẫu hỏi quá max_agent_questions: 2."},
    "test": {},
}


def mark(name: str) -> dict[str, int]:
    root = ROOT / "data" / name
    target = root / "review" / "needs_manual_review.csv"
    with target.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    by_id = {r["conversation_id"]: r for r in rows}
    why: dict[str, str] = {}
    for r in rows:
        if "J02" in r["reason"]:
            why[r["conversation_id"]] = "Agent mẫu nói thông tin không có trong ground_truth_facts (J02_no_fabrication)."
    why.update(FIXED[name])
    report = json.loads((root / "conversion-report.json").read_text(encoding="utf-8"))
    revision = report.get("revision", "?")
    for change in report["changes"]:
        if change["call"].startswith("call_") and change["field"].startswith("customer_turns"):
            cid = f"{change['scenario_id']}__{change['call']}"
            why.setdefault(cid, f"Lời khách đã đổi ở bản nhãn {revision}; hội thoại mẫu còn theo lời cũ.")
    counts = {"marked": 0, "added": 0}
    for cid, reason in sorted(why.items()):
        row = by_id.get(cid)
        if row is None:
            sid, call = cid.split("__")
            path = root / "conversations" / f"scenarios_{sid}" / f"{call}.json"
            if not path.exists():
                continue
            conversation = json.loads(path.read_text(encoding="utf-8"))
            scenario = json.loads((root / "scenarios" / f"{sid}.json").read_text(encoding="utf-8"))
            preview = " | ".join(f"{t.get('speaker', '?')}: {t.get('text', '')}" for t in conversation.get("turns", []))
            row = {"conversation_id": cid, "scenario_id": sid, "call": call, "persona": scenario.get("persona", ""),
                   "reason": f"label_revision_{revision}", "transcript_preview": preview[:PREVIEW_CHARS],
                   "transcript_path": str(path), "approve": "", "notes": ""}
            rows.append(row)
            by_id[cid] = row
            counts["added"] += 1
        row["approve"] = "N"
        row["notes"] = f"Không dùng làm ví dụ mẫu hay dữ liệu vòng cải tiến ({DAY}): {reason}"
        counts["marked"] += 1
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return counts


if __name__ == "__main__":
    for dataset in ("dev", "test"):
        print(dataset, mark(dataset))
