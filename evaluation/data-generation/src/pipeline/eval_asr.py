"""ASR evaluation with the OFFICIAL BTC function (``reference_eval.wer_cer``).

Scores a ``hypotheses.json`` (format in ``ground_truth.json → hypotheses_format``) against
BTC's set (``data/asr``) and/or our team set (``output/asr_test``): WER, CER, entity accuracy,
clean vs noisy WER and — when hypotheses carry ``turns`` with start/end — M2 diarization
accuracy against ``audio/<id>.segments.json``.

    python -m src.pipeline.eval_asr --set team --hypotheses output/asr_test/hypotheses.json
    python -m src.pipeline.eval_asr --set btc  --hypotheses path/to/hypotheses.json

``--transcribe`` (optional) produces hypotheses with a LOCAL model (M1 requires local ASR). ``--engine``
chooses it: ``zipformer`` (default; the sherpa-onnx Zipformer the agent runs, ``config/models.yaml`` ``voice.asr``)
or ``whisper`` (faster-whisper). Entities come from the recognised text through the agent's ITN
(``src.asr.entities``).

``--diarize`` (M2) cuts each recording into speaker segments (``src.asr.diarize``: pyannote segmentation 3.0 and a
speaker embedding model, sherpa-onnx), labels them ``A``/``C`` and recognises each segment on its own, so the
hypotheses carry ``turns`` with ``speaker``/``start``/``end``/``text`` and BTC's ``diarization_turn_accuracy`` is
scored. Name the models with ``--segmentation`` and ``--embedding``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from src.utils.btc_tools import reference_eval
from src.utils.paths import ASR_TEST_DIR, DATA_DIR, REPORTS_DIR, ROOT

SETS = {"btc": DATA_DIR / "asr", "team": ASR_TEST_DIR}


def load_engine(engine: str, models_dir: Path, whisper_model: str):
    """``samples (16 kHz float32) -> text`` for the local recogniser *engine*."""
    if engine == "zipformer":
        try:
            import sherpa_onnx
        except ImportError:
            sys.exit("sherpa-onnx is not installed: pip install sherpa-onnx (the agent's local ASR)")
        folder = models_dir / "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09"
        recogniser = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(next(folder.glob("encoder*.onnx"))), decoder=str(next(folder.glob("decoder*.onnx"))),
            joiner=str(next(folder.glob("joiner*.onnx"))), tokens=str(folder / "tokens.txt"),
            num_threads=4, sample_rate=16_000, feature_dim=80, decoding_method="greedy_search")

        def run(samples):
            stream = recogniser.create_stream()
            stream.accept_waveform(16_000, samples)
            recogniser.decode_stream(stream)
            return stream.result.text.strip().lower()  # the Zipformer vocabulary is upper case
        return run
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is not installed: pip install faster-whisper")
    model = WhisperModel(whisper_model, device="auto", compute_type="int8")

    def run(samples):
        segments, _ = model.transcribe(samples, language="vi", beam_size=1, without_timestamps=True,
                                       condition_on_previous_text=False, vad_filter=False)
        return "".join(s.text for s in segments).strip()
    return run


def transcribe(asr_dir: Path, run, diarizer=None) -> dict:
    """``hypotheses.json`` for every ``audio/*.wav``; with a *diarizer*, also ``turns`` by speaker."""
    import numpy as np
    import soundfile

    from src.asr import diarize as D
    from src.asr.entities import extract

    hypotheses = {}
    for wav in sorted((asr_dir / "audio").glob("*.wav")):
        samples, rate = soundfile.read(str(wav), dtype="float32")
        samples = samples if samples.ndim == 1 else samples.mean(axis=1)
        if rate != 16_000:
            samples = np.interp(np.linspace(0, len(samples) - 1, int(len(samples) * 16_000 / rate)),
                                np.arange(len(samples)), samples).astype("float32")
        if diarizer is None:
            text = run(samples)
            hypotheses[wav.stem] = {"text": text, "entities": extract(text)}
            continue
        turns = D.diarize(samples, diarizer, run)
        text = " ".join(t["text"] for t in turns)
        hypotheses[wav.stem] = {"text": text, "entities": extract(text), "turns": turns}
    return hypotheses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=sorted(SETS), default="team")
    parser.add_argument("--hypotheses", type=Path, help="hypotheses.json produced by the agent's ASR")
    parser.add_argument("--transcribe", action="store_true", help="create hypotheses with a local recogniser")
    parser.add_argument("--engine", choices=("zipformer", "whisper"), default="zipformer")
    parser.add_argument("--models-dir", type=Path, default=ROOT.parent.parent / "apps/ai-agent-service/models/voice",
                        help="where the agent's voice models are (zipformer)")
    parser.add_argument("--model", default="small", help="faster-whisper model size or CT2 folder (--engine whisper)")
    parser.add_argument("--diarize", action="store_true", help="split by speaker (A/C) and score diarization (M2)")
    parser.add_argument("--segmentation", type=Path, help="pyannote segmentation 3.0 model.onnx (sherpa-onnx)")
    parser.add_argument("--embedding", type=Path, help="speaker embedding .onnx (sherpa-onnx)")
    args = parser.parse_args()

    asr_dir = SETS[args.set]
    if not (asr_dir / "ground_truth.json").exists():
        sys.exit(f"{asr_dir / 'ground_truth.json'} not found (team set: run build_asr_testset first)")
    # Work in output/reports/asr_eval/<set>/ so BTC input folders are never modified.
    work = REPORTS_DIR / "asr_eval" / args.set
    (work / "audio").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(asr_dir / "ground_truth.json", work / "ground_truth.json")
    for seg in (asr_dir / "audio").glob("*.segments.json"):
        shutil.copyfile(seg, work / "audio" / seg.name)
    if args.transcribe:
        diarizer = None
        if args.diarize:
            if not (args.segmentation and args.embedding):
                sys.exit("--diarize needs --segmentation and --embedding")
            from src.asr.diarize import Diarizer
            diarizer = Diarizer(args.segmentation, args.embedding)
        hyp = transcribe(asr_dir, load_engine(args.engine, args.models_dir, args.model), diarizer)
        (work / "hypotheses.json").write_text(json.dumps(hyp, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.hypotheses:
        shutil.copyfile(args.hypotheses, work / "hypotheses.json")
    if not (work / "hypotheses.json").exists():
        sys.exit("No hypotheses.json: pass --hypotheses or --transcribe")

    report = reference_eval().wer_cer(str(work))
    out = REPORTS_DIR / f"asr_report_{args.set}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_dialogue"}, ensure_ascii=False, indent=2))
    print(out)


if __name__ == "__main__":
    main()
