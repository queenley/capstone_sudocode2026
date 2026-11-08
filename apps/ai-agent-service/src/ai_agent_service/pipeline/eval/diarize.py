"""Who spoke when in a recorded call, so ASR hypotheses can carry the organisers' ``turns[]``.

The organisers score ``entity_accuracy_per_turn`` by matching each reference turn to the hypothesis turn
with the same ``idx``, and diarization from each turn's ``speaker``/``start``/``end``. A reference turn is one
speaker's turn (A agent, C customer), so turns come from speaker diarization, not from pauses:
sherpa-onnx with pyannote segmentation 3.0 and a 3D-Speaker ERes2Net embedding, two speakers per call.

Which cluster is the agent is read from the words each one said (agents say "dạ ... ạ", "bên em",
"shop"; customers "chị muốn", "em ơi", "alo"). A split that does not look like a call (one speaker, a
single turn, more turns than people take) gives no turns at all: wrong turns score worse than none.
Weights are fetched explicitly (``apps/asr-service/models/diarization``); inference never downloads.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

VERSION = "turns-pyannote3-eres2net-v2"
SEGMENTATION = Path("diarization/sherpa-onnx-pyannote-segmentation-3-0/model.onnx")
EMBEDDING = Path("diarization/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")
RATE = 16000
#: Speech shorter than this is a backchannel or noise, not a turn; a pause shorter than this does not end one.
MIN_SPEECH, MIN_PAUSE = 0.3, 0.5
#: People in a call take at most about one turn every two seconds. Fewer than six a minute, or fewer than
#: three in all, is two voices merged into one (two similar voices on montage calls: 2-3 turns in 25 s).
MAX_TURNS_PER_MINUTE, MIN_TURNS_PER_MINUTE, MIN_TURNS = 30, 6, 3

AGENT_CUES = re.compile(r"\bdạ\b|\bạ\b|\bbên em\b|\bshop\b|\bem (?:xin|gợi ý|kiểm tra|xác nhận|ghi nhận|gửi|chào)\b|"
                        r"\bmình\b|\bquý khách\b|\bem có thể giúp\b")
CUSTOMER_CUES = re.compile(r"\balo\b|\bem ơi\b|\b(?:chị|anh|cô|chú|tôi) (?:muốn|cần|hỏi|thấy|định|lấy|đặt|mua)\b|"
                           r"\bcho (?:chị|anh|cô|chú|tôi)\b|\bbao nhiêu\b")


def _models_dir() -> Path:
    from ...components.voice import asr
    return Path(asr._engines().models_dir())


def available() -> bool:
    try:
        directory = _models_dir()
    except Exception:
        return False
    return (directory / SEGMENTATION).is_file() and (directory / EMBEDDING).is_file()


@lru_cache(maxsize=1)
def _diarizer():
    import sherpa_onnx

    directory = _models_dir()
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(directory / SEGMENTATION)),
            num_threads=2),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(directory / EMBEDDING), num_threads=2),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=2),
        min_duration_on=MIN_SPEECH, min_duration_off=MIN_PAUSE)
    if not config.validate():
        raise RuntimeError("Invalid speaker diarization configuration")
    return sherpa_onnx.OfflineSpeakerDiarization(config)


def speaker_spans(samples) -> list[tuple[float, float, int]]:
    """(start, end, cluster) of each stretch of speech, in seconds, sorted by start."""
    import numpy as np

    result = _diarizer().process(np.asarray(samples, dtype=np.float32)).sort_by_start_time()
    return [(float(item.start), float(item.end), int(item.speaker)) for item in result]


def turns(spans: list[tuple[float, float, int]]) -> list[dict[str, Any]]:
    """Consecutive spans of one cluster are one turn; speech shorter than ``MIN_SPEECH`` is dropped."""
    out: list[dict[str, Any]] = []
    for start, end, cluster in spans:
        if end - start < MIN_SPEECH:
            continue
        if out and out[-1]["cluster"] == cluster:
            out[-1]["end"] = max(out[-1]["end"], end)
            continue
        out.append({"start": round(start, 2), "end": round(end, 2), "cluster": cluster})
    for idx, turn in enumerate(out, start=1):
        turn["idx"] = idx
    return out


def label_speakers(found: list[dict[str, Any]]) -> dict[int, str]:
    """Cluster -> "A" (agent) or "C" (customer), by the words each cluster said; the first speaker is A on a tie."""
    clusters = list(dict.fromkeys(turn["cluster"] for turn in found))
    def lean(cluster: int) -> int:
        text = " ".join(turn.get("text", "") for turn in found if turn["cluster"] == cluster).lower()
        return len(AGENT_CUES.findall(text)) - len(CUSTOMER_CUES.findall(text))
    if len(clusters) < 2:
        return {cluster: "A" for cluster in clusters}
    first, second = clusters[0], clusters[1]
    agent = second if lean(second) > lean(first) else first
    return {cluster: ("A" if cluster == agent else "C") for cluster in clusters}


def plausible(found: list[dict[str, Any]], audio_seconds: float) -> str | None:
    """None when *found* looks like a two-person call; otherwise why its turns must not be submitted."""
    if len({turn["cluster"] for turn in found}) < 2:
        return "one speaker"
    if len(found) < MIN_TURNS:
        return "fewer than three turns"
    rate = len(found) / (audio_seconds / 60) if audio_seconds > 0 else 0
    if rate > MAX_TURNS_PER_MINUTE:
        return "more turns per minute than a call has"
    if audio_seconds > 0 and rate < MIN_TURNS_PER_MINUTE:
        return "fewer turns per minute than a call has: voices merged"
    return None
