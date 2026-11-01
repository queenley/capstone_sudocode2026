"""Platform workflows end to end: identity, orders, promotions, knowledge review, handoff.

Agent behaviour (lanes, guard, memory) is tested in ``tests/agent``; here the
agent is the scripted stand-in from ``conftest``.
"""

from decimal import Decimal
from datetime import timedelta
from sqlalchemy import select
from src.db.models import Handoff, ProfileFact, Outbox, Promotion, Proposal, SKU, now
from conftest import conversation, identify

ADMIN = {"Authorization": "Bearer local-admin-change-me"}
SELLER = {"Authorization": "Bearer local-seller-change-me"}


def send(client, c, h, text, **extra):
    response = client.post(
        f"/api/conversations/{c}/turns", headers=h, json={"message": text, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def order_body(client):
    enable_bank(client)
    quote = client.get("/api/catalog/ASUS-V16-BLACK/quote").json()
    return {
        "sku_code": quote["sku_code"],
        "quantity": 1,
        "shipping_address": "123 Test Street",
        "expected_unit_price": quote["sale_price"],
        "expected_total": quote["total"],
        "confirmed": True,
        "idempotency_key": "purchase-0001",
        "payment_method": "bank_transfer",
    }


def enable_bank(client):
    from dataclasses import replace
    security = client.app.state.security
    security.settings = replace(security.settings, bank_bin="970436", bank_account_no="0000000000",
                                bank_name="Test bank", bank_account_name="Test shop")


def test_health_and_catalog(client):
    assert client.get("/health/ready").status_code == 200
    assert len(client.get("/api/catalog").json()) == 3
    assert len(client.get("/api/catalog?q=laptop&budget=18000000").json()) == 1


def test_customer_isolation(client):
    a, ha = conversation(client)
    b, hb = conversation(client)
    assert client.get(f"/api/conversations/{a}", headers=hb).status_code == 404
    assert client.get(f"/api/conversations/{b}", headers=ha).status_code == 404


def test_identity_requires_consent_and_code(client):
    c, h = conversation(client)
    assert (
        client.post(
            f"/api/conversations/{c}/identity/challenge",
            headers=h,
            json={"kind": "phone", "value": "0901234567", "consent": False},
        ).status_code
        == 422
    )
    challenge = client.post(
        f"/api/conversations/{c}/identity/challenge",
        headers=h,
        json={"kind": "phone", "value": "0901234567", "consent": True},
    ).json()
    wrong = "000000" if challenge["development_code"] != "000000" else "111111"
    for _ in range(5):
        assert (
            client.post(
                f"/api/conversations/{c}/identity/verify",
                headers=h,
                json={"challenge_id": challenge["challenge_id"], "code": wrong},
            ).status_code
            == 422
        )
    assert (
        client.post(
            f"/api/conversations/{c}/identity/verify",
            headers=h,
            json={
                "challenge_id": challenge["challenge_id"],
                "code": challenge["development_code"],
            },
        ).status_code
        == 422
    )


def test_shared_phone_does_not_disclose_context(client):
    c, h = conversation(client)
    identify(client, c, h)
    second, headers = conversation(client)
    challenge = client.post(
        f"/api/conversations/{second}/identity/challenge",
        headers=headers,
        json={"kind": "phone", "value": "0901234567", "consent": True},
    ).json()
    result = client.post(
        f"/api/conversations/{second}/identity/verify",
        headers=headers,
        json={
            "challenge_id": challenge["challenge_id"],
            "code": challenge["development_code"],
        },
    )
    assert result.status_code == 409
    assert (
        client.get(f"/api/conversations/{second}", headers=headers).json()[
            "customer_id"
        ]
        is None
    )


def test_order_confirmation_price_and_idempotency(client):
    c, h = conversation(client)
    body = order_body(client)
    assert (
        client.post(f"/api/conversations/{c}/orders", headers=h, json=body).status_code
        == 403
    )
    identify(client, c, h)
    assert (
        client.post(
            f"/api/conversations/{c}/orders",
            headers=h,
            json={**body, "confirmed": False},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/conversations/{c}/orders",
            headers=h,
            json={**body, "expected_total": "1"},
        ).status_code
        == 409
    )
    first = client.post(f"/api/conversations/{c}/orders", headers=h, json=body)
    assert first.status_code == 201, first.text
    repeat = client.post(f"/api/conversations/{c}/orders", headers=h, json=body)
    assert repeat.json()["id"] == first.json()["id"]
    assert client.get("/api/catalog/ASUS-V16-BLACK").json()["available"] == 11
    assert (
        client.post(
            f"/api/conversations/{c}/orders", headers=h, json={**body, "quantity": 2}
        ).status_code
        == 409
    )
    with client.app.state.database.sessions() as db:
        assert (
            len(
                db.scalars(
                    select(Outbox).where(Outbox.event_type == "order.created")
                ).all()
            )
            == 1
        )


def test_insufficient_stock_rolls_back(client):
    c, h = conversation(client)
    identify(client, c, h)
    quote = client.get("/api/catalog/ASUS-V16-BLACK/quote?quantity=13").json()
    body = {**order_body(client), "quantity": 13, "expected_total": quote["total"]}
    assert (
        client.post(f"/api/conversations/{c}/orders", headers=h, json=body).status_code
        == 409
    )
    assert client.get("/api/catalog/ASUS-V16-BLACK").json()["available"] == 12
    assert client.get("/api/seller/orders", headers=SELLER).json() == []


def test_cancel_releases_inventory_once(client):
    c, h = conversation(client)
    identify(client, c, h)
    order = client.post(
        f"/api/conversations/{c}/orders", headers=h, json=order_body(client)
    ).json()
    for _ in range(2):
        assert (
            client.post(
                f"/api/seller/orders/{order['id']}/cancel", headers=SELLER, json={}
            ).status_code
            == 200
        )
    assert client.get("/api/catalog/ASUS-V16-BLACK").json()["available"] == 12


def test_expired_and_wrong_channel_promotions(client):
    with client.app.state.database.sessions() as db:
        sku = db.scalar(select(SKU).where(SKU.sku_code == "ASUS-V16-BLACK"))
        for channel, start, end in [
            ("web", now() - timedelta(days=2), now() - timedelta(days=1)),
            ("hotline", now() - timedelta(days=1), now() + timedelta(days=1)),
        ]:
            db.add(
                Promotion(
                    sku_id=sku.id,
                    name="test",
                    description="test",
                    channel=channel,
                    promotion_type="fixed",
                    value=1000000,
                    starts_at=start,
                    ends_at=end,
                )
            )
        db.commit()
    assert client.get("/api/catalog/ASUS-V16-BLACK/quote").json()["discount"] == "0"
    assert (
        Decimal(
            client.get("/api/catalog/ASUS-V16-BLACK/quote?channel=hotline").json()[
                "discount"
            ]
        )
        == 1000000
    )


def test_knowledge_requires_human_approval(client):
    with client.app.state.database.sessions() as db:
        db.add(Proposal(kind="knowledge_gap", candidate={"question": "Policy quasar?"}))
        db.commit()
    proposal = client.get("/api/admin/proposals", headers=ADMIN).json()[0]
    path = f"/api/admin/proposals/{proposal['id']}/review"
    assert (
        client.post(
            path,
            headers=SELLER,
            json={
                "decision": "approved",
                "knowledge_text": "Quasar policy: unsupported.",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            path,
            headers=ADMIN,
            json={
                "decision": "approved",
                "knowledge_text": "Quasar policy: unsupported.",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            path,
            headers=ADMIN,
            json={"decision": "approved", "knowledge_text": "again"},
        ).status_code
        == 409
    )


def test_sse_and_handoff(client):
    c, h = conversation(client)
    response = client.post(
        f"/api/conversations/{c}/stream",
        headers=h,
        json={"message": "Giá bao nhiêu?", "selected_sku": "ASUS-V16-BLACK"},
    )
    assert response.status_code == 200
    assert (
        "event: start" in response.text
        and "event: delta" in response.text
        and "event: done" in response.text
    )
    result = send(client, c, h, "Muốn gặp nhân viên")
    assert result["signals"]["handoff_required"]
    # The assistant's handoff reaches the staff queue as a platform handoff.
    assert client.get(f"/api/conversations/{c}", headers=h).json()["status"] == "handed_off"
    with client.app.state.database.sessions() as db:
        assert db.scalar(select(Handoff).where(Handoff.conversation_id == c)).from_actor_id == "assistant"
    agent = {"Authorization": "Bearer local-agent-change-me"}
    assert (
        client.post(
            f"/api/staff/conversations/{c}/claim", headers=agent, json={}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/staff/conversations/{c}/messages",
            headers=agent,
            json={"message": "Xin chào, tôi là nhân viên."},
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/conversations/{c}", headers=h).json()["messages"][-1][
            "speaker"
        ]
        == "agent"
    )


def test_delete_revokes_access_and_memory(client):
    c, h = conversation(client)
    token = identify(client, c, h)
    send(client, c, h, "Ngân sách 18 triệu")
    headers = {"Authorization": "Bearer " + token}
    assert client.delete("/api/customer/data", headers=headers).status_code == 200
    assert client.get("/api/customer/profile", headers=headers).status_code == 401
    assert client.get(f"/api/conversations/{c}", headers=h).status_code == 404
    with client.app.state.database.sessions() as db:
        assert db.scalars(select(ProfileFact)).all() == []


def lines_body(client, lines, key="basket-0001", **extra):
    """A several-line order: lines as (sku, quantity)."""
    if "payment_method" not in extra:
        enable_bank(client)
        extra["payment_method"] = "bank_transfer"
    quotes = [client.get(f"/api/catalog/{sku}/quote?quantity={qty}").json() for sku, qty in lines]
    return {
        "items": [
            {"sku_code": q["sku_code"], "quantity": qty, "expected_unit_price": q["sale_price"]}
            for q, (_, qty) in zip(quotes, lines)
        ],
        "shipping_address": "123 Test Street",
        "expected_total": str(sum(Decimal(q["total"]) for q in quotes)),
        "confirmed": True,
        "idempotency_key": key,
        **extra,
    }


def test_basket_is_one_order_of_several_lines(client):
    c, h = conversation(client)
    identify(client, c, h)
    body = lines_body(client, [("ASUS-V16-BLACK", 1), ("LENOVO-S5-SILVER", 2)])
    first = client.post(f"/api/conversations/{c}/orders", headers=h, json=body)
    assert first.status_code == 201, first.text
    order = first.json()
    assert sorted((i["sku_code"], i["quantity"]) for i in order["items"]) == [
        ("ASUS-V16-BLACK", 1), ("LENOVO-S5-SILVER", 2)]
    assert Decimal(order["total"]) == Decimal(body["expected_total"])
    assert (order["payment_method"], order["payment_status"]) == ("bank_transfer", "awaiting_transfer")
    repeat = client.post(f"/api/conversations/{c}/orders", headers=h, json=body)
    assert repeat.json()["id"] == order["id"]
    assert client.get("/api/catalog/ASUS-V16-BLACK").json()["available"] == 11
    assert client.get("/api/catalog/LENOVO-S5-SILVER").json()["available"] == 6


def test_one_line_short_of_stock_reserves_nothing(client):
    c, h = conversation(client)
    identify(client, c, h)
    body = lines_body(client, [("ASUS-V16-BLACK", 1), ("LENOVO-S5-SILVER", 50)])
    assert client.post(f"/api/conversations/{c}/orders", headers=h, json=body).status_code == 409
    assert client.get("/api/catalog/ASUS-V16-BLACK").json()["available"] == 12
    assert client.get("/api/seller/orders", headers=SELLER).json() == []


def test_cod_limit_and_bank_transfer(client):
    from dataclasses import replace

    c, h = conversation(client)
    identify(client, c, h)
    cod = lines_body(client, [("ASUS-V16-BLACK", 1)], payment_method="cod")
    assert client.post(f"/api/conversations/{c}/orders", headers=h, json=cod).status_code == 422
    transfer = lines_body(client, [("ASUS-V16-BLACK", 1)], key="basket-0002", payment_method="bank_transfer")
    # No shop account configured: bank transfer is not offered.
    assert client.post(f"/api/conversations/{c}/orders", headers=h, json=transfer).status_code == 422
    security = client.app.state.security
    security.settings = replace(security.settings, bank_bin="970436", bank_name="Vietcombank",
                                bank_account_no="0123456789", bank_account_name="TIEP NOI")
    created = client.post(f"/api/conversations/{c}/orders", headers=h, json=transfer)
    assert created.status_code == 201, created.text
    order = created.json()
    assert (order["payment_method"], order["payment_status"]) == ("bank_transfer", "awaiting_transfer")
    assert order["transfer"]["account_no"] == "0123456789"
    assert order["transfer"]["qr_url"].startswith("https://img.vietqr.io/image/970436-0123456789")
    paid = client.post(f"/api/seller/orders/{order['id']}/paid", headers=SELLER, json={})
    assert paid.status_code == 200 and paid.json()["payment_status"] == "paid"
