import json
import tempfile
import unittest
from unittest.mock import patch
import sys
from pathlib import Path

from src.datasets.registry import inspect
from src.steps.prepare.prepare import EVALUATION as ROOT, prepare


class DataRegistryTest(unittest.TestCase):
    def test_create_data_revision_has_a_label_per_call(self):
        root = ROOT / "datasets" / "create-data-diagnostic-v2"
        if not root.is_dir():
            self.skipTest("normalize_create_data.py has not been run")
        report = inspect(ROOT / "datasets", only="create-data-diagnostic-v2")
        self.assertEqual(report["issues"], [])
        self.assertFalse(report["execution_gate"]["allowed"])  # diagnostic, never approved by the generator
        labels = json.loads((root / "tool-labels.json").read_text(encoding="utf-8"))
        for path in (root / "scenarios").glob("*.json"):
            scenario = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(labels[scenario["scenario_id"]]), set(scenario["calls"]))

    def test_registered_sixth_case_can_prepare_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "new/scenarios"
            directory.mkdir(parents=True)
            sample = json.loads(next((ROOT / "datasets/create-data-diagnostic-v4/scenarios").glob("SCN-GEN-*.json")).read_text(encoding="utf-8"))
            sample["scenario_id"] = "TEAM-NEW-0006"
            (directory / "TEAM-NEW-0006.json").write_text(json.dumps(sample), encoding="utf-8")
            labels = {sample["scenario_id"]: {call: ([{"name": spec["success_if"]["tool_called"],
                "args_match": spec["success_if"].get("args_match", {}), "required": True}]
                if spec["success_if"].get("tool_called") else []) for call, spec in sample["calls"].items()}}
            (root / "labels.json").write_text(json.dumps(labels))
            reviews = {sample["scenario_id"]: {call: {"status": "approved", "reviewed_by": "human-reviewer",
                "source": "BTC policy and mock state for the call date", "decision": "Verified expected outcome and success conditions"}
                for call in sample["calls"]}}
            (root / "review.json").write_text(json.dumps(reviews))
            (root / "registry.json").write_text(json.dumps({"schema_version": "team-datasets-v1", "sets": [
                {"id": "new", "split": "development", "path": "new/scenarios", "tool_labels": "labels.json",
                 "gt_review": "review.json", "reviewed_by": "human-reviewer", "status": "approved"}]}))
            self.assertTrue(inspect(root, only="new")["execution_gate"]["allowed"])
            (root / "review.json").write_text("{}")
            self.assertFalse(inspect(root, only="new")["execution_gate"]["allowed"])
            (root / "review.json").write_text(json.dumps(reviews))
            with patch("src.steps.prepare.prepare.DATASETS", root), patch("src.steps.prepare.prepare.PYTHON", Path(sys.executable)), patch("src.steps.prepare.prepare.product_settings", return_value={
                "provider": "test", "model": "test-model", "parameters": {"temperature": 0},
                "extractor": {"provider": "test", "model": "test-model"},
            }):
                report = prepare(root / "prepared", dataset_id="new")
            self.assertTrue(report["execution_gate"]["allowed"])


if __name__ == "__main__":
    unittest.main()
