"""Text to speech, streamed.

The reply is split into sentences. Each sentence is synthesised as a stream
of audio chunks where the engine allows it, and every chunk goes to the
browser as soon as it exists, so the caller hears the answer begin while the
rest is still being made. That is the lever on time to first audio that does
not need a speech-to-speech model.

Engines:

- ``vieneu``: VieNeu-TTS on CPU through ONNX Runtime, fully local. Streams:
  on this laptop the first chunk is ready in about 0.35 s and synthesis runs
  faster than playback, so the stream never starves.
- ``openai``: OpenAI's speech API (``openai:<voice>``, model ``OPENAI_TTS_MODEL``,
  ``gpt-4o-mini-tts`` unless set) with ``OPENAI_API_KEY``. In the cloud: no
  weights to download, no CPU taken from the recogniser, about a second per
  sentence, and every sentence requested at once. Paid per character. One
  chunk per sentence (mp3), as the browser decodes each message whole.
- ``elevenlabs``: ElevenLabs (``ELEVENLABS_API_KEY``, model
  ``ELEVENLABS_TTS_MODEL``, ``eleven_flash_v2_5`` unless set). ``elevenlabs:``
  picks the agent's voice by the caller's region from ``voices.yaml`` (the
  file ``scripts/create_data`` voices its test calls with: ``agent.<bac|trung|
  nam|default>.<female|male>``, gender from ``VOICE_GENDER``, female unless
  set); one customer always hears the same voice, an unknown caller (or one
  with no region) a northern one (``VOICE_DEFAULT_REGION``, ``bac`` unless set).
  ``elevenlabs:<voice id>`` is one fixed voice. Paid per character.
- ``edge``: Microsoft's neural voices (vi-VN HoaiMy, NamMinh) through the free
  endpoint behind Edge's read-aloud. The same voices Azure Speech sells, but
  the free endpoint refuses a large share of requests without audio (all of
  them, 403, on 2026-10-24), so it is here to hear the voices, not to time
  them. One chunk per sentence.

Which one a call uses: ``voice.tts`` in ``config/models.yaml``, unless
``VOICE_TTS`` is set (``runtime/options.py``), unless the Admin page changed
it. Only the chosen voice is ever loaded: with ``openai`` VieNeu's weights are
neither downloaded nor loaded, and its package need not be installed
(``requirements-voice-local-tts.txt``).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import threading
import time
import wave
from dataclasses import dataclass
from typing import AsyncIterator

import numpy as np


@dataclass
class Speech:
    audio: bytes
    mime: str
    elapsed: float  # since synthesis of this sentence began
    first_byte: float | None  # until the engine returned its first audio for this sentence
    duration: float | None = None  # seconds of audio in this chunk, when known


class EdgeVoice:
    """One request per sentence; refusals are retried inside the measured time."""

    ATTEMPTS = 4
    parallel = True  # network-bound: all sentences may be requested at once

    def __init__(self, voice: str) -> None:
        self.voice = voice

    async def warm(self) -> None:
        return None

    async def stream(self, text: str) -> AsyncIterator[Speech]:
        import edge_tts

        started = time.perf_counter()
        for attempt in range(self.ATTEMPTS):
            first: float | None = None
            chunks: list[bytes] = []
            try:
                async for chunk in edge_tts.Communicate(text, self.voice).stream():
                    if chunk["type"] == "audio":
                        if first is None:
                            first = time.perf_counter() - started
                        chunks.append(chunk["data"])
                break
            except edge_tts.exceptions.NoAudioReceived:
                if attempt == self.ATTEMPTS - 1:
                    raise
                await asyncio.sleep(0.3)
        yield Speech(b"".join(chunks), "audio/mpeg", time.perf_counter() - started, first)


class OpenAIVoice:
    """OpenAI's speech API: one request per sentence, all sentences at once."""

    parallel = True  # network-bound
    _client = None
    VOICES = ("coral", "nova", "sage", "shimmer", "alloy", "ash", "ballad", "echo", "fable", "onyx", "verse")
    #: Only the gpt-4o voices follow instructions; tts-1 ignores them.
    INSTRUCTIONS = ("Đọc bằng tiếng Việt tự nhiên, giọng nhân viên chăm sóc khách hàng thân thiện, "
                    "rõ ràng, tốc độ vừa phải. Đọc số tiền và mã sản phẩm chậm, rõ từng phần.")

    def __init__(self, voice: str | None) -> None:
        self.voice = voice or "coral"
        self.model = os.environ.get("OPENAI_TTS_MODEL", "").strip() or "gpt-4o-mini-tts"

    @classmethod
    def _api(cls):
        if cls._client is None:
            from openai import AsyncOpenAI

            from ...config.config_manager import require_api_key

            cls._client = AsyncOpenAI(api_key=require_api_key("openai"), timeout=20.0, max_retries=1)
        return cls._client

    async def warm(self) -> None:
        """Nothing to load: only check that the key is there, so a call does not find out."""
        self._api()

    async def stream(self, text: str) -> AsyncIterator[Speech]:
        started = time.perf_counter()
        first: float | None = None
        chunks: list[bytes] = []
        extra = {"instructions": self.INSTRUCTIONS} if self.model.startswith("gpt-4o") else {}
        async with self._api().audio.speech.with_streaming_response.create(
            model=self.model, voice=self.voice, input=text, response_format="mp3", **extra,
        ) as response:
            async for chunk in response.iter_bytes():
                if first is None:
                    first = time.perf_counter() - started
                chunks.append(chunk)
        yield Speech(b"".join(chunks), "audio/mpeg", time.perf_counter() - started, first)


REGIONS = ("bac", "trung", "nam")


def voices_file() -> "Path | None":
    """voices.yaml: ``ELEVENLABS_VOICES`` when set, the agent's config (the image
    copies it there), else the create_data copy in this repository."""
    from pathlib import Path

    from ...config.config_manager import ROOT

    candidates = [os.environ.get("ELEVENLABS_VOICES", "").strip(), str(ROOT / "config" / "voices.yaml")]
    candidates += [str(parent / "scripts" / "create_data" / "config" / "voices.yaml") for parent in Path(__file__).resolve().parents]
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


class ElevenLabsVoice:
    """ElevenLabs, one request per sentence, all sentences at once; the voice by region."""

    parallel = True  # network-bound
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
    _client = None
    _agents: dict | None = None

    def __init__(self, voice: str | None) -> None:
        self.fixed = voice or None
        self.voice_id = voice or None
        self.region: str | None = None
        self.model = os.environ.get("ELEVENLABS_TTS_MODEL", "").strip() or "eleven_flash_v2_5"
        self.gender = os.environ.get("VOICE_GENDER", "female").strip().lower() or "female"

    @classmethod
    def agents(cls) -> dict:
        """The ``agent`` voices of voices.yaml: region -> gender -> [voice ids]."""
        if cls._agents is None:
            import yaml

            path = voices_file()
            data = yaml.safe_load(path.read_text(encoding="utf-8")) if path else {}
            cls._agents = ((data or {}).get("voices") or {}).get("agent") or {}
        return cls._agents

    def choose(self, region: str | None, key: str) -> str | None:
        """The voice for a caller of *region* (None: unknown), stable for *key* (the
        customer, else the call). Returns the voice id; a fixed voice never changes."""
        if self.fixed:
            return self.voice_id
        agents = self.agents()
        if region not in REGIONS or region not in agents:
            # An unknown caller hears the shop's default voice: VOICE_DEFAULT_REGION, northern unless set.
            region = os.environ.get("VOICE_DEFAULT_REGION", "bac").strip().lower() or "bac"
            region = region if region in agents else "default"
        by_gender = agents.get(region) or agents.get("default") or {}
        pool = by_gender.get(self.gender) or next((ids for ids in by_gender.values() if ids), [])
        if pool:
            index = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(pool)
            self.voice_id, self.region = pool[index], region
        return self.voice_id

    @classmethod
    def _api(cls):
        if cls._client is None:
            import httpx

            key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
            if not key:
                raise RuntimeError("ELEVENLABS_API_KEY is not set: the elevenlabs voice cannot speak")
            cls._client = httpx.AsyncClient(headers={"xi-api-key": key}, timeout=20.0)
        return cls._client

    async def warm(self) -> None:
        """Nothing to load: check the key and that voices.yaml has an agent voice."""
        self._api()
        if not self.fixed and not self.choose(None, "warm"):
            raise RuntimeError("voices.yaml has no agent voice: set ELEVENLABS_VOICES or VOICE_TTS=elevenlabs:<voice id>")

    async def stream(self, text: str) -> AsyncIterator[Speech]:
        voice = self.voice_id or self.choose(None, "default")
        started = time.perf_counter()
        first: float | None = None
        chunks: list[bytes] = []
        body = {"text": text, "model_id": self.model, "language_code": "vi",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
        async with self._api().stream("POST", self.URL.format(voice=voice), params={"output_format": "mp3_44100_128"},
                                      json=body) as response:
            if response.status_code >= 400:
                detail = (await response.aread()).decode("utf-8", "replace")[:200]
                raise RuntimeError(f"ElevenLabs {response.status_code}: {detail}")
            async for chunk in response.aiter_bytes():
                if first is None:
                    first = time.perf_counter() - started
                chunks.append(chunk)
        yield Speech(b"".join(chunks), "audio/mpeg", time.perf_counter() - started, first)


class VieNeuVoice:
    """Local and streaming. One engine per process, used by one sentence at a time."""

    parallel = False  # CPU-bound: sentences in parallel would only slow each other
    _engine = None
    _lock = threading.Lock()

    def __init__(self, voice: str | None) -> None:
        self.voice = voice

    def _load(self):
        if VieNeuVoice._engine is None:
            if not _vieneu_installed():
                raise RuntimeError("VieNeu-TTS is not installed here: build with a local voice "
                                   "(VOICE_TTS=vieneu:) or choose a cloud voice (VOICE_TTS=openai:coral)")
            from vieneu import Vieneu

            VieNeuVoice._engine = Vieneu()
        return VieNeuVoice._engine

    async def warm(self) -> None:
        """Load the model and synthesise one word, outside any timed turn."""

        def run() -> None:
            with VieNeuVoice._lock:
                self._load().infer("Dạ.")

        await asyncio.to_thread(run)

    async def stream(self, text: str) -> AsyncIterator[Speech]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[object] = asyncio.Queue()
        stop = threading.Event()
        started = time.perf_counter()

        def work() -> None:
            try:
                with VieNeuVoice._lock:
                    engine = self._load()
                    kwargs = {"voice": self.voice} if self.voice else {}
                    for chunk in engine.infer_stream(text, **kwargs):
                        if stop.is_set():
                            break
                        audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
                        loop.call_soon_threadsafe(queue.put_nowait, (audio, engine.sample_rate))
            except Exception as error:  # noqa: BLE001 - re-raised on the loop below
                loop.call_soon_threadsafe(queue.put_nowait, error)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker = loop.run_in_executor(None, work)
        first: float | None = None
        try:
            while (item := await queue.get()) is not None:
                if isinstance(item, Exception):
                    raise item
                audio, rate = item
                if first is None:
                    first = time.perf_counter() - started
                yield Speech(_wav(audio, rate), "audio/wav", time.perf_counter() - started, first, len(audio) / rate)
        finally:
            # The caller stopped listening (a barge-in): let the thread finish
            # its current chunk and quit instead of voicing the whole sentence.
            stop.set()
            await worker


def _wav(audio: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _vieneu_installed() -> bool:
    try:
        import vieneu  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means "not offered"
        return False
    return True


def voices() -> list[dict[str, str]]:
    offered = []
    if _vieneu_installed():
        offered.append({"name": "vieneu:", "label": "VieNeu-TTS · local CPU, streaming"})
    from ...config.config_manager import has_api_key

    if os.environ.get("ELEVENLABS_API_KEY", "").strip():
        offered.append({"name": "elevenlabs:", "label": "ElevenLabs · giọng theo vùng miền của khách, cloud, paid"})
    if has_api_key("openai"):
        offered += [{"name": f"openai:{name}", "label": f"OpenAI {name} · cloud, paid"} for name in OpenAIVoice.VOICES[:4]]
    offered += [
        {"name": "edge:vi-VN-HoaiMyNeural", "label": "HoaiMy · Microsoft neural, free endpoint (unreliable)"},
        {"name": "edge:vi-VN-NamMinhNeural", "label": "NamMinh · Microsoft neural, free endpoint (unreliable)"},
    ]
    return offered


def voice(name: str) -> EdgeVoice | ElevenLabsVoice | OpenAIVoice | VieNeuVoice:
    engine, _, rest = name.partition(":")
    if engine == "elevenlabs":
        return ElevenLabsVoice(rest or None)
    if engine == "openai":
        return OpenAIVoice(rest or None)
    if engine == "edge":
        return EdgeVoice(rest)
    if engine == "vieneu":
        return VieNeuVoice(rest or None)
    raise ValueError(f"Unknown voice {name!r}")


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def sentences(text: str, *, shortest: int = 18) -> list[str]:
    """Split on sentence ends; fold fragments shorter than *shortest* into the next.

    A lone "Dạ." costs a synthesis round trip for half a second of audio, so
    it rides with the sentence after it.
    """
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    merged: list[str] = []
    carry = ""
    for part in parts:
        carry = f"{carry} {part}".strip()
        if len(carry) >= shortest:
            merged.append(carry)
            carry = ""
    if carry:
        if merged:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)
    return merged
