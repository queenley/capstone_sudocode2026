from conftest import conversation

ADMIN = {"Authorization": "Bearer local-admin-change-me"}
AGENT = {"Authorization": "Bearer local-agent-change-me"}


def test_human_transfer_and_return_to_ai(client):
    c, h = conversation(client)
    client.post(
        f"/api/conversations/{c}/turns", headers=h, json={"message": "gặp nhân viên"}
    )
    assert (
        client.post(
            f"/api/staff/conversations/{c}/claim", headers=AGENT, json={}
        ).status_code
        == 200
    )
    user = client.post(
        "/api/admin/users",
        headers=ADMIN,
        json={
            "username": "second-agent",
            "password": "secure-password-123",
            "role": "agent",
        },
    ).json()
    assert (
        client.post(
            f"/api/staff/conversations/{c}/transfer",
            headers=AGENT,
            json={"to_actor_id": user["id"], "reason": "Shift change"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/staff/conversations/{c}/claim", headers=AGENT, json={}
        ).status_code
        == 409
    )
    token = client.post(
        "/api/auth/login",
        json={"username": "second-agent", "password": "secure-password-123"},
    ).json()["access_token"]
    second = {"Authorization": "Bearer " + token}
    assert (
        client.post(
            f"/api/staff/conversations/{c}/claim", headers=second, json={}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/staff/conversations/{c}/transfer",
            headers=second,
            json={"reason": "Customer requested AI continuation"},
        ).json()["status"]
        == "open"
    )
    assert (
        client.post(
            f"/api/conversations/{c}/turns", headers=h, json={"message": "xin chào"}
        ).status_code
        == 200
    )
