import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage
from ai_agent_service.agents.advisor import AgentContext,system_prompt
from ai_agent_service.components.intake import pii
from ai_agent_service.mcp.tools import ToolGuardMiddleware
from ai_agent_service.pipeline.eval.trace import turn_row
from ai_agent_service.components.memory.brief import BriefLine


@pytest.mark.asyncio
async def test_tool_receives_raw_phone_but_model_and_checkpoint_receive_token():
    vault=pii.Vault()
    phone='0900000001'
    vault.put('PHONE',phone)
    ctx=AgentContext(call_id='fixture',tier='VERIFIED',lane='CONTINUITY',customer_phone=phone,vault=vault)
    request=SimpleNamespace(tool_call={'name':'order_status','id':'lookup','args':{}},
        runtime=SimpleNamespace(context=ctx),tool=SimpleNamespace(args={'customer_phone':{}}))
    request.override=lambda **changes:SimpleNamespace(**{**vars(request),**changes})
    handler=AsyncMock(return_value=ToolMessage(tool_call_id='lookup',name='order_status',
        content=json.dumps({'ok':True,'data':{'orders':[{'order_id':'ORDER-OWN','customer_phone':phone}]}})))
    result=await ToolGuardMiddleware(['order_status'],retries=0).awrap_tool_call(request,handler)
    assert handler.await_args.args[0].tool_call['args']['customer_phone']==phone
    assert phone not in result.content
    assert phone not in json.dumps(result.additional_kwargs)
    assert json.loads(result.content)['data']['orders'][0]['customer_phone']=='<PHONE_1>'
    assert result.additional_kwargs['args']['customer_phone']=='<PHONE_1>'


def test_sensitive_tool_values_are_restored_only_at_explicit_trace_export():
    vault=pii.Vault();vault.put('PHONE','0900000001')
    row=turn_row(run_id='fixture',config='full',scenario_id='FIXTURE',call='call_1',turn=1,
        customer_text='fixture',state={'reply':{'text':'Dạ em kiểm tra ạ.'},'tool_results':[{
            'name':'order.status','args':{'customer_phone':'<PHONE_1>'},
            'result':{'ok':True,'data':{'customer_phone':'<PHONE_1>'}}}]},vault=vault,
        total_ms=1,first_token_ms=1,call_brief_latency_ms=None,input_mode='clean')
    assert row['tool_calls'][0]['args']['customer_phone']=='0900000001'
    assert row['tool_calls'][0]['result']['customer_phone']=='0900000001'


def test_business_evidence_and_repair_reason_survive_context_budget():
    results=tuple({'name':'catalog.search','args':{},'result':{'ok':True,'data':{
        'items':[{'name':'Sản phẩm cần tra '+('chi tiết '*150),'sku':f'SKU-TEST-{i}'}]}}} for i in range(12))
    ctx=AgentContext(call_id='fixture',tier='VERIFIED',lane='CONTINUITY',
        brief_lines=(BriefLine('B1','Size khách đã chọn: 42.'),),tool_results=results,
        block_reasons=('Không tạo đơn khi chưa xác nhận giá.',))
    prompt,cut=system_prompt(ctx)
    assert 'tool_results' not in cut
    assert 'SKU-TEST-11' in prompt
    assert 'Không tạo đơn khi chưa xác nhận giá.' in prompt
    assert 'Size khách đã chọn: 42.' in prompt


def test_json_redaction_round_trip_keeps_quotes_and_unicode():
    vault=pii.Vault()
    data={'address':'12 Nguyễn Du, phường 1, ghi chú "cổng sau"','phone':'0900000001',
          'nested':[{'price':5200000,'confirmed':False}]}
    shown=pii.tokenise_data(data,vault)
    assert 'Nguyễn Du' not in json.dumps(shown,ensure_ascii=False)
    assert shown['address'].startswith('<ADDR_')
    assert pii.detokenize_data(shown,vault)==data
    assert '0900000001' not in str(pii.detokenize_data(shown,vault,reveal_phone=False))


@pytest.mark.asyncio
async def test_crm_episode_pii_is_masked_before_checkpoint_brief():
    from datetime import datetime,timezone
    from ai_agent_service.pipeline.hot import nodes
    from ai_agent_service.pipeline.hot.state import HotContext
    tools=SimpleNamespace(data=AsyncMock(side_effect=[{'facts':[]},{'episodes':[]}]))
    state={'customer_id':'C-FIXTURE','on':'2026-10-22','now':datetime.now(timezone.utc),
           'crm':{'sessions':[{'session_id':'previous','date':'2026-10-21','channel':'web',
                   'summary':'Liên hệ số 0900000001'}]}}
    import time
    update=await nodes._brief(state,HotContext(harness=tools),time.perf_counter())
    assert '0900000001' not in json.dumps(update,ensure_ascii=False,default=str)
    assert '<PHONE_1>' in str(update)


@pytest.mark.asyncio
async def test_shared_phone_crm_result_shows_only_verified_customer_profile():
    ctx=AgentContext(call_id='fixture',tier='VERIFIED',lane='CONTINUITY',customer_phone='0900000001',
                     customer_id='C-OWN',shared_phone=True)
    request=SimpleNamespace(tool_call={'name':'crm_get_customer','id':'lookup','args':{}},
        runtime=SimpleNamespace(context=ctx),tool=SimpleNamespace(args={'phone':{}}))
    request.override=lambda **changes:SimpleNamespace(**{**vars(request),**changes})
    handler=AsyncMock(return_value=ToolMessage(tool_call_id='lookup',name='crm_get_customer',content=json.dumps({
        'ok':True,'data':{'found':True,'ambiguous':True,'candidates':[
            {'customer_id':'C-OWN','name':'Hoa','orders':[]},
            {'customer_id':'C-OTHER','name':'Other Person','orders':[{'order_id':'ORDER-OTHER'}]}]}})))
    result=await ToolGuardMiddleware(['crm_get_customer'],retries=0).awrap_tool_call(request,handler)
    body=json.loads(result.content)
    assert body['data']['customer_id']=='C-OWN'
    assert 'C-OTHER' not in result.content and 'ORDER-OTHER' not in result.content


def test_tool_address_is_only_reused_explicitly_and_does_not_replace_customer_default():
    vault=pii.Vault()
    first=vault.put('ADDR','12 Nguyễn Du')
    second=vault.put('ADDR','99 Lê Lợi')
    ctx=AgentContext(call_id='fixture',addresses={first:'12 Nguyễn Du'},vault=vault)
    for chosen,expected in [(None,'12 Nguyễn Du'),(second,'99 Lê Lợi')]:
        request=SimpleNamespace(tool_call={'name':'delivery_estimate','id':'delivery','args':{'address':chosen}},
            runtime=SimpleNamespace(context=ctx),tool=SimpleNamespace(args={'address':{}}))
        request.override=lambda **changes:SimpleNamespace(**{**vars(request),**changes})
        adjusted=ToolGuardMiddleware(['delivery_estimate'],retries=0)._with_context(request)
        assert adjusted.tool_call['args']['address']==expected
