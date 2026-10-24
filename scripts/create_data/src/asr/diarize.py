"""Speaker diarization for the M2 ASR test: who spoke when, in BTC's ``A``/``C`` labels.

BTC scores ``diarization_turn_accuracy`` by looking up, for each ground-truth segment, the hypothesis turn that
contains its midpoint and comparing ``speaker`` with the segment's ``A`` (agent) or ``C`` (customer). So the
hypothesis needs ``turns`` with ``start``/``end``/``speaker``/``text``.

Recognisers such as the agent's Zipformer give text without segments, and a diariser gives anonymous clusters
(``0``, ``1``). This module joins them:

1. :class:`Diarizer` cuts the recording into speaker segments (sherpa-onnx: pyannote segmentation 3.0 and a
   speaker embedding model, both CPU-only ONNX, so it runs where the agent's ASR runs).
2. :func:`label_roles` turns clusters into ``A``/``C``. In BTC dialogues the shop answers the phone first
   ("dạ shop ... xin nghe"), so the first speaker is ``A``; every other cluster is ``C``. A recording with one
   cluster is all ``A`` or all ``C`` by ``single`` (the per-turn customer clips of the team set are ``C``).
3. :func:`merge` joins a speaker's neighbouring segments across short gaps.
4. :func:`turns` recognises each segment and returns BTC's ``turns`` list.

The models are not in the repository: ``--segmentation`` and ``--embedding`` of ``eval_asr`` name them.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

SAMPLE_RATE = 16_000
#: Neighbouring segments of one speaker closer than this (seconds) are one turn.
MERGE_GAP = 0.6
#: Shorter pieces are back-channel or noise, not a turn.
MIN_TURN = 0.3


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    speaker: int


class Diarizer:
    """sherpa-onnx offline diarization with a known number of speakers (a call has two)."""

    def __init__(self, segmentation: Path, embedding: Path, *, num_speakers: int = 2, threads: int = 2) -> None:
        import sherpa_onnx

        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
                num_threads=threads),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=threads),
            clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers, threshold=0.5),
            min_duration_on=0.2, min_duration_off=0.4)
        if not config.validate():
            raise ValueError("The diarization models could not be loaded")
        self._diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
        if self._diarizer.sample_rate != SAMPLE_RATE:
            raise ValueError(f"The diariser expects {self._diarizer.sample_rate} Hz")

    def segments(self, samples: np.ndarray) -> list[Segment]:
        result = self._diarizer.process(samples).sort_by_start_time()
        return [Segment(float(r.start), float(r.end), int(r.speaker)) for r in result]


def label_roles(segments: Sequence[Segment], *, single: str = "C") -> list[tuple[Segment, str]]:
    """BTC roles: the speaker heard first is the agent ``A``, anyone else the customer ``C``."""
    ordered = sorted(segments, key=lambda s: s.start)
    clusters = list(dict.fromkeys(s.speaker for s in ordered))
    if len(clusters) < 2:
        return [(s, single) for s in ordered]
    return [(s, "A" if s.speaker == clusters[0] else "C") for s in ordered]


def merge(labelled: Sequence[tuple[Segment, str]], *, gap: float = MERGE_GAP, minimum: float = MIN_TURN) -> list[tuple[float, float, str]]:
    """Adjacent pieces of one role, closer than *gap*, become one turn; pieces under *minimum* are dropped."""
    turns: list[list] = []
    for segment, role in labelled:
        if segment.end - segment.start < minimum:
            continue
        if turns and turns[-1][2] == role and segment.start - turns[-1][1] <= gap:
            turns[-1][1] = max(turns[-1][1], segment.end)
        else:
            turns.append([segment.start, segment.end, role])
    return [(a, b, role) for a, b, role in turns]


def turns(samples: np.ndarray, merged: Sequence[tuple[float, float, str]],
          transcribe: Callable[[np.ndarray], str]) -> list[dict]:
    """BTC's ``turns``: each merged span recognised on its own, so every turn has its speaker and its words."""
    out = []
    for start, end, role in merged:
        piece = samples[int(start * SAMPLE_RATE): int(end * SAMPLE_RATE)]
        out.append({"speaker": role, "start": round(start, 2), "end": round(end, 2), "text": transcribe(piece)})
    return out


def diarize(samples: np.ndarray, diarizer: Diarizer, transcribe: Callable[[np.ndarray], str], *, single: str = "C") -> list[dict]:
    """The whole path: cut, label, merge, recognise."""
    return turns(samples, merge(label_roles(diarizer.segments(samples), single=single)), transcribe)
