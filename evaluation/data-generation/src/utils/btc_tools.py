"""Load BTC's reference code from ``data/eval/`` so ground truth and scoring never drift from it.

* ``mock_tools.py``     – reference tool logic (price after promotions, stock by date,
                          promo conditions, COD limit, callback holiday rules). BTC checks
                          our data against it (``validate_scenarios.py``).
* ``reference_eval.py`` – official metric script (CCR, RQR, TSR, HR, guardrails, ASR, RAG).

``fresh_mock_tools()`` re-executes the module so runtime state (created orders,
once-per-customer promo usage, callbacks) starts empty for every scenario.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
from functools import lru_cache
from types import ModuleType

from src.utils.paths import CATALOG_DIR, DATA_DIR

EVAL_DIR = DATA_DIR / "eval"
OFFICIAL_TOOLS = ("crm.get_customer", "catalog.search", "inventory.check", "order.create", "order.update",
                  "schedule.callback", "handoff.transfer", "pricing.get_quote", "order.status")
M2_TOOLS = ("pricing.get_quote", "order.status")


def _load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EVAL_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _add_synthetic_customers(module: ModuleType) -> None:
    """Add the synthetic CRM customers this project generates to the mock's CRM, in memory, so generated
    scenarios find their callers. ``mock_tools.py`` stays the organisers' file, as in the agent
    (``mcp/servers/btc.py``): ids and phones that collide with BTC's 50 are not added; ``BTC_SYNTHETIC_CRM=0``
    turns it off."""
    path = CATALOG_DIR / "crm_seed_synthetic.json"
    if os.environ.get("BTC_SYNTHETIC_CRM", "1") == "0" or not path.exists():
        return
    known_ids = {c.get("customer_id") for c in module.CRM}
    known_phones = {c.get("phone") for c in module.CRM}
    module.CRM.extend(c for c in json.loads(path.read_text(encoding="utf-8")).get("customers", [])
                      if c.get("customer_id") not in known_ids and c.get("phone") not in known_phones)


def fresh_mock_tools() -> ModuleType:
    """New, state-free instance of BTC ``mock_tools``, with the synthetic customers."""
    module = _load("btc_mock_tools", "mock_tools.py")
    _add_synthetic_customers(module)
    return module


@lru_cache(maxsize=1)
def mock_tools() -> ModuleType:
    """Shared instance for read-only lookups (quotes, stock). Do not create orders on it."""
    return fresh_mock_tools()


@lru_cache(maxsize=1)
def reference_eval() -> ModuleType:
    return _load("btc_reference_eval", "reference_eval.py")


def tool_signatures() -> dict[str, list[str]]:
    """Parameter names of every official mock tool, e.g. ``{"order.create": ["customer_phone", ...]}``."""
    return {name: list(inspect.signature(fn).parameters) for name, fn in mock_tools().TOOLS.items()}


def call_tool(module: ModuleType, name: str, args: dict) -> dict:
    """Execute an official tool on ``module`` with only the parameters it accepts."""
    fn = module.TOOLS[name]
    accepted = inspect.signature(fn).parameters
    return fn(**{k: v for k, v in args.items() if k in accepted})
