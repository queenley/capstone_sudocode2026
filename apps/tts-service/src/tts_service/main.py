"""The TTS service: Vietnamese text in, VieNeu-TTS speech out, streamed, on its own small CPU share.

    uvicorn tts_service.main:app --app-dir apps/tts-service/src --port 8600

The agent's voice call reaches it at ``TTS_URL`` (``components/voice/tts.py``, VieNeuVoice), so the agent pods carry
neither VieNeu's packages nor its 1.4 GB of weights, and synthesis never takes CPU from a turn being reasoned.

- ``POST /v1/speak`` with ``{"text": "...", "voice": null}`` -> the audio as it is made: 16-bit little-endian mono
  PCM, the rate in the ``X-Sample-Rate`` header. The first bytes leave as soon as VieNeu yields its first chunk.
  A client that hangs up (a barge-in) stops the synthesis after the chunk in progress.
- ``GET /health`` (alive) and ``GET /health/ready`` (503 until the model is loaded and warmed).

One engine, one sentence at a time (``TTS_CONCURRENCY``, 1 unless set): on a small CPU share two syntheses at once
only slow each other down; a second caller waits for the first sentence. ONNX Runtime's threads follow
``OMP_NUM_THREADS``, set to the pod's CPU limit. ``TTS_API_KEY``, when set, is required as ``Authorization: Bearer``.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("tts-service")

API_KEY = os.environ.get("TTS_API_KEY", "").strip()
#: The longest text accepted: the agent sends one sentence at a time.
MAX_CHARS = int(os.environ.get("TTS_MAX_CHARS", "600"))
CONCURRENCY = max(1, int(os.environ.get("TTS_CONCURRENCY", "1")))
#: VieNeu's model. v3nano (48M parameters, 24 kHz, ONNX on CPU) is the light one, made for CPUs where v3turbo
#: (48 kHz) cannot keep up: on 2 vCPUs v3turbo took 9 to 13 times longer than the speech it made (2026-11-28).
MODE = os.environ.get("TTS_MODE", "v3nano").strip() or "v3nano"

state: dict[str, Any] = {"ready": False, "error": None, "loaded_in": None, "engine": None, "rate": None}
_slots = threading.BoundedSemaphore(CONCURRENCY)


def _load() -> None:
    from vieneu import Vieneu

    started = time.perf_counter()
    engine = Vieneu(mode=MODE)
    engine.infer("Dạ.")  # the first real sentence pays no warm-up
    state.update(engine=engine, rate=int(engine.sample_rate), ready=True,
                 loaded_in=round(time.perf_counter() - started, 1))
    logger.info("VieNeu %s ready in %.1f s (%s Hz, %s threads)", MODE, state["loaded_in"], state["rate"],
                os.environ.get("OMP_NUM_THREADS", "all"))


async def _prepare() -> None:
    try:
        await asyncio.to_thread(_load)
    except Exception as error:  # noqa: BLE001 - reported by /health/ready
        state["error"] = f"{type(error).__name__}: {error}"
        logger.exception("TTS preparation failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_prepare())
    yield
    task.cancel()


app = FastAPI(title="tts-service", lifespan=lifespan)


def authorised(request: Request) -> None:
    if not API_KEY:
        return
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given, API_KEY):
        raise HTTPException(401, "TTS_API_KEY required")


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str | None = None


def pcm16(chunk: Any) -> bytes:
    audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


async def _speak(text: str, voice: str | None) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[object] = asyncio.Queue()
    stop = threading.Event()
    engine = state["engine"]

    def work() -> None:
        try:
            with _slots:
                kwargs = {"voice": voice} if voice else {}
                for chunk in engine.infer_stream(text, **kwargs):
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, pcm16(chunk))
        except Exception as error:  # noqa: BLE001 - logged; the stream just ends
            logger.exception("Synthesis failed")
            loop.call_soon_threadsafe(queue.put_nowait, error)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    worker = loop.run_in_executor(None, work)
    try:
        while (item := await queue.get()) is not None:
            if isinstance(item, Exception):
                break
            yield item
    finally:
        # The caller hung up or the sentence is done: the thread stops after its current chunk.
        stop.set()
        await worker


@app.post("/v1/speak", dependencies=[Depends(authorised)])
async def speak(body: SpeakRequest) -> StreamingResponse:
    if not state["ready"]:
        raise HTTPException(503, state["error"] or "VieNeu is still loading")
    text = body.text.strip()
    if len(text) > MAX_CHARS:
        raise HTTPException(413, f"at most {MAX_CHARS} characters a request: send one sentence at a time")
    return StreamingResponse(_speak(text, body.voice), media_type="application/octet-stream",
                             headers={"X-Sample-Rate": str(state["rate"]), "X-Sample-Format": "s16le"})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> JSONResponse:
    body = {"ready": state["ready"], "error": state["error"], "loaded_in": state["loaded_in"],
            "sample_rate": state["rate"], "concurrency": CONCURRENCY, "mode": MODE}
    return JSONResponse(body, status_code=200 if state["ready"] else 503)
