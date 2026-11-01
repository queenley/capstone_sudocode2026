"""Synthetic malformed inputs must not produce private artifacts or successful scores."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_agent_service.pipeline.eval import asr, asr_entities, asr_package


@pytest.fixture
def package(tmp_path):
    import numpy as np
    import soundfile as sf

    source = tmp_path / "package"
    source.mkdir()
    sf.write(source / "one.wav", np.zeros(160, dtype="float32"), 16000)
    (source / "one.txt").write_text("xin chào", encoding="utf-8")
    segment = {"segment_id": "clip", "start_sample": 0, "end_sample": 160, "reference_text": "xin chào"}
    (source / "one.jsonl").write_text(json.dumps(segment), encoding="utf-8")
    item = {"file_id": "one", "audio_file": "one.wav", "reference_file": "one.txt", "segments_file": "one.jsonl",
            "audio_sha256": hashlib.sha256((source / "one.wav").read_bytes()).hexdigest(),
            "reference_sha256": hashlib.sha256((source / "one.txt").read_bytes()).hexdigest()}
    (source / "manifest.json").write_text(json.dumps({"files": [item]}), encoding="utf-8")
    return source, item, segment


@pytest.mark.parametrize("invalid", [None, {}, {"file_id": "one"}])
def test_bad_package_file_entries_are_rejected_before_output(package, tmp_path, invalid):
    source, _, _ = package
    (source / "manifest.json").write_text(json.dumps({"files": [invalid]}))
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        asr_package.prepare(source, out, unit="montage")
    assert not out.exists()


@pytest.mark.parametrize("updates", [{"audio_file": []}, {"file_id": "../unsafe"}, {"audio_file": "../external.wav"}])
def test_package_file_paths_and_ids_are_validated(package, tmp_path, updates):
    source, item, _ = package
    (source / "manifest.json").write_text(json.dumps({"files": [{**item, **updates}]}))
    with pytest.raises(ValueError):
        asr_package.prepare(source, tmp_path / "out", unit="montage")
    assert not (tmp_path / "out").exists()


def test_duplicate_montage_ids_are_rejected_before_output(package, tmp_path):
    source, item, _ = package
    (source / "manifest.json").write_text(json.dumps({"files": [item, item]}))
    with pytest.raises(ValueError, match="file IDs must be unique"):
        asr_package.prepare(source, tmp_path / "out", unit="montage")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("invalid", ["[]", "{}", '{"reference_text": 1}',
    '{"segment_id":"clip","start_sample":-1,"start_sample":0,"end_sample":160,"reference_text":"xin chào"}'])
def test_bad_segment_rows_cannot_override_reference_or_boundaries(package, tmp_path, invalid):
    source, _, _ = package
    (source / "one.jsonl").write_text(invalid, encoding="utf-8")
    with pytest.raises(ValueError):
        asr_package.prepare(source, tmp_path / "out", unit="segments")
    assert not (tmp_path / "out").exists()


def test_package_adapter_refuses_to_write_references_into_project_files(package):
    source, _, _ = package
    out = Path(__file__).resolve().parents[2] / f"asr-private-{uuid4().hex}"
    with pytest.raises(ValueError, match="private ASR evidence"):
        asr_package.prepare(source, out, unit="segments")
    assert not out.exists()


@pytest.mark.parametrize("score", [None, {}, {"WER": 0, "CER": 0, "n_dialogues": 0},
    {"WER": None, "CER": 0, "n_dialogues": 1}, {"WER": float("nan"), "CER": 0, "n_dialogues": 1}])
def test_missing_or_invalid_main_scores_never_claim_complete(tmp_path, monkeypatch, score):
    source = tmp_path / "input"
    source.mkdir()
    (source / "ground_truth.json").write_text(json.dumps({"dialogues": [{"id": "one", "full_text": "xin chào"}]}))
    (source / "hypotheses.json").write_text(json.dumps({"one": {"text": "xin chào", "entities": {}}}))
    monkeypatch.setattr(asr, "_grader", lambda: SimpleNamespace(wer_cer=lambda _: score))
    report = asr.evaluate(source, None, tmp_path / "out")
    assert report["status"] == "INCOMPLETE"
    assert report["diagnostics"]["main_scores_available"] is False
    assert all(value["status"] == "unavailable" for value in report["main_scorer"].values())


def test_scorer_runtime_failure_preserves_incomplete_evidence(tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.mkdir()
    (source / "ground_truth.json").write_text(json.dumps({"dialogues": [{"id": "one", "full_text": "xin chào"}]}))
    (source / "hypotheses.json").write_text(json.dumps({"one": {"text": "xin chào", "entities": {}}}))

    def failed():
        raise RuntimeError("synthetic scorer failure")

    monkeypatch.setattr(asr, "_grader", failed)
    report = asr.evaluate(source, None, tmp_path / "out")
    assert report["status"] == "INCOMPLETE"
    assert json.loads((tmp_path / "out/report.json").read_text())["status"] == "INCOMPLETE"
    assert (tmp_path / "out/raw/hypotheses.json").is_file()


@pytest.mark.parametrize("changes", [
    {"status": "approved", "reviewer": "reviewer"},
    {"status": "approved", "reviewer": True, "source": "synthetic"},
    {"vocabulary": [{"type": "disease", "canonical": "abc", "aliases": "abc"}]},
    {"records": {"one": {"reference_text": "xin chào", "entities": {"number": float("nan")}}}},
    {"records": {"one": {"reference_text": None, "entities": {}}}},
])
def test_invalid_review_metadata_and_labels_are_rejected(tmp_path, changes):
    path = tmp_path / "review.json"
    document = {"schema_version": 1, "status": "pending", "records": {"one": {"reference_text": "xin chào", "entities": {}}}}
    path.write_text(json.dumps({**document, **changes}))
    with pytest.raises(ValueError):
        asr_entities.labels(path, [{"id": "one", "full_text": "xin chào"}])
