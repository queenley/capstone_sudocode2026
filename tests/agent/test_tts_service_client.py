"""The agent's side of apps/tts-service: TTS_URL makes vieneu: stream from it, as 16-bit PCM re-cut into wav chunks."""

import asyncio
import io
import wave

import httpx
import numpy as np
import pytest

from ai_agent_service.components.voice import tts

RATE = 24_000


@pytest.fixture
def service(monkeypatch):
    """A fake tts-service: one second of a tone, sent in uneven pieces, an odd byte included."""
    seen = {}
    pcm = (np.sin(np.arange(RATE) / 10) * 8000).astype("<i2").tobytes()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.setdefault("paths", []).append(request.url.path)
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"ready": True})
        seen["body"] = request.content
        pieces = [pcm[:3001], pcm[3001:20000], pcm[20000:]]

        async def body():
            for piece in pieces:
                yield piece

        return httpx.Response(200, headers={"X-Sample-Rate": str(RATE)}, content=body())

    monkeypatch.setenv("TTS_URL", "http://tts-service:8600/")
    monkeypatch.setattr(tts.RemoteVieNeuVoice, "_client",
                        httpx.AsyncClient(base_url="http://tts-service:8600", transport=httpx.MockTransport(handler)))
    yield seen
    monkeypatch.setattr(tts.RemoteVieNeuVoice, "_client", None)


def test_vieneu_goes_to_the_service_only_when_tts_url_is_set(monkeypatch):
    monkeypatch.delenv("TTS_URL", raising=False)
    assert isinstance(tts.voice("vieneu:"), tts.VieNeuVoice)
    monkeypatch.setenv("TTS_URL", "http://tts-service:8600")
    assert isinstance(tts.voice("vieneu:"), tts.RemoteVieNeuVoice)
    assert tts.voice("vieneu:").parallel is False
    assert tts.voices()[0]["name"] == "vieneu:"


def test_remote_stream_rebuilds_the_whole_audio_in_playable_chunks(service):
    voice = tts.voice("vieneu:")

    async def run():
        await voice.warm()
        return [speech async for speech in voice.stream("Dạ, máy còn hàng ạ.")]

    chunks = asyncio.run(run())
    assert b"m\\u00e1y" in service["body"] or "máy".encode() in service["body"]
    assert len(chunks) >= 2 and chunks[0].first_byte is not None
    total = 0
    for speech in chunks:
        with wave.open(io.BytesIO(speech.audio)) as audio:
            assert audio.getframerate() == RATE and audio.getsampwidth() == 2
            total += audio.getnframes()
    assert total == RATE  # no sample lost or cut in two
    assert sum(speech.duration for speech in chunks) == pytest.approx(1.0)


def test_a_service_that_is_not_ready_fails_the_warm_up(monkeypatch):
    monkeypatch.setenv("TTS_URL", "http://tts-service:8600")
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"ready": False}))
    monkeypatch.setattr(tts.RemoteVieNeuVoice, "_client", httpx.AsyncClient(base_url="http://x", transport=transport))
    async def speak():
        return [speech async for speech in tts.voice("vieneu:").stream("Dạ.")]

    with pytest.raises(RuntimeError, match="not ready"):
        asyncio.run(tts.voice("vieneu:").warm())
    with pytest.raises(RuntimeError, match="503"):
        asyncio.run(speak())
    monkeypatch.setattr(tts.RemoteVieNeuVoice, "_client", None)
