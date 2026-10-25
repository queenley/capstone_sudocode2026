"""Stage 4 — generate one reference transcript per scenario call.

Output: ``output/conversations/<scenario_id>__<call>.json``. The transcript is
the gold behaviour for that call; ``validate_rules`` scores it with the same
metric code as the agent under test and rejects anything below a perfect score.

Usage::

    python -m src.pipeline.generate_dialogue --limit 48 [--resume] [--calls call_2,call_3]
"""
from __future__ import annotations

import argparse
import json

from src.schemas.conversation import Conversation, ConversationDraft, conversation_id
from src.schemas.scenario import Scenario
from src.utils.crm import load_customers
from src.utils.io import iter_models, load_model, write_json
from src.utils.memory import known_facts_before, speaker_of, stale_slots_before
from src.utils.paths import CONVERSATIONS_DIR, PERSONAS_JSON, POLICY_DIR, PROMPTS_DIR, REPORTS_DIR, SCENARIOS_INTERNAL_DIR
from src.utils.pii import redact_contacts
from src.utils.policy import load_customer_policy
from src.utils.settings import load_settings, model_client, sampling
from src.utils.quota import DailyLimitReached, stop_on_daily_limit


def build_context(scenario: Scenario, call_name: str, customer, persona_style: str, policies: dict) -> dict:
    call = scenario.calls[call_name]
    call_payload = call.model_dump(mode="json", exclude={"simulator_persona_key", "patience_start"})
    return {
        "scenario_id": scenario.scenario_id,
        "call_name": call_name,
        "call": call_payload,
        "memory": known_facts_before(scenario, call_name),
        "stale_slots": stale_slots_before(scenario, call_name),
        "customer": redact_contacts(customer.model_dump(mode="json", include={"name", "honorific", "region"}))
        if customer else {"honorific": scenario.honorific, "region": scenario.region},
        "shared_phone_note": "Another person uses this phone number; confirm identity once and never mention them."
        if call.speaker_customer_id or (customer and customer.shared_phone_with) else None,
        "persona_style": persona_style,
        "policy_documents": policies,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="max scenarios to process")
    parser.add_argument("--resume", action="store_true", help="skip conversations already on disk")
    parser.add_argument("--calls", default="", help="comma-separated subset, e.g. call_2,call_3 (default: all)")
    args = parser.parse_args()
    wanted = {c.strip() for c in args.calls.split(",") if c.strip()}

    settings = load_settings()
    client = model_client("dialogue", settings)
    params = sampling(settings)
    template = (PROMPTS_DIR / "dialogue_full_call.jinja").read_text(encoding="utf-8")
    customers = {c.customer_id: c for c in load_customers()}
    styles = {p["persona_id"]: p.get("style", "") for p in json.loads(PERSONAS_JSON.read_text(encoding="utf-8"))["personas"]}
    policies = load_customer_policy(POLICY_DIR)

    paths = sorted(SCENARIOS_INTERNAL_DIR.glob("SCN-GEN-*.json"))[:args.limit]
    written = 0
    failures: list[dict] = []
    for _, scenario in iter_models(paths, Scenario):
        for session_index, (call_name, call) in enumerate(scenario.ordered_calls(), start=1):
            if wanted and call_name not in wanted:
                continue
            cid = conversation_id(scenario.scenario_id, call_name)
            dest = CONVERSATIONS_DIR / f"{cid}.json"
            if args.resume and dest.exists():
                try:
                    load_model(dest, Conversation)
                    continue
                except ValueError:
                    pass  # old schema: regenerate
            customer = customers.get(speaker_of(scenario, call_name))
            context = build_context(scenario, call_name, customer, styles.get(scenario.persona, ""), policies)
            try:
                draft = client.generate(f"{template}\n\nCALL JSON (trusted):\n{json.dumps(context, ensure_ascii=False)}",
                                        ConversationDraft, temperature=params["temperature"],
                                        max_output_tokens=params["max_output_tokens"])
            except DailyLimitReached:
                raise
            except RuntimeError as error:
                # One transcript the model cannot get right must not stop the other calls.
                print(f"  SKIPPED {cid}: {error}", flush=True)
                failures.append({"conversation_id": cid, "error": str(error)})
                continue
            # Identity fields are owned by the pipeline, never by the model; the
            # full Conversation is validated here, from trusted values.
            conversation = Conversation(
                conversation_id=cid, scenario_id=scenario.scenario_id, call=call_name,
                customer_id=speaker_of(scenario, call_name), session_index=session_index,
                channel=call.channel, date=call.call_date, region=scenario.region,
                category=scenario.category, persona=scenario.persona,
                turns=draft.turns, gold=draft.gold,
            )
            write_json(dest, conversation)
            written += 1
            print(f"Wrote {dest.name}", flush=True)
    print(f"Generated {written} reference transcripts")
    write_json(REPORTS_DIR / "dialogue_failures.json", {"failed": failures})
    if failures:
        print(f"{len(failures)} transcript(s) skipped ({', '.join(f['conversation_id'] for f in failures)}); "
              "rerun with --resume to retry only those.", flush=True)


if __name__ == "__main__":
    stop_on_daily_limit(main)()
