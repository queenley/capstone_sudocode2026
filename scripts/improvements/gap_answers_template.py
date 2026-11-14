"""After a round's learn step: the questions the agent could not answer, as an answers file for a person to fill.

    python scripts/improvements/gap_answers_template.py --name dev-gap-1

reads evaluation/runs/<name>/improvement/knowledge-gaps.json and writes data/.build/rounds/<name>/answers.json, one
{"question", "answer": "", "cites": [], "source": "consultant"} per open question, the most asked first. Fill each
"answer" as a consultant would (no amount, promotion code or stock status: the gate refuses those) and delete the
questions that must stay unanswered (the documents say there is no information): answering those makes the agent
fail cases that expect it to say so. Delete every entry you leave unanswered before the round reads the file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="The round's --name")
    p.add_argument("--include", type=Path, action="append", default=[],
                   help="An answers file already written (data/gap-loop/answers.json): its answers come first, as is")
    args = p.parse_args()

    store = ROOT / "evaluation" / "runs" / args.name / "improvement" / "knowledge-gaps.json"
    if not store.is_file():
        sys.exit(f"No {store}: run the round's learn step first (improve round --name {args.name} ...)")
    gaps = sorted((g for g in json.loads(store.read_text(encoding="utf-8")).values() if g.get("status") == "open"),
                  key=lambda g: -len(g.get("occurrences") or []))
    out = ROOT / "data" / ".build" / "rounds" / args.name / "answers.json"
    if out.exists():
        sys.exit(f"{out} already exists: it may hold answers already written")
    out.parent.mkdir(parents=True, exist_ok=True)
    written = [row for path in args.include for row in json.loads(path.read_text(encoding="utf-8"))]
    rows = [{"question": g.get("restated") or g["question"], "asked": len(g.get("occurrences") or []),
             "answer": "", "cites": [], "source": "consultant", "from": (g.get("occurrences") or [{}])[0].get("call_id")}
            for g in gaps]
    out.write_text(json.dumps(written + rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(written)} answers already written, {len(rows)} open questions to fill or delete -> {out}")
    print("An open question of a topic an included answer covers (same customer need) can be deleted: one answer serves both.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
