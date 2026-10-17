"""The organisers' reference business logic, shared by every path that serves it.

``docs/design.md`` section 6.1: the catalogue, CRM and order tools wrap
``eval/mock_tools.py`` from the organisers' pack, so a price, a promotion, a
stock level, the COD limit or a moved callback is what the grader computes,
by construction rather than by care. The data is committed under
``data/btc`` and found through
:func:`~src.config.config_manager.btc_data_dir`.

Two paths serve these tools. Our MCP servers serve the API and the
organisers' evaluation command; the harness in ``evaluation/`` answers the
nine organisers' tools with its own copy of the mock, through
``pipeline/eval/bridge.py``. What we add on top of the mock lives here, once,
so both paths answer alike:

- :func:`enrich`: every applied promotion carries its end date, so the
  ``MemoryAgent`` can write ``promo_expiry`` (section 6.1);
- :func:`search_catalog`: a ``catalog.search`` whose words match nothing is
  retried loosely and says so;
- :func:`delivery_estimate`: the mock's own delivery rule, asked before an
  order exists, so the advisor can read the order back with its delivery
  time (PB-09).

**State.** The mock keeps its state in module globals: orders created,
callbacks, tickets, promotions already used once. Three processes load it
(``mcp-catalog``, ``mcp-crm``, ``mcp-order``), and an order created by one
must be visible to ``order.status`` in another, and after a restart. So the
state lives in one Postgres row. A read loads it and never writes it, so
reads take no lock and never queue behind one another. A write runs under a
transaction-scoped advisory lock and stores its result under its
idempotency key: a write tool is never retried (section 6.1), and a key seen
again returns the first outcome instead of creating a second order, which is
how Stripe makes its create and update requests safe to repeat.
:func:`reset` empties the row, which the evaluation runner does per scenario
(section 9.2).

A mock result carrying ``error`` becomes the ``{ok: false}`` envelope, with
the rest of the result as details the model can act on (the expected price
of a ``price_mismatch``, the restock date of an ``out_of_stock``).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import unicodedata
from datetime import date, timedelta
from types import ModuleType
from typing import Any, Awaitable, Callable

from ...config.config_manager import btc_data_dir
from ..server_base import ToolFailure, database

logger = logging.getLogger(__name__)

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS mock_state (
    id         INT PRIMARY KEY,
    state      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

#: The advisory lock every process takes around a write. Any fixed number.
_LOCK_KEY = 1510_2026

#: The organisers' tools that change the mock's state (``tools.schema.json``).
WRITES = frozenset({"order.create", "order.update", "schedule.callback", "handoff.transfer"})

#: Areas of the mock's delivery rule (``mock_tools._eta``), named as a
#: customer would hear them, each with an address the rule places there.
DELIVERY_AREAS = (("Hà Nội, TP.HCM, Đà Nẵng", "Hà Nội"), ("tỉnh thành khác", None))

_mock: ModuleType | None = None


def mock() -> ModuleType:
    """``eval/mock_tools.py``, imported once from the pack."""
    global _mock
    if _mock is None:
        path = btc_data_dir() / "eval" / "mock_tools.py"
        if not path.exists():
            raise RuntimeError(
                f"The organisers' data is not at {path.parent.parent}. It ships in "
                "apps/ai-agent-service/data/btc; BTC_DATA_DIR points elsewhere."
            )
        spec = importlib.util.spec_from_file_location("btc_mock_tools", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _add_synthetic_customers(module)
        _mock = module
    return _mock


def _add_synthetic_customers(module: ModuleType) -> None:
    """The team's synthetic CRM customers (``catalog/crm_seed_synthetic.json``,
    written by ``scripts/create_data``), so generated scenarios find their
    callers. Added to the mock's CRM in memory; ``mock_tools.py`` itself stays
    the organisers' file. IDs and phones never collide with the official 50
    (checked here). ``BTC_SYNTHETIC_CRM=0`` turns this off."""
    if os.environ.get("BTC_SYNTHETIC_CRM", "1") == "0":
        return
    path = btc_data_dir() / "catalog" / "crm_seed_synthetic.json"
    if not path.exists():
        return
    known_ids = {c.get("customer_id") for c in module.CRM}
    known_phones = {c.get("phone") for c in module.CRM}
    extra = [
        c for c in json.loads(path.read_text(encoding="utf-8")).get("customers", [])
        if c.get("customer_id") not in known_ids and c.get("phone") not in known_phones
    ]
    module.CRM.extend(extra)
    logger.info("BTC mock: %d synthetic CRM customers added to %d official", len(extra), len(module.CRM) - len(extra))


def reference_date() -> str:
    """The pack's "today", 2026-10-15: the default day of a call."""
    return str(mock().REF)


# ── the shared state ──────────────────────────────────────────────────────


def _dump(m: ModuleType) -> dict[str, Any]:
    return {
        "orders": m._ORDERS,
        "callbacks": m._CALLBACKS,
        "tickets": m._TICKETS,
        "once_used": sorted([list(pair) for pair in m._ONCE_USED]),
    }


def _load(m: ModuleType, state: dict[str, Any]) -> None:
    m._ORDERS.clear()
    m._ORDERS.update(state.get("orders") or {})
    m._CALLBACKS[:] = state.get("callbacks") or []
    m._TICKETS[:] = state.get("tickets") or []
    m._ONCE_USED.clear()
    m._ONCE_USED.update(tuple(pair) for pair in state.get("once_used") or [])


def _serialised(state: dict[str, Any]) -> str:
    return json.dumps(state, sort_keys=True, ensure_ascii=False)


def run_write(
    m: ModuleType, state: dict[str, Any], fn: Callable[..., Any], arguments: dict[str, Any], key: str | None,
) -> tuple[Any, dict[str, Any] | None]:
    """One write against *state*: the mock's result, and the state to store (None when nothing changed).

    A key already in the state returns the result it got the first time and
    changes nothing. Pure, apart from the mock's globals it loads *state* into.
    """
    remembered = dict(state.get("idempotent") or {})
    if key and key in remembered:
        logger.info("Write replayed under its idempotency key; returning its first result")
        return remembered[key], None
    _load(m, state)
    before = _serialised(_dump(m))
    result = fn(**arguments)
    # A copy, so the mock's globals changing later cannot change what is stored.
    after = json.loads(_serialised(_dump(m)))
    if not key and _serialised(after) == before:
        return result, None
    if key:
        remembered[key] = result
    if remembered:
        after["idempotent"] = remembered
    return result, after


async def _read_state(conn: Any) -> dict[str, Any]:
    cursor = await conn.execute("SELECT state FROM mock_state WHERE id = 1")
    row = await cursor.fetchone()
    return row["state"] if row else {}


async def call(name: str, fn: Callable[..., Any], /, *, idempotency_key: str | None = None, **kwargs: Any) -> Any:
    """Run one mock function against the shared state; the envelope's data.

    Arguments left as None are dropped, so the mock's own defaults apply, as
    they would to a caller who did not pass them. A read sees the last
    committed state and writes nothing; a write holds the lock (module
    docstring).
    """
    m = mock()
    arguments = {k: v for k, v in kwargs.items() if v is not None}
    pool = await database()
    async with pool.connection() as conn:
        if name not in WRITES:
            # No await between loading the state and reading it: the mock's
            # globals cannot change under this call within the process.
            _load(m, await _read_state(conn))
            return unwrap(name, enrich(name, fn(**arguments)))
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
            result, changed = run_write(m, await _read_state(conn), fn, arguments, idempotency_key)
            if changed is not None:
                await conn.execute(
                    "INSERT INTO mock_state (id, state) VALUES (1, %s) "
                    "ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()",
                    (_serialised(changed),),
                )
    return unwrap(name, enrich(name, result))


def unwrap(name: str, result: Any) -> Any:
    """The mock's own ``{"error": ...}`` as a business failure the model reads."""
    if isinstance(result, dict) and result.get("error"):
        code = str(result["error"]).upper()
        details = {k: v for k, v in result.items() if k != "error"}
        raise ToolFailure(code, f"{name}: {result['error']}", retryable=False, details=details)
    return result


async def reset() -> None:
    """Forget every order, callback, ticket, used promotion and idempotency key."""
    pool = await database()
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM mock_state")
    logger.info("Mock state reset")


# ── what we add on top of the mock ────────────────────────────────────────


def enrich(name: str, result: Any) -> Any:
    """A mock result with our additions; anything the mock said stays as it said it.

    ``pricing.get_quote``: each applied promotion gets ``end``, its last day
    in ``promotions.json``, the only source of a promotion's expiry.
    """
    if name != "pricing.get_quote" or not isinstance(result, dict) or not result.get("applied_promos"):
        return result
    ends = {promo["promo_code"]: promo.get("end") for promo in mock().PROMOS}
    return {**result, "applied_promos": [{**p, "end": ends.get(p.get("promo_code"))} for p in result["applied_promos"]]}


def product_of(sku: str) -> tuple[str | None, dict[str, Any] | None]:
    """The product a code belongs to, and the variant when the code is one: ``("SKU-SN-CAS", {...size 39...})``."""
    parent, variant = mock()._parent(sku)
    return (parent["sku"] if parent else None), (dict(variant) if variant else None)


def plain(text: str) -> str:
    """Lower case, no diacritics, hyphens and slashes as spaces: how a customer types."""
    decomposed = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).replace("-", " ").replace("/", " ")


def rank(query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """*items* that share a word with *query*, most shared words first, then cheapest."""
    words = [w for w in plain(query).split() if len(w) > 1]
    scored = []
    for item in items:
        haystack = plain(" ".join([item["name"], item["category"], item["sku"], str(item.get("attributes", ""))]))
        score = sum(1 for w in words if w in haystack)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["list_price_vnd"]))
    return [item for _, item in scored]


async def search_catalog(args: dict[str, Any], search: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """``catalog.search``, retried loosely when the name matches nothing.

    The mock wants every word of the query in a product's name, so "máy lọc
    không khí" finds nothing (the category is spelled
    ``may-loc-khong-khi``), and a search that answers "nothing" to the name
    of a category the shop sells makes the model say the shop does not sell
    it. *search* runs one mock search, through whichever path serves the
    tools, and returns its data.
    """
    found = await search(args)
    if found.get("items") or not args.get("query"):
        return {**found, "match": "exact"}
    loose = await search({k: v for k, v in args.items() if k != "query"})
    ranked = rank(args["query"], loose.get("items") or [])
    return {"items": ranked[:10], "total": len(ranked), "match": "loose" if ranked else "none"}


def _working_days(start: str, end: str) -> int:
    """Days after *start*, up to and including *end*, that the mock delivers on."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    holidays = mock().HOLIDAYS
    days = (first + timedelta(days=n) for n in range(1, (last - first).days + 1))
    return sum(1 for d in days if d.weekday() != 6 and d.isoformat() not in holidays)


def delivery_estimate(address: str | None, on: str) -> dict[str, Any]:
    """When an order placed on *on* would arrive, by the mock's own rule (``mock_tools._eta``).

    With an address: its working days and date, which ``order.create`` will
    then return as ``estimated_delivery``. Without one the area decides, so
    both areas are given and no single figure is: a number for an address
    nobody gave would be a promise nobody made.
    """
    m = mock()
    if address:
        estimated = m._eta(on, address)
        return {"address_known": True, "delivery_days": _working_days(on, estimated), "estimated_delivery": estimated}
    areas = []
    for area, example in DELIVERY_AREAS:
        estimated = m._eta(on, example)
        areas.append({"area": area, "delivery_days": _working_days(on, estimated), "estimated_delivery": estimated})
    return {"address_known": False, "delivery_days": None, "estimated_delivery": None, "by_area": areas}
