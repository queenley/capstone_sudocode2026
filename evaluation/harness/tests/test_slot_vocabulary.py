"""The harness extractor labels like the agent's own grading instrument (``components/evaluation/scorers.py``)."""
import glob
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from agent import slots  # noqa: E402

BTC = HERE / "evaluation-contracts/sources/btc"


def btc_slot_names():
    names = set()
    for path in glob.glob(str(BTC / "test_set/**/*.json"), recursive=True):
        data = json.load(open(path, encoding="utf-8"))
        for scenario in data if isinstance(data, list) else data.get("scenarios") or [data]:
            for call in (scenario.get("calls") or {}).values():
                for field in ("must_not_ask", "must_carry_over"):
                    names |= set(call.get(field, []))
    return names


class SlotVocabulary(unittest.TestCase):
    def test_every_slot_btc_scores_on_is_in_the_vocabulary(self):
        self.assertTrue(btc_slot_names())
        self.assertLessEqual(btc_slot_names(), slots.vocabulary())

    def test_the_prompt_carries_exactly_this_vocabulary(self):
        prompt = (HERE.parents[1] / "config/prompts/evaluation/extractor.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn(slots.prompt_block(), prompt)

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

    def test_the_instruments_grounding_rules_apply(self):
        kept, _ = slots.restrict([
            {"kind": "claim", "slot_or_field": "delivery_days", "value": 3, "quote": "xóa trong 3 ngày"},
            {"kind": "claim", "slot_or_field": "is_human", "value": True, "quote": "chào chị"}])
        self.assertEqual(kept, [])


if __name__ == "__main__":
    unittest.main()
