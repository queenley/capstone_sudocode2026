import json
import tempfile
import unittest
from pathlib import Path

from src.reports.history import render_history


class HistoryTest(unittest.TestCase):
    def test_completed_and_failed_runs(self):
        with tempfile.TemporaryDirectory() as root:
            runs = Path(root)
            failed = runs / "20261010-100000"
            failed.mkdir()
            (failed / "execution-report.json").write_text(json.dumps({
                "stages": [{"stage": "run", "completed_calls": 0, "execution_complete": False,
                            "errors": [{"code": "EXECUTION_ERROR", "phase": "open_scenario"}]}],
                "pipeline_error": None,
            }))
            complete = runs / "20261010-110000"
            (complete / "scored").mkdir(parents=True)
            (complete / "execution-report.json").write_text(json.dumps({
                "stages": [{"stage": "run", "completed_calls": 24},
                           {"stage": "score", "status": {"verdict": "FAIL", "completeness": "INCOMPLETE",
                                                         "reason_codes": ["USAGE_MISSING"]}}],
                "pipeline_error": None,
            }))
            (complete / "scored/official-report.json").write_text(json.dumps({
                "baseline": {"task_success_rate": {"value": 20}},
                "system": {"task_success_rate": {"value": 40}},
            }))
            table = render_history(runs)
            self.assertIn("20261010-100000 | 0 | — → —", table)
            self.assertIn("ERROR | EXECUTION_ERROR (open_scenario)", table)
            self.assertIn("20261010-110000 | 24 | 20% → 40%", table)
            self.assertIn("FAIL/INCOMPLETE | USAGE_MISSING", table)

    def test_runs_inside_a_folder_that_only_groups_them_are_listed_and_the_folder_is_not(self):
        with tempfile.TemporaryDirectory() as root:
            runs = Path(root)
            group = runs / "20261024-work"
            (group / "development-r0-M1/scored").mkdir(parents=True)
            (group / "development-r0-M1/execution-report.json").write_text(json.dumps({
                "stages": [{"stage": "run", "completed_calls": 12}, {"stage": "score", "status": {"verdict": "PASS", "completeness": "COMPLETE"}}],
                "pipeline_error": None}))
            (group / "development-r0-M1/scored/official-report.json").write_text(json.dumps({
                "baseline": {"task_success_rate": {"value": 10}}, "system": {"task_success_rate": {"value": 30}}}))
            (group / "started-never-finished/raw").mkdir(parents=True)
            (group / "prepared-only").mkdir()
            (group / "prepared-only/manifest.json").write_text("{}")
            (group / "budget-notes").mkdir()                      # neither a run nor holding one
            (group / "budget.sqlite").write_text("")
            table = render_history(runs)
            self.assertIn("| 20261024-work/development-r0-M1 | 12 | 10% → 30%", table)
            self.assertIn("| 20261024-work/started-never-finished | — |", table)
            self.assertIn("| 20261024-work/prepared-only | — |", table)
            self.assertNotIn("| 20261024-work/budget-notes |", table)
            self.assertNotIn("| 20261024-work |", table)

    def test_a_folder_with_no_run_inside_is_still_shown_as_missing_its_report(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "20261010-100000").mkdir()
            table = render_history(Path(root))
            self.assertIn("| 20261010-100000 | — | — | — | — | INCOMPLETE | EXECUTION_REPORT_MISSING", table)

    def test_a_run_directly_under_runs_keeps_its_own_name(self):
        with tempfile.TemporaryDirectory() as root:
            run = Path(root) / "20261010-100000"
            (run / "raw").mkdir(parents=True)
            self.assertIn("| 20261010-100000 |", render_history(Path(root)))


if __name__ == "__main__":
    unittest.main()
