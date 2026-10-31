"""Oct 17 failure pattern: a guessed SKU must never reach pricing/stock tools."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage

from ai_agent_service.agents.advisor import ActionGuardMiddleware, AgentContext, tool_results_of
from langchain_core.messages import AIMessage
from ai_agent_service.mcp.tools import idempotency_key
from ai_agent_service.mcp.servers import btc


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["pricing_get_quote", "inventory_check"])
@pytest.mark.parametrize("seen", [False, True])
async def test_catalog_result_required_before_sku_reads(name, seen):
    call = {"id": "tool-1", "name": name, "args": {"sku": "SKU-TEST-42"}}
    message = ToolMessage(name="catalog_search", tool_call_id="catalog-1", content=json.dumps({
        "ok": True, "data": {"items": [{"sku": "SKU-TEST", "variants": [{"variant_sku": "SKU-TEST-42"}]}]}}))
    request = SimpleNamespace(tool_call=call, runtime=SimpleNamespace(context=AgentContext(call_id="test")),
                              state={"messages": [message] if seen else []})
    request.override = lambda **changes: SimpleNamespace(**{**vars(request), **changes})
    handler = AsyncMock(return_value="tool-result")
    result = await ActionGuardMiddleware().awrap_tool_call(request, handler)
    if seen:
        assert result == "tool-result"
        handler.assert_awaited_once()
    else:
        assert json.loads(result.content)["error"]["code"] == "PRECONDITION"
        handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_tool_result_does_not_trust_a_sku():
    context = AgentContext(call_id="test")
    call = {"id": "tool-1", "name": "pricing_get_quote", "args": {"sku": "GUESSED"}}
    request = SimpleNamespace(tool_call=call, runtime=SimpleNamespace(context=context), state={"messages": [
        ToolMessage(name="pricing_get_quote", tool_call_id="old", content=json.dumps({
            "ok": False, "data": {"sku": "GUESSED"}, "error": {"code": "unknown_sku"}}))]})
    handler = AsyncMock()
    result = await ActionGuardMiddleware().awrap_tool_call(request, handler)
    assert result.additional_kwargs["blocked_by"] == "guardrail"
    handler.assert_not_awaited()


def test_repeat_order_across_turns_replays_first_result():
    context = SimpleNamespace(call_id="call-1", turn_id="t2")
    args = {"sku": "SKU-AP-X", "price_vnd": 4890000, "qty": 1, "payment": "COD"}
    first = idempotency_key(context, "order_create", args)
    context.turn_id = "t4"
    repeated = idempotency_key(context, "order_create", args)
    assert first == repeated
    # Exercise the real persisted replay path, with no business mutation or database.
    result = {"order_id": "ORDER-TEST", "status": "created"}
    reply, changed = btc.run_write(None, {"idempotent": {first: result}}, None, args, repeated)
    assert reply == result
    assert changed is None
    assert idempotency_key(context, "order_create", {**args, "qty": 2}) != first
    assert idempotency_key(SimpleNamespace(call_id="call-2", turn_id="t4"), "order_create", args) != first


def test_other_writes_remain_scoped_to_turn():
    a = SimpleNamespace(call_id="call", turn_id="t1")
    b = SimpleNamespace(call_id="call", turn_id="t2")
    assert idempotency_key(a, "order_update", {"action": "update_address"}) != idempotency_key(
        b, "order_update", {"action": "update_address"})


def test_catalog_codes_survive_turn_reset_and_enter_advisor_context():
    from datetime import datetime, timezone
    from ai_agent_service.pipeline.hot.nodes import _absorb, _agent_context
    from ai_agent_service.pipeline.hot.state import TURN_KEYS, HotContext

    state = {"call_id": "test", "now": datetime.now(timezone.utc), "tier": "UNKNOWN"}
    state.update(_absorb(state, [{"name": "catalog.search", "args": {}, "result": {"ok": True, "data": {
        "items": [{"sku": "SKU-TEST", "variants": [{"variant_sku": "SKU-TEST-42"}]}]}}}]))
    state.update(TURN_KEYS)
    context = _agent_context(state, HotContext(), None)
    assert context.trusted_skus == frozenset({"SKU-TEST", "SKU-TEST-42"})


@pytest.mark.asyncio
async def test_delivery_estimate_needs_no_sku():
    request = SimpleNamespace(tool_call={"id": "delivery", "name": "delivery_estimate", "args": {"address": "Huế"}})
    handler = AsyncMock(return_value="delivery-date")
    assert await ActionGuardMiddleware().awrap_tool_call(request, handler) == "delivery-date"


def test_framework_limit_is_not_exported_as_an_executed_order():
    from ai_agent_service.pipeline.eval.trace import tool_calls

    messages = [AIMessage(content="", tool_calls=[{
        "id": "order", "name": "order_create", "args": {"sku": "SKU-TEST", "qty": 1}}]),
        ToolMessage(content="Tool call limit exceeded. Do not make additional tool calls.",
                    tool_call_id="order", name="order_create", status="error")]
    result = tool_results_of(messages)
    assert result[0]["result"]["error"]["code"] == "TOOL_CALL_LIMIT"
    assert result[0]["blocked_by"] == "framework"
    assert tool_calls(result) == []


def test_successful_order_remains_exported():
    from ai_agent_service.pipeline.eval.trace import tool_calls

    messages = [AIMessage(content="", tool_calls=[{
        "id": "order", "name": "order_create", "args": {"sku": "SKU-TEST"}}]),
        ToolMessage(content=json.dumps({"ok": True, "data": {"order_id": "ORDER-TEST"}}),
                    tool_call_id="order", name="order_create")]
    # The grader reads result.order_id to accept the order a later call acts on (organisers' answer 10).
    assert tool_calls(tool_results_of(messages))[0]["result"]["order_id"] == "ORDER-TEST"


def test_a_refused_call_is_traced_as_the_tool_s_error():
    from ai_agent_service.pipeline.eval.trace import tool_calls
    refused = [{"name": "order.create", "args": {}, "result": {"ok": False, "error": {"code": "price_mismatch"}}}]
    assert tool_calls(refused)[0]["result"] == {"error": "price_mismatch"}


@pytest.mark.asyncio
async def test_react_can_execute_more_than_six_catalogue_reads():
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import StructuredTool
    from ai_agent_service.agents.advisor import AdvisorAgent

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    queried = []

    async def lookup(query: str) -> str:
        queried.append(query)
        return json.dumps({"ok": True, "data": {"items": []}})

    model = Model(responses=[AIMessage(content="", tool_calls=[{
        "name": "catalog_search", "id": str(i), "args": {"query": str(i)}} for i in range(7)]),
        AIMessage(content="Dạ em đã kiểm tra các sản phẩm ạ.")])
    tool = StructuredTool.from_function(coroutine=lookup, name="catalog_search", description="Find a product")
    agent = AdvisorAgent(llm=model, tools=[tool], retries=0)
    result = await agent.draft([HumanMessage(content="Tìm sản phẩm")], AgentContext(call_id="test", lane="NEW"))
    assert len(queried) == 7
    assert all(r["result"]["ok"] for r in result.tool_results)


# ── catalog_search: what the shop does not sell is not answered with something else ──


async def _search(query, **filters):
    async def mock_search(args):
        return btc.mock().catalog_search(**{k: v for k, v in args.items() if v is not None})
    return await btc.search_catalog({"query": query, "category": None, "sku": None, "max_price_vnd": None,
                                     "min_room_area_m2": None, **filters}, mock_search)


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["máy rửa bát Bosch", "tủ lạnh", "nồi cơm điện", "điều hòa Daikin", "máy giặt",
                                   "áo mưa"])
async def test_a_product_the_shop_does_not_sell_finds_nothing(query):
    found = await _search(query)
    assert found["match"] == "none" and found["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("query, sku", [
    ("may loc khong khi", "SKU-AP-MINI"),
    ("máy lọc không khí cho phòng ngủ có em bé", "SKU-AP-MINI"),
    ("xe day gap gon", "SKU-MB-STR1"),
    ("may hut sua", "SKU-MB-PUMP1"),
    ("mang loc thay the", "SKU-AP-FLT-X"),
])
async def test_the_loose_search_still_finds_what_the_shop_sells(query, sku):
    found = await _search(query)
    assert found["match"] != "none"
    assert sku in {item["sku"] for item in found["items"]}


@pytest.mark.asyncio
async def test_the_loose_search_keeps_the_kind_asked_for():
    found = await _search("nồi chiên Sunhouse")
    assert found["match"] == "loose"
    assert {item["category"] for item in found["items"]} == {"gia-dung/noi-chien"}
    assert all(item["category"] == "me-be" for item in (await _search("xe day", category="me-be"))["items"])
