"""What the harness does ahead of the model so the first sentence does not wait for a second model round."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from ai_agent_service.agents.advisor import AdvisorAgent, AgentContext
from ai_agent_service.components.guardrails import fallback

NOW = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)


def sse(*chunks):
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks] + ["data: [DONE]\n\n"]
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(lines).encode())


def chunk(**delta):
    return {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "gpt-5.6-luna",
            "choices": [{"index": 0, "delta": {"role": "assistant", **delta}, "finish_reason": None}]}


def tool(name, data, properties, ran):
    async def run(**kwargs):
        ran.append((name, kwargs))
        return json.dumps({"ok": True, "data": data})
    return StructuredTool.from_function(coroutine=run, name=name, description=name, args_schema={
        "type": "object", "properties": properties, "additionalProperties": False})


def advisor(answer, tools):
    model = ChatOpenAI(model="gpt-5.6-luna", api_key="x", reasoning_effort="none", use_responses_api=False, stream_usage=True,
                       http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)), max_retries=0)
    return AdvisorAgent(tools=tools, llm=model, retries=0)


SKU = {"sku": {"type": "string"}}
DAY = {"on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}}


def lookups(ran):
    return [tool("catalog_search", {"items": []}, {"query": {"type": "string"}}, ran),
            tool("pricing_get_quote", {"sku": "SKU-AP-X", "final_price_vnd": 4890000}, {**SKU, "qty": {"type": "integer"}, **DAY}, ran),
            tool("inventory_check", {"sku": "SKU-AP-X", "in_stock": True}, {**SKU, **DAY}, ran)]


@pytest.mark.asyncio
async def test_a_named_product_is_priced_before_the_models_first_call(monkeypatch):
    monkeypatch.setenv("ADVISOR_PREFETCH", "1")
    requests, ran = [], []

    def answer(request):
        requests.append(json.loads(request.content))
        return sse(chunk(content="Dạ AirPure X giá 4.890.000đ, còn hàng ạ."))

    said = "Máy lọc không khí AirPure X giá bao nhiêu, còn hàng không em?"
    context = AgentContext(call_id="c", lane="NEW", now=NOW, on="2026-11-07", turn_id="t1", customer_said=said)
    events = [event async for event in advisor(answer, lookups(ran)).stream([HumanMessage(said)], context)]

    assert len(requests) == 1  # the answer is the first model call: the price and the stock were already there
    called = [c["function"]["name"] for m in requests[0]["messages"] for c in m.get("tool_calls") or []]
    assert called == ["pricing_get_quote", "inventory_check"]
    assert ("pricing_get_quote", {"sku": "SKU-AP-X", "qty": 1, "on": "2026-11-07"}) in ran
    done = events[-1].draft
    assert [r["name"] for r in done.tool_results] == ["pricing.get_quote", "inventory.check"]  # in the trace, as tools
    assert done.model_calls == 1


@pytest.mark.asyncio
async def test_no_product_named_or_the_switch_off_looks_nothing_up(monkeypatch):
    for switch, said in (("1", "Mua về không ưng thì đổi trả trong bao nhiêu ngày?"), ("0", "AirPure X giá bao nhiêu em?")):
        monkeypatch.setenv("ADVISOR_PREFETCH", switch)
        ran = []
        context = AgentContext(call_id="c", lane="NEW", now=NOW, on="2026-11-07", turn_id="t1", customer_said=said)
        agent = advisor(lambda request: sse(chunk(content="Dạ vâng ạ.")), lookups(ran))
        [event async for event in agent.stream([HumanMessage(said)], context)]
        assert ran == []


@pytest.mark.asyncio
async def test_the_models_next_round_is_told_what_the_harness_said_from_a_tools_result():
    requests, ran = [], []

    def answer(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            call = {"index": 0, "id": "s1", "type": "function",
                    "function": {"name": "catalog_search", "arguments": json.dumps({"query": "quạt"})}}
            return sse(chunk(tool_calls=[call]))
        return sse(chunk(content="Dạ còn gì nữa không ạ?"))

    context = AgentContext(call_id="c", lane="NEW", now=NOW, on="2026-11-07", turn_id="t1")
    line = "Dạ em đã đặt lịch gọi lại cho chị vào 09:00 thứ Sáu 16/10/2026 ạ."
    async for event in advisor(answer, lookups(ran)).stream([HumanMessage("alo")], context):
        if event.kind == "tools":
            context.harness_said.append(line)  # as pipeline.hot.nodes does when a tool with an effect answered

    assert len(requests) == 2
    assert not any(line in json.dumps(m, ensure_ascii=False) for m in requests[0]["messages"])
    assert any(line in json.dumps(m, ensure_ascii=False) for m in requests[1]["messages"])


def test_a_result_line_is_only_for_a_tool_that_did_something():
    booked = {"name": "schedule.callback", "result": {"ok": True, "data": {"callback_at": "2026-10-16T09:00", "moved_from": None}}}
    assert "9 giờ sáng" in fallback.result_line(booked, "chị")
    moved = {"name": "schedule.callback", "result": {"ok": True, "data": {"callback_at": "2026-10-19T09:00", "moved_from": "2026-10-18T09:00"}}}
    assert "dời" in fallback.result_line(moved, "chị")
    assert "OD600001" in fallback.result_line({"name": "order.create", "result": {"ok": True, "data": {"order_id": "OD600001"}}})
    assert fallback.result_line({"name": "order.create", "result": {"ok": False, "error": {"code": "PRECONDITION"}}}) is None
    assert fallback.result_line({"name": "pricing.get_quote", "result": {"ok": True, "data": {"sku": "SKU-AP-X"}}}) is None


# ── plan 002, step 4: the lookups ahead widened to a stated need and the order being closed ──

from ai_agent_service.mcp.tools import MAX_AHEAD_CALLS, ahead_lookups, need_search  # noqa: E402

BUSINESS = frozenset({"catalog_search", "pricing_get_quote", "inventory_check", "delivery_estimate"})


def test_a_need_is_searched_only_with_a_kind_and_an_area_or_a_budget():
    assert need_search("Chị cần máy lọc không khí cho phòng 30m2") == {
        "category": "gia-dung/may-loc-khong-khi", "min_room_area_m2": 30}
    assert need_search("Phòng ngủ 25 mét vuông") is None  # no kind of product
    assert need_search("Phòng ngủ 25 mét vuông", [("customer", "Chị muốn mua máy lọc không khí")]) == {
        "category": "gia-dung/may-loc-khong-khi", "min_room_area_m2": 25}  # the kind said earlier in the call
    assert need_search("Máy lọc không khí loại nào tốt em?") is None  # a kind but no need


def test_the_order_being_closed_is_priced_and_dated_ahead_within_the_limit():
    said = "Đúng rồi em, lên đơn cho chị đi."
    context = AgentContext(call_id="c", customer_said=said, addresses={"<ADDR_1>": "12 Nguyễn Trãi, Q1, HCM"},
                           pending_purchase={"args": {"sku": "SKU-AP-X", "qty": 1}})
    calls = ahead_lookups([HumanMessage(said)], context, BUSINESS)
    assert [c["name"] for c in calls] == ["pricing_get_quote", "inventory_check", "delivery_estimate"]
    assert calls[0]["args"] == {"sku": "SKU-AP-X", "qty": 1}
    # a lane without the tool gets no call of it; nothing after the model's first call
    assert [c["name"] for c in ahead_lookups([HumanMessage(said)], context, frozenset({"pricing_get_quote"}))] == [
        "pricing_get_quote"]
    assert ahead_lookups([], context, BUSINESS) == []
    named = AgentContext(call_id="c", customer_said="AirPure X với Samsung AX40 cái nào tốt hơn",
                         pending_purchase={"args": {"sku": "SKU-AP-Y"}}, addresses={"<ADDR_1>": "x"})
    assert len(ahead_lookups([HumanMessage(named.customer_said)], named, BUSINESS)) == MAX_AHEAD_CALLS


@pytest.mark.asyncio
async def test_a_stated_need_is_searched_and_its_first_results_priced_before_the_model(monkeypatch):
    monkeypatch.setenv("ADVISOR_PREFETCH", "1")
    requests, ran = [], []
    items = [{"sku": "SKU-AP-X", "name": "AirPure X"}, {"sku": "SKU-AP-Y", "name": "AirPure Y"}]
    tools = [tool("catalog_search", {"items": items}, {"category": {"type": "string"},
                                                        "min_room_area_m2": {"type": "integer"}}, ran),
             *lookups(ran)[1:]]

    def answer(request):
        requests.append(json.loads(request.content))
        return sse(chunk(content="Dạ phòng 30m2 thì chị tham khảo AirPure X ạ."))

    said = "Chị cần máy lọc không khí cho phòng 30m2"
    context = AgentContext(call_id="c", lane="NEW", now=NOW, on="2026-11-07", turn_id="t1", customer_said=said)
    events = [e async for e in advisor(answer, tools).stream([HumanMessage(said)], context)]
    assert len(requests) == 1
    assert [name for name, _ in ran] == ["catalog_search", "pricing_get_quote", "inventory_check", "pricing_get_quote"]
    assert events[-1].draft.model_calls == 1


# ── plan 002, B3: one call for a question that needs weighing ──

from ai_agent_service.mcp.tools import _fit  # noqa: E402


def test_the_best_fit_comes_first():
    small = {"sku": "A", "list_price_vnd": 3_000_000, "attributes": {"room_area_m2": 20, "child_safe_lock": True}}
    fits = {"sku": "B", "list_price_vnd": 5_200_000, "attributes": {"room_area_m2": 30, "child_safe_lock": True}}
    no_lock = {"sku": "C", "list_price_vnd": 4_890_000, "attributes": {"room_area_m2": 25, "child_safe_lock": False}}
    # a child lock wanted: C (no lock) falls behind B, which is over budget but has one
    assert [i["sku"] for i in sorted([small, no_lock, fits], key=lambda i: _fit(i, 25, 5_000_000, True))] == ["C", "B", "A"]
    # the room first, then the budget, then the lock
    assert [i["sku"] for i in sorted([small, no_lock, fits], key=lambda i: _fit(i, 25, None, True))] == ["B", "C", "A"]
    assert [i["sku"] for i in sorted([small, no_lock, fits], key=lambda i: _fit(i, 25, 5_000_000, False))] == ["C", "B", "A"]


@pytest.mark.asyncio
async def test_product_advise_is_one_model_call_and_the_trace_has_the_organisers_tools(monkeypatch):
    monkeypatch.setenv("ADVISOR_PRODUCT_ADVISE", "1")
    requests, ran = [], []
    items = [{"sku": "SKU-AP-X", "name": "AirPure X", "list_price_vnd": 4890000,
              "attributes": {"room_area_m2": 25, "child_safe_lock": False}},
             {"sku": "SKU-AP-Y", "name": "AirPure Y", "list_price_vnd": 5200000,
              "attributes": {"room_area_m2": 30, "child_safe_lock": True}}]
    tools = [tool("catalog_search", {"items": items}, {"category": {"type": "string"},
                                                        "min_room_area_m2": {"type": "integer"}}, ran),
             *lookups(ran)[1:]]

    def answer(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            call = {"index": 0, "id": "a1", "type": "function", "function": {"name": "product_advise", "arguments": json.dumps(
                {"category": "gia-dung/may-loc-khong-khi", "room_area_m2": 25, "budget_vnd": 5000000, "has_children": True})}}
            return sse(chunk(tool_calls=[call]))
        return sse(chunk(content="Dạ có bé nhỏ thì chị tham khảo AirPure Y có khóa trẻ em ạ."))

    said = "Phòng hai lăm mét vuông, có bé nhỏ, tầm năm triệu"
    context = AgentContext(call_id="c", lane="NEW", now=NOW, on="2026-11-07", turn_id="t1", customer_said=said)
    agent = advisor(answer, tools)
    events = [e async for e in agent.stream([HumanMessage(said)], context)]
    offered = [t["function"]["name"] for t in requests[0]["tools"]]
    assert "product_advise" in offered
    assert len(requests) == 2  # the call, then the answer: no search, quote and stock rounds in between
    assert [name for name, _ in ran][0] == "catalog_search" and len(ran) == 5
    shown = json.loads(requests[1]["messages"][-1]["content"])["data"]["candidates"]
    # within budget ranks before a child lock; both are shown with how they fit, and the price is the quote's
    assert [c["sku"] for c in shown] == ["SKU-AP-X", "SKU-AP-Y"] and shown[0]["final_price_vnd"] == 4890000
    assert shown[1]["child_safe_lock"] is True and shown[0]["fits_room"] is True
    names = [r["name"] for r in events[-1].draft.tool_results]
    assert names == ["catalog.search", "pricing.get_quote", "inventory.check", "pricing.get_quote", "inventory.check"]


def test_without_the_switch_the_tool_is_not_offered(monkeypatch):
    monkeypatch.setenv("ADVISOR_PRODUCT_ADVISE", "0")
    agent = advisor(lambda request: sse(chunk(content="Dạ.")), lookups([]))
    assert "product_advise" not in agent.tool_names


@pytest.mark.asyncio
async def test_a_stated_need_is_looked_up_ahead_through_product_advise_when_it_is_offered(monkeypatch):
    monkeypatch.setenv("ADVISOR_PREFETCH", "1")
    monkeypatch.setenv("ADVISOR_PRODUCT_ADVISE", "1")
    requests, ran = [], []
    items = [{"sku": "SKU-AP-X", "list_price_vnd": 4890000, "attributes": {"room_area_m2": 25}}]
    tools = [tool("catalog_search", {"items": items}, {"category": {"type": "string"},
                                                        "min_room_area_m2": {"type": "integer"}}, ran),
             *lookups(ran)[1:]]

    def answer(request):
        requests.append(json.loads(request.content))
        return sse(chunk(content="Dạ chị tham khảo AirPure X ạ."))

    said = "Chị cần máy lọc không khí cho phòng 30m2, có bé nhỏ"
    context = AgentContext(call_id="c", lane="NEW", now=NOW, on="2026-11-07", turn_id="t1", customer_said=said)
    events = [e async for e in advisor(answer, tools).stream([HumanMessage(said)], context)]
    assert len(requests) == 1
    ahead = [c["function"]["name"] for m in requests[0]["messages"] for c in m.get("tool_calls") or []]
    assert ahead == ["product_advise"]
    assert ran[0] == ("catalog_search", {"category": "gia-dung/may-loc-khong-khi", "min_room_area_m2": 30})
    assert [r["name"] for r in events[-1].draft.tool_results] == ["catalog.search", "pricing.get_quote", "inventory.check"]
    assert events[-1].draft.model_calls == 1
