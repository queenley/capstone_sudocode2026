"""Who spoke when, in BTC's labels: ``A`` the shop agent, ``C`` the customer.

BTC scores ``diarization_turn_accuracy`` by finding, for each true segment (``audio/<id>.segments.json``), the
hypothesis turn that contains its midpoint and comparing the speaker. A dialogue set therefore needs a diarizer:

- ``native``: the engine returns speaker segments itself (``openai:gpt-4o-transcribe-diarize``, or a hypotheses file
  with ``turns``);
- ``sherpa``: a CPU diarizer (:mod:`.sherpa`: pyannote segmentation 3.0 + a speaker embedding, sherpa-onnx;
  ``pip install sherpa-onnx`` and the two models' paths), each segment then heard by the engine.

Anonymous speakers become roles as BTC's dialogues are recorded: the shop answers the phone, so the first speaker is
``A`` and anyone else ``C``. The agent itself never diarizes: on a real call it hears only the caller's channel.
"""
from __future__ import annotations

from pathlib import Path

from src.services.asr import sherpa

#: Neighbouring segments of one role closer than this (seconds) are one turn (as data-generation's diarizer).
MERGE_GAP = 0.6


def roles(segments: list[dict]) -> list[dict]:
    """Engine segments (any speaker labels) → BTC turns: first speaker ``A``, others ``C``; one role's neighbours merged."""
    ordered = sorted(segments, key=lambda s: s["start"])
    first = ordered[0]["speaker"] if ordered else None
    turns: list[dict] = []
    for segment in ordered:
        role = "A" if segment["speaker"] == first else "C"
        if turns and turns[-1]["speaker"] == role and segment["start"] - turns[-1]["end"] <= MERGE_GAP:
            turns[-1]["end"] = max(turns[-1]["end"], segment["end"])
            turns[-1]["text"] = (turns[-1]["text"] + " " + segment["text"]).strip()
        else:
            turns.append({"speaker": role, "start": round(segment["start"], 2), "end": round(segment["end"], 2),
                          "text": segment["text"].strip()})
    return turns


class Native:
    name = "native"

    def turns(self, samples, engine, clip_id):
        heard = engine.hear(samples, clip_id)
        if "segments" not in heard:
            raise ValueError(f"{engine.name} returned no speaker segments for {clip_id}")
        return roles(heard["segments"]), heard


class Sherpa:
    name = "sherpa"

    def __init__(self, segmentation: Path, embedding: Path) -> None:
        self.module = sherpa
        try:
            self.diarizer = self.module.Diarizer(Path(segmentation), Path(embedding))
        except ImportError as exc:
            raise RuntimeError("sherpa diarization needs `pip install sherpa-onnx` in the agent's venv") from exc

    def turns(self, samples, engine, clip_id):
        seconds = 0.0
        heard = {"seconds": 0.0, "audio_seconds": round(len(samples) / 16_000, 3)}

        def transcribe(piece):
            nonlocal seconds
            result = engine.hear(piece, clip_id)
            seconds += result.get("seconds") or 0
            return result["text"]

        turns = self.module.diarize(samples, self.diarizer, transcribe)
        heard.update(seconds=round(seconds, 3), text=" ".join(t["text"] for t in turns))
        return turns, heard


def choose(name: str, engine, *, segmentation=None, embedding=None):
    """The diarizer *name* asks for; ``auto`` is the engine's own when it has one, else none."""
    if name == "auto":
        return Native() if engine.diarizes else None
    if name == "none":
        return None
    if name == "native":
        if not engine.diarizes:
            raise ValueError(f"{engine.name} does not diarize; use openai:gpt-4o-transcribe-diarize or --diarizer sherpa")
        return Native()
    if name == "sherpa":
        if not (segmentation and embedding):
            raise ValueError("--diarizer sherpa needs --segmentation and --embedding (the two ONNX models)")
        return Sherpa(segmentation, embedding)
    raise ValueError(f"Unknown --diarizer {name!r}: auto, native, sherpa or none")
