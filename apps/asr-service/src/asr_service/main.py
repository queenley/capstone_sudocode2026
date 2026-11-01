"""The ASR service: speech in, Vietnamese text out, on its own machine.

    uvicorn asr_service.main:app --app-dir apps/asr-service/src --port 8500

Two ways in, both float32 mono PCM (little endian):

- ``POST /v1/transcribe?model=zipformer-30m&hotwords=AirPure,Xiaomi`` with the
  samples of one utterance at 16 kHz as the body (``application/octet-stream``)
  -> ``{text, model, seconds, audio_seconds, rtf}``. What the agent's voice
  call uses: its own VAD and turn detector decide where an utterance ends.
- ``WS /v1/stream``, realtime. First a text frame ``{"model", "sample_rate",
  "hotwords", "partial_ms"}``; then binary frames of samples at that rate. The
  service answers ``{"type": "ready"}``, then ``{"type": "partial", "text"}``
  as the utterance grows (every ``partial_ms`` of new audio, default 600), and
  ``{"type": "final", "text", ...}`` after a ``{"type": "end"}`` frame, which
  also starts the next utterance. ``{"type": "reset"}`` drops what was heard.
  The recognisers here are offline models, so a partial is the utterance so
  far decoded again: cheap on a GPU, and the protocol stays the same when a
  streaming model takes their place.

Also ``GET /v1/models``, ``POST /v1/models/{name}/load``, ``GET /health`` and
``GET /health/ready`` (ready once the models in ``ASR_PRELOAD`` are loaded).

``ASR_API_KEY``, when set, is required as ``Authorization: Bearer <key>`` (or
``?token=`` on the WebSocket): set it whenever the service is reachable from
outside, e.g. on a rented GPU.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from . import engines, fetch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("asr-service")

API_KEY = os.environ.get("ASR_API_KEY", "").strip()
PRELOAD = [name.strip() for name in os.environ.get("ASR_PRELOAD", "zipformer-30m").split(",") if name.strip()]
#: The longest utterance accepted, in seconds of audio.
MAX_SECONDS = float(os.environ.get("ASR_MAX_SECONDS", "120"))

state: dict[str, Any] = {"ready": False, "error": None, "loaded_in": None}


async def _prepare() -> None:
    """Fetch what is missing, then load ASR_PRELOAD, off the request path."""
    started = time.perf_counter()
    try:
        if os.environ.get("ASR_FETCH", "1") != "0":
            await asyncio.to_thread(fetch.fetch_all)
        for name in PRELOAD:
            seconds = await asyncio.to_thread(engines.load, name)
            # One short decode, so the first real call pays no warm-up.
            await asyncio.to_thread(engines.transcribe, name, np.zeros(engines.RATE // 2, dtype=np.float32))
            logger.info("Loaded %s in %.1f s on %s", name, seconds, engines.DEVICE)
        state.update(ready=True, loaded_in=round(time.perf_counter() - started, 1))
        logger.info("ASR ready in %.1f s: %s", time.perf_counter() - started, ", ".join(PRELOAD))
    except Exception as error:  # noqa: BLE001 - reported by /health/ready
        state["error"] = f"{type(error).__name__}: {error}"
        logger.exception("ASR preparation failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_prepare())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="ASR service", version="1.0.0", lifespan=lifespan)


def _authorised(given: str) -> bool:
    return not API_KEY or hmac.compare_digest(given.encode(), API_KEY.encode())


def require_key(request: Request) -> None:
    header = request.headers.get("authorization", "")
    if not _authorised(header.removeprefix("Bearer ").strip()):
        raise HTTPException(401, "Missing or wrong ASR_API_KEY")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "device": engines.DEVICE, "ready": state["ready"], "error": state["error"]}


@app.get("/health/ready")
def ready() -> JSONResponse:
    body = {"ready": state["ready"], "preload": PRELOAD, "loaded_in": state["loaded_in"], "error": state["error"]}
    return JSONResponse(body, status_code=200 if state["ready"] else 503)


@app.get("/v1/models", dependencies=[Depends(require_key)])
def models() -> list[dict[str, object]]:
    return engines.available()


@app.post("/v1/models/{name}/load", dependencies=[Depends(require_key)])
async def load(name: str) -> dict[str, Any]:
    try:
        seconds = await asyncio.to_thread(engines.load, name)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(409, f"{name}: weights missing ({error}); run python -m asr_service.fetch") from error
    return {"model": name, "load_seconds": round(seconds, 2), "device": engines.DEVICE}


@app.get("/v1/models/{name}/artifact", dependencies=[Depends(require_key)])
def artifact(name: str) -> dict:
    try:
        return engines.metadata(name)
    except KeyError as error:
        raise HTTPException(404, "Unknown ASR model") from error


def _samples(body: bytes) -> np.ndarray:
    if len(body) % 4:
        raise HTTPException(400, "The body must be float32 samples (a multiple of 4 bytes)")
    samples = np.frombuffer(body, dtype="<f4")
    if not samples.size or not np.isfinite(samples).all():
        raise HTTPException(400, "Audio must contain finite samples")
    if samples.size > MAX_SECONDS * engines.RATE:
        raise HTTPException(413, f"At most {MAX_SECONDS:.0f} s of audio per request")
    return samples


def _result(transcript: engines.Transcript) -> dict[str, Any]:
    return {"text": transcript.text, "model": transcript.model, "seconds": round(transcript.seconds, 3),
            "audio_seconds": round(transcript.audio_seconds, 3), "rtf": round(transcript.rtf, 3)}


@app.post("/v1/transcribe", dependencies=[Depends(require_key)])
async def transcribe(
    request: Request,
    model: str = Query("zipformer-30m", max_length=64),
    hotwords: str = Query("", max_length=2000),
) -> dict[str, Any]:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_SECONDS * engines.RATE * 4:
            raise HTTPException(413, "Audio is too long")
    samples = _samples(bytes(body))
    words = [word.strip() for word in hotwords.split(",") if word.strip()]
    try:
        transcript = await asyncio.to_thread(engines.transcribe, model, samples, words)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(409, "Local model weights missing or incomplete") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return _result(transcript)


# ── realtime ──────────────────────────────────────────────────────────────


class Stream:
    """One caller's audio as it arrives: partials while they speak, a final on "end"."""

    def __init__(self, model: str, sample_rate: int, hotwords: list[str], partial_ms: int) -> None:
        self.model, self.hotwords = model, hotwords
        self.partial_every = max(0.2, partial_ms / 1000) * engines.RATE
        self.resampler = None
        if sample_rate != engines.RATE:
            import soxr

            self.resampler = soxr.ResampleStream(sample_rate, engines.RATE, 1, dtype="float32")
        self.chunks: list[np.ndarray] = []
        self.size = 0
        self.since_partial = 0
        self.last_partial = ""
        self.decoding: asyncio.Task[Any] | None = None
        self.generation = 0

    def add(self, data: bytes) -> None:
        if not data or len(data) % 4 or len(data) > 256 * 1024:
            raise ValueError("Audio frame is invalid or too large")
        samples = np.frombuffer(data, dtype="<f4")
        if not np.isfinite(samples).all():
            raise ValueError("Audio samples must be finite")
        if self.resampler is not None:
            samples = self.resampler.resample_chunk(samples)
        if self.size + samples.size > MAX_SECONDS * engines.RATE:
            raise ValueError(f"utterance longer than {MAX_SECONDS:.0f} s: send an end frame")
        self.chunks.append(samples.astype(np.float32, copy=False))
        self.size += samples.size
        self.since_partial += samples.size

    def audio(self) -> np.ndarray:
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, dtype=np.float32)

    def finish(self) -> np.ndarray:
        if self.resampler is not None:
            tail = self.resampler.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
            if self.size + tail.size > MAX_SECONDS * engines.RATE:
                raise ValueError("Audio is too long")
            self.chunks.append(tail)
        return self.audio()

    def reset(self) -> None:
        self.generation += 1
        self.chunks, self.size, self.since_partial, self.last_partial = [], 0, 0, ""
        if self.resampler is not None:
            self.resampler.clear()


@app.websocket("/v1/stream")
async def stream(ws: WebSocket, token: str = "") -> None:
    given = token or ws.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not _authorised(given):
        await ws.close(code=4401)
        return
    await ws.accept()
    send_lock = asyncio.Lock()

    async def send(payload: dict[str, Any]) -> None:
        async with send_lock:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))

    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        if len(raw) > 16 * 1024:
            raise ValueError("Configuration too large")
        config = json.loads(raw)
        if not isinstance(config, dict):
            raise ValueError("Configuration must be an object")
        model = str(config.get("model") or "zipformer-30m")
        rate = int(config.get("sample_rate", engines.RATE))
        words = config.get("hotwords", [])
        partial_ms = int(config.get("partial_ms", 600))
        if (not 8000 <= rate <= 192000 or not 200 <= partial_ms <= 10000 or not isinstance(words, list)
                or len(words) > 100 or any(not isinstance(w, str) or len(w) > 100 for w in words)):
            raise ValueError("Invalid sample rate, partial interval or hotwords")
        await asyncio.to_thread(engines.load, model)
        session = Stream(model, rate, words, partial_ms)
    except WebSocketDisconnect:
        return
    except (KeyError, ValueError, TypeError, OverflowError, FileNotFoundError, asyncio.TimeoutError):
        await ws.send_text(json.dumps({"type": "error", "text": "ASR configuration or local weights are unavailable"}))
        await ws.close(code=4400)
        return
    await send({"type": "ready", "model": model, "device": engines.DEVICE})

    async def partial(audio: np.ndarray, generation: int) -> None:
        try:
            transcript = await asyncio.to_thread(engines.transcribe, session.model, audio, session.hotwords)
        except Exception:
            if generation == session.generation:
                await send({"type": "error", "text": "Local ASR decoding failed"})
            return
        if generation == session.generation and transcript.text and transcript.text != session.last_partial:
            session.last_partial = transcript.text
            await send({"type": "partial", "text": transcript.text, "audio_seconds": round(transcript.audio_seconds, 2)})

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                try:
                    session.add(message["bytes"])
                except ValueError as error:
                    await send({"type": "error", "text": str(error)})
                    continue
                # A new partial when enough new audio arrived and none is being decoded.
                if session.since_partial >= session.partial_every and (session.decoding is None or session.decoding.done()):
                    session.since_partial = 0
                    session.decoding = asyncio.create_task(partial(session.audio(), session.generation))
                continue
            try:
                raw = message.get("text") or "{}"
                if len(raw) > 16 * 1024:
                    raise ValueError("Control too large")
                control = json.loads(raw)
                if not isinstance(control, dict):
                    raise ValueError("Control must be an object")
            except ValueError:
                await send({"type": "error", "text": "Invalid control frame"})
                continue
            if control.get("type") == "end":
                if session.decoding is not None:
                    session.decoding.cancel()
                    await asyncio.gather(session.decoding, return_exceptions=True)
                audio = session.finish()
                session.reset()
                if not audio.size:
                    await send({"type": "final", "text": "", "model": session.model, "seconds": 0, "audio_seconds": 0, "rtf": 0})
                    continue
                transcript = await asyncio.to_thread(engines.transcribe, session.model, audio, session.hotwords)
                await send({"type": "final", **_result(transcript)})
            elif control.get("type") == "reset":
                if session.decoding is not None:
                    session.decoding.cancel()
                    await asyncio.gather(session.decoding, return_exceptions=True)
                session.reset()
    except WebSocketDisconnect:
        pass
    except (ValueError, RuntimeError, FileNotFoundError):
        await send({"type": "error", "text": "Local ASR decoding failed"})
    finally:
        if session.decoding is not None:
            session.decoding.cancel()
            await asyncio.gather(session.decoding, return_exceptions=True)
