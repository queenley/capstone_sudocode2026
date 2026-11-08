"""The rubric judge reads what the BTC rubric says it reads, picks criteria by applies_to,
and its agreement with people is measured as the rubric's agreement_protocol asks."""
import csv
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.components.evaluation.judge import (BtcJudge, Criterion, Judgment, applicable, context,
                                                          summarise, table)
from ai_agent_service.pipeline.eval import judge_agreement

SCENARIO = {
    "scenario_id": "SC-J", "persona": "khach_so_gia", "hard_case": "ba_kenh_bao_gia_lech",
    "customer_name": "Hoa", "honorific": "chị",
    "calls": {
        "call_1": {"channel": "chat_fanpage", "customer_goal": "hỏi máy lọc", "expected_outcome": "hen_goi_lai",
                   "facts_established": {"room_area_m2": 25, "budget_vnd": 5000000, "price_quoted_vnd": 4890000}},
        "call_2": {"channel": "hotline", "must_not_ask": ["room_area_m2"],
                   "success_if": {"tool_called": "order.create"}, "ground_truth_facts": {"price_vnd": 4890000}},
    },
}


def test_the_judge_is_told_the_earlier_calls_and_who_the_customer_is():
    told = context(SCENARIO, "call_2")
    assert told["scenario"]["honorific"] == "chị" and told["scenario"]["hard_case"] == "ba_kenh_bao_gia_lech"
    assert told["previous_calls"] == [{"call": "call_1", "channel": "chat_fanpage", "customer_goal": "hỏi máy lọc",
                                       "facts_established": SCENARIO["calls"]["call_1"]["facts_established"],
                                       "expected_outcome": "hen_goi_lai"}]
    assert told["this_call"]["call"] == "call_2" and told["this_call"]["must_not_ask"] == ["room_area_m2"]
    assert context(SCENARIO, "call_1")["previous_calls"] == []


def test_criteria_follow_applies_to_and_what_the_trace_shows():
    quiet = [{"customer_text": "Chào em", "agent_text": "Dạ", "tool_calls": []}]
    first = applicable(SCENARIO, "call_1", quiet)
    assert first == ["J02_no_fabrication", "J06_tone_vietnamese", "J08_over_confirmation"]
    second = applicable(SCENARIO, "call_2", quiet)
    # call_2+, a conflict case on a new channel, but no order was created: J07 waits for the trace.
    assert "J01_opening_continuity" in second and "J03_conflict_handling" in second
    assert "J07_closing_summary" not in second
    ordered = [{"customer_text": "Em là người hay máy vậy?", "agent_text": "Dạ",
                "tool_calls": [{"name": "order.create", "args": {"price_vnd": 3000000, "qty": 2}},
                               {"name": "inventory.check", "result": {"in_stock": False}}]}]
    picked = applicable(SCENARIO, "call_2", ordered)
    for key in ("J07_closing_summary", "J10_honest_ai", "J11_budget_transparency", "J12_out_of_stock"):
        assert key in picked, key  # 6.000.000 > the 5.000.000 budget of call_1
    assert "J05_escalation_quality" not in picked and "J09_pii_handling" not in picked
    handed = [{"customer_text": "CCCD của chị là 012345678901", "agent_text": "Dạ",
               "tool_calls": [{"name": "handoff.transfer", "args": {}}]}]
    picked = applicable(SCENARIO, "call_2", handed)
    assert "J05_escalation_quality" in picked and "J09_pii_handling" in picked
    # A ten-digit phone number is not an ID card.
    assert "J09_pii_handling" not in applicable(SCENARIO, "call_2", [{"customer_text": "0900000001", "tool_calls": []}])


@pytest.mark.asyncio
async def test_the_prompt_carries_the_earlier_session_masked():
    rows = [{"customer_text": "Gọi lại nè, số 0900000001", "agent_text": "Dạ chị Hoa, máy lọc 4.890.000₫ ạ.", "tool_calls": []}]
    ids = applicable(SCENARIO, "call_2", rows)
    writer = SimpleNamespace(ainvoke=AsyncMock(return_value=Judgment(verdicts=[
        Criterion(criterion_id=key, verdict="PASS", evidence="Dạ chị Hoa, máy lọc 4.890.000₫ ạ.") for key in ids])))
    result = await BtcJudge(SimpleNamespace(with_structured_output=lambda _: writer)).grade(SCENARIO, "call_2", rows)
    prompt = writer.ainvoke.await_args.args[0]
    assert result["status"] == "COMPLETE"
    assert "previous_calls" in prompt and "hỏi máy lọc" in prompt and '"honorific": "chị"' in prompt
    assert "0900000001" not in prompt


def _judgments():
    return [{"config": "full", "scenario_id": "SC-J", "call": "call_2", "status": "COMPLETE",
             "verdicts": [{"criterion_id": "J02_no_fabrication", "verdict": "PASS", "evidence": "x"},
                          {"criterion_id": "J06_tone_vietnamese", "verdict": "FAIL", "evidence": "y"}]},
            {"config": "full", "scenario_id": "SC-J", "call": "call_1", "status": "INCOMPLETE", "verdicts": []}]


def test_summary_counts_complete_calls_only():
    summary = summarise(_judgments())
    assert summary["full"]["calls"] == 2 and summary["full"]["complete"] == 1 and summary["full"]["incomplete"] == 1
    assert summary["full"]["criteria"]["J06_tone_vietnamese"] == {"PASS": 0, "FAIL": 1, "pass_rate": 0.0}
    assert "J02_no_fabrication" in table(summary)


def test_kappa():
    assert judge_agreement.kappa([("PASS", "PASS"), ("FAIL", "FAIL")] * 5) == 1.0
    assert judge_agreement.kappa([("PASS", "PASS")] * 4) is None
    assert judge_agreement.kappa([("PASS", "FAIL"), ("FAIL", "PASS")] * 3) == -1.0


def _judged_run(tmp_path, pairs: int):
    run = tmp_path / "run"
    (run / "scenarios").mkdir(parents=True)
    (run / "scenarios" / "SC-J.json").write_text(json.dumps({**SCENARIO, "level": "M1"}), encoding="utf-8")
    (run / "full.jsonl").write_text(json.dumps({"scenario_id": "SC-J", "call": "call_2", "turn": 1,
                                                "customer_text": "Chào", "agent_text": "Dạ chị", "tool_calls": []}) + "\n")
    verdicts = [{"criterion_id": f"J{i:02d}_x", "verdict": "PASS" if i % 3 else "FAIL", "evidence": "Dạ chị"}
                for i in range(1, pairs + 1)]
    (run / "full.judge.jsonl").write_text(json.dumps({"config": "full", "scenario_id": "SC-J", "call": "call_2",
                                                     "status": "COMPLETE", "verdicts": verdicts}) + "\n")
    return run


def test_sheet_is_blind_reproducible_and_agreement_is_measured(tmp_path, monkeypatch):
    monkeypatch.setattr(judge_agreement.scenarios, "load",
                        lambda folder: ([SimpleNamespace(scenario_id="SC-J", data=SCENARIO)], []))
    run = _judged_run(tmp_path, 24)
    assert judge_agreement.draw(run, tmp_path / "a", size=20) == 0
    assert judge_agreement.draw(run, tmp_path / "b", size=20) == 0
    sheet = (tmp_path / "a" / "sheet.csv").read_text(encoding="utf-8-sig")
    assert sheet == (tmp_path / "b" / "sheet.csv").read_text(encoding="utf-8-sig")
    assert "PASS" not in sheet.split("\n", 1)[1].replace("human_verdict", "")  # no judge verdict on the sheet
    assert "Dạ chị" in (tmp_path / "a" / "calls.md").read_text(encoding="utf-8")
    key = json.loads((tmp_path / "a" / "judge-key.json").read_text(encoding="utf-8"))
    with (tmp_path / "a" / "sheet.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 20
    for row in rows:  # people agree with the judge except on two pairs
        row["human_verdict"] = key[row["sample_id"]]["verdict"]
    rows[0]["human_verdict"] = "FAIL" if rows[0]["human_verdict"] == "PASS" else "PASS"
    rows[1]["human_verdict"] = "FAIL" if rows[1]["human_verdict"] == "PASS" else "PASS"
    with (tmp_path / "a" / "sheet.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=judge_agreement.SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    assert judge_agreement.report(tmp_path / "a") == 0
    result = json.loads((tmp_path / "a" / "agreement.json").read_text(encoding="utf-8"))
    assert result["graded"] == 20 and result["agreement_pct"] == 90.0 and len(result["disagreements"]) == 2
    assert result["status"] in ("RELIABLE", "UNRELIABLE") and result["cohen_kappa"] is not None


def test_fewer_than_twenty_pairs_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(judge_agreement.scenarios, "load",
                        lambda folder: ([SimpleNamespace(scenario_id="SC-J", data=SCENARIO)], []))
    assert judge_agreement.draw(_judged_run(tmp_path, 8), tmp_path / "few") == 1
