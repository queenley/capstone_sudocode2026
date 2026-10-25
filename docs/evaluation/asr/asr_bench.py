"""Compare three local Vietnamese ASR models on the team's per-turn customer audio, scored with BTC's wer_cer."""
import importlib.util
import os
import json
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

LAB = Path(os.environ.get("ASR_LAB", Path(__file__).parent))  # models/, agent_tts/ and the venv live here
REPO = Path(__file__).resolve().parents[3]
# ASR_AUDIO, else create_data's output (gitignored), else the copy committed at the repository root.
AUDIO = Path(os.environ.get("ASR_AUDIO") or next(
    (p for p in (REPO / "evaluation/data-generation/output/audio/scenarios_SCN-GEN-0001", REPO / "scenarios_SCN-GEN-0001")
     if p.is_dir()), REPO / "scenarios_SCN-GEN-0001"))
spec = importlib.util.spec_from_file_location("ref", REPO / "evaluation/harness/evaluation-contracts/sources/btc/eval/reference_eval.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)

sys.path.insert(0, str(REPO / "evaluation/data-generation"))
from src.asr.spoken import to_spoken  # noqa: E402

clips = []
for wav in sorted(AUDIO.glob("call_*/turn_*.wav")):
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    clips.append({"id": f"{wav.parent.name}_{wav.stem}", "wav": wav, "text": to_spoken(meta["text"]), "written": meta["text"],
                  "noise": (meta.get("noise") or {}).get("type") or "clean", "voice": meta.get("voice_id")})


def load_audio(path):
    x, sr = sf.read(str(path), dtype="float32")
    assert sr == 16000
    return x if x.ndim == 1 else x.mean(1)


class Zipformer:
    name = "zipformer-30m"

    def __init__(self):
        import sherpa_onnx
        d = LAB / "models/zipformer/sherpa-onnx-zipformer-vi-30M-int8-2026-02-09"
        self.r = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.onnx"), joiner=str(d / "joiner.int8.onnx"),
            tokens=str(d / "tokens.txt"), num_threads=4, sample_rate=16000, feature_dim=80, decoding_method="greedy_search")

    def __call__(self, x):
        s = self.r.create_stream()
        s.accept_waveform(16000, x)
        self.r.decode_stream(s)
        return s.result.text.strip().lower()


class PhoWhisper:
    name = "faster-whisper PhoWhisper-small"

    def __init__(self):
        from faster_whisper import WhisperModel
        self.m = WhisperModel(str(LAB / "models/phowhisper-small-ct2"), device="cpu", compute_type="int8", cpu_threads=4)

    def __call__(self, x):
        segs, _ = self.m.transcribe(x, language="vi", beam_size=1, without_timestamps=True,
                                    condition_on_previous_text=False, vad_filter=False)
        return "".join(s.text for s in segs).strip()


class VieGem:
    name = "VieGem-ASR (greedy)"

    def __init__(self):
        import torch
        from transformers import AutoTokenizer
        sys.path.insert(0, str(LAB / "models/viegem"))
        from asr.model import CTCModel, ModelConfig
        from asr.text import Units
        self.torch = torch
        ck = torch.load(LAB / "models/viegem/viegem_asr.pt", map_location="cpu", weights_only=False)
        cfg = ModelConfig.from_dict(ck["model_config"])
        cfg.encoder_id = str(LAB / "models/embeddinggemma-2")
        self.units = Units(ck["gemma_ids"])
        self.tok = AutoTokenizer.from_pretrained(cfg.encoder_id)
        self.model = CTCModel(cfg, self.units.gemma_ids)
        self.model.load_state_dict(ck["model"], strict=False)
        self.model = self.model.float().eval()
        torch.set_num_threads(4)

    def __call__(self, x):
        from asr.model import greedy_decode
        t = self.torch
        w = t.from_numpy(x)[None]
        with t.no_grad():
            logits, lens = self.model(w, t.tensor([w.shape[1]]), streaming=False)
        return self.units.decode(self.tok, greedy_decode(logits, lens)[0])


def main(names):
    engines = {"zipformer": Zipformer, "phowhisper": PhoWhisper, "viegem": VieGem}
    report = {}
    for key in names:
        t0 = time.time()
        engine = engines[key]()
        load = time.time() - t0
        hyp, secs, audio_s = {}, 0.0, 0.0
        for c in clips:
            x = load_audio(c["wav"])
            t1 = time.time()
            hyp[c["id"]] = {"text": engine(x), "entities": {}}
            secs += time.time() - t1
            audio_s += len(x) / 16000
        d = Path(tempfile.mkdtemp())
        (d / "ground_truth.json").write_text(json.dumps({"dialogues": [
            {"id": c["id"], "full_text": c["text"], "noisy": c["noise"] != "clean", "entities": {}} for c in clips]}, ensure_ascii=False), encoding="utf-8")
        (d / "hypotheses.json").write_text(json.dumps(hyp, ensure_ascii=False), encoding="utf-8")
        score = ref.wer_cer(str(d))
        report[key] = {"model": engine.name, "load_s": round(load, 1), "decode_s": round(secs, 2),
                       "rtf": round(secs / audio_s, 3), **{k: score[k] for k in ("WER", "CER", "wer_noisy", "wer_clean")},
                       "per_clip": {c["id"]: {"noise": c["noise"], "wer": score["per_dialogue"][c["id"]]["wer"],
                                              "ref": c["text"], "hyp": hyp[c["id"]]["text"]} for c in clips}}
        print(json.dumps({k: v for k, v in report[key].items() if k != "per_clip"}, ensure_ascii=False), flush=True)
    (LAB / "bench-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:] or ["zipformer", "phowhisper", "viegem"])
