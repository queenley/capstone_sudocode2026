"""Memory integrity across tools, ledger, recall and brief; no provider calls."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.agents.memory import from_tools
from ai_agent_service.components.memory import brief, gate, ontology, recall
from ai_agent_service.pipeline.cold.after_call import plan_writes, _remember
from ai_agent_service.pipeline.hot import nodes
from ai_agent_service.pipeline.hot.state import HotContext


def tool(name, turn, args, data):
    return {'name':name,'turn':turn,'args':args,'result':{'ok':True,'data':data}}


def quote(sku, price, turn, promo=None):
    return tool('pricing.get_quote',turn,{'sku':sku},{'sku':sku,'final_price_vnd':price,
        'applied_promos':([{'promo_code':promo,'type':'discount','end':'2026-10-31'}] if promo else [])})


def values(log):
    return {c.slot:c.value for c in gate.settle(from_tools(log,on='2026-10-22'))}


def fact(slot,value):
    return {'slot':slot,'value':value,'status':'active','fact_id':'fact-'+slot,'kind':ontology.slot(slot).kind}


def test_quote_fields_cannot_be_joined_across_products():
    got=values([quote('SKU-AP-Y',5200000,1),quote('SKU-XM-4P',5490000,2,'XM-COMBO')])
    assert got['product_advised']=='SKU-AP-Y'
    assert got['price_quoted_vnd']==5200000
    assert 'promo_code' not in got
    assert got['alt_suggested']=='SKU-XM-4P'


def test_primary_order_uses_its_quote_and_keeps_every_created_order():
    log=[quote('SKU-AP-PRO',7990000,1),quote('SKU-AP-FLT-P',690000,2)]
    log += [tool('order.create',3,{'sku':'SKU-AP-PRO','price_vnd':7990000,'payment':'bank'}, {'order_id':'ORDER-A'}),
            tool('order.create',3,{'sku':'SKU-AP-FLT-P','price_vnd':690000,'payment':'bank'}, {'order_id':'ORDER-B'})]
    got=values(log)
    assert got['product_advised']=='SKU-AP-FLT-P'
    assert got['price_quoted_vnd']==690000
    assert got['order_ids']==['ORDER-A','ORDER-B']
    assert got['order_id']=='ORDER-B'


def test_variants_and_promotions_follow_selected_quote():
    got=values([quote('SKU-SN-RUN1-42-DEN',1000000,1),quote('SKU-SN-RUN2-43-DEN',1740000,2,'RUN-10')])
    assert got['product_advised']=='SKU-SN-RUN1'
    assert got['variant_sku']=='SKU-SN-RUN1-42-DEN'
    assert got['size']==42
    assert got['price_quoted_vnd']==1000000
    assert 'promo_code' not in got


def test_no_promotion_snapshot_invalidates_previous_promo_and_keeps_history():
    old=[fact('promo_code','OLD-PROMO'),fact('promo_expiry','2026-10-31')]
    decisions=plan_writes(from_tools([quote('SKU-AP-Y',5200000,2)],on='2026-10-22'),old,
                          source={'call_id':'fixture','call':'call_2'},on='2026-10-22')
    cleared={d.slot:d for d in decisions if d.operation=='invalidate'}
    assert set(cleared)=={'promo_code','promo_expiry'}
    assert cleared['promo_code'].replaces=='fact-promo_code'
    assert cleared['promo_code'].source['said_by']=='tool'


def test_order_history_unions_across_calls():
    old=[fact('order_ids',['ORDER-A'])]
    candidates=from_tools([tool('order.create',1,{'sku':'SKU-AP-Y','price_vnd':5200000},
                               {'order_id':'ORDER-B'})],on='2026-10-22')
    decisions=plan_writes(candidates,old,source={'call_id':'fixture'},on='2026-10-22')
    assert next(d.value for d in decisions if d.slot=='order_ids')==['ORDER-A','ORDER-B']


@pytest.mark.asyncio
async def test_recall_uses_persisted_order_ids_even_when_crm_has_no_orders():
    tools=SimpleNamespace(data=AsyncMock(side_effect=[{'facts':[fact('order_ids',['ORDER-A','ORDER-B'])]},
                                                     {'episodes':[]}]))
    found=await recall.retrieve('C-FIXTURE','2026-10-22',tools,crm={},memory_on=True)
    assert {o['order_id'] for o in found['orders']}=={'ORDER-A','ORDER-B'}


@pytest.mark.asyncio
async def test_baseline_still_reads_no_previous_memory():
    tools=SimpleNamespace(data=AsyncMock())
    assert await recall.retrieve('C-FIXTURE','2026-10-22',tools,crm={},memory_on=False)=={
        'facts':[],'orders':[],'episodes':[]}
    tools.data.assert_not_awaited()


@pytest.mark.asyncio
async def test_unconfirmed_ledger_identity_is_not_a_verified_match():
    from ai_agent_service.components.identity.resolver import make_key
    tools=SimpleNamespace(data=AsyncMock(side_effect=[{'found':False}, {'matches':[
        {'customer_id':'C-OTHER','status':'provisional'}]}]))
    result=await nodes._look_up([make_key('phone','0900000001','fixture',from_connection=True)],
                                HotContext(harness=tools))
    assert result[0]==[]


@pytest.mark.asyncio
async def test_new_number_mentioned_after_verification_is_not_linked_to_customer():
    from ai_agent_service.components.identity.resolver import make_key
    ctx=HotContext(identity_secret='fixture')
    original=make_key('phone','0900000001','fixture',from_connection=True)
    token=ctx.vault.put('PHONE','0900000002')
    state={'call_id':'fixture','tier':'VERIFIED','customer_id':'C-FIXTURE',
           'keys_seen':[{'kind':original.kind,'digest':original.digest,'last4':original.last4,
                         'from_connection':True}],
           'flags':{'new_key':True,'new_phone_tokens':[token]}}
    update=await nodes._identify(state,ctx)
    assert len(update.get('keys_seen',state['keys_seen']))==1


def test_low_confidence_late_candidate_does_not_erase_valid_earlier_fact():
    candidates=[gate.Candidate('budget_vnd',5000000,'customer',1),
                gate.Candidate('budget_vnd',500,'customer',2,confidence=0.1)]
    decisions=plan_writes(candidates,[],source={'call_id':'fixture'},on='2026-10-22')
    assert next(d.value for d in decisions if d.slot=='budget_vnd')==5000000


def test_customer_preference_wins_over_agent_suggestion_in_same_call():
    got={c.slot:c.value for c in gate.settle([gate.Candidate('size',42,'customer',1),
                                            gate.Candidate('size',43,'agent',2)])}
    assert got['size']==42


def test_full_customer_name_matches_at_word_boundaries():
    from ai_agent_service.components.identity.resolver import Match,pick_by_name
    candidates=[Match('C-1','Nguyễn Thị Hoa'),Match('C-2','Nguyễn Thị Hoàng')]
    assert pick_by_name('Tôi là Nguyễn Thị Hoa',candidates)==candidates[0]


@pytest.mark.asyncio
async def test_spoken_key_does_not_inherit_unrelated_connection_trust():
    ctx=HotContext(identity_secret='fixture',caller_phone='0900000001')
    token=ctx.vault.put('PHONE','0900000002')
    ctx.harness=SimpleNamespace(data=AsyncMock(side_effect=[{'found':False},{'matches':[]},
        {'found':True,'customer_id':'C-OTHER','name':'Hoa'}, {'matches':[]}]),call=AsyncMock())
    state={'call_id':'fixture','on':'2026-10-22','now':datetime.now(timezone.utc),'tier':'UNKNOWN',
           'flags':{'new_key':True,'new_phone_tokens':[token]}}
    # Rendering is independent of identity trust and has its own tests.
    from unittest.mock import patch
    with patch.object(nodes,'_brief',AsyncMock(return_value={})):
        update=await nodes._identify(state,ctx)
    assert update['tier']=='PROBABLE'
    assert update['customer_id']=='C-OTHER'
    assert len(ctx.harness.call.await_args_list)==1


@pytest.mark.asyncio
async def test_only_keys_that_match_settled_customer_are_confirmed():
    writer=SimpleNamespace(data=AsyncMock(side_effect=[{'customer_id':'C-1'}, {'facts':[]}, {'episodes':[]},
                                                      {'memory_writes':[]}, {}]))
    memory=SimpleNamespace(summarize=AsyncMock(return_value={'summary':'fixture'}))
    await _remember({'call_id':'fixture','tier':'VERIFIED','customer_id':'C-1','on':'2026-10-22',
        'keys_seen':[{'kind':'phone','digest':'own','customer_ids':['C-1']},
                     {'kind':'phone','digest':'other','customer_ids':['C-2']},
                     {'kind':'phone','digest':'unmatched','customer_ids':[]}]},[],writer=writer,memory=memory)
    args=writer.data.await_args_list[0]
    assert args.args==('memory_confirm_identity',)
    assert args.kwargs['keys']==[{'key_type':'phone','key_hash':'own'}]


def test_legacy_price_without_sku_link_is_not_claimed_as_product_history():
    products=recall.advised([fact('product_advised','SKU-AP-Y'),fact('price_quoted_vnd',5490000)],[])
    assert products[0]['price_quoted_vnd'] is None
    assert products[0]['quote_unlinked'] is True


def test_new_quote_price_has_explicit_product_link():
    candidates=from_tools([quote('SKU-AP-Y',5200000,1)],on='2026-10-22')
    products=recall.advised([fact(c.slot,c.value) for c in candidates if c.slot],[])
    assert products[0]['price_quoted_vnd']==5200000
    assert products[0]['quote_unlinked'] is False


@pytest.mark.asyncio
async def test_store_merges_order_history_again_under_customer_lock(monkeypatch):
    from ai_agent_service.mcp.servers import memory as store
    from datetime import date
    import json
    monkeypatch.setattr(store,'_already',AsyncMock(return_value=False))
    cursor=SimpleNamespace(fetchone=AsyncMock(return_value={'fact_id':'previous','value':['ORDER-A']}))
    conn=SimpleNamespace(execute=AsyncMock(return_value=cursor))
    decision={'operation':'update','slot':'order_ids','value':['ORDER-B'],'kind':'past_event',
              'source':{'call_id':'fixture','turn':1,'extractor_version':'fixture'}}
    result=await store._apply(conn,'C-1',decision,date(2026,10,22))
    assert result['value']==['ORDER-A','ORDER-B']
    insert=next(args for args in conn.execute.await_args_list if args.args[0].startswith('INSERT'))
    assert json.loads(insert.args[1][3])==['ORDER-A','ORDER-B']


def test_exchange_uses_new_variant_quote_without_mixing_original_price():
    log=[quote('SKU-SN-RUN1-42-DEN',1000000,1),quote('SKU-SN-RUN2-43-DEN',1740000,2),
         tool('order.update',3,{'order_id':'ORDER-A','action':'exchange_product',
              'new_variant_sku':'SKU-SN-RUN2-43-DEN'}, {'status':'pickup_scheduled'})]
    got=values(log)
    assert got['product_advised']=='SKU-SN-RUN2'
    assert got['variant_sku']=='SKU-SN-RUN2-43-DEN'
    assert got['price_quoted_vnd']==1740000


def test_quote_after_order_does_not_rewrite_price_of_completed_order():
    log=[quote('SKU-AP-Y',5200000,1),tool('order.create',2,{'sku':'SKU-AP-Y','price_vnd':5200000},
         {'order_id':'ORDER-A'}),quote('SKU-AP-Y',5000000,3)]
    assert values(log)['price_quoted_vnd']==5200000


@pytest.mark.asyncio
async def test_model_opinion_cannot_promote_unconfirmed_identity_for_memory_write():
    from ai_agent_service.pipeline.cold.after_call import _settle_identity
    writer=SimpleNamespace(data=AsyncMock(return_value={'facts':[]}))
    memory=SimpleNamespace(same_person=AsyncMock(return_value=True))
    call={'tier':'PROBABLE','customer_id':'C-OTHER','on':'2026-10-22','call_id':'fixture',
          'provisional':{'customer_id':'C-OTHER','name':'Hoa'}}
    settled=_settle_identity(call)
    assert settled['tier']!='VERIFIED'
    memory.same_person.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_deletion_does_not_depend_on_extraction_model():
    from ai_agent_service.pipeline.cold.after_call import after_call
    memory=SimpleNamespace(extract=AsyncMock(side_effect=RuntimeError('model must not be called')))
    admin_tools=SimpleNamespace(data=AsyncMock(return_value={'deleted':True}))
    admin=AsyncMock(return_value=admin_tools)
    qa=SimpleNamespace(tag=AsyncMock(return_value={}),score=AsyncMock(return_value={}))
    result=await after_call({'call_id':'fixture','tier':'VERIFIED','customer_id':'C-1','on':'2026-10-22'},
        [],[tool('memory.request_deletion',1,{}, {})],writer=SimpleNamespace(),memory=memory,qa=qa,admin=admin)
    assert result['status']=='deleted'
    memory.extract.assert_not_awaited()
    admin_tools.data.assert_awaited_once_with('memory_delete_customer',customer_id='C-1')


def test_word_extraction_cannot_write_raw_phone_into_open_note():
    candidate=gate.Candidate(None,'Liên hệ số 0900000001','customer',1)
    assert not gate.check(candidate,[],open_notes=0).passed


@pytest.mark.asyncio
async def test_new_profile_does_not_bind_every_number_mentioned_in_call():
    writer=SimpleNamespace(data=AsyncMock(side_effect=[{'customer_id':'NEW-1'}, {'facts':[]}, {'episodes':[]},
                                                      {'memory_writes':[]}, {}]))
    memory=SimpleNamespace(summarize=AsyncMock(return_value={'summary':'fixture'}))
    await _remember({'call_id':'fixture','tier':'UNKNOWN','on':'2026-10-22','keys_seen':[
        {'kind':'phone','digest':'caller','from_connection':True,'customer_ids':[]},
        {'kind':'phone','digest':'gift-recipient','from_connection':False,'customer_ids':[]}]},
        [],writer=writer,memory=memory)
    assert writer.data.await_args_list[0].kwargs['keys']==[{'key_type':'phone','key_hash':'caller'}]


@pytest.mark.parametrize('text',['Tôi là chồng của Nguyễn Thị Hoa','Tôi gọi hộ Nguyễn Thị Hoa',
                                 'Không phải Nguyễn Thị Hoa'])
def test_mentioning_another_person_is_not_self_identification(text):
    from ai_agent_service.components.identity.resolver import Match,pick_by_name
    assert pick_by_name(text,[Match('C-1','Nguyễn Thị Hoa')]) is None


@pytest.mark.asyncio
async def test_denied_identity_does_not_keep_other_persons_phone_for_writes():
    state={'tier':'PROBABLE','customer_id':'C-OTHER','customer_name':'Hoa','awaiting':'confirm',
           'phone_token':'<PHONE_1>','quotes':{'SKU-AP-Y':5200000}}
    update=await nodes._settle(state,HotContext(),'Không phải chị Hoa')
    assert update['tier']=='UNKNOWN'
    assert update['phone_token'] is None
    assert update['quotes']=={}


@pytest.mark.asyncio
@pytest.mark.parametrize('speaker',['agent','human_agent'])
async def test_commitment_provenance_accepts_assistant_or_staff_actual_turn(speaker):
    from ai_agent_service.agents.memory import MemoryAgent,CallMemory,Observation
    memory=MemoryAgent(use_model=False)
    memory._labeller=SimpleNamespace(ainvoke=AsyncMock(return_value=CallMemory(observations=[
        Observation(slot='commitments',value='Gọi lại lúc 10 giờ',said_by='agent',turn=2,confidence=1)])))
    result=await memory._from_words([{'speaker':'customer','turn':1,'text':'Gọi lại giúp chị'},
                                    {'speaker':speaker,'turn':2,'text':'Em sẽ gọi lại lúc 10 giờ ạ.'}])
    assert next(c.value for c in result if c.slot=='commitments')=='Gọi lại lúc 10 giờ'


@pytest.mark.asyncio
async def test_a_probable_caller_s_words_are_kept_unconfirmed_for_the_number_s_owner():
    from ai_agent_service.pipeline.cold.after_call import after_call
    writer=SimpleNamespace(data=AsyncMock(side_effect=lambda name, **kw: {'facts':[]} if name=='memory_get_profile' else {'memory_writes':[]}))
    memory=SimpleNamespace(extract=AsyncMock(return_value=from_tools([quote('SKU-T-1',990000,1,'PROMO-T')],on='2026-10-15')))
    qa=SimpleNamespace(tag=AsyncMock(return_value={}))
    call={'tier':'PROBABLE','customer_id':'C-T','on':'2026-10-15','call_id':'chat-1','channel':'zalo',
          'provisional':{'customer_id':'C-T','name':'Mai'},'keys_seen':[]}
    result=await after_call(call,[],[],writer=writer,memory=memory,qa=qa)
    assert result['status']=='unconfirmed' and result['customer_id']=='C-T' and result['memory_writes']==[]
    commit=[c for c in writer.data.await_args_list if c.args[0]=='memory_commit_facts'][0]
    assert commit.kwargs['customer_id']=='C-T'
    assert all(d['unconfirmed'] and d['operation']=='add' for d in commit.kwargs['decisions'])
    assert {d['slot'] for d in commit.kwargs['decisions']} >= {'product_advised','price_quoted_vnd'}
    assert not any(c.args[0] in ('memory_commit_episode','memory_confirm_identity') for c in writer.data.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize('said, confirm', [
    ('Alo em, hôm qua chị có nhắn hỏi về cái quạt đó.', True),
    ('Không phải chị đâu em, chị không nhắn gì cả.', False),
    ('Chắc nhầm số rồi em ơi.', False),
])
async def test_the_owner_s_own_call_settles_what_was_kept_unconfirmed(said, confirm):
    from ai_agent_service.pipeline.cold import after_call as module
    writer=SimpleNamespace(data=AsyncMock(return_value={'facts':[],'episodes':[],'customer_id':'C-T','memory_writes':[]}))
    memory=SimpleNamespace(extract=AsyncMock(return_value=[]),
                           summarize=AsyncMock(return_value={'summary':'s','outcome':'khac'}))
    qa=SimpleNamespace(tag=AsyncMock(return_value={}))
    call={'tier':'VERIFIED','customer_id':'C-T','on':'2026-10-16','call_id':'hot-1','channel':'hotline','keys_seen':[]}
    await module.after_call(call,[{'speaker':'customer','text':said,'turn':1}],[],writer=writer,memory=memory,qa=qa)
    settle=[c for c in writer.data.await_args_list if c.args[0]=='memory_settle_unconfirmed']
    assert len(settle)==1 and settle[0].kwargs['confirm'] is confirm


def test_the_brief_shows_unconfirmed_facts_as_a_question_and_counts_them_when_cited():
    unconfirmed={'slot':'product_advised','value':'SKU-T-1','status':'unconfirmed','fact_id':'F-u1','kind':'past_event',
                 'valid_from':'2026-10-15','source':{'channel':'zalo'}}
    data,lines=brief.render(customer={'customer_id':'C-T','name':'Mai','honorific':'chị'},facts=[unconfirmed],
                            episodes=[],orders=[],products=[],warnings=[],now=datetime(2026,10,16,10,tzinfo=timezone.utc),latency_ms=1)
    line=next(l for l in lines if l.text.startswith('Chưa xác nhận'))
    assert 'SKU-T-1' in line.text and line.fact_ids==('F-u1',) and data['is_returning']
    assert brief.used_slots([line.id],[l.as_dict() for l in lines],data['profile_facts'])==['product_advised']



def test_the_brief_shows_the_delivery_area_and_the_product_the_customer_owns():
    facts=[fact('delivery_area','quận 7'),fact('owned_sku','SKU-AP-X')]
    data,lines=brief.render(customer={'customer_id':'C-T','name':'Mai','honorific':'chị'},facts=facts,
                            episodes=[],orders=[],products=[],warnings=[],now=datetime(2026,10,16,10,tzinfo=timezone.utc),latency_ms=1)
    area=next(l for l in lines if 'quận 7' in l.text)
    owned=next(l for l in lines if 'SKU-AP-X' in l.text)
    assert area.fact_ids==('fact-delivery_area',) and owned.fact_ids==('fact-owned_sku',)
    assert brief.used_slots([area.id,owned.id],[l.as_dict() for l in lines],data['profile_facts'])==['delivery_area','owned_sku']

@pytest.mark.parametrize('slot_name, value, lapses', [
    ('address_token', '<ADDR_1>', '2027-04-13'),     # 180 days: an address may have changed
    ('blocker', 'cần hỏi chồng', '2026-11-14'),        # 30 days: a pending matter goes stale
    ('room_area_m2', 25, None),                        # a need never lapses
])
def test_each_slot_lapses_after_its_ttl(slot_name, value, lapses):
    candidate=gate.Candidate(slot_name,value,'customer',1)
    decisions=plan_writes([candidate],[],source={'call_id':'c1','call':'call_1'},on='2026-10-15')
    assert [d.valid_to for d in decisions]==[lapses]


@pytest.mark.asyncio
@pytest.mark.parametrize('last_contact, warned', [('2026-03-01', True), ('2026-08-01', False)])
async def test_a_contact_older_than_six_months_warns_the_agent_to_ask_again(last_contact, warned):
    tools=SimpleNamespace(data=AsyncMock(return_value={}))
    _, _, warnings=await recall.refresh([],[],[{'date':last_contact,'channel':'hotline'}],'2026-10-15',tools,customer_phone=None)
    assert any('hơn 6 tháng' in w for w in warnings) is warned


@pytest.mark.asyncio
async def test_forgetting_a_customer_also_clears_their_conversation_log(monkeypatch):
    from contextlib import asynccontextmanager
    from ai_agent_service.mcp.servers import memory as store
    executed=[]

    class Cursor:
        rowcount=1
        def __init__(self, sql): self.sql = sql
        async def fetchone(self):return {'t':'present'}
        async def fetchall(self):
            if self.sql.startswith('SELECT id, turn_lease'): return [{'id': 1, 'busy': False}]
            if self.sql.startswith('SELECT value_enc'): return []
            return [{'request_id':'D-1'}]

    class Conn:
        async def execute(self,sql,params=()):
            executed.append(' '.join(sql.split()));return Cursor(sql)
        @asynccontextmanager
        async def transaction(self):yield

    class Pool:
        @asynccontextmanager
        async def connection(self):yield Conn()

    monkeypatch.setattr(store,'database',AsyncMock(return_value=Pool()))
    fn=getattr(store.memory_delete_customer,'fn',store.memory_delete_customer)
    result=await fn(customer_id='C-T')
    assert {'facts','episodes','identities','pii_vault','turns','calls_unlinked'}<=set(result['deleted'])
    assert any(s.startswith('DELETE FROM turns WHERE call_id = ANY') for s in executed)
    assert any(s.startswith('UPDATE calls SET customer_id = NULL') for s in executed)
