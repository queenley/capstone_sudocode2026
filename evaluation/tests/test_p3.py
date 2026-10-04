"""Offline P3 evidence/extraction integration. No provider or product database."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.eval_harness.assets import Assets, read_json
from evaluation.eval_harness.collector import collect, locked_run, export_trace
from evaluation.eval_harness.contracts import ROOT, checker, validate
from evaluation.eval_harness.extractor import digest, extractor_input
from evaluation.eval_harness import extractor as implementation
from evaluation.tests import test_p2 as p2

FIRST_TEXT = "Phòng chị bao nhiêu m²? Máy giá 5000000 đồng, giao 2 ngày."
SECOND_TEXT = "Vẫn phòng 30 m² đúng không ạ? Vẫn phòng 30 m² đúng không ạ?"


def annotation(text, quote, kind, field, value=None, question_type=None, start=None, speaker="agent", source_field="agent_text"):
    start = text.index(quote) if start is None else start
    return {"kind": kind, "slot_or_field": field, "value": value, "question_type": question_type,
            "speaker": speaker, "source_field": source_field, "quote": quote,
            "start": start, "end": start + len(quote), "purpose": "Fixture annotation from actual scripted source"}


def setUpModule():
    checker.verify_sources()


def tearDownModule():
    checker.verify_sources()


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.p2 = p2.RunnerTest()
        self.p2.setUp()
        self.addCleanup(self.p2.doCleanups)
        self.root, self.inputs = self.p2.root, self.p2.inputs
        self.out = self.root / "collected"
        self.configure()

    def configure(self, suffix="", change_records=None):
        code = (ROOT / "fixtures/p3-adapter.py").read_text(encoding="utf-8") + suffix
        (self.p2.assets_root / "adapter.py").write_text(code, encoding="utf-8")
        descriptor = read_json(self.p2.assets_root / "adapter.json")
        descriptor["code"] = self.inputs.assets.ref("adapter.py")
        self.inputs.save(self.p2.assets_root / "adapter.json", descriptor)
        adapter_ref = self.inputs.assets.ref("adapter.json")
        settings = read_json(self.p2.settings)
        settings["adapter"] = adapter_ref
        self.inputs.save(self.p2.settings, settings)
        schema_path = self.p2.assets_root / "contracts.schema.json"
        schema_path.write_bytes((ROOT / "contracts.schema.json").read_bytes())
        self.schema_ref = self.inputs.assets.ref("contracts.schema.json", "/$defs/Extraction")
        tool = json.dumps({"name": "crm.get_customer", "args": {"phone": "0900000000"}}, ensure_ascii=False, sort_keys=True)
        first = [annotation(FIRST_TEXT, "Phòng chị bao nhiêu m²?", "question", "room_area_m2", question_type="open"),
                 annotation(FIRST_TEXT, "5000000 đồng", "claim", "price_vnd", 5000000),
                 annotation(FIRST_TEXT, "2 ngày", "claim", "delivery_days", 2)]
        quote = "Vẫn phòng 30 m² đúng không ạ?"
        second = [annotation(SECOND_TEXT, quote, "question", "room_area_m2", 30, "confirm", start=0),
                  annotation(SECOND_TEXT, quote, "question", "room_area_m2", 30, "confirm", start=len(quote) + 1),
                  annotation(SECOND_TEXT, "30 m²", "fact_usage", "room_area_m2", 30)]
        self.records = [{"input_sha256": digest({"agent_text": text, "tool_texts": [tool], "consultant_texts": []}), "items": items}
                        for text, items in ((FIRST_TEXT, first), (SECOND_TEXT, second))]
        if change_records:
            change_records(self.records)
        self.inputs.save(self.p2.assets_root / "records.json", self.records)
        self.extractor = {"kind": "fixture_replay", "version": "fixture-p3-v1", "records": self.inputs.assets.ref("records.json"),
                          "schema": self.schema_ref, "implementation_sha256": hashlib.sha256(Path(implementation.__file__).read_bytes()).hexdigest()}
        self.inputs.save(self.p2.assets_root / "extractor.json", self.extractor)
        self.inputs.manifest["sources"] = self.inputs.manifest["sources"][:2] + [adapter_ref, descriptor["code"],
            self.inputs.assets.ref("extractor.json"), self.extractor["records"], self.schema_ref]
        self.inputs.manifest["configuration"]["extractor_version"] = self.extractor["version"]
        self.inputs.run_preflight()

    def replay(self, **kwargs):
        return collect(self.p2.out, self.out, extractor_path="extractor.json", **kwargs)

    def lines(self, name):
        return [json.loads(line) for line in (self.out / name).read_text(encoding="utf-8").splitlines()]

    def codes(self):
        return {i["code"] for i in read_json(self.out / "validation.json")["issues"]}

    def relock(self):
        # Mutations are synthetic tests only; production closed runs are never rewritten.
        self.inputs.save(self.p2.out / "artifacts.lock.json", {"files": {
            str(p.relative_to(self.p2.out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.p2.out.rglob("*") if p.is_file() and p.name != "artifacts.lock.json"}})

    def test_export_complete_cohort_not_quality_and_refuse_partial(self):
        self.p2.run_fixture()
        self.replay()
        target = self.root / "export.jsonl"
        report = export_trace(self.out, target, "full")
        self.assertTrue(report["exported"])
        self.assertFalse(report["quality_accepted"])
        self.assertEqual(target.read_bytes(), (self.out / "full.jsonl").read_bytes())
        with self.assertRaises(ValueError):
            export_trace(self.out, target, "full")
        partial = self.root / "partial"
        collect(self.p2.out, partial)
        target = self.root / "not-created.jsonl"
        self.assertFalse(export_trace(partial, target, "full")["exported"])
        self.assertFalse(target.exists())

    def test_missing_after_turn_memory_not_invented_from_after_call(self):
        self.configure("\noriginal_turn=FixtureAdapter.run_turn\ndef no_memory(self,text):\n    result=original_turn(self,text)\n    result.pop('memory_snapshot')\n    return result\nFixtureAdapter.run_turn=no_memory\n")
        self.p2.scenario(lambda scenario: scenario["calls"]["call_2"].update(memory_expectation={}))
        self.p2.run_fixture()
        report = self.replay()
        self.assertFalse(report["trace_wire_complete"])
        self.assertIn("MEMORY_WRITES_MISSING", self.codes())
        self.assertTrue(any(m["phase"] == "after_call" for m in self.lines("full/memory.jsonl")))

    def test_consultant_tool_claims_excluded_from_agent_predictions(self):
        consultant = "Giá là 999 đồng"
        tool = json.dumps({"name": "crm.get_customer", "args": {"phone": "0900000000"}}, ensure_ascii=False, sort_keys=True)
        def labels(records):
            for record, text in zip(records, (FIRST_TEXT, SECOND_TEXT)):
                record["input_sha256"] = digest({"agent_text": text, "tool_texts": [tool], "consultant_texts": [consultant]})
                record["items"] += [annotation(consultant, "999 đồng", "claim", "price_vnd", 999,
                    speaker="consultant", source_field="consultant_texts/0"),
                    annotation(tool, "0900000000", "claim", "customer_phone", "0900000000",
                    speaker="tool", source_field="tool_texts/0")]
        self.configure("\noriginal_turn=FixtureAdapter.run_turn\ndef consultant_turn(self,text):\n    self.emit({'role':'consultant','text':'Giá là 999 đồng'})\n    return original_turn(self,text)\nFixtureAdapter.run_turn=consultant_turn\n", labels)
        self.p2.run_fixture()
        self.assertTrue(self.replay()["trace_wire_complete"], self.codes())
        for row in self.lines("full.jsonl"):
            self.assertNotIn(999, [claim["value"] for claim in row["claims"]])
            self.assertNotIn("customer_phone", [claim["field"] for claim in row["claims"]])

    def test_replay_valid_wire_unicode_two_claims_confirm_repeat_wrong_value_and_no_gold(self):
        self.assertTrue(self.p2.run_fixture()["execution_complete"])
        original = (self.p2.out / "artifacts.lock.json").read_bytes()
        report = self.replay()
        self.assertTrue(report["trace_wire_complete"], self.codes())
        self.assertEqual(report["trace_rows"], 4)
        self.assertEqual(report["typed_memory_records"], 12)
        self.assertEqual(report["status"]["completeness"], "INCOMPLETE")
        self.assertIn("USAGE_MISSING", self.codes())
        self.assertIn("EXTRACTOR_AUDIT_PENDING", self.codes())
        for filename in ("full.jsonl", "baseline.jsonl"):
            rows = self.lines(filename)
            self.assertEqual(len(rows[0]["claims"]), 2)
            self.assertEqual([q["type"] for q in rows[1]["questions"]], ["confirm", "confirm"])
            self.assertEqual(rows[1]["facts_used"], ["room_area_m2"])
            for row in rows:
                self.assertEqual(checker.errors("sources/btc/schemas/trace_log.schema.json", row), [])
        for config in ("full", "baseline_no_memory"):
            for definition, filename in (("Extraction", "extraction.jsonl"), ("TimingEvidence", "timing.jsonl"),
                                         ("MemoryEvidence", "memory.jsonl"), ("BriefEvidence", "brief-evidence.jsonl")):
                for item in self.lines(f"{config}/{filename}"):
                    validate(definition, item)
            extraction = self.lines(f"{config}/extraction.jsonl")[1]
            self.assertEqual(extraction["items"][-1]["value"], 30)  # Never "repair" to gold25.
            for item in extraction["items"]:
                source = Assets(self.out).resolve(item["source"])
                self.assertEqual(source[item["start"]:item["end"]], item["quote"])
            timings = self.lines(f"{config}/timing.jsonl")
            self.assertTrue(all(t["warmup"] for t in timings))  # Warmup is per config.
            self.assertTrue(all(t["input_tokens"] is None for t in timings))
        self.assertEqual((self.p2.out / "artifacts.lock.json").read_bytes(), original)
        locked_run(self.p2.out)
        locked_run(self.out)

    def test_old_p2_without_typed_memory_and_without_extractor_stays_incomplete(self):
        self.p2.configure()
        self.p2.run_fixture()
        report = collect(self.p2.out, self.out)
        self.assertFalse(report["trace_wire_complete"])
        self.assertIn("EXTRACTOR_NOT_CONFIGURED", self.codes())
        self.assertIn("MEMORY_EVIDENCE_MISSING", self.codes())
        self.assertEqual(self.lines("full.jsonl"), [])

    def test_wrong_quote_role_and_duplicate_labels_cannot_become_valid_trace(self):
        changes = [lambda r: r[0]["items"][0].update(quote="invented"),
                   lambda r: r[0]["items"][0].update(speaker="consultant"),
                   lambda r: r[0]["items"].append(copy.deepcopy(r[0]["items"][0]))]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.configure(change_records=change)
                self.p2.out = self.root / f"raw-{index}"
                self.out = self.root / f"output-{index}"
                self.p2.run_fixture()
                report = self.replay()
                self.assertFalse(report["trace_wire_complete"])
                self.assertIn("EXTRACTION_MISSING_OR_INVALID", self.codes())
                self.assertEqual(len(self.lines("full.jsonl")), 1)

    def test_missing_streaming_timestamp_no_fake_zero_and_nonstream_protocol(self):
        for streaming in (True, False):
            suffix = '\nbase_turn = FixtureAdapter.run_turn\ndef turn(self, text):\n    result = base_turn(self, text)\n    result["first_token_at"] = None\n    result["mode"] = "' + ("stream" if streaming else "nonstream") + '"\n    return result\nFixtureAdapter.run_turn = turn\n'
            self.configure(suffix)
            self.p2.out = self.root / f"raw-stream-{streaming}"
            self.out = self.root / f"stream-{streaming}"
            self.p2.run_fixture()
            report = self.replay()
            if streaming:
                self.assertFalse(report["trace_wire_complete"])
                self.assertEqual(self.lines("full.jsonl"), [])
                self.assertIn("TRACE_TIMING_MISSING", self.codes())
            else:
                self.assertTrue(report["trace_wire_complete"])
                self.assertTrue(all(r["latency"]["ttft_ms"] == r["latency"]["total_ms"] for r in self.lines("full.jsonl")))

    def test_wrong_profile_is_fail_even_with_missing_usage_and_human_review(self):
        self.configure('''
base_end = FixtureAdapter.end_call
async def end(self):
    result = await base_end(self)
    for fact in result["memory_snapshot"]["facts"]:
        fact["customer_id"] = "WRONG-PROFILE"
    return result
FixtureAdapter.end_call = end
''')
        self.p2.run_fixture()
        report = self.replay()
        self.assertEqual(report["status"]["verdict"], "FAIL")
        self.assertEqual(report["status"]["completeness"], "INCOMPLETE")
        self.assertIn("MEMORY_WRONG_PROFILE", self.codes())

    def test_brief_invalid_vs_missing_keeps_raw_and_distinguishes_fail(self):
        for missing in (False, True):
            suffix = '\nbase_start = FixtureAdapter.start_call\ndef start(self, context):\n    result = base_start(self, context)\n    if result["call_brief"] is not None:\n        ' + ('result["call_brief"] = None' if missing else 'result["call_brief"].pop("customer_phone")') + '\n    return result\nFixtureAdapter.start_call = start\n'
            self.configure(suffix)
            self.p2.out = self.root / f"raw-brief-{missing}"
            self.out = self.root / f"brief-{missing}"
            self.p2.run_fixture()
            report = self.replay()
            self.assertIn("BRIEF_MISSING" if missing else "BRIEF_INVALID", self.codes())
            self.assertEqual(report["status"]["verdict"], "UNDETERMINED" if missing else "FAIL")

    def test_lock_tampering_and_no_overwrite_rejected_before_output(self):
        self.p2.run_fixture()
        self.replay()
        with self.assertRaises(ValueError):
            self.replay()
        raw = self.p2.out / "full/raw-execution.jsonl"
        raw.write_bytes(raw.read_bytes() + b"\n")
        self.out = self.root / "tampered"
        with self.assertRaises(ValueError):
            self.replay()
        self.assertFalse(self.out.exists())

    def test_duplicate_turn_and_unfinished_barrier_preserve_coverage(self):
        self.p2.run_fixture()
        path = self.p2.out / "full/raw-execution.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        answer = next(r for r in rows if r["kind"] == "adapter_message" and r["data"].get("hook") == "run_turn")
        rows.append(copy.deepcopy(answer))
        end = next(r for r in rows if r["kind"] == "adapter_message" and r["data"].get("hook") == "end_call")
        end["data"]["result"]["barrier_complete"] = False
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        self.relock()
        report = self.replay()
        self.assertFalse(report["trace_wire_complete"])
        self.assertIn("CALL_BEFORE_BARRIER", self.codes())
        cov = read_json(self.out / "coverage/raw_turns.json")
        self.assertEqual(len(cov["duplicate_ids"]), 1)
        self.assertEqual(len(cov["expected_ids"]), 4)

    def test_extractor_implementation_pin_and_runtime_fixture_use_rejected(self):
        self.extractor["implementation_sha256"] = "0" * 64
        self.inputs.save(self.p2.assets_root / "extractor.json", self.extractor)
        self.inputs.manifest["sources"][4] = self.inputs.assets.ref("extractor.json")
        self.inputs.run_preflight()
        self.p2.run_fixture()
        report = self.replay()
        self.assertFalse(report["trace_wire_complete"])
        self.assertIn("EXTRACTOR_CONFIG", self.codes())

    def test_cli_replay_offline_partial_exit_and_audit_reproducibility(self):
        self.p2.run_fixture()
        command = [sys.executable, "-B", str(ROOT.parent / "run_eval.py"), "collect", "--run", str(self.p2.out),
                   "--extractor", "extractor.json", "--audit-seed", "42", "--out", str(self.out)]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["trace_wire_complete"])
        audit = read_json(self.out / "extractor-audit.json")
        self.assertEqual(audit["reviews"], [])
        self.assertEqual(len(audit["selected_ids"]), 4)
        self.assertEqual(len(set(audit["selected_ids"])), 4)


if __name__ == "__main__":
    unittest.main()
