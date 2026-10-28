from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai import LengthFinishReasonError
from openai.types.chat import ChatCompletion

from ai_agent_service.components.evaluation.scorers import Extractor, Items, turn_input
from ai_agent_service.llm import evaluation_budget as budget
from ai_agent_service.llm.callback_handler import TokenTrackingCallback
from ai_agent_service.llm import token_ledger
from ai_agent_service.pipeline.eval.cli import ConfigRun, _label

TURN = turn_input("Em sẽ kiểm tra lại ạ.")


def truncated():
    return LengthFinishReasonError(completion=ChatCompletion(id="fixture", model="gpt-4.1-mini", object="chat.completion",
        created=0, choices=[], usage={"prompt_tokens": 1258, "completion_tokens": 4096, "total_tokens": 5354}))


@pytest.mark.asyncio
async def test_truncation_retries_once_and_keeps_attempt_evidence(tmp_path):
    labeller = SimpleNamespace(ainvoke=AsyncMock(side_effect=[truncated(), Items(items=[])]))
    extractor = Extractor(SimpleNamespace(with_structured_output=lambda *_, **__: labeller), model_name="mock",
                          cache_path=tmp_path/'cache.json')
    result = await extractor.label(TURN)
    assert 'error' not in result
    assert len(result['recovered_errors']) == 1
    assert result['recovered_errors'][0].startswith('LengthFinishReasonError')
    assert labeller.ainvoke.await_count == 2
    assert extractor.stats()['calls'] == 2
    assert extractor.stats()['failures'] == 1
    assert extractor.stats()['retries'] == 1
    await extractor.label(TURN)
    assert labeller.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_the_cache_is_keyed_by_the_whole_input_so_new_history_means_new_labels(tmp_path):
    labeller = SimpleNamespace(ainvoke=AsyncMock(return_value=Items(items=[])))
    extractor = Extractor(SimpleNamespace(with_structured_output=lambda *_, **__: labeller), model_name="mock",
                          cache_path=tmp_path/'cache.json')
    await extractor.label(TURN)
    await extractor.label(turn_input("Em sẽ kiểm tra lại ạ.", previous_sessions=[{"call": "call_1", "turns": []}]))
    assert labeller.ainvoke.await_count == 2
    reloaded = Extractor(SimpleNamespace(with_structured_output=lambda *_, **__: labeller), model_name="mock",
                         cache_path=tmp_path/'cache.json')
    await reloaded.label(TURN)
    assert labeller.ainvoke.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('errors', [[truncated(), truncated()], [RuntimeError('budget exhausted')]])
async def test_extractor_does_not_loop_or_cache_failure(tmp_path, errors):
    labeller = SimpleNamespace(ainvoke=AsyncMock(side_effect=errors))
    cache = tmp_path/'cache.json'
    extractor = Extractor(SimpleNamespace(with_structured_output=lambda *_, **__: labeller), model_name="mock",cache_path=cache)
    result = await extractor.label(TURN)
    assert result.get('error')
    assert labeller.ainvoke.await_count == len(errors)
    assert not cache.exists()


def test_truncation_usage_is_charged_and_recorded(tmp_path, monkeypatch):
    path = tmp_path/'budget.sqlite'
    budget.initialize(path, 1)
    monkeypatch.setenv('EVAL_BUDGET_DB', str(path))
    config = {'provider':'openai','model':'gpt-4.1-mini','max_tokens':4096,'max_retries':0,
              'rate_limits':{'input_token_price_per_million':0.4,'output_token_price_per_million':1.6}}
    cb = budget.BudgetCallback(config, 'extractor')
    cb.on_chat_model_start({}, [[]], run_id='truncate')
    cb.on_llm_error(truncated(), run_id='truncate')
    import sqlite3
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT settled,units FROM requests').fetchone() == (1,budget.units(0.0070568))
    token_ledger.reset()
    tracker = TokenTrackingCallback(SimpleNamespace(record_request=lambda *usage: None), agent_name='extractor')
    tracker.on_llm_error(truncated())
    assert token_ledger.snapshot()['extractor']['output'] == 4096
    token_ledger.reset()


def fixture_row(turn):
    return {'scenario_id': 'S', 'call': 'call_1', 'turn': turn, 'customer_text': 'fixture', 'agent_text': 'fixture',
            'tool_calls': [], 'facts_used': []}


@pytest.mark.asyncio
async def test_capped_label_batch_waits_for_usage_instead_of_refusing_burst(tmp_path, monkeypatch):
    import asyncio
    path = tmp_path/'budget.sqlite'; budget.initialize(path, 0.6)
    monkeypatch.setenv('EVAL_BUDGET_DB', str(path))

    class Labeller:
        async def label(self, data):
            key = budget.reserve('fixture',0.4)
            await asyncio.sleep(0.01)
            budget.settle(key,0.01)
            return {'items': [], 'questions': [], 'claims': [], 'facts_used': [], 'dropped': 0, 'changed': 0,
                    'recovered_errors': ['recovered truncation']}
        def stats(self):return {}

    run = ConfigRun(rows=[fixture_row(t) for t in range(1, 5)], diagnostics=[{} for _ in range(4)])
    await _label(run, Labeller())
    assert all(d['extraction_recovered_errors'] == ['recovered truncation'] for d in run.diagnostics)


@pytest.mark.asyncio
async def test_a_failed_turn_is_unlabelled_and_blocks_the_table():
    from ai_agent_service.pipeline.eval import report

    class Failing:
        async def label(self, data):
            return {'items': [], 'questions': [], 'claims': [], 'facts_used': [], 'dropped': 0, 'changed': 0,
                    'error': 'RuntimeError: boom', 'attempt_errors': ['RuntimeError: boom']}
        def stats(self):return {}

    run = ConfigRun(rows=[fixture_row(1)], diagnostics=[{}])
    await _label(run, Failing())
    found = report.problems(run.rows, run.diagnostics, schema_errors=0, rejected=0, scenario_errors=0)
    assert found['unlabelled_turns'] == 1 and 'unlabelled_turns' in report.BLOCKING
