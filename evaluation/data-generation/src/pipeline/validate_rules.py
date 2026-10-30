"""Stage 6 — deterministic validation of reference transcripts with the OFFICIAL BTC script.

Each transcript is converted to BTC trace rows (tool calls re-executed on BTC
``mock_tools``) and scored by ``data/eval/reference_eval.py``. A gold transcript
must be perfect: RQR 0, CCR 100%, success_if pass, HR 0, no guardrail violation.
Extra consistency checks: identity fields, script adherence, tool calls rejected
by the mock, spoken amounts that are not grounded in the call's facts, and BTC's
schemas (``data/schemas``: every trace row against ``trace_log``, every tool call
against ``tools``).

Output: ``<seed>/reports/validation.json`` (one row per conversation).
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from src.ground_truth.traces import conversation_rows
from src.metrics.btc_metrics import money_mentions, score_call
from src.schemas.conversation import Conversation
from src.schemas.scenario import CallSpec, Scenario
from src.utils.btc_schemas import errors as schema_errors, tool_call_errors
from src.utils.btc_tools import fresh_mock_tools
from src.utils.dataset import Dataset
from src.utils.memory import known_facts_before, speaker_of
from src.utils.paths import OUTPUT_DIR, VALIDATION_JSON

# Personas/tags that always need a human look, even when every rule passes.
RISK_MARKERS = ("xoa_du_lieu", "chung_sdt", "shared_phone", "pii", "memory_poison", "bot_identity", "internal_doc",
                "privacy", "prompt_injection", "other_customer", "handoff")
SCRIPT_ADHERENCE_MIN = 0.6


def needs_review(scenario: Scenario) -> bool:
    haystack = " ".join([scenario.persona, *scenario.tags, scenario.hard_case or ""]).lower()
    return any(marker in haystack for marker in RISK_MARKERS)


def _norm(text: str) -> str:
    """Lowercase, NFC, punctuation-free, single-spaced — for verbatim script comparison."""
    text = unicodedata.normalize("NFC", text.lower())
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def trusted_money(call: CallSpec, known: dict[str, Any]) -> set[int]:
    """Every amount the agent may legitimately say in this call."""
    values: set[int] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 1000:
            values.add(int(value))

    for source in (call.ground_truth_facts, call.facts_established, call.success_if.model_dump(mode="json"),
                   call.oracle_tool_calls, known):
        collect(source)
    return values


def validate(scenario: Scenario, call_name: str, conversation: Conversation, mock=None) -> tuple[list[str], dict[str, Any]]:
    call = scenario.calls[call_name]
    spec = scenario.btc_export()["calls"][call_name]
    known = known_facts_before(scenario, call_name)
    errors: list[str] = []

    # -- identity -------------------------------------------------------------
    if conversation.category != scenario.category:
        errors.append("category_mismatch")
    if conversation.region != scenario.region:
        errors.append("region_mismatch")
    if conversation.customer_id != speaker_of(scenario, call_name):
        errors.append("customer_id_mismatch")
    if conversation.gold.outcome != call.expected_outcome:
        errors.append(f"gold_outcome_mismatch:{conversation.gold.outcome}!={call.expected_outcome}")

    # -- official metrics on the gold agent --------------------------------------
    rows = conversation_rows(conversation, mock if mock is not None else fresh_mock_tools())
    score = score_call(scenario.scenario_id, call_name, spec, rows, scenario.hard_case)
    errors += score.failures
    for row in rows:
        for tc in row["tool_calls"]:
            if isinstance(tc["result"], dict) and tc["result"].get("error"):
                errors.append(f"tool_rejected_by_mock:{tc['name']}:{tc['result']['error']}")
            errors += [f"schema:tools:{e}" for e in tool_call_errors(tc["name"], tc["args"])]
        errors += [f"schema:trace_log:turn {row['turn']}:{e}" for e in schema_errors("trace_log", row)]

    # -- the customer must speak the scenario outline ------------------------------
    script = call.customer_turns_asr if call.input_mode != "text" and call.customer_turns_asr else call.customer_turns
    spoken = [_norm(turn.text) for turn in conversation.customer_turns()]
    followed = sum(1 for line in script if any(_norm(line) == said for said in spoken))
    if script and followed / len(script) < SCRIPT_ADHERENCE_MIN:
        errors.append(f"customer_script_not_followed:{followed}/{len(script)}")

    # -- every spoken amount must be grounded --------------------------------------
    accepted = trusted_money(call, known)
    for turn in conversation.agent_turns():
        for amount in money_mentions(turn.text):
            if amount >= 10_000 and amount not in accepted:
                errors.append(f"unverified_spoken_price:{amount}")

    metrics = {"tsr": score.tsr, "rqr": score.rqr, "ccr": score.ccr, "hr": score.hr, "guardrails": score.guardrails}
    return sorted(set(errors)), metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=OUTPUT_DIR, help="dataset root (src/utils/dataset.py)")
    parser.add_argument("--output", type=Path, default=VALIDATION_JSON)
    args = parser.parse_args()

    dataset = Dataset(args.root)
    mocks: dict[str, Any] = {}
    rows = []
    for conversation in dataset.iter_conversations():
        scenario_id, call_name = conversation.scenario_id, conversation.call
        scenario = dataset.scenario(scenario_id)
        if scenario is None or call_name not in scenario.calls:
            continue
        if scenario_id not in mocks:
            mocks[scenario_id] = fresh_mock_tools()   # calls of one scenario share runtime state (order ids)
        errors, metrics = validate(scenario, call_name, conversation, mocks[scenario_id])
        rows.append({"scenario_id": scenario_id, "call": call_name, "conversation_id": conversation.conversation_id,
                     "hard_case": scenario.hard_case, "validator_pass": not errors, "errors": errors,
                     "metrics": metrics, "needs_manual_review": bool(errors) or needs_review(scenario)})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(row["validator_pass"] for row in rows)
    print(f"Validated {len(rows)} transcripts; {passed} passed all rules -> {args.output}")


if __name__ == "__main__":
    main()
