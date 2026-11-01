"""Pinned sources and reproducibility receipts; weights and downloaded source stay untracked."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

VIEGEM = ('5CD-AI/VieGem-ASR', '95eae70b21fb0ef640e3ac4ea8cfa2380872ed20')
GEMMA = ('google/embeddinggemma-2', 'f9972ac22e696a105c482202646979e33e4b5a1e')
PHOWHISPER = ('vinai/PhoWhisper-small', 'a86b604c346caf7148c37512eafe783a16420adb')
PHOWHISPER_CT2 = ('diepho/PhoWhisper-small-ct2', '5463cb9d0040071dcc245038d1039d7edee45a1c')
ZIPFORMER_SHA256 = 'da8b637947091829d7ee9eda23da2a4ec7caa399233a3f4e34eb719fb2ea6b9b'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(directory: Path, sources: list[dict], **settings) -> None:
    files = {str(p.relative_to(directory)): {'bytes': p.stat().st_size, 'sha256': sha256(p)}
             for p in sorted(directory.rglob('*'))
             if p.is_file() and '.cache' not in p.parts and p.name != 'artifact.json'}
    body = {'sources': sources, 'settings': settings, 'files': files}
    (directory / 'artifact.json').write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding='utf-8')


def verify(directory: Path) -> bool:
    """A directory left by an interrupted download/conversion is never considered ready."""
    try:
        body = json.loads((directory / 'artifact.json').read_text())
        return bool(body['files']) and all(
            (directory / name).is_file() and (directory / name).stat().st_size == item['bytes']
            and sha256(directory / name) == item['sha256'] for name, item in body['files'].items())
    except (OSError, ValueError, KeyError, TypeError):
        return False
