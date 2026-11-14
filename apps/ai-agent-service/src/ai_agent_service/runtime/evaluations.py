"""The evaluation history and the weekly improvement rounds, in the agent's schema.

``docs/plan/001-vong-cai-tien-hang-tuan-va-dashboard.md``, parts B and C. Until now a run's numbers lived only in its
directory under ``evaluation/runs`` and a round's review was a JSON file someone edited by hand; neither can be shared
by the Airflow worker that runs the loop, the API the admin uses and the pods that serve customers. These tables are
what they share:

- ``eval_runs`` and ``eval_metrics``: one row per scored run (``run_eval.py --ingest``), one per number of it.
- ``improvement_rounds``: one weekly round, its status and what it measured.
- ``improvement_proposals``: each change Reflection proposed in a round, and the person's decision on it.

The review file stays what ``improve publish`` reads (:mod:`ai_agent_service.components.improvement.review`): the
weekly commands copy the proposals into the table and the decisions back, so the rules of who may approve stay in
one place. Every function takes an open connection whose ``search_path`` is the agent's schema.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterable, Mapping

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id TEXT PRIMARY KEY,
    directory TEXT NOT NULL,
    purpose TEXT NOT NULL,
    round TEXT,
    profile TEXT NOT NULL,
    kb_version INTEGER,
    skills_version INTEGER,
    knowledge_version INTEGER,
    cohort_sha256 TEXT,
    n_scenarios INTEGER,
    extractor_version TEXT,
    advisor_model TEXT,
    advisor_context TEXT,
    status TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    week DATE NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS eval_runs_week ON eval_runs (week);
CREATE TABLE IF NOT EXISTS eval_metrics (
    run_id TEXT NOT NULL REFERENCES eval_runs (run_id) ON DELETE CASCADE,
    config TEXT NOT NULL,
    metric TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, config, metric)
);
CREATE TABLE IF NOT EXISTS improvement_rounds (
    name TEXT PRIMARY KEY,
    week DATE NOT NULL,
    status TEXT NOT NULL,
    base_skills_version INTEGER NOT NULL,
    candidate_skills_version INTEGER,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS improvement_proposals (
    id TEXT PRIMARY KEY,
    round TEXT NOT NULL REFERENCES improvement_rounds (name) ON DELETE CASCADE,
    review_file TEXT NOT NULL,
    kind TEXT NOT NULL,
    body JSONB NOT NULL,
    decision TEXT,
    reviewer TEXT,
    note TEXT,
    decided_at TIMESTAMPTZ
);
"""

#: A round, from learning to the admin's last word. ``measured`` and ``harm`` wait for the admin to switch it on.
STATUSES = ("learning", "no_change", "waiting_review", "expired", "rejected", "measuring", "measured", "harm",
            "active", "failed")
DECISIONS = ("approved", "rejected")


def app_database_url() -> str:
    """The app's database for a command run outside the service, with the agent's ``search_path``.

    ``AGENT_DATABASE_URL`` or ``DATABASE_URL`` when set. On a developer's machine only ``EVAL_DATABASE_URL`` is often
    set (the service gets its URL from compose); the app's database is then that one without ``_eval``, the inverse
    of how ``pipeline.eval.runner.use_evaluation_database`` names it. Never an ``*_eval`` database: every evaluation
    run empties it, and the history would go with it."""
    import os
    from urllib.parse import urlsplit, urlunsplit

    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from ..config.database import configured_url, schema

    url, _ = configured_url()
    if not url:
        evaluation = os.environ.get("EVAL_DATABASE_URL", "").strip()
        parts = urlsplit(evaluation)
        name = parts.path.lstrip("/")
        if not evaluation or not name.endswith("_eval"):
            raise RuntimeError("Set DATABASE_URL (the app's database), or EVAL_DATABASE_URL naming a *_eval database")
        url = urlunsplit(parts._replace(path="/" + name[: -len("_eval")]))
    if str(conninfo_to_dict(url).get("dbname") or "").endswith("_eval"):
        raise RuntimeError("The evaluation history must not live in an *_eval database: each run empties it")
    return make_conninfo(url, options=f"-c search_path={schema()},public")


@asynccontextmanager
async def cli_connection() -> AsyncIterator[Any]:
    """An autocommit connection to the app's database for a command run outside the service (ingest, weekly)."""
    import psycopg
    from psycopg.rows import dict_row

    from ..config.database import schema

    url = app_database_url()
    async with await psycopg.AsyncConnection.connect(url, autocommit=True, row_factory=dict_row) as conn:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema()}"', prepare=False)
        await conn.execute(SCHEMA, prepare=False)
        yield conn


async def ensure(conn: Any) -> None:
    await conn.execute(SCHEMA, prepare=False)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


# ── evaluation history ────────────────────────────────────────────────────


async def save_run(conn: Any, record: Mapping[str, Any]) -> None:
    """One run and its numbers (``pipeline.eval.history.summary``); ingesting it again replaces them, never doubles."""
    run = dict(record["run"])
    columns = ("run_id", "directory", "purpose", "round", "profile", "kb_version", "skills_version",
               "knowledge_version", "cohort_sha256", "n_scenarios", "extractor_version", "advisor_model",
               "advisor_context", "status", "started_at", "finished_at", "week")
    async with conn.transaction():
        await conn.execute(
            f"INSERT INTO eval_runs ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) "
            "ON CONFLICT (run_id) DO UPDATE SET "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in columns[1:]) + ", ingested_at = now()",
            tuple(run.get(c) for c in columns))
        await conn.execute("DELETE FROM eval_metrics WHERE run_id = %s", (run["run_id"],))
        for metric in record.get("metrics") or []:
            await conn.execute("INSERT INTO eval_metrics (run_id, config, metric, value) VALUES (%s, %s, %s, %s)",
                               (run["run_id"], metric["config"], metric["metric"], float(metric["value"])))


async def list_runs(conn: Any, *, purpose: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """The scored runs, oldest first, each with ``metrics: {config: {metric: value}}``."""
    where, params = ("WHERE purpose = %s", [purpose]) if purpose else ("", [])
    rows = await (await conn.execute(
        f"SELECT * FROM (SELECT * FROM eval_runs {where} ORDER BY started_at DESC LIMIT %s) recent "
        "ORDER BY started_at", (*params, limit))).fetchall()
    ids = [row["run_id"] for row in rows]
    metrics: dict[str, dict[str, dict[str, float]]] = {run_id: {} for run_id in ids}
    if ids:
        for row in await (await conn.execute(
                "SELECT run_id, config, metric, value FROM eval_metrics WHERE run_id = ANY(%s)", (ids,))).fetchall():
            metrics[row["run_id"]].setdefault(row["config"], {})[row["metric"]] = row["value"]
    return [{**_jsonable(dict(row)), "metrics": metrics[row["run_id"]]} for row in rows]


# ── weekly rounds ─────────────────────────────────────────────────────────


async def start_round(conn: Any, name: str, *, week: str, base_skills_version: int) -> None:
    """A round begins learning; running the same week again starts it over (its proposals with it)."""
    await conn.execute(
        "INSERT INTO improvement_rounds (name, week, status, base_skills_version) VALUES (%s, %s, 'learning', %s) "
        "ON CONFLICT (name) DO UPDATE SET status = 'learning', base_skills_version = EXCLUDED.base_skills_version, "
        "candidate_skills_version = NULL, detail = '{}'::jsonb, updated_at = now()",
        (name, week, base_skills_version))
    await conn.execute("DELETE FROM improvement_proposals WHERE round = %s", (name,))


async def set_round(conn: Any, name: str, *, status: str, detail: Mapping[str, Any] | None = None,
                    candidate_skills_version: int | None = None) -> None:
    if status not in STATUSES:
        raise ValueError(f"Unknown round status {status!r}")
    from psycopg.types.json import Jsonb

    await conn.execute(
        "UPDATE improvement_rounds SET status = %s, updated_at = now(), "
        "detail = detail || %s, candidate_skills_version = COALESCE(%s, candidate_skills_version) WHERE name = %s",
        (status, Jsonb(_jsonable(dict(detail or {}))), candidate_skills_version, name))


async def add_proposals(conn: Any, name: str, review_file: str, proposals: Iterable[Mapping[str, Any]]) -> int:
    """The proposals of one review file, each waiting for a person (a decision already in the file is kept)."""
    from psycopg.types.json import Jsonb

    count = 0
    for item in proposals:
        await conn.execute(
            "INSERT INTO improvement_proposals (id, round, review_file, kind, body, decision, reviewer, note) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body",
            (str(item["proposal_id"]), name, review_file, str(item.get("kind") or "skill"),
             Jsonb(_jsonable(dict(item))), item.get("decision"), item.get("reviewer"), item.get("note")))
        count += 1
    return count


async def get_round(conn: Any, name: str) -> dict[str, Any] | None:
    row = await (await conn.execute("SELECT * FROM improvement_rounds WHERE name = %s", (name,))).fetchone()
    if row is None:
        return None
    proposals = await (await conn.execute(
        "SELECT * FROM improvement_proposals WHERE round = %s ORDER BY id", (name,))).fetchall()
    return {**_jsonable(dict(row)), "proposals": [_jsonable(dict(p)) for p in proposals]}


async def list_rounds(conn: Any, *, limit: int = 52) -> list[dict[str, Any]]:
    """The latest rounds, newest first, with how many proposals each has and how many still wait."""
    rows = await (await conn.execute(
        "SELECT r.*, count(p.id) AS proposals, count(p.id) FILTER (WHERE p.decision IS NULL) AS pending "
        "FROM improvement_rounds r LEFT JOIN improvement_proposals p ON p.round = r.name "
        "GROUP BY r.name ORDER BY r.week DESC, r.name DESC LIMIT %s", (limit,))).fetchall()
    return [_jsonable(dict(row)) for row in rows]


async def decide(conn: Any, proposal_id: str, *, decision: str, reviewer: str, note: str) -> dict[str, Any]:
    """A person's decision on one proposal of a round still waiting for review."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    if not reviewer.strip():
        raise ValueError("A decision needs the reviewer")
    async with conn.transaction():
        row = await (await conn.execute(
            "SELECT p.id, p.decision, r.status FROM improvement_proposals p JOIN improvement_rounds r "
            "ON r.name = p.round WHERE p.id = %s FOR UPDATE OF p", (proposal_id,))).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        if row["status"] != "waiting_review":
            raise PermissionError(f"The round is {row['status']}: decisions are taken only while it waits for review")
        await conn.execute(
            "UPDATE improvement_proposals SET decision = %s, reviewer = %s, note = %s, decided_at = now() "
            "WHERE id = %s", (decision, reviewer, note, proposal_id))
    found = await (await conn.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))).fetchone()
    return _jsonable(dict(found))


def pending(round_: Mapping[str, Any]) -> list[str]:
    return [str(p["id"]) for p in round_.get("proposals") or [] if not p.get("decision")]


def decisions_by_file(round_: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The round's decided proposals, grouped by the review file they came from."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for proposal in round_.get("proposals") or []:
        if proposal.get("decision"):
            grouped.setdefault(str(proposal["review_file"]), []).append(proposal)
    return grouped


def age_days(round_: Mapping[str, Any], now: datetime | None = None) -> float:
    updated = datetime.fromisoformat(str(round_["updated_at"]))
    return ((now or datetime.now(timezone.utc)) - updated).total_seconds() / 86400
