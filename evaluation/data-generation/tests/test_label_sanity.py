"""Label mistakes met while adding the BTC 11/2026 scenarios (SCN-ADV-0155..0160), kept from coming back.

Each was a label the oracle still scored perfect, so only a reader or the judge caught it:
- a call on the shop's day off (LN-02);
- a COD order above 2.000.000đ whose confirmation call (VC-05) was not required;
- a budget taken from ONE unit's quote in an order of several (J11 then saw every order as over budget);
- a reason to put the purchase off ("chờ cuối tháng nhận lương") in a call that closes an order.
"""
from collections import Counter

from src.planning.call_kinds import ORDERING_KINDS
from src.planning.planner import COD_LIMIT_VND
from src.utils.btc_tools import mock_tools

#: Kinds that state a budget below the order on purpose (BTC hard case: over budget, J11).
OVER_BUDGET_BY_DESIGN = {"order_multi", "order_split"}


def _calls(plans):
    for sp in plans:
        for pc in sp.calls:
            yield sp, pc


def test_no_call_on_a_day_off_unless_it_moves_a_callback(plans, advanced_plans):
    for sp, pc in _calls([*plans, *advanced_plans]):
        if pc.call_date.isoformat() in mock_tools().HOLIDAYS:
            assert pc.kind == "consult_callback_holiday", (sp.scenario_id, pc.name, pc.call_date, pc.kind)


def test_an_order_call_never_puts_the_purchase_off(plans, advanced_plans):
    for sp, pc in _calls([*plans, *advanced_plans]):
        if pc.kind in ORDERING_KINDS and pc.outcome == "chot_don":
            assert "blocker" not in pc.customer_must_state, (sp.scenario_id, pc.name, pc.customer_must_state["blocker"])


def test_a_cod_order_above_two_million_asks_for_the_confirmation_call(plans, advanced_plans):
    for sp, pc in _calls([*plans, *advanced_plans]):
        created = [t for t in pc.oracle_tool_calls if t["name"] == "order.create" and not t["result"].get("error")]
        if any(t["result"].get("needs_confirmation_call") for t in created):
            assert pc.ground_truth.get("needs_confirmation_call") is True, (sp.scenario_id, pc.name)
            assert pc.success_if.must_say_any, (sp.scenario_id, pc.name)


def test_a_budget_covers_the_whole_order_unless_the_case_is_over_budget(plans, advanced_plans):
    for sp, pc in _calls([*plans, *advanced_plans]):
        budget, total = pc.customer_must_state.get("budget_vnd"), pc.ground_truth.get("total_vnd")
        if pc.outcome == "chot_don" and budget and total and pc.kind not in OVER_BUDGET_BY_DESIGN:
            assert budget >= total, (sp.scenario_id, pc.name, pc.kind, budget, total)


def test_order_units_follow_btc_11_2026(advanced_plans):
    """pricing.quote_order, then ONE order.create with lines; AIR-2ND-50 on exactly one unit; the totals agree."""
    seen = 0
    for sp, pc in _calls(advanced_plans):
        if pc.kind != "order_units":
            continue
        seen += 1
        names = [t["name"] for t in pc.oracle_tool_calls]
        assert names.count("order.create") == 1 and "pricing.quote_order" in names, (sp.scenario_id, names)
        quote = next(t["result"] for t in pc.oracle_tool_calls if t["name"] == "pricing.quote_order")
        order = next(t for t in pc.oracle_tool_calls if t["name"] == "order.create")
        lines = order["args"]["lines"]
        assert len({(l["sku"], l["price_vnd"]) for l in lines}) == len(lines)     # one line per product and price
        assert sum(l["qty"] for l in lines) == len(quote["units"]) >= 2
        assert Counter(a["promo_code"] for u in quote["units"] for a in u["applied_promos"])["AIR-2ND-50"] == 1
        total = quote["total_vnd"]
        assert order["result"]["total_vnd"] == total == pc.success_if.total_match_vnd == pc.ground_truth["total_vnd"]
        assert total not in {f.value for f in pc.success_if.forbidden_claims if getattr(f, "field", None) == "total_vnd"}
        if total > COD_LIMIT_VND:   # VC-03: no COD; the customer hears the limit (J11)
            assert pc.success_if.args_match["payment"] == "bank"
            assert "10 triệu" in pc.success_if.must_say_any
        assert "room_area_m2" not in pc.customer_must_state and "has_children" not in pc.customer_must_state
    assert seen >= 6
