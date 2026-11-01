import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.api.routes import voice


@pytest.mark.asyncio
@pytest.mark.parametrize("hello", ['[]', 'not JSON', '{"sample_rate":"NaN"}', '{"sample_rate":-1}',
                                  '{"sample_rate":999999999}', 'x' * (256 * 1024 + 1)])
async def test_invalid_voice_handshakes_close_before_identity_or_model_work(hello, monkeypatch):
    authorize = AsyncMock()
    monkeypatch.setattr(voice.platform, "authorize", authorize)
    ws = SimpleNamespace(accept=AsyncMock(), receive_text=AsyncMock(return_value=hello), close=AsyncMock())
    await voice.voice_call(ws, "fixture")
    ws.close.assert_awaited_once_with(code=1008)
    authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_close_waits_for_cancelled_tasks_before_releasing_the_call(monkeypatch):
    entered = asyncio.Event()
    stopped = []
    async def running():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            stopped.append(True)
    task = asyncio.create_task(running())
    await entered.wait()
    async def end(call_id): assert stopped and call_id == 1
    monkeypatch.setattr(voice.calls, "hang_up", end)
    session = voice.Session.__new__(voice.Session)
    session.tasks, session.recording, session.hung_up, session.call_id = {task}, [], False, 1
    await session.close()
    assert task.done() and session.hung_up


def test_voice_control_rejects_missing_fields_negative_indexes_and_nonfinite_times():
    valid = {"type": "playback_stopped", "turn": "t1", "seq": 0, "played_ms": 100, "duration_ms": 200}
    assert voice.valid_control(valid)
    for message in ([], {}, {"type": "playback_started"}, {**valid, "seq": -1}, {**valid, "played_ms": "NaN"},
                    {**valid, "duration_ms": 0}, {**valid, "seq": True}):
        assert not voice.valid_control(message)


@pytest.mark.asyncio
async def test_client_cannot_truncate_a_turn_this_socket_never_played():
    session = voice.Session.__new__(voice.Session)
    session.timings = {}
    session.truncated = AsyncMock()
    await session.control({"type": "playback_stopped", "turn": "other"})
    session.truncated.assert_not_awaited()
