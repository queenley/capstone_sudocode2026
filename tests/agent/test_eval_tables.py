"""``run_eval.py --report``: the report's tables from finished runs, no model and no database."""

import json

import pytest

from ai_agent_service.pipeline.eval import cli, tables


def write_run(directory, knowledge="kb0", scenarios="set-a"):
    directory.mkdir()
    rate = {"value": 50.0}
    section = {"repeat_question_rate": rate, "context_carryover_rate": rate, "task_success_rate": {"value": 75.0},
               "hallucination_rate": {"value": 9.0, "price_promo_only": {"value": 2.0}}}
    (directory / "report.json").write_text(json.dumps({"system": section, "baseline": {
        **section, "task_success_rate": {"value": 25.0}}}), encoding="utf-8")
    (directory / "manifest.json").write_text(json.dumps({
        "knowledge_sha256": knowledge, "scenarios": scenarios, "models": {"advisor": {"model": "gpt-4.1-mini"}}}), encoding="utf-8")
    row = {"scenario_id": "S", "call": "call_1", "turn": 1, "input_mode": "text", "call_brief_latency_ms": 50,
           "latency": {"ttft_ms": 1000, "total_ms": 2000, "ttfa_ms": None}}
    (directory / "full.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return directory


def test_all_means_every_section_and_a_choice_keeps_the_report_order():
    assert tables.sections("all") == ("asr", "agent", "performance")
    assert tables.sections("performance,agent") == ("agent", "performance")
    with pytest.raises(ValueError):
        tables.sections("speed")


def test_a_run_is_named_for_a_column_the_report_has():
    assert tables.named_run("router=runs/x")[0] == "router"
    with pytest.raises(ValueError):
        tables.named_run("gemini=runs/x")


def test_the_baseline_column_is_the_routers_own_baseline_and_hr_is_the_organisers_figure(tmp_path):
    text = tables.agent_table({"router": write_run(tmp_path / "r")})
    lines = text.splitlines()
    assert "| 3. Task Success Rate (TSR) | 25% | 75% | chưa có | chưa đo | chưa đo | chưa có |" in lines
    assert "| 4. Hallucination Rate (HR) | 2% | 2% | chưa có | chưa đo | chưa đo | chưa có |" in lines


def test_a_column_with_the_routers_knowledge_is_called_a_rerun(tmp_path):
    runs = {"router": write_run(tmp_path / "r"), "gaploop": write_run(tmp_path / "g")}
    assert any("chỉ là chạy lại Router" in note for note in tables.notes(runs))
    runs["gaploop"] = write_run(tmp_path / "g2", knowledge="kb1", scenarios="set-b")
    found = tables.notes(runs)
    assert not any("chỉ là chạy lại Router" in note for note in found)
    assert any("khác bộ kịch bản" in note for note in found)


def test_report_warns_when_a_column_label_does_not_match_its_profile(tmp_path):
    router = write_run(tmp_path / "r")
    gap = write_run(tmp_path / "g", knowledge="kb1")
    manifest = json.loads((gap / "manifest.json").read_text(encoding="utf-8"))
    manifest["evaluation"] = {"profile": "router"}
    (gap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert any("nhãn cột là gaploop" in note for note in tables.notes({"router": router, "gaploop": gap}))


def test_parser_exposes_reproducible_evaluation_profiles():
    gap = cli.parser().parse_args(["--profile", "gaploop", "--kb-version", "2"])
    reflection = cli.parser().parse_args(["--profile", "reflection", "--skills-version", "0"])
    assert (gap.profile, gap.kb_version) == ("gaploop", 2)
    assert (reflection.profile, reflection.skills_version) == ("reflection", 0)


def test_asr_scores_come_from_the_organisers_scorer_and_an_unrun_one_says_so(tmp_path):
    assert "| 1. WER (Word Error Rate) | chưa đo |" in tables.asr_table(None)
    (tmp_path / "report.json").write_text(json.dumps({"main_scorer": {
        "raw": {"WER": 12.5, "CER": 6.0, "entity_accuracy": 90}, "agent_input": {"status": "unavailable"}}}), encoding="utf-8")
    assert "| 3. Entity Accuracy | 90% | chưa đo |" in tables.asr_table(tmp_path)


def test_the_command_chooses_a_section_and_writes_no_model_call(tmp_path, capsys):
    run = write_run(tmp_path / "r")
    assert cli.main(["--report", "agent", "--run", f"router={run}"]) == 0
    out = capsys.readouterr().out
    assert "Phần Agent" in out and "Phần ASR" not in out


def test_report_alone_will_not_start_a_paid_run_on_the_default_scenarios(capsys):
    assert cli.main(["--report"]) == 2


def test_a_knowledge_version_that_does_not_exist_is_refused(capsys):
    assert cli.main(["--kb-version", "999", "--only", "S"]) == 2
