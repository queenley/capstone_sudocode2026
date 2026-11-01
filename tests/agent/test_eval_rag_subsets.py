"""RAG diagnostics must use the tuning/report subset in every metric denominator."""
import json

from ai_agent_service.pipeline.eval import rag


def test_per_type_recall_and_abstention_are_measured_only_on_the_selected_questions(tmp_path):
    questions = [
        {"qid": "selected-single", "type": "single", "relevant_chunk_ids": ["A"]},
        {"qid": "outside-single", "type": "single", "relevant_chunk_ids": ["B"]},
        {"qid": "selected-multi", "type": "multi_hop", "relevant_chunk_ids": ["A", "B"]},
        {"qid": "outside-multi", "type": "multi_hop", "relevant_chunk_ids": ["C", "D"]},
        {"qid": "selected-abstain", "type": "unanswerable", "relevant_chunk_ids": []},
        {"qid": "outside-abstain", "type": "unanswerable", "relevant_chunk_ids": []},
    ]
    qa_path, results_path = tmp_path / "qa.json", tmp_path / "results.json"
    qa_path.write_text(json.dumps({"questions": questions}), encoding="utf-8")
    original = qa_path.read_bytes()
    subset = {
        "selected-single": {"retrieved_chunk_ids": ["A"], "abstained": False},
        "selected-multi": {"retrieved_chunk_ids": ["A", "B"], "abstained": False},
        "selected-abstain": {"retrieved_chunk_ids": [], "abstained": True},
    }
    results_path.write_text(json.dumps(subset), encoding="utf-8")

    scores = rag._on_subset(rag.reference(), qa_path, results_path, subset)

    assert scores["by_type_recall@5"]["single"] == 100
    assert scores["by_type_recall@5"]["multi_hop"] == 100
    assert scores["multi_hop_full_recall@5"] == 100
    assert scores["abstain_rate_unanswerable"] == 100
    assert scores["false_abstain_rate"] == 0
    assert scores["by_type_recall@5"]["numeric"] is None
    assert qa_path.read_bytes() == original
