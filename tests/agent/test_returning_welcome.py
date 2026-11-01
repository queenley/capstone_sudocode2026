"""Welcome uses verified account ownership and the agent ledger; entirely offline."""
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.api.routes import welcome
from ai_agent_service.components.clock import VIETNAM
from ai_agent_service.components.identity.resolver import digest
from conftest import conversation, identify


@pytest.fixture
def welcome_client(client, monkeypatch):
    client.app.include_router(welcome.router)
    today = datetime.now(VIETNAM).date()
    fact = {"slot": "blocker", "value": "cần hỏi người nhà", "status": "active", "confidence": 1,
            "valid_from": today.isoformat(), "valid_to": (today + timedelta(days=30)).isoformat(),
            "source": {"call_id": 7, "turn": 1, "said_by": "customer"}}
    profile = {"facts": [fact], "deleted_at": None, "deletion_pending": False}
    reads = []

    async def get_profile(customer_id, on=None):
        reads.append(customer_id)
        return deepcopy(profile)

    monkeypatch.setattr(welcome.memory, "memory_get_profile", AsyncMock(side_effect=get_profile))
    monkeypatch.setattr(welcome.memory, "memory_get_episodes", AsyncMock(return_value={"episodes": []}))
    monkeypatch.setattr(welcome.memory, "identity_find", AsyncMock(return_value={"matches": []}))
    monkeypatch.setattr(welcome, "identity_secret", lambda: "offline-secret")
    conv, headers = conversation(client)
    token = identify(client, conv, headers, phone="0900000001")
    auth = {"Authorization": "Bearer " + token}
    client.patch("/api/customer/me", headers=auth, json={"full_name": "Khách An"}).raise_for_status()
    return client, auth, profile, reads


def test_bearer_is_required_and_conversation_or_staff_token_cannot_read_memory(welcome_client):
    client, _, _, reads = welcome_client
    for headers in ({}, {"Authorization": "Bearer local-admin-change-me"}, {"Authorization": "Bearer fabricated"}):
        assert client.get("/api/agent/welcome", headers=headers).status_code == 401
    assert reads == []


def test_own_profile_only_no_call_or_message_is_created(welcome_client, agent):
    client, auth, _, reads = welcome_client
    me = client.get("/api/customer/me", headers=auth).json()
    response = client.get("/api/agent/welcome?customer_id=someone-else", headers=auth)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["vary"] == "Authorization"
    assert set(reads) == {"web:" + me["customer_id"]}
    body = response.json()
    assert body["returning"] and body["name"] == "Khách An"
    assert body["blocker"]["text"] == "cần hỏi người nhà"
    assert "customer_id" not in body and "source" not in body["blocker"]
    assert agent.calls == {} and agent.turns == []
    assert welcome.memory.identity_find.await_count == 2
    welcome.memory.identity_find.assert_awaited_with("phone", digest("phone", "0900000001", "offline-secret"))


def test_confirmed_unique_legacy_identity_uses_agent_memory(welcome_client):
    client, auth, _, reads = welcome_client
    welcome.memory.identity_find.return_value = {"matches": [{"customer_id": "LEGACY-A", "status": "confirmed"}]}
    assert client.get("/api/agent/welcome", headers=auth).json()["blocker"]
    assert "LEGACY-A" in reads


@pytest.mark.parametrize("matches", [
    [{"customer_id": "A", "status": "provisional"}],
    [{"customer_id": "A", "status": "confirmed"}, {"customer_id": "B", "status": "confirmed"}],
    [{"customer_id": "web:another-account", "status": "confirmed"}],
])
def test_shared_unconfirmed_or_other_web_account_is_not_exposed(welcome_client, matches):
    client, auth, _, reads = welcome_client
    welcome.memory.identity_find.return_value = {"matches": matches}
    result = client.get("/api/agent/welcome", headers=auth).json()
    assert result["returning"] is False and result["name"] is None and result["blocker"] is None
    assert not any(owner in {row["customer_id"] for row in matches} for owner in reads)


@pytest.mark.parametrize("changes", [
    {"status": "unconfirmed"}, {"status": "disputed"}, {"status": "invalidated"},
    {"valid_to": "2000-01-01"}, {"valid_from": "2000-01-01", "valid_to": None},
    {"source": {}}, {"source": {"call_id": 7, "turn": 1, "said_by": "agent"}}, {"confidence": 0.2},
])
def test_expired_unconfirmed_or_unproven_blocker_is_never_repeated(welcome_client, changes):
    client, auth, profile, _ = welcome_client
    profile["facts"][0].update(changes)
    assert client.get("/api/agent/welcome", headers=auth).json()["blocker"] is None


def test_a_newer_order_resolves_a_blocker(welcome_client):
    client, auth, profile, _ = welcome_client
    profile["facts"].append({**profile["facts"][0], "slot": "outcome", "value": "chot_don"})
    assert client.get("/api/agent/welcome", headers=auth).json()["blocker"] is None


@pytest.mark.parametrize("marker", ["deleted_at", "deletion_pending"])
def test_recorded_pending_and_completed_erasure_hide_even_name(welcome_client, marker):
    client, auth, profile, _ = welcome_client
    profile[marker] = "2026-11-01" if marker == "deleted_at" else True
    result = client.get("/api/agent/welcome", headers=auth).json()
    assert not result["returning"] and result["name"] is None and result["blocker"] is None


def test_revocation_during_memory_read_discards_the_response(welcome_client):
    client, auth, _, _ = welcome_client
    async def revoke(*args, **kwargs):
        from sqlalchemy import update
        from src.db.models import CustomerAccess, now
        with client.app.state.database.sessions() as db:
            db.execute(update(CustomerAccess).values(revoked_at=now()))
            db.commit()
        return {"episodes": []}
    welcome.memory.memory_get_episodes.side_effect = revoke
    response = client.get("/api/agent/welcome", headers=auth)
    assert response.status_code == 401 and "Khách An" not in response.text


def test_erasure_recorded_during_read_discards_the_response(welcome_client):
    client, auth, profile, _ = welcome_client
    async def erase(*args, **kwargs):
        profile["deletion_pending"] = True
        return {"episodes": []}
    welcome.memory.memory_get_episodes.side_effect = erase
    result = client.get("/api/agent/welcome", headers=auth).json()
    assert not result["returning"] and result["name"] is None


def test_unavailable_memory_is_a_safe_retryable_error(welcome_client):
    client, auth, _, _ = welcome_client
    welcome.memory.memory_get_profile.side_effect = RuntimeError("private details")
    response = client.get("/api/agent/welcome", headers=auth)
    assert response.status_code == 503 and "private details" not in response.text


def test_deleted_account_access_is_revoked_before_agent_memory_is_read(welcome_client):
    client, auth, _, reads = welcome_client
    client.delete("/api/customer/data", headers=auth).raise_for_status()
    assert client.get("/api/agent/welcome", headers=auth).status_code == 401
    assert reads == []


def test_new_account_without_agent_memory_has_no_personalized_popup(welcome_client):
    client, auth, profile, _ = welcome_client
    profile["facts"] = []
    result = client.get("/api/agent/welcome", headers=auth).json()
    assert not result["returning"] and result["name"] is None


def test_no_verified_phone_cannot_read_even_own_memory(welcome_client):
    from sqlalchemy import update
    from src.db.models import CustomerIdentity, now
    client, auth, _, reads = welcome_client
    with client.app.state.database.sessions() as db:
        db.execute(update(CustomerIdentity).values(revoked_at=now()))
        db.commit()
    assert not client.get("/api/agent/welcome", headers=auth).json()["returning"]
    assert reads == []


def test_fact_resolved_while_reading_is_not_restored_by_older_snapshot(welcome_client):
    client, auth, profile, _ = welcome_client
    async def resolve(*args, **kwargs):
        profile["facts"][0]["status"] = "invalidated"
        return {"episodes": [{"call_id": 7}]}
    welcome.memory.memory_get_episodes.side_effect = resolve
    result = client.get("/api/agent/welcome", headers=auth).json()
    assert result["returning"] and result["blocker"] is None


@pytest.mark.parametrize("confidence", [None, True, [], {}, "invalid", "NaN", float("nan"), float("inf"), -float("inf"), 1.1])
def test_malformed_confidence_fails_closed_without_breaking_greeting(welcome_client, confidence):
    client, auth, profile, _ = welcome_client
    profile["facts"][0]["confidence"] = confidence
    response = client.get("/api/agent/welcome", headers=auth)
    assert response.status_code == 200
    assert response.json()["blocker"] is None


@pytest.mark.parametrize("blocker_at,outcome_at,hidden", [
    ("2026-11-01T07:00:00+07:00", "2026-11-01T01:00:00+00:00", True),
    ("2026-11-01T01:00:00+00:00", "2026-11-01T07:00:00+07:00", False),
    ("2026-11-01", "2026-11-01", True),
    ("2026-11-01T00:00:00", "2026-11-01T01:00:00+00:00", True),
    ("malformed", "2026-11-01T01:00:00+00:00", True),
    ("2026-11-01T07:00:00+07:00", "malformed", True),
])
def test_resolution_compares_instants_and_hides_uncertain_ordering(welcome_client, blocker_at, outcome_at, hidden):
    _, _, profile, _ = welcome_client
    blocker = profile["facts"][0]
    blocker["valid_from"] = "2026-11-01"
    blocker["valid_to"] = "2026-12-01"
    blocker["source"]["observed_at"] = blocker_at
    outcome = {**blocker, "slot": "outcome", "value": "chot_don", "source": {"observed_at": outcome_at}}
    result = welcome._blocker([blocker, outcome], datetime(2026, 11, 1, 10, tzinfo=VIETNAM))
    assert (result is None) is hidden


def test_identity_that_becomes_shared_during_read_is_hidden(welcome_client):
    client, auth, _, _ = welcome_client
    welcome.memory.identity_find.side_effect = [
        {"matches": []}, {"matches": [{"customer_id": "OTHER", "status": "confirmed"}]},
    ]
    result = client.get("/api/agent/welcome", headers=auth).json()
    assert not result["returning"] and result["name"] is None
