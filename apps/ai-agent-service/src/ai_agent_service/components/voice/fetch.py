"""Download the models the agent's own voice code uses into models/voice.

The agent keeps the caller's side of the call: Silero VAD and Smart Turn,
which decide when an utterance ends. The recognisers belong to the ASR
service (``apps/asr-service``), which fetches its own weights; without
``ASR_URL`` the agent recognises in this process and fetches them here too.

The API runs this itself when it starts, so a new machine fetches what it
lacks; files already present are skipped, so it is safe to run again.

    python -m ai_agent_service.components.voice.fetch
    python -m ai_agent_service.components.voice.fetch --turbo

The second, in-process only, also fetches Whisper large-v3-turbo (1.6 GB).
The folder is ``VOICE_MODELS_DIR`` when set.
"""

from __future__ import annotations

import argparse
import os
import urllib.request
from pathlib import Path

from huggingface_hub import hf_hub_download

from . import asr, models_dir

MODELS = models_dir()

SILERO_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"


def fetch(url: str, target: Path) -> None:
    if target.exists():
        print(f"have {target.name}")
        return
    print(f"get  {url}")
    partial = target.with_suffix(target.suffix + ".part")
    urllib.request.urlretrieve(url, partial)
    partial.rename(target)


def fetch_all(*, turbo: bool = False) -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    fetch(SILERO_URL, MODELS / "silero_vad.onnx")
    if not (MODELS / "smart-turn-v3.2-cpu.onnx").exists():
        hf_hub_download("pipecat-ai/smart-turn-v3", "smart-turn-v3.2-cpu.onnx", local_dir=MODELS)
    if not asr.remote():
        # Recognising in this process: the ASR service's weights, into the same folder.
        os.environ.setdefault("ASR_MODELS_DIR", str(MODELS))
        asr._engines()
        from asr_service import fetch as asr_fetch

        asr_fetch.fetch_all(turbo=turbo)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turbo", action="store_true", help="also fetch Whisper large-v3-turbo")
    args = parser.parse_args()
    fetch_all(turbo=args.turbo)
    print("done")


if __name__ == "__main__":
    main()
