"""A failed/cancelled lazy pool must not keep unowned connection workers."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import anyio
import pytest

from ai_agent_service.config import database as config
from ai_agent_service.mcp import server_base


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["open", "wait", "cancel", "cancel_scope"])
async def test_pool_startup_failure_closes_pool_and_allows_a_fresh_connection(monkeypatch, failure):
    started = asyncio.Event()
    closed = []

    async def close():
        await anyio.sleep(0)
        closed.append(True)

    async def wait(**kwargs):
        started.set()
        if failure == "cancel":
            await asyncio.Future()
        if failure == "cancel_scope":
            await anyio.sleep_forever()
        raise RuntimeError("synthetic startup failure")

    bad = SimpleNamespace(open=AsyncMock(), wait=AsyncMock(side_effect=wait), close=AsyncMock(side_effect=close))
    good = SimpleNamespace(open=AsyncMock(), wait=AsyncMock(), close=AsyncMock())
    if failure == "open":
        bad.open.side_effect = RuntimeError("synthetic startup failure")
    factory = Mock(side_effect=[bad, good])
    monkeypatch.setattr(server_base, "AsyncConnectionPool", factory)
    monkeypatch.setattr(server_base, "_pool", None)
    monkeypatch.setattr(server_base, "_pool_lock", asyncio.Lock())
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        require_database_url=lambda: ("postgresql://synthetic/synthetic_eval", "EVAL_DATABASE_URL")))

    if failure == "cancel_scope":
        with pytest.raises(TimeoutError), anyio.fail_after(.01):
            await server_base.database()
    elif failure == "cancel":
        task = asyncio.create_task(server_base.database())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError, match="synthetic startup failure"):
            await server_base.database()
    bad.close.assert_awaited_once()
    assert closed == [True]
    assert server_base._pool is None
    assert await server_base.database() is good
    assert await server_base.database() is good
    assert factory.call_count == 2
