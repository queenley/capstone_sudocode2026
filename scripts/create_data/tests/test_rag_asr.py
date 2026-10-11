"""RAG baseline and ASR helpers."""
import json

from src.asr.spoken import number_words, to_spoken
from src.pipeline.eval_rag import QA_PATH, baseline_results
from src.rag.retriever import load_chunks
from src.utils.btc_tools import reference_eval
from src.utils.paths import DATA_DIR, POLICY_DIR


def test_chunks_follow_btc_chunk_id_rule():
    ids = {c.chunk_id for c in load_chunks(POLICY_DIR)}
    labelled = {cid for q in json.loads(QA_PATH.read_text(encoding="utf-8"))["questions"] for cid in q["relevant_chunk_ids"]}
    assert labelled <= ids


def test_baseline_rag_regression(tmp_path):
    questions = json.loads(QA_PATH.read_text(encoding="utf-8"))["questions"]
    path = tmp_path / "rag_results.json"
    path.write_text(json.dumps(baseline_results(questions), ensure_ascii=False), encoding="utf-8")
    report = reference_eval().rag_eval(str(QA_PATH), str(path))
    assert report["recall@3"] >= 80 and report["recall@5"] >= 90
    assert report["abstain_rate_restricted"] >= 60 and report["false_abstain_rate"] <= 10


def test_spoken_form_matches_btc_style():
    assert number_words(5200000) == "năm triệu hai trăm nghìn"
    assert number_words(25) == "hai mươi lăm" and number_words(21) == "hai mươi mốt" and number_words(105) == "một trăm linh năm"
    assert to_spoken("Giá 4.890.000đ, phòng 25m², hết hạn 22/10") == \
        "giá bốn triệu tám trăm chín mươi nghìn, phòng hai mươi lăm mét vuông, hết hạn hai mươi hai tháng mười"


def test_btc_ground_truth_text_is_already_spoken():
    gt = json.loads((DATA_DIR / "asr" / "ground_truth.json").read_text(encoding="utf-8"))
    for dialogue in gt["dialogues"]:
        assert to_spoken(dialogue["full_text"]) == dialogue["full_text"].lower()
