"""mcp-memory: the ledger of what the shop knows about each customer.

``docs/design.md`` sections 5 and 6. The one server the brief requires by
name. Its tables:

| Table | Holds |
|---|---|
| ``facts`` | profile: one row per value a slot has had, never overwritten |
| ``episodes`` | one line per call |
| ``identities`` | hashed keys (phone, Zalo, Facebook) to customers; a key may point to several |

Roles decide who may do what (section 6.2), checked here on every call:
``advisor`` and ``harness`` read; ``harness`` may link a key provisionally;
only ``memory_writer`` (the MemoryAgent, after the call) commits facts and
episodes and confirms identities; ``admin`` deletes a customer.

The ledger is append-only (section 5.3). A change of mind closes the old
row's window and opens a new one; ``current`` facts are those active and in
force on the day asked about, so two contradicting values are never live
together. Keys arrive already hashed: the raw phone number never reaches
this server.

**Integrity with several writers** (section 5.3), for instance two calls of
one customer ending on two channels the same evening:

1. ``memory.commit_facts`` runs in one transaction under an advisory lock on
   the customer, so their writes queue rather than interleave;
2. a partial unique index allows one active row per slot, turning a silent
   double into a loud error;
3. the server decides each write again under the lock, on the facts as they
   are now: the MemoryAgent planned on a profile another call may have
   changed since, so "update the row I saw" becomes "update whatever is
   active", and a value already held is skipped.

**Forgetting a customer** (QT-06, section 5.4): the advisor records a
request (``memory.request_deletion``); ``after_call`` carries it out under
the ``admin`` role (``memory.delete_customer``), which removes the facts,
episodes, identities and vault rows and keeps a tombstone, so the next call
reads as a stranger's even where the organisers' CRM still knows the number.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Literal

from ..server_base import Server, ToolFailure, apply_schema, database

server = Server("memory")

READERS = {"advisor", "harness", "memory_writer", "admin"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id        TEXT PRIMARY KEY,
    customer_id    TEXT NOT NULL,
    slot           TEXT NOT NULL,
    value          JSONB NOT NULL,
    kind           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'invalidated', 'disputed')),
    valid_from     DATE NOT NULL,
    valid_to       DATE,
    confidence     REAL NOT NULL DEFAULT 1.0,
    source         JSONB NOT NULL DEFAULT '{}',
    superseded_by  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS facts_customer_idx ON facts (customer_id, slot);
-- The idempotency key of section 5.4: a replayed after_call writes nothing twice.
CREATE UNIQUE INDEX IF NOT EXISTS facts_once_idx ON facts (
    customer_id, slot, (source->>'call_id'), (source->>'turn'), (source->>'extractor_version')
);
-- Section 5.3: one active value per slot. Doubles left by a ledger written
-- before this index existed are closed first, the newest kept.
UPDATE facts f SET status = 'invalidated', valid_to = COALESCE(f.valid_to, CURRENT_DATE)
WHERE f.status = 'active' AND f.kind <> 'open_note' AND EXISTS (
    SELECT 1 FROM facts g WHERE g.customer_id = f.customer_id AND g.slot = f.slot AND g.status = 'active'
    AND g.kind <> 'open_note' AND (g.created_at, g.fact_id) > (f.created_at, f.fact_id));
CREATE UNIQUE INDEX IF NOT EXISTS facts_active_slot_idx ON facts (customer_id, slot)
    WHERE status = 'active' AND kind <> 'open_note';

CREATE TABLE IF NOT EXISTS deletion_requests (
    request_id   TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL,
    call_id      TEXT,
    reason       TEXT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    done_at      TIMESTAMPTZ,
    UNIQUE (customer_id, call_id)
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id       TEXT PRIMARY KEY,
    customer_id      TEXT NOT NULL,
    call_id          TEXT NOT NULL,
    channel          TEXT NOT NULL,
    started_at       DATE NOT NULL,
    summary          TEXT NOT NULL,
    outcome          TEXT,
    objection_type   TEXT,
    sentiment        TEXT,
    commitments      JSONB NOT NULL DEFAULT '[]',
    source_turn_span JSONB NOT NULL DEFAULT '[]',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (customer_id, call_id)
);

CREATE TABLE IF NOT EXISTS identities (
    key_type    TEXT NOT NULL CHECK (key_type IN ('phone', 'zalo_id', 'fb_id')),
    key_hash    TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'provisional' CHECK (status IN ('provisional', 'confirmed')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (key_type, key_hash, customer_id)
);
"""

KeyType = Literal["phone", "zalo_id", "fb_id"]


def _day(value: str | None) -> date:
    if not value:
        return date.today()
    return datetime.fromisoformat(value[:10]).date()


def _fact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_id": row["fact_id"],
        "slot": row["slot"],
        "value": row["value"],
        "kind": row["kind"],
        "status": row["status"],
        "valid_from": row["valid_from"].isoformat(),
        "valid_to": row["valid_to"].isoformat() if row["valid_to"] else None,
        "confidence": row["confidence"],
        "source": row["source"],
    }


# ── read ──────────────────────────────────────────────────────────────────


@server.tool(roles=READERS, name="memory_get_profile")
async def memory_get_profile(customer_id: str, on: str | None = None) -> dict[str, Any]:
    """What is known about a customer and still holds on the day of the call.

    Args:
        customer_id: The customer, as identity resolution named them.
        on: The day of the call, YYYY-MM-DD. Set by the system.
    """
    day = _day(on)
    pool = await database()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM facts WHERE customer_id = %s AND status IN ('active', 'disputed') "
            "AND valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s) "
            "ORDER BY valid_from, created_at",
            (customer_id, day, day),
        )
        rows = await cursor.fetchall()
        cursor = await conn.execute(
            "SELECT max(done_at) AS done FROM deletion_requests WHERE customer_id = %s AND done_at IS NOT NULL",
            (customer_id,),
        )
        forgotten = (await cursor.fetchone())["done"]
    # deleted_at: the customer asked to be forgotten; what any other source
    # still holds about them before that day is not memory to use (QT-06).
    return {"customer_id": customer_id, "facts": [_fact(r) for r in rows],
            "deleted_at": forgotten.isoformat() if forgotten else None}


@server.tool(roles=READERS, name="memory_get_episodes")
async def memory_get_episodes(customer_id: str, n: int = 3) -> dict[str, Any]:
    """The customer's last calls, one line each, newest first.

    Args:
        customer_id: The customer.
        n: How many, at most 10.
    """
    pool = await database()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM episodes WHERE customer_id = %s ORDER BY started_at DESC, created_at DESC LIMIT %s",
            (customer_id, max(1, min(n, 10))),
        )
        rows = await cursor.fetchall()
    return {
        "episodes": [
            {
                "episode_id": r["episode_id"], "call_id": r["call_id"], "channel": r["channel"],
                "date": r["started_at"].isoformat(), "summary": r["summary"], "outcome": r["outcome"],
                "objection_type": r["objection_type"], "sentiment": r["sentiment"],
                "commitments": r["commitments"],
            }
            for r in rows
        ]
    }


@server.tool(roles=READERS, name="memory_get_open_items")
async def memory_get_open_items(customer_id: str, on: str | None = None) -> dict[str, Any]:
    """Unfinished business: blockers, callbacks, commitments, disputed facts.

    Args:
        customer_id: The customer.
        on: The day of the call. Set by the system.
    """
    profile = await memory_get_profile(customer_id, on)
    open_slots = {"blocker", "callback_at", "commitments", "decision_maker"}
    return {
        "customer_id": customer_id,
        "items": [f for f in profile["facts"] if f["slot"] in open_slots or f["status"] == "disputed"],
    }


@server.tool(roles={"harness", "memory_writer", "admin"}, name="identity_find")
async def identity_find(key_type: KeyType, key_hash: str) -> dict[str, Any]:
    """Customers a hashed key points to. More than one means a shared key.

    Args:
        key_type: phone, zalo_id or fb_id.
        key_hash: The keyed hash of the value, never the value.
    """
    pool = await database()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT customer_id, status FROM identities WHERE key_type = %s AND key_hash = %s "
            "ORDER BY created_at",
            (key_type, key_hash),
        )
        rows = await cursor.fetchall()
    return {"matches": [{"customer_id": r["customer_id"], "status": r["status"]} for r in rows]}


# ── write ─────────────────────────────────────────────────────────────────


@server.tool(roles={"harness"}, name="identity_link_provisional")
async def identity_link_provisional(customer_id: str, key_type: KeyType, key_hash: str) -> dict[str, Any]:
    """Note, during a call, that a key seems to belong to a customer. Unconfirmed.

    Args:
        customer_id: The customer.
        key_type: phone, zalo_id or fb_id.
        key_hash: The keyed hash.
    """
    pool = await database()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO identities (key_type, key_hash, customer_id) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (key_type, key_hash, customer_id),
        )
    return {"customer_id": customer_id, "status": "provisional"}


@server.tool(roles={"memory_writer"}, name="memory_confirm_identity")
async def memory_confirm_identity(
    keys: list[dict[str, str]], customer_id: str | None = None
) -> dict[str, Any]:
    """Confirm that keys belong to a customer; with no customer, create one.

    Args:
        keys: [{key_type, key_hash}] seen and confirmed in the call.
        customer_id: The customer; omit for a caller the shop has never met.
    """
    customer_id = customer_id or f"N-{uuid.uuid4().hex[:10]}"
    pool = await database()
    async with pool.connection() as conn:
        for key in keys:
            await conn.execute(
                "INSERT INTO identities (key_type, key_hash, customer_id, status) "
                "VALUES (%s, %s, %s, 'confirmed') "
                "ON CONFLICT (key_type, key_hash, customer_id) DO UPDATE SET status = 'confirmed'",
                (key["key_type"], key["key_hash"], customer_id),
            )
    return {"customer_id": customer_id, "confirmed": len(keys)}


@server.tool(roles={"memory_writer"}, name="memory_commit_facts")
async def memory_commit_facts(customer_id: str, decisions: list[dict[str, Any]], on: str) -> dict[str, Any]:
    """Apply the write gate's decisions to the ledger.

    Each decision is {operation: add | update | invalidate | skip, slot, value,
    kind, confidence, source, replaces, disputed, valid_to}. Under the
    customer's lock each is decided again on the facts as they are now: a
    value already active is skipped, any other active value of the slot is
    closed on ``on`` and the new one opened; nothing is deleted. A decision
    already applied by an earlier run of the same call writes nothing.

    Args:
        customer_id: The customer, confirmed in the call.
        decisions: What to write, from the MemoryAgent.
        on: The day of the call.
    """
    day = _day(on)
    written: list[dict[str, Any]] = []
    pool = await database()
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"memory:{customer_id}",))
            for decision in decisions:
                operation = decision.get("operation")
                if operation == "skip":
                    continue
                if operation not in ("add", "update", "invalidate"):
                    raise ToolFailure("BAD_REQUEST", f"Unknown operation {operation!r}")
                write = await _apply(conn, customer_id, decision, day)
                if write is not None:
                    written.append(write)
    return {"customer_id": customer_id, "memory_writes": written}


async def _apply(conn: Any, customer_id: str, decision: dict[str, Any], day: date) -> dict[str, Any] | None:
    """One decision against the ledger as it is now; the write made, or None when there was nothing to do."""
    slot, value, source = decision["slot"], decision.get("value"), decision.get("source") or {}
    if decision["operation"] == "invalidate":
        cursor = await conn.execute(
            "UPDATE facts SET status = 'invalidated', valid_to = %s WHERE fact_id = %s AND customer_id = %s "
            "AND status = 'active' RETURNING fact_id",
            (day, decision.get("replaces"), customer_id),
        )
        return _write(slot, value, "delete", source, customer_id, None) if await cursor.fetchone() else None
    if await _already(conn, customer_id, slot, source):
        return None
    kind = decision.get("kind", "preference")
    current = None
    if not decision.get("disputed"):
        cursor = await conn.execute(
            "SELECT fact_id, value FROM facts WHERE customer_id = %s AND slot = %s AND status = 'active' "
            + ("AND value = %s::jsonb " if kind == "open_note" else "AND kind <> 'open_note' ")
            + "ORDER BY created_at DESC LIMIT 1",
            (customer_id, slot, json.dumps(value, ensure_ascii=False)) if kind == "open_note" else (customer_id, slot),
        )
        current = await cursor.fetchone()
        if current is not None and current["value"] == value:
            return None  # held already, whether noted or as the slot's value
    new_id = f"F-{uuid.uuid4().hex[:12]}"
    if current is not None and kind != "open_note":
        await conn.execute(
            "UPDATE facts SET status = 'invalidated', valid_to = %s, superseded_by = %s WHERE fact_id = %s",
            (day, new_id, current["fact_id"]),
        )
    await conn.execute(
        "INSERT INTO facts (fact_id, customer_id, slot, value, kind, status, valid_from, valid_to, confidence, source) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            new_id, customer_id, slot, json.dumps(value, ensure_ascii=False), kind,
            "disputed" if decision.get("disputed") else "active",
            day, _day(decision["valid_to"]) if decision.get("valid_to") else None,
            float(decision.get("confidence", 1.0)), json.dumps(source, ensure_ascii=False),
        ),
    )
    op = "supersede" if current is not None and kind != "open_note" else "set"
    return _write(slot, value, op, source, customer_id, new_id)


async def _already(conn: Any, customer_id: str, slot: str, source: dict[str, Any]) -> bool:
    """Whether this call, turn and extractor already wrote this slot: a replayed ``after_call``."""
    cursor = await conn.execute(
        "SELECT 1 FROM facts WHERE customer_id = %s AND slot = %s AND source->>'call_id' = %s "
        "AND source->>'turn' = %s AND source->>'extractor_version' = %s",
        (customer_id, slot, str(source.get("call_id")), str(source.get("turn")), str(source.get("extractor_version"))),
    )
    return await cursor.fetchone() is not None


def _write(slot: str, value: Any, op: str, source: dict[str, Any], customer_id: str, fact_id: str | None) -> dict[str, Any]:
    """A write as the trace's ``memory_writes`` names it, plus our fact id."""
    return {"key": slot, "value": value, "op": op,
            "source": f"{source.get('call', 'call')}#turn{source.get('turn', 0)}",
            "customer_id": customer_id, "fact_id": fact_id}


@server.tool(roles={"memory_writer"}, name="memory_commit_episode")
async def memory_commit_episode(customer_id: str, episode: dict[str, Any]) -> dict[str, Any]:
    """Write the call's one-line episode.

    Args:
        customer_id: The customer.
        episode: {call_id, channel, date, summary, outcome, objection_type,
            sentiment, commitments, source_turn_span}.
    """
    episode_id = f"E-{uuid.uuid4().hex[:12]}"
    pool = await database()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO episodes (episode_id, customer_id, call_id, channel, started_at, summary, outcome, "
            "objection_type, sentiment, commitments, source_turn_span) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (customer_id, call_id) DO UPDATE SET summary = EXCLUDED.summary, outcome = EXCLUDED.outcome",
            (
                episode_id, customer_id, str(episode["call_id"]), episode.get("channel", "web"),
                _day(episode.get("date")), episode["summary"], episode.get("outcome"),
                episode.get("objection_type"), episode.get("sentiment"),
                json.dumps(episode.get("commitments") or [], ensure_ascii=False),
                json.dumps(episode.get("source_turn_span") or [], ensure_ascii=False),
            ),
        )
    return {"episode_id": episode_id}


@server.tool(roles={"advisor"}, name="memory_request_deletion")
async def memory_request_deletion(
    customer_id: str | None = None, call_id: str | None = None, reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Record that the customer asked the shop to delete their data (policy QT-06).

    Call it only after asking the customer to confirm and hearing them agree.
    Nothing is deleted now: the system deletes everything within 72 hours,
    which is what to tell the customer.

    Args:
        customer_id: Set by the system; leave it out.
        call_id: Set by the system; leave it out.
        reason: The customer's words, if they gave a reason.
        idempotency_key: Set by the system; leave it out.
    """
    if not customer_id:
        raise ToolFailure("NOT_IDENTIFIED", "The customer's identity is not confirmed in this call; "
                          "no request can be recorded for them.")
    pool = await database()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "INSERT INTO deletion_requests (request_id, customer_id, call_id, reason) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (customer_id, call_id) DO UPDATE SET reason = COALESCE(EXCLUDED.reason, deletion_requests.reason) "
            "RETURNING request_id",
            (f"D-{uuid.uuid4().hex[:12]}", customer_id, call_id, reason),
        )
        request_id = (await cursor.fetchone())["request_id"]
    return {"request_id": request_id, "status": "recorded", "deleted_within_hours": 72}


@server.tool(roles={"admin"}, name="memory_delete_customer")
async def memory_delete_customer(customer_id: str) -> dict[str, Any]:
    """Forget a customer entirely, on their request (policy QT-06).

    Facts, episodes, identities and vault rows go; a tombstone stays, so a
    later call from a number the organisers' CRM still knows is read as a
    stranger's (``memory_get_profile``'s ``deleted_at``).

    Args:
        customer_id: The customer.
    """
    pool = await database()
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"memory:{customer_id}",))
            counts = {}
            for table in ("facts", "episodes", "identities"):
                cursor = await conn.execute(f"DELETE FROM {table} WHERE customer_id = %s", (customer_id,))
                counts[table] = cursor.rowcount
            # The API's vault lives in the same database; an evaluation database has none.
            if (await (await conn.execute("SELECT to_regclass('pii_vault') AS t")).fetchone())["t"]:
                cursor = await conn.execute("DELETE FROM pii_vault WHERE customer_id = %s", (customer_id,))
                counts["pii_vault"] = cursor.rowcount
            cursor = await conn.execute(
                "UPDATE deletion_requests SET done_at = now() WHERE customer_id = %s AND done_at IS NULL "
                "RETURNING request_id", (customer_id,))
            if not await cursor.fetchall():
                await conn.execute(
                    "INSERT INTO deletion_requests (request_id, customer_id, reason, done_at) VALUES (%s, %s, %s, now())",
                    (f"D-{uuid.uuid4().hex[:12]}", customer_id, "deleted by an administrator"),
                )
    return {"customer_id": customer_id, "deleted": counts}


if __name__ == "__main__":
    apply_schema(SCHEMA)
    server.run()
