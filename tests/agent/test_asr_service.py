from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import numpy as np
import pytest


@pytest.fixture
def service(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "apps/asr-service/src"))
    from asr_service import main
    monkeypatch.setattr(main, "API_KEY", "")
    def transcribe(model, samples, hotwords):
        return SimpleNamespace(model=model, text="xin chào", seconds=.01, audio_seconds=len(samples) / 16000, rtf=.1)
    monkeypatch.setattr(main.engines, "load", lambda _: 0)
    monkeypatch.setattr(main.engines, "transcribe", transcribe)
    # No lifespan: real model preload/fetch is forbidden in this fixture.
    return main, TestClient(main.app)


@pytest.mark.parametrize("body", [b"", b"x", np.array([np.nan], dtype="<f4").tobytes(),
                                  np.array([np.inf], dtype="<f4").tobytes()])
def test_bad_pcm_rejected_before_decode(service, body):
    _, client = service
    assert client.post("/v1/transcribe", content=body).status_code == 400


def test_asr_http_and_stream_contract_use_the_same_fake_recognizer(service):
    main, client = service
    audio = np.zeros(16000, dtype="<f4").tobytes()
    assert client.post("/v1/transcribe", content=audio).json()["text"] == "xin chào"
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_json({"model": "zipformer-30m", "sample_rate": 16000})
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(audio)
        ws.send_json({"type": "end"})
        result = ws.receive_json()
        if result["type"] == "partial": result = ws.receive_json()
        assert result["type"] == "final" and result["text"] == "xin chào"


def test_stream_reset_invalidates_prior_partial_generation(service):
    main, _ = service
    stream = main.Stream("fixture", 16000, [], 600)
    stream.add(np.zeros(512, dtype="<f4").tobytes())
    generation = stream.generation
    stream.reset()
    assert stream.generation == generation + 1 and stream.audio().size == 0


def test_stream_flushes_resampler_tail_and_reset_clears_previous_turn(service):
    main, _ = service
    stream = main.Stream('fixture', 8000, [], 600)
    stream.add(np.ones(8000, dtype='<f4').tobytes())
    assert stream.finish().shape == (16000,)
    stream.reset()
    stream.add(np.zeros(8000, dtype='<f4').tobytes())
    assert np.max(np.abs(stream.finish())) == 0


def test_model_errors_and_unknown_artifact_are_explicit(service, monkeypatch):
    main, client = service
    def missing(*args):
        raise FileNotFoundError('private path')
    monkeypatch.setattr(main.engines, 'transcribe', missing)
    result = client.post('/v1/transcribe', content=np.zeros(512, dtype='<f4').tobytes())
    assert result.status_code == 409 and 'private path' not in result.text
    assert client.get('/v1/models/unknown/artifact').status_code == 404


def test_http_and_websocket_defaults_are_zipformer_greedy(service):
    _, client = service
    audio = np.zeros(16000, dtype='<f4').tobytes()
    assert client.post('/v1/transcribe', content=audio).json()['model'] == 'zipformer-30m'
    with client.websocket_connect('/v1/stream') as ws:
        ws.send_json({'sample_rate': 16000})
        assert ws.receive_json()['model'] == 'zipformer-30m'
