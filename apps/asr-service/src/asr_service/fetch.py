"""Download the recognisers' weights into ASR_MODELS_DIR.

The service runs this itself when it starts, so a new machine fetches what it
lacks; files already present are skipped. By hand:

    python -m asr_service.fetch                 # the Zipformers and PhoWhisper small
    python -m asr_service.fetch --turbo         # also Whisper large-v3-turbo (1.6 GB, for a GPU)

Whisper-family models are CTranslate2 conversions from Hugging Face; the two
Zipformer models are the sherpa-onnx packages of Vietnamese transducers.
"""

from __future__ import annotations

import argparse
import os
import tarfile
import urllib.request
from pathlib import Path

from .engines import models_dir

SHERPA_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
SHERPA_PACKAGES = [
    "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09",
    "sherpa-onnx-zipformer-vi-int8-2025-04-20",
]
WHISPER_REPOS = {"phowhisper-small": "diepho/PhoWhisper-small-ct2"}
TURBO_REPO = ("whisper-large-v3-turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo")


def _get(url: str, target: Path) -> None:
    print(f"get  {url}")
    partial = target.with_suffix(target.suffix + ".part")
    urllib.request.urlretrieve(url, partial)
    partial.rename(target)


def fetch_sherpa(models: Path, name: str) -> None:
    if (models / name).is_dir():
        print(f"have {name}")
        return
    archive = models / f"{name}.tar.bz2"
    if not archive.exists():
        _get(f"{SHERPA_RELEASES}/{name}.tar.bz2", archive)
    with tarfile.open(archive) as tar:
        tar.extractall(models, filter="data")
    archive.unlink()


def fetch_whisper(models: Path, local: str, repo: str) -> None:
    from huggingface_hub import snapshot_download

    target = models / local
    if (target / "model.bin").exists():
        print(f"have {local}")
        return
    print(f"get  {repo}")
    snapshot_download(repo, local_dir=target)


def fetch_all(*, turbo: bool | None = None) -> None:
    """Everything the catalogue knows; Whisper turbo only with ``turbo`` or ``ASR_FETCH_TURBO=1``."""
    models = models_dir()
    models.mkdir(parents=True, exist_ok=True)
    for name in SHERPA_PACKAGES:
        fetch_sherpa(models, name)
    for local, repo in WHISPER_REPOS.items():
        fetch_whisper(models, local, repo)
    if turbo if turbo is not None else os.environ.get("ASR_FETCH_TURBO") == "1":
        fetch_whisper(models, *TURBO_REPO)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--turbo", action="store_true", help="also fetch Whisper large-v3-turbo")
    args = parser.parse_args()
    fetch_all(turbo=args.turbo)
    print("done")


if __name__ == "__main__":
    main()
