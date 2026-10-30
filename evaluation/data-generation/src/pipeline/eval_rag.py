"""RAG evaluation (Phụ lục A, M2): Recall@3/@5 on ``data/rag/qa_labeled.json`` over ``data/policy/``.

Two modes:

* baseline (default) – run the BM25 baseline retriever (``src/rag/retriever.py``) and write
  ``<seed>/rag/rag_results.json`` in BTC format ``{qid: {retrieved_chunk_ids, abstained, answer}}``;
* ``--results path.json`` – score the agent's own retriever output in the same format.

Either way the numbers come from the OFFICIAL ``reference_eval.rag_eval``: recall@3/@5,
multi-hop full recall, abstain rate on unanswerable/restricted, false-abstain rate,
recall@5 by question type. Output: ``<seed>/rag/rag_report.json`` + ``rag_per_question.csv``.

The scenarios' own questions: every call with ``relevant_policy_ids`` (src/planning/policies.py) becomes one
question in ``qa_labeled.json``'s format, its text the call's customer turns, in
``<root>/rag/scenario_qa.json``; the same retriever and ``rag_eval`` score it into ``scenario_rag_report.json``.
With ``--root <seed>/plan_preview`` the turns are the plan's placeholders, so only the labels are meaningful.

    python -m src.pipeline.eval_rag
    python -m src.pipeline.eval_rag --results path/to/team_rag_results.json
    python -m src.pipeline.eval_rag --root <seed>/plan_preview
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.planning.policies import question_type
from src.rag.retriever import BM25Retriever, load_chunks, should_abstain
from src.utils.dataset import Dataset
from src.utils.btc_tools import reference_eval
from src.utils.paths import DATA_DIR, OUTPUT_DIR, POLICY_DIR

QA_PATH = DATA_DIR / "rag" / "qa_labeled.json"
RAG_DIR = OUTPUT_DIR / "rag"
TOP_K = 5


def baseline_results(questions: list[dict]) -> dict[str, dict]:
    retriever = BM25Retriever(load_chunks(POLICY_DIR))
    results = {}
    for q in questions:
        top = retriever.retrieve(q["question"], TOP_K)
        abstained, reason = should_abstain(top, q["question"])
        results[q["qid"]] = {"retrieved_chunk_ids": [c.chunk_id for c, _ in top],
                             "scores": [round(s, 3) for _, s in top], "abstained": abstained,
                             "abstain_reason": reason,
                             "answer": "" if abstained else top[0][0].text.split("\n", 1)[-1][:400]}
    return results


#: Calls whose answer is "the documents do not say": their sections are the evidence to abstain on.
UNANSWERABLE_KINDS = frozenset({"unknown_fact", "not_sold", "off_topic"})


def scenario_qa(dataset: Dataset) -> dict:
    """One question per call that needs policy, in rag/qa_labeled.json's shape."""
    questions = []
    for scenario in dataset.iter_scenarios():
        for name, call in scenario.ordered_calls():
            if not call.relevant_policy_ids:
                continue
            kind = "unanswerable" if call.kind in UNANSWERABLE_KINDS else question_type(call.relevant_policy_ids)
            questions.append({"qid": f"{scenario.scenario_id}__{name}", "type": kind,
                              "question": " ".join(call.customer_turns), "relevant_chunk_ids": call.relevant_policy_ids,
                              "scenario_id": scenario.scenario_id, "call": name, "call_kind": call.kind})
    counts: dict[str, int] = {}
    for q in questions:
        counts[q["type"]] = counts.get(q["type"], 0) + 1
    return {"description": "Câu hỏi RAG lấy từ kịch bản: mỗi cuộc gọi cần chính sách là một câu, nội dung là lời khách "
                           "của cuộc đó, relevant_chunk_ids là relevant_policy_ids do planner gán theo luật "
                           "(src/planning/policies.py). Nhãn chẩn đoán, chưa có người duyệt.",
            "corpus_dir": "policy/", "chunk_id_rule": "Mỗi mục '## [XX-nn]' là một chunk chuẩn (như qa_labeled.json).",
            "counts": counts, "questions": questions}


def score_scenarios(root: Path) -> dict | None:
    """``<root>/rag/scenario_qa.json`` and the baseline retriever's report on it; None without scenarios."""
    qa = scenario_qa(Dataset(root))
    if not qa["questions"]:
        return None
    out = root / "rag"
    out.mkdir(parents=True, exist_ok=True)
    qa_path, results_path = out / "scenario_qa.json", out / "scenario_rag_results.json"
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    results_path.write_text(json.dumps(baseline_results(qa["questions"]), ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"n_questions": len(qa["questions"]), "counts": qa["counts"],
              **reference_eval().rag_eval(str(qa_path), str(results_path))}
    (out / "scenario_rag_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, help="team retriever output in BTC rag_results.json format")
    parser.add_argument("--root", type=Path, default=OUTPUT_DIR, help="dataset root whose scenarios give scenario_qa.json")
    args = parser.parse_args()

    questions = json.loads(QA_PATH.read_text(encoding="utf-8"))["questions"]
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    if args.results:
        results_path = args.results
        results = json.loads(results_path.read_text(encoding="utf-8"))
        method = f"team results: {results_path}"
    else:
        results = baseline_results(questions)
        results_path = RAG_DIR / "rag_results.json"
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        method = "baseline BM25 (syllable uni+bi-grams, 1 chunk per ## [XX-nn], expired docs ×0.6, abstain on restricted intent / internal doc / topical absence)"

    report = reference_eval().rag_eval(str(QA_PATH), str(results_path))
    report = {"method": method, "n_questions": len(questions), **report}
    (RAG_DIR / "rag_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with (RAG_DIR / "rag_per_question.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["qid", "type", "question", "relevant", "retrieved_top5", "hit@3", "hit@5", "abstained", "reason"])
        for q in questions:
            r = results.get(q["qid"], {})
            top = [c.split("#")[0] for c in r.get("retrieved_chunk_ids", [])]
            rel = set(q["relevant_chunk_ids"])
            writer.writerow([q["qid"], q["type"], q["question"], " ".join(q["relevant_chunk_ids"]), " ".join(top[:5]),
                             bool(rel & set(top[:3])), bool(rel & set(top[:5])), r.get("abstained"), r.get("abstain_reason", "")])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    scenarios = score_scenarios(args.root)
    if scenarios:
        print("scenario questions:", json.dumps({k: v for k, v in scenarios.items() if k.startswith(("n_", "recall"))},
                                               ensure_ascii=False))


if __name__ == "__main__":
    main()
