"""Offline evaluation of the AI agent's parts that need no model and no database.

Today: knowledge retrieval (Phụ lục A, M2). The agent's own retriever,
``mcp/servers/knowledge.py`` (BM25 over the organisers' policy corpus, one
chunk per ``## [XX-nn]``), answers every question in
``data/btc/rag/qa_labeled.json``; the organisers' ``reference_eval.rag_eval``
scores it (Recall@3/@5, multi-hop, abstain rates). The agent "abstains" the
way the advisor is told to: no hit, or the best hit is restricted.

End-to-end scores (CCR, RQR, TSR, HR, over-escalation) need the agent running
against a model: generate scenarios and grade traces with ``scripts/create_data``
and ``reference_eval.py --scenarios ... --trace ...``.

    python -m scripts.evaluation.evaluate [--k 5] [--output reports/generated/evaluation.json]
"""

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "apps" / "ai-agent-service"
sys.path.insert(0, str(AGENT / "src"))

from ai_agent_service.mcp.servers.knowledge import bm25, corpus  # noqa: E402

BTC = AGENT / "data" / "btc"
QA_PATH = BTC / "rag" / "qa_labeled.json"


def reference_eval():
    spec = importlib.util.spec_from_file_location("reference_eval", BTC / "eval" / "reference_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def agent_results(questions: list[dict], k: int) -> dict[str, dict]:
    chunks = corpus()
    results = {}
    for question in questions:
        ranked = bm25(question["question"], chunks)[:k]
        abstained = not ranked or ranked[0][1].restricted
        results[question["qid"]] = {
            "retrieved_chunk_ids": [chunk.chunk_id for _, chunk in ranked],
            "scores": [round(score, 3) for score, _ in ranked],
            "abstained": abstained,
        }
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "generated" / "evaluation.json")
    args = parser.parse_args()

    questions = json.loads(QA_PATH.read_text(encoding="utf-8"))["questions"]
    results = agent_results(questions, args.k)
    with tempfile.TemporaryDirectory() as folder:
        results_path = Path(folder) / "rag_results.json"
        results_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
        scores = reference_eval().rag_eval(str(QA_PATH), str(results_path))

    report = {
        "retrieval": {"retriever": "agent kb_search (BM25, policy corpus)", "n_questions": len(questions), **scores},
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["retrieval"], ensure_ascii=False, indent=2))
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
