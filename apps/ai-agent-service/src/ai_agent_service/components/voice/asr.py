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

            _client = httpx.Client(base_url=url(), headers=_headers(), timeout=TIMEOUT)
        return _client


def _check(response) -> Any:
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:200]
        raise RuntimeError(f"ASR service {response.status_code}: {detail}")
    return response.json()


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


def transcribe(name: str, samples: np.ndarray, hotwords: list[str] | None = None) -> Transcript:
    """One utterance, float32 mono at 16 kHz -> text."""
    samples = np.ascontiguousarray(samples, dtype="<f4")
    if remote():
        result = _check(_http().post(
            "/v1/transcribe",
            params={"model": name, "hotwords": ",".join(hotwords or [])},
            content=samples.tobytes(),
            headers={"Content-Type": "application/octet-stream"},
        ))
        return Transcript(result["model"], result["text"], result["seconds"], result["audio_seconds"])
    found = _engines().transcribe(name, samples, hotwords)
    return Transcript(found.model, found.text, found.seconds, found.audio_seconds)


async def stream(
    name: str, chunks: AsyncIterator[np.ndarray], *, sample_rate: int = RATE,
    hotwords: list[str] | None = None, partial_ms: int = 600,
) -> AsyncIterator[dict[str, Any]]:
    """Realtime: send *chunks* (float32 mono at *sample_rate*) as they come and
    yield the service's messages, ``partial`` while audio arrives and one
    ``final`` when *chunks* ends. Needs ``ASR_URL``."""
    import asyncio

    import websockets

    if not remote():
        raise RuntimeError("Realtime ASR needs the ASR service (ASR_URL)")
    address = url().replace("http", "ws", 1) + "/v1/stream"
    async with websockets.connect(address, additional_headers=_headers(), max_size=None) as ws:
        await ws.send(json.dumps({"model": name, "sample_rate": sample_rate,
                                  "hotwords": hotwords or [], "partial_ms": partial_ms}))
        ready = json.loads(await ws.recv())
        if ready.get("type") != "ready":
            raise RuntimeError(f"ASR stream refused: {ready}")
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def read() -> None:
            async for message in ws:
                item = json.loads(message)
                await queue.put(item)
                if item.get("type") == "final":
                    break
            await queue.put(None)

        reader = asyncio.create_task(read())
        try:
            async for chunk in chunks:
                await ws.send(np.ascontiguousarray(chunk, dtype="<f4").tobytes())
                while not queue.empty():
                    item = queue.get_nowait()
                    if item is not None:
                        yield item
            await ws.send(json.dumps({"type": "end"}))
            while (item := await queue.get()) is not None:
                yield item
        finally:
            reader.cancel()
