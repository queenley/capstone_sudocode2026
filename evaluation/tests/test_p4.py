"""P4 offline integration/fault tests; synthetic fixtures, no product DB/provider."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.eval_harness.assets import read_json
from evaluation.eval_harness.collector import locked_run
from evaluation.eval_harness.contracts import ROOT, checker, validate
from evaluation.eval_harness.extractor import digest
from evaluation.eval_harness.scoring import score, new_order_verified
from evaluation.eval_harness.environment import MockEnvironment
from evaluation.tests import test_p3 as p3


class ScoringTest(unittest.TestCase):
    def setUp(self):
        self.fixture = p3.CollectorTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.out = self.root / "score"

    def execute(self, config="full"):
        self.fixture.p2.run_fixture(config=config)
        self.fixture.replay()

    def grading(self, change):
        f = self.fixture
        path = f.p2.assets_root / "fixtures/grading.json"
        obj = read_json(path)
        change(obj)
        f.inputs.save(path, obj)
        f.inputs.manifest["grading_contracts"] = [f.inputs.assets.ref("fixtures/grading.json")]
        f.inputs.run_preflight()

    def relock(self):
        folder = self.fixture.out
        self.fixture.inputs.save(folder / "artifacts.lock.json", {"files": {
            str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob("*") if p.is_file() and p != folder / "artifacts.lock.json"}})

    def codes(self):
        return {i["code"] for i in read_json(self.out / "validation.json")["issues"]}

    def test_exact_btc_cli_report_wrong_value_fail_incomplete_and_replay(self):
        self.execute(config=None)
        original = (self.fixture.out / "artifacts.lock.json").read_bytes()
        report = score(self.fixture.out, self.out)
        self.assertEqual(report["status"]["verdict"], "FAIL")
        self.assertEqual(report["status"]["completeness"], "INCOMPLETE")
        self.assertIn("FACT_VALUE_WRONG_OR_UNUSED", self.codes())
        official = read_json(self.out / "official-report.json")
        self.assertEqual(official["system"]["context_carryover_rate"]["value"], 100)
        validate("OfficialReport", official)
        validate("SupplementalReport", read_json(self.out / "supplemental-report.json"))
        invocation = read_json(self.out / "scorer-invocation.json")
        # Repeat the exact unmodified BTC CLI to an independent temporary output.
        argv = invocation["argv"][:]
        argv[argv.index("--out") + 1] = str(self.root / "parity.json")
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_json(self.root / "parity.json"), official)
        self.assertEqual((self.fixture.out / "artifacts.lock.json").read_bytes(), original)
        locked_run(self.fixture.out)
        locked_run(self.out)

    def test_negative_only_missing_trace_never_supplemental_pass(self):
        self.execute()
        (self.fixture.out / "full.jsonl").write_text("", encoding="utf-8")
        self.relock()  # Synthetic mutation, never production run rewriting.
        report = score(self.fixture.out, self.out)
        self.assertEqual(read_json(self.out / "official-report.json")["system"]["task_success_rate"]["value"], 100, read_json(self.out / "official-report.json"))
        self.assertTrue(report["diagnostic_only"])
        self.assertNotEqual(report["status"]["verdict"], "PASS")
        self.assertIn("TRACE_COVERAGE", self.codes())
        self.assertEqual(len(read_json(self.out / "coverage.json")["missing_ids"]), 2)

    def order_fixture(self, args=None):
        args = args or {"customer_phone": "0900000000", "sku": "FIXTURE-MISSING-SKU", "qty": 1,
                        "price_vnd": 100, "payment": "COD"}
        f = self.fixture
        def labels(records):
            tool = json.dumps({"name": "crm.get_customer", "args": {"phone": "0900000000"}}, ensure_ascii=False, sort_keys=True)
            order = json.dumps({"name": "order.create", "args": args}, ensure_ascii=False, sort_keys=True)
            records[0]["input_sha256"] = digest({"agent_text": p3.FIRST_TEXT, "tool_texts": [tool, order], "consultant_texts": []})
        suffix = "\noriginal_turn=FixtureAdapter.run_turn\ndef order_turn(self,text):\n    if self.call['call']=='call_1':\n        self.runtime['call_tool']('order.create'," + repr(args) + ")\n    return original_turn(self,text)\nFixtureAdapter.run_turn=order_turn\n"
        f.configure(suffix, labels)
        f.p2.scenario(lambda s: s["calls"]["call_1"].update(success_if={"tool_called": "order.create", "args_match": args}))
        expected = {"schema_version": "1.0.0", "artifact_id": "fixture/tool-labels", "run_id": "FIXTURE-R0",
            "context": {"run_id": "FIXTURE-R0", "config": "full", "scenario_id": "FIXTURE-M1", "call": "call_1", "turn": 1},
            "calls": [{"name": "order.create", "args_match": args, "required": True}],
            "allow_extra_read_only": True, "labelled_by": "independent-fixture-before-execution", "evidence_refs": []}
        f.inputs.save(f.p2.assets_root / "expected-tools.json", expected)
        pinned = f.inputs.assets.ref("expected-tools.json")
        f.inputs.manifest["sources"].append(pinned)
        def grading(g):
            g["calls"][0]["checks"] = [
                {"check_id": "create-success", "kind": "tool_success", "params": {"tool_name": "order.create", "expected_status": "success"}, "required_evidence": ["tools"]},
                {"check_id": "invocation", "kind": "tool_accuracy", "params": {"expected_calls": pinned}, "required_evidence": ["tools"]}]
        self.grading(grading)

    def test_verified_new_order_close_and_seed_or_missing_state_not_counted(self):
        with MockEnvironment("FIXTURE-PRICE", "fixture", "full") as env:
            quote = env.call_tool("pricing.get_quote", {"sku": "SKU-AP-PRO", "customer_phone": "0900000000", "qty": 1}, call="call_1", turn=1, on="2026-10-15")
        self.order_fixture({"customer_phone": "0900000000", "sku": "SKU-AP-PRO", "qty": 1,
                            "price_vnd": quote["final_price_vnd"], "payment": "bank"})
        self.execute()
        score(self.fixture.out, self.out)
        verified = read_json(self.out / "full/verified-orders.json")
        self.assertEqual(len(verified["event_ids"]), 1)
        self.assertEqual(verified["first_close_call_by_scenario"], {"FIXTURE-M1": 1})
        records = read_json(self.fixture.out / "full/raw-records.json")
        audit = next(r["data"] for r in records if r["kind"] == "tool_audit" and r["data"]["event"]["request"]["name"] == "order.create")
        self.assertTrue(new_order_verified(audit["event"], audit["state_before"], audit["state_after"]))
        self.assertFalse(new_order_verified(audit["event"], audit["state_before"], audit["state_before"]))
        self.assertFalse(new_order_verified(audit["event"], audit["state_after"], audit["state_after"]))

    def test_memory_ttl_delete_and_profile_state_contradictions(self):
        self.fixture.configure("\noriginal_snapshot=FixtureAdapter.snapshot\ndef bad_snapshot(self,visible=False):\n    snapshot=original_snapshot(self,visible)\n    for fact in snapshot['facts']:\n        fact['valid_until']='2026-10-15T00:00:00+07:00'\n        fact['customer_id']='WRONG-PROFILE'\n    for w in snapshot['writes']:\n        w['op']='delete'\n    return snapshot\nFixtureAdapter.snapshot=bad_snapshot\n")
        self.execute()
        report = score(self.fixture.out, self.out)
        self.assertEqual(report["status"]["verdict"], "FAIL")
        self.assertIn("MEMORY_INACTIVE_VALUE_EXPOSED", self.codes())
        self.assertIn("MEMORY_WRITE_STATE", self.codes())
        self.assertIn("MEMORY_WRONG_PROFILE", self.codes())

    def test_brief_schema_pass_but_wrong_profile_and_fact_fails_supplemental(self):
        self.fixture.configure("\noriginal_start=FixtureAdapter.start_call\ndef wrong_brief(self,context):\n    result=original_start(self,context)\n    if result['call_brief'] is not None:\n        result['call_brief']['customer_phone']='0911111111'\n        result['call_brief']['profile_facts']['room_area_m2']=30\n    return result\nFixtureAdapter.start_call=wrong_brief\n")
        self.execute()
        score(self.fixture.out, self.out)
        self.assertIn("BRIEF_WRONG_PROFILE", self.codes())
        self.assertIn("BRIEF_FACT_WRONG", self.codes())
        self.assertNotIn("BRIEF_INVALID", self.codes())

    def test_schema_fragment_assertion_and_explicit_memory_expectation(self):
        f = self.fixture
        expectation = {"room_area_m2": 25, "address_ttl_check": True}
        f.inputs.save(f.p2.assets_root / "memory-expectation.json", expectation)
        pinned = f.inputs.assets.ref("memory-expectation.json")
        f.inputs.manifest["sources"].append(pinned)
        def grading(g):
            g["calls"][0]["checks"] = [
                {"check_id": "wire", "kind": "schema", "params": {"schema_ref": "sources/btc/schemas/trace_log.schema.json", "artifact_role": "trace"}, "required_evidence": ["trace"]},
                {"check_id": "fragment", "kind": "schema", "params": {"schema_ref": "contracts.schema.json#/$defs/ToolArgs", "artifact_role": "tool_args"}, "required_evidence": ["tools"]},
                {"check_id": "state", "kind": "memory", "params": {"expectation": pinned}, "required_evidence": ["memory"]}]
        self.grading(grading)
        self.execute()
        score(f.out, self.out)
        self.assertIn("MEMORY_EXPECTATION_SEMANTICS_PENDING", self.codes())
        self.assertNotIn("MEMORY_EXPECTATION_WRONG", self.codes())
        checks = read_json(self.out / "supplemental-report.json")["checks"]
        self.assertEqual(next(c for c in checks if c["check_id"].endswith("/wire"))["status"]["verdict"], "PASS")
        self.assertEqual(next(c for c in checks if c["check_id"].endswith("/fragment"))["status"]["verdict"], "PASS")

    def test_trace_role_leak_and_tool_wrong_config_are_evidence_errors(self):
        self.execute(config=None)
        path = self.fixture.out / "full.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["claims"].append({"field": "price_vnd", "value": 999, "text": "consultant-only"})
        path.write_text("".join(json.dumps(r,ensure_ascii=False) + "\n" for r in rows))
        source = self.fixture.out / "baseline_no_memory/tools.jsonl"
        (self.fixture.out / "full/tools.jsonl").write_bytes(source.read_bytes())
        self.relock()
        score(self.fixture.out, self.out)
        self.assertIn("TRACE_EXTRACTION_MISMATCH", self.codes())
        self.assertIn("EVIDENCE_SCHEMA", self.codes())
        self.assertIn("TOOL_EVIDENCE_COVERAGE", self.codes())

    def test_invocation_tp_business_error_official_tsr_pass_supplemental_fail(self):
        self.order_fixture()
        self.execute()
        report = score(self.fixture.out, self.out)
        self.assertEqual(read_json(self.out / "official-report.json")["system"]["task_success_rate"]["value"], 100, {"official":read_json(self.out / "official-report.json"),"collector":read_json(self.fixture.out / "validation.json")})
        self.assertEqual(report["status"]["verdict"], "FAIL")
        self.assertIn("TOOL_BUSINESS_ERROR", self.codes())
        matches = read_json(self.out / "assertion-details.json")[0]["matching"]
        self.assertEqual((matches["tp"], matches["fp"], matches["fn"]), (1, 0, 0))
        self.assertEqual(matches["value"], 100)
        self.assertEqual(read_json(self.out / "full/verified-orders.json")["event_ids"], [])

    def test_judge_hybrid_pending_does_not_override_hard_fail(self):
        rubric = self.fixture.inputs.assets.ref("sources/btc/eval/llm_judge_rubric.json")
        def grading(g):
            call = g["calls"][0]
            call["mode"], call["aggregation"] = "hybrid", "AND"
            call["criteria"] = [{"criterion_id": "J06_tone_vietnamese", "condition": "all", "rubric_ref": rubric}]
            call["checks"] = [{"check_id": "pii", "kind": "guardrail", "params": {"patterns": ["5000000"]}, "required_evidence": ["trace"]}]
        self.grading(grading)
        self.execute()
        report = score(self.fixture.out, self.out)
        self.assertIn("JUDGE_PENDING", self.codes())
        self.assertIn("GUARDRAIL_PATTERN", self.codes())
        self.assertEqual(report["status"], read_json(self.out / "supplemental-report.json")["status"])
        self.assertEqual(report["status"]["verdict"], "FAIL")
        self.assertEqual(report["status"]["completeness"], "INCOMPLETE")

    def test_duplicate_and_malformed_rows_keep_diagnostic_coverage(self):
        self.execute()
        path = self.fixture.out / "full.jsonl"
        path.write_text(path.read_text() + path.read_text().splitlines()[0] + '\n{"broken":true}\n')
        self.relock()
        report = score(self.fixture.out, self.out)
        self.assertTrue(report["diagnostic_only"])
        self.assertIn("EVIDENCE_SCHEMA", self.codes())
        self.assertTrue(read_json(self.out / "coverage.json")["duplicate_ids"])

    def test_scorer_failure_is_infra_not_fake_official_report(self):
        self.execute()
        with patch("evaluation.eval_harness.scoring.subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="fault injection")):
            report = score(self.fixture.out, self.out)
        self.assertFalse(report["official_report_available"])
        self.assertFalse((self.out / "supplemental-report.json").exists())
        self.assertIn("SCORER_INFRA", self.codes())
        validate("ValidationReport", read_json(self.out / "validation.json"))

    def test_hash_tamper_rejected_before_output_and_no_overwrite(self):
        self.execute()
        score(self.fixture.out, self.out)
        with self.assertRaises(ValueError):
            score(self.fixture.out, self.out)
        (self.fixture.out / "full.jsonl").write_text("tampered")
        target = self.root / "must-not-exist"
        with self.assertRaises(ValueError):
            score(self.fixture.out, target)
        self.assertFalse(target.exists())

    def test_cli_other_cwd_hard_fail_exit_and_invalid_run(self):
        self.execute()
        wrapper = ROOT.parent / "run_eval.py"
        result = subprocess.run([sys.executable, "-B", str(wrapper), "score", "--run", str(self.fixture.out), "--out", str(self.out)], cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["official_report_available"])
        result = subprocess.run([sys.executable, "-B", str(wrapper), "score", "--run", str(self.root / "missing"), "--out", str(self.root / "unused")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)


if __name__ == "__main__":
    unittest.main()
