"""Splitting a decoded call into the organisers' turns[] (pipeline/eval/diarize.py, asr.decode(turns=True))."""
from types import SimpleNamespace

import numpy as np
import pytest

from ai_agent_service.pipeline.eval import asr as evaluation, diarize


def test_spans_of_one_speaker_are_one_turn_and_blips_are_dropped():
    spans = [(0.0, 2.0, 1), (2.4, 4.0, 1), (4.5, 4.6, 0), (5.0, 7.0, 0), (7.5, 9.0, 1)]
    found = diarize.turns(spans)
    assert [(t["idx"], t["start"], t["end"], t["cluster"]) for t in found] == [
        (1, 0.0, 4.0, 1), (2, 5.0, 7.0, 0), (3, 7.5, 9.0, 1)]


def test_the_agent_is_the_cluster_that_talks_like_an_agent():
    found = [{"cluster": 0, "text": "alo em ơi chị muốn hỏi máy lọc không khí"},
             {"cluster": 1, "text": "dạ bên em có mẫu e pia y ạ"},
             {"cluster": 0, "text": "giá bao nhiêu em"}]
    assert diarize.label_speakers(found) == {0: "C", 1: "A"}
    tie = [{"cluster": 3, "text": "ừ"}, {"cluster": 5, "text": "ừ"}]
    assert diarize.label_speakers(tie) == {3: "A", 5: "C"}


@pytest.mark.parametrize("found, seconds, reason", [
    ([{"cluster": 0}], 10, "one speaker"),
    ([{"cluster": 0}, {"cluster": 1}], 10, "fewer than three turns"),
    ([{"cluster": i % 2} for i in range(3)], 60, "fewer turns per minute than a call has: voices merged"),
    ([{"cluster": i % 2} for i in range(40)], 60, "more turns per minute than a call has"),
    ([{"cluster": i % 2} for i in range(10)], 60, None),
])
def test_only_call_like_splits_are_submitted(found, seconds, reason):
    assert diarize.plausible(found, seconds) == reason


@pytest.fixture
def decoder(monkeypatch):
    from ai_agent_service.components.voice import asr
    calls = []
    monkeypatch.setattr(evaluation, "_audio", lambda path: (np.ones(16000 * 10, np.float32), {"audio_seconds": 10.0}))
    monkeypatch.setattr(asr, "remote", lambda: False)
    monkeypatch.setattr(asr, "load", lambda model: 0.0)
    monkeypatch.setattr(asr, "metadata", lambda model: {"model": model})

    def transcribe(model, samples, hotwords, denoiser="none"):
        calls.append(len(samples))
        return SimpleNamespace(text=f"lượt {len(calls)}", seconds=0.01)
    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(diarize, "available", lambda: True)
    return calls


def test_decode_gives_turns_in_order_with_speakers(decoder, monkeypatch, tmp_path):
    monkeypatch.setattr(diarize, "speaker_spans", lambda samples: [(0.0, 3.0, 1), (3.5, 6.0, 0), (6.5, 9.5, 1)])
    result = evaluation.decode(tmp_path / "call.wav", "fixture", turns=True)
    assert [(t["idx"], t["start"], t["end"], t["text"]) for t in result["turns"]] == [
        (1, 0.0, 3.0, "lượt 1"), (2, 3.5, 6.0, "lượt 2"), (3, 6.5, 9.5, "lượt 3")]
    assert {t["speaker"] for t in result["turns"]} == {"A", "C"}
    assert result["text"] == "lượt 1 lượt 2 lượt 3" and result["turning_version"] == diarize.VERSION


def test_an_implausible_split_gives_no_turns_and_decodes_the_whole_call(decoder, monkeypatch, tmp_path):
    monkeypatch.setattr(diarize, "speaker_spans", lambda samples: [(0.0, 9.5, 0)])
    result = evaluation.decode(tmp_path / "call.wav", "fixture", turns=True)
    assert "turns" not in result and result["turns_rejected"] == "one speaker"
    assert decoder[-1] == 16000 * 10  # the whole call, decoded again without the split


def test_missing_weights_never_download_and_give_no_turns(decoder, monkeypatch, tmp_path):
    monkeypatch.setattr(diarize, "available", lambda: False)
    result = evaluation.decode(tmp_path / "call.wav", "fixture", turns=True)
    assert "turns" not in result and "not fetched" in result["turns_rejected"]


def test_turns_need_local_transcription(tmp_path):
    with pytest.raises(ValueError, match="needs --asr-transcribe"):
        evaluation.evaluate(tmp_path, None, tmp_path / "out", turns=True)


def test_every_call_is_split_even_after_one_whose_split_was_rejected(monkeypatch, tmp_path):
    import json
    from ai_agent_service.components.voice import asr
    asked = []
    def fake_decode(path, model, denoiser="none", *, turns=False):
        asked.append(turns)
        return {"text": "xin chào", "seconds": 0.1, "audio_seconds": 1.0}  # no turns: as when a split is rejected
    monkeypatch.setattr(evaluation, "decode", fake_decode)
    monkeypatch.setattr(asr, "remote", lambda: False)
    source = tmp_path / "calls"
    source.mkdir()
    (source / "ground_truth.json").write_text(json.dumps({"dialogues": [
        {"id": f"C{n}", "full_text": "xin chào", "entities": {}, "audio": f"audio/C{n}.wav"} for n in range(3)]}))
    evaluation.evaluate(source, None, tmp_path / "out", transcribe=True, turns=True)
    assert asked == [True, True, True]
