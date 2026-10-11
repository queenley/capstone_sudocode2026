"""The agent's PostgreSQL access: one async pool, the LangGraph checkpointer, the call tables.

Ported from the reference project's ``api/db.py`` (``docs/design.md`` section 3.1)
with two changes for this platform:

* Everything is in the agent's own schema (``config.database``): the pool's
  connections set ``search_path``, so the SQL below stays unqualified.
* There is no ``users`` table here. People are authenticated by the platform
  (identity service tokens, conversation tokens); a call row stores the
  platform's ``conversation_id`` and staff actor ids as plain text.

A *call* is the agent's unit of work: one platform conversation is one call.
``turns`` is the transcript as the agent saw it (tokenised), with the console
metadata of every agent turn; the platform's ``conversation.messages`` keeps
the customer-facing copy (``runtime.platform``).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ..agents import CHECKPOINTED_TYPES
from ..config.database import database_url, ensure_schema

logger = logging.getLogger(__name__)

SCHEMA = """
-- A call is a platform conversation while the assistant is active; a conversation that
-- goes idle is remembered and its next message opens a new call (docs/design.md 3.1).
CREATE TABLE IF NOT EXISTS calls (
    id                   BIGSERIAL PRIMARY KEY,
    conversation_id      UUID,
    customer_key         TEXT,
    phone_last4          TEXT,
    channel              TEXT NOT NULL CHECK (channel IN ('web', 'hotline', 'zalo', 'facebook')),
    tier                 TEXT NOT NULL DEFAULT 'UNKNOWN',
    lane                 TEXT NOT NULL DEFAULT 'NEW',
    mode                 TEXT NOT NULL DEFAULT 'speak',
    brief                JSONB NOT NULL DEFAULT '[]',
    warnings             JSONB NOT NULL DEFAULT '[]',
    opened_by            TEXT,
    started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at             TIMESTAMPTZ,
    turn_lease_until     TIMESTAMPTZ,
    handoff_status       TEXT,
    handoff_reason       TEXT,
    handoff_requested_at TIMESTAMPTZ,
    accepted_by          TEXT,
    accepted_at          TIMESTAMPTZ,
    suggestion           JSONB,
    customer_id          TEXT,
    customer_label       TEXT,
    channel_ref          TEXT,
    caller_token         TEXT,
    business_day         DATE,
    brief_object         JSONB,
    route_reason         TEXT,
    handoff_brief        JSONB,
    memory_status        TEXT,
    after_call           JSONB
);

CREATE INDEX IF NOT EXISTS calls_conversation_idx ON calls (conversation_id, started_at DESC);
CREATE INDEX IF NOT EXISTS calls_customer_idx ON calls (customer_key, started_at DESC);
CREATE INDEX IF NOT EXISTS calls_open_idx ON calls (started_at DESC) WHERE ended_at IS NULL;

-- One utterance. meta carries what the console needs to explain an agent turn:
-- lane, tier, model, brief lines used, tool calls with arguments and results.
CREATE TABLE IF NOT EXISTS turns (
    id         BIGSERIAL PRIMARY KEY,
    call_id    BIGINT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    turn_id    TEXT NOT NULL,
    speaker    TEXT NOT NULL CHECK (speaker IN ('customer', 'agent', 'human_agent', 'system')),
    content    TEXT NOT NULL,
    meta       JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS turns_turn_idx ON turns (call_id, turn_id, speaker);
CREATE INDEX IF NOT EXISTS turns_call_idx ON turns (call_id, created_at);

-- docs/design.md section 4.1: a call's personal data, one row per token, the
-- value encrypted. The model, the checkpoint and the transcript hold only the token.
CREATE TABLE IF NOT EXISTS pii_vault (
    call_id     BIGINT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    token       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    value_enc   BYTEA NOT NULL,
    customer_id TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (call_id, token)
);
"""

_pool: AsyncConnectionPool | None = None
_pool_lock = asyncio.Lock()
_checkpointer: AsyncPostgresSaver | None = None


async def pool() -> AsyncConnectionPool:
    """The process-wide pool, opened on first use."""
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            url, source = database_url()
            logger.info("Agent connecting to PostgreSQL using %s", source)
            pool_ = AsyncConnectionPool(
                url,
                min_size=1,
                max_size=5,
                open=False,
                timeout=10,
                kwargs={
                    "row_factory": dict_row,
                    "connect_timeout": 10,
                    # The LangGraph checkpointer shares this pool and expects
                    # autocommit with server-side prepared statements off.
                    "autocommit": True,
                    "prepare_threshold": 0,
                },
            )
            await pool_.open()
            try:
                await pool_.wait(timeout=12)
            except Exception as error:
                await pool_.close()
                raise RuntimeError(f"Could not reach the agent database ({source}): {type(error).__name__}: {error}") from error
            _pool = pool_
    return _pool


@asynccontextmanager
async def connection() -> AsyncIterator[Any]:
    """A pooled, autocommit connection."""
    pool_ = await pool()
    async with pool_.connection() as conn:
        yield conn


async def init_db() -> None:
    """Create the schema and the call tables. Safe to run on every start."""
    await asyncio.to_thread(ensure_schema)
    try:
        async with connection() as conn:
            await conn.execute(SCHEMA, prepare=False)
    except (psycopg.errors.UniqueViolation, psycopg.errors.DuplicateTable, psycopg.errors.DuplicateObject):
        logger.info("Another process created the agent tables first; continuing")


async def init_checkpointer() -> AsyncPostgresSaver:
    """The hot graph's working memory (section 3.1), over the shared pool, once."""
    global _checkpointer
    if _checkpointer is None:
        serde = JsonPlusSerializer(
            allowed_msgpack_modules=[(cls.__module__, cls.__name__) for cls in CHECKPOINTED_TYPES]
        )
        saver = AsyncPostgresSaver(await pool(), serde=serde)
        await saver.setup()
        _checkpointer = saver
        logger.info("Agent checkpointer ready")
    return _checkpointer


def checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError("init_checkpointer() runs in the app lifespan before the first turn")
    return _checkpointer


def checkpointer_ready() -> bool:
    return _checkpointer is not None


async def ping() -> dict[str, Any]:
    try:
        async with connection() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as error:  # noqa: BLE001 - this is the report
        return {"status": "error", "detail": f"{type(error).__name__}: {error}"[:200]}


async def close_pool() -> None:
    global _pool, _checkpointer
    _checkpointer = None
    if _pool is not None:
        await _pool.close()
        _pool = None
