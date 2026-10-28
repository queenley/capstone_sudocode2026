"""Roles, merging and per-turn recognition of the diarization step; no model."""
import numpy as np

from src.services.asr.sherpa import Segment, label_roles, merge, turns


def seg(a, b, s):
    return Segment(a, b, s)


def test_the_first_speaker_is_the_agent_and_anyone_else_the_customer():
    labelled = label_roles([seg(5, 8, 1), seg(0, 4, 0), seg(9, 12, 0)])
    assert [(s.start, r) for s, r in labelled] == [(0, "A"), (5, "C"), (9, "A")]


def test_a_recording_with_one_cluster_takes_the_single_role():
    assert {r for _, r in label_roles([seg(0, 3, 4), seg(4, 7, 4)])} == {"C"}
    assert {r for _, r in label_roles([seg(0, 3, 4)], single="A")} == {"A"}


def test_a_speakers_neighbouring_pieces_join_across_a_short_gap_only():
    labelled = [(seg(0, 2, 0), "A"), (seg(2.4, 4, 0), "A"), (seg(5.5, 7, 0), "A"), (seg(7.2, 9, 1), "C")]
    assert merge(labelled) == [(0, 4, "A"), (5.5, 7, "A"), (7.2, 9, "C")]


def test_pieces_too_short_to_be_a_turn_are_dropped():
    assert merge([(seg(0, 0.1, 0), "A"), (seg(1, 3, 1), "C")]) == [(1, 3, "C")]


def test_each_turn_is_recognised_on_its_own_audio():
    audio = np.arange(16_000 * 10, dtype="float32")
    heard = []

    def fake(piece):
        heard.append((piece[0], len(piece)))
        return f"{len(piece) // 16_000}s"

    out = turns(audio, [(1.0, 3.0, "A"), (4.0, 7.0, "C")], fake)
    assert out == [{"speaker": "A", "start": 1.0, "end": 3.0, "text": "2s"},
                   {"speaker": "C", "start": 4.0, "end": 7.0, "text": "3s"}]
    assert heard[0][0] == 16_000.0
