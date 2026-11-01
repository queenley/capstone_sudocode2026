from conftest import conversation, identify
from test_workflows import order_body, SELLER


def checkout(client):
    c, headers = conversation(client)
    token = identify(client, c, headers)
    return c, headers, {"Authorization": "Bearer " + token}, order_body(client)


def test_omitted_payment_cannot_bypass_cod_limit(client):
    c, headers, _, body = checkout(client)
    body.pop("payment_method")
    assert client.post(f"/api/conversations/{c}/orders", headers=headers, json=body).status_code == 422


def test_payment_methods_is_not_captured_as_a_sku(client):
    response = client.get("/api/catalog/payment-methods")
    assert response.status_code == 200
    assert response.json()["cod"] == {"enabled": True, "max_total": "10000000"}


def test_replay_must_match_payment_total_price_and_confirmation(client):
    c, headers, _, body = checkout(client)
    assert client.post(f"/api/conversations/{c}/orders", headers=headers, json=body).status_code == 201
    for changes in [{"payment_method": "cod"}, {"expected_total": "1"},
                    {"expected_unit_price": "1"}, {"confirmed": False}]:
        assert client.post(f"/api/conversations/{c}/orders", headers=headers, json={**body, **changes}).status_code == 409


def test_lost_checkout_response_is_recoverable_only_by_its_owner(client):
    c, headers, customer, body = checkout(client)
    created = client.post(f"/api/conversations/{c}/orders", headers=headers, json=body).json()
    path = "/api/customer/orders/by-key/" + body["idempotency_key"]
    assert client.get(path, headers=customer).json()["id"] == created["id"]
    other, other_headers = conversation(client)
    other_token = identify(client, other, other_headers, phone="0901234568")
    assert client.get(path, headers={"Authorization": "Bearer " + other_token}).status_code == 404
    assert client.get(path).status_code == 401
    for _ in range(2):
        assert client.post(f"/api/seller/orders/{created['id']}/cancel", headers=SELLER, json={}).status_code == 200
    assert client.get(path, headers=customer).json()["status"] == "cancelled"


def test_deletion_receipt_survives_account_revocation_and_waits_for_agent_ack(client, monkeypatch):
    from sqlalchemy import select
    from src.db.models import Outbox
    from src.messaging.worker import process
    from src.identity import deletion
    c, _, customer, _ = checkout(client)
    receipt = client.delete("/api/customer/data", headers=customer).json()
    assert receipt["agent_data_status"] == "pending"
    assert client.get("/api/customer/me", headers=customer).status_code == 401
    url = "/api/customer/deletions/" + receipt["deletion_id"]
    headers = {"Authorization": "Bearer " + receipt["deletion_token"]}
    assert client.get(url, headers=customer).status_code == 403
    assert client.get(url, headers=headers).json() == {"status": "pending"}
    delivered = []
    monkeypatch.setattr(deletion, "deliver", lambda event, settings: delivered.append(event["id"]))
    with client.app.state.database.sessions() as db:
        event = db.scalar(select(Outbox).where(Outbox.id == receipt["deletion_id"]))
        assert c in event.payload["conversation_ids"]
        command = {"id": str(event.id), "event_type": event.event_type, "payload": event.payload}
        assert process(db, command)
        assert not process(db, command)
        db.commit()
    assert delivered == [receipt["deletion_id"]]
    assert client.get(url, headers=headers).json() == {"status": "deleted"}
