"""Staff console for the agent's calls: queue, transcript, handoff, copilot replies, FAQ, hang-up.

Ported from the reference ``api/calls.py`` (``docs/design.md`` sections 4.6,
4.10, 10.2). Customers take turns through ``/api/conversations/{id}/turns``;
these endpoints are for consultants (platform roles ``admin`` and ``agent``).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from src.api.routes.shared import staff

from ...mcp.servers import btc
from ...runtime import calls, platform, zalo
from ...runtime.db import connection
from ...runtime.calls import Actor, CallError

router = APIRouter(prefix="/api/agent", tags=["agent-console"])
ROLES = {"admin", "agent"}


def _actor(request: Request) -> Actor:
    role = staff(request, ROLES)
    actor_id = str(getattr(request.state, "actor_id", None) or role)
    return Actor(id=actor_id, is_staff=True, label=f"{role}:{actor_id}")


def _call(row: dict[str, Any], turn_count: int | None = None) -> dict[str, Any]:
    return {
        "id": row["id"], "conversation_id": str(row["conversation_id"]) if row.get("conversation_id") else None,
        "phone_last4": row.get("phone_last4"), "channel": row["channel"], "channel_ref": row.get("channel_ref"),
        "tier": row["tier"], "lane": row["lane"], "route_reason": row.get("route_reason"), "mode": row["mode"],
        "customer_id": row.get("customer_id"), "customer_label": row.get("customer_label"),
        "brief": list(row.get("brief") or []), "brief_object": row.get("brief_object"),
        "warnings": list(row.get("warnings") or []),
        "business_day": row["business_day"].isoformat() if row.get("business_day") else None,
        "started_at": row["started_at"].isoformat(), "ended_at": row["ended_at"].isoformat() if row.get("ended_at") else None,
        "turn_count": int(turn_count if turn_count is not None else row.get("turn_count") or 0),
        "handoff_status": row.get("handoff_status"), "handoff_reason": row.get("handoff_reason"),
        "handoff_brief": row.get("handoff_brief"), "accepted_by": row.get("accepted_by"),
        "suggestion": row.get("suggestion"), "memory_status": row.get("memory_status"), "after_call": row.get("after_call"),
    }


def _http(error: CallError) -> HTTPException:
    return HTTPException(error.status, str(error))


class HandoffRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class ConsultantReply(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    #: The feedback signal of section 4.6: "used" approves the suggestion, the other two reject it.
    action: Literal["used", "edited", "own"] = "own"
    #: Send even though the guard warned.
    force: bool = False


class SuggestionFeedback(BaseModel):
    """The consultant's 👍/👎 on the assistant's current suggestion."""

    thumb: Literal["up", "down"]
    reason: str | None = Field(default=None, max_length=300)


class FaqEntry(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=3, max_length=2000)


@router.get("/calls")
async def list_calls(request: Request, open_only: bool = Query(default=False),
                     limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
    _actor(request)
    return [_call(row) for row in await calls.list_calls(open_only=open_only, limit=limit)]


@router.get("/callbacks")
async def list_callbacks(request: Request) -> list[dict[str, Any]]:
    """Call-backs the assistant booked (``schedule.callback``), soonest first.

    As on a call, staff see the last four digits of the number, and the
    customer's name only when the number belongs to one CRM customer (a
    shared number names nobody)."""
    _actor(request)
    async with connection() as conn:
        state = await btc._read_state(conn)
    mock = btc.mock()
    rows = []
    for cb in state.get("callbacks") or []:
        phone = str(cb.get("customer_phone") or "")
        crm = mock.crm_get_customer(phone=phone) if phone else {"found": False}
        named = crm.get("found") and not crm.get("ambiguous")
        rows.append({
            "callback_id": cb.get("callback_id"),
            "callback_at": cb.get("callback_at"),
            "moved_from": cb.get("moved_from"),
            "note": cb.get("note"),
            "phone_last4": phone[-4:] if phone else None,
            "customer_name": crm.get("name") if named else None,
            "customer_id": crm.get("customer_id") if named else None,
        })
    return sorted(rows, key=lambda row: row["callback_at"] or "")


@router.get("/calls/{call_id}")
async def get_call(call_id: int, request: Request) -> dict[str, Any]:
    """The call and its transcript; staff see only the last four digits of a phone number."""
    actor = _actor(request)
    try:
        row, turns = await calls.call_turns(call_id, reveal_phone=False)
    except CallError as error:
        raise _http(error) from error
    visible = sum(1 for t in turns if t["speaker"] == "customer")
    return {**_call(row, visible), "held_by_you": row.get("accepted_by") == actor.id, "turns": [
        {"id": t["id"], "turn_id": t["turn_id"], "speaker": t["speaker"], "content": t["content"],
         "meta": t["meta"] or {}, "created_at": t["created_at"].isoformat()} for t in turns]}


@router.post("/calls/{call_id}/end")
async def end_call(call_id: int, request: Request) -> dict[str, Any]:
    """Hang up; idempotent; starts after_call (MemoryAgent, QaAgent) once."""
    _actor(request)
    try:
        return _call(await calls.hang_up(call_id))
    except CallError as error:
        raise _http(error) from error


@router.get("/calls/{call_id}/context")
async def customer_context(call_id: int, request: Request):
    """The agent's own ledger and orders; no projection from the platform's older memory tables."""
    _actor(request)
    try:
        row, turns = await calls.call_turns(call_id, reveal_phone=False)
    except CallError as error:
        raise _http(error) from error
    facts, episodes = [], []
    order_ids = set()
    for turn in turns:
        meta = turn.get("meta")
        for tool in (meta.get("tool_calls") or []) if isinstance(meta, dict) else []:
            if not isinstance(tool, dict):
                continue
            result = tool.get("result") or {}
            if not isinstance(result, dict):
                continue
            data = result.get("data") or {}
            if isinstance(data, dict) and tool.get("name") in ("order.create", "order_create") and result.get("ok") and data.get("order_id"):
                order_ids.add(str(data["order_id"]))
    async with connection() as conn:
        if row.get("customer_id") and row.get("tier") == "VERIFIED":
            facts = await (await conn.execute(
                "SELECT slot, value, status, source, valid_from, valid_to, created_at FROM facts "
                "WHERE customer_id = %s ORDER BY created_at DESC LIMIT 100", (row["customer_id"],))).fetchall()
            episodes = await (await conn.execute(
                "SELECT call_id, channel, started_at, summary, outcome FROM episodes "
                "WHERE customer_id = %s ORDER BY started_at DESC LIMIT 20", (row["customer_id"],))).fetchall()
            for fact in facts:
                if fact["status"] == "active" and fact["slot"] in ("order_id", "order_ids"):
                    value = fact["value"]
                    order_ids.update(str(item) for item in (value if isinstance(value, list) else [value]))
        state = await btc._read_state(conn)
    fields = ("order_id", "sku", "variant_sku", "qty", "price_vnd", "payment", "status", "estimated_delivery")
    orders = [{"source": "agent", **{field: order.get(field) for field in fields}} for key, order in (state.get("orders") or {}).items()
              if key in order_ids and isinstance(order, dict)]
    return {"facts": facts, "episodes": episodes, "orders": orders,
            "identity_confirmed": row.get("tier") == "VERIFIED", "memory_status": row.get("memory_status")}


@router.post("/calls/{call_id}/handoff")
async def request_handoff(call_id: int, body: HandoffRequest, request: Request) -> dict[str, Any]:
    actor = _actor(request)
    try:
        return _call(await calls.request_handoff(call_id, reason=body.reason or f"Requested by {actor.label}"))
    except CallError as error:
        raise _http(error) from error


@router.post("/calls/{call_id}/accept")
async def accept_handoff(call_id: int, request: Request) -> dict[str, Any]:
    try:
        return _call(await calls.accept_handoff(call_id, actor=_actor(request)))
    except CallError as error:
        raise _http(error) from error


@router.post("/calls/{call_id}/reply")
async def consultant_reply(call_id: int, body: ConsultantReply, request: Request) -> dict[str, Any]:
    """The consultant's words pass the same hard check as a draft; warnings come back unless forced."""
    try:
        sent, warnings, row = await calls.consultant_reply(call_id, actor=_actor(request), content=body.content,
                                                           action=body.action, force=body.force)
    except CallError as error:
        raise _http(error) from error
    if sent and row.get("conversation_id"):
        # The customer reads the chat on the platform, not the agent's transcript.
        await platform.append_staff_message(request.app, str(row["conversation_id"]), body.content.strip())
    if sent and row.get("channel") == "zalo" and row.get("channel_ref"):
        # A Zalo customer reads it in Zalo.
        await zalo.send(str(row["channel_ref"]), body.content.strip(), str(row.get("conversation_id") or ""))
    return {"sent": sent, "warnings": warnings, "call": _call(row) if sent else None}


@router.post("/calls/{call_id}/suggestion-feedback")
async def suggestion_feedback(call_id: int, body: SuggestionFeedback, request: Request) -> dict[str, Any]:
    """Rate the current suggestion; kept as a ``consultant`` signal for the improvement loop."""
    try:
        return await calls.suggestion_feedback(call_id, actor=_actor(request), thumb=body.thumb, reason=body.reason)
    except CallError as error:
        raise _http(error) from error


@router.post("/calls/{call_id}/faq")
async def save_faq(call_id: int, body: FaqEntry, request: Request) -> dict[str, Any]:
    try:
        return await calls.save_faq(call_id, actor=_actor(request), question=body.question, answer=body.answer)
    except CallError as error:
        raise _http(error) from error
