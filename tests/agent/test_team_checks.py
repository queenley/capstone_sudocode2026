"""The team's say_at_most is counted beside the organisers' table, per configuration, and nothing checked is not a pass."""
import json

from ai_agent_service.pipeline.eval import report

PITCH = r"(?i)máy\s*thứ\s*(?:hai|2)|giảm\s*50\s*%"
WRONG = r"(?i)giảm\s*50\s*%\s*(?:cho\s*)?(?:cả hai|mỗi)\s*máy"


def scenario(tmp_path):
    folder = tmp_path / "scenarios"
    folder.mkdir()
    (folder / "S.json").write_text(json.dumps({"scenario_id": "S", "calls": {"call_1": {"success_if": {
        "tool_called": None, "say_at_most": [{"pattern": PITCH, "max": 2}, {"pattern": WRONG, "max": 0}]}}}}),
        encoding="utf-8")
    return folder


def trace(path, *texts):
    path.write_text("".join(json.dumps({"scenario_id": "S", "call": "call_1", "turn": i, "agent_text": t}) + "\n"
                            for i, t in enumerate(texts, 1)), encoding="utf-8")
    return path


def test_a_pitch_told_once_and_answered_once_passes_and_a_third_time_or_a_wrong_condition_fails(tmp_path):
    folder = scenario(tmp_path)
    good = trace(tmp_path / "full.jsonl", "Dạ bên em có chương trình máy thứ hai giảm 50% cho máy rẻ hơn ạ.",
                 "Dạ giảm 50% cho máy có giá thấp hơn, hai máy cùng một đơn ạ.", "Dạ em ghi nhận ạ.")
    bad = trace(tmp_path / "baseline.jsonl", "Máy thứ hai giảm 50% ạ.", "Giảm 50% cho cả hai máy luôn ạ.",
                "Chị nhớ là máy thứ 2 giảm 50% nhé.")
    checks = report.team_checks(folder, {"full": good, "baseline_no_memory": bad})
    assert checks["full"] == {"calls_checked": 1, "calls_failed": 0, "failures": []}
    failed = {(f["pattern"], f["turns"]) for f in checks["baseline_no_memory"]["failures"]}
    assert failed == {(PITCH, 3), (WRONG, 1)} and checks["baseline_no_memory"]["calls_failed"] == 1
    assert "1/1 calls over the limit" in report.team_table(checks)


def test_a_run_without_the_calls_is_reported_as_unchecked(tmp_path):
    folder = scenario(tmp_path)
    other = tmp_path / "full.jsonl"
    other.write_text(json.dumps({"scenario_id": "T", "call": "call_1", "turn": 1, "agent_text": "x"}) + "\n",
                     encoding="utf-8")
    checks = report.team_checks(folder, {"full": other, "baseline_no_memory": tmp_path / "missing.jsonl"})
    assert checks == {"full": None, "baseline_no_memory": None}
    assert "no call carries say_at_most" in report.team_table(checks)
