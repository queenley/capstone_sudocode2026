"""Diarization sanity check: one real speaker alone, then a two-speaker dialogue built from the uploaded clips.

There is no recorded agent audio for SCN-GEN-0001 (only the customer's turns, one voice), so the second speaker is the
same clips pitch-shifted by resampling. That is a fixture for the code path, not a measure of accuracy on real calls.
"""
import importlib.util
import os
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

LAB = Path(os.environ.get("ASR_LAB", Path(__file__).parent))  # models/, agent_tts/ and the venv live here
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts/create_data"))
sys.path.insert(0, str(Path(__file__).parent))
from src.asr import diarize as D  # noqa: E402
from src.asr.spoken import to_spoken  # noqa: E402
from asr_bench import Zipformer  # noqa: E402

spec = importlib.util.spec_from_file_location("ref", REPO / "scripts/evaluation/evaluation-contracts/sources/btc/eval/reference_eval.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)

# ASR_AUDIO, else create_data's output (gitignored), else the copy committed at the repository root.
AUDIO = Path(os.environ.get("ASR_AUDIO") or next(
    (p for p in (REPO / "scripts/create_data/output/audio/scenarios_SCN-GEN-0001", REPO / "scenarios_SCN-GEN-0001")
     if p.is_dir()), REPO / "scenarios_SCN-GEN-0001"))


def clip(call, turn):
    x, sr = sf.read(str(AUDIO / call / f"turn_{turn}.wav"), dtype="float32")
    meta = json.loads((AUDIO / call / f"turn_{turn}.json").read_text(encoding="utf-8"))
    return x, to_spoken(meta["text"])


def shift(x, factor):
    """Resample: lowers (factor<1) or raises the pitch together with the formants, so it reads as another voice."""
    n = int(len(x) / factor)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype("float32")


def agent_clip(name):
    x, sr = sf.read(str(LAB / "agent_tts" / f"{name}.mp3"), dtype="float32")
    x = x if x.ndim == 1 else x.mean(1)
    if sr != 16000:
        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * 16000 / sr)), np.arange(len(x)), x).astype("float32")
    text = {"a1": "dạ shop bê tê xê xin nghe, em có thể giúp gì cho mình ạ", "a2": "dạ em kiểm tra giúp chị ngay. chị cho em biết diện tích phòng và ngân sách được không ạ"}[name]
    return x, text


def main(factor=0.8, threshold=None):
    asr = Zipformer()
    diarizer = D.Diarizer(LAB / "models/diar/sherpa-onnx-pyannote-segmentation-3-0/model.onnx",
                          LAB / "models/diar/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")
    # 1. a single real speaker: must come out as one role
    x, _ = clip("call_1", 1)
    solo = D.label_roles(diarizer.segments(x))
    print("single speaker roles:", sorted({r for _, r in solo}), "clusters:", sorted({s.speaker for s, _ in solo}))

    # 2. a dialogue: A greets first (pitch-shifted), C answers (original), alternating
    real = factor == 0
    plan = ([("A", "a1", 0), ("C", "call_1", 1), ("A", "a2", 0), ("C", "call_1", 2), ("A", "a1", 0), ("C", "call_1", 3), ("A", "a2", 0), ("C", "call_1", 4)]
            if real else [("A", "call_2", 1), ("C", "call_1", 1), ("A", "call_2", 2), ("C", "call_1", 2), ("A", "call_2", 1), ("C", "call_1", 3)])
    gap = np.zeros(int(0.8 * 16000), dtype="float32")
    audio, truth, texts, t = [gap], [], [], 0.8
    for role, call, turn in plan:
        x, text = agent_clip(call) if (real and role == "A") else clip(call, turn)
        x = shift(x, factor) if (role == "A" and not real) else x
        audio.append(x)
        audio.append(gap)
        truth.append({"speaker": role, "start": round(t, 2), "end": round(t + len(x) / 16000, 2)})
        texts.append(text)
        t += len(x) / 16000 + 0.8
    wav = np.concatenate(audio)
    work = Path(tempfile.mkdtemp())
    (work / "audio").mkdir()
    sf.write(str(work / "audio" / "D01.wav"), wav, 16000)
    (work / "audio" / "D01.segments.json").write_text(json.dumps({"segments": truth}), encoding="utf-8")
    turns = D.diarize(wav, diarizer, asr)
    print("ground truth:", [(s["speaker"], s["start"], s["end"]) for s in truth])
    print("hypothesis  :", [(x["speaker"], x["start"], x["end"]) for x in turns])
    (work / "ground_truth.json").write_text(json.dumps({"dialogues": [
        {"id": "D01", "full_text": " ".join(texts), "noisy": False, "entities": {}}]}, ensure_ascii=False), encoding="utf-8")
    (work / "hypotheses.json").write_text(json.dumps({"D01": {"text": " ".join(x["text"] for x in turns), "entities": {}, "turns": turns}},
                                                      ensure_ascii=False), encoding="utf-8")
    score = ref.wer_cer(str(work))
    print({k: score[k] for k in ("WER", "CER", "diarization_turn_accuracy")})


if __name__ == "__main__":
    main(*(float(a) for a in sys.argv[1:]))
