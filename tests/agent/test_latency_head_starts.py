"""What the harness does ahead of the model so the first sentence does not wait for a second model round."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from ai_agent_service.mcp.tools import _fit  # noqa: E402
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
    assert names[:5] == ["catalog.search", "pricing.get_quote", "inventory.check", "pricing.get_quote", "inventory.check"]
    # Plan 003: what the team's tool concluded follows, for the harness to say; it did not run, so no trace line.
    assert names[5:] == ["product_advise"] and events[-1].draft.tool_results[5]["result"] is None


def test_without_the_switch_the_tool_is_not_offered(monkeypatch):
    monkeypatch.setenv("ADVISOR_PRODUCT_ADVISE", "0")
    agent = advisor(lambda request: sse(chunk(content="Dạ.")), lookups([]))
    assert "product_advise" not in agent.tool_names

