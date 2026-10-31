"""Verified web identity and incremental memory; no provider calls."""
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_agent_service.agents.memory import MemoryAgent
from ai_agent_service.components.memory.gate import Candidate
from ai_agent_service.mcp.servers import memory as server
from ai_agent_service.pipeline.cold.after_call import _remember
from ai_agent_service.pipeline.hot import nodes
from ai_agent_service.pipeline.hot.state import HotContext
from ai_agent_service.runtime import calls, harness


@pytest.mark.asyncio
async def test_verified_new_web_account_gets_stable_memory_identity_without_trusting_spoken_phone():
    ctx = HotContext(account_id='account-A', account_name='An', caller_phone='0902910201', identity_secret='test',
                     harness=SimpleNamespace(data=AsyncMock(return_value={})))
    state = {'channel':'web','on':'2026-10-29','flags':{},'keys_seen':[]}
    with patch.object(nodes, '_brief', AsyncMock(return_value={})):
        got = await nodes._identify(state, ctx)
    assert got['tier'] == 'VERIFIED' and got['customer_id'] == 'web:account-A'
    assert got['customer_name'] == 'An'
    assert all(k['from_connection'] and k['customer_ids'] == ['web:account-A'] for k in got['keys_seen'])
    ctx.caller_phone = None
    with patch.object(nodes, '_brief', AsyncMock(return_value={})):
        unverified = await nodes._identify(state, ctx)
    assert unverified.get('tier') != 'VERIFIED'


@pytest.mark.asyncio
async def test_existing_phone_memory_identity_is_preserved_and_account_name_fills_missing_name():
    async def read(name, **kwargs):
        if name == 'identity_find':return {'matches':[{'customer_id':'LEGACY-A','status':'confirmed'}]}
        return {}
    ctx = HotContext(account_id='account-A', account_name='An', caller_phone='0902910201', identity_secret='test',
                     harness=SimpleNamespace(data=read))
    with patch.object(nodes, '_brief', AsyncMock(return_value={})):
        got = await nodes._identify({'channel':'web','flags':{}}, ctx)
    assert got['tier'] == 'VERIFIED' and got['customer_id'] == 'LEGACY-A'
    assert got['customer_name'] == 'An'


@pytest.mark.asyncio
async def test_incremental_commit_has_provenance_but_no_episode_or_qa():
    writes=[]
    async def data(name, **kwargs):
        if name=='memory_get_profile':return {'facts':[]}
        if name=='memory_get_episodes':return {'episodes':[]}
        if name=='memory_commit_facts':writes.extend(kwargs['decisions']);return {'memory_writes':[]}
        raise AssertionError(name)
    memory=SimpleNamespace(summarize=AsyncMock())
    result=await _remember({'call_id':1,'tier':'VERIFIED','customer_id':'A','on':'2026-10-29',
        'turn_times':{1:'2026-10-29T16:00:00+00:00'}},[Candidate('room_area_m2',25,'customer',1)],
        writer=SimpleNamespace(data=data),memory=memory,episode=False)
    assert result['status']=='done'
    assert writes[0]['source']['observed_at']=='2026-10-29T16:00:00+00:00'
    memory.summarize.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_retries_failed_memory_without_repeating_advisor(monkeypatch):
    monkeypatch.setattr(calls,'claim_lease',AsyncMock(return_value=True))
    monkeypatch.setattr(calls,'release_lease',AsyncMock())
    monkeypatch.setattr(calls,'stored_reply',AsyncMock(return_value={'content':'saved','meta':{'memory_status':'failed'}}))
    monkeypatch.setattr(harness,'remember',AsyncMock(return_value={'status':'done'}))
    monkeypatch.setattr(harness,'_patch_meta',AsyncMock())
    monkeypatch.setattr(harness,'run_turn',AsyncMock())
    out=await calls.take_turn({'id':1,'ended_at':None},content='same',turn_id='t1',arrived=0,
                             actor=calls.Actor('customer',False))
    assert out.content=='saved'
    harness.remember.assert_awaited_once_with(1,finalize=False)
    harness.run_turn.assert_not_awaited()
    calls.release_lease.assert_awaited_once()


@pytest.mark.asyncio
async def test_delayed_tab_cannot_replace_a_newer_fact():
    held={'fact_id':'f1','value':30,'source':{'observed_at':'2026-10-29T16:01:00+00:00'}}
    conn=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(fetchone=AsyncMock(return_value=held))))
    with patch.object(server,'_already',AsyncMock(return_value=False)):
        result=await server._apply(conn,'A',{'slot':'room_area_m2','value':25,'operation':'update',
            'source':{'observed_at':'2026-10-29T16:00:00+00:00'}},date(2026,10,29))
    assert result is None
    assert conn.execute.await_count==1


@pytest.mark.parametrize('text,name',[('Dạ em đã lên đơn cho anh ạ.','order.create'),
                                      ('Dạ em đã đổi size cho anh ạ.','order.update')])
def test_completed_order_claim_requires_successful_tool(text,name):
    from ai_agent_service.components.guardrails.hard import GuardInput, _completed_order
    assert _completed_order(text,GuardInput(text=text,tier='VERIFIED',tool_results=()))
    assert not _completed_order(text,GuardInput(text=text,tier='VERIFIED',tool_results=({
        'name':name,'result':{'ok':True,'data':{'order_id':'TEST'}}},)))
    assert _completed_order(text,GuardInput(text=text,tier='VERIFIED',tool_results=({
        'name':name,'result':{'ok':False,'error':{'code':'TIMEOUT'}}},)))


@pytest.mark.parametrize('text',['Dạ em chưa tạo đơn cho anh.','Anh đã đặt hàng chưa ạ?',
                                'Dạ em sẽ lên đơn khi anh xác nhận.'])
def test_order_question_or_future_action_is_not_a_completed_claim(text):
    from ai_agent_service.components.guardrails.hard import GuardInput, _completed_order
    assert not _completed_order(text,GuardInput(text=text,tier='VERIFIED',tool_results=()))


def test_incremental_facts_put_customer_name_in_advisor_brief_without_inventing_episode():
    from ai_agent_service.components.memory.brief import render
    from datetime import datetime, timezone
    brief, lines=render(customer={'customer_id':'A','name':'An','honorific':'anh'},
        facts=[{'slot':'room_area_m2','value':25,'kind':'preference','status':'active','fact_id':'F1'}],
        episodes=[],orders=[],products=[],warnings=[],now=datetime(2026,10,29,tzinfo=timezone.utc),latency_ms=1,channel='web')
    assert brief['is_returning'] and brief['n_previous_sessions']==0
    assert any('anh An' in line.text for line in lines)
    assert 'An' in brief['suggested_opening']
