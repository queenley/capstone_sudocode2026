"""mcp-knowledge: what the shop's documents say. ``docs/design.md`` section 7.

One knowledge base, three sources (``components.knowledge``):

- the organisers' policy corpus, ``policy/*.md``, one chunk per section;
- the approved Knowledge Gap Loop and playbook entries of the version ``config/knowledge.yaml``
  names, ``data/kb/v<N>.jsonl``, copied into ``kb_chunks`` at startup with
  scope ``release`` (section 7.5), so rolling back is pointing at another
  file and restarting;
- entries of the Knowledge Gap Loop a consultant saved from the console
  (``kb_upsert``), scope ``demo``: in the database only, never exported, never
  counted as an improvement, and **not served until a person approves them**
  (``kb_review``, after the gate of section 10.2, ``components.improvement.gap``).
  ``kb_pending`` lists what waits.

``kb_search`` is the harness's (``load_context`` searches every customer
turn, section 4.2) and the admin's; the advisor never calls it, it reads the
passages the harness put in its prompt. A restricted passage is returned with
its code and the instruction to refuse, its text only to ``admin``.

The index is built once at startup. A server started for another role sees
an entry saved through ``admin`` within :data:`REFRESH_SECONDS`, when it
notices ``kb_chunks`` changed and rebuilds (only the new passages are
embedded; the rest come from the vector cache).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from ...components import knowledge
from ...components.knowledge import corpus
from ...components.knowledge.search import Hit, KnowledgeBase, Result
from ...components.improvement import gap
from ...config.config_manager import get_knowledge_config, kb_dir
from ..server_base import SCHEMA_LOCK, Server, ToolFailure, apply_schema, current_role, database

logger = logging.getLogger(__name__)

server = Server("knowledge")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_chunks (
    chunk_id    TEXT PRIMARY KEY,
    source      TEXT NOT NULL CHECK (source IN ('gap', 'playbook')),
    title       TEXT NOT NULL,
    text        TEXT NOT NULL,
    situation   TEXT,
    valid_from  DATE,
    valid_to    DATE,
    provenance  JSONB NOT NULL DEFAULT '{}',
    revoked     BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'demo';
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS persona TEXT;
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
-- A console entry is served only once a person approved it (section 10.2); a release entry always is.
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS approved_by TEXT;
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
-- The Knowledge Gap Loop's entries were called 'faq' until 2026-11-01.
ALTER TABLE kb_chunks DROP CONSTRAINT IF EXISTS kb_chunks_source_check;
UPDATE kb_chunks SET source = 'gap' WHERE source = 'faq';
ALTER TABLE kb_chunks ADD CONSTRAINT kb_chunks_source_check CHECK (source IN ('gap', 'playbook'));
"""

#: How often a search checks whether ``kb_chunks`` changed under another process.
REFRESH_SECONDS = 10.0
#: The most passages one search returns.
MAX_K = 8

_kb: KnowledgeBase | None = None
_stamp: tuple[Any, ...] | None = None
_checked = 0.0
_rebuild_lock = asyncio.Lock()


# ── startup: the version file into kb_chunks, then the index ──────────────


def sync_release(version: int) -> int:
    """Make ``kb_chunks``' release rows exactly the entries of ``v<version>.jsonl``; demo rows are left alone."""
    entries = corpus.load_version(kb_dir(), version)
    from ...config.database import get_settings

    url, _ = get_settings().require_database_url()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK,))
        try:
            with conn.transaction():
                ids = [chunk.chunk_id for chunk in entries]
                conn.execute("DELETE FROM kb_chunks WHERE scope = 'release' AND NOT (chunk_id = ANY(%s))", (ids,))
                for chunk in entries:
                    conn.execute(
                        "INSERT INTO kb_chunks (chunk_id, source, title, text, situation, persona, valid_from, valid_to,"
                        " provenance, scope, revoked, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'release', false, now()) "
                        "ON CONFLICT (chunk_id) DO UPDATE SET source = EXCLUDED.source, title = EXCLUDED.title,"
                        " text = EXCLUDED.text, situation = EXCLUDED.situation, persona = EXCLUDED.persona,"
                        " valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to,"
                        " provenance = EXCLUDED.provenance, scope = 'release', revoked = false, updated_at = now() "
                        "WHERE (kb_chunks.title, kb_chunks.text, kb_chunks.scope, kb_chunks.revoked)"
                        " IS DISTINCT FROM (EXCLUDED.title, EXCLUDED.text, 'release', false)",
                        (chunk.chunk_id, chunk.source, chunk.title, chunk.text, chunk.situation, chunk.persona,
                         chunk.valid_from, chunk.valid_to, json.dumps(dict(chunk.provenance), ensure_ascii=False)),
                    )
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK,))
    return len(entries)


#: What is served: a release entry, or a console entry a person approved.
ROWS = ("SELECT chunk_id, source, title, text, situation, persona, valid_from, valid_to, provenance, scope "
        "FROM kb_chunks WHERE NOT revoked AND (scope = 'release' OR approved_at IS NOT NULL) ORDER BY chunk_id")
STAMP = "SELECT count(*) AS n, max(updated_at) AS at FROM kb_chunks"


def prepare() -> KnowledgeBase:
    """Build the index before serving, so the first customer turn does not wait for the model to load."""
    global _kb, _stamp, _checked
    from ...config.database import get_settings

    url, _ = get_settings().require_database_url()
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        rows = conn.execute(ROWS).fetchall()
        stamp = conn.execute(STAMP).fetchone()
    _kb = knowledge.build([_row_chunk(row) for row in rows])
    _stamp, _checked = (stamp["n"], stamp["at"]), time.monotonic()
    return _kb


def _row_chunk(row: dict[str, Any]) -> corpus.Chunk:
    entry = {**(row.get("provenance") or {}), **{k: row[k] for k in ("chunk_id", "source", "title", "text", "situation",
                                                                      "persona", "valid_from", "valid_to")}}
    return corpus.entry_chunk(entry, doc=f"kb_chunks:{row['scope']}")


async def _stored() -> tuple[list[corpus.Chunk], tuple[Any, ...]]:
    """The entries in force, and a stamp that changes whenever they do."""
    pool = await database()
    async with pool.connection() as conn:
        rows = await (await conn.execute(ROWS)).fetchall()
        stamp = await (await conn.execute(STAMP)).fetchone()
    return [_row_chunk(row) for row in rows], (stamp["n"], stamp["at"])


async def _stamp_now() -> tuple[Any, ...]:
    pool = await database()
    async with pool.connection() as conn:
        row = await (await conn.execute(STAMP)).fetchone()
    return row["n"], row["at"]


async def base() -> KnowledgeBase:
    """The index, rebuilt when ``kb_chunks`` changed since it was built."""
    global _kb, _stamp, _checked
    now = time.monotonic()
    if _kb is not None and now - _checked < REFRESH_SECONDS:
        return _kb
    async with _rebuild_lock:
        if _kb is not None and time.monotonic() - _checked < REFRESH_SECONDS:
            return _kb
        stamp = await _stamp_now() if _kb is not None else None
        if _kb is None or stamp != _stamp:
            entries, _stamp = await _stored()
            _kb = await asyncio.to_thread(knowledge.build, entries)
            logger.info("Knowledge base: %d chunks, %s retrieval", len(_kb.chunks), _kb.mode)
        _checked = time.monotonic()
    return _kb


# ── tools ─────────────────────────────────────────────────────────────────


def hit_view(hit: Hit, *, reveal: bool) -> dict[str, Any]:
    chunk = hit.chunk
    return {
        "chunk_id": chunk.chunk_id,
        "doc": chunk.doc,
        "source": chunk.source,
        "title": chunk.title,
        "text": None if chunk.restricted and not reveal else chunk.text,
        "restricted": chunk.restricted,
        "superseded": hit.superseded,
        "validity": hit.validity,
        "instruction": hit.instruction,
        "redirect": hit.redirect,
        "changelog": list(chunk.changelog),
        "situation": chunk.situation,
        "rank": hit.rank,
        "score": hit.score,
        "cosine": hit.cosine,
        "coverage": hit.coverage,
        "absence": hit.absence,
    }


def result_view(result: Result, *, reveal: bool, threshold: float) -> dict[str, Any]:
    return {
        "query": result.query,
        "mode": result.mode,
        "version": get_knowledge_config().version,
        "hits": [hit_view(hit, reveal=reveal) for hit in result.hits],
        "top_score": result.top_score,
        "threshold": threshold,
        "abstain": result.abstain,
        "reason": result.reason,
        "changelog": [{"chunk_id": c.chunk_id, "title": c.title, "text": c.text} for c in result.changelog.values()],
    }


@server.tool(roles={"harness", "admin"}, name="kb_search")
async def kb_search(
    query: str,
    k: int = 5,
    on: str | None = None,
    order_date: str | None = None,
    situation: str | None = None,
) -> dict[str, Any]:
    """Search the shop's policies, Knowledge Gap Loop answers and playbook for what applies to a question.

    Returns the best passages with their scores and flags (restricted,
    superseded and since when, an absence), whether the documents do not
    cover the question (``abstain`` and why), and the changelog entries the
    passages cite.

    Args:
        query: The customer's question in their own words.
        k: How many passages to return, at most 8.
        on: The day of the call, YYYY-MM-DD: which version of a policy is in force.
        order_date: When the question is about an order already placed, the day it was placed; it decides the version instead (CL-01).
        situation: The call's situation, to prefer the playbook entry written for it.
    """
    if not query.strip():
        raise ToolFailure("BAD_REQUEST", "An empty query has no passages")
    kb = await base()
    result = kb.search(query, k=max(1, min(k, MAX_K)), on=on, order_date=order_date, situation=situation)
    settings = kb.settings
    threshold = settings.abstain_cosine if kb.mode == "hybrid" else settings.abstain_coverage
    return result_view(result, reveal=current_role() == "admin", threshold=threshold)


@server.tool(roles={"admin"}, name="kb_upsert")
async def kb_upsert(
    source: Literal["gap", "playbook"],
    title: str,
    text: str,
    situation: str | None = None,
    persona: str | None = None,
    chunk_id: str | None = None,
    provenance: dict[str, Any] | None = None,
    revoke: bool = False,
) -> dict[str, Any]:
    """Add, replace or revoke one Knowledge Gap Loop or playbook entry, saved from the console.

    A new or changed entry waits for a person (``kb_review``) and is not
    served until then. A demo entry lives in the database only; what counts
    as the system's improvement is what a release file holds (section 7.5).

    Args:
        source: gap (an answer of the Knowledge Gap Loop) or playbook.
        title: The question, or the situation it handles.
        text: The answer, or the entry.
        situation: For a playbook entry, its situation from config/situations.yaml.
        persona: For a playbook entry, the kind of customer it is for.
        chunk_id: Omit to add; give it to replace or revoke.
        provenance: call_id and turn of the answer, the passages it cites, who approved it.
        revoke: True to switch the entry off.
    """
    global _checked
    if not text.strip() or not title.strip():
        raise ToolFailure("BAD_REQUEST", "An entry needs a title and text")
    chunk_id = chunk_id or f"{source.upper()}-{uuid.uuid4().hex[:8]}"
    pool = await database()
    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT scope FROM kb_chunks WHERE chunk_id = %s", (chunk_id,))
        existing = await cursor.fetchone()
        if existing and existing["scope"] == "release":
            raise ToolFailure("FORBIDDEN", f"{chunk_id} belongs to a release file; change the file instead")
        await conn.execute(
            "INSERT INTO kb_chunks (chunk_id, source, title, text, situation, persona, provenance, scope, revoked,"
            " updated_at, approved_by, approved_at) VALUES (%s, %s, %s, %s, %s, %s, %s, 'demo', %s, now(), NULL, NULL) "
            "ON CONFLICT (chunk_id) DO UPDATE SET title = EXCLUDED.title, text = EXCLUDED.text,"
            " situation = EXCLUDED.situation, persona = EXCLUDED.persona, provenance = EXCLUDED.provenance,"
            " revoked = EXCLUDED.revoked, updated_at = now(), approved_by = NULL, approved_at = NULL",
            (chunk_id, source, title, text, situation, persona, json.dumps(provenance or {}, ensure_ascii=False), revoke),
        )
    _checked = 0.0  # this process rebuilds on its next search
    return {"chunk_id": chunk_id, "revoked": revoke, "scope": "demo", "status": "revoked" if revoke else "pending"}


PENDING = ("SELECT chunk_id, source, title, text, provenance, created_at, updated_at FROM kb_chunks "
           "WHERE scope = 'demo' AND NOT revoked AND approved_at IS NULL ORDER BY updated_at")


@server.tool(roles={"admin"}, name="kb_pending")
async def kb_pending() -> dict[str, Any]:
    """The Knowledge Gap Loop entries saved from the console that wait for a person, oldest first.

    Each comes with what the gate of section 10.2 would say if it were
    approved now (``gate``: empty when the checks find nothing).
    """
    pool = await database()
    async with pool.connection() as conn:
        rows = await (await conn.execute(PENDING)).fetchall()
    return {"entries": [
        {"chunk_id": r["chunk_id"], "source": r["source"], "question": r["title"], "answer": r["text"],
         "provenance": r["provenance"] or {}, "saved_at": r["updated_at"].isoformat(),
         "gate": list(gap.gate(r["title"], r["text"]))}
        for r in rows
    ]}


@server.tool(roles={"admin"}, name="kb_review")
async def kb_review(chunk_id: str, decision: Literal["approve", "reject"], reviewer: str) -> dict[str, Any]:
    """A person's decision on one waiting Knowledge Gap Loop entry (section 10.2).

    ``approve`` runs the gate first and refuses an entry that fails it; an
    approved entry is served from the next search. ``reject`` switches it off.

    Args:
        chunk_id: The entry, as ``kb_pending`` lists it.
        decision: approve or reject.
        reviewer: Who decided, for the record.
    """
    global _checked
    pool = await database()
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT title, text, scope, revoked, approved_at FROM kb_chunks WHERE chunk_id = %s", (chunk_id,))).fetchone()
        if row is None or row["scope"] != "demo":
            raise ToolFailure("NOT_FOUND", f"No console entry {chunk_id}")
        if row["revoked"] or row["approved_at"] is not None:
            raise ToolFailure("CONFLICT", f"{chunk_id} was already decided")
        if decision == "approve":
            reasons = gap.gate(row["title"], row["text"])
            if reasons:
                raise ToolFailure("GATE", " ".join(reasons))
            await conn.execute(
                "UPDATE kb_chunks SET approved_by = %s, approved_at = now(), updated_at = now(),"
                " provenance = provenance || %s WHERE chunk_id = %s",
                (reviewer, json.dumps({"approved_by": reviewer}, ensure_ascii=False), chunk_id),
            )
        else:
            await conn.execute("UPDATE kb_chunks SET revoked = true, updated_at = now() WHERE chunk_id = %s", (chunk_id,))
    _checked = 0.0  # this process rebuilds on its next search
    return {"chunk_id": chunk_id, "status": "approved" if decision == "approve" else "rejected", "reviewer": reviewer}


if __name__ == "__main__":
    apply_schema(SCHEMA)
    synced = sync_release(get_knowledge_config().version)
    built = prepare()
    logger.info("Knowledge version %d: %d approved entries; %d chunks, %s retrieval",
                get_knowledge_config().version, synced, len(built.chunks), built.mode)
    server.run()
