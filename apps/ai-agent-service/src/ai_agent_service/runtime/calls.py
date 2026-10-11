"""Call lifecycle on the agent's tables, without HTTP. Ported from the reference ``api/calls.py``.

A call is one platform conversation while the assistant is active. The rules
that keep concurrent callers apart are the reference project's:

- one turn at a time per call, claimed with a conditional UPDATE (a lease that
  expires on its own if the turn dies);
- a turn id per turn, so a retry replays the stored reply;
- hanging up starts ``after_call`` (MemoryAgent, QaAgent) exactly once;
- a session idle for :data:`IDLE_MINUTES`, or whose platform conversation was
  closed by the Sales service, is hung up by :func:`reconcile`.

The HTTP routes (``api/routes``) are thin wrappers over these functions.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage

from ..components.guardrails.fallback import LINES
from ..components.guardrails.hard import GuardInput, check
from ..components.handoff import copilot
from ..components.intake import pii
from ..mcp import client as mcp_client
from ..mcp.tools import ToolBox
from . import harness, options, trace_export, vault as vaults
from .db import connection

logger = logging.getLogger(__name__)

TURN_LEASE_SECONDS = 180
IDLE_MINUTES = 30
JOINED_MARK = "[consultant joined]"

#: Platform conversation channel -> the agent's channel (docs/design.md section 4.2).
CHANNELS = {"web": "web", "chat": "web", "call": "hotline", "hotline": "hotline", "zalo": "zalo", "fanpage": "facebook"}


class CallError(Exception):
    """A refused call operation; ``status`` is the HTTP status the route returns."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Actor:
    """Who is acting: a staff member (platform actor id) or the customer of a conversation."""

    id: str
    is_staff: bool
    label: str = ""


# ── opening and finding a call ────────────────────────────────────────────


async def call_for_conversation(conversation_id: str, platform_channel: str, *, actor: Actor) -> dict[str, Any]:
    """The open call of a platform conversation, opened on its first turn."""
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM calls WHERE conversation_id = %s AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        if row is not None:
            return row
        cursor = await conn.execute(
            "INSERT INTO calls (conversation_id, channel, tier, lane, opened_by, business_day) "
            "VALUES (%s, %s, 'UNKNOWN', 'NEW', %s, %s) RETURNING *",
            (conversation_id, CHANNELS.get(platform_channel, "web"), actor.id, options.business_day()),
        )
        row = await cursor.fetchone()
    logger.info("Call %s opened for conversation %s over %s", row["id"], conversation_id, row["channel"])
    return row


async def call_row(call_id: int) -> dict[str, Any]:
    async with connection() as conn:
        cursor = await conn.execute("SELECT * FROM calls WHERE id = %s", (call_id,))
        row = await cursor.fetchone()
    if row is None:
        raise CallError(404, "Call not found")
    return row


# ── a turn ────────────────────────────────────────────────────────────────


async def claim_lease(call_id: int) -> bool:
    async with connection() as conn:
        cursor = await conn.execute(
            "UPDATE calls SET turn_lease_until = now() + %s * interval '1 second' WHERE id = %s AND ended_at IS NULL "
            "AND (turn_lease_until IS NULL OR turn_lease_until < now()) RETURNING id",
            (TURN_LEASE_SECONDS, call_id),
        )
        return await cursor.fetchone() is not None


async def release_lease(call_id: int) -> None:
    try:
        async with connection() as conn:
            await conn.execute("UPDATE calls SET turn_lease_until = NULL WHERE id = %s", (call_id,))
    except Exception:  # noqa: BLE001 - the lease expires on its own
        logger.exception("Could not release the turn lease on call %s", call_id)


async def stored_reply(call_id: int, turn_id: str) -> dict[str, Any] | None:
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT content, meta FROM turns WHERE call_id = %s AND turn_id = %s AND speaker = 'agent'", (call_id, turn_id)
        )
        return await cursor.fetchone()


async def take_turn(row: dict[str, Any], *, content: str, turn_id: str, arrived: float,
                    actor: Actor, memory: bool = True) -> harness.Outcome:
    """Run one customer turn under the call's lease. Raises :class:`CallError` if busy or ended."""
    if row["ended_at"] is not None:
        raise CallError(409, "This session has ended. Start a new one.")
    if not await claim_lease(row["id"]):
        raise CallError(409, "The assistant is still answering the previous message.")
    try:
        return await harness.run_turn(row, content=content, turn_id=turn_id, arrived=arrived,
                                      user_id=actor.id, memory=memory)
    finally:
        await release_lease(row["id"])


# ── hanging up, idle sessions ─────────────────────────────────────────────


async def hang_up(call_id: int) -> dict[str, Any]:
    """End the call once and start ``after_call`` that once. Returns the row after."""
    async with connection() as conn:
        cursor = await conn.execute(
            "UPDATE calls SET ended_at = now(), turn_lease_until = NULL, memory_status = 'pending' "
            "WHERE id = %s AND ended_at IS NULL RETURNING id",
            (call_id,),
        )
        newly = await cursor.fetchone() is not None
    if newly:
        harness.spawn(harness.remember(call_id))
    return await call_row(call_id)


async def hang_up_conversation(conversation_id: str) -> None:
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT id FROM calls WHERE conversation_id = %s AND ended_at IS NULL", (conversation_id,)
        )
        rows = await cursor.fetchall()
    for row in rows:
        await hang_up(row["id"])


async def reconcile(closed_conversations: set[str] | None = None) -> list[int]:
    """Hang up idle calls and calls whose platform conversation is no longer open."""
    ended: list[int] = []
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT id, conversation_id FROM calls WHERE ended_at IS NULL AND COALESCE("
            "(SELECT max(created_at) FROM turns t WHERE t.call_id = calls.id), started_at"
            ") < now() - %s * interval '1 minute'",
            (IDLE_MINUTES,),
        )
        idle = await cursor.fetchall()
        cursor = await conn.execute("SELECT id, conversation_id FROM calls WHERE ended_at IS NULL")
        open_calls = await cursor.fetchall()
    targets = {r["id"] for r in idle}
    if closed_conversations:
        targets |= {r["id"] for r in open_calls if r["conversation_id"] and str(r["conversation_id"]) in closed_conversations}
    for call_id in sorted(targets):
        await hang_up(call_id)
        ended.append(call_id)
    if ended:
        logger.info("Hung up %d call(s): %s", len(ended), ended)
    return ended


async def open_conversation_ids() -> list[str]:
    async with connection() as conn:
        cursor = await conn.execute("SELECT DISTINCT conversation_id FROM calls WHERE ended_at IS NULL AND conversation_id IS NOT NULL")
        return [str(r["conversation_id"]) for r in await cursor.fetchall()]


# ── handoff and copilot, docs/design.md sections 4.6 and 4.10 ─────────────


async def request_handoff(call_id: int, *, reason: str) -> dict[str, Any]:
    """A change of mode, not an end: the bridging line once, then copilot."""
    row = await call_row(call_id)
    if row["ended_at"] is not None:
        raise CallError(409, "This session has ended.")
    if row["handoff_status"] is not None:
        return row
    async with connection() as conn:
        cursor = await conn.execute("SELECT 1 FROM calls WHERE id = %s AND turn_lease_until > now()", (call_id,))
        if await cursor.fetchone() is not None:
            raise CallError(409, "The assistant is still answering. Try again in a moment.")
        turn_id = f"bridge-{call_id}"
        cursor = await conn.execute(
            "UPDATE calls SET mode = 'copilot', handoff_status = 'pending', handoff_reason = %s, "
            "handoff_requested_at = now() WHERE id = %s AND handoff_status IS NULL RETURNING *",
            (reason, call_id),
        )
        row = await cursor.fetchone() or row
        await conn.execute(
            "INSERT INTO turns (call_id, turn_id, speaker, content, meta) VALUES (%s, %s, 'agent', %s, %s) "
            "ON CONFLICT (call_id, turn_id, speaker) DO NOTHING",
            (call_id, turn_id, LINES["bridging"], json.dumps({"bridging": True})),
        )
    await harness.add_spoken(call_id, AIMessage(content=LINES["bridging"], id=f"agent-{turn_id}"))
    logger.info("Handoff requested on call %s: %s", call_id, reason)
    return row


async def accept_handoff(call_id: int, *, actor: Actor) -> dict[str, Any]:
    """Claim a waiting handoff; two consultants cannot both win."""
    async with connection() as conn:
        cursor = await conn.execute(
            "UPDATE calls SET handoff_status = 'accepted', accepted_by = %s, accepted_at = now() "
            "WHERE id = %s AND handoff_status = 'pending' RETURNING *",
            (actor.id, call_id),
        )
        row = await cursor.fetchone()
    if row is None:
        existing = await call_row(call_id)
        if existing["handoff_status"] == "accepted":
            raise CallError(409, "Another consultant already took this conversation.")
        raise CallError(409, "No handoff is waiting on this conversation.")
    async with connection() as conn:
        await conn.execute(
            "INSERT INTO turns (call_id, turn_id, speaker, content, meta) VALUES (%s, %s, 'system', %s, %s) "
            "ON CONFLICT (call_id, turn_id, speaker) DO NOTHING",
            (call_id, f"joined-{call_id}", JOINED_MARK, json.dumps({"joined": actor.label or actor.id})),
        )
    return row


async def consultant_reply(call_id: int, *, actor: Actor, content: str, action: str,
                           force: bool) -> tuple[bool, list[str], dict[str, Any]]:
    """The consultant answers in copilot mode; their words pass the same hard check as a draft."""
    row = await call_row(call_id)
    if row["ended_at"] is not None:
        raise CallError(409, "This session has ended.")
    if row["mode"] != "copilot" or row["handoff_status"] != "accepted":
        raise CallError(409, "Accept the handoff before replying.")
    if row["accepted_by"] != actor.id:
        raise CallError(409, "Another consultant holds this conversation.")

    vault = await vaults.load(call_id)
    tokenised = pii.tokenise(content.strip(), vault)
    async with connection() as conn:
        cursor = await conn.execute("SELECT content FROM turns WHERE call_id = %s AND speaker = 'customer'", (call_id,))
        said = tuple(r["content"] for r in await cursor.fetchall())
    verdict = check(GuardInput(text=tokenised, tool_results=(), tier=row["tier"], tokens=frozenset(vault.entries),
                               customer_said=said))
    # A consultant may quote a price the tools did not give this turn: they are accountable for it.
    warnings = [r for r in verdict.reasons if not r.startswith("Số tiền")]
    if warnings and not force:
        return False, warnings, row

    suggestion = row["suggestion"] or {}
    signal = copilot.signal_of(copilot.HumanDecision(tokenised, action, "sent despite warnings" if warnings else None),
                               suggestion.get("text"))
    turn_id = uuid.uuid4().hex
    meta = {"action": action, "consultant": actor.label or actor.id, "suggested": suggestion.get("text"),
            "signal": signal, "warnings": warnings}
    async with connection() as conn:
        await conn.execute(
            "INSERT INTO turns (call_id, turn_id, speaker, content, meta) VALUES (%s, %s, 'human_agent', %s, %s)",
            (call_id, turn_id, tokenised, json.dumps(meta, ensure_ascii=False)),
        )
        cursor = await conn.execute("UPDATE calls SET suggestion = NULL WHERE id = %s RETURNING *", (call_id,))
        row = await cursor.fetchone()
    await vaults.save(call_id, vault)
    await harness.add_spoken(call_id, AIMessage(content=tokenised, id=f"human_agent-{turn_id}", name="human_agent"))
    return True, warnings, row


async def save_faq(call_id: int, *, actor: Actor, question: str, answer: str) -> dict[str, Any]:
    """Gap Loop step 6c (section 10.2): the consultant's answer becomes a FAQ entry, live at once."""
    await call_row(call_id)
    admin = ToolBox(await mcp_client.tools_for("admin"))
    envelope = await admin.call("kb_upsert", source="faq", title=question, text=answer,
                                provenance={"call_id": call_id, "saved_by": actor.label or actor.id})
    if not envelope.get("ok"):
        raise CallError(502, (envelope.get("error") or {}).get("message", "Could not save"))
    return envelope["data"]


# ── reads for the console ─────────────────────────────────────────────────


async def list_calls(*, open_only: bool, limit: int) -> list[dict[str, Any]]:
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT c.*, (SELECT count(*) FROM turns t WHERE t.call_id = c.id AND t.speaker = 'customer') AS turn_count "
            "FROM calls c WHERE (c.ended_at IS NULL OR EXISTS (SELECT 1 FROM turns t WHERE t.call_id = c.id "
            "AND t.speaker = 'customer')) "
            + ("AND c.ended_at IS NULL " if open_only else "")
            + "ORDER BY (c.ended_at IS NULL) DESC, c.started_at DESC LIMIT %s",
            (limit,),
        )
        return list(await cursor.fetchall())


async def call_turns(call_id: int, *, reveal_phone: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    row = await call_row(call_id)
    vault = await vaults.load(call_id)
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT id, turn_id, speaker, content, meta, created_at FROM turns WHERE call_id = %s ORDER BY created_at, id",
            (call_id,),
        )
        turns = await cursor.fetchall()
    if row.get("handoff_brief"):
        row = {**row, "handoff_brief": json.loads(pii.detokenize(json.dumps(row["handoff_brief"], ensure_ascii=False),
                                                                  vault, reveal_phone=reveal_phone))}
    shown = [{**t, "content": pii.detokenize(t["content"], vault, reveal_phone=reveal_phone)} for t in turns]
    return row, shown


async def trace_rows(call_id: int, *, scenario_id: str, call_label: str, config: str, run_id: str) -> list[dict[str, Any]]:
    """The call as ``trace_log`` rows for ``eval/reference_eval.py`` (``runtime.trace_export``)."""
    row = await call_row(call_id)
    vault = await vaults.load(call_id)
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT turn_id, speaker, content, meta FROM turns WHERE call_id = %s ORDER BY created_at, id", (call_id,)
        )
        turns = [{**t, "meta": t["meta"] or {}} for t in await cursor.fetchall()]
    return trace_export.build_rows(row, turns, vault, scenario_id=scenario_id, call_label=call_label,
                                   config=config, run_id=run_id)


async def recent_agent_turns(limit: int = 100) -> list[dict[str, Any]]:
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT call_id, turn_id, meta, created_at FROM turns WHERE speaker = 'agent' "
            "AND NOT (meta ? 'bridging') ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return list(await cursor.fetchall())


async def session_counts() -> dict[str, int]:
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT count(*) FILTER (WHERE ended_at IS NULL) AS open, "
            "count(*) FILTER (WHERE started_at >= date_trunc('day', now())) AS today, "
            "count(*) FILTER (WHERE handoff_status = 'pending') AS handoffs_waiting FROM calls"
        )
        row = await cursor.fetchone()
    return {k: int(v) for k, v in row.items()}
