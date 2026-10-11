"""RAG evaluation (Phụ lục A, M2): Recall@3/@5 on ``data/rag/qa_labeled.json`` over ``data/policy/``.

Two modes:

* baseline (default) – run the BM25 baseline retriever (``src/rag/retriever.py``) and write
  ``output/rag/rag_results.json`` in BTC format ``{qid: {retrieved_chunk_ids, abstained, answer}}``;
* ``--results path.json`` – score the agent's own retriever output in the same format.

Either way the numbers come from the OFFICIAL ``reference_eval.rag_eval``: recall@3/@5,
multi-hop full recall, abstain rate on unanswerable/restricted, false-abstain rate,
recall@5 by question type. Output: ``output/rag/rag_report.json`` + ``rag_per_question.csv``.

    python -m src.pipeline.eval_rag
    python -m src.pipeline.eval_rag --results path/to/team_rag_results.json
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.rag.retriever import BM25Retriever, load_chunks, should_abstain
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, help="team retriever output in BTC rag_results.json format")
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


if __name__ == "__main__":
    main()
