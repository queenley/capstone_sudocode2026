"""Which recogniser hears the audio: ``create(spec)`` builds one from ``--engine``.

| ``--engine`` | Recogniser | Diarizes |
|---|---|---|
| ``agent`` (default) | the agent's own client (``ai_agent_service.components.voice.asr``) with its model ``voice.asr`` of ``config/models.yaml`` and the lexicon's hotwords: what a real call hears | no |
| ``agent:<model>`` | the same client, another model of the ASR service (``zipformer-2025``, ``phowhisper-small``, ``whisper-turbo``…) | no |
| ``openai:<model>`` | OpenAI's transcription API (``gpt-4o-transcribe``, ``gpt-4o-mini-transcribe``, ``whisper-1``) | no |
| ``openai:gpt-4o-transcribe-diarize`` | the same, with speaker segments | yes |
| ``file:<hypotheses.json>`` | a hypotheses file another system wrote (BTC's ``hypotheses_format``) | when it has ``turns`` |

Every engine answers :meth:`Engine.hear`: ``{"text", "seconds", "audio_seconds"}`` and, when it diarizes,
``"segments": [{"speaker", "start", "end", "text"}]`` with its own speaker labels. Whatever it heard then goes through
the agent's lexicon and intake (``understanding.py``), as a real call's words do.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import time
import wave

import numpy as np

RATE = 16_000


class Engine:
    name = "engine"
    diarizes = False

    def hear(self, samples: np.ndarray, clip_id: str) -> dict:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"engine": self.name}


def _agent():
    """The agent's process environment (``.env``, import path), as its own processes start."""
    from src.services.agent import launch

    launch.prepare()


class AgentEngine(Engine):
    """The agent's ASR client: ``ASR_URL`` (the ASR service; ``--url``), the model, the lexicon's hotwords."""

    def __init__(self, model: str | None, *, url: str, hotwords: bool = True) -> None:
        _agent()
        os.environ["ASR_URL"] = url.rstrip("/")
        from ai_agent_service.components.intake.lexicon import lexicon
        from ai_agent_service.components.voice import asr
        from ai_agent_service.config.config_manager import get_models_config

        self.asr = asr
        self.model = model or get_models_config().voice.asr
        self.hotwords = lexicon().hotwords if hotwords else []
        self.name = f"agent:{self.model}"
        try:
            asr.load(self.model)
        except Exception as exc:  # noqa: BLE001 - say what to start, whatever the client raised
            raise RuntimeError(f"The agent's ASR at {url} cannot load {self.model}: {exc} "
                               "(docker compose up -d asr-service)") from exc

    def hear(self, samples, clip_id):
        heard = self.asr.transcribe(self.model, samples, self.hotwords)
        return {"text": heard.text, "seconds": heard.seconds, "audio_seconds": heard.audio_seconds}

    def describe(self):
        return {"engine": self.name, "url": os.environ.get("ASR_URL"), "hotwords": len(self.hotwords)}


def _wav_bytes(samples: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buffer.getvalue()


class OpenAIEngine(Engine):
    """OpenAI's ``audio.transcriptions``; ``*-diarize`` models return speaker segments."""

    def __init__(self, model: str, *, hotwords: bool = True) -> None:
        _agent()   # loads the repository's .env, where OPENAI_API_KEY is
        from openai import OpenAI

        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set (.env at the repository root)")
        self.client, self.model = OpenAI(), model
        self.diarizes = "diarize" in model
        self.name = f"openai:{model}"
        words = []
        if hotwords and not self.diarizes:
            from ai_agent_service.components.intake.lexicon import lexicon

            words = lexicon().hotwords
        # The agent's hotwords as the prompt, the only biasing these models take.
        self.prompt = ", ".join(words[:80]) if words else None

    def hear(self, samples, clip_id):
        started = time.perf_counter()
        options = {"model": self.model, "file": (f"{clip_id}.wav", _wav_bytes(samples), "audio/wav"), "language": "vi"}
        if self.diarizes:
            options.update(response_format="diarized_json", chunking_strategy="auto")
        elif self.prompt:
            options["prompt"] = self.prompt
        result = self.client.audio.transcriptions.create(**options)
        heard = {"text": result.text, "seconds": round(time.perf_counter() - started, 3),
                 "audio_seconds": round(len(samples) / RATE, 3)}
        if self.diarizes:
            heard["segments"] = [{"speaker": str(s.speaker), "start": float(s.start), "end": float(s.end), "text": s.text}
                                 for s in result.segments]
        return heard


class FileEngine(Engine):
    """Hypotheses another system wrote: ``{id: {"text", "turns"?}}``."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.given = json.loads(self.path.read_text(encoding="utf-8"))
        self.diarizes = any(isinstance(v, dict) and v.get("turns") for v in self.given.values())
        self.name = f"file:{self.path.name}"

    def hear(self, samples, clip_id):
        if clip_id not in self.given:
            raise KeyError(f"{clip_id} is not in {self.path}")
        item = self.given[clip_id]
        heard = {"text": item["text"], "seconds": None, "audio_seconds": round(len(samples) / RATE, 3)}
        if item.get("turns"):
            heard["segments"] = [{"speaker": t["speaker"], "start": t["start"], "end": t["end"], "text": t.get("text", "")}
                                 for t in item["turns"]]
        return heard


def create(spec: str, *, url: str = "http://127.0.0.1:8500", hotwords: bool = True) -> Engine:
    kind, _, rest = spec.partition(":")
    if kind == "agent":
        return AgentEngine(rest or None, url=url, hotwords=hotwords)
    if kind == "openai" and rest:
        return OpenAIEngine(rest, hotwords=hotwords)
    if kind == "file" and rest:
        return FileEngine(rest)
    raise ValueError(f"Unknown --engine {spec!r}: agent, agent:<model>, openai:<model> or file:<hypotheses.json>")
