"""Stage 5 — replay reference agent turns against the BTC customer simulator.

For each conversation the simulator (``src.simulator.engine``, 8 BTC rules) is
run with three seeds. Each run logs the BTC record
``{scenario_id, call, persona_id, seed, patience_trace, outcome, n_turns, ended_by}``
plus whether the call's ``success_if`` passed, so the report can show
TSR mean ± std across seeds ("tính lặp lại", required deviation ≤ 10 points).

``--llm`` paraphrases customer turns with the ``simulator`` model role; without
it the scripted outline is spoken verbatim and the three seeds are identical.
"""
from __future__ import annotations

import argparse
import json

from src.ground_truth.traces import conversation_rows
from src.metrics.btc_metrics import check_call, has_positive_requirement
from src.planning.persona_config import load_profiles
from src.simulator.engine import SimulatorState
from src.simulator.role_player import CustomerRolePlayer
from src.utils.dataset import Dataset
from src.utils.memory import known_facts_before
from src.utils.paths import SIMULATION_REPLAYS
from src.utils.settings import load_settings, model_client
from src.utils.quota import stop_on_daily_limit

SEEDS_PER_CALL = 3


def agent_input(row: dict) -> dict:
    """Simulator view of one agent response (a trace row): only what a customer would perceive."""
    price = next((c["value"] for c in row["claims"] if c["field"] == "price_vnd" and isinstance(c["value"], (int, float))), None)
    question = row["questions"][0] if row["questions"] else {}
    return {"speaker": "agent_ai", "text": row["agent_text"], "asks_slot": question.get("slot"),
            "q_type": question.get("type"), "tool_calls": row["tool_calls"], "price_vnd": price,
            "silent": not row["agent_text"].strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="max conversations")
    parser.add_argument("--llm", action="store_true", help="paraphrase customer turns with the simulator model")
    args = parser.parse_args()

    settings = load_settings()
    seed_base = int(settings["generation"]["seed"])
    personas = load_profiles()
    role_player = CustomerRolePlayer(personas, model_client("simulator", settings)) if args.llm else None

    output = SIMULATION_REPLAYS
    dataset = Dataset()
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output.open("w", encoding="utf-8") as stream:
        for conversation in dataset.iter_conversations(args.limit):
            call_name = conversation.call
            scenario = dataset.scenario(conversation.scenario_id)
            if scenario is None:
                continue
            call = scenario.calls.get(call_name)
            persona = personas.get(call.simulator_persona_key or scenario.persona) if call else None
            if call is None or persona is None:
                continue
            call_number = int(call_name.split("_")[1])
            outline = [{"text": turn.text, "facts_stated": turn.facts_stated} for turn in conversation.customer_turns()]
            positive = has_positive_requirement(call.success_if)
            spec = scenario.btc_export()["calls"][call_name]
            rows = conversation_rows(conversation)

            for offset in range(SEEDS_PER_CALL):
                state = SimulatorState.from_persona(
                    scenario.scenario_id, call_number, persona, call.customer_goal,
                    dict(known_facts_before(scenario, call_name)), outline, seed_base + offset,
                    call.must_not_ask, call.expected_outcome, call.patience_start)
                trace, history = [], []
                paraphrase = (lambda context, last: role_player.reply(state.persona_id, context, last)) if role_player else None
                for row in rows:
                    history.append(row)
                    view = agent_input(row)
                    # The customer accepts only once the agent has *done* what success requires (official check).
                    view["proposal_correct"] = positive and bool(check_call(spec, history)[0])
                    response = state.respond(view, paraphrase)
                    trace.append({"agent": row["agent_text"], "customer": response.get("text"),
                                  "ended": response.get("ended", False)})
                    if response.get("ended"):
                        break
                success, failures = check_call(spec, history)
                success = bool(success) if success is not None else True
                if state.outcome is None:  # agent ran out of turns without the customer hanging up
                    state.outcome = call.expected_outcome if success else "timeout"
                    state.ended_by = "agent"
                record = {**state.log_record(), "call": call_name, "conversation_id": conversation.conversation_id,
                          "expected_outcome": call.expected_outcome, "tsr_pass": success,
                          "tsr_failures": failures, "trace": trace}
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
    print(f"Wrote {written} seeded simulator replays to {output}")


if __name__ == "__main__":
    stop_on_daily_limit(main)()
