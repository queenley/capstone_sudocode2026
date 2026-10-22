"""Offline regressions for the Oct 22 logs; no provider or historical scenario execution."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.tools import StructuredTool

from ai_agent_service.agents.advisor import AdvisorAgent, AgentContext
from ai_agent_service.components.orchestration.rules import RouteInput, decide
from ai_agent_service.pipeline.hot import nodes
from ai_agent_service.pipeline.hot.state import HotContext


@pytest.mark.parametrize("said", ["Alo, anh gọi để hỏi tình trạng đơn hàng của mình.",
                                  "Đơn hàng của anh đang ở đâu rồi?"])
def test_verified_order_lookup_does_not_offer_new_purchase_tools(said):
    route = decide(RouteInput(tier="VERIFIED", has_brief=True, has_order=False, asr_low_conf=False,
                              tool_failures=0, safe_lines=0, customer_said=said))
    assert route.lane == "ORDER_SERVICE"


@pytest.mark.parametrize("tier,said", [("UNKNOWN", "Đơn hàng đang ở đâu?"),
                                       ("VERIFIED", "Nếu mua thì khi nào giao?"),
                                       ("VERIFIED", "Tư vấn đổi size trước khi mua")])
def test_order_lookup_does_not_bypass_identity_or_capture_presale_questions(tier, said):
    route = decide(RouteInput(tier=tier, has_brief=tier=="VERIFIED", has_order=False,
                              asr_low_conf=False, tool_failures=0, safe_lines=0, customer_said=said))
    assert route.lane != "ORDER_SERVICE"


class Model(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.asyncio
async def test_last_model_call_has_no_tools_and_preserves_previous_results():
    observed = []

    class InspectModel(Model):
        def bind_tools(self, tools, **kwargs):
            observed.append([t.name for t in tools])
            return self

    async def lookup(query: str) -> str:
        return json.dumps({"ok": True, "data": {"items": []}})

    model = InspectModel(responses=[AIMessage(content="", tool_calls=[{
        "name": "catalog_search", "id": str(i), "args": {"query": str(i)}}]) for i in range(7)]
        + [AIMessage(content="Dạ em chưa tìm được sản phẩm phù hợp ạ.")])
    tool = StructuredTool.from_function(coroutine=lookup, name="catalog_search", description="Find product")
    agent = AdvisorAgent(llm=model, tools=[tool], retries=0)
    draft = await agent.draft([HumanMessage(content="Tìm sản phẩm")], AgentContext(call_id="fixture", lane="NEW"))
    assert len(draft.tool_results) == 7
    # create_agent skips bind_tools entirely when tools is empty.
    assert len(observed) == 7
    assert draft.model_calls == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["speak", "copilot"])
async def test_model_failure_preserves_executed_order_in_hot_state(mode):
    class BrokenGraph:
        async def astream(self, *args, **kwargs):
            yield "updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{
                "id": "order", "name": "order_create", "args": {"sku": "SKU-TEST"}}])]}}
            yield "updates", {"tools": {"messages": [ToolMessage(name="order_create", tool_call_id="order",
                content=json.dumps({"ok": True, "data": {"order_id": "ORDER-TEST"}}))]}}
            raise RuntimeError("fixture model failure after the order")

    agent = AdvisorAgent(llm=Model(responses=[AIMessage(content="unused")]), tools=[], retries=0)
    agent._graph = BrokenGraph()
    state = {"call_id": "fixture", "turn_id": "turn-1", "mode": mode, "tier": "VERIFIED",
             "now": datetime.now(timezone.utc), "lane": "NEW", "messages": [HumanMessage(content="Kiểm tra giúp em")], "turn_no": 1}
    update = await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=agent)))
    assert update["draft"]["fallback"] is True
    assert update["draft"]["error"] == "RuntimeError"
    assert update["known_orders"] == ["ORDER-TEST"]
    assert update["tool_results"][0]["result"]["ok"] is True


def test_unanswered_tool_request_is_unknown_and_not_exported_as_executed():
    from ai_agent_service.agents.advisor import tool_results_of
    from ai_agent_service.pipeline.eval.trace import tool_calls
    results = tool_results_of([AIMessage(content='',tool_calls=[{
        'id':'unanswered','name':'order_create','args':{'sku':'SKU-TEST'}}])])
    assert results[0]['result']['error']['code'] == 'TOOL_RESULT_MISSING'
    assert results[0]['result']['error']['retryable'] is False
    assert tool_calls(results) == []


@pytest.mark.asyncio
async def test_stream_error_keeps_sent_sentence_and_only_adds_safe_line():
    class BrokenGraph:
        async def astream(self, *args, **kwargs):
            yield 'messages', (AIMessage(content='Dạ em đang kiểm tra ạ. Em sẽ', id='reply'),{'langgraph_node':'model'})
            raise RuntimeError('fixture failure while speaking')

    agent = AdvisorAgent(llm=Model(responses=[AIMessage(content='unused')]), tools=[], retries=0)
    agent._graph = BrokenGraph()
    state = {'call_id':'fixture','turn_id':'turn-1','mode':'speak','tier':'VERIFIED','lane':'NEW',
             'now':datetime.now(timezone.utc), 'messages':[HumanMessage(content='Kiểm tra giúp em')]}
    spoken = []
    async def emit(kind,text):
        if kind=='sentence':spoken.append(text)
    update = await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=agent,emit=emit)))
    assert update['draft']['fallback'] and update['draft']['error']=='RuntimeError'
    assert update['draft']['text'].startswith('Dạ em đang kiểm tra ạ.')
    assert spoken[0]=='Dạ em đang kiểm tra ạ.'
    assert len(spoken)==2


@pytest.mark.parametrize('tier,lane,expected', [
    ('VERIFIED','ORDER_SERVICE',{'phone':'0900000001'}),
    ('UNKNOWN','ORDER_SERVICE',{'phone':'0900000002','zalo_id':'other-profile'}),
    ('VERIFIED','NEW',{'phone':'0900000002','zalo_id':'other-profile'}),
])
def test_order_lookup_uses_verified_caller_without_exposing_phone_to_model(tier,lane,expected):
    from ai_agent_service.mcp.tools import ToolGuardMiddleware
    request = SimpleNamespace(tool_call={'name':'crm_get_customer','args':{
        'phone':'0900000002','zalo_id':'other-profile'}},
        tool=SimpleNamespace(args={'phone':{},'zalo_id':{},'fb_id':{}}),
        runtime=SimpleNamespace(context=AgentContext(call_id='fixture',tier=tier,lane=lane,
                                                   customer_phone='0900000001')))
    request.override = lambda **changes: SimpleNamespace(**{**vars(request),**changes})
    adjusted = ToolGuardMiddleware(['crm_get_customer'],retries=0)._with_context(request)
    assert adjusted.tool_call['args']==expected
