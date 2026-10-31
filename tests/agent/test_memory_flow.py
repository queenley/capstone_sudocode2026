"""One offline flow across cold memory, recall, the hot graph, guard and trace."""
from datetime import datetime,timezone
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from ai_agent_service.agents.advisor import AdvisorAgent
from ai_agent_service.agents.memory import MemoryAgent
from ai_agent_service.components.memory import recall
from ai_agent_service.components.intake import pii
from ai_agent_service.pipeline.cold.after_call import plan_writes
from ai_agent_service.pipeline.hot.graph import build_graph
from ai_agent_service.pipeline.hot.state import HotContext
from ai_agent_service.pipeline.eval.trace import facts_used,schema_errors,turn_row
from ai_agent_service.runtime.harness import CallStore


@pytest.mark.asyncio
async def test_previous_call_facts_reach_model_guard_and_both_trace_paths_without_pii():
    transcript=[{'speaker':'customer','turn':1,'text':'Phòng 25 m², ngân sách 6 triệu, không có trẻ nhỏ.'}]
    tools=[{'name':'pricing.get_quote','turn':1,'args':{'sku':'SKU-AP-Y'},'result':{'ok':True,'data':{
        'sku':'SKU-AP-Y','final_price_vnd':5200000,'applied_promos':[]}}}]
    candidates=await MemoryAgent(use_model=False).extract(transcript,tools,on='2026-10-21')
    decisions=plan_writes(candidates,[],source={'call_id':'previous','call':'call_1'},on='2026-10-21')
    facts=[{'slot':d.slot,'value':d.value,'fact_id':'fact-'+d.slot,'status':'active','source':d.source,
            'kind':d.kind} for d in decisions]
    assert recall.advised(facts,[])[0]['price_quoted_vnd']==5200000
    read=[]

    class Harness:
        async def data(self,name,**kwargs):
            read.append((name,kwargs))
            if name=='crm_get_customer':
                return {'found':True,'customer_id':'C-FIXTURE','name':'Hoa','honorific':'chị',
                        'phone':'0900000001','orders':[],'sessions':[]}
            if name=='identity_find':return {'matches':[]}
            if name=='memory_get_profile':return {'facts':facts}
            if name=='memory_get_episodes':return {'episodes':[{'call_id':'previous','date':'2026-10-21',
                'channel':'web','summary':'Đã tư vấn máy lọc không khí','outcome':'khac'}]}
            if name=='pricing_get_quote':return {'sku':'SKU-AP-Y','final_price_vnd':5200000,'applied_promos':[]}
            if name=='inventory_check':return {'in_stock':True}
            if name=='catalog_search':return {'items':[{'sku':'SKU-AP-Y','name':'AirPure Y'}]}
            if name=='kb_search':return {'hits':[],'abstain':True}
            raise AssertionError(name)

    class Model(FakeMessagesListChatModel):
        def bind_tools(self,tools,**kwargs):return self

    # Actual graph context decides the brief IDs; the scripted reply cites its room fact.
    class ReplyAdvisor(AdvisorAgent):
        async def stream(self,messages,context,**kwargs):
            room=next(line.id for line in context.brief_lines if 'fact-room_area_m2' in line.fact_ids)
            self.llm.responses=[AIMessage(content=f'Dạ phòng mình vẫn 25 m² đúng không ạ? [{room}]')]
            async for event in super().stream(messages,context,**kwargs):yield event

    agent=ReplyAdvisor(llm=Model(responses=[AIMessage(content='unused')]),tools=[],retries=0)
    vault=pii.Vault()
    context=HotContext(text='Chị gọi tiếp chuyện hôm trước.',caller_phone='0900000001',identity_secret='fixture',
                       vault=vault,harness=Harness(),advisor=agent)
    graph=build_graph(checkpointer=InMemorySaver())
    state=await graph.ainvoke({'call_id':'current','turn_id':'turn-1','turn_no':1,'channel':'web',
        'on':'2026-10-22','now':datetime(2026,10,22,tzinfo=timezone.utc),'switches':{'memory':True}},
        context=context,config={'configurable':{'thread_id':'fixture'}})
    assert state['tier']=='VERIFIED' and state['lane']=='CONTINUITY'
    assert state['guard']['passed']
    assert state['reply']['text']=='Dạ phòng mình vẫn 25 m² đúng không ạ?'
    assert facts_used(state)==['room_area_m2']
    assert CallStore(1,vault)._meta(state)['facts_used']==['room_area_m2']
    assert any(name=='memory_get_profile' for name,_ in read)
    import json
    assert '0900000001' not in json.dumps(state,default=str,ensure_ascii=False)
    row=turn_row(run_id='fixture',config='full',scenario_id='FIXTURE',call='call_2',turn=1,
        customer_text='fixture',state=state,vault=vault,total_ms=1,first_token_ms=1,input_mode='clean')
    assert schema_errors(row)==[]
    assert row['facts_used']==['room_area_m2']


@pytest.mark.asyncio
@pytest.mark.parametrize('lines,outcome',[
    (['Chị cần xem xét rồi sẽ gọi lại sau nhé.'],'hen_goi_lai'),
    (['Hết hàng à? Thôi khỏi em, chị không lấy nữa.'],'tu_choi'),
    (['Thôi để chị xem lại.'],'tu_choi'),
    (['Để chị gọi lại sau.','Thôi chị không mua nữa đâu.'],'tu_choi'),
    (['Thôi không mua đâu.','À mà em gọi lại cho chị tuần sau nhé.'],'hen_goi_lai'),
    (['Thôi chị gọi lại sau.'],'hen_goi_lai'),
    (['Máy này giá bao nhiêu em?'],None),
    (['Thôi không sao em, giao chậm cũng được.'],None),
])
async def test_outcome_from_the_customers_last_word(lines,outcome):
    transcript=[{'speaker':'customer','turn':n,'text':text} for n,text in enumerate(lines,1)]
    found={c.slot:c.value for c in await MemoryAgent(use_model=False).extract(transcript,[],on='2026-10-21')}
    assert found.get('outcome')==outcome


@pytest.mark.asyncio
async def test_a_tool_outcome_wins_over_words():
    transcript=[{'speaker':'customer','turn':1,'text':'Thôi khỏi.'},{'speaker':'customer','turn':2,'text':'À thôi lên đơn cho chị.'}]
    tools=[{'name':'order.create','turn':2,'args':{'sku':'SKU-AP-Y'},'result':{'ok':True,'data':{'order_id':'OD1'}}}]
    found={c.slot:c.value for c in await MemoryAgent(use_model=False).extract(transcript,tools,on='2026-10-21')}
    assert found['outcome']=='chot_don'
