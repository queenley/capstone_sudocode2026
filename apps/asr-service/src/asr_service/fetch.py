"""Explicit model download. --model can be repeated; inference never fetches weights."""
from __future__ import annotations

import argparse
import os
import shutil
import ssl
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from filelock import FileLock

from . import artifacts
from .engines import CATALOG, models_dir

SHERPA_RELEASES = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models'
SHERPA_PACKAGES = ['sherpa-onnx-zipformer-vi-30M-int8-2026-02-09', 'sherpa-onnx-zipformer-vi-int8-2025-04-20']
TURBO_REPO = ('whisper-large-v3-turbo', 'mobiuslabsgmbh/faster-whisper-large-v3-turbo')


def _snapshot(repo: str, revision: str, target: Path, patterns: list[str]) -> None:
    from huggingface_hub import snapshot_download
    snapshot_download(repo, revision=revision, local_dir=target, allow_patterns=patterns)


def fetch_model(name: str, *, convert_phowhisper: bool = False) -> None:
    if name not in CATALOG:
        raise ValueError(f'Unknown model: {name}')
    directory = models_dir()
    directory.mkdir(parents=True, exist_ok=True)
    # Shared volumes and decoder aliases must never write the same archive/stage concurrently.
    with FileLock(str(directory / (CATALOG[name][2] + '.download.lock')), timeout=600):
        _fetch_model(name, convert_phowhisper=convert_phowhisper)


def _fetch_model(name: str, *, convert_phowhisper: bool = False) -> None:
    if name not in CATALOG:
        raise ValueError(f'Unknown model: {name}')
    models = models_dir()
    models.mkdir(parents=True, exist_ok=True)
    target = models / CATALOG[name][2]
    verified = artifacts.verify(target)
    if verified and convert_phowhisper and name == 'phowhisper-small':
        import json
        verified = json.loads((target / 'artifact.json').read_text()).get('settings', {}).get('conversion') == 'ctranslate2'
    if verified:
        print(f'have {name} (checksum verified)', flush=True)
        return
    print(f'fetch {name}', flush=True)
    # Retain .downloads across retries; publish only after all artifacts are complete.
    downloads = models / '.downloads'
    downloads.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stage-', dir=models) as temporary:
        stage = Path(temporary) / target.name
        stage.mkdir()
        if name.startswith('zipformer-'):
            package = target.name
            archive = downloads / f'{package}.tar.bz2'
            url = f'{SHERPA_RELEASES}/{archive.name}'
            if not archive.exists():
                import certifi
                partial = archive.with_suffix('.part')
                with urllib.request.urlopen(url, timeout=60, context=ssl.create_default_context(cafile=certifi.where())) as response, partial.open('wb') as stream:
                    shutil.copyfileobj(response, stream)
                partial.replace(archive)
            digest = artifacts.sha256(archive)
            if package == SHERPA_PACKAGES[0] and digest != artifacts.ZIPFORMER_SHA256:
                archive.unlink()
                raise ValueError('Zipformer archive checksum mismatch')
            with tarfile.open(archive) as tar:
                members = tar.getmembers()
                if any(Path(m.name).parts[0] != package or m.issym() or m.islnk() for m in members):
                    raise ValueError('Unexpected archive layout')
                tar.extractall(temporary, filter='data')
            if any(not list(stage.glob(pattern)) for pattern in ['encoder*.onnx', 'decoder*.onnx', 'joiner*.onnx', 'tokens.txt']):
                raise ValueError('Incomplete Zipformer archive')
            artifacts.receipt(stage, [{'url': url, 'sha256': digest}], decoding='greedy_search', precision='int8')
        elif name == 'phowhisper-small' and convert_phowhisper:
            import ctranslate2
            repo, revision = artifacts.PHOWHISPER
            source = downloads / 'phowhisper-original'
            _snapshot(repo, revision, source, ['*.json', '*.txt', '*.bin', 'README.md'])
            converter = ctranslate2.converters.TransformersConverter(str(source), copy_files=['tokenizer.json', 'preprocessor_config.json'])
            converter.convert(str(stage), quantization='int8', force=True)
            artifacts.receipt(stage, [{'repo': repo, 'revision': revision}], conversion='ctranslate2',
                              converter_version=ctranslate2.__version__, precision='int8', decoding='greedy')
        elif name == 'phowhisper-small':
            # Keep the base image usable without Torch/Transformers. Research conversion is explicit.
            repo, revision = artifacts.PHOWHISPER_CT2
            _snapshot(repo, revision, stage, ['config.json', 'model.bin', 'vocabulary.json', 'README.md'])
            official, official_revision = artifacts.PHOWHISPER
            _snapshot(official, official_revision, stage / 'tokenizer-source', ['tokenizer.json', 'preprocessor_config.json'])
            for filename in ['tokenizer.json', 'preprocessor_config.json']:
                shutil.copyfile(stage / 'tokenizer-source' / filename, stage / filename)
            artifacts.receipt(stage, [{'repo': repo, 'revision': revision}, {'repo': official, 'revision': official_revision,
                              'scope': 'tokenizer/preprocessor only'}], conversion='upstream-ctranslate2', precision='upstream file; int8 at CPU load', decoding='greedy')
        elif name == 'viegem':
            repo, revision = artifacts.VIEGEM
            cached = downloads / 'viegem'
            _snapshot(repo, revision, cached, ['viegem_asr.pt', 'asr/*.py', 'README.md'])
            base, base_revision = artifacts.GEMMA
            _snapshot(base, base_revision, cached / 'base', ['config.json', 'preprocessor_config.json', 'processor_config.json',
                      'tokenizer*', 'model.safetensors', 'README.md'])
            shutil.copytree(cached, stage, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.cache'))
            artifacts.receipt(stage, [{'repo': repo, 'revision': revision}, {'repo': base, 'revision': base_revision}],
                              precision='float32', decoding='CTC greedy, offline; no n-gram LM')
        else:
            from huggingface_hub import HfApi
            repo = TURBO_REPO[1]
            revision = HfApi().model_info(repo).sha
            _snapshot(repo, revision, stage, ['*.json', '*.bin', '*.txt', 'README.md'])
            artifacts.receipt(stage, [{'repo': repo, 'revision': revision}], decoding='greedy')
        if not artifacts.verify(stage):
            raise ValueError(f'Incomplete artifacts: {name}')
        # Keep an older local download until the replacement is fully verified.
        if target.exists():
            backup = models / (target.name + '.previous')
            if backup.exists():
                raise FileExistsError(f'Inspect existing backup before replacing {target.name}')
            target.rename(backup)
        stage.rename(target)
    print(f'ready {name}', flush=True)


def fetch_all(*, turbo: bool | None = None) -> None:
    selected = os.environ.get('ASR_FETCH_MODELS', 'zipformer-30m')
    names = [name.strip() for name in selected.split(',') if name.strip()]
    if turbo if turbo is not None else os.environ.get('ASR_FETCH_TURBO') == '1':
        names.append('whisper-turbo')
    for name in dict.fromkeys(names):
        fetch_model(name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', action='append', choices=sorted(CATALOG), help='Only fetch these models (repeatable)')
    parser.add_argument('--turbo', action='store_true')
    parser.add_argument('--convert-phowhisper', action='store_true', help='Convert original pinned VinAI weights to int8; requires requirements-research.txt')
    args = parser.parse_args()
    if args.model:
        for name in dict.fromkeys(args.model):
            fetch_model(name, convert_phowhisper=args.convert_phowhisper)
    else:
        if args.convert_phowhisper:
            parser.error('--convert-phowhisper requires --model phowhisper-small')
        fetch_all(turbo=args.turbo)


if __name__ == '__main__':
    main()
