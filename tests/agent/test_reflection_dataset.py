"""data/policy-regression, what the product must do right from R0: it loads as the evaluation loads it, the frozen set is never learned
from, every customer is a different one, and each expected order, price and stock state is the organisers' mock's on
the day of the call. No model call."""

import importlib.util
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest

from ai_agent_service.components.improvement import lessons
from ai_agent_service.config.config_manager import btc_data_dir
from ai_agent_service.pipeline.eval import scenarios as loader

SET = Path(__file__).resolve().parents[2] / "data" / "policy-regression" / "after-sale-and-delivery"


def mock():
    spec = importlib.util.spec_from_file_location("btc_mock_tools_for_set", btc_data_dir() / "eval" / "mock_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(name):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((SET / name / "scenarios").glob("*.json"))]


def meta(name):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((SET / name / "metadata").glob("*.json"))}


@pytest.mark.parametrize("name", ["learn", "frozen"])
def test_the_evaluation_loads_every_scenario(name):
    loaded, rejected = loader.load(SET / name / "scenarios")
    assert rejected == [] and len(loaded) == len(read(name))


def test_the_frozen_set_is_listed_and_shares_no_scenario_or_customer_with_the_learning_set():
    learn, frozen = read("learn"), read("frozen")
    assert json.loads((SET / "frozen.json").read_text(encoding="utf-8")) == [s["scenario_id"] for s in frozen]
    phones = [s["customer_phone"] for s in learn + frozen]
    assert len(phones) == len(set(phones))


def test_each_lesson_has_enough_learning_customers_and_frozen_cases_and_controls_guard_against_harm():
    learn, frozen = Counter(), Counter()
    for counts, name in ((learn, "learn"), (frozen, "frozen")):
        for tags in meta(name).values():
            assert tags["situation"] in lessons.situations()
            counts[(tags["target"], tags["situation"])] += 1
    for key, count in learn.items():
        if key[0] == "skill_gap":
            assert count >= lessons.MIN_SUPPORT and frozen[key] >= 3
    assert sum(c for (target, _), c in frozen.items() if target == "control") >= sum(
        c for (target, _), c in frozen.items() if target == "skill_gap")


@pytest.mark.parametrize("name", ["learn", "frozen"])
def test_every_expected_order_price_and_stock_is_the_mock_s_on_the_day_of_the_call(name):
    tools = mock()
    for scenario in read(name):
        days = loader.call_days(scenario)
        for call, spec in scenario["calls"].items():
            on = days[call]
            success = spec.get("success_if") or {}
            truth = spec.get("ground_truth_facts") or {}
            if success.get("tool_called") == "order.create":
                args = success["args_match"]
                assert tools.inventory_check(args["sku"], on)["in_stock"], (scenario["scenario_id"], call)
                assert tools.pricing_get_quote(args["sku"], on)["final_price_vnd"] == args["price_vnd"] == truth["price_vnd"]
            if success.get("tool_called") == "inventory.check":
                assert truth["in_stock"] is False
            if success.get("tool_called") == "order.update":
                assert tools.inventory_check(success["args_match"]["new_variant_sku"], on)["in_stock"]


def test_a_return_the_policy_refuses_is_past_its_window_or_opened():
    tools = mock()
    for scenario in read("learn") + read("frozen"):
        first, second = scenario["calls"]["call_1"], scenario["calls"]["call_2"]
        if "warranty_months" not in (second.get("ground_truth_facts") or {}):
            continue
        sku = first["success_if"]["args_match"]["sku"]
        days = loader.call_days(scenario)
        elapsed = (date.fromisoformat(days["call_2"]) - date.fromisoformat(days["call_1"])).days
        assert elapsed > 30, scenario["scenario_id"]  # past DT-01's 7 days and DT-05's 30
        product = next(p for p in tools.PRODUCTS if p["sku"] == sku)
        months = product["attributes"]["warranty_months"]
        assert second["ground_truth_facts"]["warranty_months"] == months
        assert date.fromisoformat(days["call_1"]) + timedelta(days=months * 30) > date.fromisoformat(days["call_2"])


GAPS = Path(__file__).resolve().parents[2] / "data" / "policy-regression" / "paraphrase"


@pytest.mark.parametrize("name", ["learn", "frozen"])
def test_the_gap_loop_set_loads_and_its_customers_are_new(name):
    loaded, rejected = loader.load(GAPS / name / "scenarios")
    assert rejected == [] and loaded
    phones = [json.loads(p.read_text(encoding="utf-8"))["customer_phone"] for d in (GAPS, SET)
              for p in d.glob("*/scenarios/*.json")]
    assert len(phones) == len(set(phones))


LOOP = Path(__file__).resolve().parents[2] / "data" / "gap-loop"


def test_the_gap_loop_set_asks_only_what_the_documents_never_cover_and_loads():
    from ai_agent_service.components.improvement.gap import gate

    for name in ("learn", "frozen"):
        loaded, rejected = loader.load(LOOP / name / "scenarios")
        assert rejected == [] and loaded
    data = Path(__file__).resolve().parents[2] / "data"
    ours = [*data.glob("gap-loop/*/scenarios/*.json"), *data.glob("policy-regression/**/scenarios/*.json"),
            *data.glob("reflection/*/scenarios/*.json")]  # the proof sets: new customers only, one each
    phones = [json.loads(p.read_text(encoding="utf-8"))["customer_phone"] for p in ours]
    assert len(phones) == len(set(phones))
    for item in json.loads((LOOP / "answers.json").read_text(encoding="utf-8")):
        assert item["source"] == "consultant" and gate(item["question"], item["answer"]) == ()
    frozen = json.loads((LOOP / "frozen.json").read_text(encoding="utf-8"))
    assert not set(frozen) & {p.stem for p in (LOOP / "learn" / "scenarios").glob("*.json")}


CONDUCT = Path(__file__).resolve().parents[2] / "data" / "reflection" / "conduct"


@pytest.mark.parametrize("name", ["learn", "frozen"])
def test_the_conduct_set_loads_and_every_order_and_price_is_the_mock_s(name):
    loaded, rejected = loader.load(CONDUCT / name / "scenarios")
    assert rejected == [] and loaded
    tools = mock()
    for path in sorted((CONDUCT / name / "scenarios").glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        days = loader.call_days(scenario)
        for call, spec in scenario["calls"].items():
            success = spec.get("success_if") or {}
            if success.get("tool_called") == "order.create":
                args = success["args_match"]
                assert tools.pricing_get_quote(args["sku"], days[call])["final_price_vnd"] == args["price_vnd"]
            if "must_not_ask" in spec:  # what may not be asked again was established in an earlier call
                earlier = {k for c, s in scenario["calls"].items() if c < call for k in s.get("facts_established") or {}}
                assert set(spec["must_not_ask"]) <= earlier, (path.name, call)
