import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ai_agent_service.llm import evaluation_budget as budget


def test_budget_is_shared_and_unknown_calls_remain_charged(tmp_path, monkeypatch):
    path = tmp_path / "budget.sqlite"
    budget.initialize(path, 1)
    monkeypatch.setenv("EVAL_BUDGET_DB", str(path))

    def attempt(_):
        try:
            return budget.reserve("test", 0.4)
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = [k for k in pool.map(attempt, range(8)) if k]
    assert len(keys) == 2
    budget.settle(keys[0], 0.01)
    budget.settle(keys[0], 0)  # Duplicate reconciliation cannot release more.
    budget.reserve("test", 0.4)
    with pytest.raises(RuntimeError, match="exhausted"):
        budget.reserve("test", 0.4)
    with pytest.raises(FileExistsError):
        budget.initialize(path, 20)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT SUM(units) FROM requests").fetchone()[0] == budget.units(0.81)


def test_callback_reserves_before_dispatch_and_reconciles_usage(tmp_path, monkeypatch):
    path = tmp_path / "budget.sqlite"
    budget.initialize(path, 1)
    monkeypatch.setenv("EVAL_BUDGET_DB", str(path))
    callback = budget.BudgetCallback({"provider": "openai", "model": "gpt-4.1-mini", "max_tokens": 4096,
        "max_retries": 0, "rate_limits": {"input_token_price_per_million": 0.4, "output_token_price_per_million": 1.6}}, "test")
    callback.on_chat_model_start({}, [[]], run_id="success")
    callback.on_llm_end(SimpleNamespace(llm_output={"token_usage": {
        "prompt_tokens": 1000, "completion_tokens": 1000}}), run_id="success")
    callback.on_chat_model_start({}, [[]], run_id="failed")
    callback.on_llm_error(RuntimeError("unknown billing"), run_id="failed")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT units FROM requests WHERE settled=1").fetchone()[0] == budget.units(0.002)
        assert db.execute("SELECT COUNT(*) FROM requests WHERE settled=0").fetchone()[0] == 1


def test_missing_budget_file_blocks_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_BUDGET_DB", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="initialized"):
        budget.reserve("test", 0.1)


def test_langchain_propagates_budget_refusal_before_model_execution(tmp_path, monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    path = tmp_path / "budget.sqlite"
    budget.initialize(path, 0.1)
    monkeypatch.setenv("EVAL_BUDGET_DB", str(path))
    callback = budget.BudgetCallback({"provider": "openai", "model": "gpt-4.1-mini", "max_tokens": 4096,
        "max_retries": 0, "rate_limits": {"input_token_price_per_million": 0.4, "output_token_price_per_million": 1.6}}, "test")
    model = FakeListChatModel(responses=["first", "second"], callbacks=[callback])
    with pytest.raises(RuntimeError, match="exhausted"):
        model.invoke("This model must never be reached")
    assert model.i == 0
