"""Synthetic contract fixtures; no benchmark conversations, labels or audio."""
from datetime import datetime
import json
import re

import pytest

from ai_agent_service.components.intake import commerce
from ai_agent_service.pipeline.eval import asr


def replay(tmp_path, document, predictions, *, name="out"):
    source = tmp_path / f"{name}-input"
    source.mkdir()
    (source / "ground_truth.json").write_text(json.dumps(document, ensure_ascii=False))
    (source / "hypotheses.json").write_text(json.dumps(predictions, ensure_ascii=False))
    out = tmp_path / name
    report = asr.evaluate(source, None, out)
    snapshots = {variant: json.loads((out / variant / "hypotheses.json").read_text())
                 for variant in ("raw", "corrected", "agent_input")}
    return report, snapshots


@pytest.fixture
def extractor(monkeypatch):
    """Small independent instrument makes mode, clock and text provenance observable."""
    calls = []

    def extract(text, *, now=None, mode, speaker=None):
        calls.append((mode, text, now, speaker))
        colors = re.findall(r"màu (đen|trắng)", text)
        color = {"đen": "den", "trắng": "trang"}
        values = {"color": color[colors[-1]]} if colors and (mode == "dialogue" or len(set(colors)) == 1) else {}
        return {"asr_entities": values, "scenario_entities": dict(values)}

    monkeypatch.setattr(commerce, "observe", lambda text, *, now=None, speaker=None: extract(text, now=now, mode="utterance", speaker=speaker))
    monkeypatch.setattr(commerce, "observe_dialogue", lambda text, *, now=None: extract(text, now=now, mode="dialogue"), raising=False)
    monkeypatch.setattr(commerce, "metadata", lambda: {"version": "synthetic-instrument-v1"})
    return calls


def test_default_dialogue_correction_uses_predicted_text_and_records_instrument(tmp_path, extractor):
    document = {"dialogues": [{"id": "one", "full_text": "màu đen", "entities": {"color": "den"},
                               "turns": [{"idx": 99, "text": "màu đen", "entities": {"color": "den"}}]}]}
    predictions = {"one": {"text": "Chọn màu đen. À đổi sang màu trắng."}}
    report, snapshots = replay(tmp_path, document, predictions)
    assert report["status"] == "COMPLETE"
    for snapshot in snapshots.values():
        assert snapshot["one"]["entities"] == {"color": "trang"}
        assert "turns" not in snapshot["one"]
    provenance = report["manifest"]["entity_extraction"]
    assert provenance["mode"] == "dialogue"
    assert provenance["parent"] == {"generated": 1, "supplied": 0}
    assert provenance["turns"] == {"samples": 0, "predicted": 0, "generated": 0, "supplied": 0}
    assert provenance["instrument"] == {"kind": "commerce", "version": "synthetic-instrument-v1"}
    assert all(mode == "dialogue" and "màu trắng" in text for mode, text, _, _ in extractor)


@pytest.mark.parametrize("metadata,source", [({"kind": "turns"}, "document.kind"),
                                             ({"provenance": {"unit": "segments"}}, "document.provenance.unit")])
def test_explicit_utterance_mode_does_not_guess_from_reference_turns(tmp_path, extractor, metadata, source):
    document = {**metadata, "dialogues": [{"id": "one", "full_text": "màu đen", "turns": []}]}
    report, snapshots = replay(tmp_path, document, {"one": {"text": "màu đen rồi màu trắng"}})
    assert snapshots["raw"]["one"]["entities"] == {}
    assert report["manifest"]["entity_extraction"]["mode_source"] == source
    assert all(mode == "utterance" for mode, _, _, _ in extractor)


def test_predicted_turns_keep_actual_indices_metadata_and_use_their_own_text(tmp_path, extractor):
    document = {"reference_date": "2031-04-05", "dialogues": [{"id": "one", "full_text": "màu đen",
                "entities": {"color": "den"}, "turns": [{"idx": 77, "entities": {"color": "den"}}]}]}
    predictions = {"one": {"text": "màu đen", "context": {"call_date": "2032-12-31"}, "turns": [
        {"idx": 8, "text": "À đổi sang màu trắng.", "speaker": "caller", "start": 2.0, "end": 3.0},
        {"idx": 3, "text": "Chọn màu đen.", "speaker": "caller", "start": 0.0, "end": 1.0}]}}
    report, snapshots = replay(tmp_path, document, predictions)
    for snapshot in snapshots.values():
        predicted = snapshot["one"]
        assert predicted["entities"] == {"color": "trang"}
        assert predicted["text"] == "màu đen"  # WER keeps the supplied parent transcript.
        assert [t["idx"] for t in predicted["turns"]] == [8, 3]
        assert [t["entities"] for t in predicted["turns"]] == [{"color": "trang"}, {"color": "den"}]
        assert [(t["speaker"], t["start"], t["end"]) for t in predicted["turns"]] == [("caller", 2.0, 3.0), ("caller", 0.0, 1.0)]
    assert all(now == datetime(2032, 12, 31) for _, _, now, _ in extractor)
    assert {text for mode, text, _, _ in extractor if mode == "dialogue"} == {"Chọn màu đen.\nÀ đổi sang màu trắng."}
    assert report["manifest"]["entity_extraction"]["turns"] == {"samples": 1, "predicted": 2, "generated": 2, "supplied": 0}


def test_supplied_parent_and_turn_entities_survive_rejected_agent_input(tmp_path, extractor):
    document = {"dialogues": [{"id": "one", "full_text": "ừm", "turns": []}]}
    predictions = {"one": {"text": "ừm", "entities": {"custom": "parent-value"},
                          "scenario_entities": {"custom": "parent-scenario"}, "turns": [
        {"idx": 4, "text": "ừm", "entities": {"custom": "turn-value"}, "scenario_entities": {"custom": "turn-scenario"}}]}}
    report, snapshots = replay(tmp_path, document, predictions)
    for snapshot in snapshots.values():
        prediction = snapshot["one"]
        assert prediction["entities"] == {"custom": "parent-value"}
        assert prediction["scenario_entities"] == {"custom": "parent-scenario"}
        assert prediction["turns"][0]["entities"] == {"custom": "turn-value"}
        assert prediction["turns"][0]["scenario_entities"] == {"custom": "turn-scenario"}
    assert snapshots["agent_input"]["one"]["text"] == ""
    assert not extractor
    assert report["manifest"]["commerce_extractor"] is None
    assert report["manifest"]["entity_extraction"]["instrument"]["kind"] == "supplied"
    assert report["manifest"]["entity_extraction"]["parent"]["supplied"] == 1
    assert report["manifest"]["entity_extraction"]["turns"]["supplied"] == 1


def test_supplied_parent_still_allows_missing_turn_entities_to_be_extracted(tmp_path, extractor):
    document = {"dialogues": [{"id": "one", "full_text": "màu đen", "turns": []}]}
    report, snapshots = replay(tmp_path, document, {"one": {"text": "màu đen", "entities": {"custom": "kept"},
        "turns": [{"idx": 0, "text": "màu trắng"}]}})
    assert snapshots["raw"]["one"]["entities"] == {"custom": "kept"}
    assert snapshots["raw"]["one"]["turns"][0]["entities"] == {"color": "trang"}
    assert report["manifest"]["generated_entity_samples"] == 0
    assert report["manifest"]["commerce_extractor"]["version"] == "synthetic-instrument-v1"


def test_clock_comes_from_document_or_actual_turn_context_not_ground_truth(tmp_path, extractor):
    document = {"reference_date": "2033-01-02", "dialogues": [{"id": "one", "full_text": "màu đen",
        "call_date": "1900-01-01", "entities": {"promo_expiry": "1900-01-01"}, "turns": []}]}
    replay(tmp_path, document, {"one": {"text": "màu đen", "turns": [
        {"idx": 0, "text": "màu trắng", "context": {"call_date": "2034-02-03"}}]}})
    assert {now for mode, _, now, _ in extractor if mode == "dialogue"} == {datetime(2033, 1, 2)}
    assert {now for mode, _, now, _ in extractor if mode == "utterance"} == {datetime(2034, 2, 3)}


def test_only_actual_predicted_speaker_metadata_reaches_utterance_extractor(tmp_path, extractor):
    document = {"kind": "turns", "dialogues": [{"id": "one", "full_text": "màu đen", "speaker": "wrong",
        "turns": [{"idx": 90, "speaker": "wrong"}]}]}
    replay(tmp_path, document, {"one": {"text": "màu đen", "context": {"speaker": "C"},
        "turns": [{"idx": 2, "text": "màu trắng", "speaker": "A"}]}})
    assert [speaker for _, _, _, speaker in extractor].count("C") == 3
    assert [speaker for _, _, _, speaker in extractor].count("A") == 3
    assert all(speaker != "wrong" for _, _, _, speaker in extractor)


def test_each_predicted_turn_variant_is_extracted_from_its_own_processed_text(tmp_path, extractor, monkeypatch):
    class Dictionary:
        hotwords = []
        _rules = []

        def correct(self, text):
            return text.replace("fixture-white", "màu trắng"), []

    monkeypatch.setattr(asr, "lexicon", Dictionary)
    document = {"dialogues": [{"id": "one", "full_text": "màu đen", "turns": []}]}
    _, snapshots = replay(tmp_path, document, {"one": {"text": "màu đen", "entities": {},
        "turns": [{"idx": 0, "text": "fixture-white"}]}})
    assert snapshots["raw"]["one"]["turns"][0]["entities"] == {}
    for variant in ("corrected", "agent_input"):
        assert snapshots[variant]["one"]["turns"][0]["text"] == "màu trắng"
        assert snapshots[variant]["one"]["turns"][0]["entities"] == {"color": "trang"}


@pytest.mark.parametrize("updates", [
    {"turns": {}}, {"turns": [{"idx": 1}]},
    {"turns": [{"idx": 1, "text": "a"}, {"idx": 1, "text": "b"}]},
    {"turns": [{"idx": True, "text": "a"}]},
    {"turns": [{"idx": 0, "text": "a", "start": 2, "end": 1}]},
    {"turns": [{"idx": 0, "text": "a", "start": 0}]},
    {"turns": [{"idx": 0, "text": "a", "end": float("inf"), "start": 0}]},
    {"turns": [{"idx": 0, "text": "a", "entities": []}]},
    {"turns": [{"idx": 0, "text": "a", "speaker": []}]},
    {"context": {"call_date": "2033-02-30"}},
    {"turns": [{"idx": 0, "text": "a", "context": {"call_date": "tomorrow"}}]},
])
def test_invalid_prediction_shapes_are_incomplete_without_extraction(tmp_path, extractor, updates):
    report, snapshots = replay(tmp_path, {"dialogues": [{"id": "one", "full_text": "màu đen"}]},
                               {"one": {"text": "màu trắng", **updates}})
    assert report["status"] == "INCOMPLETE"
    assert report["diagnostics"]["coverage"] == 0
    assert all(not snapshot for snapshot in snapshots.values())
    assert not extractor


def test_invalid_document_clock_is_rejected_before_decoder_or_artifacts(tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.mkdir()
    (source / "ground_truth.json").write_text(json.dumps({"reference_date": "2031-02-29", "dialogues": [
        {"id": "one", "full_text": "màu đen"}]}))
    monkeypatch.setattr(asr, "decode", lambda *args: pytest.fail("must validate before decoding"))
    with pytest.raises(ValueError, match="reference_date"):
        asr.evaluate(source, None, tmp_path / "out", transcribe=True)
    assert not (tmp_path / "out").exists()
