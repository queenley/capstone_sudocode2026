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
        assert second.success_if.max_agent_questions == 3
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
                and (call.success_if.total_match_vnd or args["price_vnd"]) > 2_000_000:
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


def test_a_customer_past_the_address_ttl_says_they_moved(plans):
    from src.planning.planner import moved_address_errors

    ttl = [pc for sp in plans for pc in sp.calls if pc.memory_extra.get("address_ttl_check")]
    assert ttl and all("ĐÃ CHUYỂN NHÀ" in pc.scene for pc in ttl)
    # SCN-GEN-0001 as first written: the new address called the old one.
    bad = ["Chị muốn mua lại máy lọc không khí AirPure X như lần trước.",
           "Địa chỉ giao hàng vẫn như cũ nhé, Cầu Giấy, Hà Nội."]
    assert len(moved_address_errors(bad, "Cầu Giấy, Hà Nội")) == 2
    good = ["Chị muốn mua lại máy lọc không khí AirPure X như lần trước.",
            "Giờ chị chuyển về Cầu Giấy, Hà Nội rồi em, giao về đó nhé."]
    assert moved_address_errors(good, "Cầu Giấy, Hà Nội") == []


def test_a_purifier_is_never_advised_for_a_room_bigger_than_it_is_rated_for(all_scenarios):
    import json
    from src.utils.paths import CATALOG_DIR

    products = json.loads((CATALOG_DIR / "products.json").read_text(encoding="utf-8"))
    capacity = {p["sku"]: p["attributes"].get("room_area_m2") for p in (products if isinstance(products, list) else products["products"])}
    for scenario in all_scenarios:
        room = None
        for call in scenario.calls.values():
            room = call.facts_established.get("room_area_m2", room)
            sku = call.facts_established.get("product_advised")
            if room and capacity.get(sku):
                assert room <= capacity[sku], (scenario.scenario_id, sku, room)


def test_a_cod_order_needing_a_confirmation_call_says_so(all_scenarios):
    from src.planning.planner import COD_CONFIRMATION_PHRASES

    calls = [c for s in all_scenarios for c in s.calls.values() if c.ground_truth_facts.get("needs_confirmation_call")]
    assert calls
    # No call holds must_say_any for another phrase any more (the split order proves itself by order_group).
    for call in calls:
        assert set(call.success_if.must_say_any) == set(COD_CONFIRMATION_PHRASES), call.kind


def test_reference_agent_answers_and_does_not_close_with_anything_else():
    from src.pipeline.validate_rules import OUTBOUND_OPENING, closing_courtesy

    assert OUTBOUND_OPENING.search("Dạ em chào chị ạ, em gọi lại về máy lọc không khí chị quan tâm hôm qua.")
    assert not OUTBOUND_OPENING.search("Dạ em chào chị ạ, em là trợ lý ảo của shop, em có thể hỗ trợ gì cho mình ạ?")
    assert closing_courtesy("Dạ em đã ghi nhận ạ. Chị cần hỗ trợ thêm thông tin gì khác không ạ?")
    assert not closing_courtesy("Dạ em chào chị ạ, em có thể hỗ trợ gì cho mình hôm nay ạ?")
    assert not closing_courtesy("Chị có cần em gửi thêm hình ảnh sản phẩm không ạ?")


def test_policy_labels_read_the_blocker_and_the_delivery_window():
    def labels(**kw):
        base = dict(kind="consult", category="gia-dung/noi-chien", sku="SKU-AF-XM", persona="p", gt={}, si={},
                    stated={}, returning=False)
        return policies.for_call(**{**base, **kw})

    family = labels(stated={"blocker": "để bàn với gia đình"})
    assert "PB-03" in family and "PB-02" not in family          # "gia đình" is not a price objection
    hotline = labels(stated={"blocker": "muốn gọi hotline hỏi thêm"})
    assert "PB-03" not in hotline                                  # asking the shop is not asking the family
    assert "PB-02" in labels(stated={"objection": "giá cao hơn chỗ khác"})
    assert "VC-04" in labels(stated={"blocker": "muốn trả góp"})
    order = {"tool_called": "order.create", "args_match": {"payment": "bank"}}
    over_the_day_off = {"call_date": "2026-10-23", "estimated_delivery": "2026-10-29", "price_vnd": 1}
    assert "LN-03" in labels(kind="order", si=order, gt=over_the_day_off)
    assert "LN-03" not in labels(kind="order", si=order, gt={"call_date": "2026-10-27", "estimated_delivery": "2026-10-29"})


def test_a_promotion_met_by_buying_more_is_not_labelled_false(all_scenarios):
    # AIR-2ND-50 needs a second purifier: "mua thêm máy thứ hai giảm 50%" is a true offer to a one-item buyer.
    from src.utils.btc_tools import mock_tools

    promo = next(p for p in mock_tools().PROMOS if p["promo_code"] == "AIR-2ND-50")
    for scenario in all_scenarios:
        for call in scenario.calls.values():
            running = promo["start"] <= call.call_date.isoformat() <= promo["end"]
            if running and call.success_if.tool_called == "order.create" and not call.success_if.also_ordered:
                assert call.ground_truth_facts.get("promo_AIR-2ND-50_active") is not False, scenario.scenario_id


def test_the_call_brief_opening_answers_a_returning_caller(all_scenarios):
    from src.pipeline.validate_rules import OUTBOUND_OPENING

    briefs = [c.expected_call_brief for s in all_scenarios for c in s.calls.values() if c.expected_call_brief]
    assert briefs
    for brief in briefs:
        assert not OUTBOUND_OPENING.search(brief["suggested_opening"]), brief["suggested_opening"]


def test_asking_the_family_ends_with_a_booked_callback(all_scenarios):
    # PB-03: a set day and time, booked with schedule.callback, inside working hours (LN-01).
    calls = [c for s in all_scenarios for c in s.calls.values()
             if c.kind == "consult" and policies.FAMILY.search(str(c.facts_established.get("blocker") or ""))]
    assert calls
    for call in calls:
        assert call.success_if.tool_called == "schedule.callback", call.facts_established.get("blocker")
        assert call.success_if.args_match["callback_at"] == call.ground_truth_facts["callback_at"]   # not moved
        assert "LN-01" in call.relevant_policy_ids and "order.create" in call.success_if.must_not_call_tools


def test_a_record_of_several_is_never_superseded_and_a_change_is_said(plans, all_scenarios):
    for scenario in all_scenarios:
        for call in scenario.calls.values():
            assert not {"order_id", "owned_sku"} & set(call.memory_expectation.get("superseded", {})), scenario.scenario_id
    changed = [pc for sp in plans for pc in sp.calls if pc.changed]
    assert changed
    for pc in changed:
        assert "TỰ nói rõ mình đã đổi" in pc.scene and set(pc.changed) <= set(pc.customer_must_state)


def test_a_customer_with_a_second_room_hears_the_second_purifier_offer(advanced_scenarios):
    # rules.md 23 (KM-05, FAQ-19): told for a reason, with its conditions; one purifier keeps its own price.
    from src.planning.call_kinds import SECOND_ITEM_PHRASES

    for scenario in _by_persona(advanced_scenarios, "khach_hoi_may_thu_hai"):
        call = scenario.calls["call_1"]
        si, gt = call.success_if, call.ground_truth_facts
        assert set(si.must_say_any) == set(SECOND_ITEM_PHRASES) and not si.trace_must_not_match   # not a guardrail
        assert gt["promo_AIR-2ND-50_active"] is True and "order.create" in si.must_not_call_tools
        assert any(not isinstance(f, str) and f.field == "price_vnd" and f.value == gt["price_vnd:SKU-AP-X"] // 2
                   for f in si.forbidden_claims)
        assert "giảm 50% cả hai máy" in si.forbidden_claims and "price_vnd" not in gt   # each item its own price
        pitch, *wrong = si.say_at_most
        assert pitch.max == 3 and wrong and all(limit.max == 0 for limit in wrong)
        assert gt["price_vnd:SKU-AP-MINI"] > 0
        assert {"KM-05", "FAQ-19"} <= set(call.relevant_policy_ids)
        if "call_2" in scenario.calls:      # both purifiers in one order: the cheaper one at 50%
            orders = {tc["args"]["sku"]: tc["args"]["price_vnd"] for tc in _orders(scenario.calls["call_2"])}
            assert orders["SKU-AP-MINI"] * 2 < orders["SKU-AP-X"] and len(orders) == 2
