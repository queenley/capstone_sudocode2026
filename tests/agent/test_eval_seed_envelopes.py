"""Seed diagnostics preserve infrastructure failure without retrying writes."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ai_agent_service.pipeline.eval import report, runner
from ai_agent_service.mcp.tools import ToolBox


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['TIMEOUT', 'FORBIDDEN', 'BAD_ENVELOPE'])
async def test_failed_seed_records_tool_and_code_without_leaking_message_or_retry(monkeypatch, code):
    monkeypatch.setattr(runner, '_seed_owner', AsyncMock(return_value='synthetic-owner'))
    writer = SimpleNamespace(call=AsyncMock(return_value={
        'ok': False, 'error': {'code': code, 'message': 'private-value-must-not-be-printed'}}))
    session = SimpleNamespace(session_id='S-SYNTHETIC', day='2035-02-03', channel='hotline',
                              facts={'budget_vnd': 123000}, summary='', outcome='hen_goi_lai')
    with pytest.raises(runner.scenarios.ScenarioError) as failure:
        await runner.seed(SimpleNamespace(writer=writer), (session,), customer_phone=None, customer_name=None)
    assert 'memory_commit_facts' in str(failure.value) and code in str(failure.value)
    assert 'private-value' not in str(failure.value)
    writer.call.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('data', [None, [], 'invalid'])
async def test_empty_success_payload_is_not_a_successful_seed(data):
    rig = SimpleNamespace(writer=SimpleNamespace(call=AsyncMock(return_value={'ok': True, 'data': data})))
    with pytest.raises(runner.scenarios.ScenarioError, match='BAD_ENVELOPE'):
        await runner._seed_data(rig, 'memory_commit_episode', 'synthetic stage')


@pytest.mark.asyncio
async def test_successful_seed_still_writes_facts_then_episode(monkeypatch):
    monkeypatch.setattr(runner, '_seed_owner', AsyncMock(return_value='synthetic-owner'))
    writer = SimpleNamespace(call=AsyncMock(side_effect=[{'ok': True, 'data': {'memory_writes': []}},
                                                        {'ok': True, 'data': {'episode_id': 'synthetic'}}]))
    session = SimpleNamespace(session_id='S-SYNTHETIC', day='2035-02-03', channel='hotline',
                              facts={'budget_vnd': 123000}, summary='', outcome='hen_goi_lai')
    assert await runner.seed(SimpleNamespace(writer=writer), (session,), customer_phone=None, customer_name=None) == 'synthetic-owner'
    assert [call.args[0] for call in writer.call.await_args_list] == ['memory_commit_facts', 'memory_commit_episode']


@pytest.mark.asyncio
async def test_real_toolbox_timeout_stops_seed_without_retrying(monkeypatch):
    import asyncio
    monkeypatch.setattr(runner, '_seed_owner', AsyncMock(return_value='synthetic-owner'))
    async def slow(_):
        await asyncio.sleep(1)
    tool = SimpleNamespace(name='memory_commit_facts', ainvoke=AsyncMock(side_effect=slow))
    session = SimpleNamespace(session_id='S-SYNTHETIC', day='2035-02-03', channel='hotline',
                              facts={'budget_vnd': 123000}, summary='', outcome='hen_goi_lai')
    rig = SimpleNamespace(writer=ToolBox([tool], timeout=.001))
    with pytest.raises(runner.scenarios.ScenarioError, match='TIMEOUT'):
        await runner.seed(rig, (session,), customer_phone=None, customer_name=None)
    tool.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_identity_lookup_does_not_create_another_customer(monkeypatch):
    monkeypatch.setattr(runner.btc, 'mock', lambda: SimpleNamespace(crm_get_customer=lambda **_: {'found': False}))
    writer = SimpleNamespace(call=AsyncMock(return_value={'ok': False, 'error': {'code': 'TIMEOUT'}}))
    with pytest.raises(runner.scenarios.ScenarioError, match='identity_find'):
        await runner._seed_owner(SimpleNamespace(writer=writer), '0900000000', None)
    assert [call.args[0] for call in writer.call.await_args_list] == ['identity_find']


@pytest.mark.parametrize('content', [None, '', ' \n\n'])
def test_grader_never_invokes_btc_with_an_empty_or_missing_trace(monkeypatch, tmp_path, content):
    full = tmp_path / 'full.jsonl'
    if content is not None:
        full.write_text(content)
    invoke = Mock()
    monkeypatch.setattr(report.subprocess, 'run', invoke)
    code, text = report.grade(tmp_path, full=full, baseline=None, out=tmp_path / 'report.json')
    assert code == 1 and 'Not scored' in text
    invoke.assert_not_called()
