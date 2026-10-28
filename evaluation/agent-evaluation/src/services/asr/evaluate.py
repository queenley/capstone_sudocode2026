"""``run_eval.py asr``: an ASR set heard by the chosen engine, understood by the agent, scored by BTC's ``wer_cer``.

For every item of the set (a customer turn, or a whole two-person call):

1. the engine hears the WAV (``engines.py``); a dialogue is cut into speaker turns first (``diarization.py``);
2. the agent understands it (``understanding.py``), twice:
   - ``raw``: the recogniser's words, through intake without the lexicon;
   - ``lexicon``: after the agent's ``voice.lexicon`` corrections, the way a real call reaches the advisor;
3. each variant is written as BTC's ``hypotheses.json`` (text, entities, and ``turns`` when diarized) beside the set's
   ``ground_truth.json`` and ``audio/<id>.segments.json``, and scored by the organisers' ``wer_cer``: WER, CER,
   entity accuracy, diarization turn accuracy, WER clean / noisy.

Entity accuracy counts the keys the agent can take from speech (``understanding.UNDERSTOOD``); the ground truth's
other keys (what the agent reads from its tools, or tokenises) are listed under ``entities_not_from_speech``.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import cache
import importlib.util
import json
from pathlib import Path
import shutil
import statistics
import wave

import numpy as np

from src.common.contracts import btc_module
from src.services.asr import diarization, engines
from src.services.asr.dataset import DATASETS, DEFAULT_SET, REPOSITORY, check_set, has_number_or_code, sha256
from src.services.asr.understanding import UNDERSTOOD, AgentUnderstanding


@cache
def _spoken_module():
    spec = importlib.util.spec_from_file_location("data_generation_spoken", REPOSITORY / "evaluation/data-generation/src/asr/spoken.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def spoken(text):
    """*text* with digits and codes spelled as said; unchanged when it has none."""
    return _spoken_module().to_spoken(text) if has_number_or_code(text) else text


def _samples(path):
    with wave.open(str(path), "rb") as audio:
        pcm = audio.readframes(audio.getnframes())
    return np.frombuffer(pcm, dtype="<i2").astype("<f4") / 32768


def _breakdown(rows, per_dialogue):
    """Mean WER (BTC's ``wer_noisy`` arithmetic) by noise type, input mode, numbers/codes."""
    groups = defaultdict(list)
    for row in rows:
        score = per_dialogue.get(row["id"])
        if score is None:
            continue
        groups["noise:" + str(row.get("noise") or ("noisy" if row.get("noisy") else "clean"))].append(score["wer"])
        if row.get("input_mode"):
            groups["input_mode:" + row["input_mode"]].append(score["wer"])
        numbers = row.get("number_or_code", has_number_or_code(row.get("source_text") or ""))
        groups["number_or_code:" + ("yes" if numbers else "no")].append(score["wer"])
    return {key: {"n": len(values), "mean_wer": round(statistics.mean(values), 1)} for key, values in sorted(groups.items())}


def _entity_detail(rows, produced):
    """Per BTC key: how often the ground truth states it, how often the agent understood it right, and whether the
    agent can take it from speech at all."""
    table = defaultdict(lambda: {"in_ground_truth": 0, "understood_right": 0})
    for row in rows:
        heard = produced.get(row["id"], {}).get("entities", {})
        for key, value in row.get("entities", {}).items():
            table[key]["in_ground_truth"] += 1
            table[key]["understood_right"] += int(str(heard.get(key)) == str(value))
    return {key: {**counts, "from_speech": key in UNDERSTOOD} for key, counts in sorted(table.items())}


def evaluate(out, *, set_id=DEFAULT_SET, engine="agent", url="http://127.0.0.1:8500", understanding="model",
             diarizer="auto", segmentation=None, embedding=None, limit=None, hotwords=True):
    out = Path(out)
    if out.exists():
        raise ValueError(f"{out} exists: choose a new output directory")
    source = DATASETS / set_id
    issues, _ = check_set(source, set_id)
    if issues:
        raise ValueError(f"{set_id} fails its offline check ({len(issues)} issues): run data-check --set {set_id}")
    truth = json.loads((source / "ground_truth.json").read_text(encoding="utf-8"))
    kind = truth.get("kind", "turns")
    rows = truth["dialogues"][:limit] if limit else truth["dialogues"]
    hearer = engines.create(engine, url=url, hotwords=hotwords)
    # A per-turn clip has one speaker, the customer: no diarization (it would label the only voice A, the shop).
    cutter = diarization.choose(diarizer, hearer, segmentation=segmentation, embedding=embedding) if kind == "dialogues" else None
    if kind == "dialogues" and cutter is None:
        raise ValueError("A dialogue set needs speaker turns: --engine openai:gpt-4o-transcribe-diarize "
                         "(--diarizer native), or --diarizer sherpa --segmentation <onnx> --embedding <onnx>")
    agent = AgentUnderstanding(use_model=understanding == "model", reference_date=truth.get("reference_date") or "2026-10-15")

    heard, timing = {}, {}
    for index, row in enumerate(rows, 1):
        samples = _samples(source / "audio" / f"{row['id']}.wav")
        if cutter is not None:
            turns, result = cutter.turns(samples, hearer, row["id"])
        else:
            result = hearer.hear(samples, row["id"])
            turns = [{"speaker": "C", "text": result["text"]}]
        heard[row["id"]] = turns
        timing[row["id"]] = {"audio_seconds": result.get("audio_seconds"), "asr_seconds": result.get("seconds")}
        if index % 50 == 0:
            print(f"  heard {index}/{len(rows)}", flush=True)

    btc = btc_module()
    variants = {}
    for variant in ("raw", "lexicon"):
        folder = out / variant
        (folder / "audio").mkdir(parents=True)
        # BTC's wer_cer counts every ground-truth key; only the keys the agent reads from speech are scored.
        scored = [{**row, "entities": {k: v for k, v in row.get("entities", {}).items() if k in UNDERSTOOD}} for row in rows]
        (folder / "ground_truth.json").write_text(json.dumps({**truth, "dialogues": scored}, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
        for row in rows:
            segments = source / "audio" / f"{row['id']}.segments.json"
            if segments.is_file():
                shutil.copyfile(segments, folder / "audio" / segments.name)
        produced = {}
        for clip_id, turns in heard.items():
            lines = [{**t, "text": agent.lexicon.correct(t["text"]) if variant == "lexicon" else t["text"]} for t in turns]
            # WER text in the reference's written form (BTC's normalization_rule: one form on both sides). The
            # reference spells numbers and codes as said; a recogniser writing "25" is spelled "hai mươi lăm" here.
            item = {"text": spoken(" ".join(line["text"] for line in lines).strip()),
                    "entities": agent.entities(lines, lexicon=variant == "lexicon")}
            if cutter is not None:
                item["turns"] = [{**{k: line[k] for k in ("speaker", "start", "end")}, "text": spoken(line["text"])}
                                 for line in lines]
            produced[clip_id] = item
        (folder / "hypotheses.json").write_text(json.dumps(produced, ensure_ascii=False, indent=2), encoding="utf-8")
        official = btc.wer_cer(str(folder))
        variants[variant] = {"official": {k: v for k, v in official.items() if k != "per_dialogue"},
                             "breakdown": _breakdown(rows, official["per_dialogue"]),
                             "entities": _entity_detail(rows, produced),
                             "per_dialogue": official["per_dialogue"], "hypotheses": produced}

    per, said = variants["lexicon"]["per_dialogue"], variants["lexicon"]["hypotheses"]
    worst = sorted(rows, key=lambda row: -per.get(row["id"], {}).get("wer", 0))[:25]
    rtf = [t["asr_seconds"] / t["audio_seconds"] for t in timing.values() if t.get("asr_seconds") and t.get("audio_seconds")]
    missing = Counter(k for row in rows for k in row.get("entities", {}) if k not in UNDERSTOOD)
    report = {
        "schema_version": "team-asr-eval-v2", "set_id": set_id, "kind": kind, "set_sha256": sha256(source / "ground_truth.json"),
        "engine": hearer.describe(), "diarizer": cutter.name if cutter else None,
        "understanding": {"pipeline": "ai_agent_service: lexicon → intake (clean, ITN, PII) → MemoryAgent.extract",
                          "extractor": agent.version, "usage": agent.usage()},
        "hypothesis_normalization": "numbers, money, dates and codes the recogniser wrote as digits are spelled as "
                                    "said (evaluation/data-generation/src/asr/spoken.py), the form of the reference",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n_items": len(rows),
        "rtf_mean": round(statistics.mean(rtf), 3) if rtf else None,
        **{variant: {k: variants[variant][k] for k in ("official", "breakdown", "entities")} for variant in ("raw", "lexicon")},
        "entities_not_from_speech": dict(missing.most_common()),
        "worst_lexicon": [{"id": row["id"], "wer": per.get(row["id"], {}).get("wer"), "noisy": row.get("noisy"),
                           "reference": row["full_text"], "hypothesis": said.get(row["id"], {}).get("text")} for row in worst],
        "notice": "Diagnostic team set (ElevenLabs voices, synthetic noise, references not human-reviewed). Entity "
                  "accuracy counts only keys the agent takes from speech; see entities_not_from_speech.",
        "timing": timing}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
