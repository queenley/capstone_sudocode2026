"""Stage 7 — LLM-as-a-judge with the OFFICIAL BTC rubric (``data/eval/llm_judge_rubric.json``).

For every reference transcript (one call) the applicable criteria J01–J12 are
selected deterministically from the scenario (``applies_to`` of each criterion),
the BTC ``judge_prompt_template`` is filled with the scenario JSON, the agent
transcript and those criteria, and the model returns PASS/FAIL + one evidence
quote per criterion. Rule failures from ``validate_rules`` always force manual review.

Output: ``output/judgments/<conversation_id>.json``. Human agreement (Cohen's kappa,
≥ 20 samples) is measured with ``python -m src.pipeline.judge_agreement``.
"""
from __future__ import annotations

import argparse
import json

from src.pipeline.validate_rules import needs_review
from src.schemas.conversation import AgentTurn, Conversation, split_conversation_id
from src.schemas.review import JudgeOutput, JudgeVerdict
from src.schemas.scenario import Scenario
from src.utils.io import iter_models, load_model, write_json
from src.utils.memory import known_facts_before
from src.utils.paths import CONVERSATIONS_DIR, DATA_DIR, JUDGMENTS_DIR, SCENARIOS_INTERNAL_DIR, VALIDATION_JSON
from src.utils.settings import load_settings, model_client, sampling
from src.utils.quota import DailyLimitReached, stop_on_daily_limit

RUBRIC = json.loads((DATA_DIR / "eval" / "llm_judge_rubric.json").read_text(encoding="utf-8"))
CONFLICT_CASES = {"ba_kenh_bao_gia_lech", "doi_khuyen_mai_het_han", "ba_phien_doi_thong_tin", "phien_ban_chinh_sach_cu"}


def applicable_criteria(scenario: Scenario, call_name: str) -> list[str]:
    """Map each rubric ``applies_to`` to a deterministic condition on the call."""
    call = scenario.calls[call_name]
    gt, si = call.ground_truth_facts, call.success_if
    pii = any(p.isdigit() and len(p) >= 9 for p in si.trace_must_not_match)
    rules = {
        "J01_opening_continuity": call_name != "call_1" and bool(call.must_carry_over),
        "J02_no_fabrication": True,
        "J03_conflict_handling": scenario.hard_case in CONFLICT_CASES or "superseded" in call.memory_expectation
        or any(getattr(f, "field", "") == "price_vnd" for f in si.forbidden_claims),
        "J04_identity_check": "must_not_write_to" in call.memory_expectation,
        "J05_escalation_quality": call.expected_outcome == "chuyen_may",
        "J06_tone_vietnamese": True,
        "J07_closing_summary": si.tool_called == "order.create",
        "J08_over_confirmation": True,
        "J09_pii_handling": pii,
        "J10_honest_ai": "is_human" in gt,
        "J11_budget_transparency": gt.get("cod_allowed") is False or bool(si.also_ordered),
        "J12_out_of_stock": gt.get("in_stock") is False,
    }
    return [c["id"] for c in RUBRIC["criteria"] if rules.get(c["id"], False)]


def transcript_text(conversation: Conversation) -> str:
    lines = []
    for turn in conversation.turns:
        item = turn.root
        who = "Agent" if isinstance(item, AgentTurn) else "Khách"
        lines.append(f"{who}: {item.text}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="max conversations to judge")
    parser.add_argument("--resume", action="store_true", help="skip conversations already judged")
    args = parser.parse_args()

    settings = load_settings()
    client = model_client("judge", settings)
    params = sampling(settings)
    rules = {row["conversation_id"]: row for row in json.loads(VALIDATION_JSON.read_text(encoding="utf-8"))
             if "conversation_id" in row} if VALIDATION_JSON.exists() else {}
    criteria_by_id = {c["id"]: c for c in RUBRIC["criteria"]}

    judged = 0
    skipped: list[str] = []
    paths = sorted(CONVERSATIONS_DIR.glob("*__call_*.json"))[:args.limit]
    for _, conversation in iter_models(paths, Conversation):
        cid = conversation.conversation_id
        dest = JUDGMENTS_DIR / f"{cid}.json"
        if args.resume and dest.exists():
            continue
        scenario_id, call_name = split_conversation_id(cid)
        scenario_path = SCENARIOS_INTERNAL_DIR / f"{scenario_id}.json"
        if not scenario_path.exists():
            continue
        scenario = load_model(scenario_path, Scenario)
        applied = applicable_criteria(scenario, call_name)
        scenario_json = {"customer_goal": scenario.calls[call_name].customer_goal,
                         "facts_from_previous_sessions": known_facts_before(scenario, call_name),
                         **scenario.btc_export()["calls"][call_name]}
        prompt = RUBRIC["judge_prompt_template"].format(
            scenario_json=json.dumps(scenario_json, ensure_ascii=False),
            transcript=transcript_text(conversation),
            criteria=json.dumps([criteria_by_id[c] for c in applied], ensure_ascii=False))
        prompt += "\n\nTrả về JSON {\"verdicts\": [ ... một phần tử cho MỖI tiêu chí ở trên ... ]}."
        try:
            output = client.generate(prompt, JudgeOutput, temperature=params["judge_temperature"], max_output_tokens=2048)
        except DailyLimitReached:
            raise
        except RuntimeError as error:
            # One verdict the model cannot produce must not stop the others; --resume retries it.
            print(f"  SKIPPED {cid}: {error}", flush=True)
            skipped.append(cid)
            continue
        verdicts = [v for v in output.verdicts if v.criterion_id in applied]
        missing = sorted(set(applied) - {v.criterion_id for v in verdicts})
        failed = [v.criterion_id for v in verdicts if v.verdict == "FAIL"]
        rule_failed = bool(rules.get(cid, {}).get("errors"))
        write_json(dest, JudgeVerdict(
            scenario_id=scenario_id, conversation_id=cid, criteria_applied=applied, verdicts=verdicts,
            overall_pass=not failed and not missing and not rule_failed,
            needs_manual_review=bool(failed or missing or rule_failed or needs_review(scenario)),
            reasons="; ".join([*(f"FAIL {c}" for c in failed), *(f"missing {c}" for c in missing),
                               *(["rule failures"] if rule_failed else [])])))
        judged += 1
    print(f"Judged {judged} conversations -> {JUDGMENTS_DIR}")
    if skipped:
        print(f"{len(skipped)} conversation(s) not judged ({', '.join(skipped)}); rerun with --resume.", flush=True)


if __name__ == "__main__":
    stop_on_daily_limit(main)()
