"""Offline evaluation of the AI agent's parts that need no model and no database.

Today: knowledge retrieval (Phụ lục A, M2). The agent's own knowledge base,
``components/knowledge`` as the calls use it (BM25 and a local embedding
fused by Reciprocal Rank Fusion, over the organisers' policy corpus, one
chunk per ``## [XX-nn]``), answers every question in
``data/btc/rag/qa_labeled.json``; the organisers' ``reference_eval.rag_eval``
scores it (Recall@3/@5, multi-hop, abstain rates). The agent abstains as its
search decides: the best passage is restricted, says there is no
information, or scores under θ (``config/knowledge.yaml``).

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

from ai_agent_service.components import knowledge  # noqa: E402
from ai_agent_service.mcp.servers import btc  # noqa: E402

BTC = AGENT / "data" / "btc"
QA_PATH = BTC / "rag" / "qa_labeled.json"


def reference_eval():
    spec = importlib.util.spec_from_file_location("reference_eval", BTC / "eval" / "reference_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def agent_results(questions: list[dict], k: int) -> dict[str, dict]:
    base = knowledge.build()
    results = {}
    for question in questions:
        found = base.search(question["question"], k=k, on=btc.reference_date())
        results[question["qid"]] = {
            "retrieved_chunk_ids": [hit.chunk.chunk_id for hit in found.hits],
            "scores": [hit.score for hit in found.hits],
            "abstained": found.abstain,
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
        "retrieval": {"retriever": "agent knowledge base (BM25 + embedding, RRF)", "n_questions": len(questions),
                      **scores},
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["retrieval"], ensure_ascii=False, indent=2))
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
