import pytest
from ai_agent_service.components.intake import pii
from ai_agent_service.pipeline.eval.trace import facts_used as native_used
from ai_agent_service.runtime import trace_export
from ai_agent_service.runtime.harness import CallStore


def test_literal_overlap_without_citation_does_not_prove_memory_use():
    profile={'size':{'value':42,'fact_id':'size-fact'}}
    assert trace_export.facts_used('Mẫu này giá 1.420.000đ',[],[],profile)==[]


def test_export_uses_frozen_turn_provenance_after_call_brief_changes():
    call={'brief':[{'id':'B1','fact_ids':['new-size']}],
          'brief_object':{'profile_facts':{'size':{'value':43,'fact_id':'new-size'}}}}
    turns=[{'speaker':'customer','turn_id':'t1','content':'Hỏi tiếp','meta':{}},
           {'speaker':'agent','turn_id':'t1','content':'Phòng vẫn 25 m² đúng không ạ?',
            'meta':{'used_brief_lines':['B1'],'facts_used':['room_area_m2']}}]
    row=trace_export.build_rows(call,turns,pii.Vault(),scenario_id='FIXTURE',call_label='call_2')[0]
    assert row['facts_used']==['room_area_m2']


def test_export_does_not_count_blocked_or_unknown_tool_as_executed():
    turns=[{'speaker':'customer','turn_id':'t1','content':'Hỏi tiếp','meta':{}},
           {'speaker':'agent','turn_id':'t1','content':'Em sẽ kiểm tra lại ạ.', 'meta':{'tool_calls':[
               {'name':'order.create','args':{},'blocked_by':'guardrail','result':{'ok':False}},
               {'name':'order.create','args':{},'result':None}]}}]
    row=trace_export.build_rows({},turns,pii.Vault(),scenario_id='FIXTURE',call_label='call_1')[0]
    assert row['tool_calls']==[]


def test_runtime_persists_same_explicit_provenance_as_native_runner():
    state={'reply':{'text':'Phòng vẫn 25 m² đúng không ạ?','used_lines':['B2']},
           'brief_lines':[{'id':'B2','fact_ids':['room-fact']}],
           'brief':{'profile_facts':{'room_area_m2':{'value':25,'fact_id':'room-fact'}}}}
    store=CallStore(call_id=1,vault=pii.Vault())
    assert store._meta(state)['facts_used']==native_used(state)==['room_area_m2']


@pytest.mark.asyncio
async def test_citation_of_unsaid_overflow_sentence_is_not_credited():
    from ai_agent_service.pipeline.hot.nodes import _Attempt,_offer,lines_used
    from ai_agent_service.pipeline.hot.state import HotContext
    attempt=_Attempt(said=['Một câu.','Hai câu.','Ba câu.'],last_spoken=True)
    timing={'first_token_ms':None,'filler_ms':None}
    assert await _offer({},HotContext(),'Thêm một câu nữa.',(),attempt,timing)
    assert await _offer({},HotContext(),'[B5]',(),attempt,timing)
    assert lines_used(' '.join(attempt.said))==[]
