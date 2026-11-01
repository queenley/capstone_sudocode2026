"""ASR-only mode of run_eval.py. Main's scorer is imported unchanged; extras stay separate."""
from __future__ import annotations

import hashlib
from datetime import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import urlparse
import re
import unicodedata

from ...config.config_manager import btc_data_dir
from ...components.voice.recognition import process
from ...components.voice.policy import POLICY_VERSION
from ...components.intake.lexicon import lexicon

METRICS_VERSION = "asr-diagnostics-v3-dialogue-entities"


def normalize(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFC", text.lower()))
    return re.sub(r"\s+", " ", text).strip()


def edits(reference: list[str], hypothesis: list[str]) -> dict:
    """Word alignment counts, diagnostic only. Tie order: substitute, delete, insert."""
    row = [(j, 0, 0, j) for j in range(len(hypothesis) + 1)]
    for i, left in enumerate(reference, 1):
        current = [(i, 0, i, 0)]
        for j, right in enumerate(hypothesis, 1):
            cost, sub, delete, insert = row[j - 1]
            if left == right:
                current.append((cost, sub, delete, insert))
            else:
                a = (cost + 1, sub + 1, delete, insert)
                cost, sub, delete, insert = row[j]
                b = (cost + 1, sub, delete + 1, insert)
                cost, sub, delete, insert = current[-1]
                c = (cost + 1, sub, delete, insert + 1)
                current.append(min((a, b, c), key=lambda x: x[0]))
        row = current
    cost, sub, delete, insert = row[-1]
    return {"errors": cost, "substitutions": sub, "deletions": delete, "insertions": insert,
            "reference_words": len(reference), "wer": cost / len(reference) if reference else None}


def distribution(values: list[float]) -> dict:
    values = sorted(value for value in values if math.isfinite(value) and value >= 0)
    def q(p): return values[max(0, math.ceil(len(values) * p) - 1)] if values else None
    return {"n": len(values), "p50": q(.5), "p95": q(.95), "p99": q(.99),
            "warning": "fewer than 100 observations" if len(values) < 100 else None}


def _loads(text: str):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def _read(path: Path):
    return _loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clock(value, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must be a valid YYYY-MM-DD date")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be a valid YYYY-MM-DD date") from error


def _context(prediction: dict, fallback: datetime | None) -> tuple[dict, datetime | None]:
    context = prediction.get("context", {})
    if not isinstance(context, dict):
        raise ValueError("context must be an object")
    if "speaker" in context and (not isinstance(context["speaker"], str) or not context["speaker"]):
        raise ValueError("context speaker must be a nonempty string")
    now = _clock(context.get("call_date"), "context.call_date")
    return context, now if now is not None else fallback


def _predicted_turns(prediction: dict) -> list[dict]:
    turns = prediction.get("turns", [])
    if not isinstance(turns, list):
        raise ValueError("hypothesis turns must be a list")
    indices = set()
    for turn in turns:
        if not isinstance(turn, dict) or not isinstance(turn.get("text"), str):
            raise ValueError("Each hypothesis turn needs its own text")
        idx = turn.get("idx")
        if type(idx) is not int or idx < 0 or idx in indices:
            raise ValueError("Hypothesis turn idx must be a unique nonnegative integer")
        indices.add(idx)
        if "entities" in turn and not isinstance(turn["entities"], dict):
            raise ValueError("turn entities must be an object")
        if "speaker" in turn and (not isinstance(turn["speaker"], str) or not turn["speaker"]):
            raise ValueError("turn speaker must be a nonempty string")
        if ("start" in turn) != ("end" in turn):
            raise ValueError("turn start and end must be supplied together")
        for field in ("start", "end"):
            if field in turn:
                value = turn[field]
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError("turn timings must be finite and nonnegative")
        if "end" in turn and turn["end"] < turn["start"]:
            raise ValueError("turn end must not precede start")
        _context(turn, None)
    return turns


def _recognition_values(recognized) -> dict[str, str]:
    return {"raw": recognized.raw_text, "corrected": recognized.corrected_text,
            "agent_input": recognized.agent_text}


def _grader():
    path = btc_data_dir() / "eval/reference_eval.py"
    spec = importlib.util.spec_from_file_location("main_asr_scorer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_output(out: Path) -> None:
    from .cli import runs_dir
    repository = Path(__file__).resolve().parents[6]
    out = out.resolve()
    if out.is_relative_to(repository) and not out.is_relative_to(runs_dir().resolve()):
        raise ValueError("Write private ASR evidence under evaluation/runs or outside the repository")
    out.mkdir(parents=True, exist_ok=False)


def _audio(path: Path):
    import numpy as np
    import soundfile as sf
    import soxr
    info = sf.info(path)
    if not info.frames or not 1 <= info.channels <= 8 or info.duration > 1800:
        raise ValueError("Audio must contain 0–1800 seconds and 1–8 channels")
    samples, rate = sf.read(path, dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)
    if not np.isfinite(samples).all():
        raise ValueError("Audio contains nonfinite samples")
    if rate != 16000:
        samples = soxr.resample(samples, rate, 16000).astype(np.float32)
    return samples, {"sample_rate": rate, "channels": info.channels,
                     "audio_seconds": info.duration, "audio_sha256": _sha(path),
                     "signal": signal_metrics(samples)}


def signal_metrics(samples) -> dict:
    """Reference-free signal descriptors, never clean-speech quality or true SNR."""
    import numpy as np
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(samples)))
    frames = samples[:len(samples) // 320 * 320].reshape(-1, 320)
    frame_rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)) if len(frames) else np.array([])
    blocks = samples[:len(samples) // 512 * 512].reshape(-1, 512)
    power = np.sum(np.abs(np.fft.rfft(blocks * np.hanning(512), axis=1)) ** 2, axis=0) if len(blocks) else None
    frequencies = np.fft.rfftfreq(512, 1 / 16000)
    total = float(np.sum(power)) if power is not None else 0
    def db(value): return 20 * math.log10(value) if value > 0 else None
    return {"rms": rms, "rms_dbfs": db(rms), "peak": peak, "peak_dbfs": db(peak),
            "dc_offset": float(np.mean(samples)), "clipped_fraction": float(np.mean(np.abs(samples) >= .999)),
            "low_energy_frame_fraction_below_minus50_dbfs": float(np.mean(frame_rms < 10 ** (-50/20))) if frame_rms.size else None,
            "band_power_fraction": {name: float(np.sum(power[(frequencies >= lo) & (frequencies < hi)])) / total if total else None
                                    for name, lo, hi in [("below_100_hz", 0, 100), ("100_to_4000_hz", 100, 4000), ("above_4000_hz", 4000, 8001)]},
            "snr_db": None, "pesq": None, "stoi": None, "si_sdr": None,
            "note": "No aligned clean reference; low-energy frames include inserted montage gaps."}


def audio_windows(samples):
    """Bound decoder work to 20 s, cut at low energy near the boundary; no transcript/GT input."""
    import numpy as np
    rate, maximum, search = 16000, 20 * 16000, 4 * 16000
    start = 0
    while start < len(samples):
        end = min(start + maximum, len(samples))
        if end < len(samples):
            left = end - search
            frames = samples[left:end].reshape(-1, 320)
            energy = np.mean(frames.astype(np.float64) ** 2, axis=1)
            # Center of a silent plateau avoids cutting a word at the gap's edge.
            quiet = np.flatnonzero(energy <= energy.min() + 1e-12)
            end = left + (int(quiet[len(quiet) // 2]) + 1) * 320
        yield start, end, samples[start:end]
        start = end


def decode(path: Path, model: str, denoiser: str = "none") -> dict:
    from ...components.voice import asr
    if asr.remote() and urlparse(asr.url()).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("This mode allows local ASR only; no paid/external provider")
    samples, info = _audio(path)
    load_seconds = asr.load(model)
    started = time.perf_counter()
    chunks = []
    for start, end, chunk in audio_windows(samples):
        result = asr.transcribe(model, chunk, lexicon().hotwords, denoiser=denoiser)
        chunks.append({"start": start / 16000, "end": end / 16000, "text": result.text, "seconds": result.seconds,
                       "denoise_seconds": getattr(result, "denoise_seconds", 0.0),
                       "decoder_seconds": getattr(result, "decoder_seconds", None),
                       "preprocessing": getattr(result, "preprocessing", None) or {"name": "none"}})
    return {"text": " ".join(c["text"].strip() for c in chunks).strip(), "seconds": sum(c["seconds"] for c in chunks), "model": model,
            "denoiser": denoiser, "denoise_seconds": sum(c["denoise_seconds"] for c in chunks),
            "decoder_seconds": sum(c["decoder_seconds"] if c["decoder_seconds"] is not None else c["seconds"] for c in chunks),
            "chunks": chunks, "chunking_version": "energy-min-20s-v1", "load_seconds": load_seconds,
            "model_metadata": asr.metadata(model),
            "wall_seconds": time.perf_counter() - started, **info}


def audio_smoke(path: Path, out: Path, model: str, denoiser: str = "none") -> dict:
    """Unlabelled audio: transcription/latency only, no invented WER reference."""
    from .cli import runs_dir
    repository = Path(__file__).resolve().parents[6]
    out = out.resolve()
    if out.is_relative_to(repository) and not out.is_relative_to(runs_dir().resolve()):
        raise ValueError("Write private ASR evidence under evaluation/runs or outside the repository")
    out.mkdir(parents=True, exist_ok=False)
    result = decode(path, model, denoiser)
    recognition = process(result["text"], lexicon=lexicon())
    report = {"status": "UNLABELLED", "hypothesis": {**result, **recognition.to_dict()},
              "WER": None, "CER": None, "entity_accuracy": None,
              "policy_version": POLICY_VERSION, "metrics_version": METRICS_VERSION,
              "note": "A human-verified reference is required for WER/CER; SNR needs a clean/noise reference."}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report


def evaluate(source: Path, hypotheses: Path | None, out: Path, *, model: str = "zipformer-30m",
             transcribe: bool = False, only: set[str] | None = None, entity_review: Path | None = None, denoiser: str = "none") -> dict:
    """Replay provided predictions or explicitly decode existing local audio. Never fetch weights."""
    if denoiser not in ("none", "rnnoise") or (denoiser != "none" and not transcribe):
        raise ValueError("Denoiser requires local transcription and a valid option")
    ground_truth = source / "ground_truth.json" if source.is_dir() else source
    document = _read(ground_truth)
    records = document.get("dialogues") if isinstance(document, dict) else None
    if not isinstance(records, list) or not records:
        raise ValueError("ground_truth.json needs a nonempty dialogues list")
    ids = [record.get("id") for record in records if isinstance(record, dict)]
    if len(ids) != len(records) or any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError("Dialogue IDs must be unique, nonempty strings")
    if any(not re.fullmatch(r"[\w-]+", key) for key in ids):
        raise ValueError("Dialogue IDs must be safe file names (letters, numbers, underscore, dash)")
    if any(not isinstance(record.get("full_text"), str) for record in records):
        raise ValueError("Every dialogue needs full_text; references are never invented")
    reference_date = _clock(document.get("reference_date"), "reference_date")
    provenance = document.get("provenance")
    if document.get("kind") == "turns":
        extraction_mode, mode_source = "utterance", "document.kind"
    elif isinstance(provenance, dict) and provenance.get("unit") == "segments":
        extraction_mode, mode_source = "utterance", "document.provenance.unit"
    else:
        extraction_mode, mode_source = "dialogue", "default-dialogue"
    if only and not only.issubset(set(ids)):
        raise ValueError("Unknown --only dialogue ID")
    selected = [record for record in records if not only or record["id"] in only]
    entity_info, vocabulary = None, []
    if entity_review:
        from .asr_entities import labels
        selected, entity_info, vocabulary = labels(entity_review, selected)
    if transcribe and hypotheses is not None:
        raise ValueError("Choose recorded hypotheses OR --asr-transcribe")
    hypotheses = hypotheses or (ground_truth.parent / "hypotheses.json" if not transcribe else None)
    if not transcribe and (hypotheses is None or not hypotheses.is_file()):
        raise ValueError("Provide --asr-hypotheses, or explicitly --asr-transcribe for local audio")
    incoming = _read(hypotheses) if hypotheses else {}
    if not isinstance(incoming, dict):
        raise ValueError("hypotheses.json must be keyed by dialogue ID")
    if transcribe:
        from ...components.voice import asr
        if asr.remote() and urlparse(asr.url()).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("This mode allows local ASR only; no paid/external provider")
    # Raw transcripts must stay outside tracked project directories.
    repository = Path(__file__).resolve().parents[6]
    from .cli import runs_dir
    out = out.resolve()
    if out.is_relative_to(repository) and not out.is_relative_to(runs_dir().resolve()):
        raise ValueError("Write private ASR evidence under evaluation/runs or outside the repository")
    out.mkdir(parents=True, exist_ok=False)
    snapshots = {variant: out / variant for variant in ("raw", "corrected", "agent_input")}
    variants = {variant: {} for variant in snapshots}
    rows, failures = [], []
    dictionary = lexicon()
    from ...components.intake import commerce as commerce_extractor
    generated_entity_samples = 0
    entity_provenance = {"mode": extraction_mode, "mode_source": mode_source,
                         "parent": {"generated": 0, "supplied": 0},
                         "turns": {"samples": 0, "predicted": 0, "generated": 0, "supplied": 0},
                         "clocks": {"context.call_date": 0, "document.reference_date": 0,
                                    "catalogue-default": 0}}
    for record in selected:
        key = record["id"]
        try:
            prediction = incoming.get(key)
            if transcribe:
                filename = record.get("audio") or f"audio/{key}.wav"
                path = (ground_truth.parent / filename).resolve()
                prediction = decode(path, model, denoiser)
                with (out / "decoded.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"id": key, "prediction": prediction}, ensure_ascii=False, allow_nan=False) + "\n")
                print(f"ASR {model}: {len(rows) + len(failures) + 1}/{len(selected)} {key}", file=sys.stderr, flush=True)
            if not isinstance(prediction, dict) or not isinstance(prediction.get("text"), str):
                raise ValueError("missing or invalid hypothesis")
            if ("entities" in prediction and not isinstance(prediction["entities"], dict)):
                raise ValueError("entities must be an object")
            for field in ("seconds", "wall_seconds", "audio_seconds"):
                value = prediction.get(field)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                    raise ValueError("timings must be finite and nonnegative")
            context, now = _context(prediction, reference_date)
            turns = _predicted_turns(prediction)
            recognized = process(prediction["text"], lexicon=dictionary, busy=context.get("busy") is True,
                                 min_words=2, echo_text=str(context.get("echo_text") or ""))
            values = _recognition_values(recognized)
            turn_values = []
            for turn in turns:
                turn_context, turn_now = _context(turn, now)
                turn_recognized = process(turn["text"], lexicon=dictionary, busy=turn_context.get("busy") is True,
                                          min_words=2, echo_text=str(turn_context.get("echo_text") or ""))
                turn_values.append((turn, _recognition_values(turn_recognized), turn_now))
            scored, sample_variants = {}, {}
            for variant, text in values.items():
                sample = {**prediction, "text": text}
                actual_text = "\n".join(v[variant] for _, v, _ in sorted(turn_values, key=lambda item: item[0]["idx"])) if turns else text
                if "entities" not in prediction:
                    if entity_review:
                        from .asr_entities import predict
                        sample["entities"] = predict(actual_text, vocabulary, version=entity_info["extractor_version"])
                    else:
                        if extraction_mode == "dialogue":
                            observed = commerce_extractor.observe_dialogue(actual_text, now=now)
                        else:
                            observed = commerce_extractor.observe(actual_text, now=now, speaker=context.get("speaker"))
                        sample["entities"] = observed["asr_entities"]
                        sample["scenario_entities"] = observed["scenario_entities"]
                if "turns" in prediction:
                    sample["turns"] = []
                    for turn, transformed, turn_now in turn_values:
                        predicted_turn = {**turn, "text": transformed[variant]}
                        if "entities" not in turn:
                            if entity_review:
                                from .asr_entities import predict
                                predicted_turn["entities"] = predict(transformed[variant], vocabulary, version=entity_info["extractor_version"])
                            else:
                                observed = commerce_extractor.observe(transformed[variant], now=turn_now, speaker=turn.get("speaker"))
                                predicted_turn["entities"] = observed["asr_entities"]
                                predicted_turn["scenario_entities"] = observed["scenario_entities"]
                        sample["turns"].append(predicted_turn)
                sample_variants[variant] = sample
                scored[variant] = edits(normalize(record["full_text"]).split(), normalize(text).split())
            for variant, sample in sample_variants.items():
                variants[variant][key] = sample
            parent_source = "supplied" if "entities" in prediction else "generated"
            entity_provenance["parent"][parent_source] += 1
            entity_provenance["turns"]["samples"] += bool(turns)
            entity_provenance["turns"]["predicted"] += len(turns)
            for turn in turns:
                entity_provenance["turns"]["supplied" if "entities" in turn else "generated"] += 1
            clock_source = "context.call_date" if context.get("call_date") is not None else "document.reference_date" if reference_date is not None else "catalogue-default"
            entity_provenance["clocks"][clock_source] += 1
            if not entity_review and parent_source == "generated":
                generated_entity_samples += 1
            audio_seconds, seconds = prediction.get("audio_seconds"), prediction.get("seconds")
            rtf = seconds / audio_seconds if (isinstance(seconds, (int, float)) and seconds >= 0
                and isinstance(audio_seconds, (int, float)) and audio_seconds > 0) else None
            rows.append({"id": key, **recognized.to_dict(), "scores": scored, "rtf": rtf,
                         "seconds": seconds, "audio_seconds": audio_seconds,
                         "wall_seconds": prediction.get("wall_seconds"),
                         "denoise_seconds": prediction.get("denoise_seconds"), "decoder_seconds": prediction.get("decoder_seconds"),
                         "capture_profile": prediction.get("capture_profile", "recorded-audio-unverified"),
                         "noisy": record.get("noisy"), "region": record.get("customer_region"),
                         "expected_voice": record.get("voice_expectation"),
                         "entities_provided": isinstance(prediction.get("entities"), dict),
                         "entity_extraction_mode": extraction_mode, "predicted_turns": len(turns),
                         "signal": prediction.get("signal"),
                         "chunks": prediction.get("chunks"),
                         "reference_text": record["full_text"],
                         "condition": record.get("condition"),
                         "audio_sha256": prediction.get("audio_sha256")})
            if prediction.get("model_metadata"):
                rows[-1]["model_metadata"] = prediction["model_metadata"]
        except Exception as error:
            failures.append({"id": key, "error": type(error).__name__, "detail": str(error)[:300]})
    official, score_cache = {}, {}
    for variant, folder in snapshots.items():
        folder.mkdir()
        # Preserve references verbatim; selection is recorded in the run manifest.
        (folder / "ground_truth.json").write_text(json.dumps({**document, "dialogues": selected}, ensure_ascii=False), encoding="utf-8")
        (folder / "hypotheses.json").write_text(json.dumps(variants[variant], ensure_ascii=False), encoding="utf-8")
        for record in selected:
            segment = ground_truth.parent / "audio" / f"{record['id']}.segments.json"
            if segment.is_file():
                (folder / "audio").mkdir(exist_ok=True)
                shutil.copyfile(segment, folder / "audio" / segment.name)
        try:
            fingerprint = json.dumps(variants[variant], ensure_ascii=False, sort_keys=True)
            if fingerprint not in score_cache:
                score = _grader().wer_cer(str(folder))
                if (not isinstance(score, dict) or score.get("n_dialogues") != len(rows)
                        or any(type(score.get(key)) not in (int, float)
                               or not math.isfinite(score[key]) or score[key] < 0 for key in ("WER", "CER"))):
                    raise ValueError("Main ASR scorer returned missing or invalid scores")
                score_cache[fingerprint] = score
            official[variant] = score_cache[fingerprint]
        except Exception as error:
            official[variant] = {"status": "unavailable", "error": type(error).__name__}
    diagnostics = summarize(rows, attempted=len(selected), failures=failures)
    diagnostics["main_scores_available"] = all(isinstance(score, dict) and score.get("status") != "unavailable" for score in official.values())
    from .asr_errors import analyze
    error_analysis = analyze(rows)
    generated_entities = entity_provenance["parent"]["generated"] + entity_provenance["turns"]["generated"]
    commerce_metadata = commerce_extractor.metadata() if generated_entities and not entity_review else None
    entity_provenance["instrument"] = ({"kind": "reviewed-vocabulary", "version": entity_info["extractor_version"]}
                                       if generated_entities and entity_review else
                                       {"kind": "commerce", **commerce_metadata} if commerce_metadata else
                                       {"kind": "supplied", "version": None})
    manifest = {"metrics_version": METRICS_VERSION, "policy_version": POLICY_VERSION,
                "commerce_extractor": commerce_metadata, "entity_extraction": entity_provenance,
                "generated_entity_samples": generated_entity_samples,
                "mode": "local-decode" if transcribe else "hypothesis-replay", "model": model if transcribe else None, "denoiser": denoiser,
                "ground_truth_sha256": _sha(ground_truth), "hypotheses_sha256": _sha(hypotheses) if hypotheses else None,
                "main_scorer_sha256": _sha(btc_data_dir() / "eval/reference_eval.py"),
                "selected_ids": [record["id"] for record in selected],
                "code_sha256": {p.name: _sha(p) for p in [Path(__file__), Path(process.__code__.co_filename),
                                 Path(__file__).with_name("asr_entities.py"), Path(__file__).with_name("asr_errors.py"),
                                 Path(__file__).with_name("asr_package.py"),
                                 Path(__file__).parents[2] / "components/voice/asr.py",
                                 Path(__file__).parents[2] / "components/voice/policy.py",
                                 Path(__file__).parents[2] / "components/intake/entities.py",
                                 Path(__file__).parents[2] / "components/intake/commerce.py",
                                 Path(__file__).parents[2] / "components/intake/spoken.py",
                                 Path(__file__).parents[2] / "components/intake/itn.py",
                                 Path(__file__).parents[2] / "components/intake/lexicon.py"]},
                "hotwords": dictionary.hotwords,
                "lexicon_sha256": hashlib.sha256(json.dumps([(p.pattern, r) for p, r in dictionary._rules],
                    ensure_ascii=False).encode()).hexdigest()}
    report = {"status": "INCOMPLETE" if failures or not diagnostics["main_scores_available"] else "COMPLETE", "main_scorer": official,
              "diagnostics": diagnostics, "manifest": manifest}
    if entity_review:
        from .asr_entities import diagnostics as entity_diagnostics
        report["entity_review"] = entity_info
        report["entity_diagnostics"] = {variant: entity_diagnostics(selected, predictions) for variant, predictions in variants.items()}
    for name, content in (("report.json", report), ("diagnostics.json", rows), ("errors.json", failures),
                          ("error-analysis.json", error_analysis)):
        (out / name).write_text(json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report


def summarize(rows: list[dict], *, attempted: int, failures: list) -> dict:
    def micro(subset, variant):
        n = sum(row["scores"][variant]["reference_words"] for row in subset)
        counts = {key: sum(row["scores"][variant][key] for row in subset)
                  for key in ("errors", "substitutions", "deletions", "insertions")}
        return {**counts, "reference_words": n, "wer": counts["errors"] / n if n else None}
    expectations = [row for row in rows if isinstance(row.get("expected_voice"), dict)
                    and type(row["expected_voice"].get("accepted")) is bool]
    negatives = [row for row in expectations if not row["expected_voice"]["accepted"]]
    positives = [row for row in expectations if row["expected_voice"]["accepted"]]
    silence = [row for row in rows if row["scores"]["raw"]["reference_words"] == 0]
    return {"attempted": attempted, "scored": len(rows), "failed": len(failures),
            "coverage": len(rows) / attempted if attempted else None,
            "word_alignment": {variant: micro(rows, variant) for variant in ("raw", "corrected", "agent_input")},
            "by_noise": {str(noisy): {"n": len(sub), "raw": micro(sub, "raw"), "agent_input": micro(sub, "agent_input")}
                         for noisy in (False, True) if (sub := [row for row in rows if row["noisy"] is noisy])},
            "by_region": {region: {"n": len(sub), "raw": micro(sub, "raw")}
                          for region in sorted({row["region"] for row in rows if isinstance(row["region"], str)})
                          if (sub := [row for row in rows if row["region"] == region])},
            "rtf": distribution([row["rtf"] for row in rows if row["rtf"] is not None]),
            "micro_rtf": sum(row["seconds"] for row in rows if row["seconds"] is not None) / sum(row["audio_seconds"] for row in rows if row["audio_seconds"] is not None)
                         if rows and all(row["seconds"] is not None and row["audio_seconds"] is not None for row in rows)
                         and sum(row["audio_seconds"] for row in rows) > 0 else None,
            "by_condition": {condition: {"n": len(sub), "raw": micro(sub, "raw")}
                             for condition in sorted({row["condition"] for row in rows if isinstance(row.get("condition"), str)})
                             if (sub := [row for row in rows if row.get("condition") == condition])},
            "noise_labels_missing": sum(row["noisy"] is None for row in rows),
            "decode_seconds": distribution([row["seconds"] for row in rows if isinstance(row["seconds"], (int, float))]),
            "silence": {"n": len(silence), "nonempty_hypotheses": sum(bool(normalize(row["raw_text"])) for row in silence)},
            "voice_decisions": {"labelled": len(expectations), "negative_n": len(negatives), "positive_n": len(positives),
                                "false_accept_rate": sum(row["accepted"] for row in negatives) / len(negatives) if negatives else None,
                                "missed_accept_rate": sum(not row["accepted"] for row in positives) / len(positives) if positives else None},
            "entity_predictions_provided": sum(row["entities_provided"] for row in rows),
            "entity_source": "supplied hypothesis entities when present; otherwise extracted from actual predicted text",
            "note": "Main's scores can omit missing files: read coverage/errors. WER is undefined for empty references. "
                    "Capture AEC/NS cannot be reproduced on an already recorded file; no reference or entity labels are inferred."}
