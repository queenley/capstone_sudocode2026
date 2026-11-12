"""data/hard-cases: the scenarios load as the evaluation loads them, each price is the organisers' mock's on the day,
each product is in stock, and what a scenario requires or forbids is consistent with BH-05. No model call."""

import json
from pathlib import Path

from ai_agent_service.components.improvement import lessons, signals
from ai_agent_service.pipeline.eval import scenarios as loader
from tests.agent.test_reflection_dataset import mock

SET = Path(__file__).resolve().parents[2] / "data" / "hard-cases" / "scenarios"


def read():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SET.glob("*.json"))]


def test_the_hard_cases_load_and_every_price_is_the_mock_s_on_the_day():
    loaded, rejected = loader.load(SET)
    assert rejected == [] and len(loaded) == len(read()) == 5
    tools = mock()
    phones = [s["customer_phone"] for s in read()]
    assert len(phones) == len(set(phones))
    for scenario in read():
        spec = scenario["calls"]["call_1"]
        truth = spec["ground_truth_facts"]
        # A call about two products states each price under its product: the grader compares a bare ``price_vnd``
        # claim with one value only, and the second product's price then counts as a false claim.
        prices = {**({truth["sku"]: truth["price_vnd"]} if "sku" in truth else {}),
                  **{key.split(":", 1)[1]: value for key, value in truth.items() if key.startswith("price_vnd:")}}
        assert prices, scenario["scenario_id"]
        for sku, price in prices.items():
            assert tools.pricing_get_quote(sku, spec["call_date"])["final_price_vnd"] == price, scenario["scenario_id"]
            assert tools.inventory_check(sku, spec["call_date"])["in_stock"], scenario["scenario_id"]
        assert set(spec["relevant_policy_ids"]) <= set(lessons.rule_texts())


def test_the_extended_warranty_cases_stand_on_either_side_of_the_rule_s_price():
    by_id = {s["scenario_id"]: s["calls"]["call_1"] for s in read()}
    below, above = by_id["SCN-HARD-03"], by_id["SCN-HARD-04"]
    assert below["ground_truth_facts"]["price_vnd"] < 3_000_000 < above["ground_truth_facts"]["price_vnd"]
    assert "3.000.000đ" in lessons.rule_texts()["BH-05"] and "8%" in lessons.rule_texts()["BH-05"]
    # 8% of the price is the amount the assistant must not work out itself (its rule 1).
    assert above["success_if"]["forbidden_claims"] == [f"{above['ground_truth_facts']['price_vnd'] * 8 // 100:,}".replace(",", ".")]


def test_the_grader_passes_a_right_answer_and_fails_the_failure_each_case_was_written_for():
    check = signals.grader().check_call
    by_id = {s["scenario_id"]: s["calls"]["call_1"] for s in read()}

    def rows(text, tools=()):
        return [{"turn": 1, "customer_text": "x", "agent_text": text, "tool_calls": [{"name": t, "args": {}} for t in tools]}]

    assert check(by_id["SCN-HARD-01"], rows("Dạ thời gian xử lý 7–15 ngày làm việc ạ."))[0]
    assert not check(by_id["SCN-HARD-01"], rows("Dạ em chưa có thông tin, em chuyển nhân viên ạ.", ["handoff.transfer"]))[0]
    assert check(by_id["SCN-HARD-02"], rows("Dạ nồi Philips 6.2L giá 3.990.000đ ạ."))[0]
    assert not check(by_id["SCN-HARD-02"], rows("Dạ nồi Philips 6.2L giá 3.990.000đ ạ.", ["handoff.transfer"]))[0]
    assert check(by_id["SCN-HARD-03"], rows("Dạ gói chỉ áp dụng cho gia dụng trên 3.000.000đ nên quạt này chưa thuộc diện ạ."))[0]
    assert not check(by_id["SCN-HARD-03"], rows("Dạ anh có thể mua thêm gói 12 tháng, áp dụng cho gia dụng trên 3.000.000đ ạ."))[0]
    assert check(by_id["SCN-HARD-04"], rows("Dạ được ạ, phí bằng 8% giá sản phẩm, mua trong 15 ngày từ ngày nhận hàng."))[0]
    assert not check(by_id["SCN-HARD-04"], rows("Dạ phí 8% giá sản phẩm, tức 615.200đ ạ."))[0]
    assert check(by_id["SCN-HARD-05"], rows("Dạ AirPure Y giá 5.200.000đ, đổi trả trong 7 ngày kể từ ngày nhận hàng ạ."))[0]
    assert not check(by_id["SCN-HARD-05"], rows("Dạ AirPure Y giá 5.200.000đ ạ."))[0]


def test_a_chat_without_a_channel_identity_is_the_scenario_s_customer_and_one_with_it_is_known_by_it_alone():
    """The organisers' SAMPLE-06 continues a hotline call on zalo_oa with no identity and expects the order placed."""
    sample = json.loads((Path(__file__).resolve().parents[2] / "apps" / "ai-agent-service" / "data" / "btc" / "test_set"
                         / "public_sample" / "SAMPLE-06.json").read_text(encoding="utf-8"))
    channel, keys = loader.connection(sample, sample["calls"]["call_2"])
    assert channel == "zalo" and keys == {"caller_phone": sample["customer_phone"], "zalo_id": None, "fb_id": None}
    scenario = {"scenario_id": "S", "customer_phone": "0900000001"}
    assert loader.connection(scenario, {"channel": "chat_fanpage", "channel_identity": "fb.x.1"})[1] == {
        "caller_phone": None, "zalo_id": None, "fb_id": "fb.x.1"}
    assert loader.connection(scenario, {"channel": "zalo_oa", "channel_identity": "zalo.x.1"})[1]["caller_phone"] is None
    assert loader.connection(scenario, {"channel": "web_chat"})[1] == {"caller_phone": None, "zalo_id": None, "fb_id": None}
    assert loader.connection(scenario, {})[1]["caller_phone"] == "0900000001"


def test_a_run_s_gap_is_a_turn_the_assistant_could_not_answer_not_one_the_search_found_nothing_for():
    from ai_agent_service.components.improvement import gaps

    def row(turn, customer, agent, tools=()):
        return {"scenario_id": "S", "call": "call_1", "turn": turn, "customer_text": customer, "agent_text": agent,
                "tool_calls": [{"name": name, "args": args} for name, args in tools]}

    rows = [row(1, "Bên em có gói quà không?", "Dạ hiện em chưa có thông tin về gói quà ạ."),
            row(2, "Dạ chị hiểu rồi, cảm ơn em.", "Dạ vâng ạ."),
            row(3, "Bên em có showroom không?", "Dạ em chuyển nhân viên ạ.",
                [("handoff.transfer", {"brief": {"escalation_reason": "ngoai_pham_vi_tai_lieu"}})])]
    diagnostics = [{"scenario_id": "S", "call": "call_1", "turn": turn, "knowledge": {"abstain": "no_match"}} for turn in (1, 2)]
    recorded = []
    original, gaps.record = gaps.record, lambda question, **kw: recorded.append(question) or "id"
    try:
        assert gaps.record_from_run(rows, diagnostics) == 2
    finally:
        gaps.record = original
    assert recorded == ["Bên em có gói quà không?", "Bên em có showroom không?"]
