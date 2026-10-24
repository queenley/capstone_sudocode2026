"""The agent's own report of the memory it used (``facts_used``) reaches the BTC trace next to the extractor's items."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_harness.collector import merged_facts_used, reported_facts  # noqa: E402


class AgentFactsUsed(unittest.TestCase):
    def test_a_turn_result_reports_slots_sorted_and_once(self):
        self.assertEqual(reported_facts({"facts_used": ["price_quoted_vnd", "product_advised", "product_advised"]}),
                         ["price_quoted_vnd", "product_advised"])
        self.assertEqual(reported_facts({}), [])

    def test_a_malformed_report_is_refused(self):
        for bad in ("product_advised", [1], [""], None):
            with self.assertRaises(ValueError):
                reported_facts({"facts_used": bad})

    def test_the_trace_row_lists_the_extractors_items_then_the_agents_slots_once_each(self):
        items = [{"kind": "fact_usage", "slot_or_field": "sku"}, {"kind": "claim", "slot_or_field": "price"},
                 {"kind": "fact_usage", "slot_or_field": "product_advised"}]
        document = {"agent_facts_used": ["product_advised", "order_id"]}
        self.assertEqual(merged_facts_used(items, document), ["sku", "product_advised", "order_id"])
        self.assertEqual(merged_facts_used(items, {}), ["sku", "product_advised"])


if __name__ == "__main__":
    unittest.main()


class FirstToken(unittest.TestCase):
    def test_the_first_token_is_the_products_own_stamp_inside_the_turn(self):
        from agent.bridge import first_token_time

        start, end = "2026-10-24T10:00:00+00:00", "2026-10-24T10:00:04+00:00"
        self.assertEqual(first_token_time(start, end, 1500), "2026-10-24T10:00:01.500000+00:00")
        self.assertEqual(first_token_time(start, end, 9000), end)  # never after the end
        for missing in (None, "x", -1):
            self.assertIsNone(first_token_time(start, end, missing))
