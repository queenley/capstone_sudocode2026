"""The speech recognisers: ``transcribe(model, samples) -> Transcript``.

Moved out of the agent (``ai_agent_service/components/voice/asr.py``) so they
can run on their own machine, a GPU one when there is one:

- sherpa-onnx transducers: the Vietnamese Zipformer models. Small, fast on CPU.
- faster-whisper (CTranslate2): PhoWhisper and Whisper. int8 on CPU, float16
  on a GPU. Greedy decoding, so the timing is the fastest the model can do.

``ASR_DEVICE`` is ``cpu`` (default) or ``cuda``; ``ASR_THREADS`` the CPU
threads per model; ``ASR_MODELS_DIR`` where the weights are (``fetch.py``).
A recogniser is loaded once and shared; loading takes seconds. Calls on one
model run one at a time (a lock per model): parallel decodes on the same
weights only slow each other down, on a CPU and on one GPU alike.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RATE = 16_000
DEVICE = os.environ.get("ASR_DEVICE", "cpu").strip().lower() or "cpu"
THREADS = int(os.environ.get("ASR_THREADS", os.environ.get("LAB_ASR_THREADS", "4")))


def models_dir() -> Path:
    raw = os.environ.get("ASR_MODELS_DIR") or os.environ.get("VOICE_MODELS_DIR")
    return Path(raw).expanduser().resolve() if raw else Path(__file__).resolve().parents[2] / "models"


@dataclass
class Transcript:
    model: str
    text: str
    seconds: float  # decoding time
    audio_seconds: float

    @property
    def rtf(self) -> float:
        return self.seconds / self.audio_seconds if self.audio_seconds else 0.0


class SherpaTransducer:
    beam_size = 1
    def __init__(self, directory: Path) -> None:
        import sherpa_onnx

        def one(pattern: str) -> str:
            found = sorted(directory.glob(pattern))
            if not found:
                raise FileNotFoundError(f"{pattern} in {directory}")
            return str(found[0])

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=one("encoder*.onnx"),
            decoder=one("decoder*.onnx"),
            joiner=one("joiner*.onnx"),
            tokens=one("tokens.txt"),
            num_threads=THREADS,
            sample_rate=RATE,
            feature_dim=80,
            decoding_method="greedy_search" if self.beam_size == 1 else "modified_beam_search",
            max_active_paths=self.beam_size,
            provider="cuda" if DEVICE == "cuda" else "cpu",
        )

    def transcribe(self, samples: np.ndarray, hotwords: list[str]) -> str:
        stream = self._recognizer.create_stream()
        stream.accept_waveform(RATE, samples)
        self._recognizer.decode_stream(stream)
        # The Zipformer vocabularies are upper case; the agent, the lexicon
        # and the WER bench all read lower case.
        return stream.result.text.strip().lower()


class SherpaBeamSearch(SherpaTransducer):
    beam_size = 4


class FasterWhisper:
    def __init__(self, directory: Path) -> None:
        from faster_whisper import WhisperModel

        cuda = DEVICE == "cuda"
        self._model = WhisperModel(str(directory), device="cuda" if cuda else "cpu",
                                   compute_type="float16" if cuda else "int8", cpu_threads=THREADS,
                                   local_files_only=True)

    def transcribe(self, samples: np.ndarray, hotwords: list[str]) -> str:
        segments, _ = self._model.transcribe(
            samples,
            language="vi",
            beam_size=1,
            temperature=0.0,
            without_timestamps=True,
            condition_on_previous_text=False,
            vad_filter=False,
            hotwords=", ".join(hotwords) if hotwords else None,
        )
        return "".join(segment.text for segment in segments).strip()


class VieGem:
    """Reviewed, pinned upstream CTC code, local base encoder and tokenizer only."""

    def __init__(self, directory: Path) -> None:
        import importlib.util
        import sys
        import torch
        from transformers import AutoTokenizer
        from . import artifacts

        if not artifacts.verify(directory):
            raise FileNotFoundError("VieGem artifacts missing/corrupt; run fetch --model viegem")
        # Keep the downloaded package isolated from unrelated packages named 'asr'.
        package = "_viegem_pinned"
        spec = importlib.util.spec_from_file_location(package, directory / "asr/__init__.py",
                                                     submodule_search_locations=[str(directory / "asr")])
        module = importlib.util.module_from_spec(spec)
        sys.modules[package] = module
        spec.loader.exec_module(module)
        from importlib import import_module
        upstream = import_module(package + ".model")
        text = import_module(package + ".text")
        checkpoint = torch.load(directory / "viegem_asr.pt", map_location="cpu", weights_only=True)
        cfg = upstream.ModelConfig.from_dict(checkpoint["model_config"])
        cfg.encoder_id = str(directory / "base")
        torch.set_num_threads(THREADS)
        self._units = text.Units(checkpoint["gemma_ids"])
        self._tokenizer = AutoTokenizer.from_pretrained(cfg.encoder_id, local_files_only=True)
        self._model = upstream.CTCModel(cfg, self._units.gemma_ids)
        missing, unexpected = self._model.load_state_dict(checkpoint["model"], strict=False)
        # The released checkpoint omits frozen base weights, but must include the reader/head.
        if unexpected or any(not key.startswith("encoder.") for key in missing):
            raise ValueError(f"Incompatible VieGem checkpoint: {missing}, {unexpected}")
        self._model = self._model.to(DEVICE).eval()
        self._decode = upstream.greedy_decode

    def transcribe(self, samples: np.ndarray, hotwords: list[str]) -> str:
        import torch
        if len(samples) > 30 * RATE:
            raise ValueError("VieGem supports utterances up to 30 seconds; segment longer audio explicitly")
        wav = torch.from_numpy(samples.copy())[None].to(DEVICE)
        with torch.inference_mode():
            logits, lengths = self._model(wav, torch.tensor([wav.shape[1]], device=DEVICE), streaming=False)
        return self._units.decode(self._tokenizer, self._decode(logits, lengths)[0])


#: name -> (label, engine, directory under the models folder)
CATALOG: dict[str, tuple[str, type, str]] = {
    "zipformer-30m": (
        "Zipformer 30M int8 · sherpa-onnx",
        SherpaTransducer,
        "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09",
    ),
    "viegem": ("VieGem ASR · CTC greedy · research license", VieGem, "viegem"),
    "zipformer-30m-beam4": (
        "Zipformer 30M int8 · beam 4",
        SherpaBeamSearch,
        "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09",
    ),
    "zipformer-2025": (
        "Zipformer vi 2025-04 int8 · sherpa-onnx",
        SherpaTransducer,
        "sherpa-onnx-zipformer-vi-int8-2025-04-20",
    ),
    "phowhisper-small": (
        "PhoWhisper small · faster-whisper",
        FasterWhisper,
        "phowhisper-small",
    ),
    "whisper-turbo": (
        "Whisper large-v3-turbo · faster-whisper",
        FasterWhisper,
        "whisper-large-v3-turbo",
    ),
}

_loaded: dict[str, object] = {}
_load_locks: dict[str, threading.Lock] = {name: threading.Lock() for name in CATALOG}
_run_locks: dict[str, threading.Lock] = {name: threading.Lock() for name in CATALOG}


def available() -> list[dict[str, object]]:
    """The models whose weights are here, and whether each is loaded."""
    return [
        {"name": name, "label": label, "loaded": name in _loaded, "device": DEVICE}
        for name, (label, _, folder) in CATALOG.items()
        if present(name)
    ]


def present(name: str) -> bool:
    directory = models_dir() / CATALOG[name][2]
    if name == "viegem":
        required = ["artifact.json", "viegem_asr.pt", "asr/model.py", "base/model.safetensors", "base/tokenizer.json"]
    elif name.startswith("zipformer"):
        required = ["encoder*.onnx", "decoder*.onnx", "joiner*.onnx", "tokens.txt"]
    else:
        required = ["model.bin", "config.json", "tokenizer.json"]
    return all(any(directory.glob(pattern)) for pattern in required)


def metadata(name: str) -> dict:
    import json
    from importlib.metadata import version, PackageNotFoundError
    if name not in CATALOG:
        raise KeyError(name)
    path = models_dir() / CATALOG[name][2] / "artifact.json"
    packages = {}
    for package in ["torch", "transformers", "sherpa-onnx", "faster-whisper", "ctranslate2", "numpy"]:
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            pass
    options = ({"decoding_method": "modified_beam_search", "max_active_paths": 4} if name.endswith("-beam4") else
               {"decoding_method": "greedy_search"} if name.startswith("zipformer") else
               {"beam_size": 1, "temperature": 0.0, "language": "vi", "condition_on_previous_text": False} if name in {"phowhisper-small", "whisper-turbo"} else
               {"decoding_method": "CTC greedy", "streaming": False, "language_model": None})
    return {"model": name, "device": DEVICE, "threads": THREADS, "packages": packages, "decoder_options": options,
            "artifact": json.loads(path.read_text()) if path.is_file() else None,
            "hotwords_supported": name in {"phowhisper-small", "whisper-turbo"}}


def load(name: str) -> float:
    """Load *name* if needed. Returns the seconds spent loading (0 if cached)."""
    if name not in CATALOG:
        raise KeyError(f"Unknown model {name!r}; known: {sorted(CATALOG)}")
    if name in _loaded:
        return 0.0
    with _load_locks[name]:
        if name in _loaded:
            return 0.0
        _, engine, folder = CATALOG[name]
        if not present(name):
            raise FileNotFoundError(f"Incomplete local weights for {name}; run fetch --model {name}")
        started = time.perf_counter()
        _loaded[name] = engine(models_dir() / folder)
        return time.perf_counter() - started


def transcribe(name: str, samples: np.ndarray, hotwords: list[str] | None = None) -> Transcript:
    """Float32 mono samples at 16 kHz -> text. Blocks: run it in a thread."""
    load(name)
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    with _run_locks[name]:
        started = time.perf_counter()
        text = _loaded[name].transcribe(samples, hotwords or [])
        seconds = time.perf_counter() - started
    return Transcript(name, text, seconds, len(samples) / RATE)
