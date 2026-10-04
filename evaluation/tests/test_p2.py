"""P2 fixture/fault integration; never quality acceptance of a real Agent."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.eval_harness.assets import read_json
from evaluation.eval_harness.contracts import ROOT, checker, validate
from evaluation.eval_harness.preflight import ADAPTER_CAPABILITIES
from evaluation.eval_harness.runner import run_fixed
from evaluation.eval_harness.environment import MockEnvironment
from evaluation.tests import test_p1 as fixtures


def setUpModule():
    checker.verify_sources()


def tearDownModule():
    checker.verify_sources()


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.inputs = fixtures.PreflightTest()
        self.inputs.setUp()
        self.addCleanup(self.inputs.doCleanups)
        self.root = self.inputs.root
        self.out = self.root.parent / (self.root.name + "-run")
        # Keep output in the same TemporaryDirectory, outside asset_root.
        self.assets_root = self.root / "assets"
        self.assets_root.mkdir()
        (self.root / "fixtures").rename(self.assets_root / "fixtures")
        (self.root / "sources").rename(self.assets_root / "sources")
        from evaluation.eval_harness.assets import Assets
        self.inputs.root = self.assets_root
        self.inputs.assets = Assets(self.assets_root)
        self.out = self.root / "run"
        self.settings = self.inputs.settings
        self.configure()

    def configure(self, suffix=""):
        base = (ROOT / "fixtures/p2-adapter.py").read_text(encoding="utf-8")
        path = self.assets_root / "adapter.py"
        path.write_text(base + suffix, encoding="utf-8")
        descriptor = {"kind": "test", "entrypoint": "p2_fixture:factory",
                      "code": self.inputs.assets.ref("adapter.py"), "capabilities": sorted(ADAPTER_CAPABILITIES)}
        self.inputs.save(self.assets_root / "adapter.json", descriptor)
        ref = self.inputs.assets.ref("adapter.json")
        self.inputs.manifest["sources"] = self.inputs.manifest["sources"][:2] + [ref, descriptor["code"]]
        self.inputs.save(self.settings, {"asset_root": "assets", "manifest": "fixtures/manifest.json",
                                        "scope": "fixtures/p1-scope.json", "adapter": ref})
        self.inputs.run_preflight()

    def scenario(self, change):
        path = self.assets_root / "fixtures/scenario.json"
        scenario = read_json(path)
        change(scenario)
        self.inputs.save(path, scenario)
        ref = self.inputs.assets.ref("fixtures/scenario.json")
        self.inputs.manifest["scenarios"] = [ref]
        grading_path = self.assets_root / "fixtures/grading.json"
        grading = read_json(grading_path)
        grading["scenario"] = ref
        for call in grading["calls"]:
            call["ground_truth"] = [{**ref, "pointer": ground["pointer"]} for ground in call["ground_truth"]]
            if call["official_success_if"] is not None:
                call["official_success_if"] = {**ref, "pointer": "/calls/" + call["call"] + "/success_if"}
        self.inputs.save(grading_path, grading)
        self.inputs.manifest["grading_contracts"] = [self.inputs.assets.ref("fixtures/grading.json")]
        self.inputs.scope["source_decisions"][0]["origin"] = ref
        for plan in self.inputs.manifest["planned_calls"]:
            spec = scenario["calls"][plan["call"]]
            plan["expected_turns"] = len(spec["customer_turns"])
            if plan["config"] == "full" and spec.get("seed_history"):
                plan["memory_required"] = True
        self.inputs.run_preflight()

    def run_fixture(self, **kwargs):
        return run_fixed(self.settings, self.out, **kwargs)

    def records(self, config="full"):
        return [json.loads(line) for line in (self.out / config / "raw-execution.jsonl").read_text(encoding="utf-8").splitlines()]

    def events(self, config="full"):
        return [r["data"]["event"] for r in self.records(config)
                if r["kind"] == "adapter_message" and r["data"]["type"] == "event"]

    def test_fixed_13_noisy_turns_seed_once_barrier_baseline_working_context_and_hashes(self):
        def change(scenario):
            spec = scenario["calls"]["call_1"]
            spec["customer_turns"] = [f"clean {i}" for i in range(13)]
            spec["customer_turns_asr"] = [f"asr lỗi {i}" for i in range(13)]
            spec["seed_history"] = {"summary": "prior business history"}
            scenario["calls"]["call_2"]["call_date"] = "2026-10-22"
        self.scenario(change)
        result = self.run_fixture()
        self.assertTrue(result["execution_complete"], result["errors"])
        self.assertEqual((result["attempted_calls"], result["completed_calls"], result["failed_calls"]), (4, 4, 0))
        self.assertEqual(len(result["coverage"]["observed_ids"]), 28)
        self.assertEqual(result["evaluation_status"]["completeness"], "INCOMPLETE")
        self.assertNotEqual(result["bindings"][0]["pid"], result["bindings"][1]["pid"])
        for config in ("full", "baseline_no_memory"):
            rows = self.records(config)
            inputs = [r for r in rows if r["kind"] == "customer_input"]
            self.assertEqual(inputs[0]["data"]["text"], "asr lỗi 0")
            self.assertEqual(inputs[12]["data"]["text"], "asr lỗi 12")
            events = self.events(config)
            self.assertEqual(sum(e["kind"] == "seeded_once" for e in events), 1)
            gates = [e["visible_history"] for e in events if e["kind"] == "memory_read_gate"]
            self.assertEqual([len(h) for h in gates], [1, 2] if config == "full" else [0, 0])
            working = [e for e in events if e["kind"] == "working_context"]
            self.assertEqual(len(working[12]["texts"]), 13)  # Baseline does NOT clear each turn.
            commit_index = next(i for i, r in enumerate(rows) if r["kind"] == "adapter_message"
                                and r["data"].get("event", {}).get("kind") == "after_call_committed")
            start2 = next(i for i, r in enumerate(rows) if r["kind"] == "hook_request"
                          and r["data"]["hook"] == "start_call" and r["context"]["call"] == "call_2")
            self.assertLess(commit_index, start2)
            raw_turn = next(r["data"]["result"] for r in rows if r["kind"] == "adapter_message"
                            and r["data"].get("hook") == "run_turn")
            self.assertIsNone(raw_turn["usage"])
            self.assertNotIn("claims", raw_turn)
            self.assertNotIn("questions", raw_turn)
            tools = [json.loads(line) for line in (self.out / config / "tools.jsonl").read_text().splitlines()]
            self.assertEqual(tools[-1]["on"], "2026-10-22")
            for event in tools:
                validate("ToolEvent", event)
        for name, digest in read_json(self.out / "artifacts.lock.json")["files"].items():
            self.assertEqual(hashlib.sha256((self.out / name).read_bytes()).hexdigest(), digest)

    def test_oracle_labels_not_passed_and_configuration_equal(self):
        self.configure('''
class AsyncRuntime(FixtureAdapter):
    async def open_scenario(self, context):
        import asyncio
        self.loop = asyncio.get_running_loop()
        super().open_scenario(context)
    async def start_call(self, context):
        import asyncio
        assert asyncio.get_running_loop() is self.loop
        return super().start_call(context)
    async def run_turn(self, text):
        import asyncio
        assert asyncio.get_running_loop() is self.loop
        self.pending = self.loop.create_future()
        self.loop.call_later(0.01, self.pending.set_result, True)
        return super().run_turn(text)
    async def end_call(self):
        await self.pending
        return await super().end_call()
    async def close_scenario(self):
        import asyncio
        assert asyncio.get_running_loop() is self.loop
        super().close_scenario()
def factory():
    return AsyncRuntime()
''')
        result = self.run_fixture()
        self.assertTrue(result["execution_complete"])
        opens = []
        forbidden = {"facts_established", "must_not_ask", "must_carry_over", "success_if", "ground_truth_facts", "memory_expectation"}
        for config in ("full", "baseline_no_memory"):
            rows = self.records(config)
            requests = [r["data"] for r in rows if r["kind"] == "hook_request"]
            for request in requests:
                if request["hook"] in ("open_scenario", "start_call"):
                    self.assertFalse(forbidden & request["args"][0].keys())
            opens.append(next(r["args"][0] for r in requests if r["hook"] == "open_scenario"))
        self.assertEqual(opens[0]["configuration"], opens[1]["configuration"])
        self.assertEqual(opens[0]["resources"], opens[1]["resources"])
        self.assertNotEqual(opens[0]["namespace"], opens[1]["namespace"])

    def test_after_call_timeout_partial_no_next_call_and_no_retry(self):
        self.configure('\nclass Fault(FixtureAdapter):\n    async def end_call(self):\n        import asyncio\n        self.emit({"kind": "barrier_entered"})\n        await asyncio.sleep(5)\ndef factory():\n    return Fault()\n')
        self.inputs.manifest["timeouts_ms"]["after_call"] = 50
        self.inputs.run_preflight()
        result = self.run_fixture(config="full")
        self.assertFalse(result["execution_complete"])
        self.assertEqual(result["completed_calls"], 0)
        self.assertEqual(result["failed_calls"], 1)
        self.assertEqual(result["errors"][0]["phase"], "end_call")
        self.assertTrue(result["errors"][0]["reconciliation_required"])
        rows = self.records()
        self.assertEqual(sum(r["kind"] == "hook_request" and r["data"]["hook"] == "end_call" for r in rows), 1)
        self.assertFalse(any(r["context"] and r["context"]["call"] == "call_2" for r in rows))
        self.assertEqual(len(result["coverage"]["missing_ids"]), 1)
        self.assertTrue((self.out / "artifacts.lock.json").exists())

    def test_failed_barrier_and_invalid_turn_preserve_raw_without_completion(self):
        for suffix, phase in (("\nclass Fault(FixtureAdapter):\n    def end_call(self):\n        return {\"completed\": True, \"barrier_complete\": False, \"memory_snapshot\": {}}\ndef factory():\n    return Fault()\n", "end_call"),
                              ("\nclass Fault(FixtureAdapter):\n    def run_turn(self, text):\n        return {\"unexpected\": text}\ndef factory():\n    return Fault()\n", "run_turn")):
            with self.subTest(phase=phase):
                self.configure(suffix)
                self.out = self.root / phase
                result = self.run_fixture(config="full")
                self.assertEqual(result["completed_calls"], 0)
                self.assertEqual(result["errors"][0]["phase"], phase)
                self.assertTrue(any(r["kind"] == "adapter_message" and r["data"].get("hook") == phase for r in self.records()))

    def test_binding_rejects_missing_hook_capability_retry_and_import_error_no_fallback(self):
        suffixes = ["\nFixtureAdapter.run_turn = None\n",
                    "\nFixtureAdapter.capabilities = ()\n",
                    "\nFixtureAdapter.retry = {\"agent\": 1, \"tool\": 0}\n",
                    "\nraise RuntimeError(\"binding exploded\")\n"]
        for i, suffix in enumerate(suffixes):
            with self.subTest(suffix=suffix):
                self.configure(suffix)
                self.out = self.root / f"bad-bind-{i}"
                result = self.run_fixture(config="full")
                self.assertFalse(result["execution_complete"])
                self.assertEqual(result["attempted_calls"], 0)
                self.assertEqual(result["errors"][0]["phase"], "binding")
                self.assertFalse(any(r["kind"] == "customer_input" for r in self.records()))

    def test_agent_timeout_and_exception_preserve_partial_no_retry(self):
        self.configure('\nclass Fault(FixtureAdapter):\n    def run_turn(self, text):\n        self.emit({"kind": "turn_entered"})\n        time.sleep(5)\ndef factory():\n    return Fault()\n')
        # Enough for spawn/binding/start, short enough to cancel a stuck turn.
        self.inputs.manifest["timeouts_ms"]["agent"] = 1500
        self.inputs.run_preflight()
        result = self.run_fixture(config="full")
        self.assertEqual(result["errors"][0]["phase"], "run_turn")
        self.assertEqual(result["completed_calls"], 0)
        self.assertEqual(len(result["coverage"]["missing_ids"]), 2)
        self.assertEqual(sum(e["kind"] == "turn_entered" for e in self.events()), 1)

    def test_input_gate_blocks_before_import_and_development_dispute_stays_open(self):
        self.inputs.manifest["dispute_ids"] = ["B02"]
        self.inputs.run_preflight()
        result = self.run_fixture(config="full")
        self.assertTrue(result["execution_complete"])
        self.assertEqual(result["validation_status"]["completeness"], "INCOMPLETE")
        self.out = self.root / "blocked"
        self.inputs.manifest["purpose"] = "regression"
        self.inputs.run_preflight()
        result = self.run_fixture(config="full")
        self.assertEqual(result["attempted_calls"], 0)
        self.assertEqual(result["bindings"], [])
        self.assertEqual(result["errors"][0]["code"], "INPUT_GATE_BLOCKED")

    def test_cli_cwd_round_single_config_exit_and_no_overwrite(self):
        self.configure('\nprint("adapter startup diagnostic")\n')
        command = [sys.executable, "-B", str(ROOT.parent / "run_eval.py"), "run", "--settings", str(self.settings),
                   "--config", "full", "--round", "R0", "--out", str(self.out)]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["execution_complete"])
        self.assertFalse((self.out / "baseline_no_memory").exists())
        self.assertIn("adapter startup diagnostic", (self.out / "full/adapter-0.log").read_text())
        locked = (self.out / "artifacts.lock.json").read_bytes()
        again = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(again.returncode, 3)
        self.assertEqual((self.out / "artifacts.lock.json").read_bytes(), locked)
        with self.assertRaises(ValueError):
            run_fixed(self.settings, self.root / "wrong-round", round_name="R1")
        self.assertFalse((self.root / "wrong-round").exists())
        with self.assertRaises(ValueError):
            run_fixed(self.settings, self.assets_root / "bad-output")

    def test_mock_business_state_persists_but_isolated_and_result_error_logged(self):
        self.configure('''
class Business(FixtureAdapter):
    def run_turn(self, text):
        tool = self.context["call_tool"]
        if self.call["call"] == "call_1":
            initial = tool("order.status", {"customer_phone": "0900000000"})
            self.emit({"kind": "initial_orders", "result": initial})
            quote = tool("pricing.get_quote", {"sku": "SKU-AP-PRO", "customer_phone": "0900000000"})
            result = tool("order.create", {"customer_phone": "0900000000", "sku": "SKU-AP-PRO", "qty": 1, "price_vnd": quote["final_price_vnd"], "payment": "bank"})
            self.order = result.get("order_id")
        else:
            result = tool("order.status", {"order_id": self.order})
        self.emit({"kind": "business_result", "result": result})
        tool("inventory.check", {"sku": "DOES-NOT-EXIST"})
        return super().run_turn(text)
def factory():
    return Business()
''')
        result = self.run_fixture()
        self.assertTrue(result["execution_complete"], result["errors"])
        for config in ("full", "baseline_no_memory"):
            events = self.events(config)
            self.assertEqual(next(e["result"]["orders"] for e in events if e["kind"] == "initial_orders"), [])
            results = [e["result"] for e in events if e["kind"] == "business_result"]
            self.assertIn("order_id", results[0])
            self.assertEqual(results[1]["orders"][0]["order_id"], results[0]["order_id"])
            tools = [json.loads(line) for line in (self.out / config / "tools.jsonl").read_text().splitlines()]
            self.assertEqual(sum(e["request"]["name"] == "order.create" for e in tools), 1)
            self.assertTrue(any(e["outcome"] == "business_error" for e in tools))
            snapshots = [r["data"]["state"] for r in self.records(config) if r["kind"] == "business_snapshot"]
            self.assertEqual(snapshots[0]["_ORDERS"], {})
            self.assertEqual(len(snapshots[-1]["_ORDERS"]), 1)

    def test_timeout_after_tool_commit_keeps_audit_and_does_not_retry_or_start_call2(self):
        self.configure('''
class Commit(FixtureAdapter):
    def run_turn(self, text):
        self.context["call_tool"]("schedule.callback", {"customer_phone": "0900000000", "callback_at": "2026-10-26T09:00"})
        return super().run_turn(text)
def factory():
    return Commit()
''')
        class LostReply(MockEnvironment):
            def call_tool(self, name, args, **kwargs):
                result = super().call_tool(name, args, **kwargs)
                if name == "schedule.callback":
                    self.failures.append({"code": "LOST_REPLY_AFTER_COMMIT", "reconciliation_required": True})
                    raise TimeoutError("Injected reply loss after real BTC commit")
                return result
        with patch("evaluation.eval_harness.runner.MockEnvironment", LostReply):
            report = self.run_fixture(config="full")
        self.assertFalse(report["execution_complete"])
        self.assertEqual(report["completed_calls"], 0)
        self.assertTrue(report["errors"][0]["reconciliation_required"])
        rows = self.records()
        self.assertFalse(any(r["context"] and r["context"]["call"] == "call_2" for r in rows))
        audits = [r["data"] for r in rows if r["kind"] == "tool_audit"
                  and r["data"]["raw_request"]["request"]["name"] == "schedule.callback"]
        self.assertEqual(len(audits), 1)
        self.assertEqual(len(audits[0]["state_after"]["_CALLBACKS"]), 1)
        self.assertTrue(audits[0]["event"]["side_effect"])
        self.assertEqual(audits[0]["event"]["attempt"], 1)


if __name__ == "__main__":
    unittest.main()
