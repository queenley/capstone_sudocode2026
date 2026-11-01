"""Evaluation configures the Windows DB-compatible loop before creating it."""
import json
import pytest

from ai_agent_service.mcp import server_base
from ai_agent_service.pipeline.eval import cli, relabel, runner


@pytest.mark.parametrize('mode', ['scenarios', 'relabel'])
def test_evaluation_selects_loop_policy_before_asyncio_run(tmp_path, monkeypatch, mode):
    events = []
    monkeypatch.setattr(server_base, 'use_selector_loop_on_windows', lambda: events.append('policy'))
    monkeypatch.setattr(runner, 'use_evaluation_database', lambda: 'synthetic_eval')
    monkeypatch.setattr(cli, '_extractor', lambda: object())
    monkeypatch.setattr(cli, 'validate_ledger', lambda: None)
    # main sets these environment variables for MCP children; isolate that mutation.
    monkeypatch.setenv('MCP_TRANSPORT', 'stdio')
    monkeypatch.setenv('MCP_LOG_FILE', str(tmp_path / 'before.log'))

    async def unused(*args, **kwargs):
        raise AssertionError('No DB, model or extractor operation may run in this test')

    def run(coroutine):
        events.append('asyncio.run')
        coroutine.close()
        return 23

    monkeypatch.setattr(cli, '_evaluate', unused)
    monkeypatch.setattr(relabel, 'relabel', unused)
    monkeypatch.setattr(cli.asyncio, 'run', run)
    source = tmp_path / 'input'
    source.mkdir()
    (source / 'synthetic.json').write_text(json.dumps({'scenario_id': 'SYNTHETIC-1',
        'calls': {'call_1': {'customer_turns': ['Synthetic request']}}}))
    assert cli.main(['--' + mode, str(source), '--out', str(tmp_path / 'output')]) == 23
    assert events == ['policy', 'asyncio.run']


def test_loop_helper_is_a_noop_off_windows(monkeypatch):
    import sys

    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(server_base.asyncio, 'set_event_loop_policy',
                        lambda policy: pytest.fail('Non-Windows runs must retain their loop policy'))
    server_base.use_selector_loop_on_windows()
