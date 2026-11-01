"""Synthetic erasure regressions. Provider calls are forbidden by conftest."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.components.improvement import gaps, signals
from ai_agent_service.components.memory import recall

RECORDED = {'status': 'recorded', 'request_id': 'D-000000000001', 'deleted_within_hours': 72}


@pytest.mark.asyncio
async def test_erasure_removes_feedback_and_blocks_delayed_feedback():
    await signals.record('consultant', call_id='1', turn_id='t1', value={'note': 'private blocker'})
    await signals.record('consultant', call_id='2', turn_id='t2', value={'note': 'other owner'})
    key = gaps.record('private question', call_id='1', turn_id='t1')
    proposal = signals.home() / 'regression-proposals' / f'{key}.json'
    proposal.parent.mkdir(parents=True)
    proposal.write_text(json.dumps({'question': 'private question'}))
    gaps.forget_calls([1])
    await signals.record('consultant', call_id='1', turn_id='late', value={'note': 'private blocker'})
    assert [row['call_id'] for row in signals.read()] == ['2']
    assert gaps.record('private question', call_id='1', turn_id='late') is None
    assert not gaps.list_gaps() and not proposal.exists()


@pytest.mark.asyncio
async def test_confirmed_pending_deletion_suppresses_recall_before_cleanup():
    tools = SimpleNamespace(data=AsyncMock(side_effect=[
        {'facts': [{'slot': 'blocker', 'value': 'private blocker'}], 'deletion_pending': True},
        {'episodes': [{'summary': 'private episode'}]},
    ]))
    found = await recall.retrieve('C-SYNTHETIC', '2026-11-01', tools,
        crm={'sessions': [{'summary': 'old CRM history'}], 'orders': [{'order_id': 'OLD'}]}, memory_on=True)
    assert found == {'facts': [], 'episodes': [], 'orders': [], 'forgotten': True}


@pytest.mark.asyncio
async def test_eval_stops_before_another_turn_or_after_call_after_invocation_error(monkeypatch):
    from ai_agent_service.pipeline.eval import runner
    session = SimpleNamespace(turn_no=1, vault=SimpleNamespace(),
        connect=AsyncMock(return_value=SimpleNamespace(brief_ms=None)),
        turn=AsyncMock(return_value=SimpleNamespace(state={}, error='AuthenticationError: synthetic',
            usage={}, total_ms=1, first_token_ms=None)), hang_up=AsyncMock(return_value={'status': 'done'}))
    monkeypatch.setattr(runner.CallSession, 'for_plan', lambda *args, **kwargs: session)
    monkeypatch.setattr(runner.trace, 'turn_row', lambda **kwargs: {'call': 'call_1', 'tool_calls': []})
    run = runner.ScenarioRun()
    plan = SimpleNamespace(name='call_1', turns=['one', 'two'], trace_input_mode='clean')
    await runner._run_call(SimpleNamespace(), SimpleNamespace(scenario_id='SYNTHETIC'), plan, 'full',
        run=run, run_id='synthetic', progress=lambda _: None)
    assert run.error and 'AuthenticationError' in run.error
    assert session.turn.await_count == 1
    session.hang_up.assert_not_awaited()


@pytest.mark.asyncio
async def test_eval_cli_saves_failed_trace_without_labelling_or_starting_baseline(monkeypatch, tmp_path):
    from ai_agent_service.pipeline.eval import cli, runner, scenarios, report
    from ai_agent_service.mcp import client
    from ai_agent_service.llm import jev
    args = cli.parser().parse_args(['--scenarios', str(tmp_path), '--warmup', '0'])
    import json
    for sid in ('SYNTHETIC-1', 'SYNTHETIC-2'):
        (tmp_path / f'{sid}.json').write_text(json.dumps({'scenario_id': sid,
            'calls': {'call_1': {'customer_turns': ['Synthetic request']}}}))
    monkeypatch.setattr(runner, 'build', AsyncMock(return_value=SimpleNamespace(provider='fake',
        advisor=SimpleNamespace(model_name='fake'))))
    monkeypatch.setattr(runner, 'warm_up', AsyncMock())
    monkeypatch.setattr(runner, 'run_scenario', AsyncMock(return_value=runner.ScenarioRun(error='AuthenticationError: synthetic')))
    monkeypatch.setattr(cli, '_extractor', lambda: SimpleNamespace(model_name='fake', stats=lambda: {}))
    monkeypatch.setattr(cli, '_label', AsyncMock())
    monkeypatch.setattr(report, 'manifest', lambda **kwargs: {})
    monkeypatch.setattr(client, 'close_all', AsyncMock())
    monkeypatch.setattr(jev, 'close', AsyncMock())
    layout = cli.Layout(tmp_path, {'full': tmp_path/'full.jsonl', 'baseline_no_memory': tmp_path/'baseline.jsonl'})
    assert await cli._evaluate(args, run_id='synthetic', layout=layout, database='synthetic_eval') == 1
    runner.run_scenario.assert_awaited_once()
    cli._label.assert_not_awaited()
    assert (tmp_path/'full.jsonl').exists() and not (tmp_path/'baseline.jsonl').exists()


@pytest.mark.parametrize('tier,asked,said,allowed', [
    ('UNKNOWN', 'Anh/chị xác nhận xóa dữ liệu?', 'Đồng ý', False),
    ('PROBABLE', 'Anh/chị xác nhận xóa dữ liệu?', 'Đồng ý', False),
    ('AMBIGUOUS', 'Anh/chị xác nhận xóa dữ liệu?', 'Đồng ý', False),
    ('VERIFIED', None, 'Đồng ý', False),
    ('VERIFIED', 'Anh/chị xác nhận xóa dữ liệu?', 'Không đồng ý', False),
    ('VERIFIED', 'Anh/chị xác nhận xóa dữ liệu?', 'Đồng ý', True),
])
def test_deletion_needs_verified_owner_and_explicit_confirmation(tier, asked, said, allowed):
    from ai_agent_service.components.guardrails.actions import check
    result = check('memory_request_deletion', {}, tier=tier, mode='speak', has_phone=True,
        quotes={}, last_agent_said=asked, customer_said=said)
    assert result.passed is allowed


@pytest.mark.asyncio
async def test_eval_stops_labelling_after_extractor_invocation_failure(monkeypatch):
    from ai_agent_service.pipeline.eval import cli
    monkeypatch.setenv('EVAL_BUDGET_DB', 'unused-by-injected-fake')
    rows = [{'config': 'full', 'scenario_id': 'SYNTHETIC', 'call': 'call_1', 'turn': i,
             'agent_text': 'Synthetic answer.', 'customer_text': 'Synthetic input.',
             'tool_calls': [], 'facts_used': []} for i in (1, 2)]
    extractor = SimpleNamespace(label=AsyncMock(return_value={'questions': [], 'claims': [], 'facts_used': [],
        'items': [], 'dropped': 0, 'changed': 0, 'error': 'AuthenticationError: synthetic'}), stats=lambda: {})
    run = cli.ConfigRun(rows=rows, diagnostics=[{}, {}])
    await cli._label(run, extractor)
    assert extractor.label.await_count == 1 and run.stopped


@pytest.mark.parametrize('acknowledgement', [
    'Dạ em đã ghi nhận yêu cầu xóa dữ liệu của chị rồi ạ.',
    'Em ghi nhận yêu cầu xóa dữ liệu của chị rồi ạ.',
    'Yêu cầu xóa dữ liệu của chị đã được ghi nhận ạ.',
    'Dạ em đã xóa toàn bộ dữ liệu của chị rồi ạ.',
    'Dữ liệu của chị đã được xóa rồi ạ.',
])
def test_deletion_acknowledgement_requires_the_actual_effect(acknowledgement):
    from ai_agent_service.components.guardrails.hard import GuardInput, check
    assert not check(GuardInput(acknowledgement, (), 'VERIFIED')).passed
    failed = ({'name': 'memory.request_deletion', 'result': {'ok': False, 'error': {'code': 'PRECONDITION'}}},)
    assert not check(GuardInput(acknowledgement, failed, 'VERIFIED')).passed


def test_recorded_request_can_be_acknowledged_but_cannot_be_claimed_as_erased():
    from ai_agent_service.components.guardrails.hard import GuardInput, check
    success = ({'name': 'memory.request_deletion', 'result': {'ok': True, 'data': RECORDED}},)
    assert check(GuardInput('Dạ em đã ghi nhận yêu cầu xóa dữ liệu của chị rồi ạ.', success, 'VERIFIED')).passed
    assert not check(GuardInput('Dạ em đã xóa toàn bộ dữ liệu của chị rồi ạ.', success, 'VERIFIED')).passed


@pytest.mark.asyncio
@pytest.mark.parametrize('middle,owner,confirmation,allowed', [
    ('Đây là số CCCD: <ID_1>.', 'C-OWN', 'Chị đồng ý xóa dữ liệu của mình.', True),
    ('Không, chị không muốn xóa nữa.', 'C-OWN', 'Chị đồng ý xóa dữ liệu của mình.', False),
    ('Đồng ý xóa giúp chị.', 'C-OWN', 'Chị đồng ý xóa dữ liệu của mình.', False),
    ('Đây là số CCCD: <ID_1>.', 'C-OTHER', 'Chị đồng ý xóa dữ liệu của mình.', False),
    ('Đây là số CCCD: <ID_1>.', 'C-OWN', 'Vâng, cho chị xem mẫu khác.', False),
])
async def test_deletion_confirmation_survives_an_intervening_id_turn_but_not_cancellation(middle, owner, confirmation, allowed):
    from datetime import datetime, timezone
    from langchain_core.messages import HumanMessage, AIMessage
    from ai_agent_service.pipeline.hot import nodes
    from ai_agent_service.pipeline.hot.state import HotContext
    from ai_agent_service.components.guardrails.actions import check
    state = {'call_id': 'synthetic', 'tier': 'VERIFIED', 'customer_id': 'C-OWN',
        'now': datetime(2026,11,1,tzinfo=timezone.utc), 'on': '2026-11-01',
        'messages': [], 'reply': {'text': 'Chị xác nhận muốn xóa toàn bộ dữ liệu chứ ạ?'}}
    runtime = SimpleNamespace(context=HotContext())
    state.update(await nodes.persist(state, runtime))
    assert state['deletion_awaiting_for'] == 'C-OWN'
    state.update(customer_id=owner, messages=[HumanMessage(content=middle)],
        reply={'text': 'Chị vui lòng không gửi CCCD qua chat ạ.'})
    state.update(await nodes.persist(state, runtime))
    state['messages'] += [AIMessage(content=state['reply']['text']), HumanMessage(content=confirmation)]
    context = nodes._agent_context(state, HotContext(), None)
    verdict = check('memory_request_deletion', {}, tier='VERIFIED', mode='speak', has_phone=True, quotes={},
        last_agent_said=context.last_agent_said, customer_said=context.customer_said,
        deletion_asked=context.deletion_asked)
    assert verdict.passed is allowed


@pytest.mark.parametrize('text', ['Em chưa ghi nhận yêu cầu xóa dữ liệu ạ.',
    'Em sẽ ghi nhận yêu cầu xóa sau khi chị xác nhận ạ.',
    'Chị có muốn em ghi nhận yêu cầu xóa dữ liệu không ạ?'])
def test_deletion_questions_and_future_or_negated_actions_are_not_success_claims(text):
    from ai_agent_service.components.guardrails.hard import GuardInput, check
    assert check(GuardInput(text, (), 'VERIFIED')).passed


def test_recorded_deletion_can_be_acknowledged_on_later_turns():
    from ai_agent_service.pipeline.hot import nodes
    from ai_agent_service.pipeline.hot.state import HotContext
    from ai_agent_service.components.guardrails.hard import check
    state = nodes._absorb({}, [{'name': 'memory.request_deletion',
        'result': {'ok': True, 'data': RECORDED}}])
    assert state['deletion_recorded']
    view = nodes.guard_input(state, HotContext(), 'Dạ em đã ghi nhận yêu cầu xóa dữ liệu của chị rồi ạ.', ())
    assert check(view).passed


@pytest.mark.asyncio
async def test_trusted_deletion_confirmation_reaches_the_actual_action_middleware():
    from langchain_core.messages import ToolMessage
    from ai_agent_service.agents.advisor import AgentContext, ActionGuardMiddleware
    from ai_agent_service.mcp.tools import ToolGuardMiddleware
    context = AgentContext(call_id='synthetic', tier='VERIFIED', customer_id='C-OWN',
        customer_phone='0900000001', deletion_asked=True,
        last_agent_said='Chị không gửi CCCD qua chat nhé.', customer_said='Chị đồng ý xóa dữ liệu.')
    request = SimpleNamespace(tool_call={'name': 'memory_request_deletion', 'id': 't1',
        'args': {'customer_id': 'C-VICTIM', 'call_id': 'other'}},
        tool=SimpleNamespace(args={'customer_id': {}, 'call_id': {}}), runtime=SimpleNamespace(context=context))
    request.override = lambda **changes: SimpleNamespace(**{**vars(request), **changes})
    handler = AsyncMock(return_value=ToolMessage(tool_call_id='t1', content=json.dumps({'ok': True, 'data': RECORDED})))
    bound = ToolGuardMiddleware(['memory_request_deletion'])._with_context(request)
    await ActionGuardMiddleware().awrap_tool_call(bound, handler)
    handler.assert_awaited_once()
    assert handler.await_args.args[0].tool_call['args'] == {'customer_id': 'C-OWN', 'call_id': 'synthetic'}


@pytest.mark.parametrize('data', [
    {'status': 'recorded'}, {**RECORDED, 'request_id': ''}, {**RECORDED, 'request_id': 'invented'},
    {**RECORDED, 'deleted_within_hours': True}, {**RECORDED, 'status': 'failed'},
])
def test_wrong_request_response_cannot_set_recorded_flag_or_support_acknowledgement(data):
    from ai_agent_service.pipeline.hot import nodes
    from ai_agent_service.components.guardrails.hard import GuardInput, check
    results = [{'name': 'memory.request_deletion', 'result': {'ok': True, 'data': data}}]
    assert not nodes._absorb({}, results)['deletion_recorded']
    assert not check(GuardInput('Em đã ghi nhận yêu cầu xóa dữ liệu ạ.', tuple(results), 'VERIFIED', check_handoff=False)).passed


@pytest.mark.parametrize('deleted,valid', [(False, False), ('done', False), ([], False),
    ({'facts': False}, False), ({'facts': -1}, False), ({'facts': '1'}, False), ({}, True), ({'facts': 3}, True)])
def test_only_real_deletion_counts_support_completed_erasure(deleted, valid):
    from ai_agent_service.components.guardrails.hard import GuardInput, check
    results = ({'name': 'memory.delete_customer', 'result': {'ok': True,
        'data': {'customer_id': 'C-OWN', 'deleted': deleted}}},)
    assert check(GuardInput('Em đã xóa toàn bộ dữ liệu của chị rồi ạ.', results, 'VERIFIED',
        check_handoff=False)).passed is valid
