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


@pytest.mark.asyncio
async def test_gemini_voice_streams_its_pcm_as_small_wav_chunks_and_is_offered_with_a_google_key(monkeypatch):
    import base64
    import json

    import httpx

    from ai_agent_service.components.voice import tts

    pcm = b"\x01\x00" * tts.OPENAI_PCM_RATE  # one second of 24 kHz pcm, sent in two events
    events = "".join(f"data: {json.dumps({'candidates': [{'content': {'parts': [{'inlineData': {'mimeType': 'audio/L16;codec=pcm;rate=24000', 'data': base64.b64encode(half).decode()}}]}}]})}\n\n"
                     for half in (pcm[:len(pcm) // 2], pcm[len(pcm) // 2:]))
    seen = {}

    def answer(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(200, text=events)

    monkeypatch.setattr(tts.GeminiVoice, "_client", httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    chunks = [speech async for speech in tts.voice("gemini:Leda").stream("Dạ em chào chị.")]
    assert "gemini-3.8-flash-lite-tts:streamGenerateContent" in seen["url"] and "alt=sse" in seen["url"]
    assert seen["body"]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Leda"
    assert len(chunks) == 4 and all(c.mime == "audio/wav" for c in chunks)
    assert abs(sum(c.duration for c in chunks) - 1.0) < 1e-6
    monkeypatch.setattr("ai_agent_service.config.config_manager.has_api_key", lambda provider: provider == "google_genai")
    assert "gemini:Kore" in {v["name"] for v in tts.voices()}



@pytest.mark.asyncio
async def test_remote_voice_reads_the_rate_the_server_names_and_sends_quarter_second_wav_chunks(monkeypatch):
    import json

    import httpx

    from ai_agent_service.components.voice import tts

    seen = {}

    def answer(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(200, content=b"\x01\x00" * 48_000, headers={"X-Sample-Rate": "48000"})

    monkeypatch.setattr(tts.RemoteVoice, "_client", httpx.AsyncClient(transport=httpx.MockTransport(answer),
                                                                      base_url="http://tts"))
    chunks = [speech async for speech in tts.voice("remote:zerotts:maichi").stream("Dạ em chào chị.")]
    assert seen == {"path": "/v1/tts", "body": {"engine": "zerotts", "text": "Dạ em chào chị.", "voice": "maichi"}}
    assert len(chunks) == 4 and abs(sum(c.duration for c in chunks) - 1.0) < 1e-6
    monkeypatch.setenv("TTS_URL", "https://tts.example")
    assert "remote:zerotts" in {v["name"] for v in tts.voices()}


def test_a_voice_reads_two_words_joined_by_a_slash_as_two_words_and_keeps_numbers_and_units():
    """2026-11-19: VieNeu read "anh/chị" as "anh trên chị"."""
    from ai_agent_service.components.voice.tts import for_voice

    assert for_voice("Dạ xin chào anh/chị. Anh/chị cần gì ạ?") == "Dạ xin chào anh chị. Anh chị cần gì ạ?"
    assert for_voice("Tốc độ 30 km/h, giảm 1/2 giá") == "Tốc độ 30 km h, giảm 1/2 giá"
