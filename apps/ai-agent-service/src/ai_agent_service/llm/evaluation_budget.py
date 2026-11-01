"""Opt-in, process-shared evaluation spend cap; no prompts or secrets in the ledger.

Create the ledger once with initialize(), then set EVAL_BUDGET_DB in every
evaluation child. Reserve a whole model context before a request; reconcile
only when usage is known. Failed/unknown requests keep their reservation.
"""
from __future__ import annotations

import os
import sqlite3
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler

from .callback_handler import error_usage, extract_usage

SCALE = 1_000_000_000
# Verified 2026-10-22: developers.openai.com/api/docs/models/gpt-4.1-mini
OPENAI_CONTEXT = 1_047_576


def units(dollars: Any) -> int:
    amount = Decimal(str(dollars))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Budget amounts must be finite and non-negative")
    return int((amount * SCALE).to_integral_value(rounding=ROUND_CEILING))


def initialize(path: Path, limit_usd: float) -> None:
    limit = units(limit_usd)
    if limit <= 0:
        raise ValueError("A positive evaluation budget is required")
    # Never reset an existing ledger and accidentally permit another $20.
    with path.open("x"):
        pass
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE budget (limit_units INTEGER NOT NULL)")
        db.execute("INSERT INTO budget VALUES (?)", (limit,))
        db.execute("CREATE TABLE requests (id TEXT PRIMARY KEY, agent TEXT, units INTEGER NOT NULL, settled INTEGER NOT NULL)")


def _ledger_totals(db: sqlite3.Connection) -> tuple[int, int]:
    limits = db.execute("SELECT limit_units FROM budget").fetchall()
    if len(limits) != 1 or type(limits[0][0]) is not int or limits[0][0] <= 0:
        raise RuntimeError("Evaluation budget ledger must have one positive integer cap")
    invalid = db.execute("SELECT 1 FROM requests WHERE typeof(units) != 'integer' OR units < 0 "
                         "OR typeof(settled) != 'integer' OR settled NOT IN (0, 1) LIMIT 1").fetchone()
    if invalid:
        raise RuntimeError("Evaluation budget ledger contains invalid request charges")
    spent = db.execute("SELECT COALESCE(SUM(units),0) FROM requests").fetchone()[0]
    return limits[0][0], spent


def validate_ledger() -> None:
    """Preflight an existing ledger without creating or changing it."""
    path = os.environ.get("EVAL_BUDGET_DB")
    if not path:
        raise RuntimeError("EVAL_BUDGET_DB is required for model-backed evaluation")
    try:
        with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30) as db:
            limit, spent = _ledger_totals(db)
    except (OSError, sqlite3.Error) as error:
        raise RuntimeError("Evaluation budget ledger must exist and have a valid schema") from error
    if spent >= limit:
        raise RuntimeError("Evaluation budget exhausted; paid request blocked before dispatch")


def reserve(agent: str, dollars: float) -> str | None:
    path = os.environ.get("EVAL_BUDGET_DB")
    if not path:
        return None
    if not Path(path).is_file():
        raise RuntimeError("Evaluation budget ledger must be initialized before model calls")
    amount = units(dollars)
    if amount <= 0:
        raise ValueError("Request reservation must be positive")
    key = str(uuid4())
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True, timeout=30) as db:
        db.execute("BEGIN IMMEDIATE")
        limit, spent = _ledger_totals(db)
        if spent + amount > limit:
            raise RuntimeError("Evaluation budget exhausted; paid request blocked before dispatch")
        db.execute("INSERT INTO requests VALUES (?, ?, ?, 0)", (key, agent, amount))
    return key


def settle(key: str | None, dollars: float) -> None:
    if key is None:
        return
    amount = units(dollars)
    path = Path(os.environ["EVAL_BUDGET_DB"]).resolve()
    with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=30) as db:
        # A retry/late callback cannot release a reservation twice.
        db.execute("UPDATE requests SET units=?, settled=1 WHERE id=? AND settled=0",
                   (amount, key))


class BudgetCallback(BaseCallbackHandler):
    raise_error = True

    def __init__(self, config: dict[str, Any], agent: str) -> None:
        if config["provider"] != "openai" or config["model"] != "gpt-4.1-mini":
            raise RuntimeError("Evaluation budget currently supports only openai:gpt-4.1-mini")
        rates = config["rate_limits"]
        self.input_price = rates["input_token_price_per_million"]
        self.output_price = rates["output_token_price_per_million"]
        if self.input_price != 0.40 or self.output_price != 1.60:
            raise RuntimeError("Verify gpt-4.1-mini pricing before changing the budget rate")
        # SDK retries expose only the final attempt's usage, hiding earlier bills.
        if config.get("max_retries") != 0:
            raise RuntimeError("Evaluation budget requires explicit max_retries=0")
        self.maximum = (OPENAI_CONTEXT * self.input_price + config["max_tokens"] * self.output_price) / 1_000_000
        self.agent = agent
        self.pending: dict[Any, str | None] = {}

    def on_chat_model_start(self, serialized: dict, messages: list, *, run_id: Any, **kwargs: Any) -> None:
        if len(messages) != 1:
            raise RuntimeError("Evaluation budget requires one request per model invocation")
        self.pending[run_id] = reserve(self.agent, self.maximum)

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        key = self.pending.pop(run_id, None)
        usage = (response.llm_output or {}).get("token_usage") or {}
        input_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if input_tokens is None or output_tokens is None:
            message = response.generations[0][0].message
            if not message.usage_metadata:
                return
            input_tokens, output_tokens = extract_usage(message)
        settle(key, (input_tokens * self.input_price + output_tokens * self.output_price) / 1_000_000)

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        key = self.pending.pop(run_id, None)
        if (usage := error_usage(error)) is not None:
            settle(key, (usage[0] * self.input_price + usage[1] * self.output_price) / 1_000_000)
        # Unknown billing, including interrupted streams, retains the full reservation.
