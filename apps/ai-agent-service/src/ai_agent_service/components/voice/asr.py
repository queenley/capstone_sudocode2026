"""Speech recognition for a call: ``transcribe(model, samples) -> Transcript``.

The recognisers live in the ASR service (``apps/asr-service``), so they can
run on another machine, a GPU one when there is one. This module is how the
agent reaches them:

- ``ASR_URL`` set (``http://asr-service:8500`` in Docker, or a rented GPU):
  over HTTP, one request per utterance, with ``ASR_API_KEY`` when the service
  asks for one. ``stream()`` opens the service's realtime WebSocket, for
  partial transcripts while the caller is still speaking.
- ``ASR_URL`` unset (a laptop without Docker): the same engines in this
  process, imported from ``apps/asr-service/src`` (``pip install -r
  apps/asr-service/requirements.txt``).

The call blocks, so the voice session runs it in a thread, as before.
"""

from __future__ import annotations

import json
import math
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

import numpy as np

RATE = 16_000
TIMEOUT = float(os.environ.get("ASR_TIMEOUT", "30"))


@dataclass
class Transcript:
    model: str
    text: str
    seconds: float  # decoding time
    audio_seconds: float
    denoise_seconds: float = 0.0
    decoder_seconds: float | None = None
    preprocessing: dict | None = None

    @property
    def rtf(self) -> float:
        return self.seconds / self.audio_seconds if self.audio_seconds else 0.0


def url() -> str:
    return os.environ.get("ASR_URL", "").strip().rstrip("/")


def remote() -> bool:
    return bool(url())


def _headers() -> dict[str, str]:
    key = os.environ.get("ASR_API_KEY", "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


# ── the service ───────────────────────────────────────────────────────────

_client = None
_client_lock = threading.Lock()


def _http():
    global _client
    with _client_lock:
        if _client is None:
            import httpx

            _client = httpx.Client(base_url=url(), headers=_headers(), timeout=TIMEOUT, trust_env=False)
        return _client


def close() -> None:
    global _client
    with _client_lock:
        client, _client = _client, None
    if client is not None:
        client.close()


def _check(response) -> Any:
    if response.status_code >= 400:
        raise RuntimeError(f"ASR service returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as error:
        raise RuntimeError("ASR service returned invalid JSON") from error


# ── in this process ───────────────────────────────────────────────────────


def _engines():
    """The ASR service's engines, from this repository when not installed."""
    try:
        from asr_service import engines
    except ImportError:
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "asr-service" / "src"
            if candidate.is_dir():
                sys.path.insert(0, str(candidate))
                break
        try:
            from asr_service import engines
        except ImportError as error:
            raise RuntimeError("No ASR: set ASR_URL to the ASR service, or install "
                               "apps/asr-service/requirements.txt to recognise in this process") from error
    return engines


# ── the API the voice call uses ───────────────────────────────────────────


def available() -> list[dict[str, Any]]:
    """The recognisers there are (weights present), each with whether it is loaded."""
    if remote():
        return _check(_http().get("/v1/models"))
    return _engines().available()


def load(name: str) -> float:
    """Load *name* if needed. Returns the seconds spent loading (0 if cached)."""
    if remote():
        return float(_check(_http().post(f"/v1/models/{name}/load"))["load_seconds"])
    return _engines().load(name)


def metadata(name: str) -> dict:
    if remote():
        return _check(_http().get(f"/v1/models/{name}/artifact"))
    return _engines().metadata(name)


def transcribe(name: str, samples: np.ndarray, hotwords: list[str] | None = None, *, denoiser: str | None = None) -> Transcript:
    """One utterance, float32 mono at 16 kHz -> text."""
    denoiser = denoiser if denoiser is not None else os.environ.get("ASR_DENOISER", "none")
    if denoiser not in ("none", "rnnoise"):
        raise ValueError("denoiser must be none or rnnoise")
    samples = np.ascontiguousarray(samples, dtype="<f4")
    if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
        raise ValueError("ASR requires finite, nonempty mono samples")
    if remote():
        result = _check(_http().post(
            "/v1/transcribe",
            params={"model": name, "hotwords": ",".join(hotwords or []), "denoiser": denoiser},
            content=samples.tobytes(),
            headers={"Content-Type": "application/octet-stream"},
        ))
        if (not isinstance(result, dict) or result.get("model") != name or not isinstance(result.get("text"), str)
                or any(type(result.get(key)) not in (int, float) or not math.isfinite(result[key]) or result[key] < 0
                       for key in ("seconds", "audio_seconds"))
                or abs(result["audio_seconds"] - len(samples) / RATE) > .01):
            raise RuntimeError("ASR service response does not match the requested model/audio")
        preprocessing = result.get("preprocessing") or {"name": "none"}
        if not isinstance(preprocessing, dict) or preprocessing.get("name") != denoiser:
            raise RuntimeError("ASR service preprocessing does not match request")
        for key in ("denoise_seconds", "decoder_seconds"):
            value = result.get(key)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise RuntimeError("Invalid ASR preprocessing timing")
            if denoiser != "none" and value is None:
                raise RuntimeError("ASR service omitted requested denoiser timing")
        return Transcript(result["model"], result["text"], result["seconds"], result["audio_seconds"],
                          result.get("denoise_seconds", 0.0), result.get("decoder_seconds"), preprocessing)
    found = (_engines().recognize(name, samples, hotwords, denoiser=denoiser) if denoiser != "none"
             else _engines().transcribe(name, samples, hotwords))
    return Transcript(found.model, found.text, found.seconds, found.audio_seconds,
                      getattr(found, "denoise_seconds", 0.0), getattr(found, "decoder_seconds", None),
                      getattr(found, "preprocessing", None))


async def stream(
    name: str, chunks: AsyncIterator[np.ndarray], *, sample_rate: int = RATE,
    hotwords: list[str] | None = None, partial_ms: int = 600, denoiser: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Realtime: send *chunks* (float32 mono at *sample_rate*) as they come and
    yield the service's messages, ``partial`` while audio arrives and one
    ``final`` when *chunks* ends. Needs ``ASR_URL``."""
    import asyncio

    import websockets

    if not remote():
        raise RuntimeError("Realtime ASR needs the ASR service (ASR_URL)")
    denoiser = denoiser if denoiser is not None else os.environ.get("ASR_DENOISER", "none")
    if denoiser not in ("none", "rnnoise"):
        raise ValueError("denoiser must be none or rnnoise")
    address = url().replace("http", "ws", 1) + "/v1/stream"
    async with websockets.connect(address, additional_headers=_headers(), max_size=256 * 1024,
                                  max_queue=8, open_timeout=5, proxy=None) as ws:
        await asyncio.wait_for(ws.send(json.dumps({"model": name, "sample_rate": sample_rate,
                                                   "hotwords": hotwords or [], "partial_ms": partial_ms, "denoiser": denoiser})), TIMEOUT)
        ready = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT))
        if (not isinstance(ready, dict) or ready.get("type") != "ready"
                or ready.get("model", name) != name or ready.get("denoiser", "none") != denoiser):
            raise RuntimeError("ASR stream refused")
        queue: asyncio.Queue[dict[str, Any] | Exception | None] = asyncio.Queue(maxsize=8)

        async def read() -> None:
            try:
                async for message in ws:
                    item = json.loads(message)
                    if not isinstance(item, dict) or item.get("type") not in {"partial", "final", "error"}:
                        raise ValueError("Invalid ASR stream frame")
                    if not isinstance(item.get("text"), str) or item.get("model", name) != name:
                        raise ValueError("Invalid ASR transcript/model")
                    await queue.put(item)
                    if item["type"] == "final":
                        break
            except Exception as error:
                await queue.put(error)
            finally:
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass

        async def write() -> None:
            try:
                async for chunk in chunks:
                    await asyncio.wait_for(ws.send(np.ascontiguousarray(chunk, dtype="<f4").tobytes()), TIMEOUT)
                await asyncio.wait_for(ws.send(json.dumps({"type": "end"})), TIMEOUT)
            except Exception as error:
                await queue.put(error)
            finally:
                close = getattr(chunks, "aclose", None)
                if close is not None:
                    await close()

        reader, sender = asyncio.create_task(read()), asyncio.create_task(write())
        try:
            while True:
                if reader.done() and queue.empty():
                    raise RuntimeError("ASR stream ended without a final transcript")
                item = await asyncio.wait_for(queue.get(), TIMEOUT)
                if item is None:
                    raise RuntimeError("ASR stream ended without a final transcript")
                if isinstance(item, Exception):
                    raise RuntimeError("ASR stream failed") from item
                if item["type"] == "error":
                    raise RuntimeError("ASR recognizer rejected the stream")
                yield item
                if item["type"] == "final":
                    break
        finally:
            for task in (reader, sender):
                task.cancel()
            await asyncio.gather(reader, sender, return_exceptions=True)
