"""Team ASR set from the scenario audio, and its evaluation with BTC's ``wer_cer``; no LLM.

``build_set`` filters ``evaluation/data-generation/output/audio`` (one WAV per customer turn, made by
``synthesize_scenario_audio``) into a BTC-shaped set under ``datasets/<set>/``: ``ground_truth.json``,
``audio/<id>.wav`` and ``conversion-report.json`` (what was kept, what was dropped and why, source hashes).
A clip is kept only when its WAV is a nonempty PCM16 mono 16 kHz file of the length its JSON states and its
text is still the turn of the current scenario; typed teencode is not speech and is dropped.

``evaluate`` sends every clip to the ASR service the agent uses (``POST /v1/transcribe``, the agent's
hotwords), writes ``hypotheses.json`` twice -- ``raw`` (the recogniser) and ``lexicon`` (after the agent's
``voice.lexicon`` corrections, what the advisor reads) -- and scores both with BTC's ``wer_cer``, plus
WER by noise type, input mode and whether the sentence holds numbers or codes.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import sys
import time
import wave

from .reporting import btc_module

EVALUATION = Path(__file__).resolve().parents[1]
REPOSITORY = EVALUATION.parents[1]
CREATE_DATA = REPOSITORY / "evaluation/data-generation"
SERVICE_SRC = REPOSITORY / "apps/ai-agent-service/src"
AUDIO_ROOT = CREATE_DATA / "output/audio"
#: The test cases (BTC format); their region is in the metadata/ folder beside them (data-generation dataset.py).
SCENARIOS_DIR = CREATE_DATA / "output/scenarios"
DATASETS = EVALUATION / "datasets"
DEFAULT_SET = "asr-team-v2"
RATE = 16_000
#: Typed chat (teencode, no diacritics, typos): the clip reads it aloud, no caller says it.
NOT_SPEECH = {"chat_teencode", "chat_khong_dau", "chat_sai_chinh_ta"}
BTC_GROUND_TRUTH = EVALUATION / "evaluation-contracts/sources/btc/asr/ground_truth.json"


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spoken():
    return _module("create_data_spoken", CREATE_DATA / "src/asr/spoken.py")


def _entities():
    # The same extraction as create_data's eval_asr: the agent's ITN, then plain cues.
    return _module("create_data_entities", CREATE_DATA / "src/asr/entities.py")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _shown(path):
    path = Path(path).resolve()
    return path.relative_to(REPOSITORY).as_posix() if path.is_relative_to(REPOSITORY) else path.as_posix()


def wav_problem(path, seconds=None):
    """Why *path* cannot be scored (None when it is a nonempty PCM16 mono 16 kHz WAV of *seconds*)."""
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != RATE:
                return "wav_format"
            frames = audio.getnframes()
    except (OSError, EOFError, wave.Error):
        return "wav_unreadable"
    if frames <= 0:
        return "wav_empty"
    if seconds is not None and abs(frames / RATE - float(seconds)) > 0.05:
        return "wav_length_mismatch"
    return None


def has_number_or_code(text):
    """Digits, a code (SKU-AP-X, TS16) or an acronym (COD, CCCD): the reference spells them as we
    assume the voice read them."""
    return bool(re.search(r"\d|\b[A-Z]{2,}\b|\b[A-Z]{1,4}(?:-[A-Z0-9]+)+\b", text))


def build_set(out=None, *, audio_root=AUDIO_ROOT, scenarios_dir=SCENARIOS_DIR, set_id=DEFAULT_SET):
    """Filter the scenario audio into a new BTC-shaped set; refuses to overwrite an existing revision."""
    out = Path(out or DATASETS / set_id)
    audio_root, scenarios_dir = Path(audio_root), Path(scenarios_dir)
    if out.exists():
        raise ValueError(f"{out} exists: a used revision is never overwritten; choose a new --set-id")
    clips = sorted(audio_root.glob("scenarios_*/call_*/turn_*.json"))
    if not clips:
        raise ValueError(f"No clip JSON under {audio_root} (run create_data's synthesize_scenario_audio)")
    spoken, entities = _spoken(), _entities()
    scenarios, used = {}, {}
    kept, dropped = [], []
    for meta_path in clips:
        relative = meta_path.relative_to(audio_root).as_posix()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        sid, call, turn = meta.get("scenario_id"), meta.get("call"), meta.get("turn")
        if sid not in scenarios:
            source = scenarios_dir / f"{sid}.json"
            scenarios[sid] = json.loads(source.read_text(encoding="utf-8")) if source.is_file() else None
            if scenarios[sid] is not None:
                used[source.name] = _sha256(source)
                metadata = scenarios_dir.parent / "metadata" / source.name
                if metadata.is_file():
                    scenarios[sid].setdefault("region", json.loads(metadata.read_text(encoding="utf-8")).get("region"))
        scenario = scenarios[sid]
        wav = meta_path.with_suffix(".wav")
        turns = (scenario or {}).get("calls", {}).get(call, {}).get("customer_turns", [])
        text = (meta.get("text") or "").strip()
        if not wav.is_file():
            reason = "wav_missing"
        elif scenario is None:
            reason = "scenario_missing"
        elif call not in scenario["calls"]:
            reason = "call_missing"
        elif not isinstance(turn, int) or not 1 <= turn <= len(turns):
            reason = "turn_out_of_range"
        elif not text or turns[turn - 1].strip() != text:
            reason = "text_changed"
        elif meta.get("input_mode") in NOT_SPEECH:
            reason = "not_speech"
        else:
            reason = wav_problem(wav, meta.get("duration_seconds"))
        if reason:
            dropped.append({"clip": relative, "reason": reason})
            continue
        noise = (meta.get("noise") or {}).get("type")
        clip_id = f"{sid}-{call}-t{turn}"
        # What the voice read: the model-written spoken form the clip carries (create_data src/asr/reference.py),
        # or, for clips spoken before it existed, the rule-made one.
        reference = meta.get("spoken_text") or spoken.to_spoken(text)
        source = (meta.get("reference_source") or "rule") if meta.get("spoken_text") else "rule_at_build"
        # From the spoken reference, the way a hypothesis gets them: a perfect transcript scores 100%.
        stated = entities.extract(reference)
        kept.append((wav, {
            "id": clip_id, "full_text": reference, "noisy": bool(noise), "entities": stated,
            "turns": [{"idx": 1, "speaker": "C", "text": reference, "entities": stated}],
            "n_turns": 1, "scenario_ref": f"{sid} {call} turn {turn}", "source_text": text,
            "customer_region": scenario.get("region"), "input_mode": meta.get("input_mode"),
            "noise": noise or "clean", "snr_db": (meta.get("noise") or {}).get("snr_db"),
            "reference_source": source, "reference_entities": meta.get("entities"),
            "voice_id": meta.get("voice_id"), "tts_model": meta.get("model_id"),
            "duration_seconds": meta.get("duration_seconds"), "number_or_code": has_number_or_code(text),
            "source_clip": relative}))
    if not kept:
        raise ValueError("No clip passed the filter: " + json.dumps(Counter(d["reason"] for d in dropped)))
    (out / "audio").mkdir(parents=True)
    btc = json.loads(BTC_GROUND_TRUTH.read_text(encoding="utf-8"))
    dialogues = [row for _, row in kept]
    files = {}
    for wav, row in kept:
        shutil.copyfile(wav, out / "audio" / f"{row['id']}.wav")
        files[f"audio/{row['id']}.wav"] = _sha256(wav)
    ground_truth = {
        "description": f"{set_id}: one customer turn per clip (ElevenLabs voices, synthetic noise) from the "
                       "team scenarios; diagnostic, not reviewed. Reference = the spoken form the voice read "
                       "(create_data src/asr/reference.py), or for older clips the source text in spoken form "
                       "(src/asr/spoken.py), as we assume the voice read it.",
        "hypotheses_format": btc["hypotheses_format"], "normalization_rule": btc["normalization_rule"],
        "reference_date": btc.get("reference_date"), "dialogues": dialogues}
    (out / "ground_truth.json").write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files["ground_truth.json"] = _sha256(out / "ground_truth.json")
    seconds = sum(float(row["duration_seconds"]) for row in dialogues)
    report = {
        "schema_version": "team-asr-set-v1", "set_id": set_id, "status": "diagnostic", "reviewed_by": None,
        "official_gt_approved": False, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"audio_root": _shown(audio_root), "scenarios_dir": _shown(scenarios_dir),
                   "scenario_sha256": dict(sorted(used.items())),
                   "spoken_py_sha256": _sha256(CREATE_DATA / "src/asr/spoken.py"),
                   "entities_py_sha256": _sha256(CREATE_DATA / "src/asr/entities.py")},
        "rules": ["WAV exists, PCM16 mono 16 kHz, nonempty, length = duration_seconds ± 0.05 s",
                  "scenario, call and turn exist in the current scenarios file",
                  "clip text == that customer turn (otherwise the audio is stale)",
                  "input_mode chat_teencode dropped (typed slang, not speech)"],
        "reference": "full_text = the clip's spoken_text, the exact words TTS read (reference_source llm|rule); "
                     "a clip spoken before create_data wrote spoken_text gets to_spoken(source_text) "
                     "(reference_source rule_at_build), scored against how we assume the voice read numbers and "
                     "codes: listen before blaming the recogniser. entities = entities.extract(full_text), the "
                     "same extraction the hypotheses get; the model's own entities are kept as reference_entities.",
        "counts": {"clips_json": len(clips), "kept": len(kept), "dropped": len(dropped),
                   "dropped_by_reason": dict(Counter(d["reason"] for d in dropped).most_common()),
                   "kept_by_noise": dict(Counter(r["noise"] for r in dialogues).most_common()),
                   "kept_by_input_mode": dict(Counter(r["input_mode"] for r in dialogues).most_common()),
                   "kept_by_reference_source": dict(Counter(r["reference_source"] for r in dialogues).most_common()),
                   "kept_number_or_code": sum(r["number_or_code"] for r in dialogues),
                   "kept_with_entities": sum(bool(r["entities"]) for r in dialogues),
                   "scenarios": len({r["scenario_ref"].split()[0] for r in dialogues}),
                   "audio_hours": round(seconds / 3600, 3), "mean_seconds": round(seconds / len(dialogues), 2)},
        "files_sha256": files, "dropped": dropped}
    (out / "conversion-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def restore_audio(set_id=DEFAULT_SET, *, audio_root=AUDIO_ROOT):
    """Copy back the WAVs of a committed set (audio/ is not in Git) from the clip folder, hash-checked."""
    out = DATASETS / set_id
    truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    expected = json.loads((out / "conversion-report.json").read_text(encoding="utf-8"))["files_sha256"]
    (out / "audio").mkdir(exist_ok=True)
    restored, mismatched = 0, []
    for row in truth["dialogues"]:
        source = (Path(audio_root) / row["source_clip"]).with_suffix(".wav")
        name = f"audio/{row['id']}.wav"
        if not source.is_file() or _sha256(source) != expected.get(name):
            mismatched.append(row["source_clip"])
            continue
        shutil.copyfile(source, out / name)
        restored += 1
    return {"set_id": set_id, "restored": restored, "missing_or_changed": mismatched}


def check_set(path, set_id):
    """Offline issues of an ASR set: audio of every dialogue present and well-formed, hashes as built."""
    path = Path(path)
    issues = []
    try:
        truth = json.loads((path / "ground_truth.json").read_text(encoding="utf-8"))
        report = json.loads((path / "conversion-report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [{"code": "ASR_SET_UNREADABLE", "set": set_id, "message": str(exc)}], 0
    ids = [d.get("id") for d in truth.get("dialogues", [])]
    for key, count in Counter(ids).items():
        if count > 1:
            issues.append({"code": "ASR_ID_DUPLICATE", "set": set_id, "value": key})
    expected = report.get("files_sha256", {})
    for clip_id in ids:
        name = f"audio/{clip_id}.wav"
        wav = path / name
        problem = "wav_missing" if not wav.is_file() else wav_problem(wav)
        if problem:
            issues.append({"code": "ASR_AUDIO_INVALID", "set": set_id, "id": clip_id, "reason": problem})
        elif expected.get(name) != _sha256(wav):
            issues.append({"code": "ASR_AUDIO_HASH", "set": set_id, "id": clip_id})
    if expected.get("ground_truth.json") != _sha256(path / "ground_truth.json"):
        issues.append({"code": "ASR_GROUND_TRUTH_HASH", "set": set_id})
    return issues, len(ids)


def _api_key():
    if os.environ.get("ASR_API_KEY"):
        return os.environ["ASR_API_KEY"].strip()
    env = REPOSITORY / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ASR_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def _agent_lexicon():
    if str(SERVICE_SRC) not in sys.path:
        sys.path.insert(0, str(SERVICE_SRC))
    from ai_agent_service.components.intake.lexicon import lexicon  # noqa: PLC0415
    return lexicon()


def _samples(path):
    import numpy as np
    with wave.open(str(path), "rb") as audio:
        pcm = audio.readframes(audio.getnframes())
    return np.frombuffer(pcm, dtype="<i2").astype("<f4") / 32768


def _breakdown(ground_truth, per_dialogue):
    """Mean per-clip WER (BTC's ``wer_noisy`` arithmetic) by noise type, input mode, numbers/codes."""
    groups = defaultdict(list)
    for row in ground_truth:
        score = per_dialogue.get(row["id"])
        if score is None:
            continue
        groups[f"noise:{row['noise']}"].append(score["wer"])
        groups[f"input_mode:{row['input_mode']}"].append(score["wer"])
        groups["number_or_code:" + ("yes" if row["number_or_code"] else "no")].append(score["wer"])
    return {key: {"n": len(values), "mean_wer": round(statistics.mean(values), 1)}
            for key, values in sorted(groups.items())}


def evaluate(out, *, set_id=DEFAULT_SET, url="http://127.0.0.1:8500", model="zipformer-30m", limit=None,
             hypotheses=None, hotwords=True):
    """Transcribe the set through the ASR service (or take *hypotheses*), score raw and lexicon with BTC."""
    out = Path(out)
    if out.exists():
        raise ValueError(f"{out} exists: choose a new output directory")
    source = DATASETS / set_id
    issues, _ = check_set(source, set_id)
    if issues:
        raise ValueError(f"{set_id} fails its offline check ({len(issues)} issues): run data-check --set {set_id}")
    truth = json.loads((source / "ground_truth.json").read_text(encoding="utf-8"))
    dialogues = truth["dialogues"][:limit] if limit else truth["dialogues"]
    entities, lexicon = _entities(), _agent_lexicon()
    raw, timing = {}, {}
    if hypotheses:
        given = json.loads(Path(hypotheses).read_text(encoding="utf-8"))
        raw = {row["id"]: {"text": given[row["id"]]["text"]} for row in dialogues if row["id"] in given}
    else:
        import httpx
        headers = {"Content-Type": "application/octet-stream"}
        if _api_key():
            headers["Authorization"] = f"Bearer {_api_key()}"
        words = lexicon.hotwords if hotwords else []
        with httpx.Client(base_url=url.rstrip("/"), headers=headers, timeout=120) as client:
            try:
                client.get("/health").raise_for_status()
                client.post(f"/v1/models/{model}/load").raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError(f"ASR service at {url} not reachable or cannot load {model}: {exc}") from exc
            for index, row in enumerate(dialogues, 1):
                samples = _samples(source / "audio" / f"{row['id']}.wav")
                started = time.perf_counter()
                try:
                    response = client.post("/v1/transcribe", params={"model": model, "hotwords": ",".join(words)},
                                           content=samples.tobytes())
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise RuntimeError(f"{row['id']}: {exc}") from exc
                body = response.json()
                raw[row["id"]] = {"text": body["text"]}
                timing[row["id"]] = {"audio_seconds": body["audio_seconds"], "asr_seconds": body["seconds"],
                                     "round_trip_seconds": round(time.perf_counter() - started, 3)}
                if index % 50 == 0:
                    print(f"  {index}/{len(dialogues)}", flush=True)
    missing = [row["id"] for row in dialogues if row["id"] not in raw]
    btc = btc_module()
    variants = {}
    for variant in ("raw", "lexicon"):
        folder = out / variant
        folder.mkdir(parents=True)
        (folder / "ground_truth.json").write_text(json.dumps({**truth, "dialogues": dialogues}, ensure_ascii=False,
                                                             indent=2), encoding="utf-8")
        produced = {}
        for clip_id, hyp in raw.items():
            text, applied = (hyp["text"], []) if variant == "raw" else lexicon.correct(hyp["text"])
            produced[clip_id] = {"text": text, "entities": entities.extract(text),
                                 **({"corrections": applied} if applied else {})}
        (folder / "hypotheses.json").write_text(json.dumps(produced, ensure_ascii=False, indent=2), encoding="utf-8")
        official = btc.wer_cer(str(folder))
        variants[variant] = {"official": {k: v for k, v in official.items() if k != "per_dialogue"},
                             "breakdown": _breakdown(dialogues, official["per_dialogue"]),
                             "per_dialogue": official["per_dialogue"], "hypotheses": produced}
    per, heard = variants["lexicon"]["per_dialogue"], variants["lexicon"]["hypotheses"]
    worst = sorted(dialogues, key=lambda row: -per.get(row["id"], {}).get("wer", 0))[:25]
    seconds = [t["asr_seconds"] / t["audio_seconds"] for t in timing.values() if t["audio_seconds"]]
    report = {
        "schema_version": "team-asr-eval-v1", "set_id": set_id, "set_sha256": _sha256(source / "ground_truth.json"),
        "engine": "hypotheses file" if hypotheses else {"url": url, "model": model, "hotwords": bool(hotwords)},
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_clips": len(dialogues), "missing_hypotheses": missing, "complete": not missing,
        "rtf_mean": round(statistics.mean(seconds), 3) if seconds else None,
        **{variant: {k: variants[variant][k] for k in ("official", "breakdown")} for variant in ("raw", "lexicon")},
        "worst_clips_lexicon": [{"id": row["id"], "wer": per.get(row["id"], {}).get("wer"), "noise": row["noise"],
                                 "reference": row["full_text"], "hypothesis": heard.get(row["id"], {}).get("text")}
                                for row in worst],
        "notice": "Diagnostic team set (one customer turn per clip, synthetic voices and noise, unreviewed reference); "
                  "BTC's set is whole dialogues. No diarization: a clip has one speaker.",
        "timing": timing}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
