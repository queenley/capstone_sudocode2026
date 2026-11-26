"""The developer console's live view: each agent turn as it is stored, with its model, tokens, cost, tools and guard.

- ``GET /api/developer/live/turns?after=<id>``: the latest agent turns (newest first), or those after *id*;
- ``GET /api/developer/live/stream?after=<id>``: the same rows as server-sent events, as they are written. The stream
  ends after :data:`STREAM_SECONDS` and the page reconnects from the last id it saw, so no proxy timeout cuts it;
- ``GET /api/developer/live/summary?minutes=15``: what those turns add up to: p50/p95, tokens, cost, tool failures.

Everything comes from the agent's own ``turns`` table (the source of truth, ``llm/tracing.py``); a turn's prompt and
the model's tree of calls stay in Langfuse, linked per turn when ``LANGFUSE_HOST`` and ``LANGFUSE_PROJECT_ID`` are set.
Text is never sent: only what the turn did. Staff with the ``admin`` or ``developer`` role only.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from src.api.routes.shared import staff

from ...runtime import load
from ...runtime.db import connection

router = APIRouter(prefix="/api/developer/live", tags=["developer"])
ROLES = {"admin", "developer"}
POLL_SECONDS = 1.5
HEARTBEAT_SECONDS = 15.0
STREAM_SECONDS = 100.0  # under the 120 s the web proxy (app/backend) and the gateway give a /stream

_COLUMNS = ("SELECT t.id, t.call_id, t.turn_id, t.meta, t.created_at, c.channel, c.customer_id, c.mode "
            "FROM turns t JOIN calls c ON c.id = t.call_id "
            "WHERE t.speaker = 'agent' AND NOT (t.meta ? 'bridging') ")


def langfuse_url(session_id: str | None) -> str | None:
    """The turn's Langfuse session (the advisor traces under the customer's id, else the call's): a link, not data."""
    host, project = os.getenv("LANGFUSE_HOST", "").rstrip("/"), os.getenv("LANGFUSE_PROJECT_ID", "")
    if not (host and project and session_id):
        return None
    return f"{host}/project/{quote(project)}/sessions/{quote(str(session_id))}"


def _tool(call: dict[str, Any]) -> dict[str, Any]:
    result = call.get("result") or {}
    ok = bool(result.get("ok")) if isinstance(result, dict) else False
    error = None
    if not ok and isinstance(result, dict):
        error = (result.get("error") or {}).get("code") if isinstance(result.get("error"), dict) else result.get("error")
    return {"name": call.get("name"), "ok": ok, "error": str(error)[:120] if error else None,
            "blocked_by": call.get("blocked_by"), "args": sorted((call.get("args") or {}).keys())}


def row(found: dict[str, Any]) -> dict[str, Any]:
    """One stored agent turn as the console draws it."""
    meta = found["meta"] or {}
    guard = meta.get("guard") or {}
    reasons = list((guard.get("hard") or {}).get("reasons") or []) + list((guard.get("soft") or {}).get("reasons") or [])
    latency = meta.get("latency") or {}
    usage = meta.get("usage") or {}
    session = found.get("customer_id") or found["call_id"]
    return {
        "id": found["id"],
        "call_id": found["call_id"],
        "turn_id": found["turn_id"],
        "at": found["created_at"].isoformat() if found.get("created_at") else None,
        "channel": found.get("channel"),
        "mode": found.get("mode"),
        "lane": meta.get("lane"),
        "route_reason": meta.get("route_reason"),
        "tier": meta.get("tier"),
        "model": meta.get("model"),
        "ttft_ms": latency.get("ttft_ms"),
        "total_ms": latency.get("total_ms"),
        "stages": {k: v for k, v in latency.items() if k.endswith("_ms") and k not in ("ttft_ms", "total_ms", "ttfa_ms")},
        "warmup": bool(latency.get("warmup")),
        "model_calls": usage.get("calls", meta.get("model_calls") or 0),
        "tokens": {"input": usage.get("input"), "output": usage.get("output"), "cached": usage.get("cached")},
        "cost_usd": usage.get("cost_usd"),
        "by_agent": usage.get("by_agent") or {},
        "tools": [_tool(t) for t in meta.get("tool_calls") or []],
        "guard": {"passed": not reasons, "reasons": reasons},
        "regenerations": meta.get("regenerations") or 0,
        "fallback": bool(meta.get("fallback")),
        "error": meta.get("error"),
        "handoff": bool(meta.get("handoff")),
        "langfuse_url": langfuse_url(session),
    }


async def fetch(after: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    async with connection() as conn:
        if after is None:
            found = await (await conn.execute(_COLUMNS + "ORDER BY t.id DESC LIMIT %s", (limit,))).fetchall()
        else:
            found = await (await conn.execute(_COLUMNS + "AND t.id > %s ORDER BY t.id LIMIT %s", (after, limit))).fetchall()
    return [row(dict(f)) for f in found]


@router.get("/turns")
async def turns(request: Request, after: int | None = Query(default=None, ge=0),
                limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    staff(request, ROLES)
    return {"turns": await fetch(after, limit)}


def _event(name: str, data: Any) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/stream")
async def stream(request: Request, after: int | None = Query(default=None, ge=0)) -> StreamingResponse:
    """New agent turns as server-sent events (``turn``), a ``ping`` comment while quiet, ``bye`` before it ends."""
    staff(request, ROLES)

    async def events():
        last = after
        if last is None:
            latest = await fetch(None, 1)
            last = latest[0]["id"] if latest else 0
        started = beat = time.monotonic()
        yield _event("hello", {"after": last})
        while time.monotonic() - started < STREAM_SECONDS:
            if await request.is_disconnected():
                return
            for item in await fetch(last, 100):
                last = item["id"]
                yield _event("turn", item)
                beat = time.monotonic()
            if time.monotonic() - beat > HEARTBEAT_SECONDS:
                yield ": ping\n\n"
                beat = time.monotonic()
            await asyncio.sleep(POLL_SECONDS)
        yield _event("bye", {"after": last})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _p(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What a window of turns adds up to; warm-up turns are left out of the latency figures."""
    timed = [r for r in rows if not r["warmup"]]
    ttft = [float(r["ttft_ms"]) for r in timed if r["ttft_ms"] is not None]
    total = [float(r["total_ms"]) for r in timed if r["total_ms"] is not None]
    tools = [t for r in rows for t in r["tools"]]
    by_tool: dict[str, dict[str, int]] = {}
    for t in tools:
        entry = by_tool.setdefault(t["name"] or "?", {"calls": 0, "failed": 0})
        entry["calls"] += 1
        entry["failed"] += 0 if t["ok"] else 1
    by_model: dict[str, int] = {}
    for r in rows:
        by_model[r["model"] or "?"] = by_model.get(r["model"] or "?", 0) + 1
    tokens_in = sum(r["tokens"]["input"] or 0 for r in rows)
    tokens_out = sum(r["tokens"]["output"] or 0 for r in rows)
    priced = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    return {
        "turns": len(rows),
        "ttft_p50_ms": statistics.median(ttft) if ttft else None,
        "ttft_p95_ms": _p(ttft, 0.95),
        "total_p95_ms": _p(total, 0.95),
        "tokens_input": tokens_in,
        "tokens_output": tokens_out,
        "tokens_per_turn": (tokens_in + tokens_out) / len(rows) if rows else None,
        "cost_usd": round(sum(priced), 6) if priced else None,
        "tool_calls": len(tools),
        "tool_failures": sum(1 for t in tools if not t["ok"]),
        "guard_blocks": sum(1 for r in rows if not r["guard"]["passed"]),
        "errors": sum(1 for r in rows if r["error"]),
        "fallbacks": sum(1 for r in rows if r["fallback"]),
        "handoffs": sum(1 for r in rows if r["handoff"]),
        "by_tool": dict(sorted(by_tool.items(), key=lambda kv: -kv[1]["calls"])),
        "by_model": by_model,
    }


@router.get("/summary")
async def summary(request: Request, minutes: int = Query(default=15, ge=1, le=1440)) -> dict[str, Any]:
    staff(request, ROLES)
    async with connection() as conn:
        found = await (await conn.execute(
            _COLUMNS + "AND t.created_at > now() - %s * interval '1 minute' ORDER BY t.id DESC LIMIT 2000",
            (minutes,))).fetchall()
    return {"minutes": minutes, **summarize([row(dict(f)) for f in found]),
            "langfuse": bool(os.getenv("LANGFUSE_HOST") and os.getenv("LANGFUSE_PROJECT_ID")),
            # The fleet's load and today's model spend (runtime/load.py); None without AGENT_REDIS_URL.
            "spend_today_usd": await load.spend_today(), "load": await load.fleet()}
