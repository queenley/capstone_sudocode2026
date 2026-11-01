"""Shared fixtures: the platform routes in one app, with the AI service's turn routes.

The platform services (commerce, identity, sales) share backend-common, so one
FastAPI app with all of their routers exercises the same code the gateway
reaches. The AI service's ``/turns`` and ``/stream`` are mounted on top, with
the agent itself replaced by :class:`ScriptedAgent`: the real hot graph needs
PostgreSQL (checkpointer, agent schema) and a model provider, so the agent's own
logic is tested separately in ``tests/agent``. What these tests cover is the
contract around it: authorisation, the TurnResult shape, the SSE events, the
platform transcript and the assistant-initiated handoff.
"""

import os
import socket
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.api.routes import admin, auth, catalog, conversations, customer, seller, staff
from src.core.config import Settings
from src.core.service_runtime import database_ready
from src.db.session import Database
from src.memory.service import WorkingMemory
from src.security.service import Security
from scripts.seed.catalog import seed

from ai_agent_service.api.routes import agent_calls, conversations as agent_turns, developer
from ai_agent_service.runtime import calls, harness

ADMIN = {"Authorization": "Bearer local-admin-change-me"}
AGENT = {"Authorization": "Bearer local-agent-change-me"}


@pytest.fixture(autouse=True)
def private_improvement_store(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path / "improvement"))


@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    """Tests may use local dependencies; provider and other public network calls are forbidden."""
    connect = socket.socket.connect
    def local_only(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError("Offline tests forbid external network calls")
        return connect(sock, address)
    monkeypatch.setattr(socket.socket, "connect", local_only)
    from ai_agent_service.llm.factory import LLMFactory
    def no_provider(*args, **kwargs):
        raise AssertionError("Offline tests require an injected fake model")
    monkeypatch.setattr(LLMFactory, "create_llm", staticmethod(no_provider))


class ScriptedAgent:
    """Stands in for ``runtime.calls``: one call per conversation, canned turns.

    "nhân viên" asks for a person (lane HANDOFF, handoff pending) and turns the
    call to copilot, as the real graph does; in copilot mode a turn only drafts
    a suggestion (outcome "waiting"). Anything else is answered on lane NEW
    with one ``catalog.search`` result.
    """

    def __init__(self) -> None:
        self.calls: dict[str, dict[str, Any]] = {}
        self.replies: dict[tuple[int, str], str] = {}
        self.turns: list[dict[str, Any]] = []

    async def call_for_conversation(self, conversation_id, channel, *, actor):
        row = self.calls.setdefault(conversation_id, {
            "id": len(self.calls) + 1, "conversation_id": conversation_id, "channel": channel, "mode": "speak",
        })
        return row

    async def set_caller(self, call_id, number):
        """As ``calls.set_caller``: the call now knows the number (kept in clear here, for the tests)."""
        row = next(r for r in self.calls.values() if r["id"] == call_id)
        row.update(caller_token="<PHONE_1>", caller_phone=number, phone_last4=number[-4:])

    async def call_row(self, call_id):
        return next(r for r in self.calls.values() if r["id"] == call_id)

    async def stored_reply(self, call_id, turn_id):
        content = self.replies.get((call_id, turn_id))
        return {"content": content} if content is not None else None

    async def take_turn(self, row, *, content, turn_id, arrived, actor, memory, emit=None, account_id=None, account_name=None):
        self.turns.append({"call_id": row["id"], "content": content, "memory": memory, "account_id": account_id, "account_name": account_name})
        if row.get("mode") == "copilot":
            return harness.Outcome(kind="waiting", turn_id=turn_id, state={"lane": "HANDOFF", "mode": "copilot"})
        if "nhân viên" in content.lower():
            row["mode"] = "copilot"
            reply = "Dạ, em chuyển anh/chị sang nhân viên tư vấn ngay ạ."
            state = {"lane": "HANDOFF", "route_rule": 5, "tier": "UNKNOWN",
                     "handoff": {"status": "pending", "reason": "customer_asked", "brief": {"summary": "asks for staff"}},
                     "guard": {"passed": True}}
        else:
            reply = "Dạ, bên em có mẫu này ạ.\nAnh/chị muốn xem thêm không?"
            state = {"lane": "NEW", "route_rule": 7, "tier": "UNKNOWN", "guard": {"passed": True},
                     "tool_results": [{"name": "catalog.search", "result": {"ok": True, "data": {"items": [
                         {"sku": "SKU-1", "name": "Máy demo", "brand": "Demo", "category": "laptop",
                          "list_price_vnd": 18_000_000, "stock": 3}]}}}],
                     "quotes": {"SKU-1": 17_500_000}}
        self.replies[(row["id"], turn_id)] = reply
        return harness.Outcome(kind="message", turn_id=turn_id, content=reply,
                               latency={"total_ms": 5}, state=state)


def create_test_app(settings: Settings, database: Database) -> FastAPI:
    app = FastAPI(title="Platform test app")
    app.state.settings = settings
    app.state.database = database
    app.state.security = Security(settings)
    app.state.working = WorkingMemory(settings.redis_url)
    app.state.turn_tracker = None
    for module in (auth, admin, staff, seller, customer, catalog, conversations):
        app.include_router(module.router)
    app.include_router(agent_turns.router)
    app.include_router(agent_calls.router)
    app.include_router(developer.router)

    @app.exception_handler(IntegrityError)
    async def conflict(request, error):
        return JSONResponse(status_code=409, content={"detail": "Write conflicted with an existing record"})

    @app.get("/health/ready")
    def ready():
        return {"status": "ready" if database_ready(app) else "not ready"}

    return app


class StreamingAgent(ScriptedAgent):
    """As :class:`ScriptedAgent`, but the reply is said a checked sentence at a
    time through ``emit``, as the real graph does (``docs/design.md`` 4.8)."""

    SENTENCES = ("Dạ, bên em có mẫu này ạ.", "Anh/chị muốn xem thêm không?")

    async def take_turn(self, row, *, content, turn_id, arrived, actor, memory, emit=None, account_id=None, account_name=None):
        outcome = await super().take_turn(row, content=content, turn_id=turn_id, arrived=arrived, actor=actor,
                                          memory=memory, account_id=account_id, account_name=account_name)
        if emit is None or outcome.kind != "message":
            return outcome
        # The line said while tools run comes first; the chat shows typing instead of it.
        await emit("filler", "Dạ anh/chị chờ em một xíu ạ.")
        for sentence in self.SENTENCES:
            await emit("sentence", sentence)
        reply = " ".join(self.SENTENCES)
        self.replies[(row["id"], turn_id)] = reply
        return harness.Outcome(kind="message", turn_id=turn_id, content=reply, latency=outcome.latency,
                               state=outcome.state)


def _scripted(monkeypatch, scripted: ScriptedAgent) -> ScriptedAgent:
    for name in ("call_for_conversation", "stored_reply", "take_turn", "set_caller", "call_row"):
        monkeypatch.setattr(calls, name, getattr(scripted, name))
    return scripted


@pytest.fixture
def agent(monkeypatch) -> ScriptedAgent:
    return _scripted(monkeypatch, ScriptedAgent())


@pytest.fixture
def streaming_agent(monkeypatch) -> StreamingAgent:
    return _scripted(monkeypatch, StreamingAgent())


@pytest.fixture
def client(agent):
    url = os.getenv("TEST_DATABASE_URL", "sqlite://")
    database = Database(url)
    connection = transaction = None
    database.migrate()
    if not url.startswith("sqlite"):
        if not url.split("?")[0].endswith("/telesales_test"):
            raise ValueError("Integration tests only allow the dedicated telesales_test database")
        connection = database.engine.connect()
        transaction = connection.begin()
        database.sessions = sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
        )
    app = create_test_app(Settings(database_url="sqlite://"), database)
    with TestClient(app) as client:
        with database.sessions() as db:
            seed(db)
        yield client
    if transaction:
        transaction.rollback()
        connection.close()


def conversation(client, customer_token=""):
    response = client.post(
        "/api/conversations",
        json={},
        headers={"Authorization": "Bearer " + customer_token} if customer_token else {},
    )
    assert response.status_code == 201, response.text
    session = response.json()
    return session["conversation_id"], {"Authorization": "Bearer " + session["conversation_token"]}


def identify(client, conv_id, headers, phone="0901234567"):
    challenge = client.post(
        f"/api/conversations/{conv_id}/identity/challenge",
        headers=headers,
        json={"kind": "phone", "value": phone, "consent": True},
    ).json()
    result = client.post(
        f"/api/conversations/{conv_id}/identity/verify",
        headers=headers,
        json={"challenge_id": challenge["challenge_id"], "code": challenge["development_code"]},
    )
    assert result.status_code == 200, result.text
    return result.json()["customer_token"]
