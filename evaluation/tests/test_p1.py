"""P1 component tests; no runtime Agent, no A11/A16 end-to-end claim."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.eval_harness.assets import Assets, read_json
from evaluation.eval_harness.contracts import ROOT, checker, validate
from evaluation.eval_harness.environment import MockEnvironment
from evaluation.eval_harness.preflight import ADAPTER_CAPABILITIES, call_plan, execution_gate, preflight

BTC = ROOT / "sources/btc"


def setUpModule():
    checker.verify_sources()


def tearDownModule():
    checker.verify_sources()


class EnvironmentTest(unittest.TestCase):
    def invoke(self, worker, name, args, call="call_1", on="2026-10-15"):
        return worker.call_tool(name, args, call=call, turn=1, on=on)

    def test_state_persists_across_calls_but_not_workers(self):
        crm = read_json(BTC / "catalog/crm_seed.json")["customers"]
        phone = next(c["phone"] for c in crm if c.get("orders") and c["orders"][0]["sku"] == "SKU-AP-X-2024")
        with MockEnvironment("P1-TEST", "scenario", "full") as full:
            first_pid = full.pid
            quote = self.invoke(full, "pricing.get_quote", {"sku": "SKU-AP-PRO", "customer_phone": phone})
            self.assertEqual(quote["final_price_vnd"], 7590000)
            order = self.invoke(full, "order.create", {
                "customer_phone": phone, "sku": "SKU-AP-PRO", "qty": 1,
                "price_vnd": quote["final_price_vnd"], "payment": "bank"})
            self.assertIn("order_id", order)
            self.invoke(full, "schedule.callback", {"customer_phone": phone, "callback_at": "2026-10-26T09:00"})
            brief = copy.deepcopy(checker.read("fixtures/handoff-brief.json"))
            self.invoke(full, "handoff.transfer", {"brief": brief})
            state = full.snapshot()
            self.assertEqual(len(state["_ORDERS"]), 1)
            self.assertEqual(len(state["_CALLBACKS"]), 1)
            self.assertEqual(len(state["_TICKETS"]), 1)
            self.assertTrue(state["_ONCE_USED"])
            second = self.invoke(full, "order.status", {"order_id": order["order_id"]}, call="call_2", on="2026-10-17")
            self.assertEqual(second["orders"][0]["order_id"], order["order_id"])
            self.assertEqual(full.snapshot(), state)
            for event in full.events:
                validate("ToolEvent", event)
            self.assertTrue(any(event["side_effect"] for event in full.events))
            self.assertEqual(full.events[-1]["on"], "2026-10-17")
            self.assertNotIn("on", full.audit[-1]["effective_args"])
        with MockEnvironment("P1-TEST", "scenario", "baseline_no_memory") as baseline:
            self.assertNotEqual(first_pid, baseline.pid)
            state = baseline.snapshot()
            self.assertEqual((state["_ORDERS"], state["_CALLBACKS"], state["_TICKETS"], state["_ONCE_USED"]), ({}, [], [], []))
            self.assertEqual(self.invoke(baseline, "pricing.get_quote", {"sku": "SKU-AP-PRO", "customer_phone": phone})["final_price_vnd"], quote["final_price_vnd"])
            self.assertEqual(self.invoke(baseline, "order.status", {"order_id": order["order_id"]})["orders"], [])

    def test_baseline_hides_sessions_single_and_ambiguous_keeps_orders(self):
        crm = read_json(BTC / "catalog/crm_seed.json")["customers"]
        counts = {c["phone"]: sum(other["phone"] == c["phone"] for other in crm) for c in crm}
        single = next(c for c in crm if c.get("sessions") and counts[c["phone"]] == 1)
        shared = next(c for c in crm if counts[c["phone"]] > 1)
        with MockEnvironment("P1-CRM", "single", "full") as full, MockEnvironment("P1-CRM", "single", "baseline_no_memory") as baseline:
            for customer in (single, shared):
                args = {"phone": customer["phone"]}
                raw = self.invoke(full, "crm.get_customer", args)
                visible = self.invoke(baseline, "crm.get_customer", args)
                entries = visible.get("candidates", [visible])
                original = raw.get("candidates", [raw])
                for a, b in zip(entries, original):
                    self.assertEqual(a["sessions"], [])
                    self.assertEqual(a["orders"], b["orders"])
                self.assertEqual(baseline.events[-1]["result"], raw)
                self.assertNotIn("on", baseline.audit[-1]["effective_args"])
            self.assertTrue(self.invoke(full, "crm.get_customer", {"phone": single["phone"]})["sessions"])

    def test_inventory_date_injection_and_raw_args_preserved(self):
        with MockEnvironment("P1-DATE", "scenario", "full") as worker:
            args = {"sku": "SKU-SN-RUN2-41-DEN"}
            before = self.invoke(worker, "inventory.check", args)
            after = self.invoke(worker, "inventory.check", args, call="call_2", on="2026-10-17")
            self.assertNotEqual(before["qty"], after["qty"])
            self.assertFalse(after["in_stock"])
            self.assertEqual(args, {"sku": "SKU-SN-RUN2-41-DEN"})
            self.assertNotIn("on", worker.events[-1]["request"]["args"])
            self.assertEqual(worker.audit[-1]["effective_args"]["on"], "2026-10-17")
            self.assertGreaterEqual(worker.audit[-1]["elapsed_ms"], 0)

    def test_rejected_args_do_not_execute_or_retry(self):
        with MockEnvironment("P1-INVALID", "scenario", "full") as worker:
            original = worker.snapshot()
            for name, args in (("unknown", {}), ("crm.get_customer", {"on": "2026-10-15"}),
                               ("inventory.check", {"sku": "SKU-AP-PRO", "on": "2026-10-17"})):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.invoke(worker, name, args)
            self.assertEqual(worker.snapshot(), original)
            self.assertEqual(worker.events, [])
            self.assertEqual(len(worker.audit), 3)
            self.assertTrue(all("raw_request" in item and "rejected" in item for item in worker.audit))

    def test_business_error_and_timeout_not_fake_success(self):
        with MockEnvironment("P1-ERROR", "scenario", "full") as worker:
            result = self.invoke(worker, "inventory.check", {"sku": "DOES-NOT-EXIST"})
            self.assertEqual(result["error"], "unknown_sku")
            self.assertEqual(worker.events[-1]["outcome"], "business_error")
            self.assertFalse(worker.events[-1]["side_effect"])
            worker.timeout = 0.001
            with self.assertRaises(TimeoutError):
                worker._receive()  # No reply queued: deterministic timeout without editing BTC.
            self.assertTrue(worker.closed)
            self.assertTrue(worker.failures[-1]["reconciliation_required"])
            with self.assertRaises(RuntimeError):
                worker.snapshot()


class PreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="evaluation-p1-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Fixtures may be copied for mutation, protected source is never edited.
        shutil.copytree(ROOT / "fixtures", self.root / "fixtures")
        shutil.copytree(BTC, self.root / "sources/btc")
        self.assets = Assets(self.root)
        self.manifest = read_json(self.root / "fixtures/manifest.json")
        self.scope = read_json(self.root / "fixtures/p1-scope.json")
        self.settings = self.root / "settings.json"
        self.save(self.settings, {"asset_root": ".", "manifest": "fixtures/manifest.json", "scope": "fixtures/p1-scope.json"})

    def save(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    def run_preflight(self):
        self.save(self.root / "fixtures/p1-scope.json", self.scope)
        self.manifest["sources"][0] = self.assets.ref("fixtures/p1-scope.json")
        self.save(self.root / "fixtures/manifest.json", self.manifest)
        return preflight(self.settings)

    def codes(self, report):
        return {issue["code"] for issue in report["validation"]["issues"]}

    def configure_adapter(self, kind="test"):
        # This file MUST NOT be imported while doing preflight.
        (self.root / "adapter.py").write_text('raise RuntimeError("preflight imported adapter code")\n', encoding="utf-8")
        descriptor = {"kind": kind, "entrypoint": "adapter:factory", "code": self.assets.ref("adapter.py"),
                      "capabilities": sorted(ADAPTER_CAPABILITIES)}
        self.save(self.root / "adapter.json", descriptor)
        settings = read_json(self.settings)
        settings["adapter"] = self.assets.ref("adapter.json")
        self.save(self.settings, settings)
        self.manifest["sources"].extend([settings["adapter"], descriptor["code"]])
        return descriptor

    def test_execution_gate_dispute_is_nonblocking_only_in_development(self):
        issue = {"code": "B02", "classification": "dispute"}
        adapter = {"kind": "runtime"}
        self.assertTrue(execution_gate(self.manifest, [issue], adapter)["allowed"])
        for purpose in ("official_eval", "regression"):
            manifest = {**self.manifest, "purpose": purpose}
            gate = execution_gate(manifest, [issue], adapter)
            self.assertFalse(gate["allowed"])
            self.assertIn("B02", gate["blocking_codes"])
        for classification in ("schema_error", "missing_evidence", "infra_error", "agent_violation"):
            with self.subTest(classification=classification):
                gate = execution_gate(self.manifest, [issue, {"code": "BROKEN_INPUT", "classification": classification}], adapter)
                self.assertFalse(gate["allowed"])
                self.assertEqual(gate["blocking_codes"], ["BROKEN_INPUT"])

    def test_adapter_optional_pinned_and_never_imported_or_fallback(self):
        old = self.run_preflight()
        self.assertEqual(old["validation"]["status"]["verdict"], "PASS")
        self.assertFalse(old["execution_gate"]["allowed"])
        self.assertIn("ADAPTER_NOT_CONFIGURED", old["execution_gate"]["blocking_codes"])
        self.configure_adapter()
        self.manifest["dispute_ids"] = ["B02"]
        report = self.run_preflight()
        self.assertTrue(report["execution_gate"]["allowed"])
        self.assertFalse(report["execution_gate"]["binding_verified"])
        self.assertEqual(report["validation"]["status"]["verdict"], "UNDETERMINED")
        self.assertEqual(report["execution_gate"]["nonblocking_dispute_codes"], ["B02"])
        self.manifest["fixture"] = False
        self.assertIn("TEST_ADAPTER_NOT_FIXTURE", self.run_preflight()["execution_gate"]["blocking_codes"])
        self.scope["pii_review"]["status"] = "pending"
        self.assertFalse(self.run_preflight()["execution_gate"]["allowed"])

    def test_adapter_pin_capabilities_and_unknown_settings_rejected(self):
        descriptor = self.configure_adapter()
        self.manifest["sources"].pop()
        self.assertIn("ADAPTER_CONFIG", self.codes(self.run_preflight()))
        self.manifest["sources"].append(descriptor["code"])
        descriptor["capabilities"].remove("after_call_barrier")
        self.save(self.root / "adapter.json", descriptor)
        settings = read_json(self.settings)
        settings["adapter"] = self.assets.ref("adapter.json")
        self.manifest["sources"][-2] = settings["adapter"]
        self.save(self.settings, settings)
        self.assertIn("ADAPTER_CONFIG", self.codes(self.run_preflight()))
        settings["api_key"] = "must-not-be-in-settings"
        self.save(self.settings, settings)
        with self.assertRaises(ValueError):
            preflight(self.settings)

    def test_cli_execution_input_gate_keeps_validation_incomplete(self):
        command = [sys.executable, "-B", str(ROOT.parent / "run_eval.py"), "preflight", "--settings", str(self.settings)]
        self.run_preflight()
        result = subprocess.run(command + ["--for-execution"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)  # No adapter, legacy P1 config still valid.
        self.configure_adapter()
        self.manifest["dispute_ids"] = ["B02"]
        self.run_preflight()
        result = subprocess.run(command + ["--for-execution"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["validation"]["status"]["completeness"], "INCOMPLETE")
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)

    def test_valid_fixture_plans_both_configs_and_reports_deferred(self):
        report = self.run_preflight()
        self.assertEqual(report["validation"]["status"]["verdict"], "PASS")
        self.assertEqual(len(report["coverage_plan"]["expected_trace_ids"]), 4)
        self.assertEqual([item["on"] for item in report["coverage_plan"]["calls"]], ["2026-10-15", "2026-10-17"])
        self.assertEqual(report["btc_full_readiness"], "INCOMPLETE")
        self.assertEqual(report["capabilities"]["runtime_memory_access_gate"], "NOT_RUN")
        self.assertTrue(report["warnings"])

    def test_call_dates_noisy_inputs_and_noncontiguous_calls(self):
        scenario = checker.read("fixtures/scenario.json")
        scenario["calls"]["call_1"]["call_date"] = "2026-10-14"
        scenario["calls"]["call_2"]["customer_turns_asr"] = ["teencode fixture"]
        plans = call_plan(scenario, "2026-10-15")
        self.assertEqual(plans[1]["on"], "2026-10-16")
        self.assertEqual(plans[1]["input_field"], "customer_turns_asr")
        scenario["calls"]["call_2"]["call_date"] = "2026-10-18"
        self.assertEqual(call_plan(scenario, "2026-10-15")[1]["on"], "2026-10-18")
        for change in ("noisy", "backward", "gap"):
            data = copy.deepcopy(scenario)
            if change == "noisy": data["calls"]["call_2"]["customer_turns_asr"] = []
            elif change == "backward": data["calls"]["call_2"]["call_date"] = "2026-10-13"
            else: data["calls"]["call_3"] = data["calls"].pop("call_2")
            with self.subTest(change=change), self.assertRaises(ValueError):
                call_plan(data, "2026-10-15")

    def test_manifest_mutations_and_missing_team_audio(self):
        for change, code in (("namespace", "NAMESPACE_COLLISION"), ("duplicate", "DUPLICATE_PLANNED_CALL"),
                             ("coverage", "PLANNED_COVERAGE"), ("audio", "ASR_ASSET_COVERAGE"),
                             ("scale", "DATASET_SCALE"), ("suite", "DUPLICATE_SUITE"),
                             ("memory", "MEMORY_APPLICABILITY"), ("simulator", "SIMULATOR_SEEDS")):
            original = copy.deepcopy(self.manifest)
            if change == "namespace": self.manifest["state_namespaces"]["full"] = self.manifest["state_namespaces"]["baseline_no_memory"]
            elif change == "duplicate": self.manifest["planned_calls"].append(self.manifest["planned_calls"][0])
            elif change == "coverage": self.manifest["planned_calls"].pop()
            elif change == "audio": self.manifest["asr_ids"].append("MISSING-TEAM-AUDIO")
            elif change == "scale": self.manifest["purpose"] = "official_eval"
            elif change == "memory": self.manifest["planned_calls"][1]["memory_required"] = False
            elif change == "simulator": self.manifest["suites"].append({"id": "simulator", "applicable": True, "reason": "fixture"})
            else: self.manifest["suites"].append(self.manifest["suites"][0])
            with self.subTest(change=change): self.assertIn(code, self.codes(self.run_preflight()))
            self.manifest = original

    def test_scope_rights_and_grading_must_be_pinned(self):
        self.scope["source_decisions"][0]["permission"] = "deny"
        self.scope["pii_review"]["status"] = "pending"
        self.scope["deferred"] = []
        codes = self.codes(self.run_preflight())
        self.assertTrue({"SOURCE_RIGHTS", "PII_REVIEW", "DEFERRED_SCOPE"} <= codes)
        grading = read_json(self.root / "fixtures/grading.json")
        grading["calls"][0]["official_success_if"]["pointer"] = "/calls/call_2/success_if"
        self.save(self.root / "fixtures/grading.json", grading)
        self.manifest["grading_contracts"][0] = self.assets.ref("fixtures/grading.json")
        self.assertIn("GRADING_SUCCESS_REF", self.codes(self.run_preflight()))
        self.scope["pii_review"]["reviewed_by"] = "changed-after-manifest-pin"
        self.save(self.root / "fixtures/p1-scope.json", self.scope)
        self.assertIn("SCOPE_NOT_PINNED", self.codes(preflight(self.settings)))

    def test_assets_hash_traversal_symlink_pointer_and_strict_json(self):
        reference = self.assets.ref("fixtures/scenario.json")
        self.assertEqual(self.assets.resolve(reference)["scenario_id"], "FIXTURE-M1")
        reference["sha256"] = "0" * 64
        with self.assertRaises(ValueError): self.assets.resolve(reference)
        with self.assertRaises(ValueError): self.assets.path("../settings.json")
        with self.assertRaises(ValueError): self.assets.path(str(self.settings))
        (self.root / "outside").symlink_to(ROOT / "examples.json")
        with self.assertRaises(ValueError): self.assets.path("outside")
        reference = self.assets.ref("fixtures/scenario.json", "/MISSING")
        with self.assertRaises(KeyError): self.assets.resolve(reference)
        self.save(self.root / "array.json", ["one", "two"])
        for pointer in ("/-1", "/01", "/~9"):
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                self.assets.resolve(self.assets.ref("array.json", pointer))
        for content in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'):
            self.settings.write_text(content)
            with self.assertRaises(ValueError): read_json(self.settings)

    def authorize(self, reference):
        decision = copy.deepcopy(self.scope["source_decisions"][0])
        decision["artifact_id"] += "/" + str(len(self.scope["source_decisions"]))
        decision["origin"] = reference
        self.scope["source_decisions"].append(decision)

    def test_registered_team_audio_ground_truth_and_missing_segments(self):
        audio_path = self.root / "team.wav"
        with wave.open(str(audio_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 160)
        self.save(self.root / "team-gt.json", {"dialogues": [{"id": "TEAM-01", "full_text": "fixture", "entities": {}}]})
        self.manifest["asr_ids"] = ["TEAM-01"]
        self.manifest["suites"].append({"id": "asr", "applicable": True, "reason": "synthetic test"})
        item = {"id": "TEAM-01", "audio": self.assets.ref("team.wav"), "ground_truth": self.assets.ref("team-gt.json")}
        self.scope["asr_assets"] = [item]
        for reference in (item["audio"], item["ground_truth"]): self.authorize(reference)
        self.assertEqual(self.codes(self.run_preflight()), set())
        self.manifest["suites"].append({"id": "diarization", "applicable": True, "reason": "synthetic test"})
        self.assertIn("SEGMENTS_MISSING", self.codes(self.run_preflight()))
        self.manifest["suites"].pop()
        self.save(self.root / "team-gt.json", {"dialogues": [{"id": "WRONG-ID"}]})
        item["ground_truth"] = self.assets.ref("team-gt.json")
        self.assertIn("ASR_ASSET_MISSING", self.codes(self.run_preflight()))

    def test_registered_rag_keeps_full_btc_labels_and_disputes(self):
        labels = read_json(BTC / "rag/qa_labeled.json")
        self.manifest["rag_ids"] = [q["qid"] for q in labels["questions"]]
        self.scope["rag_ids"] = list(self.manifest["rag_ids"])
        self.manifest["suites"].append({"id": "rag", "applicable": True, "reason": "BTC labels"})
        reference = self.assets.ref("sources/btc/rag/qa_labeled.json")
        self.scope["rag_ground_truth"] = reference
        self.authorize(reference)
        report = self.run_preflight()
        self.assertEqual(self.codes(report), {"B05", "B06"})
        self.assertEqual(len(report["coverage_plan"]["rag_ids"]), 60)
        self.manifest["rag_ids"].pop()
        self.scope["rag_ids"].pop()
        self.assertIn("RAG_GROUND_TRUTH", self.codes(self.run_preflight()))

    def test_public_disputes_preserved_and_duplicate_ids_detected(self):
        original = read_json(BTC / "test_set/public_sample/SAMPLE-01.json")
        self.manifest["scenarios"] = [self.assets.ref("sources/btc/test_set/public_sample/SAMPLE-01.json")]
        report = self.run_preflight()
        self.assertIn("B02", self.codes(report))
        self.assertEqual(read_json(self.root / "sources/btc/test_set/public_sample/SAMPLE-01.json"), original)
        self.manifest["scenarios"] *= 2
        self.assertIn("DUPLICATE_SCENARIO", self.codes(self.run_preflight()))
        original["calls"]["call_1"].setdefault("success_if", {})["unmapped_rule"] = True
        self.save(self.root / "sources/btc/test_set/public_sample/SAMPLE-01.json", original)
        self.manifest["scenarios"] = [self.assets.ref("sources/btc/test_set/public_sample/SAMPLE-01.json")]
        self.assertIn("UNKNOWN_SUCCESS_IF", self.codes(self.run_preflight()))

    def test_cli_preflight_output_no_overwrite_and_check_discovers_p1(self):
        self.run_preflight()
        command = [sys.executable, "-B", str(ROOT.parent / "run_eval.py"), "preflight", "--settings", str(self.settings)]
        output = self.root / "new-report.json"
        result = subprocess.run(command + ["--out", str(output)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first = output.read_bytes()
        result = subprocess.run(command + ["--out", str(output)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(output.read_bytes(), first)
        forbidden = BTC / "p1-test-report-must-not-exist.json"
        result = subprocess.run(command + ["--out", str(forbidden)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 3)
        self.assertFalse(forbidden.exists())
        self.scope["pii_review"]["status"] = "pending"
        self.run_preflight()
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
