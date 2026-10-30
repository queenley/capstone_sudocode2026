"""A COD order split in two, an order read back once, BTC's delivery_days from the team's delivery_estimate,
and the policy sections every call needs (relevant_policy_ids, rag/scenario_qa.json)."""
from src.pipeline.eval_rag import scenario_qa
from src.planning import policies
from src.planning.call_kinds import KIND_OUTCOME
from src.planning.personas import BTC_PLANS
from src.planning.personas_advanced import ADVANCED_PLANS
from src.utils.dataset import Dataset

COD_LIMIT = 10_000_000


def _by_persona(scenarios, persona):
    found = [s for s in scenarios if s.persona == persona]
    assert found, persona
    return found


def _orders(call):
    return [tc for tc in call.oracle_tool_calls if tc["name"] == "order.create"]


def test_a_cod_order_above_the_limit_is_split_in_two(advanced_scenarios):
    for scenario in _by_persona(advanced_scenarios, "khach_tach_don_cod"):
        call = scenario.calls["call_2"]
        orders = _orders(call)
        totals = {}
        for tc in orders:
            assert tc["args"]["payment"] == "COD" and tc["args"]["basket_skus"]
            totals[tc["args"]["order_group"]] = totals.get(tc["args"]["order_group"], 0) + tc["args"]["price_vnd"]
        assert set(totals) == {"1", "2"} and all(t <= COD_LIMIT for t in totals.values())
        assert sum(totals.values()) == call.success_if.total_match_vnd > COD_LIMIT
        assert call.success_if.args_match["order_group"] in {"1", "2"}
        assert call.ground_truth_facts["cod_allowed"] is False and call.ground_truth_facts["order_count"] == 2
        assert {"VC-03", "QT-01"} <= set(call.relevant_policy_ids)


def test_an_agreed_order_is_read_back_not_asked_again(advanced_scenarios):
    for scenario in _by_persona(advanced_scenarios, "khach_chot_don_doc_lai"):
        first, second = scenario.calls["call_1"], scenario.calls["call_2"]
        assert {"product_advised", "payment", "delivery_area"} <= set(second.must_not_ask)
        assert second.success_if.max_agent_questions == 5
        assert second.success_if.args_match["payment"] == first.facts_established["payment"]
        assert "payment" not in second.facts_established   # the customer does not say it again


def test_ordering_calls_carry_btc_delivery_days(all_scenarios):
    calls = [c for s in all_scenarios for c in s.calls.values() if _orders(c)]
    assert calls
    for call in calls:
        estimate = next(tc for tc in call.oracle_tool_calls if tc["name"] == "delivery_estimate")["result"]
        assert call.ground_truth_facts["delivery_days"] == estimate["delivery_days"] > 0
        assert call.ground_truth_facts["estimated_delivery"] == estimate["estimated_delivery"]


def test_outcomes_are_written_whole(all_scenarios):
    outcomes = {c["expected_outcome"] for s in all_scenarios for c in s.btc_export()["calls"].values()}
    assert "khac" not in outcomes and {"cap_nhat_don", "thong_tin"} <= outcomes


def test_policy_tables_name_real_kinds_personas_and_sections():
    assert set(policies.KIND_POLICIES) == set(KIND_OUTCOME)
    personas = {*BTC_PLANS, *ADVANCED_PLANS}
    assert set(policies.PERSONA_POLICIES) <= personas
    tables = [*policies.KIND_POLICIES.values(), *policies.CATEGORY_POLICIES.values(), *policies.SKU_POLICIES.values(),
              *policies.PERSONA_POLICIES.values()]
    assert {sid for ids in tables for sid in ids} <= set(policies.sections())


def test_policy_labels_follow_the_situation(all_scenarios):
    calls = [c for s in all_scenarios for c in s.calls.values()]
    assert sum(bool(c.relevant_policy_ids) for c in calls) > len(calls) * 0.7
    for call in calls:
        if call.kind == "future_promo":
            assert "KM-02" in call.relevant_policy_ids
        if call.ground_truth_facts.get("gift_sku"):
            assert "KM-07" in call.relevant_policy_ids
        args = call.success_if.args_match
        if call.success_if.tool_called == "order.create" and args.get("payment") == "COD" \
                and call.ground_truth_facts["price_vnd"] > 2_000_000:
            assert "QT-01" in call.relevant_policy_ids


def test_scenario_questions_are_in_btcs_qa_format(tmp_path, all_scenarios):
    dataset = Dataset(tmp_path)
    for scenario in all_scenarios[:20]:
        dataset.write_scenario(scenario)
    qa = scenario_qa(dataset)
    assert qa["questions"] and sum(qa["counts"].values()) == len(qa["questions"])
    for q in qa["questions"]:
        assert {"qid", "type", "question", "relevant_chunk_ids"} <= set(q) and q["relevant_chunk_ids"]
        assert q["type"] in {"single", "multi_hop", "version_conflict", "unanswerable", "restricted"}
