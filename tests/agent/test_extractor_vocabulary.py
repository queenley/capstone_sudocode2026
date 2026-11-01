"""The extractor's prompt, vocabularies and rules agree with each other and with BTC's scenarios."""
import glob
import json
import re
from pathlib import Path

import pytest

from ai_agent_service.components.evaluation import scorers
from ai_agent_service.config.config_manager import btc_data_dir


def btc_names(fields):
    names = set()
    for path in glob.glob(str(btc_data_dir() / "test_set/**/*.json"), recursive=True):
        scenario = json.loads(Path(path).read_text(encoding="utf-8"))
        for call in (scenario.get("calls") or {}).values():
            for field in fields:
                names |= set(call.get(field) or ())
    return names


def prompt():
    return scorers.instructions()


def rows(heading):
    """The ``- name (type): ...`` rows under ``# heading`` of the prompt."""
    section = re.search(rf"^# {heading}\n(.*?)(?=^# [A-Z])", prompt(), re.S | re.M).group(1)
    return re.findall(r"^- ([A-Za-z0-9_<>]+) \(", section, re.M)


def item(kind, slot, qtype=None, **extra):
    return {"kind": kind, "slot_or_field": slot, "value": None, "question_type": qtype, "speaker": "agent",
            "source_field": "agent_text", "quote": "x", "start": 0, "end": 1, "purpose": "p", **extra}


def test_every_slot_btc_scores_on_is_in_the_vocabulary():
    names = btc_names(("must_not_ask", "must_carry_over"))
    assert names and names <= scorers.vocabulary()


def test_every_slot_btc_establishes_is_in_the_vocabulary():
    names = btc_names(("facts_established",))
    assert "channel" in names and names <= scorers.vocabulary()


def test_every_claim_field_btc_checks_can_be_extracted():
    fields, forbidden = set(), set()
    for path in glob.glob(str(btc_data_dir() / "test_set/**/*.json"), recursive=True):
        for call in json.loads(Path(path).read_text(encoding="utf-8"))["calls"].values():
            fields |= set(call.get("ground_truth_facts") or ())
            forbidden |= {c["field"] for c in (call.get("success_if") or {}).get("forbidden_claims", ()) if isinstance(c, dict)}
    assert fields and forbidden
    for field in fields | forbidden:
        assert field in scorers.CLAIM_FIELDS or scorers.PROMO_FIELD.match(field), field


def test_the_prompt_defines_exactly_the_vocabulary_once_each():
    names = rows("SLOT LIST")
    assert len(names) == len(set(names)) and set(names) == set(scorers.vocabulary())


def test_the_prompt_defines_exactly_the_claim_fields():
    names = rows("CLAIM FIELDS")
    assert len(names) == len(set(names)) and set(names) == set(scorers.CLAIM_FIELDS) | {"promo_<CODE>_active"}


def test_the_prompt_output_format_names_the_item_keys():
    block = re.search(r"# OUTPUT FORMAT.*?```json\n(.*?)\n```", prompt(), re.S).group(1)
    assert set(re.findall(r'^\s{6}"(\w+)":', block, re.M)) == set(scorers.Item.model_fields)


def test_the_prompt_examples_are_valid_items_kept_whole():
    examples = re.findall(r"INPUT DATA:\n(\{.*?\})\n\nOutput:\n```json\n(.*?)\n```", prompt(), re.S)
    assert len(examples) >= 3
    for raw_input, raw_output in examples:
        data, items = json.loads(raw_input), json.loads(raw_output)["items"]
        for i in items:
            assert set(i) == set(scorers.Item.model_fields)
            assert scorers.field_text(data, i["source_field"])[i["start"]:i["end"]] == i["quote"]
            assert (i["kind"] == "question") == (i["question_type"] is not None)
            if i["kind"] == "fact_usage":
                assert i["purpose"] and "previous_sessions" in data
        labels = scorers.label_items(items, data)
        assert (labels["items"], labels["dropped"], labels["changed"]) == (items, 0, 0)


def test_the_prompt_never_contains_the_marker_that_splits_the_turn():
    assert scorers.MARKER.strip() not in prompt()


def test_a_question_outside_the_vocabulary_is_other_and_never_a_confirm():
    kept, changed = scorers.restrict([item("question", "shoe_size", "confirm"), item("question", "size", "confirm", start=5, end=6)])
    assert [(i["slot_or_field"], i["question_type"]) for i in kept] == [("other", "open"), ("size", "confirm")]
    assert changed == 2


def test_channel_keeps_its_slot():
    kept, changed = scorers.restrict([item("question", "channel", "confirm"), item("fact_usage", "channel", start=3, end=4)])
    assert [(i["kind"], i["slot_or_field"]) for i in kept] == [("question", "channel"), ("fact_usage", "channel")]
    assert changed == 0


def test_an_order_read_back_is_one_confirm_question_and_never_a_fact():
    kept, changed = scorers.restrict([item("question", "order_summary", "confirm"),
                                      item("fact_usage", "order_summary", start=3, end=4),
                                      item("fact_usage", "payment", start=5, end=6)])
    assert [(i["kind"], i["slot_or_field"], i["question_type"]) for i in kept] == [
        ("question", "order_summary", "confirm"), ("fact_usage", "payment", None)]
    assert changed == 1
    assert "order_summary" in prompt() and scorers.VERSION.endswith("v5")


def test_a_fact_use_outside_the_vocabulary_is_dropped():
    kept, _ = scorers.restrict([item("fact_usage", "date"), item("fact_usage", "order_id", start=2, end=3)])
    assert [i["slot_or_field"] for i in kept] == ["order_id"]


def test_a_named_promotion_is_also_promo_active_and_a_duplicate_is_kept_once():
    named = {**item("claim", "promo_RUN-10_active"), "value": True}
    plain = {**named, "slot_or_field": "promo_active"}
    kept, _ = scorers.restrict([named, plain])
    assert [i["slot_or_field"] for i in kept] == ["promo_RUN-10_active", "promo_active"]


def test_two_observations_of_one_slot_at_different_places_are_both_kept():
    kept, changed = scorers.restrict([item("question", "payment", "open"), item("question", "payment", "open", start=20, end=21)])
    assert (len(kept), changed) == (2, 0)


def test_only_the_agent_asks():
    kept, changed = scorers.restrict([{**item("question", "payment", "open"), "speaker": "tool"}])
    assert (kept, changed) == ([], 1)


@pytest.mark.parametrize("name", ["previous_sessions", "previous_sessions/0", "customer_text", "tool_texts/9"])
def test_only_the_turn_can_be_quoted(name):
    data = scorers.turn_input("a", previous_sessions=[{"call": "call_1", "turns": [{"customer": "k", "agent": "a"}]}])
    assert scorers.field_text(data, name) is None
    assert scorers.spanned([{"source_field": name, "quote": "a"}], data) == ([], 1)


def test_a_quote_found_once_gets_its_true_offsets():
    data = scorers.turn_input("Dạ chị thanh toán COD hay chuyển khoản ạ?")
    kept, dropped = scorers.spanned([item("question", "payment", "open", quote="COD hay chuyển khoản", start=99, end=0)], data)
    assert dropped == 0 and data["agent_text"][kept[0]["start"]:kept[0]["end"]] == "COD hay chuyển khoản"
