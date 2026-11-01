import asyncio
import json

import numpy as np
import pytest

from ai_agent_service.components.voice import asr


class Socket:
    def __init__(self, frames):
        self.frames = frames
        self.sent = []
    async def send(self, value): self.sent.append(value)
    async def recv(self): return '{"type":"ready"}'
    def __aiter__(self):
        async def frames():
            for frame in self.frames:
                yield frame
        return frames()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [["bad json"], ["[]"], [], ['{"type":"error","text":"private"}']])
async def test_stream_disconnect_or_invalid_frames_fail_without_hanging(monkeypatch, frames):
    import websockets
    socket = Socket(frames)
    monkeypatch.setenv("ASR_URL", "http://127.0.0.1:8500")
    monkeypatch.setattr(websockets, "connect", lambda *args, **kwargs: socket)
    async def chunks():
        yield np.zeros(100, dtype=np.float32)
    async def consume():
        return [item async for item in asr.stream("fixture", chunks())]
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(consume(), .5)


@pytest.mark.asyncio
async def test_stream_yields_final_and_cleans_up_an_unfinished_sender(monkeypatch):
    import websockets
    socket = Socket(['{"type":"partial","text":"xin"}', '{"type":"final","text":"xin chào"}'])
    monkeypatch.setenv("ASR_URL", "http://127.0.0.1:8500")
    monkeypatch.setattr(websockets, "connect", lambda *args, **kwargs: socket)
    closed = []
    async def chunks():
        try:
            yield np.zeros(100, dtype=np.float32)
            await asyncio.Event().wait()
        finally:
            closed.append(True)
    rows = [item async for item in asr.stream("fixture", chunks())]
    assert [item["type"] for item in rows] == ["partial", "final"]
    assert closed


@pytest.mark.parametrize('changes', [{'model': 'other'}, {'seconds': float('nan')}, {'audio_seconds': 9}, {'text': []}])
def test_http_asr_response_must_match_model_audio_and_finite_schema(monkeypatch, changes):
    from types import SimpleNamespace
    monkeypatch.setenv('ASR_URL', 'http://127.0.0.1:8500')
    payload = {'model': 'fixture', 'text': 'xin chào', 'seconds': .1, 'audio_seconds': 1, **changes}
    response = SimpleNamespace(status_code=200, json=lambda: payload)
    monkeypatch.setattr(asr, '_http', lambda: SimpleNamespace(post=lambda *args, **kwargs: response))
    with pytest.raises(RuntimeError, match='does not match'):
        asr.transcribe('fixture', np.zeros(16000, dtype=np.float32))


def test_asr_http_pool_avoids_ambient_proxy_and_closes_once(monkeypatch):
    import httpx
    from types import SimpleNamespace
    created, closed = [], []
    def factory(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(asr, '_client', None)
    monkeypatch.setattr(httpx, 'Client', factory)
    assert asr._http() is asr._http()
    assert created[0]['trust_env'] is False
    asr.close()
    asr.close()
    assert closed == [True]
