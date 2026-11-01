from pathlib import Path
import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'apps/asr-service/src'))
    from asr_service import artifacts, engines, fetch
    return artifacts, engines, fetch


def test_receipt_detects_partial_and_corrupt_downloads(tmp_path, modules):
    artifacts, _, _ = modules
    assert not artifacts.verify(tmp_path)
    weights = tmp_path / 'model.bin'
    weights.write_bytes(b'weights')
    artifacts.receipt(tmp_path, [{'repo': 'test', 'revision': 'fixed'}])
    assert artifacts.verify(tmp_path)
    weights.write_bytes(b'changed')
    assert not artifacts.verify(tmp_path)


def test_empty_model_folder_is_not_advertised_or_loaded(tmp_path, modules, monkeypatch):
    _, engines, _ = modules
    monkeypatch.setattr(engines, 'models_dir', lambda: tmp_path)
    (tmp_path / engines.CATALOG['phowhisper-small'][2]).mkdir()
    assert not engines.available()
    with pytest.raises(FileNotFoundError, match='Incomplete'):
        engines.load('phowhisper-small')


def test_explicit_fetch_selection_never_downloads_other_models(modules, monkeypatch):
    _, _, fetch = modules
    selected = []
    monkeypatch.setattr(fetch, 'fetch_model', selected.append)
    monkeypatch.setenv('ASR_FETCH_MODELS', 'viegem,zipformer-30m,phowhisper-small,viegem')
    fetch.fetch_all(turbo=False)
    assert selected == ['viegem', 'zipformer-30m', 'phowhisper-small']


def test_whisper_is_deterministic_and_never_fetches_at_inference(modules, monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    import numpy as np
    _, engines, _ = modules
    kwargs = {}
    class Model:
        def __init__(self, path, **options):
            assert options['local_files_only'] is True
        def transcribe(self, samples, **options):
            kwargs.update(options)
            return iter([SimpleNamespace(text='xin chào')]), None
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    engine = engines.FasterWhisper(tmp_path)
    assert engine.transcribe(np.zeros(16000, dtype=np.float32), []) == 'xin chào'
    assert kwargs['temperature'] == 0 and kwargs['beam_size'] == 1 and not kwargs['condition_on_previous_text']
    assert engines.CATALOG['zipformer-30m'][2] == engines.CATALOG['zipformer-30m-beam4'][2]


def test_default_phowhisper_download_uses_no_torch_conversion(modules, monkeypatch, tmp_path):
    _, engines, fetch = modules
    monkeypatch.setattr(fetch, 'models_dir', lambda: tmp_path)
    snapshots = []
    def snapshot(repo, revision, target, patterns):
        snapshots.append(repo)
        target.mkdir(parents=True, exist_ok=True)
        for pattern in patterns:
            (target / pattern).write_bytes(b'fixture')
    monkeypatch.setattr(fetch, '_snapshot', snapshot)
    # This test environment intentionally has no Torch/Transformers/ctranslate2 dependency.
    fetch.fetch_model('phowhisper-small')
    assert snapshots == ['diepho/PhoWhisper-small-ct2', 'vinai/PhoWhisper-small']
    assert (tmp_path / 'phowhisper-small/tokenizer.json').is_file()
    assert fetch.artifacts.verify(tmp_path / 'phowhisper-small')


def test_concurrent_downloads_publish_once_on_a_shared_volume(modules, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import time
    _, _, fetch = modules
    monkeypatch.setattr(fetch, 'models_dir', lambda: tmp_path)
    snapshots = []
    def snapshot(repo, revision, target, patterns):
        snapshots.append(repo)
        time.sleep(.01)
        target.mkdir(parents=True, exist_ok=True)
        for filename in patterns:
            (target / filename).write_bytes(b'fixture')
    monkeypatch.setattr(fetch, '_snapshot', snapshot)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(fetch.fetch_model, ['phowhisper-small', 'phowhisper-small']))
    assert snapshots == ['diepho/PhoWhisper-small-ct2', 'vinai/PhoWhisper-small']
    assert fetch.artifacts.verify(tmp_path / 'phowhisper-small')


def test_default_fetch_only_downloads_zipformer_greedy(modules, monkeypatch):
    _, engines, fetch = modules
    selected = []
    monkeypatch.delenv('ASR_FETCH_MODELS', raising=False)
    monkeypatch.setattr(fetch, 'fetch_model', selected.append)
    fetch.fetch_all(turbo=False)
    assert selected == ['zipformer-30m']
    assert engines.CATALOG['zipformer-30m'][1].beam_size == 1
