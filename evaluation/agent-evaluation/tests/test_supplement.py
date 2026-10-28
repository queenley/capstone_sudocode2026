"""The latency without warm-up and Calls-to-Close beside BTC's table."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.criteria.calls_to_close import closing  # noqa: E402
from src.criteria.latency import latency_without_warmup, p95  # noqa: E402
from src.steps.score.supplement import build  # noqa: E402


def row(turn, ttft, total=None, call="call_1", sid="S1"):
    return {"scenario_id": sid, "call": call, "turn": turn, "latency": {"ttft_ms": ttft, "total_ms": total or ttft}}


def timing(turn, warm, call="call_1", sid="S1"):
    return {"context": {"scenario_id": sid, "call": call, "turn": turn}, "warmup": warm}


class Supplement(unittest.TestCase):
    def test_p95_is_the_organisers(self):
        self.assertEqual(p95(list(range(1, 101))), 96)
        self.assertEqual(p95([7]), 7)
        self.assertIsNone(p95([]))

    def test_the_marked_warmup_turns_are_left_out_of_the_percentiles(self):
        trace = [row(t, 10_000 if t <= 3 else 100) for t in range(1, 11)]
        result = latency_without_warmup(trace, [timing(t, t <= 3) for t in range(1, 11)])
        self.assertEqual((result["warmup_turns_dropped"], result["n_turns"]), (3, 7))
        self.assertEqual(result["ttft"], {"n": 7, "p50_ms": 100, "p95_ms": 100})
        self.assertIsNotNone(result["warning"])

    def test_calls_to_close_names_why_it_is_empty(self):
        official = {"calls_to_close": {"value": None, "n_closed": 0, "n_scenarios": 5}}
        verified = {"value": None, "numerator": 0, "denominator": 0, "status": "UNDEFINED"}
        result = closing(official, verified)
        self.assertIn("order.create", result["btc"]["reason"])
        self.assertIn("mock", result["verified"]["reason"])
        missing = closing(official, {**verified, "status": "INCOMPLETE"})
        self.assertIn("thiếu bằng chứng", missing["verified"]["reason"])

    def test_the_text_shows_both_rules_per_configuration(self):
        official = {"system": {"calls_to_close": {"value": 2.33, "n_closed": 3, "n_scenarios": 12}},
                    "baseline": {"calls_to_close": {"value": None, "n_closed": 0, "n_scenarios": 12}}}
        traces = {"full": [row(1, 100)], "baseline_no_memory": [row(1, 200)]}
        timings = {"full": [timing(1, False)], "baseline_no_memory": [timing(1, False)]}
        metrics = [{"metric_id": "full/verified_calls_to_close", "value": 2.5, "numerator": 5, "denominator": 2, "status": "MEASURED"},
                   {"metric_id": "baseline_no_memory/verified_calls_to_close", "value": None, "numerator": 0, "denominator": 0, "status": "UNDEFINED"}]
        summary, text = build(official, traces, timings, metrics)
        self.assertIn("BTC 2.33", text)
        self.assertIn("BTC n/a", text)
        self.assertEqual(summary["configs"]["full"]["calls_to_close"]["verified"]["value"], 2.5)


if __name__ == "__main__":
    unittest.main()
