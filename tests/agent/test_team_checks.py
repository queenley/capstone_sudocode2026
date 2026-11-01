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


def test_rqr_as_a1_words_it_differs_from_the_organisers_only_by_repeated_confirmations(tmp_path):
    import importlib.util

    from ai_agent_service.config.config_manager import btc_data_dir

    spec = importlib.util.spec_from_file_location("reference_eval", btc_data_dir() / "eval" / "reference_eval.py")
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)

    folder = tmp_path / "scenarios"
    folder.mkdir()
    scenario = {"scenario_id": "S", "calls": {"call_2": {"must_not_ask": ["budget_vnd", "room_area_m2"]}}}
    (folder / "S.json").write_text(json.dumps(scenario), encoding="utf-8")
    asked = [{"slot": "budget_vnd", "type": "open"}, {"slot": "room_area_m2", "type": "confirm"},
             {"slot": "room_area_m2", "type": "confirm"}, {"slot": "payment", "type": "open"}]
    full = tmp_path / "full.jsonl"
    full.write_text("".join(json.dumps({"scenario_id": "S", "call": "call_2", "turn": i, "questions": [q]}) + "\n"
                            for i, q in enumerate(asked, 1)), encoding="utf-8")
    base = tmp_path / "baseline.jsonl"
    base.write_text(json.dumps({"scenario_id": "S", "call": "call_2", "turn": 1, "questions": [
        {"slot": "budget_vnd", "type": "open"}, {"slot": "room_area_m2", "type": "open"}]}) + "\n", encoding="utf-8")

    a1 = report.rqr_a1(folder, {"full": full, "baseline_no_memory": base})
    official = grader.repeat_question_rate({"S": scenario}, {("S", "call_2"): [json.loads(l) for l in full.read_text().splitlines()]})
    assert a1["full"] == {"value": 25.0, "redundant": 1, "total_questions": 4, "repeat_confirms": 1}
    assert official["redundant"] == a1["full"]["redundant"] + a1["full"]["repeat_confirms"]   # 2/4 = 50% for BTC
    assert a1["baseline_no_memory"]["value"] == 100.0 and a1["relative_reduction_pct"] == 75.0
    assert "75.0% (A.1)" in report.rqr_a1_table(a1, {"comparison": {"rqr_relative_reduction_pct": 50.0}})


def test_scenario_recall_reads_the_agents_searches_against_each_calls_relevant_policy_ids(tmp_path):
    folder = tmp_path / "scenarios"
    folder.mkdir()
    (folder / "S.json").write_text(json.dumps({"scenario_id": "S", "calls": {
        "call_1": {"relevant_policy_ids": ["VC-01", "VC-05"]}, "call_2": {"relevant_policy_ids": ["DT-01"]},
        "call_3": {"customer_turns": ["x"]}}}), encoding="utf-8")

    def turn(config, call, turn, chunks):
        return {"config": config, "scenario_id": "S", "call": call, "turn": turn,
                "knowledge": {"chunks": chunks} if chunks is not None else None}

    diagnostics = [turn("full", "call_1", 1, ["VC-01#2", "FAQ-03"]), turn("full", "call_1", 2, ["VC-05", "VC-01"]),
                   turn("full", "call_2", 1, ["BH-01"]), turn("full", "call_3", 1, ["VC-01"]),
                   turn("baseline_no_memory", "call_1", 1, None),
                   {"config": "baseline_no_memory", "scenario_id": "S", "call": "call_2", "turn": 1}]   # older run: no key
    result = report.scenario_recall(folder, diagnostics)
    full = result["full"]
    assert (full["calls"], full["recall"], full["full_recall"], full["coverage"]) == (2, 50.0, 50.0, 50.0)
    assert [r["missed"] for r in full["per_call"]] == [[], ["DT-01"]]
    assert full["per_call"][0]["retrieved"] == ["VC-01", "FAQ-03", "VC-05"]
    base = result["baseline_no_memory"]
    assert (base["calls"], base["recall"], base["calls_without_search"]) == (1, 0.0, 1)   # call_2 has no evidence
    assert report.scenario_recall(folder, [])["full"] is None
    assert "recall 50.0% · full_recall 50.0%" in report.scenario_recall_table(result)
