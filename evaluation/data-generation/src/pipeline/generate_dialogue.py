"""Stage 4 — generate one reference transcript per scenario call.

Output: ``output/conversations/scenarios_<scenario_id>/<call>.json``. The transcript is
the gold behaviour for that call; ``validate_rules`` scores it with the same
metric code as the agent under test and rejects anything below a perfect score.

Each draft is checked right away with that same validation (the scenario's
earlier transcripts replayed on a fresh BTC mock first, so their order ids
exist). A draft with errors is asked for again with the errors, up to
``MAX_ATTEMPTS`` times; the draft with the fewest errors is kept.

Usage::

    python -m src.pipeline.generate_dialogue --limit 48 [--resume] [--calls call_2,call_3]
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from src.ground_truth.traces import conversation_rows
from src.pipeline.validate_rules import validate
from src.planning.persona_config import load_profiles
from src.schemas.conversation import Conversation, ConversationDraft, conversation_id
from src.schemas.scenario import Scenario
from src.utils.btc_tools import fresh_mock_tools
from src.utils.crm import load_customers
from src.utils.dataset import Dataset
from src.utils.io import load_model, write_json
from src.utils.memory import known_facts_before, speaker_of, stale_slots_before
from src.utils.paths import POLICY_DIR, PROMPTS_DIR, REPORTS_DIR
from src.utils.pii import redact_contacts
from src.utils.policy import load_customer_policy
from src.utils.quota import DailyLimitReached, stop_on_daily_limit
from src.utils.settings import load_settings, model_client, sampling

MAX_ATTEMPTS = 3
#: How to fix each kind of validation error, said after the errors themselves.
FIXES = {
    "customer_script_not_followed": "copy every customer_script line as one customer turn, verbatim and in order",
    "ccr_missing": "list every slot of call.must_carry_over in the first agent turn's facts_used",
    "redundant_question": "do not ask about that slot again: it is known (memory) or was already confirmed once",
    "unverified_spoken_price": "say only amounts that are in ground_truth_facts, agent_will_tell or the tool results",
    "tsr": "satisfy call.success_if exactly: the tool with args_match, one of required_phrases word for word",
    "hr": "claim only keys and values of ground_truth_facts; never a forbidden claim",
    "tool_rejected_by_mock": "copy tool calls and their args from call.oracle_tool_calls",
    "schema": "follow BTC's schemas: tool names and required args of tools.schema.json, question/claim fields",
}
#: Retries are about following the script and the checks, not creativity.
RETRY_TEMPERATURE = 0.3


def customer_script(scenario: Scenario, call_name: str) -> list[str]:
    """The customer lines the transcript must contain, as the system receives them (BTC: the ASR version if any)."""
    call = scenario.calls[call_name]
    return call.customer_turns_asr if call.input_mode != "text" and call.customer_turns_asr else call.customer_turns


def build_context(scenario: Scenario, call_name: str, customer, persona_style: str, policies: dict) -> dict:
    call = scenario.calls[call_name]
    call_payload = call.model_dump(mode="json", exclude={"simulator_persona_key", "patience_start", "speaker_customer_id",
                                                         "customer_turns", "customer_turns_asr", "agent_will_tell"})
    return {
        "scenario_id": scenario.scenario_id,
        "call_name": call_name,
        # The two things most often got wrong, apart from the rest: the lines the customer says, verbatim, in order,
        # and the phrases the agent must say (one of them, character for character).
        "customer_script": {str(i): line for i, line in enumerate(customer_script(scenario, call_name), start=1)},
        "required_phrases": {"say_exactly_one_of": call.success_if.must_say_any,
                             "say_abstain_phrase": bool(call.success_if.agent_must_say)},
        "agent_will_tell": call.agent_will_tell,
        "call": call_payload,
        "memory": known_facts_before(scenario, call_name),
        "stale_slots": stale_slots_before(scenario, call_name),
        "customer": redact_contacts(customer.model_dump(mode="json", include={"name", "honorific", "region"}))
        if customer else {"honorific": scenario.honorific, "region": scenario.region},
        "shared_phone_note": "Another person uses this phone number; confirm identity once and never mention them."
        if call.speaker_customer_id or (customer and customer.shared_phone_with) else None,
        "customer_known_to_shop": customer is not None,
        "persona_style": persona_style,
        "policy_documents": policies,
    }


def feedback(errors: list[str], script: list[str]) -> str:
    """What to fix, for the next attempt: the validator's errors, and the script once more when it was not followed."""
    lines = ["", "", "YOUR PREVIOUS TRANSCRIPT WAS REJECTED by the official check. Fix exactly these problems:",
             *(f"- {e}" for e in errors), "How to fix them:"]
    kinds = dict.fromkeys(e.split(":")[0] for e in errors)
    lines += [f"- {FIXES[kind]}" for kind in kinds if kind in FIXES]
    if any(e.startswith("customer_script_not_followed") for e in errors):
        lines += ["The transcript must contain each of these lines as one `customer` turn, character for character, "
                  "in this order, with the agent's turns between them:",
                  *(f"{i}. {line}" for i, line in enumerate(script, start=1))]
    return "\n".join(lines)


class Writer:
    """One scenario call's transcript: drafted, checked, asked again with the errors."""

    def __init__(self, client, template: str, params: dict[str, Any], dataset: Dataset) -> None:
        self.client, self.template, self.params, self.dataset = client, template, params, dataset

    def _checked(self, scenario: Scenario, call_name: str, conversation: Conversation) -> list[str]:
        mock = fresh_mock_tools()
        for earlier, _ in scenario.ordered_calls():   # replay what came before, so its orders exist on the mock
            if earlier == call_name:
                break
            path = self.dataset.conversation_path(scenario.scenario_id, earlier)
            if path.exists():
                conversation_rows(load_model(path, Conversation), mock)
        return validate(scenario, call_name, conversation, mock)[0]

    def write(self, scenario: Scenario, call_name: str, session_index: int, context: dict) -> tuple[Conversation, list[str]]:
        call = scenario.calls[call_name]
        script = customer_script(scenario, call_name)
        prompt = f"{self.template}\n\nCALL JSON (trusted):\n{json.dumps(context, ensure_ascii=False)}"
        temperature, extra = self.params["temperature"], ""
        best: tuple[Conversation, list[str]] | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            draft = self.client.generate(prompt + extra, ConversationDraft, temperature=temperature,
                                         max_output_tokens=self.params["max_output_tokens"])
            # Identity fields are owned by the pipeline, never by the model.
            conversation = Conversation(
                conversation_id=conversation_id(scenario.scenario_id, call_name), scenario_id=scenario.scenario_id,
                call=call_name, customer_id=speaker_of(scenario, call_name), session_index=session_index,
                channel=call.channel, date=call.call_date, region=scenario.region, category=scenario.category,
                persona=scenario.persona, turns=draft.turns, gold=draft.gold)
            errors = self._checked(scenario, call_name, conversation)
            if best is None or len(errors) < len(best[1]):
                best = (conversation, errors)
            if not errors:
                break
            print(f"  {conversation.conversation_id} attempt {attempt} rejected: {errors[:4]}", flush=True)
            extra, temperature = feedback(errors, script), min(temperature, RETRY_TEMPERATURE)
        return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="max scenarios to process")
    parser.add_argument("--resume", action="store_true", help="skip conversations already on disk")
    parser.add_argument("--calls", default="", help="comma-separated subset, e.g. call_2,call_3 (default: all)")
    args = parser.parse_args()
    wanted = {c.strip() for c in args.calls.split(",") if c.strip()}

    settings = load_settings()
    template = (PROMPTS_DIR / "dialogue_full_call.jinja").read_text(encoding="utf-8")
    customers = {c.customer_id: c for c in load_customers()}
    styles = {pid: p.get("style", "") for pid, p in load_profiles().items()}
    policies = load_customer_policy(POLICY_DIR)
    dataset = Dataset()
    writer = Writer(model_client("dialogue", settings), template, sampling(settings), dataset)

    written, still_rejected = 0, 0
    failures: list[dict] = []
    for scenario in dataset.iter_scenarios(args.limit):
        for session_index, (call_name, _) in enumerate(scenario.ordered_calls(), start=1):
            if wanted and call_name not in wanted:
                continue
            cid = conversation_id(scenario.scenario_id, call_name)
            dest = dataset.conversation_path(scenario.scenario_id, call_name)
            if args.resume and dest.exists():
                try:
                    load_model(dest, Conversation)
                    continue
                except ValueError:
                    pass  # old schema: regenerate
            customer = customers.get(speaker_of(scenario, call_name))
            context = build_context(scenario, call_name, customer, styles.get(scenario.persona, ""), policies)
            try:
                conversation, errors = writer.write(scenario, call_name, session_index, context)
            except DailyLimitReached:
                raise
            except RuntimeError as error:
                # One transcript the model cannot get right must not stop the other calls.
                print(f"  SKIPPED {cid}: {error}", flush=True)
                failures.append({"conversation_id": cid, "error": str(error)})
                continue
            write_json(dest, conversation)
            written += 1
            still_rejected += bool(errors)
            print(f"Wrote {cid}" + (f" ({len(errors)} errors left after {MAX_ATTEMPTS} attempts)" if errors else ""),
                  flush=True)
    print(f"Generated {written} reference transcripts; {still_rejected} still fail validation "
          "(rerun with run_all --only-failed)")
    write_json(REPORTS_DIR / "dialogue_failures.json", {"failed": failures})
    if failures:
        print(f"{len(failures)} transcript(s) skipped ({', '.join(f['conversation_id'] for f in failures)}); "
              "rerun with --resume to retry only those.", flush=True)


if __name__ == "__main__":
    stop_on_daily_limit(main)()
