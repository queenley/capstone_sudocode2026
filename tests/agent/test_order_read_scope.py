"""A sales model cannot read another customer's order by guessing its ID."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.agents.advisor import ActionGuardMiddleware,AgentContext


@pytest.mark.asyncio
@pytest.mark.parametrize('tier,known,args,allowed',[
    ('VERIFIED',frozenset({'ORDER-OWN'}),{'order_id':'ORDER-OWN'},True),
    ('VERIFIED',frozenset({'ORDER-OWN'}),{'order_id':'ORDER-OTHER'},False),
    ('VERIFIED',frozenset(),{},True),
    ('UNKNOWN',frozenset(),{},False),
    ('PROBABLE',frozenset({'ORDER-OWN'}),{'order_id':'ORDER-OWN'},False),
])
async def test_order_read_is_scoped_to_verified_customer(tier,known,args,allowed):
    ctx=AgentContext(call_id='fixture',tier=tier,lane='CONTINUITY',customer_phone='0900000001',known_orders=known)
    request=SimpleNamespace(tool_call={'name':'order_status','id':'read','args':args},
                            runtime=SimpleNamespace(context=ctx),state={})
    request.override=lambda **changes:SimpleNamespace(**{**vars(request),**changes})
    handler=AsyncMock(return_value='own-order')
    result=await ActionGuardMiddleware().awrap_tool_call(request,handler)
    assert handler.await_count==int(allowed)
    if not allowed:assert result.additional_kwargs['blocked_by']=='guardrail'


@pytest.mark.asyncio
async def test_guarded_tool_without_runtime_context_fails_closed():
    handler=AsyncMock()
    request=SimpleNamespace(tool_call={'name':'order_create','id':'write','args':{}},
                            runtime=SimpleNamespace(context=None),state={})
    result=await ActionGuardMiddleware().awrap_tool_call(request,handler)
    handler.assert_not_awaited()
    assert result.additional_kwargs['blocked_by']=='guardrail'


@pytest.mark.asyncio
async def test_shared_phone_cannot_enumerate_other_household_members_orders():
    ctx=AgentContext(call_id='fixture',tier='VERIFIED',lane='CONTINUITY',customer_phone='0900000001',
                     shared_phone=True)
    request=SimpleNamespace(tool_call={'name':'order_status','id':'read','args':{}},
                            runtime=SimpleNamespace(context=ctx),state={})
    handler=AsyncMock()
    result=await ActionGuardMiddleware().awrap_tool_call(request,handler)
    handler.assert_not_awaited()
    assert result.additional_kwargs['blocked_by']=='guardrail'


@pytest.mark.asyncio
async def test_verified_channel_customer_can_read_known_order_without_phone():
    ctx=AgentContext(call_id='fixture',customer_id='C-OWN',tier='VERIFIED',lane='CONTINUITY',
                     known_orders=frozenset({'ORDER-OWN'}))
    request=SimpleNamespace(tool_call={'name':'order_status','id':'read','args':{'order_id':'ORDER-OWN'}},
                            runtime=SimpleNamespace(context=ctx),state={})
    request.override=lambda **changes:SimpleNamespace(**{**vars(request),**changes})
    handler=AsyncMock(return_value='own-order')
    assert await ActionGuardMiddleware().awrap_tool_call(request,handler)=='own-order'
