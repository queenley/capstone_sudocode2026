"""ASR evaluation with the OFFICIAL BTC function (``reference_eval.wer_cer``).

Scores a ``hypotheses.json`` (format in ``ground_truth.json → hypotheses_format``) against
BTC's set (``data/asr``) and/or our team set (``output/asr_test``): WER, CER, entity accuracy,
clean vs noisy WER and — when hypotheses carry ``turns`` with start/end — M2 diarization
accuracy against ``audio/<id>.segments.json``.

    python -m src.pipeline.eval_asr --set team --hypotheses output/asr_test/hypotheses.json
    python -m src.pipeline.eval_asr --set btc  --hypotheses path/to/hypotheses.json

``--transcribe`` (optional) produces hypotheses with a LOCAL model (M1 requires local ASR):
it uses ``faster-whisper`` if installed (``pip install faster-whisper``); entities are left
for the agent's ITN step.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from src.utils.btc_tools import reference_eval
from src.utils.paths import DATA_DIR, OUTPUT_DIR

SETS = {"btc": DATA_DIR / "asr", "team": OUTPUT_DIR / "asr_test"}


def transcribe(asr_dir: Path, model_size: str) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is not installed: pip install faster-whisper (local ASR, M1 requirement)")
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    hypotheses = {}
    for wav in sorted((asr_dir / "audio").glob("*.wav")):
        segments, _ = model.transcribe(str(wav), language="vi")
        segments = list(segments)
        hypotheses[wav.stem] = {"text": " ".join(s.text.strip() for s in segments), "entities": {},
                                "turns": [{"speaker": "?", "start": s.start, "end": s.end, "text": s.text.strip()}
                                          for s in segments]}
    return hypotheses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=sorted(SETS), default="team")
    parser.add_argument("--hypotheses", type=Path, help="hypotheses.json produced by the agent's ASR")
    parser.add_argument("--transcribe", action="store_true", help="create hypotheses with faster-whisper")
    parser.add_argument("--model", default="small", help="faster-whisper model size")
    args = parser.parse_args()

    asr_dir = SETS[args.set]
    if not (asr_dir / "ground_truth.json").exists():
        sys.exit(f"{asr_dir / 'ground_truth.json'} not found (team set: run build_asr_testset first)")
    # Work in output/asr_eval/<set>/ so BTC input folders are never modified.
    work = OUTPUT_DIR / "asr_eval" / args.set
    (work / "audio").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(asr_dir / "ground_truth.json", work / "ground_truth.json")
    for seg in (asr_dir / "audio").glob("*.segments.json"):
        shutil.copyfile(seg, work / "audio" / seg.name)
    if args.transcribe:
        hyp = transcribe(asr_dir, args.model)
        (work / "hypotheses.json").write_text(json.dumps(hyp, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.hypotheses:
        shutil.copyfile(args.hypotheses, work / "hypotheses.json")
    if not (work / "hypotheses.json").exists():
        sys.exit("No hypotheses.json: pass --hypotheses or --transcribe")

    report = reference_eval().wer_cer(str(work))
    out = OUTPUT_DIR / "reports" / f"asr_report_{args.set}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_dialogue"}, ensure_ascii=False, indent=2))
    print(out)


if __name__ == "__main__":
    main()
