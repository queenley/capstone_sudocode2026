"""Offline RAG check, no model and no database: the agent's knowledge base on BTC's 60 labelled questions.

The agent's own knowledge base (``components/knowledge``: BM25 and a local embedding fused by Reciprocal Rank Fusion,
over the organisers' policy corpus, one chunk per ``## [XX-nn]``) answers every question in
``data/btc/rag/qa_labeled.json``; the organisers' ``reference_eval.rag_eval`` scores it (Recall@3/@5, multi-hop,
abstain rates). The agent abstains as its search decides: the best passage is restricted, says there is no
information, or scores under θ (``config/knowledge.yaml``).

This is the quick gate of ``make eval`` and ``scripts/dev/check.ps1``. ``rag-recall`` measures the same through the
agent's ``kb_search`` MCP tool, with the database.

    python evaluation/agent-evaluation/run_eval.py rag-offline [--k 5] [--output reports/generated/evaluation.json]
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

REPOSITORY = Path(__file__).resolve().parents[4]
AGENT = REPOSITORY / "apps" / "ai-agent-service"
BTC = AGENT / "data" / "btc"
QA_PATH = BTC / "rag" / "qa_labeled.json"
DEFAULT_OUTPUT = REPOSITORY / "reports" / "generated" / "evaluation.json"


def reference_eval():
    spec = importlib.util.spec_from_file_location("reference_eval", BTC / "eval" / "reference_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def agent_results(questions: list[dict], k: int) -> dict[str, dict]:
    if str(AGENT / "src") not in sys.path:
        sys.path.insert(0, str(AGENT / "src"))
    from ai_agent_service.components import knowledge  # noqa: PLC0415
    from ai_agent_service.mcp.servers import btc  # noqa: PLC0415

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


def run(k: int = 5, output: Path = DEFAULT_OUTPUT) -> dict:
    questions = json.loads(QA_PATH.read_text(encoding="utf-8"))["questions"]
    results = agent_results(questions, k)
    with tempfile.TemporaryDirectory() as folder:
        results_path = Path(folder) / "rag_results.json"
        results_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
        scores = reference_eval().rag_eval(str(QA_PATH), str(results_path))
    report = {
        "retrieval": {"retriever": "agent knowledge base (BM25 + embedding, RRF)", "n_questions": len(questions), **scores},
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
