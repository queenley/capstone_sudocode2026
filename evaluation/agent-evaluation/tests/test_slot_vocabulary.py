"""The harness extractor labels like the agent's own grading instrument (``components/evaluation/scorers.py``)."""
import glob
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from src.services.agent import extract_command, slots  # noqa: E402

BTC = HERE / "contracts/sources/btc"
PROMPT = HERE.parents[1] / "config/prompts/evaluation/extractor.txt"


def btc_slot_names(fields=("must_not_ask", "must_carry_over")):
    names = set()
    for path in glob.glob(str(BTC / "test_set/**/*.json"), recursive=True):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for scenario in data if isinstance(data, list) else data.get("scenarios") or [data]:
            for call in (scenario.get("calls") or {}).values():
                for field in fields:
                    value = call.get(field) or ()
                    names |= set(value)
    return names


def prompt_text():
    return PROMPT.read_text(encoding="utf-8").replace("\r\n", "\n")


def named_rows(heading):
    """The ``- name (type): ...`` rows under ``# heading`` of the prompt, in order."""
    section = re.search(rf"^# {heading}\n(.*?)(?=^# [A-Z])", prompt_text(), re.S | re.M).group(1)
    return re.findall(r"^- ([A-Za-z0-9_<>]+) \(", section, re.M)


class SlotVocabulary(unittest.TestCase):
    def test_every_slot_btc_scores_on_is_in_the_vocabulary(self):
        self.assertTrue(btc_slot_names())
        self.assertLessEqual(btc_slot_names(), slots.vocabulary())

    def test_every_slot_btc_establishes_is_in_the_vocabulary(self):
        # facts_established is not scored for RQR or CCR, but BTC hand-checks the extractor against it.
        established = {name for name in btc_slot_names(("facts_established",))}
        self.assertIn("channel", established)
        self.assertLessEqual(established, slots.vocabulary())

    def test_every_claim_field_btc_checks_can_be_extracted(self):
        # ground_truth_facts is what hallucination_rate compares claims with; forbidden_claims is what task success
        # and the guardrails look for. A field the extractor cannot write could never be caught or confirmed.
        fields, forbidden = set(), set()
        for path in glob.glob(str(BTC / "test_set/**/*.json"), recursive=True):
            scenario = json.loads(Path(path).read_text(encoding="utf-8"))
            for call in scenario["calls"].values():
                fields |= set(call.get("ground_truth_facts") or ())
                for claim in (call.get("success_if") or {}).get("forbidden_claims", ()):
                    if isinstance(claim, dict):
                        forbidden.add(claim["field"])
        self.assertTrue(fields and forbidden)
        for field in fields | forbidden:
            with self.subTest(field=field):
                self.assertTrue(field in slots.scorers.CLAIM_FIELDS or slots.scorers.PROMO_FIELD.match(field), field)

    def test_a_question_about_the_channel_keeps_its_slot(self):
        kept, changed = slots.restrict([
            {"kind": "question", "slot_or_field": "channel", "question_type": "confirm"},
            {"kind": "fact_usage", "slot_or_field": "channel"}])
        self.assertEqual([(i["kind"], i["slot_or_field"]) for i in kept], [("question", "channel"), ("fact_usage", "channel")])
        self.assertEqual(changed, 0)

    def test_two_observations_of_one_slot_at_different_places_are_both_kept(self):
        at = lambda start: {"kind": "question", "slot_or_field": "payment", "question_type": "open",
                            "source_field": "agent_text", "start": start, "end": start + 5, "quote": "xxxxx"}
        kept, changed = slots.restrict([at(0), at(20)])
        self.assertEqual((len(kept), changed), (2, 0))

    def test_the_prompt_defines_exactly_this_vocabulary_once_each(self):
        rows = named_rows("SLOT LIST")
        self.assertEqual(len(rows), len(set(rows)))
        self.assertEqual(set(rows), set(slots.vocabulary()))

    def test_the_prompt_defines_exactly_the_claim_fields(self):
        rows = named_rows("CLAIM FIELDS")
        self.assertEqual(len(rows), len(set(rows)))
        self.assertEqual(set(rows), set(slots.scorers.CLAIM_FIELDS) | {"promo_<CODE>_active"})

    def test_the_marker_that_splits_the_input_data_is_not_in_the_prompt(self):
        # extract_command splits the request at this marker; one inside the prompt would cut it short.
        self.assertNotIn(extract_command.MARKER.strip(), prompt_text())

    def test_the_prompt_output_format_names_the_item_keys(self):
        block = re.search(r"# OUTPUT FORMAT.*?```json\n(.*?)\n```", prompt_text(), re.S).group(1)
        keys = set(re.findall(r'^\s{6}"(\w+)":', block, re.M))
        self.assertEqual(keys, set(extract_command.Item.model_fields))

    def test_the_prompt_examples_are_valid_items_that_the_restrictions_keep_whole(self):
        examples = re.findall(r"INPUT DATA:\n(\{.*?\})\n\nOutput:\n```json\n(.*?)\n```", prompt_text(), re.S)
        self.assertGreaterEqual(len(examples), 3)
        for raw_input, raw_output in examples:
            source, items = json.loads(raw_input), json.loads(raw_output)["items"]
            for item in items:
                self.assertEqual(set(item), set(extract_command.Item.model_fields))
                text = extract_command.field_text(source, item["source_field"])
                self.assertEqual(text[item["start"]:item["end"]], item["quote"], item)
                self.assertEqual(item["kind"] == "question", item["question_type"] is not None, item)
                self.assertTrue(item["kind"] != "fact_usage" or item["purpose"], item)
                if item["kind"] == "fact_usage":
                    self.assertIn("previous_sessions", source, "a reused fact needs an earlier session")
            self.assertEqual(len(items), len({json.dumps(i, sort_keys=True) for i in items}), "duplicate item")
            kept, changed = slots.restrict([dict(i) for i in items])
            self.assertEqual((kept, changed), (items, 0))

    def test_a_question_outside_the_vocabulary_is_other_and_never_a_confirm(self):
        kept, changed = slots.restrict([
            {"kind": "question", "slot_or_field": "shoe_size", "question_type": "confirm"},
            {"kind": "question", "slot_or_field": "size", "question_type": "confirm"}])
        self.assertEqual([(i["slot_or_field"], i["question_type"]) for i in kept], [("other", "open"), ("size", "confirm")])
        self.assertEqual(changed, 2)

    def test_a_fact_use_outside_the_vocabulary_is_dropped(self):
        kept, changed = slots.restrict([{"kind": "fact_usage", "slot_or_field": "date"},
                                        {"kind": "fact_usage", "slot_or_field": "order_id"}])
        self.assertEqual([i["slot_or_field"] for i in kept], ["order_id"])
        self.assertEqual(changed, 1)

    def test_claims_keep_to_the_organisers_fields_with_typed_values(self):
        claim = lambda field, value, quote="giá 5.200.000đ": {"kind": "claim", "slot_or_field": field, "value": value, "quote": quote}
        kept, _ = slots.restrict([claim("price_vnd", "5.200.000đ"), claim("order_status", "delivered"),
                                  claim("in_stock", "true"), claim("price_vnd", "rất rẻ")])
        self.assertEqual([(i["slot_or_field"], i["value"]) for i in kept], [("price_vnd", 5200000), ("in_stock", True)])

    def test_a_named_promotion_is_also_a_promo_active_claim(self):
        kept, _ = slots.restrict([{"kind": "claim", "slot_or_field": "promo_RUN-10_active", "value": True, "quote": "đang giảm"}])
        self.assertEqual([i["slot_or_field"] for i in kept], ["promo_RUN-10_active", "promo_active"])

    def test_the_same_observation_twice_is_kept_once(self):
        # A model that writes both the named promotion and promo_active would otherwise lose the turn to the
        # collector's duplicate check, or count one claim twice.
        named = {"kind": "claim", "slot_or_field": "promo_RUN-10_active", "value": True, "quote": "đang giảm",
                 "source_field": "agent_text", "start": 4, "end": 13, "purpose": "promotion"}
        plain = {**named, "slot_or_field": "promo_active", "purpose": "the same words, another note"}
        kept, changed = slots.restrict([named, plain])
        self.assertEqual([i["slot_or_field"] for i in kept], ["promo_RUN-10_active", "promo_active"])
        # One change for adding promo_active to the named promotion, one for setting the model's own copy aside.
        self.assertEqual(changed, 2)

    def test_the_instruments_grounding_rules_apply(self):
        kept, _ = slots.restrict([
            {"kind": "claim", "slot_or_field": "delivery_days", "value": 3, "quote": "xóa trong 3 ngày"},
            {"kind": "claim", "slot_or_field": "is_human", "value": True, "quote": "chào chị"}])
        self.assertEqual(kept, [])


if __name__ == "__main__":
    unittest.main()
