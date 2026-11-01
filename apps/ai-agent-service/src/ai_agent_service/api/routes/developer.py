"""Developer / admin endpoints: the advisor's model, traces, voice, business day, latency.

Ported from the reference ``api/admin.py``. Runtime choices live in this
process only (``runtime.options``); a restart returns to ``config/models.yaml``.
Staff with the ``admin`` or ``developer`` role only.

``/api/developer/model`` keeps the web console's contract
(``apps/web/src/features/agent-console.tsx``): ``{provider, model, configured,
overridden, choices: [{provider, model}]}``.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from src.api.routes.shared import staff

from ...components import btc_schemas, voice as voice_component
from ...config.config_manager import get_models_config, has_api_key
from ...runtime import calls, harness, options
from ...runtime.db import connection

router = APIRouter(prefix="/api/developer", tags=["developer"])
ROLES = {"admin", "developer"}


class GapResolution(BaseModel):
    answer: str = Field(min_length=3, max_length=4000)
    cites: list[str] = Field(min_length=1, max_length=20)
    approved: Literal[True]


@router.get("/knowledge-gaps")
async def knowledge_gaps(request: Request):
    _guard(request)
    from ...components.improvement import gaps
    return await asyncio.to_thread(gaps.list_gaps)


@router.post("/knowledge-gaps/{gap_id}/resolve")
async def resolve_gap(gap_id: str, body: GapResolution, request: Request):
    _guard(request)
    from ...components.improvement import gaps
    try:
        version = await asyncio.to_thread(gaps.resolve, gap_id, answer=body.answer, cites=body.cites,
                                                       reviewer=str(request.state.actor_id))
    except KeyError as error:
        raise HTTPException(404, "Knowledge gap not found") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"status": "resolved", "knowledge_version": version, "reload_required": True}


def _guard(request: Request) -> None:
    staff(request, ROLES)


# ── the advisor's model ───────────────────────────────────────────────────


class ModelSelection(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)


class AdvisorUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


def _choices() -> list[dict[str, str]]:
    config = get_models_config()
    return [{"provider": name, "model": model, "label": f"{block.label}: {model}"}
            for name, block in config.providers.items() if has_api_key(name) for model in block.models]


def _advisor_report() -> dict[str, Any]:
    routed = get_models_config().agent_llm_config("advisor")
    current = options.advisor_overrides()
    running = harness.status()
    provider = current.get("provider") or routed["provider"]
    return {
        "provider": provider,
        "model": running.get("model") or current.get("model") or routed["model"],
        "temperature": current.get("temperature", routed.get("temperature")),
        "configured": has_api_key(provider),
        "overridden": bool(current),
        "default_provider": routed["provider"],
        "default_model": routed["model"],
        "choices": _choices(),
    }


async def _rebuild(provider: str | None, model: str | None, temperature: float | None) -> None:
    if provider is not None and not any(c["provider"] == provider and c["model"] == model for c in _choices()):
        raise HTTPException(422, "That model is not configured on this server (config/models.yaml + provider key).")
    try:
        await harness.rebuild_advisor(provider=provider, model=model, temperature=temperature)
    except Exception as error:  # noqa: BLE001 - the operator needs the reason
        raise HTTPException(400, f"Could not build the advisor: {error}") from error


@router.get("/model")
async def current_model(request: Request) -> dict[str, Any]:
    _guard(request)
    return _advisor_report()


@router.put("/model")
async def select_model(data: ModelSelection, request: Request) -> dict[str, Any]:
    _guard(request)
    await _rebuild(data.provider.strip(), data.model.strip(), options.advisor_overrides().get("temperature"))
    return _advisor_report()


@router.delete("/model")
async def reset_model(request: Request) -> dict[str, Any]:
    _guard(request)
    await _rebuild(None, None, None)
    return _advisor_report()


@router.post("/advisor")
async def set_advisor(body: AdvisorUpdate, request: Request) -> dict[str, Any]:
    """Model and temperature together; an empty body resets to the file."""
    _guard(request)
    if (body.provider is None) != (body.model is None):
        raise HTTPException(422, "Give provider and model together.")
    await _rebuild(body.provider, body.model, body.temperature)
    return _advisor_report()


# ── traces ────────────────────────────────────────────────────────────────


@router.get("/traces")
async def traces(request: Request) -> list[dict[str, Any]]:
    """The last 100 agent turns, from the agent transcript (lane, guard, tools, latency)."""
    _guard(request)
    rows = await calls.recent_agent_turns(100)
    out = []
    for row in rows:
        meta = row["meta"] or {}
        guard = meta.get("guard") or {}
        reasons = list((guard.get("hard") or {}).get("reasons") or []) + list((guard.get("soft") or {}).get("reasons") or [])
        errors = ([{"stage": "advisor", "type": meta["error"]}] if meta.get("error") else []) + \
                 [{"stage": "guard", "type": r} for r in reasons]
        latency = meta.get("latency") or {}
        out.append({
            "trace_id": f"{row['call_id']}:{row['turn_id']}",
            "pipeline": "hot-graph",
            "route": meta.get("lane"),
            "confidence": 1.0 if meta.get("lane") else 0.0,
            "latency_ms": latency.get("total_ms"),
            "usage": {"model_calls": meta.get("model_calls") or 0, "regenerations": meta.get("regenerations") or 0},
            "errors": errors,
            "tools": [{"name": t.get("name"), "status": "success" if (t.get("result") or {}).get("ok") else "failed",
                       "latency_ms": None} for t in meta.get("tool_calls") or []],
            "tier": meta.get("tier"),
            "model": meta.get("model"),
        })
    return out


@router.get("/calls/{call_id}/trace", response_model=None)
async def call_trace(
    call_id: int,
    request: Request,
    scenario_id: str = Query(min_length=1, max_length=64),
    call: Literal["call_1", "call_2", "call_3"] = "call_1",
    config: Literal["full", "baseline_no_memory"] = "full",
    run_id: str = Query(default="run", max_length=64),
    format: Literal["json", "jsonl"] = "json",
) -> Any:
    """One stored call as the organisers' ``trace_log`` rows, labelled with the scenario it played.

    ``json`` returns the rows with each one's violations of
    ``schemas/trace_log.schema.json``; ``jsonl`` is the file ``reference_eval.py
    --trace`` reads (append the calls of a run together).
    """
    _guard(request)
    try:
        rows = await calls.trace_rows(call_id, scenario_id=scenario_id, call_label=call, config=config, run_id=run_id)
    except calls.CallError as error:
        raise HTTPException(error.status, str(error)) from error
    if format == "jsonl":
        return PlainTextResponse("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows),
                                 media_type="application/x-ndjson")
    problems = {r["turn"]: btc_schemas.errors("trace_log", json.loads(json.dumps(r, default=str))) for r in rows}
    return {"rows": rows, "schema_errors": {turn: e for turn, e in problems.items() if e}}


@router.get("/sessions")
async def sessions(request: Request) -> dict[str, int]:
    _guard(request)
    return await calls.session_counts()


# ── voice ─────────────────────────────────────────────────────────────────


class VoiceUpdate(BaseModel):
    asr: str | None = None
    endpointing: str | None = None
    barge_in_ms: int | None = Field(default=None, ge=100, le=2000)
    min_interruption_words: int | None = Field(default=None, ge=0, le=6)
    tts: str | None = None
    reset: bool = False


ENDPOINTING = [{"name": "smart", "label": "Smart Turn v3.2, 1.2 s ceiling"},
               {"name": "silence-500", "label": "Silence 500 ms"},
               {"name": "silence-800", "label": "Silence 800 ms"}]


def _voice_report() -> dict[str, Any]:
    current = options.voice()
    ready = voice_component.status()
    asr_choices: list[dict[str, Any]] = []
    tts_choices: list[dict[str, str]] = [{"name": current.tts, "label": current.tts}]
    if ready["status"] == "ok":
        from ...components.voice import asr, tts
        asr_choices = asr.available()
        tts_choices = tts.voices()
    return {"asr": current.asr, "endpointing": current.endpointing, "barge_in_ms": current.barge_in_ms,
            "min_interruption_words": current.min_interruption_words, "tts": current.tts,
            "overridden": options.voice_overridden(), "available": ready, "asr_choices": asr_choices,
            "endpointing_choices": ENDPOINTING, "tts_choices": tts_choices}


@router.get("/voice")
async def get_voice(request: Request) -> dict[str, Any]:
    _guard(request)
    return _voice_report()


@router.post("/voice")
async def set_voice(body: VoiceUpdate, request: Request) -> dict[str, Any]:
    _guard(request)
    report = _voice_report()
    if body.asr and report["asr_choices"] and body.asr not in {c["name"] for c in report["asr_choices"]}:
        raise HTTPException(422, f"{body.asr} is not installed here.")
    if body.endpointing and body.endpointing not in {c["name"] for c in ENDPOINTING}:
        raise HTTPException(422, "Unknown endpointing.")
    options.set_voice(asr=body.asr, endpointing=body.endpointing, barge_in_ms=body.barge_in_ms,
                      min_interruption_words=body.min_interruption_words, tts=body.tts, reset=body.reset)
    return _voice_report()


@router.post("/voice/warm")
async def warm_voice(request: Request) -> dict[str, Any]:
    _guard(request)
    if voice_component.status()["status"] != "ok":
        raise HTTPException(409, "Voice is not ready on this server: " + str(voice_component.status()["hint"]))
    from .voice import warm
    return await warm()


# ── the business day ──────────────────────────────────────────────────────


class BusinessDay(BaseModel):
    day: str | None = Field(default=None, description="YYYY-MM-DD; empty returns to the reference day")


@router.get("/clock")
async def get_clock(request: Request) -> dict[str, str]:
    _guard(request)
    return {"day": options.business_day(), "time": "10:00", "zone": "Asia/Ho_Chi_Minh"}


@router.post("/clock")
async def set_clock(body: BusinessDay, request: Request) -> dict[str, str]:
    """The organisers' data is written for 2026-10-15; advancing the day is how a demo shows call 2."""
    _guard(request)
    try:
        day = options.set_business_day(body.day)
    except ValueError as error:
        raise HTTPException(422, "Give the day as YYYY-MM-DD.") from error
    return {"day": day, "time": "10:00", "zone": "Asia/Ho_Chi_Minh"}


# ── latency, data/btc/eval/huong-dan-do-latency.md ────────────────────────

THRESHOLDS_MS = {"ttft": 3000, "total": 8000, "ttfa": 2500, "call_brief": 3000}


def p95(values: list[int]) -> int | None:
    """``eval/reference_eval.py``'s p95, exactly."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * len(ordered) + 0.5)) - 1)]


def _stats(values: list[int]) -> dict[str, Any] | None:
    return {"n": len(values), "p50_ms": int(statistics.median(values)), "p95_ms": int(p95(values))} if values else None


@router.get("/latency")
async def latency(request: Request, channel: Literal["all", "web", "zalo", "hotline", "facebook"] = "all",
                  days: int = Query(default=7, ge=1, le=90)) -> dict[str, Any]:
    """p50 and p95 of the organisers' four figures over agent turns, warm-up excluded."""
    _guard(request)
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT t.meta->'latency' AS latency FROM turns t JOIN calls c ON c.id = t.call_id "
            "WHERE t.speaker = 'agent' AND t.meta ? 'latency' AND t.created_at > now() - %s * interval '1 day' "
            + ("" if channel == "all" else "AND c.channel = %s "),
            (days,) if channel == "all" else (days, channel),
        )
        rows = await cursor.fetchall()
    figures: dict[str, list[int]] = {"ttft": [], "total": [], "ttfa": [], "call_brief": [], "ttfa_client": []}
    warmup = 0
    for row in rows:
        entry = row["latency"] or {}
        if entry.get("warmup"):
            warmup += 1
            continue
        for name, key in (("ttft", "ttft_ms"), ("total", "total_ms"), ("ttfa", "ttfa_ms"),
                          ("call_brief", "call_brief_latency_ms"), ("ttfa_client", "ttfa_client_ms")):
            if entry.get(key) is not None:
                figures[name].append(int(entry[key]))
    n = len(figures["ttft"])
    return {"turns": n, "warmup_excluded": warmup,
            "warning": None if n >= 100 else "Under 100 turns: the organisers ask for at least 100 before p95 means much.",
            "streaming": False, "thresholds_ms": THRESHOLDS_MS, **{name: _stats(values) for name, values in figures.items()}}
