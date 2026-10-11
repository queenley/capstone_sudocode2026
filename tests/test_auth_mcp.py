import asyncio
import importlib

ADMIN = {"Authorization": "Bearer local-admin-change-me"}


def test_staff_login_revocation_and_rbac(client):
    result = client.post(
        "/api/admin/users",
        headers=ADMIN,
        json={
            "username": "test-agent",
            "password": "test-password-123",
            "role": "agent",
        },
    )
    assert result.status_code == 201
    user_id = result.json()["id"]
    assert (
        client.post(
            "/api/auth/login", json={"username": "test-agent", "password": "wrong"}
        ).status_code
        == 401
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "test-agent", "password": "test-password-123"},
    )
    assert login.status_code == 200
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.get("/api/staff/conversations", headers=headers).status_code == 200
    assert client.get("/api/admin/proposals", headers=headers).status_code == 403
    assert (
        client.delete("/api/admin/users/" + user_id, headers=ADMIN).status_code == 200
    )
    assert client.get("/api/staff/conversations", headers=headers).status_code == 403


def test_agent_mcp_servers_cover_the_btc_tools():
    """The organisers' nine tools (dotted names on the wire) are all served."""
    names = set()
    for module in ("catalog", "crm", "order", "memory", "knowledge"):
        server = importlib.import_module(f"ai_agent_service.mcp.servers.{module}").server
        names |= {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert {
        "catalog_search", "inventory_check", "pricing_get_quote", "crm_get_customer",
        "order_create", "order_status", "order_update", "schedule_callback", "handoff_transfer",
        "memory_get_profile", "kb_search",
    } <= names
