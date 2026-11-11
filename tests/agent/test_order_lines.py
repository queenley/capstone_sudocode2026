"""An order of more than one unit, as the organisers asked in 11/2026: prices from pricing.quote_order, one
order.create with lines, each unit at its own price; checked against their mock and their grader."""
import importlib.util
import json

import pytest
from langchain_core.messages import HumanMessage

from ai_agent_service.agents.advisor import _filled_order
from ai_agent_service.components.guardrails import actions, purchase
from ai_agent_service.config.config_manager import btc_data_dir
from ai_agent_service.mcp.server_base import ToolFailure
from ai_agent_service.mcp.servers import btc, catalog, crm
from tests.agent.test_cache_and_strict_tools import order_context

PHONE = "0911000301"


@pytest.fixture
def mock_without_database(monkeypatch):
    """btc.call against the organisers' mock in memory: no Postgres, the same arguments and envelope."""
    async def call(name, fn, /, *, idempotency_key=None, call_id=None, turn_id=None, purchase_authorization=None,
                   order_group=None, **kwargs):
        return btc.unwrap(name, btc.enrich(name, fn(**{k: v for k, v in kwargs.items() if v is not None})))
    monkeypatch.setattr(btc, "call", call)


def grader():
    spec = importlib.util.spec_from_file_location("reference_eval", btc_data_dir() / "eval" / "reference_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_two_of_one_purifier_are_two_lines_at_two_prices_and_the_mock_and_grader_accept_them(mock_without_database):
    on = btc.reference_date()
    quote = await catalog.pricing_quote_order(lines=[{"sku": "SKU-AP-PRO", "qty": 2}], on=on, customer_phone=PHONE)
    key, units = purchase.quoted_units(quote)
    assert len({price for _, price in units}) == 2  # one unit has the second-item promotion
    assert all(p.get("name") for u in quote["units"] for p in u["applied_promos"])  # named, as get_quote's are
    model_wrote = {"lines": [{"sku": "SKU-AP-PRO", "qty": 2}], "payment": "bank"}
    filled = _filled_order(model_wrote, order_context(), {}, {key: units})
    assert sorted(line["price_vnd"] for line in filled["lines"]) == sorted(price for _, price in units)
    placed = await crm.order_create(lines=filled["lines"], payment="bank", customer_phone=PHONE, on=on)
    assert placed["status"] == "created" and placed["total_vnd"] == quote["total_vnd"]
    # The grader counts every line of the order, at its own price (total_match_vnd, args_match per line).
    rows = [{"tool_calls": [{"name": "order.create", "args": {**filled, "customer_phone": PHONE}, "result": placed}]}]
    spec = {"success_if": {"tool_called": "order.create", "args_match": {"sku": "SKU-AP-PRO"},
                           "total_match_vnd": quote["total_vnd"]}}
    assert grader().check_call(spec, rows)[0]


@pytest.mark.asyncio
async def test_one_price_for_two_units_is_refused_by_the_mock(mock_without_database):
    on, phone = btc.reference_date(), "0911000302"  # the mock remembers a second-item discount per phone and day
    quote = await catalog.pricing_quote_order(lines=[{"sku": "SKU-AP-PRO", "qty": 2}], on=on, customer_phone=phone)
    with pytest.raises(ToolFailure):
        await crm.order_create(lines=[{"sku": "SKU-AP-PRO", "qty": 2, "price_vnd": quote["units"][0]["final_price_vnd"]}],
                               payment="bank", customer_phone=phone, on=on)


def guard(lines, order_quotes, **extra):
    return actions._order_create({"lines": lines, "payment": "bank", **extra}, tier="VERIFIED", has_phone=True, quotes={},
                                 order_quotes=order_quotes, trusted=frozenset({"A", "B"}))


def test_the_guard_takes_only_the_quoted_price_of_every_unit():
    quoted = {purchase.units_key([{"sku": "A"}, {"sku": "B"}]): [["A", 7_000_000], ["B", 2_000_000]]}
    assert guard([{"sku": "A", "qty": 1, "price_vnd": 7_000_000}, {"sku": "B", "qty": 1, "price_vnd": 2_000_000}], quoted) == []
    assert guard([{"sku": "A", "qty": 1, "price_vnd": 7_000_000}, {"sku": "B", "qty": 1, "price_vnd": 4_000_000}], quoted)
    assert "pricing_quote_order" in guard([{"sku": "A", "qty": 2, "price_vnd": 7_000_000}], quoted)[0]
    assert "catalog_search" in guard([{"sku": "Z", "qty": 1, "price_vnd": 1}], quoted)[0]


def test_cod_over_the_limit_counts_the_whole_order_of_lines():
    quoted = {purchase.units_key([{"sku": "A", "qty": 2}]): [["A", 7_000_000], ["A", 3_500_000]]}
    lines = [{"sku": "A", "qty": 1, "price_vnd": 7_000_000}, {"sku": "A", "qty": 1, "price_vnd": 3_500_000}]
    assert "10.000.000" in " ".join(guard(lines, quoted, payment="COD"))
    assert guard(lines, quoted) == []


def test_the_read_back_and_the_backend_s_consent_see_one_order_of_lines():
    lines = [{"sku": "A", "qty": 1, "price_vnd": 7_000_000}, {"sku": "B", "qty": 1, "price_vnd": 2_000_000}]
    record = purchase.draft({"lines": lines, "payment": "bank"}, order_context())
    assert "Máy A" in record["read_back"] and "Nồi B" in record["read_back"] and "9.000.000đ" in record["read_back"]
    # The client writes lines as the model did (qty left out); the backend reads them back whole: one fingerprint.
    client = purchase.payload({"lines": [{"sku": "A", "price_vnd": 7_000_000}, {"sku": "B", "price_vnd": 2_000_000}],
                               "payment": "bank", "customer_phone": "0900000000", "on": "2026-10-15"})
    backend = {"lines": crm._lines(lines), "payment": "bank", "customer_phone": "0900000000", "on": "2026-10-15"}
    assert purchase.fingerprint(client) == purchase.fingerprint(backend)
    assert record["target_id"] == purchase.target(client) == "A,B"


def test_an_order_placed_with_lines_counts_once_with_its_total():
    result = {"name": "order.create", "args": {"lines": [{"sku": "A", "qty": 2, "price_vnd": 100}], "payment": "COD"},
              "result": {"ok": True, "data": {"order_id": "OD1"}}}
    assert actions.placed_lines([result]) == [{"order_id": "OD1", "sku": "A", "qty": 1, "price_vnd": 200, "skus": ["A"],
                                               "payment": "COD", "order_group": None}]


@pytest.mark.asyncio
async def test_a_turn_with_no_words_is_the_customer_still_on_the_line():
    from types import SimpleNamespace

    from ai_agent_service.pipeline.hot import nodes

    state = {"phase": "turn", "turn_id": "t4", "call_id": "c", "channel": "hotline"}
    update = await nodes.perceive(state, SimpleNamespace(context=SimpleNamespace(text="", arrived=1.0)))
    assert [m.content for m in update["messages"]] == [nodes.SILENT] and isinstance(update["messages"][0], HumanMessage)
    assert json.dumps(update["messages"][0].content, ensure_ascii=False)


def test_gpt_6_1_sol_gets_what_it_requires_whichever_agent_it_serves():
    from ai_agent_service.config.config_manager import get_models_config

    models = get_models_config()
    sol = models.llm_config("openai", "gpt-6.1-sol", agent="advisor")
    assert sol["reasoning_effort"] == "low" and sol["use_responses_api"] is True  # never none; tools need Responses
    luna = models.llm_config("openai", "gpt-5.6-luna", agent="advisor")
    assert luna["reasoning_effort"] == "none" and luna["use_responses_api"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("server, name, fields", [(catalog.server, "pricing_quote_order", {"sku", "qty"}),
                                                  (crm.server, "order_create", {"sku", "qty", "price_vnd"})])
async def test_an_order_line_s_fields_are_in_the_schema_the_model_reads(server, name, fields):
    """An untyped line is an object with no properties: under a strict schema every line reached the tool as {}."""
    tool = next(t for t in await getattr(server, "mcp", server).list_tools() if t.name == name)
    found = json.dumps(tool.parameters)
    assert all(f'"{field}"' in found for field in fields) and '"properties": {}' not in found


@pytest.mark.asyncio
async def test_strict_mode_keeps_an_order_line_s_fields():
    from langchain_core.tools import StructuredTool

    from ai_agent_service.mcp.tools import strict_tool

    published = next(t for t in await getattr(catalog.server, "mcp", catalog.server).list_tools()
                     if t.name == "pricing_quote_order")
    tool = StructuredTool.from_function(func=lambda **kw: "{}", name=published.name, description="d",
                                        args_schema=published.parameters)
    line = strict_tool(tool)["function"]["parameters"]["properties"]["lines"]["items"]
    assert set(line["properties"]) == {"sku", "qty"} and line["additionalProperties"] is False


def test_a_product_of_an_order_of_lines_already_placed_is_not_ordered_again_on_a_confirmation():
    placed = [{"order_id": "OD1", "sku": "A", "skus": ["A", "B"]}]
    reasons = actions._order_create({"sku": "B", "price_vnd": 2_000_000, "payment": "bank"}, tier="VERIFIED",
                                    has_phone=True, quotes={"B": 2_000_000}, trusted=frozenset({"A", "B"}),
                                    created=placed, customer_said="Đúng rồi, đặt đi em.", wants_more=False)
    assert reasons and "OD1" in reasons[0]
    assert actions._order_create({"sku": "B", "price_vnd": 2_000_000, "payment": "bank"}, tier="VERIFIED", has_phone=True,
                                 quotes={"B": 2_000_000}, trusted=frozenset({"A", "B"}), created=placed,
                                 customer_said="lấy thêm một cái nữa", wants_more=True) == []
