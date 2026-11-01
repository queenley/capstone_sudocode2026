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


@pytest.mark.parametrize("amount", [0, -0.1, float("nan"), float("inf"), -float("inf")])
def test_invalid_cap_does_not_leave_a_ledger(tmp_path, amount):
    path = tmp_path / "budget.sqlite"
    with pytest.raises(ValueError):
        budget.initialize(path, amount)
    assert not path.exists()


@pytest.mark.parametrize("amount", [-0.1, float("nan"), float("inf"), -float("inf")])
def test_invalid_charge_cannot_release_a_reservation(tmp_path, monkeypatch, amount):
    path = tmp_path / "budget.sqlite"
    budget.initialize(path, 1)
    monkeypatch.setenv("EVAL_BUDGET_DB", str(path))
    key = budget.reserve("test", 0.4)
    with pytest.raises(ValueError):
        budget.reserve("test", amount)
    with pytest.raises(ValueError):
        budget.settle(key, amount)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT units, settled FROM requests").fetchall() == [(budget.units(0.4), 0)]


@pytest.mark.parametrize("retry_config", [{}, {"max_retries": None}, {"max_retries": 1}, {"max_retries": -1}])
def test_budget_rejects_hidden_or_unaccounted_sdk_retries(retry_config):
    config = {"provider": "openai", "model": "gpt-4.1-mini", "max_tokens": 4096,
              "rate_limits": {"input_token_price_per_million": 0.4, "output_token_price_per_million": 1.6}}
    with pytest.raises(RuntimeError, match="explicit max_retries=0"):
        budget.BudgetCallback({**config, **retry_config}, "test")


def test_settlement_does_not_recreate_a_missing_ledger(tmp_path, monkeypatch):
    path = tmp_path / "budget.sqlite"
    budget.initialize(path, 1)
    monkeypatch.setenv("EVAL_BUDGET_DB", str(path))
    key = budget.reserve("test", 0.4)
    path.unlink()
    with pytest.raises(sqlite3.OperationalError):
        budget.settle(key, 0.01)
    assert not path.exists()


def test_ledger_preflight_requires_existing_valid_ledger_without_mutation(tmp_path, monkeypatch):
    monkeypatch.delenv("EVAL_BUDGET_DB", raising=False)
    with pytest.raises(RuntimeError, match="EVAL_BUDGET_DB is required"):
        budget.validate_ledger()
    path = tmp_path / "budget.sqlite"
    monkeypatch.setenv("EVAL_BUDGET_DB", str(path))
    with pytest.raises(RuntimeError, match="must exist"):
        budget.validate_ledger()
    assert not path.exists()
    budget.initialize(path, 1)
    before = path.read_bytes()
    budget.validate_ledger()
    assert path.read_bytes() == before
    budget.reserve("test", 1)
    with pytest.raises(RuntimeError, match="exhausted"):
        budget.validate_ledger()


@pytest.mark.parametrize("corrupt", [
    "DELETE FROM budget",
    "INSERT INTO budget VALUES (1000000000)",
    "UPDATE budget SET limit_units=-1",
    "INSERT INTO requests VALUES ('bad', 'test', -1, 1)",
    "INSERT INTO requests VALUES ('bad', 'test', 0.5, 1)",
    "INSERT INTO requests VALUES ('bad', 'test', 1, 2)",
])
def test_corrupt_ledger_fails_closed_before_new_reservation(tmp_path, monkeypatch, corrupt):
    path = tmp_path / "budget.sqlite"
    budget.initialize(path, 1)
    monkeypatch.setenv("EVAL_BUDGET_DB", str(path))
    with sqlite3.connect(path) as db:
        db.execute(corrupt)
        before = db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    with pytest.raises(RuntimeError, match="Evaluation budget ledger"):
        budget.validate_ledger()
    with pytest.raises(RuntimeError, match="Evaluation budget ledger"):
        budget.reserve("test", 0.01)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == before
