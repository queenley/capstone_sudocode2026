"""EC03 regression: purchase confirmation is bound to one session and exact order.

No provider calls. The fake model deliberately chooses both a safe and an unsafe
tool plan; both must respect the same purchase confirmation boundary.
The optional PostgreSQL test accepts only a dedicated local ec03_test database.
"""

import asyncio
import importlib.util
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from ai_agent_service.agents.advisor import ActionGuardMiddleware, AdvisorAgent, AgentContext
from ai_agent_service.components.guardrails import purchase
from ai_agent_service.components.intake.pii import Vault
from ai_agent_service.mcp.servers import btc, crm
from ai_agent_service.mcp.server_base import ToolFailure
from ai_agent_service.mcp.tools import idempotency_key, order_arguments, ToolGuardMiddleware
from ai_agent_service.pipeline.hot.graph import build_graph
from ai_agent_service.pipeline.hot.state import HotContext
from ai_agent_service.runtime import calls, db as agent_db, harness

NOW = datetime(2026, 11, 1, 10, tzinfo=timezone(timedelta(hours=7)))
PHONE = "0900000000"  # Synthetic identity, unrelated to any CRM customer.
SKU = "EC03-WHITE"
PRICE = 1_000_000
BUY_QUESTION = "Dạ anh đồng ý đặt 1 máy EC03-WHITE màu trắng giá 1.000.000đ không ạ?"
PHOTO_QUESTION = "Dạ anh muốn xem ảnh màu trắng không ạ?"


class SharedFacts:
    """One customer profile for both channels; no pending action is fabricated."""

    def __init__(self):
        self.reads = []

    async def data(self, name, **args):
        self.reads.append((name, args))
        if name == "crm_get_customer":
            return {"found": True, "customer_id": "EC03-CUSTOMER", "name": "Demo", "honorific": "anh",
                    "phone": PHONE, "orders": [], "sessions": []}
        if name == "identity_find":
            return {"matches": []}
        if name == "memory_get_profile":
            return {"facts": [{"slot": "color", "value": "trang", "kind": "preference", "status": "active",
                               "fact_id": "EC03-color", "source": {"call_id": "earlier", "channel": "web"}}]}
        if name == "memory_get_episodes":
            return {"episodes": []}
        if name == "kb_search":
            return {"hits": [], "abstain": True}
        raise AssertionError((name, args))


class ChannelModel(FakeMessagesListChatModel):
    """A shared, stateless plan generator; unsafe=True models a wrong purchase interpretation."""

    unsafe: bool = False
    views: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        channel = "hotline" if "Kênh: hotline" in str(messages[0].content) else "zalo"
        last = max(i for i, message in enumerate(messages) if isinstance(message, HumanMessage))
        text = str(messages[last].content)
        tools = {m.name for m in messages[last + 1:] if isinstance(m, ToolMessage)}
        self.views.append((channel, text, tuple(str(m.content) for m in messages)))
        if text.casefold() == "vâng":
            name = "order_create" if (self.unsafe or channel == "hotline") and "order_create" not in tools else None
            args = {"sku": SKU, "price_vnd": PRICE, "qty": 1} if name else {}
            reply = "Dạ em tiếp tục phần xem ảnh màu trắng ạ."
        else:
            name = "catalog_search" if "catalog_search" not in tools else (
                "pricing_get_quote" if "pricing_get_quote" not in tools else (
                    "order_create" if channel == "hotline" and "order_create" not in tools else None))
            args = {"query": "máy màu trắng"} if name == "catalog_search" else {"sku": SKU}
            if name == "order_create":
                args = {"sku": SKU, "price_vnd": PRICE, "qty": 1}
            reply = BUY_QUESTION if channel == "hotline" else PHOTO_QUESTION
        message = AIMessage(content="", tool_calls=[{"id": f"{channel}-{name}", "name": name, "args": args}]) if name else AIMessage(content=reply)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(0)  # Let both channels overlap without sharing a response cursor.
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def advisor_with_spy(*, unsafe=False):
    writes = []

    async def catalog_search(query: str):
        return json.dumps({"ok": True, "data": {"items": [{"sku": SKU, "name": "Máy kiểm thử màu trắng"}]}})

    async def pricing_get_quote(sku: str):
        return json.dumps({"ok": True, "data": {"sku": sku, "final_price_vnd": PRICE}})

    async def order_create(sku: str, price_vnd: int, qty: int = 1, payment: str = "COD",
                           customer_phone: str | None = None, on: str | None = None,
                           idempotency_key: str | None = None, promo_code: str | None = None,
                           address: str | None = None, call_id: str | None = None, turn_id: str | None = None,
                           purchase_authorization: str | None = None):
        purchase.verify(purchase_authorization, dict(sku=sku, price_vnd=price_vnd, qty=qty, payment=payment,
                        promo_code=promo_code, address=address, customer_phone=customer_phone, on=on), call_id, turn_id)
        writes.append(dict(sku=sku, price_vnd=price_vnd, qty=qty, payment=payment,
                           customer_phone=customer_phone, on=on, idempotency_key=idempotency_key))
        return json.dumps({"ok": True, "data": {"order_id": "EC03-ORDER", "status": "created"}})

    tools = [StructuredTool.from_function(coroutine=fn, name=fn.__name__, description="Offline EC03 fixture")
             for fn in (catalog_search, pricing_get_quote, order_create)]
    model = ChannelModel(responses=[AIMessage(content="unused")], unsafe=unsafe)
    return AdvisorAgent(llm=model, tools=tools, retries=0), model, writes


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent", [False, True], ids=["interleaved", "concurrent"])
@pytest.mark.parametrize("unsafe", [False, True], ids=["safe-plan", "wrong-purchase-plan"])
async def test_same_customer_channels_isolate_pending_purchase_and_block_wrong_plan(concurrent, unsafe):
    advisor, model, writes = advisor_with_spy(unsafe=unsafe)
    graph = build_graph(checkpointer=InMemorySaver())
    shared = SharedFacts()
    contexts = {channel: HotContext(caller_phone=PHONE if channel == "hotline" else None,
                                    zalo_id="EC03-ZALO" if channel == "zalo" else None,
                                    identity_secret="offline-ec03", harness=shared, advisor=advisor)
                for channel in ("hotline", "zalo")}

    async def turn(call_id, channel, text, turn_id):
        contexts[channel].text = text
        return await graph.ainvoke({"call_id": str(call_id), "channel": channel, "turn_id": turn_id,
                                   "turn_no": 2 if text == "vâng" else 1, "mode": "speak", "phase": "turn",
                                   "now": NOW, "on": "2026-11-01", "switches": {"memory": True}},
                                  context=contexts[channel], config=harness.thread(call_id))

    if concurrent:
        a, b = await asyncio.gather(turn(101, "hotline", "Tư vấn máy màu trắng", "same-turn-id"),
                                    turn(202, "zalo", "Cho tôi xem ảnh màu trắng", "same-turn-id"))
    else:
        a = await turn(101, "hotline", "Tư vấn máy màu trắng", "same-turn-id")
        b = await turn(202, "zalo", "Cho tôi xem ảnh màu trắng", "same-turn-id")
    assert a["customer_id"] == b["customer_id"] == "EC03-CUSTOMER"
    assert a["tier"] == b["tier"] == "VERIFIED"
    question_a = a["pending_purchase"]["question"]
    assert a["reply"]["text"] == question_a and b["reply"]["text"] == PHOTO_QUESTION
    assert a["draft"]["model_calls"] >= 1
    assert a["quotes"] == b["quotes"] == {SKU: PRICE}
    assert not writes
    a_before = (await graph.aget_state(harness.thread(101))).values
    b = await turn(202, "zalo", "vâng", "B-yes")
    a_after = (await graph.aget_state(harness.thread(101))).values
    assert a_after == a_before  # B cannot advance A, including A's pending conversational question.
    assert a_after.get("created_orders", []) == []
    assert question_a not in [str(m.content) for m in b["messages"][:-1]]
    assert all(question_a not in messages for channel, _, messages in model.views if channel == "zalo")
    assert PHOTO_QUESTION not in [str(m.content) for m in a_after["messages"]]
    assert [args["customer_id"] for name, args in shared.reads if name == "memory_get_profile"] == [
        "EC03-CUSTOMER", "EC03-CUSTOMER"]
    assert writes == [] and b.get("created_orders", []) == []
    if unsafe:
        assert b["pending_purchase"]["call_id"] == "202"
        assert b["pending_purchase"]["draft_id"] != a_before["pending_purchase"]["draft_id"]
        assert b["reply"]["text"] == b["pending_purchase"]["question"]
        b = await turn(202, "zalo", "vâng", "B-confirm-order")
        assert len(writes) == 1 and writes[0]["idempotency_key"].startswith("202:order_create:")
        assert b["pending_purchase"] is None
    a = await turn(101, "hotline", "vâng", "A-confirm-order")
    assert len(writes) == (2 if unsafe else 1)
    assert a["created_orders"] == [{"order_id": "EC03-ORDER", "sku": SKU}]
    assert a["pending_purchase"] is None


def guarded_context(**changes):
    return replace(AgentContext(call_id="202", turn_id="B-yes", customer_id="EC03-CUSTOMER", channel="zalo",
                                tier="VERIFIED", customer_phone=PHONE, now=NOW, on="2026-11-01",
                                quotes={SKU: PRICE, "EC03-OTHER": 1_100_000},
                                trusted_skus=frozenset({SKU, "EC03-OTHER"}), customer_said="vâng",
                                last_agent_said=PHOTO_QUESTION), **changes)


def authorized(context, args=None):
    args = args or {"sku": SKU, "price_vnd": PRICE, "qty": 1, "payment": "COD"}
    previous = replace(context, turn_id="prepare-order")
    pending = purchase.draft(order_arguments(args, previous), previous)
    pending = purchase.answer(pending, call_id=context.call_id, channel=context.channel, turn_id=context.turn_id,
                              said="vâng", last_reply=pending["question"])
    return replace(context, pending_purchase=pending, last_agent_said=pending["question"], customer_said="vâng")


async def attempt_order(context, args=None, handler=None):
    request = SimpleNamespace(tool_call={"id": "order", "name": "order_create", "args": args or {
        "sku": SKU, "price_vnd": PRICE, "qty": 1, "payment": "COD"}},
        runtime=SimpleNamespace(context=context), state={"messages": []})
    request.override = lambda **changes: SimpleNamespace(**{**vars(request), **changes})
    handler = handler or AsyncMock(return_value="executed")
    return await ActionGuardMiddleware().awrap_tool_call(request, handler), handler


@pytest.mark.asyncio
@pytest.mark.parametrize("said", ["vâng", "không mua đâu", "cho tôi xem ảnh"])
async def test_order_guard_requires_purchase_confirmation_after_any_unbound_words(said):
    result, handler = await attempt_order(guarded_context(customer_said=said))
    assert json.loads(result.content)["error"]["code"] == "CONFIRMATION_REQUIRED"
    handler.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["sku", "price", "qty", "old-question", "cross-channel-handoff"])
async def test_order_guard_binds_yes_to_the_original_draft(change):
    context = authorized(guarded_context(last_agent_said=BUY_QUESTION))
    args = {"sku": SKU, "price_vnd": PRICE, "qty": 1, "payment": "COD"}
    if change == "sku":
        args.update(sku="EC03-OTHER", price_vnd=1_100_000)
    elif change == "price":
        context = replace(context, quotes={SKU: 1_100_000})
        args["price_vnd"] = 1_100_000  # A current quote passes despite an older purchase question.
    elif change == "qty":
        args["qty"] = 2
    elif change == "old-question":
        context = replace(context, pending_purchase={**context.pending_purchase, "expires_at": 0})
    elif change == "cross-channel-handoff":
        context = replace(context, call_id="other-session", channel="hotline")
    result, handler = await attempt_order(context, args)
    assert json.loads(result.content)["error"]["code"] == "CONFIRMATION_REQUIRED"
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_guard_blocks_stale_price_untrusted_sku_and_same_call_duplicate():
    for context, args in [
        (guarded_context(), {"sku": SKU, "price_vnd": PRICE - 1}),
        (guarded_context(), {"sku": "UNSEEN", "price_vnd": PRICE}),
        (guarded_context(created_orders=({"order_id": "EC03-ORDER", "sku": SKU},)),
         {"sku": SKU, "price_vnd": PRICE}),
    ]:
        result, handler = await attempt_order(context, args)
        assert json.loads(result.content)["error"]["code"] == "PRECONDITION"
        handler.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("qty", [0, -1, True, 1.5])
async def test_invalid_quantity_cannot_be_read_back_as_a_different_order(qty):
    result, handler = await attempt_order(guarded_context(), {"sku": SKU, "price_vnd": PRICE, "qty": qty})
    assert json.loads(result.content)["error"]["code"] == "PRECONDITION"
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_another_sessions_order_history_does_not_authorize_a_new_purchase():
    context = guarded_context(known_orders=frozenset({"EC03-ORDER-FROM-A"}))
    result, handler = await attempt_order(context)
    assert json.loads(result.content)["error"]["code"] == "CONFIRMATION_REQUIRED"
    handler.assert_not_awaited()


@pytest.mark.parametrize("said", ["không mua đâu", "vâng nhưng đổi thành 2 cái", "cho xem ảnh", "đồng ý xem ảnh", ""])
def test_cancellation_correction_and_unrelated_turn_invalidate_pending_consent(said):
    context = guarded_context(turn_id="prepare")
    pending = purchase.draft(order_arguments({"sku": SKU, "price_vnd": PRICE}, context), context)
    assert purchase.answer(pending, call_id=context.call_id, channel=context.channel, turn_id="next",
                           said=said, last_reply=pending["question"]) is None


@pytest.mark.parametrize("said", ["vâng", "dạ vâng ạ", "có", "ừ", "đồng ý", "xác nhận mua", "đặt cho chị đi", "chốt đơn"])
def test_clear_affirmations_authorize_only_after_the_bound_order_question(said):
    context = guarded_context(turn_id="prepare")
    pending = purchase.draft(order_arguments({"sku": SKU, "price_vnd": PRICE}, context), context)
    result = purchase.answer(pending, call_id=context.call_id, channel=context.channel, turn_id="next",
                             said=said, last_reply=pending["question"])
    assert result["status"] == "authorized" and result["confirmed_turn_id"] == "next"
    assert purchase.answer(pending, call_id=context.call_id, channel=context.channel, turn_id="next",
                           said=said, last_reply=PHOTO_QUESTION) is None


@pytest.mark.parametrize("change", ["call", "channel", "same-turn", "intervening-question", "interrupted", "expired", "consumed"])
def test_yes_cannot_authorize_another_question_or_inactive_draft(change, monkeypatch):
    context = guarded_context(turn_id="prepare")
    pending = purchase.draft(order_arguments({"sku": SKU, "price_vnd": PRICE}, context), context)
    args = dict(call_id=context.call_id, channel=context.channel, turn_id="next", said="vâng", last_reply=pending["question"])
    if change == "call": args["call_id"] = "another-call"
    elif change == "channel": args["channel"] = "hotline"
    elif change == "same-turn": args["turn_id"] = "prepare"
    elif change == "intervening-question": args["last_reply"] += " Muốn xem ảnh không?"
    elif change == "interrupted": args["last_reply"] = pending["question"][:30]
    elif change == "expired": monkeypatch.setattr(purchase, "now", lambda: pending["expires_at"])
    elif change == "consumed": pending["status"] = "consumed"
    assert purchase.answer(pending, **args) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("qty", 2), ("payment", "bank"), ("address", "123 Synthetic Street"),
                                        ("promo_code", "NEW-PROMO"), ("sku", "EC03-OTHER"), ("price_vnd", PRICE + 1)])
async def test_every_order_field_requires_new_confirmation(field, value):
    context = authorized(guarded_context())
    args = {"sku": SKU, "price_vnd": PRICE, "qty": 1, "payment": "COD", field: value}
    if field == "sku": args["price_vnd"] = 1_100_000
    if field == "price_vnd": context = replace(context, quotes={SKU: value})
    result, handler = await attempt_order(context, args)
    handler.assert_not_awaited()
    pending = json.loads(result.content)["error"]["details"]["purchase_draft"]
    assert pending["draft_id"] != context.pending_purchase["draft_id"]
    assert pending["payload_hash"] != context.pending_purchase["payload_hash"]
    assert pending["status"] == "pending"


@pytest.mark.asyncio
async def test_exact_payload_and_question_authorize_only_this_customer_and_turn():
    context = authorized(guarded_context())
    result, handler = await attempt_order(context)
    assert result == "executed"
    handler.assert_awaited_once()
    for changes in ({"customer_id": "OTHER"}, {"customer_phone": "0900000001"}, {"turn_id": "later"},
                    {"last_agent_said": PHOTO_QUESTION}, {"customer_said": "không mua"}):
        result, handler = await attempt_order(replace(context, **changes))
        assert json.loads(result.content)["error"]["code"] == "CONFIRMATION_REQUIRED"
        handler.assert_not_awaited()


def test_mcp_receipt_cannot_be_forged_rebound_or_reused_for_a_changed_payload():
    context = authorized(guarded_context())
    args = order_arguments({"sku": SKU, "price_vnd": PRICE}, context)
    token = purchase.receipt(context.pending_purchase, args, context)
    assert purchase.verify(token, args, context.call_id, context.turn_id)["draft_id"] == context.pending_purchase["draft_id"]
    for receipt, payload, call, turn in [(None, args, context.call_id, context.turn_id),
        (token + "x", args, context.call_id, context.turn_id),
        (token, {**args, "qty": 2}, context.call_id, context.turn_id),
        (token, args, "another-call", context.turn_id), (token, args, context.call_id, "another-turn")]:
        with pytest.raises(ValueError, match="Purchase confirmation"):
            purchase.verify(receipt, payload, call, turn)


def test_tool_middleware_overwrites_model_consent_and_scope_and_hides_receipt_from_trace():
    from ai_agent_service.mcp.tools import with_args
    context = authorized(guarded_context())
    request = SimpleNamespace(tool_call={"id": "tool", "name": "order_create", "args": {
        "sku": SKU, "price_vnd": PRICE, "call_id": "stolen-call", "turn_id": "stolen-turn",
        "purchase_authorization": "forged", "idempotency_key": "forged-key", "customer_phone": "0900000001"}},
        tool=SimpleNamespace(args=StructuredTool.from_function(coroutine=crm.order_create, name="order_create",
                                                              description="Place an order").args),
        runtime=SimpleNamespace(context=context))
    request.override = lambda **changes: SimpleNamespace(**{**vars(request), **changes})
    guarded = ToolGuardMiddleware(["order_create"])._with_context(request)
    args = guarded.tool_call["args"]
    assert args["customer_phone"] == PHONE and args["call_id"] == context.call_id and args["turn_id"] == context.turn_id
    claims = purchase.verify(args["purchase_authorization"], args, context.call_id, context.turn_id)
    assert claims["draft_id"] == context.pending_purchase["draft_id"]
    assert args["idempotency_key"] == purchase.order_key(context.call_id, args)
    shown = with_args(ToolMessage(content='{"ok":true}', tool_call_id="tool"), args)
    assert "purchase_authorization" not in shown.additional_kwargs["args"]


def test_backend_consumes_consent_and_replays_success_even_after_expiry(monkeypatch):
    context = authorized(guarded_context())
    args = order_arguments({"sku": SKU, "price_vnd": PRICE}, context)
    token = purchase.receipt(context.pending_purchase, args, context)
    claims = purchase.verify(token, args, context.call_id, context.turn_id)
    key = idempotency_key(context, "order_create", args)
    module = SimpleNamespace(_ORDERS={}, _CALLBACKS=[], _TICKETS=[], _ONCE_USED=set())
    executions = []

    def create(**kwargs):
        executions.append(kwargs)
        module._ORDERS["EC03-ORDER"] = {"order_id": "EC03-ORDER"}
        return {"order_id": "EC03-ORDER"}

    result, state = btc.run_write(module, {}, create, args, key, claims)
    assert state["purchase_consumed"] == {claims["draft_id"]: key}
    monkeypatch.setattr(purchase, "now", lambda: claims["expires_at"] + 1)
    replay, mutation = btc.run_write(module, state, create, args, key, claims)
    assert replay == result and mutation is None and len(executions) == 1
    with pytest.raises(ToolFailure, match="already used"):
        btc.run_write(module, state, create, args, key + "-other", claims)
    with pytest.raises(ToolFailure, match="expired"):
        btc.run_write(module, {}, create, args, key, claims)
    assert len(executions) == 1


@pytest.mark.asyncio
async def test_transport_replay_uses_call_and_turn_without_running_advisor(monkeypatch):
    monkeypatch.setattr(calls, "claim_lease", AsyncMock(return_value=True))
    release = AsyncMock()
    monkeypatch.setattr(calls, "release_lease", release)
    replay = AsyncMock(return_value={"content": "stored B reply", "meta": {}})
    monkeypatch.setattr(calls, "stored_reply", replay)
    run = AsyncMock()
    monkeypatch.setattr(harness, "run_turn", run)
    result = await calls.take_turn({"id": 202, "ended_at": None}, content="vâng", turn_id="B-yes", arrived=0,
                                   actor=calls.Actor("EC03", False))
    assert result.meta["replayed"] and result.content == "stored B reply"
    replay.assert_awaited_once_with(202, "B-yes")
    release.assert_awaited_once_with(202)
    run.assert_not_awaited()


def test_idempotency_is_payload_deduplication_and_does_not_transfer_consent():
    import hashlib
    args = {"sku": SKU, "price_vnd": PRICE, "qty": 1}
    a, b = guarded_context(call_id="101", turn_id="A-yes"), guarded_context()
    key = idempotency_key(a, "order_create", args)
    previous_digest = hashlib.sha256(json.dumps(args, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert key == f"101:order_create:{previous_digest}"
    assert key == idempotency_key(replace(a, turn_id="A-retry"), "order_create", args)
    assert key != idempotency_key(b, "order_create", args)
    for changed in ({**args, "qty": 2}, {**args, "sku": "EC03-OTHER"}, {**args, "price_vnd": PRICE + 1}):
        assert key != idempotency_key(a, "order_create", changed)
    original = {"order_id": "EC03-ORDER"}
    result, mutation = btc.run_write(None, {"idempotent": {key: original}}, None, args, key)
    assert result == original and mutation is None


@pytest_asyncio.fixture
async def ec03_postgres(monkeypatch):
    url = os.getenv("EC03_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set EC03_TEST_DATABASE_URL to a private local ec03_test database")
    parsed = urlsplit(url)
    assert parsed.scheme == "postgresql" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path == "/ec03_test" and not parsed.query
    from psycopg import AsyncConnection, sql
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    schema = "ec03_" + uuid4().hex
    async with await AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    pool = AsyncConnectionPool(url, open=False, kwargs={"autocommit": True, "row_factory": dict_row,
                                                       "options": f"-c search_path={schema}"})
    await pool.open()
    await pool.wait()

    async def private_pool():
        return pool

    monkeypatch.setattr(agent_db, "pool", private_pool)
    monkeypatch.setattr(btc, "database", private_pool)
    path = btc.btc_data_dir() / "eval" / "mock_tools.py"
    spec = importlib.util.spec_from_file_location("ec03_private_mock", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(btc, "_mock", module)
    try:
        async with pool.connection() as conn:
            await conn.execute(agent_db.SCHEMA + btc.STATE_SCHEMA, prepare=False)
        saver = agent_db.ErasureSafeSaver(pool)
        await saver.setup()
        yield pool, saver, module
    finally:
        await pool.close()
        async with await AsyncConnection.connect(url, autocommit=True) as conn:
            await conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.asyncio
async def test_postgres_calls_checkpoints_replay_and_real_order_write(ec03_postgres, monkeypatch):
    pool, saver, module = ec03_postgres
    actor = calls.Actor("EC03-local", False)
    conv_a, conv_b = str(uuid4()), str(uuid4())
    a, b = await asyncio.gather(calls.call_for_conversation(conv_a, "hotline", actor=actor),
                                calls.call_for_conversation(conv_b, "zalo", actor=actor, channel_ref="EC03-ZALO"))
    assert a["id"] != b["id"] and a["conversation_id"] != b["conversation_id"]
    again = await calls.call_for_conversation(conv_b, "zalo", actor=actor)
    assert again["id"] == b["id"]
    assert await calls.claim_lease(a["id"]) and await calls.claim_lease(b["id"])
    assert not await calls.claim_lease(b["id"])
    await calls.release_lease(a["id"])
    await calls.release_lease(b["id"])

    advisor, _, writes = advisor_with_spy()
    graph = build_graph(checkpointer=saver)
    shared = SharedFacts()
    vaults = {row["id"]: Vault() for row in (a, b)}

    async def run(row, text, turn_id):
        context = HotContext(text=text, caller_phone=PHONE, identity_secret="offline-ec03", harness=shared,
                             advisor=advisor, vault=vaults[row["id"]], store=harness.CallStore(row["id"], vaults[row["id"]]))
        return await graph.ainvoke({"call_id": str(row["id"]), "channel": row["channel"], "turn_id": turn_id,
                                   "turn_no": 2 if text == "vâng" else 1, "mode": "speak", "phase": "turn",
                                   "now": NOW, "on": "2026-11-01", "switches": {"memory": True}},
                                  context=context, config=harness.thread(row["id"]))

    await asyncio.gather(run(a, "Tư vấn máy", "same-turn"), run(b, "Cho xem ảnh", "same-turn"))
    before = (await graph.aget_state(harness.thread(a["id"]))).values
    await run(b, "vâng", "B-yes")
    assert (await graph.aget_state(harness.thread(a["id"]))).values == before
    assert not writes
    async with pool.connection() as conn:
        assert (await (await conn.execute("SELECT count(*) AS n FROM mock_state")).fetchone())["n"] == 0
        assert await calls.stored_reply(a["id"], "B-yes") is None
        assert await calls.stored_reply(b["id"], "B-yes") is not None
        ids = await (await conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id")).fetchall()
        assert {r["thread_id"] for r in ids} == {f"call-{a['id']}", f"call-{b['id']}"}

    # An unbound B call is refused at MCP too; only a fresh exact-order consent can write.
    sku = "SKU-AP-X"
    quote = module.pricing_get_quote(sku, on="2026-11-01", customer_phone=PHONE)
    price = quote["final_price_vnd"]
    context = guarded_context(call_id=str(b["id"]), quotes={sku: price}, trusted_skus=frozenset({sku}))
    args = {"sku": sku, "price_vnd": price, "qty": 1, "payment": "COD"}
    with pytest.raises(ToolFailure, match="Purchase confirmation"):
        await crm.order_create(**args, customer_phone=PHONE, on="2026-11-01")
    context = authorized(context, args)

    async def execute(request):
        return await crm.order_create(**request.tool_call["args"], customer_phone=PHONE, on="2026-11-01",
                                      idempotency_key=idempotency_key(context, "order_create", order_arguments(args, context)),
                                      call_id=context.call_id, turn_id=context.turn_id,
                                      purchase_authorization=purchase.receipt(context.pending_purchase, order_arguments(args, context), context))

    handler = AsyncMock(side_effect=execute)
    (result, _), (replay, _) = await asyncio.gather(attempt_order(context, args, handler),
                                                  attempt_order(context, args, handler))
    assert result == replay and result["status"] == "created"
    assert handler.await_count == 2  # Both reached the backend; its lock/key allows one mutation.
    business = order_arguments(args, context)
    token = purchase.receipt(context.pending_purchase, business, context)
    key = purchase.order_key(context.call_id, business)
    expired_context = authorized(replace(context, turn_id="later-confirm"), {**args, "qty": 2})
    expired_payload = order_arguments({**args, "qty": 2}, expired_context)
    expired_token = purchase.receipt(expired_context.pending_purchase, expired_payload, expired_context)
    monkeypatch.setattr(purchase, "now", lambda: expired_context.pending_purchase["expires_at"] + 1)
    # A consumed receipt may retrieve its first success; an expired unused receipt cannot write.
    assert await crm.order_create(**business, call_id=context.call_id, turn_id=context.turn_id,
                                  purchase_authorization=token, idempotency_key=key) == result
    with pytest.raises(ToolFailure, match="expired"):
        await crm.order_create(**expired_payload, call_id=context.call_id, turn_id=expired_context.turn_id,
                               purchase_authorization=expired_token,
                               idempotency_key=purchase.order_key(context.call_id, expired_payload))
    for changes in ({"qty": 2}, {"call_id": str(a["id"])}, {"turn_id": "another-turn"}):
        with pytest.raises(ToolFailure, match="Purchase confirmation"):
            await crm.order_create(**{**business, "call_id": context.call_id, "turn_id": context.turn_id,
                                     "purchase_authorization": token, "idempotency_key": key, **changes})
    async with pool.connection() as conn:
        state = (await (await conn.execute("SELECT state FROM mock_state WHERE id = 1")).fetchone())["state"]
        assert len(state["orders"]) == len(state["idempotent"]) == 1
        assert state["purchase_consumed"] == {context.pending_purchase["draft_id"]: purchase.order_key(context.call_id, order_arguments(args, context))}
        assert next(iter(state["orders"].values()))["customer_phone"] == PHONE
    assert (await graph.aget_state(harness.thread(a["id"]))).values == before


def test_platform_checkout_checks_boolean_and_current_quote_but_has_no_confirmation_challenge(client):
    from conftest import conversation, identify
    from test_workflows import order_body
    from sqlalchemy import func, select
    from src.db.models import Order

    a, ha = conversation(client)
    customer = identify(client, a, ha, phone=PHONE)
    b, hb = conversation(client, customer)
    body = order_body(client)
    path = f"/api/conversations/{b}/orders"
    assert client.post(path, headers=hb, json={**body, "confirmed": False}).status_code == 422
    assert client.post(path, headers=hb, json={**body, "expected_total": "1"}).status_code == 409
    result = client.post(path, headers=hb, json=body)
    assert result.status_code == 201, result.text  # No draft/challenge was created in B beforehand.
    assert client.post(f"/api/conversations/{a}/orders", headers=ha, json=body).json()["id"] == result.json()["id"]
    with client.app.state.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1
