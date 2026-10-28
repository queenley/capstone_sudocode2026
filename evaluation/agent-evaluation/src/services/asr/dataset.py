"""An ASR set under ``datasets/<set>/``: data-generation's ground truth, its audio, hashes; no model.

data-generation is the one source of the ground truth (the spoken text the voice read, and its entities in BTC's keys
with their ``entity_schema``). :func:`build_set` does not derive anything again; it pins a copy for evaluation:

- ``turns``: ``evaluation/data-generation/output/asr_reference/ground_truth.json``, one customer turn per clip;
- ``dialogues``: ``evaluation/data-generation/output/asr_test/ground_truth.json``, whole calls with the shop agent
  and the customer, and ``audio/<id>.segments.json`` (who spoke when) for diarization. BTC's own
  ``data/asr/ground_truth.json`` is the same shape: ``--source`` it once its ``audio/`` is beside it.

Each WAV is checked (PCM16 mono 16 kHz, nonempty, the length the ground truth states) and copied; a dialogue that
fails is dropped with its reason. ``conversion-report.json`` records the source file's hash, what was kept and
dropped, and every copied file's SHA-256; the set is registered in ``datasets/registry.json`` (``asr_sets``) as
``diagnostic``. A set is never overwritten: a changed source is a new ``--set-id``.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import wave

EVALUATION = Path(__file__).resolve().parents[3]   # evaluation/agent-evaluation
REPOSITORY = EVALUATION.parents[1]
GENERATED = REPOSITORY / "evaluation/data-generation/output"
SOURCES = {"turns": GENERATED / "asr_reference/ground_truth.json", "dialogues": GENERATED / "asr_test/ground_truth.json"}
#: Where the clips of sets built before data-generation wrote ground_truth.json came from (``source_clip``).
LEGACY_AUDIO = GENERATED / "audio"
DATASETS = EVALUATION / "datasets"
DEFAULT_SET = "asr-team-v2"
RATE = 16_000


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def shown(path):
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


def wav_seconds(path):
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / RATE


def has_number_or_code(text):
    """Digits, a code (SKU-AP-X, TS16) or an acronym (COD, CCCD): the line a recogniser most often gets wrong."""
    return bool(re.search(r"\d|\b[A-Z]{2,}\b|\b[A-Z]{1,4}(?:-[A-Z0-9]+)+\b", text or ""))


def _source_audio(kind, source, row):
    """``(wav, segments or None)`` of a ground-truth row, in data-generation's output."""
    if kind == "turns":
        return source.parent.parent / row["audio"], None
    folder = source.parent / "audio"
    return folder / f"{row['id']}.wav", folder / f"{row['id']}.segments.json"


def build_set(set_id, *, kind="turns", source=None, root=DATASETS):
    """Pin data-generation's ground truth of *kind* and its audio as ``<root>/<set_id>``; refuses to overwrite."""
    if kind not in SOURCES:
        raise ValueError(f"kind must be one of {sorted(SOURCES)}")
    source = Path(source or SOURCES[kind])
    out = Path(root) / set_id
    registry_path = Path(root) / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {
        "schema_version": "team-datasets-v1", "sets": []}
    if out.exists() or any(group["id"] == set_id for group in registry.get("asr_sets", [])):
        raise ValueError(f"{out} exists: a used revision is never overwritten; choose a new --set-id")
    if not source.is_file():
        raise ValueError(f"No ground truth at {shown(source)}: run data-generation's "
                         + ("synthesize_scenario_audio" if kind == "turns" else "build_asr_testset") + " first")
    truth = json.loads(source.read_text(encoding="utf-8"))
    # BTC's own file (data/asr/ground_truth.json, whole dialogues) has no kind; data-generation's says which it is.
    if truth.get("kind", kind) != kind or not isinstance(truth.get("dialogues"), list):
        raise ValueError(f"{shown(source)} is not a '{kind}' ground truth")
    kept, dropped, copies = [], [], []
    for row in truth["dialogues"]:
        wav, segments = _source_audio(kind, source, row)
        reason = ("wav_missing" if not wav.is_file() else "segments_missing" if segments and not segments.is_file()
                  else wav_problem(wav, row.get("duration_seconds")))
        if reason:
            dropped.append({"id": row["id"], "reason": reason})
            continue
        kept.append({**row, "number_or_code": has_number_or_code(row.get("source_text") or ""),
                     "duration_seconds": row.get("duration_seconds") or round(wav_seconds(wav), 3),
                     "source_audio": shown(wav)})
        copies.append((row["id"], wav, segments))
    if not kept:
        raise ValueError("No dialogue has usable audio: " + json.dumps(Counter(d["reason"] for d in dropped)))
    (out / "audio").mkdir(parents=True)
    files = {}
    for clip_id, wav, segments in copies:
        for path, name in ((wav, f"audio/{clip_id}.wav"), (segments, f"audio/{clip_id}.segments.json")):
            if path is not None:
                shutil.copyfile(path, out / name)
                files[name] = sha256(path)
    (out / "ground_truth.json").write_text(json.dumps({**truth, "dialogues": kept}, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    files["ground_truth.json"] = sha256(out / "ground_truth.json")
    seconds = sum(float(row.get("duration_seconds") or 0) for row in kept)
    report = {
        "schema_version": "team-asr-set-v2", "set_id": set_id, "kind": kind, "status": "diagnostic", "reviewed_by": None,
        "official_gt_approved": False, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"ground_truth": shown(source), "sha256": sha256(source)},
        "reference": "data-generation's ground truth as it is: full_text = the spoken text the TTS voice read "
                     "(reference_source llm, or rule when the model's form failed its checks); entities in BTC's keys "
                     "(entity_schema). Nothing is derived again here.",
        "counts": {"in_source": len(truth["dialogues"]), "kept": len(kept), "dropped": len(dropped),
                   "dropped_by_reason": dict(Counter(d["reason"] for d in dropped).most_common()),
                   "kept_noisy": sum(bool(r.get("noisy")) for r in kept), "audio_hours": round(seconds / 3600, 3)},
        "files_sha256": files, "dropped": dropped}
    (out / "conversion-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    registry.setdefault("asr_sets", []).append({"id": set_id, "path": set_id, "kind": kind, "reviewed_by": None,
                                                "status": "diagnostic"})
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def restore_audio(set_id=DEFAULT_SET, *, root=DATASETS):
    """Copy back the audio of a committed set (audio/ is not in Git) from where it was built, hash-checked."""
    out = Path(root) / set_id
    truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    expected = json.loads((out / "conversion-report.json").read_text(encoding="utf-8"))["files_sha256"]
    (out / "audio").mkdir(exist_ok=True)
    restored, mismatched = 0, []
    for row in truth["dialogues"]:
        source = (REPOSITORY / row["source_audio"]) if row.get("source_audio") else \
            (LEGACY_AUDIO / row["source_clip"]).with_suffix(".wav")
        pairs = [(source, f"audio/{row['id']}.wav")]
        if f"audio/{row['id']}.segments.json" in expected:
            pairs.append((source.with_suffix(".segments.json"), f"audio/{row['id']}.segments.json"))
        for path, name in pairs:
            if not path.is_file() or sha256(path) != expected.get(name):
                mismatched.append(shown(path))
                continue
            shutil.copyfile(path, out / name)
            restored += 1
    return {"set_id": set_id, "restored": restored, "missing_or_changed": mismatched}


def check_set(path, set_id):
    """Offline issues of an ASR set: every dialogue's audio (and segments) present, well-formed, hashes as built."""
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
        elif expected.get(name) != sha256(wav):
            issues.append({"code": "ASR_AUDIO_HASH", "set": set_id, "id": clip_id})
        segments = f"audio/{clip_id}.segments.json"
        if segments in expected and (not (path / segments).is_file() or sha256(path / segments) != expected[segments]):
            issues.append({"code": "ASR_SEGMENTS_INVALID", "set": set_id, "id": clip_id})
    if expected.get("ground_truth.json") != sha256(path / "ground_truth.json"):
        issues.append({"code": "ASR_GROUND_TRUTH_HASH", "set": set_id})
    return issues, len(ids)
