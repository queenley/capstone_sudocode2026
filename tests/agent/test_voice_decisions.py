import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.components.voice.policy import decide_turn
from ai_agent_service.components.voice.recognition import process
from ai_agent_service.api.routes.voice import Session


@pytest.mark.parametrize("text", ["Không!", "Dừng.", "Khoan", "Hủy", "thôi"])
def test_short_stop_commands_are_heard_while_the_assistant_speaks(text):
    result = decide_turn(text, busy=True, min_words=2)
    assert result.accepted and result.text == text


def test_echo_only_does_not_become_a_customer_turn_and_mixed_speech_preserves_correction():
    echo = "Dạ mẫu này có giá năm triệu hai trăm nghìn."
    assert not decide_turn(echo, busy=True, min_words=2, echo_text=echo).accepted
    mixed = echo + " Không, đổi sang mẫu khác."
    result = decide_turn(mixed, busy=True, min_words=2, echo_text=echo)
    assert result.accepted and result.text == "Không, đổi sang mẫu khác."
    assert decide_turn("giá 6 triệu đồng", busy=True, min_words=2, echo_text="giá 5 triệu đồng").text == "giá 6 triệu đồng"


def test_repeated_answer_is_not_removed_from_the_middle_and_short_answers_survive():
    assert decide_turn("Đúng rồi, lấy máy lọc không khí đó", busy=False, min_words=2,
                       echo_text="Anh lấy máy lọc không khí đó không?").accepted
    assert decide_turn("size 42", busy=True, min_words=2, echo_text="Anh lấy size 42 nhé").text == "size 42"
    assert decide_turn("máy lọc không khí", busy=True, min_words=2,
                       echo_text="Anh lấy máy lọc không khí này không?").text == "máy lọc không khí"
    assert decide_turn("vâng", busy=False, min_words=2).accepted
    assert not decide_turn("vâng", busy=True, min_words=2).accepted


def test_web_and_benchmark_share_recognition_and_keep_raw_hypotheses():
    dictionary = SimpleNamespace(correct=lambda text: (text.replace("liker", "Lite"), []))
    result = process("liker", lexicon=dictionary)
    assert result.raw_text == "liker" and result.corrected_text == result.agent_text == "Lite"


@pytest.mark.asyncio
async def test_voice_timer_never_confirms_an_interruption_from_vad_alone(monkeypatch):
    from ai_agent_service.api.routes import voice
    monkeypatch.setattr(voice.asyncio, "sleep", AsyncMock())
    session = Session.__new__(Session)
    session.paused, session.pause_generation, session.asr_pending = "t1", 2, 1
    session.settings = SimpleNamespace(false_interruption_ms=2500)
    session.detector = SimpleNamespace(in_turn=True)
    session.resume, session.stop_paused = AsyncMock(), AsyncMock()
    await session._false_interruption("t1", 1)
    session.resume.assert_not_awaited()
    await session._false_interruption("t1", 2)
    session.resume.assert_awaited_once()
    session.stop_paused.assert_not_awaited()


def test_echo_reference_only_contains_chunks_acknowledged_as_played():
    session = Session.__new__(Session)
    session.chunks = {"t1": [{"sentence": 0, "duration": 2}]}
    session.spoken = {"t1": ["Phần đã phát", "Phần chưa phát"]}
    session.playback_events = []
    session._played({"turn": "t1", "seq": 1}, 10)
    assert session.echo_window(10, 11) == ""
    session._played({"turn": "t1", "seq": 0}, 10)
    assert session.echo_window(10, 11) == "Phần đã phát"
    assert session.echo_window(30, 31) == ""


@pytest.mark.asyncio
async def test_barge_timer_waits_for_long_speech_and_pending_asr(monkeypatch):
    from ai_agent_service.api.routes import voice
    session = Session.__new__(Session)
    session.paused, session.pause_generation, session.asr_pending = 't1', 1, 1
    session.settings = SimpleNamespace(false_interruption_ms=1500)
    session.detector = SimpleNamespace(in_turn=True, config=SimpleNamespace(max_turn_s=30))
    calls = []
    async def sleep(seconds):
        calls.append(seconds)
        if len(calls) == 4:
            session.detector.in_turn = False
        if len(calls) == 6:
            session.asr_pending = 0
    async def resume():
        assert len(calls) >= 6 and not session.detector.in_turn and not session.asr_pending
    session.resume, session.stop_paused = AsyncMock(side_effect=resume), AsyncMock()
    monkeypatch.setattr(voice.asyncio, 'sleep', sleep)
    await session._false_interruption('t1', 1)
    session.resume.assert_awaited_once()
    session.stop_paused.assert_not_awaited()
