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

from ...runtime import calls, platform
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


class FaqEntry(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=3, max_length=2000)


@router.get("/calls")
async def list_calls(request: Request, open_only: bool = Query(default=False),
                     limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
    _actor(request)
    return [_call(row) for row in await calls.list_calls(open_only=open_only, limit=limit)]


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
    return {"sent": sent, "warnings": warnings, "call": _call(row) if sent else None}


@router.post("/calls/{call_id}/faq")
async def save_faq(call_id: int, body: FaqEntry, request: Request) -> dict[str, Any]:
    try:
        return await calls.save_faq(call_id, actor=_actor(request), question=body.question, answer=body.answer)
    except CallError as error:
        raise _http(error) from error
