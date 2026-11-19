"""A small TTS server for a GPU host (Colab): POST /v1/tts streams 16-bit PCM as it is made.

Engines: zerotts (zeroweight-ai/ZeroTTS, ONNX on CUDA when it loads, else CPU) and vieneu (VieNeu-TTS v3 Turbo).
Auth: Authorization: Bearer $TTS_API_KEY. Run: uvicorn tts_server:app --host 0.0.0.0 --port 8600
Every error answers JSON with the traceback, so a caller sees why.
"""
import os
import threading
import time
import traceback

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

KEY = os.environ.get("TTS_API_KEY", "")
app = FastAPI()
_engines: dict = {}
_devices: dict = {}
_locks: dict = {}


@app.exception_handler(Exception)
async def _any(request: Request, error: Exception):
    return JSONResponse(status_code=500, content={"error": repr(error), "trace": traceback.format_exc()[-3000:]})


def _check(request: Request) -> None:
    if KEY and request.headers.get("authorization") != f"Bearer {KEY}":
        raise HTTPException(401, "Bearer token required")


def _zerotts():
    from huggingface_hub import snapshot_download
    from zerotts import ZeroTTS
    # Real files in one folder: onnxruntime refuses external weights that resolve outside the model's folder,
    # which the hub cache's symlinked blobs do.
    folder = snapshot_download("zeroweight-ai/ZeroTTS", local_dir="/content/zerotts")
    import onnxruntime
    try:
        onnxruntime.preload_dlls()  # the CUDA and cuDNN libraries pip installed (nvidia-*-cu12)
    except Exception:  # noqa: BLE001 - an older onnxruntime has no preload; CUDA may still load
        pass
    if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
        try:
            model = ZeroTTS.from_pretrained(folder,
                                            providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
            list(model.synthesize_stream("Dạ.", voice=model.list_voices()[0]))  # CUDA fails here, not at load
            return model, "cuda"
        except Exception:  # noqa: BLE001 - fall back to the CPU rather than no voice
            traceback.print_exc()
    return ZeroTTS.from_pretrained(folder, providers=["CPUExecutionProvider"]), "cpu"


def engine(name: str):
    if name in _engines:
        return _engines[name]
    _locks.setdefault(name, threading.Lock())
    with _locks[name]:
        if name in _engines:
            return _engines[name]
        if name == "zerotts":
            _engines[name], _devices[name] = _zerotts()
        elif name == "vieneu":
            from vieneu import Vieneu
            try:
                import torch
                cuda = torch.cuda.is_available()
            except Exception:  # noqa: BLE001 - no torch: the torch-free CPU path
                cuda = False
            # On CUDA, v3 Turbo runs as CUDA graphs: first audio ~170 ms on a T4 (2026-11-19), against ~700 ms on CPU.
            _engines[name], _devices[name] = (Vieneu(device="cuda"), "cuda") if cuda else (Vieneu(), "cpu")
        else:
            raise HTTPException(404, f"unknown engine {name}")
    return _engines[name]


def _rate(tts) -> int:
    return int(getattr(tts, "sample_rate", 24000))


def _chunks(name: str, tts, text: str, voice: str | None):
    if name == "zerotts":
        from zerotts import normalize_vi_text
        yield from tts.synthesize_stream(normalize_vi_text(text), voice=voice or tts.list_voices()[0])
    else:
        yield from tts.infer_stream(text, **({"voice": voice} if voice else {}))


@app.get("/health")
def health():
    return {"status": "ok", "loaded": {name: _devices.get(name) for name in _engines}}


@app.post("/v1/load/{name}")
def load(name: str, request: Request):
    _check(request)
    started = time.perf_counter()
    tts = engine(name)
    voices = tts.list_voices() if hasattr(tts, "list_voices") else []
    return {"engine": name, "device": _devices.get(name), "seconds": round(time.perf_counter() - started, 1),
            "sample_rate": _rate(tts), "voices": [str(v) for v in voices][:50]}


@app.post("/v1/tts")
async def tts(request: Request):
    _check(request)
    body = await request.json()
    name, text, voice = body.get("engine", "zerotts"), str(body.get("text", "")).strip(), body.get("voice")
    if not text:
        raise HTTPException(422, "text is empty")
    model = engine(name)

    def pcm():
        with _locks[name]:  # one sentence at a time per engine
            for chunk in _chunks(name, model, text, voice):
                audio = np.clip(np.asarray(chunk, dtype=np.float32).reshape(-1), -1.0, 1.0)
                yield (audio * 32767).astype("<i2").tobytes()

    return StreamingResponse(pcm(), media_type="application/octet-stream", headers={"X-Sample-Rate": str(_rate(model))})
