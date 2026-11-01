"""Keep role-specific MCP connections small and reusable without a model call."""

import asyncio
import importlib
from contextlib import AsyncExitStack

import pytest

from ai_agent_service.mcp import client


def test_each_role_only_connects_servers_with_permitted_business_tools():
    for name, module in client.SERVERS.items():
        server = importlib.import_module(module).server
        permitted = set().union(*(roles for tool, roles in server._allowed.items() if tool != "health"))
        assert client.SERVER_ROLES[name] == permitted
    assert set(client.client_group("memory_writer").clients) == {"memory"}
    assert set(client.client_group("admin").clients) == {"memory", "knowledge"}
    assert "knowledge" not in client.client_group("advisor").clients


@pytest.mark.asyncio
async def test_stdio_adapter_reuses_connection_and_reconnects_after_shutdown(tmp_path, monkeypatch):
    # Real stdio protocol and adapter, with no database, provider or model weights.
    (tmp_path / "fixture_mcp.py").write_text(
        'from fastmcp import FastMCP\n'
        'm = FastMCP("memory")\n'
        '@m.tool\n'
        'def ping(value: str) -> str:\n'
        '    return value\n'
        'm.run(transport="stdio", show_banner=False)\n'
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setattr(client, "SERVERS", {"memory": "fixture_mcp"})
    monkeypatch.setattr(client, "_adapters", {})
    monkeypatch.setattr(client, "_tool_names", {})
    monkeypatch.setattr(client, "_stack", AsyncExitStack())
    monkeypatch.setattr(client, "_lock", asyncio.Lock())
    try:
        for _ in range(2):
            tools = await asyncio.wait_for(client.tools_for("memory_writer"), 30)
            adapter = client._adapters["memory_writer"]
            for value in ("one", "two"):
                again = await client.tools_for("memory_writer")
                assert client._adapters["memory_writer"] is adapter
                assert [t.name for t in tools] == ["ping"]
                result = await again[0].ainvoke({"value": value})
                assert value in str(result)
            await client.close_all()
            assert not client.status()
    finally:
        await client.close_all()
