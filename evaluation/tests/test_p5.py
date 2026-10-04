"""P5 provisional registry and existing native ASR replay, without model calls."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.eval_harness.assets import Assets, read_json
from evaluation.eval_harness.asr_suite import asr_suite, verify_lock
from evaluation.eval_harness.collector import locked_run
from evaluation.eval_harness.contracts import ROOT, validate
from evaluation.eval_harness.datasets import inspect_dataset, snapshot, dataset_readiness, new_output


class DatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.shared.cleanup)
        cls.original, cls.registry, refs, _ = inspect_dataset(ROOT.parent / "p5-settings.example.json")
        snapshot(Path(cls.shared.name), cls.original, refs)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(Path(self.shared.name) / "inputs", self.root / "assets")
        self.assets = Assets(self.root / "assets")
        self.data = copy.deepcopy(self.registry)
        self.settings = self.root / "settings.json"
        self.out = self.root / "result"
        self.pin()

    def save(self, name, data):
        path = self.assets.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return self.assets.ref(name)

    def pin(self):
        ref = self.save("datasets/p5-current/registry.json", self.data)
        self.settings.write_text(json.dumps({"asset_root": "assets", "registry": ref}))

    def mutate_hypotheses(self, change):
        cohort = self.data["asr"]["cohorts"]["dev"]
        obj = self.assets.resolve(cohort["replay"]["hypotheses"])
        change(obj)
        cohort["replay"]["hypotheses"] = self.save(cohort["replay"]["hypotheses"]["path"], obj)
        self.pin()

    def test_provisional_readiness_not_frozen_not_human_verified(self):
        report = dataset_readiness(self.settings, self.out)
        self.assertTrue(report["execution_gate"]["allowed"])
        self.assertFalse(report["benchmark_ready"])
        self.assertEqual(report["quotas"]["frozen_ordinary"]["actual"], 0)
        self.assertEqual(report["quotas"]["team_eval_audio"]["actual"], 20)
        self.assertEqual([r["human_verified"] for r in report["asr_inventory"]], [0, 0])
        # Includes JSON pointer refs: snapshot copies the entire pinned file.
        locked_run(self.out)

    def test_replay_parity_typed_coverage_no_new_timing_no_overwrite(self):
        report = asr_suite(self.settings, self.out, split="dev")
        self.assertEqual(report["status"]["verdict"], "PASS")
        self.assertFalse(report["human_review_complete"])
        self.assertFalse(report["new_inference"])
        self.assertFalse(report["quality_accepted"])
        self.assertIsNone(report["timing"]["asr_seconds_per_audio_minute"])
        for view in ("raw", "normalized"):
            self.assertEqual(report[view + "_metrics"], read_json(ROOT.parent / "asr/runs/dev-whisper-medium-v1" / view / "btc_metrics.json"))
        validate("Coverage", read_json(self.out / "coverage.json"))
        validate("ValidationReport", read_json(self.out / "validation.json"))
        locked_run(self.out)
        with self.assertRaisesRegex(ValueError, "new run directory"):
            asr_suite(self.settings, self.out, split="dev")

    def test_missing_and_unknown_hypotheses_keep_registered_cohort(self):
        self.mutate_hypotheses(lambda h: h.update(UNKNOWN=h.pop(next(iter(h)))))
        report = asr_suite(self.settings, self.out, split="dev")
        coverage = read_json(self.out / "coverage.json")
        self.assertEqual(len(coverage["expected_ids"]), 4)
        self.assertEqual(len(coverage["observed_ids"]), 3)
        self.assertEqual(len(coverage["missing_ids"]), 1)
        self.assertEqual(coverage["unknown_ids"], ["UNKNOWN"])
        self.assertEqual(report["status"]["completeness"], "INCOMPLETE")
        locked_run(self.out)

    def test_duplicate_json_native_failure_retains_partial_evidence(self):
        ref = self.data["asr"]["cohorts"]["dev"]["replay"]["hypotheses"]
        (self.assets.root / ref["path"]).write_text('{"X":{},"X":{}}')
        ref.update(self.assets.ref(ref["path"]))
        self.pin()
        # Strict registry resolution catches malformed JSON before execution.
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            asr_suite(self.settings, self.out, split="dev")
        self.assertFalse(self.out.exists())

    def test_required_review_blocks_without_modifying_metadata(self):
        self.data["review_policy"] = {"required": True, "reason": "production review gate"}
        self.pin()
        with self.assertRaisesRegex(ValueError, "HUMAN_REVIEW_PENDING"):
            asr_suite(self.settings, self.out)
        self.assertFalse(self.out.exists())

    def test_missing_audio_readiness_reports_and_blocks_suite(self):
        ref = self.data["asr"]["cohorts"]["eval"]["audio"][0]["asset"]
        (self.assets.root / ref["path"]).unlink()
        report = dataset_readiness(self.settings, self.out)
        self.assertIn("ASR_AUDIO_MISSING_OR_INVALID", report["execution_gate"]["reason_codes"])
        self.assertEqual(report["quotas"]["team_eval_audio"]["actual"], 19)
        locked_run(self.out)
        with self.assertRaisesRegex(ValueError, "execution blocked"):
            asr_suite(self.settings, self.root / "blocked")

    def test_audio_hash_corruption_blocks(self):
        ref = self.data["asr"]["cohorts"]["dev"]["audio"][0]["asset"]
        with (self.assets.root / ref["path"]).open("ab") as stream:
            stream.write(b"corruption")
        report = inspect_dataset(self.settings)[3]
        self.assertFalse(report["execution_gate"]["allowed"])

    def test_pinned_invalid_wav_and_customer_split_leak(self):
        ref = self.data["asr"]["cohorts"]["dev"]["audio"][0]["asset"]
        (self.assets.root / ref["path"]).write_bytes(b"not a wav")
        ref.update(self.assets.ref(ref["path"]))
        cohort = self.data["asr"]["cohorts"]["eval"]
        gt = self.assets.resolve(cohort["ground_truth"])
        gt["dialogues"][0]["entities"]["phone"] = "0900000000"
        cohort["ground_truth"] = self.save(cohort["ground_truth"]["path"], gt)
        self.pin()
        codes = inspect_dataset(self.settings)[3]["execution_gate"]["reason_codes"]
        self.assertIn("CUSTOMER_SPLIT_LEAK", codes)
        self.assertIn("ASR_AUDIO_MISSING_OR_INVALID", codes)

    def test_infer_branch_pins_model_lock_and_never_uses_replay_or_default_small(self):
        from evaluation.eval_harness.asr_suite import file_hash
        model = self.assets.root / self.data["asr"]["model_dir"]
        model.mkdir(parents=True)
        (model / "model.bin").write_bytes(b"test-only pinned weights, not inference")
        lock = self.assets.resolve(self.data["asr"]["dev_lock"])
        lock["model_files"] = {"model.bin": file_hash(model / "model.bin")}
        self.data["asr"]["dev_lock"] = self.save(self.data["asr"]["dev_lock"]["path"], lock)
        for cohort in self.data["asr"]["cohorts"].values():
            cohort["replay"] = None
        self.pin()
        with patch("evaluation.eval_harness.asr_suite.subprocess.run", return_value=type("Result", (), {"returncode": 1})()) as run:
            report = asr_suite(self.settings, self.out, mode="infer")
        argv = run.call_args.args[0]
        self.assertIn("--lock", argv)
        self.assertNotIn("--hypotheses", argv)
        self.assertEqual(argv[argv.index("--model") + 1], str(model.resolve()))
        self.assertFalse(report["new_inference"])
        self.assertEqual(report["status"]["completeness"], "INCOMPLETE")

    def test_replay_gt_lineage_mismatch_blocks(self):
        cohort = self.data["asr"]["cohorts"]["eval"]
        history = self.assets.resolve(cohort["replay"]["manifest"])
        history["ground_truth_sha256"] = "0" * 64
        cohort["replay"]["manifest"] = self.save(cohort["replay"]["manifest"]["path"], history)
        self.pin()
        self.assertIn("REPLAY_GT_MISMATCH", inspect_dataset(self.settings)[3]["execution_gate"]["reason_codes"])

    def test_split_audio_duplication_blocks(self):
        cohort = self.data["asr"]["cohorts"]
        cohort["eval"]["audio"][0]["asset"] = cohort["dev"]["audio"][0]["asset"]
        self.pin()
        self.assertIn("ASR_SPLIT_OR_AUDIO_DUPLICATE", inspect_dataset(self.settings)[3]["execution_gate"]["reason_codes"])

    def test_dev_code_lock_mismatch_rejects_before_subprocess(self):
        lock = self.assets.resolve(self.data["asr"]["dev_lock"])
        lock["code_hashes"]["run_eval.py"] = "0" * 64
        self.data["asr"]["dev_lock"] = self.save(self.data["asr"]["dev_lock"]["path"], lock)
        self.pin()
        with patch("evaluation.eval_harness.asr_suite.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "code differs"):
                asr_suite(self.settings, self.out)
            run.assert_not_called()

    def test_inference_model_mismatch_and_replay_without_history(self):
        model = self.assets.root / self.data["asr"]["model_dir"]
        model.mkdir(parents=True)
        (model / "model.bin").write_bytes(b"wrong model")
        with self.assertRaisesRegex(ValueError, "model inventory/hash"):
            verify_lock(self.assets, self.data, "eval", "infer")
        self.data["asr"]["cohorts"]["eval"]["replay"] = None
        self.pin()
        self.assertTrue(inspect_dataset(self.settings)[3]["execution_gate"]["allowed"])
        with self.assertRaisesRegex(ValueError, "No historical replay"):
            asr_suite(self.settings, self.out)

    def test_subprocess_failure_does_not_fabricate_observations(self):
        with patch("evaluation.eval_harness.asr_suite.subprocess.run", side_effect=subprocess.TimeoutExpired("native", 120)):
            report = asr_suite(self.settings, self.out, split="dev")
        self.assertEqual(report["status"]["completeness"], "INCOMPLETE")
        self.assertEqual(len(read_json(self.out / "coverage.json")["missing_ids"]), 4)
        self.assertIsNone(report["raw_metrics"])
        self.assertTrue((self.out / "stderr.log").is_file())
        locked_run(self.out)

    def test_protected_output_and_unrecognized_review_waiver(self):
        with self.assertRaisesRegex(ValueError, "dataset/model"):
            new_output(self.assets.root / "asr/datasets/synthetic-v1/dev/new", self.assets, self.data)
        self.data["review_policy"]["reason"] = "pretend reviewed"
        self.pin()
        with self.assertRaisesRegex(ValueError, "silently waive"):
            inspect_dataset(self.settings)

    def test_cli_other_cwd_readiness_exit_and_invalid_mode(self):
        wrapper = ROOT.parent / "run_eval.py"
        command = [sys.executable, "-B", str(wrapper)]
        result = subprocess.run(command + ["dataset-readiness", "--settings", str(self.settings), "--out", str(self.out)],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertTrue(json.loads(result.stdout)["execution_gate"]["allowed"])
        result = subprocess.run(command + ["asr-suite", "--settings", str(self.settings), "--out", str(self.root / "new"), "--mode", "bad"],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 3)


if __name__ == "__main__":
    unittest.main()
