"""Optional waveform denoising: no native dependency or provider in offline tests."""
from pathlib import Path
from types import SimpleNamespace
import ctypes

import numpy as np
import pytest


@pytest.fixture
def dn(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'apps/asr-service/src'))
    from asr_service import denoise
    return denoise


def test_off_is_identity_and_does_not_load_library(dn, monkeypatch):
    monkeypatch.setattr(dn, 'library', lambda: pytest.fail('off must not load a neural model'))
    signal = np.linspace(-.5, .5, 107, dtype=np.float32)
    assert dn.process(signal) is signal
    assert dn.metadata('none')['name'] == 'none'


@pytest.mark.parametrize('samples', [[], [[0.]], [np.nan], [np.inf]])
def test_bad_audio_rejected(dn, samples):
    with pytest.raises(ValueError): dn.process(np.array(samples), 'rnnoise')


def test_unknown_option_never_silently_falls_back(dn):
    with pytest.raises(ValueError): dn.process(np.zeros(20), 'typo')


@pytest.mark.parametrize('size', [1, 159, 160, 161, 1600])
def test_framing_flush_preserves_tail_length_scale_and_state_isolation(dn, monkeypatch, size):
    class Delayed:
        allocated = closed = 0
        states = {}
        def rnnoise_create(self, _):
            self.allocated += 1
            self.states[self.allocated] = np.zeros(480, np.float32)
            return self.allocated
        def rnnoise_process_frame(self, state, out, frame):
            source = np.ctypeslib.as_array(frame, shape=(480,)).copy()
            assert np.max(np.abs(source)) <= 32767
            np.ctypeslib.as_array(out, shape=(480,))[:] = self.states[state]
            self.states[state] = source
        def rnnoise_destroy(self, state):
            self.closed += 1
            del self.states[state]
    lib = Delayed()
    monkeypatch.setattr(dn, 'library', lambda: (lib, 'fixture-sha'))
    signal = np.ones(size, np.float32) * .2
    out = dn.process(signal, 'rnnoise')
    assert out.shape == signal.shape and out.dtype == np.float32 and np.isfinite(out).all()
    import soxr
    expected = soxr.resample(soxr.resample(signal, 16000, 48000, quality="HQ"), 48000, 16000, quality="HQ")
    assert np.max(np.abs(out - expected)) < 1e-6
    assert np.max(np.abs(dn.process(np.zeros(size, np.float32), 'rnnoise'))) == 0
    assert lib.allocated == lib.closed == 2 and not lib.states


def test_state_released_if_native_processing_fails(dn, monkeypatch):
    released = []
    def fail(*args): raise RuntimeError('fixture')
    lib = SimpleNamespace(rnnoise_create=lambda _: 1, rnnoise_destroy=released.append, rnnoise_process_frame=fail)
    monkeypatch.setattr(dn, 'library', lambda: (lib, 'fixture-sha'))
    with pytest.raises(RuntimeError): dn.process(np.zeros(160), 'rnnoise')
    assert released == [1]


def test_recognizer_includes_denoise_cost_and_passes_only_processed_audio(dn, monkeypatch):
    from asr_service import engines
    monkeypatch.setattr(engines, 'load', lambda _: 0)
    monkeypatch.setattr(dn, 'metadata', lambda _: {'name': 'rnnoise', 'library_sha256': 'fixture'})
    monkeypatch.setattr(dn, 'process', lambda samples, name: samples * .5)
    def decoder(name, samples, words):
        assert np.max(samples) == .5
        return engines.Transcript(name, 'xin chào', .1, len(samples)/16000)
    monkeypatch.setattr(engines, 'transcribe', decoder)
    got = engines.recognize('fixture', np.ones(16000, np.float32), denoiser='rnnoise')
    assert got.seconds >= .1 and got.decoder_seconds == .1 and got.preprocessing['name'] == 'rnnoise'


def test_http_option_reaches_shared_recognizer_and_default_stays_off(dn, monkeypatch):
    from asr_service import main, engines
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, 'API_KEY', '')
    monkeypatch.setattr(dn, 'metadata', lambda name: {'name': name})
    loaded = []
    monkeypatch.setattr(engines, 'load', lambda model: loaded.append(model) or 0)
    seen = []
    def recognize(model, samples, words, *, denoiser):
        seen.append((model, denoiser))
        return engines.Transcript(model, 'ok', .2, len(samples)/16000, .1, .1, {'name': denoiser})
    monkeypatch.setattr(engines, 'recognize', recognize)
    client = TestClient(main.app)
    audio = np.zeros(16000, '<f4').tobytes()
    assert client.post('/v1/transcribe?denoiser=rnnoise', content=audio).json()['preprocessing']['name'] == 'rnnoise'
    assert client.post('/v1/transcribe', content=audio).status_code == 200
    assert client.post('/v1/transcribe?denoiser=typo', content=audio).status_code == 422
    assert seen == [('zipformer-30m', 'rnnoise'), ('zipformer-30m', 'none')]
    with client.websocket_connect('/v1/stream') as ws:
        ws.send_json({'denoiser':'rnnoise'})
        # Configuration checks optional dependencies before accepting audio.
        assert ws.receive_json()['type'] == 'ready'
        ws.send_bytes(audio)
        ws.send_json({'type':'end'})
        frame = ws.receive_json()
        if frame['type'] == 'partial': frame = ws.receive_json()
        assert frame['preprocessing']['name'] == 'rnnoise'
    assert loaded == ['zipformer-30m']


def test_websocket_rejects_missing_weights_before_accepting_audio(dn, monkeypatch):
    from asr_service import main, engines
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setattr(main, 'API_KEY', '')
    def missing(model):
        raise FileNotFoundError('private-model-path')
    monkeypatch.setattr(engines, 'load', missing)
    monkeypatch.setattr(dn, 'metadata', lambda _: pytest.fail('weights must be ready first'))
    with TestClient(main.app).websocket_connect('/v1/stream') as ws:
        ws.send_json({'denoiser': 'rnnoise'})
        frame = ws.receive_json()
        assert frame['type'] == 'error' and 'private-model-path' not in frame['text']
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4400


@pytest.mark.parametrize('preprocessing,denoise_seconds,decoder_seconds', [
    (None, .1, .1), ({'name':'none'}, .1, .1), ({'name':'rnnoise'}, None, .1),
    ({'name':'rnnoise'}, .1, float('nan')), ({'name':'rnnoise'}, -.1, .1),
])
def test_remote_cannot_claim_enhancement_without_matching_metadata_and_timings(monkeypatch, preprocessing, denoise_seconds, decoder_seconds):
    from ai_agent_service.components.voice import asr
    monkeypatch.setenv('ASR_URL','http://localhost:8500')
    result = {'model':'zipformer-30m','text':'ok','seconds':.2,'audio_seconds':1,
              'preprocessing':preprocessing,'denoise_seconds':denoise_seconds,'decoder_seconds':decoder_seconds}
    client = SimpleNamespace(post=lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: result))
    monkeypatch.setattr(asr,'_http',lambda:client)
    with pytest.raises(RuntimeError):
        asr.transcribe('zipformer-30m',np.zeros(16000,np.float32),denoiser='rnnoise')


def test_optional_dependency_failure_is_explicit_http_error(dn, monkeypatch):
    from asr_service import main,engines
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main,'API_KEY','')
    monkeypatch.setattr(engines,'load',lambda _:0)
    def unavailable(*args): raise RuntimeError('fixture missing optional library')
    monkeypatch.setattr(dn,'metadata',unavailable)
    response=TestClient(main.app).post('/v1/transcribe?denoiser=rnnoise',content=np.zeros(16000,'<f4').tobytes())
    assert response.status_code==503 and 'fixture missing' not in response.text
