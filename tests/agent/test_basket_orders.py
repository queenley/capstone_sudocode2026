"""An order of several products: one order.create per line, the basket passed through, COD on the whole order (VC-03),
and a split into two orders only once the customer agreed (QT-01)."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from ai_agent_service.agents.advisor import ActionGuardMiddleware, AgentContext
from ai_agent_service.components.guardrails import actions
from ai_agent_service.mcp.server_base import ToolFailure
from ai_agent_service.mcp.servers import btc, crm

SIX_M = 6_000_000
QUOTES = {"SKU-A": SIX_M, "SKU-B": SIX_M}


@pytest.fixture
def mock_without_database(monkeypatch):
    """btc.call against the organisers' mock in memory: no Postgres, the same arguments and envelope."""
    async def call(name, fn, /, *, idempotency_key=None, **kwargs):
        return btc.unwrap(name, btc.enrich(name, fn(**{k: v for k, v in kwargs.items() if v is not None})))
    monkeypatch.setattr(btc, "call", call)


@pytest.mark.asyncio
async def test_two_purifiers_order_with_the_second_item_discount(mock_without_database):
    on, phone = btc.reference_date(), "0911000201"
    second = btc.mock().pricing_get_quote("SKU-AP-X", on, 1, phone, None, ["SKU-SS-AX40"])
    assert "AIR-2ND-50" in {p["promo_code"] for p in second["applied_promos"]}
    first = await crm.order_create(sku="SKU-SS-AX40", price_vnd=6_490_000, payment="bank", customer_phone=phone,
                                   basket_skus=["SKU-AP-X"], on=on)
    placed = await crm.order_create(sku="SKU-AP-X", price_vnd=second["final_price_vnd"], payment="bank",
                                    customer_phone=phone, basket_skus=["SKU-SS-AX40"], on=on)
    assert first["status"] == placed["status"] == "created"
    assert placed["total_vnd"] == second["final_price_vnd"] < second["list_price_vnd"]
    # Without the basket the mock prices one unit alone: the discounted price is refused.
    with pytest.raises(ToolFailure) as refused:
        await crm.order_create(sku="SKU-AP-X", price_vnd=second["final_price_vnd"], payment="bank",
                               customer_phone=phone, on=on)
    assert refused.value.code == "PRICE_MISMATCH"


def _check(args, placed=(), agent="", customer=""):
    return actions.check("order_create", args, tier="VERIFIED", mode="speak", has_phone=True, quotes=QUOTES,
                         trusted=frozenset(QUOTES), placed=placed, last_agent_said=agent, customer_said=customer)


def _line(sku, payment="COD", group=None, order_id="OD1"):
    return {"order_id": order_id, "sku": sku, "qty": 1, "price_vnd": SIX_M, "payment": payment, "order_group": group}


def test_two_six_million_items_on_cod_are_refused():
    verdict = _check({"sku": "SKU-B", "price_vnd": SIX_M, "payment": "COD"}, placed=[_line("SKU-A")])
    assert not verdict.passed and "12.000.000" in verdict.reasons[0] and "tách" in verdict.reasons[0]
    assert _check({"sku": "SKU-B", "price_vnd": SIX_M, "payment": "bank"}, placed=[_line("SKU-A")]).passed
    assert _check({"sku": "SKU-A", "price_vnd": SIX_M, "payment": "COD"}).passed


def test_a_split_into_two_orders_needs_the_customers_agreement():
    line = {"sku": "SKU-A", "price_vnd": SIX_M, "payment": "COD", "order_group": "1"}
    assert not _check(line, customer="ok em").passed
    asked = "Dạ đơn trên 10 triệu không COD được, anh có muốn em tách thành hai đơn không ạ?"
    assert _check(line, agent=asked, customer="ừ được em").passed
    # The second order of the split: the call already has a group, each order is checked on its own.
    second = {"sku": "SKU-B", "price_vnd": SIX_M, "payment": "COD", "order_group": "2"}
    assert _check(second, placed=[_line("SKU-A", group="1")]).passed
    same = {**second, "order_group": "1"}
    assert "Đơn tách 1" in _check(same, placed=[_line("SKU-A", group="1")]).reasons[0]


def test_the_same_sku_in_the_other_half_of_a_split_is_not_a_repeated_order():
    # Upstream's guard books a product once a call; a split (QT-01) of two units of one sku is two orders.
    first = _line("SKU-A", group="1")
    created = [{"order_id": "OD1", "sku": "SKU-A"}]
    other_half = {"sku": "SKU-A", "price_vnd": SIX_M, "payment": "COD", "order_group": "2"}
    assert actions.check("order_create", other_half, tier="VERIFIED", mode="speak", has_phone=True, quotes=QUOTES,
                         trusted=frozenset(QUOTES), placed=[first], created=created).passed
    repeat = {"sku": "SKU-A", "price_vnd": SIX_M, "payment": "COD"}
    refused = actions.check("order_create", repeat, tier="VERIFIED", mode="speak", has_phone=True, quotes=QUOTES,
                            trusted=frozenset(QUOTES), placed=[first], created=created)
    assert not refused.passed and "đã tạo trong cuộc này" in refused.reasons[0]


@pytest.mark.asyncio
async def test_the_guard_counts_a_line_placed_earlier_in_the_same_run():
    earlier = AIMessage(content="", tool_calls=[{"id": "c1", "name": "order_create",
                                                 "args": {"sku": "SKU-A", "price_vnd": SIX_M, "payment": "COD"}}])
    answer = ToolMessage(name="order_create", tool_call_id="c1",
                         content=json.dumps({"ok": True, "data": {"order_id": "OD600001", "status": "created"}}))
    context = AgentContext(call_id="test", tier="VERIFIED", customer_phone="0911000202", quotes=QUOTES)
    call = {"id": "c2", "name": "order_create", "args": {"sku": "SKU-B", "price_vnd": SIX_M, "payment": "COD"}}
    request = SimpleNamespace(tool_call=call, runtime=SimpleNamespace(context=context),
                              state={"messages": [earlier, answer]})
    handler = AsyncMock()
    result = await ActionGuardMiddleware().awrap_tool_call(request, handler)
    assert result.additional_kwargs["blocked_by"] == "guardrail" and "12.000.000" in json.loads(result.content)["error"]["message"]
    handler.assert_not_awaited()
    # Lines seen twice (state and an earlier turn) count once.
    assert len(actions.placed_lines([{"name": "order.create", "args": call["args"],
                                      "result": {"ok": True, "data": {"order_id": "OD9"}}}] * 2)) == 1
