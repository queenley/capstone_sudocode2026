"""Synthetic offline regression only; never certifies Agent/A01–A18 PASS."""
import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

# Also works with `unittest discover -s evaluation/tests` outside workspace cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.eval_harness.contracts import ROOT, checker, validate
from evaluation.eval_harness.metrics import cost_per_completed_call, match_tool_calls

BTC = ROOT / "sources/btc"


def setUpModule():
    # Fail before importing/executing pinned BTC if any source hash has drifted.
    checker.main()


def tearDownModule():
    # Also prove BTC inventory was not changed by scorer imports/subprocesses.
    with redirect_stdout(io.StringIO()):
        checker.main()


class P0Test(unittest.TestCase):
    def setUp(self):
        self.examples = checker.read("examples.json")["valid"]
        self.labels = copy.deepcopy(self.examples["ExpectedToolCalls"]["data"])
        self.labels["allow_extra_read_only"] = False
        self.event = copy.deepcopy(self.examples["ToolEvent"]["data"])

    def test_btc_scorer_exact_parity_and_cli(self):
        spec = importlib.util.spec_from_file_location("btc_p0_scorer", BTC / "eval/reference_eval.py")
        scorer = importlib.util.module_from_spec(spec)
        # Do not create __pycache__ inside protected source inventory.
        with patch.object(sys, "dont_write_bytecode", True):
            spec.loader.exec_module(scorer)
        scenarios = scorer.load_scenarios(str(BTC / "test_set/public_sample"))
        golden = checker.read("sources/btc/eval/runs/report_example.json")
        self.assertEqual(len(scenarios), golden["n_scenarios"])
        for filename, key in (("full.jsonl", "system"), ("baseline.jsonl", "baseline")):
            with self.subTest(config=key):
                actual = scorer.evaluate(scenarios, scorer.load_trace(str(BTC / "eval/runs" / filename)))
                self.assertEqual(actual, golden[key])
        with tempfile.TemporaryDirectory(prefix="evaluation-p0-") as folder:
            output = Path(folder) / "report.json"
            result = subprocess.run([
                sys.executable, "-B", str(BTC / "eval/reference_eval.py"),
                "--scenarios", str(BTC / "test_set/public_sample"),
                "--trace", str(BTC / "eval/runs/full.jsonl"),
                "--baseline", str(BTC / "eval/runs/baseline.jsonl"), "--out", str(output),
            ], cwd=folder, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), golden)

    def test_mock_selftest_fresh_subprocess(self):
        with tempfile.TemporaryDirectory(prefix="evaluation-p0-mock-") as folder:
            outputs = []
            for _ in range(2):
                result = subprocess.run([
                    sys.executable, "-B", str(BTC / "eval/mock_tools.py"), "--selftest",
                ], cwd=folder, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.count("\n## "), 10)
                outputs.append(result.stdout)
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_correct_invocation_business_error_is_tp(self):
        self.event.update(outcome="business_error", result={"error": "OUT_OF_STOCK"},
                          error={"code": "OUT_OF_STOCK", "message": "fixture"})
        result = match_tool_calls(self.labels, [self.event])
        self.assertEqual((result["tp"], result["fp"], result["fn"], result["value"]), (1, 0, 0, 100))
        self.assertEqual(result["execution_failures"], ["EVENT-1"])
        self.assertEqual(result["execution_incomplete"], [])

    def test_timeout_is_tp_but_execution_incomplete(self):
        self.event.update(outcome="timeout", result=None,
                          error={"code": "TIMEOUT", "message": "commit unknown"})
        result = match_tool_calls(self.labels, [self.event])
        self.assertEqual(result["tp"], 1)
        self.assertEqual(result["execution_incomplete"], ["EVENT-1"])

    def test_wrong_args_is_fp_and_fn(self):
        self.event["request"]["args"]["sku"] = "WRONG-SKU"
        result = match_tool_calls(self.labels, [self.event])
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (0, 1, 1))

    def test_no_event_reuse_and_earliest_compatible_label(self):
        self.labels["calls"] *= 2
        result = match_tool_calls(self.labels, [self.event])
        self.assertEqual((result["tp"], result["fn"]), (1, 1))
        self.assertEqual(result["matches"][0]["expected_index"], 0)
        second = copy.deepcopy(self.event)
        second.update(event_id="EVENT-2", started_at="2026-10-15T09:00:01+07:00",
                      finished_at="2026-10-15T09:00:02+07:00")
        result = match_tool_calls(self.labels, [second, self.event])
        self.assertEqual(result["matches"], [
            {"expected_index": 0, "event_id": "EVENT-1"},
            {"expected_index": 1, "event_id": "EVENT-2"},
        ])

    def test_optional_is_allowed_not_tp_or_fn(self):
        self.labels["calls"][0]["required"] = False
        empty = match_tool_calls(self.labels, [])
        self.assertEqual((empty["fn"], empty["value"], empty["status"]), (0, None, "UNDEFINED"))
        result = match_tool_calls(self.labels, [self.event])
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (0, 0, 0))
        self.assertEqual(len(result["allowed"]), 1)

    def test_extra_read_only_requires_explicit_permission(self):
        self.labels["calls"] = []
        self.assertEqual(match_tool_calls(self.labels, [self.event])["fp"], 1)
        self.labels["allow_extra_read_only"] = True
        result = match_tool_calls(self.labels, [self.event])
        self.assertEqual((result["fp"], len(result["allowed"])), (0, 1))
        self.event["request"] = {"name": "schedule.callback", "args": {
            "customer_phone": "0900000000", "callback_at": "2026-10-15T09:00:00+07:00"}}
        self.assertEqual(match_tool_calls(self.labels, [self.event])["fp"], 1)

    def test_incomplete_labels_and_invalid_events_rejected(self):
        for change in ("null", "duplicate", "context", "schema", "time", "condition", "run_id"):
            with self.subTest(change=change):
                labels, events = copy.deepcopy(self.labels), [copy.deepcopy(self.event)]
                if change == "null":
                    labels["calls"][0]["args_match"]["sku"] = None
                elif change == "duplicate":
                    events *= 2
                elif change == "context":
                    events[0]["context"]["config"] = "baseline_no_memory"
                elif change == "schema":
                    del events[0]["request"]["args"]
                elif change == "time":
                    events[0]["finished_at"] = "2026-10-14T09:00:00+07:00"
                elif change == "run_id":
                    labels["run_id"] = "DIFFERENT-RUN"
                else:
                    labels["calls"][0]["condition"] = "unresolved"
                with self.assertRaises(ValueError):
                    match_tool_calls(labels, events)

    def test_tca_formula_fixture_from_real_matching(self):
        self.labels["calls"] *= 4
        good, failed, wrong = [copy.deepcopy(self.event) for _ in range(3)]
        failed.update(event_id="EVENT-2", outcome="business_error",
                      error={"code": "BUSINESS_ERROR", "message": "fixture"})
        wrong["event_id"] = "EVENT-3"
        wrong["request"]["args"]["sku"] = "WRONG"
        result = match_tool_calls(self.labels, [good, failed, wrong])
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (2, 1, 2))
        self.assertEqual(result["value"], self.examples["ToolAccuracyMetric"]["data"]["value"])

    def test_cost_completed_zero_missing_and_failed_cost(self):
        self.assertEqual(cost_per_completed_call(5 + 7 + 2, 2)["value"], 7)
        self.assertEqual(cost_per_completed_call(14, 0), {
            "value": None, "status": "UNDEFINED", "reason": "NO_COMPLETED_CALLS"})
        self.assertEqual(cost_per_completed_call(None, 2)["status"], "INCOMPLETE")
        self.assertEqual(cost_per_completed_call(0, 2)["value"], 0)
        metric = copy.deepcopy(self.examples["CostCompletedMetric"]["data"])
        metric.update(value=None, denominator=0, status="UNDEFINED", reason="NO_COMPLETED_CALLS")
        validate("Metric", metric)
        for cost, completed in ((-1, 2), (float("nan"), 2), (float("inf"), 2), (True, 2), (1, -1), (1, True)):
            with self.subTest(cost=cost, completed=completed), self.assertRaises(ValueError):
                cost_per_completed_call(cost, completed)

    def test_timing_nullable_legacy_zero_and_required(self):
        legacy = copy.deepcopy(self.examples["TimingEvidence"]["data"])
        current = copy.deepcopy(self.examples["TimingMissingUsage"]["data"])
        validate("TimingEvidence", legacy)
        validate("TimingEvidence", current)
        for field in ("audio_seconds", "asr_wall_ms", "input_tokens", "output_tokens", "cost", "currency"):
            with self.subTest(field=field):
                data = copy.deepcopy(legacy)
                data[field] = None
                with self.assertRaises(ValueError):
                    validate("TimingEvidence", data)
                data = copy.deepcopy(current)
                del data[field]
                with self.assertRaises(ValueError):
                    validate("TimingEvidence", data)

    def test_registry_missing_resource_and_fragment_fail_closed(self):
        from referencing.exceptions import Unresolvable
        for uri in ("https://unregistered.invalid/schema", (ROOT / "contracts.schema.json").as_uri() + "#/$defs/MISSING"):
            with self.subTest(uri=uri), self.assertRaises(Unresolvable):
                checker.registry.resolver().lookup(uri)

    def test_cli_help_invalid_and_result_exit_codes(self):
        from evaluation.eval_harness.__main__ import main
        for args in ([], ["run"], ["check", "--unknown"]):
            with self.subTest(args=args), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 3)
        with patch("unittest.defaultTestLoader.discover"), patch("unittest.TextTestRunner") as runner:
            for success, code in ((True, 0), (False, 1)):
                runner.return_value.run.return_value.wasSuccessful.return_value = success
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["check"]), code)
                self.assertEqual(unittest.defaultTestLoader.discover.call_args.kwargs["pattern"], "test_p*.py")
            unittest.defaultTestLoader.discover.return_value.countTestCases.return_value = 0
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["check"]), 1)
        wrapper = Path(__file__).resolve().parents[1] / "run_eval.py"
        result = subprocess.run([sys.executable, "-B", str(wrapper), "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("P0 offline", result.stdout)


if __name__ == "__main__":
    unittest.main()
