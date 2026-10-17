"""Retrieval, measured the way the organisers measure it. ``docs/design.md`` section 7.4.

The 60 labelled questions of ``rag/qa_labeled.json`` go through the same
knowledge base the calls use (``components.knowledge.build``), each asked on
the pack's reference day, and the answers are written as the organisers'
grader reads them::

    {qid: {"retrieved_chunk_ids": [...], "abstained": bool, "answer": "..."}}

The numbers are ``eval/reference_eval.py``'s own ``rag_eval``, imported, not
re-implemented. The answer is extractive (the sentence of the first allowed
passage that holds most of the question, or the abstaining line): the
grader scores retrieval and abstaining from this file, and leaves the answer
to a judge.

**Split.** θ and the other settings are tuned on 40 questions and reported on
the other 20 (section 7.4): every third question in ``qid`` order is held out,
which keeps every type in both halves. ``--calibrate`` prints the θ that
abstains on no answerable question of the tuning half; a person writes it into
``config/knowledge.yaml``.

    python -m ai_agent_service.pipeline.eval.rag
    python -m ai_agent_service.pipeline.eval.rag --calibrate
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

from ...components import knowledge
from ...components.knowledge.search import KnowledgeBase, Result
from ...config.config_manager import btc_data_dir
from ...mcp.servers import btc

#: Held out for the report: every third question.
REPORT_EVERY = 3
#: Types whose right answer is to abstain (``reference_eval.rag_eval``).
ABSTAIN_TYPES = ("unanswerable", "restricted")
#: Below the lowest answerable score of the tuning half, so that none of them abstains.
CALIBRATION_MARGIN = 0.005

ABSTAIN_LINE = "Dạ hiện em chưa có thông tin về nội dung này ạ."
RESTRICTED_LINE = "Dạ đây là thông tin nội bộ, em chưa có thông tin để chia sẻ ạ."



def questions() -> list[dict[str, Any]]:
    return json.loads((btc_data_dir() / "rag" / "qa_labeled.json").read_text(encoding="utf-8"))["questions"]


def held_out(index: int) -> bool:
    """Whether the question at *index* (0-based, ``qid`` order) belongs to the report half."""
    return index % REPORT_EVERY == REPORT_EVERY - 1


def answer_of(kb: KnowledgeBase, query: str, result: Result) -> str:
    if result.abstain:
        return RESTRICTED_LINE if result.reason == "restricted" else ABSTAIN_LINE
    allowed = [hit for hit in result.hits if not hit.chunk.restricted and not hit.superseded]
    return kb.sentence_for(query, allowed[0].chunk) if allowed else ABSTAIN_LINE


def run(kb: KnowledgeBase, qa: Sequence[dict[str, Any]], *, on: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The grader's file, and one row per question for calibration and reading."""
    results: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for index, question in enumerate(sorted(qa, key=lambda q: q["qid"])):
        text = question["question"]
        result = kb.search(text, on=on)
        retrieved = [hit.chunk.chunk_id for hit in result.hits]
        results[question["qid"]] = {"retrieved_chunk_ids": retrieved, "abstained": result.abstain,
                                    "answer": answer_of(kb, text, result)}
        rows.append({"qid": question["qid"], "type": question["type"], "held_out": held_out(index),
                     "top_score": result.top_score, "reason": result.reason, "retrieved": retrieved,
                     "relevant": question["relevant_chunk_ids"]})
    return results, rows


def calibrate(rows: Sequence[dict[str, Any]]) -> float | None:
    """θ that abstains on no answerable question of the tuning half."""
    scores = [r["top_score"] for r in rows if not r["held_out"] and r["type"] not in ABSTAIN_TYPES
              and r["top_score"] is not None]
    return round(max(0.0, min(scores) - CALIBRATION_MARGIN), 3) if scores else None


def reference() -> ModuleType:
    """The organisers' grader, as a module: its ``rag_eval`` is the measure."""
    path = btc_data_dir() / "eval" / "reference_eval.py"
    spec = importlib.util.spec_from_file_location("reference_eval", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure(results: dict[str, Any], rows: Sequence[dict[str, Any]], into: Path) -> dict[str, Any]:
    """``rag_eval`` on all 60, and on each half, written next to the results."""
    into.mkdir(parents=True, exist_ok=True)
    grader = reference()
    qa_path = btc_data_dir() / "rag" / "qa_labeled.json"
    report: dict[str, Any] = {}
    for name, keep in (("all", None), ("tuning", False), ("report", True)):
        subset = {r["qid"]: results[r["qid"]] for r in rows if keep is None or r["held_out"] == keep}
        path = into / ("rag_results.json" if name == "all" else f"rag_results.{name}.json")
        path.write_text(json.dumps(subset, ensure_ascii=False, indent=1), encoding="utf-8")
        if name == "all":
            report[name] = grader.rag_eval(str(qa_path), str(path))
        else:
            report[name] = _on_subset(grader, qa_path, path, subset)
    (into / "rag_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _on_subset(grader: ModuleType, qa_path: Path, results_path: Path, subset: dict[str, Any]) -> dict[str, Any]:
    """``rag_eval`` restricted to the questions in *subset*: it counts only questions it has a result for,
    except for abstaining and false abstaining, which it counts over every question of a type; those two
    are recomputed here on the subset alone, the same way."""
    report = grader.rag_eval(str(qa_path), str(results_path))
    qa = [q for q in json.loads(qa_path.read_text(encoding="utf-8"))["questions"] if q["qid"] in subset]
    for kind in ABSTAIN_TYPES:
        of_type = [q for q in qa if q["type"] == kind]
        report[f"abstain_rate_{kind}"] = grader.pct(sum(1 for q in of_type if subset[q["qid"]]["abstained"]), len(of_type))
    answerable = [q for q in qa if q["type"] not in ABSTAIN_TYPES]
    report["false_abstain_rate"] = grader.pct(sum(1 for q in answerable if subset[q["qid"]]["abstained"]), len(answerable))
    return report


def table(report: dict[str, Any], *, mode: str) -> str:
    keys = ("recall@3", "recall@5", "multi_hop_full_recall@5", "abstain_rate_unanswerable", "abstain_rate_restricted",
            "false_abstain_rate")
    lines = [f"Retrieval ({mode}), rag/qa_labeled.json, reference_eval.rag_eval",
             f"{'':28}{'all 60':>10}{'tuning 40':>12}{'report 20':>12}"]
    for key in keys:
        lines.append(f"{key:28}" + "".join(f"{_cell(report[h].get(key)):>{w}}"
                                           for h, w in (("all", 10), ("tuning", 12), ("report", 12))))
    return "\n".join(lines)


def _cell(value: Any) -> str:
    return "-" if value is None else f"{value}"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rag", description="Measure retrieval on rag/qa_labeled.json (design 7.4).")
    p.add_argument("--out", type=Path, default=None, help="Folder for rag_results.json and rag_report.json")
    p.add_argument("--on", default=None, help="The day questions are asked, YYYY-MM-DD (default: the pack's day)")
    p.add_argument("--calibrate", action="store_true", help="Print θ from the tuning half")
    p.add_argument("--keyword-only", action="store_true", help="Without the embedding model")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    from .cli import RUNS

    kb = knowledge.build(embed=not args.keyword_only)
    on = args.on or btc.reference_date()
    results, rows = run(kb, questions(), on=on)
    into = args.out or RUNS / "rag" / date.today().isoformat()
    report = measure(results, rows, into)
    print(table(report, mode=kb.mode))
    if args.calibrate:
        theta = calibrate(rows)
        which = "abstain_cosine" if kb.mode == "hybrid" else "abstain_coverage"
        print(f"\nθ from the tuning half: {which}: {theta}  (now {getattr(kb.settings, which)})")
    print(f"\n{into / 'rag_results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
