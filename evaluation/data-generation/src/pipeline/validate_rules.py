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
from functools import lru_cache
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
from src.planning.planner import COD_CONFIRMATION_PHRASES
from src.utils.paths import CATALOG_DIR, OUTPUT_DIR, POLICY_DIR, VALIDATION_JSON
from src.utils.policy import load_customer_policy

# Personas/tags that always need a human look, even when every rule passes.
RISK_MARKERS = ("xoa_du_lieu", "chung_sdt", "shared_phone", "pii", "memory_poison", "bot_identity", "internal_doc",
                "privacy", "prompt_injection", "other_customer", "handoff")
SCRIPT_ADHERENCE_MIN = 0.6
#: The customer calls or messages the shop in every scenario: "em gọi lại về…" in the first agent turn reads PB-01's
#: "khách gọi lại" (a returning customer) as the shop calling.
OUTBOUND_OPENING = re.compile(r"\bem (?:gọi lại|gọi điện|gọi) (?:về|cho|để)", re.I)


def closing_courtesy(text: str) -> bool:
    """rules.md: a turn never ends with a generic "anything else?" question (help/need + gì + thêm/nữa/khác + "?").
    An opening "em có thể hỗ trợ gì cho mình ạ?" and a concrete offer ("chị muốn em giới thiệu qua không ạ?") are not."""
    last = re.split(r"(?<=[.!?])\s+", text.strip())[-1].lower()
    return (last.endswith("?") and bool(re.search(r"hỗ trợ|giúp|cần", last)) and bool(re.search(r"\bgì\b", last))
            and bool(re.search(r"\b(?:thêm|nữa|khác)\b", last)))


def needs_review(scenario: Scenario) -> bool:
    haystack = " ".join([scenario.persona, *scenario.tags, scenario.hard_case or ""]).lower()
    return any(marker in haystack for marker in RISK_MARKERS)


def _norm(text: str) -> str:
    """Lowercase, NFC, punctuation-free, single-spaced — for verbatim script comparison."""
    text = unicodedata.normalize("NFC", text.lower())
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


@lru_cache(maxsize=1)
def published_money() -> frozenset[int]:
    """Amounts the shop publishes: the customer-facing policies (the 2.000.000đ confirmation call, the 10.000.000đ
    COD limit, the 35.000đ fee) and the promotions' discounts and minimum orders. Internal notes are left out, so an
    import price or a price floor said aloud is still caught."""
    found = {amount for text in load_customer_policy(POLICY_DIR).values() for amount in money_mentions(text)}
    promotions = json.loads((CATALOG_DIR / "promotions.json").read_text(encoding="utf-8"))["promotions"]
    found |= {int(p[key]) for p in promotions for key in ("discount_vnd", "min_order_vnd") if p.get(key)}
    return frozenset(found)


def trusted_money(call: CallSpec, known: dict[str, Any], customer_said: set[int] = frozenset()) -> set[int]:
    """Every amount the agent may legitimately say in this call: its facts and tool results, what the shop
    publishes, and what the customer said in it ("ngân sách 4 triệu rưỡi của chị")."""
    values: set[int] = set(published_money()) | set(customer_said)

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

    # -- the agent's own rules (config/prompts/agent/advisor/rules.md) ----------------
    agent_turns = conversation.agent_turns()
    if agent_turns and OUTBOUND_OPENING.search(agent_turns[0].text):
        errors.append("outbound_opening:the customer contacted the shop; the agent answers, it did not call")
    for turn in agent_turns:
        if closing_courtesy(turn.text):
            errors.append(f"closing_courtesy_question:{turn.text.strip()[-60:]}")
    # VC-05: the confirmation call is said whenever the order needs it, even where must_say_any holds another phrase.
    if call.ground_truth_facts.get("needs_confirmation_call"):
        said = " ".join(turn.text for turn in agent_turns).lower()
        if not any(phrase in said for phrase in COD_CONFIRMATION_PHRASES):
            errors.append("missing_cod_confirmation_call:say that a staff member will call to confirm before delivery")
    # The team's say_at_most, as the harness counts it (report.team_checks): agent turns matching the pattern.
    for limit in call.success_if.say_at_most:
        turns = sum(1 for turn in agent_turns if re.search(limit.pattern, turn.text))
        if turns > limit.max:
            errors.append(f"say_at_most:{turns}>{limit.max}:{limit.pattern[:40]}")

    # -- every spoken amount must be grounded --------------------------------------
    accepted = trusted_money(call, known, {a for turn in conversation.customer_turns() for a in money_mentions(turn.text)})
    # The call's own amounts by name tell the next attempt what each figure is, which "say only grounded amounts"
    # did not ("ngân sách 4 triệu" for a customer's "bốn triệu rưỡi", three attempts in a row).
    named = {key: value for source in (known, call.facts_established, call.ground_truth_facts)
             for key, value in source.items()
             if isinstance(value, int) and not isinstance(value, bool) and value >= 10_000}
    hint = ", ".join(f"{key} {value}" for key, value in list(named.items())[:8])
    for turn in conversation.agent_turns():
        for amount in money_mentions(turn.text):
            if amount >= 10_000 and amount not in accepted:
                errors.append(f"unverified_spoken_price:{amount}" + (f" (this call's amounts: {hint})" if hint else ""))

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
