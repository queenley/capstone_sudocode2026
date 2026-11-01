"""Real stdio/Memory/PostgreSQL path, without an agent or a paid model call."""
import asyncio
import os
from contextlib import AsyncExitStack
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql

from ai_agent_service.mcp import client, server_base
from ai_agent_service.mcp.tools import ToolBox
from ai_agent_service.pipeline.eval import runner
from ai_agent_service.pipeline.eval.scenarios import SeedSession


@pytest_asyncio.fixture
async def memory_postgres(monkeypatch, tmp_path):
    url = os.getenv("EVAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set EVAL_TEST_DATABASE_URL to a private local *_eval database")
    parsed = urlsplit(url)
    assert parsed.scheme == "postgresql" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.endswith("_eval") and not parsed.query
    schema = "seed_test_" + uuid4().hex
    for variable in ("EVAL_DATABASE_URL", "AGENT_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.setenv(variable, url)
    monkeypatch.setenv("AGENT_DB_SCHEMA", schema)
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MCP_LOG_FILE", str(tmp_path / "mcp.log"))
    monkeypatch.setattr(server_base, "_pool", None)
    monkeypatch.setattr(server_base, "_pool_lock", asyncio.Lock())
    monkeypatch.setattr(client, "SERVERS", {"memory": "ai_agent_service.mcp.servers.memory"})
    monkeypatch.setattr(client, "_adapters", {})
    monkeypatch.setattr(client, "_tool_names", {})
    monkeypatch.setattr(client, "_stack", AsyncExitStack())
    monkeypatch.setattr(client, "_lock", asyncio.Lock())
    runner.use_evaluation_database()
    try:
        writer = ToolBox(await client.tools_for("memory_writer"), timeout=10)
        await runner.reset()
        yield SimpleNamespace(writer=writer)
    finally:
        await client.close_all()
        if server_base._pool is not None:
            await server_base._pool.close()
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.asyncio
async def test_cold_writer_seeds_history_visible_to_another_mcp_role(memory_postgres, monkeypatch):
    rig = memory_postgres
    # A CRM-known owner goes directly to commit_facts: the writer's first DB call.
    monkeypatch.setattr(runner.btc, "mock", lambda: SimpleNamespace(
        crm_get_customer=lambda **_: {"found": True, "customer_id": "synthetic-owner"}))
    sessions = (SeedSession("S-SYNTHETIC", "2035-02-03", "hotline", "Synthetic prior session",
                            "hen_goi_lai", {"budget_vnd": 123000}),)
    owner = await runner.seed(rig, sessions, customer_phone="0900000000", customer_name=None)
    assert owner == "synthetic-owner"
    reader = ToolBox(await client.tools_for("harness"), timeout=10)
    profile = await reader.call("memory_get_profile", customer_id=owner, on="2035-02-03")
    assert profile["ok"] and [(f["slot"], f["value"]) for f in profile["data"]["facts"]] == [
        ("budget_vnd", 123000)]
    episodes = await reader.call("memory_get_episodes", customer_id=owner)
    assert episodes["ok"] and len(episodes["data"]["episodes"]) == 1
    # Reset is autocommitted in the parent and must release its locks before seeding again.
    await runner.reset()
    await runner.seed(rig, sessions, customer_phone="0900000000", customer_name=None)
    profile = await reader.call("memory_get_profile", customer_id=owner, on="2035-02-03")
    assert profile["ok"] and len(profile["data"]["facts"]) == 1


@pytest.mark.asyncio
async def test_evaluation_lock_excludes_other_connections_and_releases_after_failure(memory_postgres):
    url = os.environ["EVAL_TEST_DATABASE_URL"]
    conn = await psycopg.AsyncConnection.connect(url, autocommit=True)
    try:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            async with runner.evaluation_lock():
                result = await conn.execute("SELECT pg_try_advisory_lock(%s)", (runner.EVALUATION_LOCK,))
                assert (await result.fetchone())[0] is False
                raise RuntimeError("synthetic failure")
        result = await conn.execute("SELECT pg_try_advisory_lock(%s)", (runner.EVALUATION_LOCK,))
        assert (await result.fetchone())[0] is True
        await conn.execute("SELECT pg_advisory_unlock(%s)", (runner.EVALUATION_LOCK,))
    finally:
        await conn.close()
