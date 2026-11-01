"""Database URL and concurrent-run guards do not need a live database."""
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from ai_agent_service.pipeline.eval import runner


@pytest.mark.parametrize("url", [
    "postgresql://user@localhost/safe_eval?dbname=production",
    "postgresql://user@localhost/production",
    "postgresql://user@localhost/safe_eval?dbname=other%5Feval%2Fproduction",
    "sqlite:///safe_eval",
])
def test_effective_database_name_is_checked_before_any_connection(monkeypatch, url):
    monkeypatch.setenv("EVAL_DATABASE_URL", url)
    connect = Mock()
    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(RuntimeError):
        runner.use_evaluation_database()
    connect.assert_not_called()


def test_encoded_name_and_query_override_use_the_same_database_for_prepare_and_run(monkeypatch):
    url = "postgresql://user@localhost/unused?dbname=synthetic%5Feval"
    monkeypatch.setenv("EVAL_DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setenv("AGENT_DATABASE_URL", "unused")
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = (1,)
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    connect = Mock(return_value=connection)
    monkeypatch.setattr(psycopg, "connect", connect)
    assert runner.use_evaluation_database() == "synthetic_eval"
    assert conninfo_to_dict(connect.call_args.args[0])["dbname"] == "postgres"
    assert os.environ["AGENT_DATABASE_URL"] == url
    assert connection.execute.call_args.args[1] == ("synthetic_eval",)


def test_derived_database_appends_suffix_to_effective_name(monkeypatch):
    from ai_agent_service.config import database

    monkeypatch.delenv("EVAL_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setenv("AGENT_DATABASE_URL", "unused")
    monkeypatch.setattr(database, "configured_url", lambda: (
        "postgresql://user@localhost/unused?dbname=synthetic&application_name=eval", "DATABASE_URL"))
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = (1,)
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(psycopg, "connect", Mock(return_value=connection))
    assert runner.use_evaluation_database() == "synthetic_eval"
    actual = conninfo_to_dict(os.environ["AGENT_DATABASE_URL"])
    assert actual["dbname"] == "synthetic_eval" and actual["application_name"] == "eval"


def fake_pool(monkeypatch, *, acquired=True, name="synthetic_eval"):
    values = [{"name": name}, {"acquired": acquired}]
    connection = SimpleNamespace(execute=AsyncMock(side_effect=[
        SimpleNamespace(fetchone=AsyncMock(return_value=value)) for value in values
    ] + [None]))

    @asynccontextmanager
    async def connect():
        yield connection

    monkeypatch.setattr(runner, "database", AsyncMock(return_value=SimpleNamespace(connection=connect)))
    return connection


@pytest.mark.asyncio
async def test_competing_run_fails_before_entering_or_unlocking_another_run(monkeypatch):
    connection = fake_pool(monkeypatch, acquired=False)
    with pytest.raises(RuntimeError, match="Another evaluation"):
        async with runner.evaluation_lock():
            pytest.fail("A competing run cannot reset shared state or call a model")
    assert connection.execute.await_count == 2


@pytest.mark.asyncio
async def test_run_failure_always_releases_the_database_lock(monkeypatch):
    connection = fake_pool(monkeypatch)
    with pytest.raises(ValueError, match="synthetic failure"):
        async with runner.evaluation_lock():
            raise ValueError("synthetic failure")
    assert "pg_advisory_unlock" in connection.execute.await_args.args[0]
    assert connection.execute.await_args.args[1] == (runner.EVALUATION_LOCK,)


@pytest.mark.asyncio
async def test_lock_rejects_a_pool_that_was_opened_before_eval_database_selection(monkeypatch):
    connection = fake_pool(monkeypatch, name="production")
    with pytest.raises(RuntimeError, match="named"):
        async with runner.evaluation_lock():
            pytest.fail("The agent must never run in a previously opened production pool")
    assert connection.execute.await_count == 1
