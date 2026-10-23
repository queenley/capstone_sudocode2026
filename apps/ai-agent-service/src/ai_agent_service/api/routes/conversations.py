"""Customer turns on a platform conversation: ``/turns`` (JSON) and ``/stream`` (SSE).

The web client's contract is unchanged (``apps/web/src/services/api.ts``):
request ``{message, selected_sku?, memory_enabled?}``; ``/stream`` emits
``start``, ``delta`` (the reply), ``done`` (the TurnResult) or ``error``.
Behind it every turn goes through the hot graph (``runtime.harness.run_turn``)
under the call's lease, as a task that survives a dropped connection, with a
keepalive comment while the model works. A ``delta`` is a sentence the guard
has passed, sent the moment it may be said (``docs/design.md`` section 4.8);
a reply that did not stream comes as one ``delta`` at the end.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from src.api.routes.shared import bearer

from ...mcp.client import dotted
from ...pipeline.hot.graph import NODES
from ...runtime import calls, harness, platform
from ...runtime.calls import Actor, CallError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["conversations"])

HEARTBEAT_SECONDS = 15


class TurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    selected_sku: str | None = Field(default=None, max_length=64)
    #: False runs the organisers' baseline: same graph, no memory (docs/design.md 9.5).
    memory_enabled: bool = True
    #: Chosen by the client so a retried turn replays the stored reply.
    turn_id: str | None = Field(default=None, min_length=1, max_length=64)


async def _turn(request: Request, conversation_id: str, data: TurnRequest,
                emit: Callable[[str, str], Awaitable[None]] | None = None) -> dict[str, Any]:
    """Authorise with the conversation token, then :func:`answer_turn`."""
    arrived = getattr(request.state, "arrived", None) or time.perf_counter()
    token = bearer(request)
    conversation = await platform.authorize(request.app, conversation_id, token)
    return await answer_turn(request.app, conversation, data, arrived=arrived, emit=emit)


async def answer_turn(app: Any, conversation: platform.ConversationView, data: TurnRequest, *, arrived: float,
                      emit: Callable[[str, str], Awaitable[None]] | None = None,
                      channel_ref: str | None = None) -> dict[str, Any]:
    """Open or find the call, run the turn, project it to the platform.

    Shared by the web routes (after the token check) and the channels that own
    their conversations (Zalo: ``channel_ref`` is the sender's Zalo user id,
    the key the agent identifies them by).
    """
    conversation_id = conversation.id
    if conversation.status not in ("open", "handed_off"):
        raise HTTPException(409, "Conversation is closed")
    actor = Actor(id=f"conversation:{conversation_id}", is_staff=False)
    # Only channels that know the customer's id there pass it (web chat does not).
    extra = {"channel_ref": channel_ref} if channel_ref else {}
    row = await calls.call_for_conversation(conversation_id, conversation.channel, actor=actor, **extra)
    if conversation.customer_id and not row.get("caller_token"):
        # The customer proved this number with a one-time code: it identifies
        # them as a caller id does on the hotline (tier VERIFIED on one match).
        phone = await platform.verified_phone(app, conversation.customer_id)
        if phone:
            await calls.set_caller(int(row["id"]), phone)
            row = await calls.call_row(int(row["id"]))
    turn_id = data.turn_id or uuid.uuid4().hex
    if conversation.status == "handed_off" and row.get("mode") != "copilot":
        # A person has the conversation and the agent is not drafting for
        # them (Sales handed it over, not the agent): only record the words.
        await platform.append_messages(app, conversation_id, customer=data.message, assistant=None)
        return {**_result(row, turn_id, None, ""), "route": "HUMAN", "waiting": True}

    stored = await calls.stored_reply(row["id"], turn_id)
    if stored is not None:
        return {**_result(row, turn_id, None, stored["content"]), "replayed": True}

    message = data.message
    if data.selected_sku:
        # The product the customer has open on the page is context, not their words.
        message = f"{message}\n(Khách đang xem sản phẩm {data.selected_sku})"
    try:
        outcome = await harness.spawn(calls.take_turn(row, content=message, turn_id=turn_id, arrived=arrived,
                                                      actor=actor, memory=data.memory_enabled, emit=emit))
    except CallError as error:
        raise HTTPException(error.status, str(error)) from error
    if outcome.kind == "error":
        raise HTTPException(502, "The assistant could not answer this turn. Try again or ask for staff help.")
    # Copilot mode: the agent drafted a suggestion for the consultant and
    # says nothing itself; the consultant's reply reaches the chat from the console.
    waiting = outcome.kind == "waiting"

    state = outcome.state or {}
    await platform.append_messages(app, conversation_id, customer=data.message, assistant=outcome.content)
    handoff = state.get("handoff") or {}
    if handoff.get("status") == "pending" and conversation.status == "open":
        await platform.record_handoff(app, conversation_id,
                                      reason=handoff.get("reason") or "assistant_handoff", brief=handoff.get("brief") or {})
    result = {**_result(row, turn_id, outcome, outcome.content or ""), "waiting": waiting}
    tracker = getattr(app.state, "turn_tracker", None)
    if tracker is not None:
        tracker.log_turn(
            trace_id=result["trace_id"], session_id=str(row["id"]), route=result["route"], confidence=result["confidence"],
            latency_ms=int(outcome.latency.get("total_ms") or 0), tool_calls=result["tool_calls"],
            usage={"model_calls": (state.get("draft") or {}).get("model_calls") or 0},
            environment=app.state.settings.environment, router="rules",
            model=str((state.get("draft") or {}).get("model") or "unknown"), stage_timings={},
            guard_blocked=not bool((state.get("guard") or {}).get("passed", True)),
            error_count=1 if (state.get("draft") or {}).get("error") else 0,
        )
    return result


def _result(row: dict[str, Any], turn_id: str, outcome: harness.Outcome | None, reply: str) -> dict[str, Any]:
    """The web client's TurnResult, built from the hot graph's state."""
    state = (outcome.state if outcome else None) or {}
    results = state.get("tool_results") or []
    guard = state.get("guard") or {}
    draft = state.get("draft") or {}
    handoff = state.get("handoff") or {}
    return {
        "reply": reply,
        "route": state.get("lane") or "unknown",
        # Lanes are chosen by rules (docs/design.md 4.3), not by a classifier.
        "confidence": 1.0 if state.get("lane") else 0.0,
        "trace_id": f"{row['id']}:{turn_id}",
        "products": _products(results, state.get("quotes") or {}),
        "stages": list(NODES),
        "stage_timings_ms": {},
        "tool_calls": [dotted(str(r.get("name") or "")) if "." not in str(r.get("name")) else r.get("name")
                       for r in results],
        "signals": {
            "lane": state.get("lane"),
            "route_rule": state.get("route_rule"),
            "route_reason": state.get("route_reason"),
            "tier": state.get("tier"),
            "guard_passed": guard.get("passed"),
            "guard_reasons": list((guard.get("hard") or {}).get("reasons") or []) + list((guard.get("soft") or {}).get("reasons") or []),
            "regenerations": state.get("regen_count") or 0,
            "fallback": bool(draft.get("fallback")),
            "handoff_required": handoff.get("status") == "pending",
            "used_brief_lines": ((state.get("reply") or {}).get("used_lines")) or [],
            "freshness_warnings": state.get("freshness") or [],
            "call_brief_latency_ms": state.get("call_brief_latency_ms"),
            "latency": outcome.latency if outcome else None,
            "model": draft.get("model"),
        },
    }


def _products(results: list[dict[str, Any]], quotes: dict[str, int]) -> list[dict[str, Any]]:
    """``catalog.search`` items in the web client's catalog shape, priced by any quote this call."""
    items: list[dict[str, Any]] = []
    for result in results:
        if result.get("name") not in ("catalog.search", "catalog_search"):
            continue
        for item in (((result.get("result") or {}).get("data") or {}).get("items") or [])[:8]:
            sku = item.get("sku")
            items.append({
                "id": sku, "name": item.get("name"), "brand": item.get("brand") or "", "category": item.get("category"),
                "description": None, "sku_code": sku, "variant": {}, "currency": "VND",
                "list_price": str(item.get("list_price_vnd") or 0),
                "sale_price": str(quotes.get(sku, item.get("list_price_vnd") or 0)),
                "available": int(item.get("stock") or 0),
            })
    return items


@router.post("/conversations/{conversation_id}/turns")
async def turn(conversation_id: UUID, data: TurnRequest, request: Request) -> dict[str, Any]:
    return await _turn(request, str(conversation_id), data)


@router.post("/conversations/{conversation_id}/stream")
async def stream(conversation_id: UUID, data: TurnRequest, request: Request) -> StreamingResponse:
    # Authorise before the stream opens, so a bad token is a plain 404, not an SSE error.
    await platform.authorize(request.app, str(conversation_id), bearer(request))
    said: asyncio.Queue[str] = asyncio.Queue()

    async def emit(kind: str, text: str) -> None:
        # The filler line said while tools run is for a voice line; the chat shows typing instead.
        if kind == "sentence":
            said.put_nowait(text)

    task = harness.spawn(_turn(request, str(conversation_id), data, emit=emit))

    async def events() -> AsyncIterator[str]:
        yield "event: start\ndata: {}\n\n"
        streamed = False
        while True:
            getter = asyncio.ensure_future(said.get())
            done, _ = await asyncio.wait({task, getter}, timeout=HEARTBEAT_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                yield _event("delta", {"text": (" " if streamed else "") + getter.result()})
                streamed = True
                continue
            getter.cancel()
            if task in done:
                break
            yield ": keepalive\n\n"
        while not said.empty():
            yield _event("delta", {"text": (" " if streamed else "") + said.get_nowait()})
            streamed = True
        try:
            result = task.result()
        except HTTPException as error:
            yield _event("error", {"status": error.status_code, "message": error.detail})
            return
        except Exception:  # noqa: BLE001 - the browser needs an answer, the log keeps the detail
            logger.exception("Turn failed on conversation %s", conversation_id)
            yield _event("error", {"message": "Turn failed; retry or request staff help"})
            return
        if not streamed:
            for line in (result["reply"] or "").splitlines(keepends=True):
                yield _event("delta", {"text": line})
        yield _event("done", result)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
