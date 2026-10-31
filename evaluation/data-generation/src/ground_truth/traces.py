"""Build BTC ``trace_log`` rows (one JSON object per agent turn).

Row shape (as read by ``data/eval/reference_eval.py`` and shown in ``data/eval/runs/full.jsonl``)::

    {run_id, config, scenario_id, call, turn, customer_text, agent_text,
     questions: [{slot, type: open|confirm, text}], facts_used: [slot], claims: [{field, value}],
     tool_calls: [{name, args, result}], memory_writes: [...],
     latency: {ttft_ms, total_ms, ttfa_ms}, call_brief_latency_ms?}

Two producers:

* ``oracle_rows(scenario)``           – the ideal agent, derived only from the labels. If the
  official script does not give it CCR 100 / RQR 0 / TSR 100 / HR 0 / 0 guardrail
  violations, a label is wrong (not the agent).
* ``conversation_rows(conv, scenario)`` – a reference transcript (LLM-written) as a trace.
"""
from __future__ import annotations

from typing import Any

from src.metrics.btc_metrics import ABSTAIN_PHRASES
from src.schemas.conversation import AgentTurn, Conversation, CustomerTurn
from src.schemas.scenario import CallSpec, Scenario
from src.utils.btc_schemas import INPUT_MODES
from src.utils.btc_tools import call_tool, mock_tools

# ground_truth_facts keys that are context, not claimable facts.
NON_CLAIM_FACTS = {"call_date", "unknown_topic", "off_topic_question", "policy_version"}
# memory_expectation keys that are instructions to the checker, not values to write.
MEMORY_CONTROL_KEYS = {"superseded", "must_not_write_to", "address_ttl_check", "profile_state"}
# trace_log.schema.json requires integer ttft_ms/total_ms. A trace built from labels was never timed: 0, not a
# measurement (reference_eval's latency section of these traces means nothing).
NO_LATENCY = {"ttft_ms": 0, "total_ms": 0, "ttfa_ms": None}


def _row(scenario_id: str, call: str, turn: int, customer_text: str, run_id: str, config: str,
         input_mode: str | None = None) -> dict[str, Any]:
    row = {"run_id": run_id, "config": config, "scenario_id": scenario_id, "call": call, "turn": turn,
           "customer_text": customer_text, "agent_text": "", "questions": [], "facts_used": [], "claims": [],
           "tool_calls": [], "memory_writes": [], "latency": dict(NO_LATENCY)}
    if input_mode in INPUT_MODES:   # the mode the system received the customer's words in
        row["customer_input_mode"] = INPUT_MODES[input_mode]
    return row


def _customer_lines(call: CallSpec) -> list[str]:
    """BTC: when customer_turns_asr exists, the system receives that version."""
    return call.customer_turns_asr if call.input_mode != "text" and call.customer_turns_asr else call.customer_turns


def oracle_rows(scenario: Scenario, run_id: str = "oracle", config: str = "full") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for call_name, call in scenario.ordered_calls():
        lines = _customer_lines(call)
        call_rows = [_row(scenario.scenario_id, call_name, t, text, run_id, config, call.input_mode)
                     for t, text in enumerate(lines, 1)]
        first, middle, last = call_rows[0], call_rows[min(1, len(call_rows) - 1)], call_rows[-1]
        honor = scenario.honorific or "anh/chị"

        # Turn 1 — continuity (CCR) and identity / TTL confirmation, at most one confirm per slot (RQR).
        opening = [f"Dạ em chào {honor} ạ."]
        if call.must_carry_over:
            first["facts_used"] = list(call.must_carry_over)
            opening.append("Dạ em có thông tin lần trước của mình rồi ạ.")
        if call.memory_expectation.get("address_ttl_check"):
            first["questions"].append({"slot": "delivery_area", "type": "confirm",
                                       "text": "Mình vẫn nhận hàng ở địa chỉ cũ đúng không ạ?"})
        if call.expected_call_brief is not None:
            first["call_brief_latency_ms"] = None
        first["agent_text"] = " ".join(opening)
        first["tool_calls"] += _lookups(scenario, call)

        # Middle turn — every checkable fact, stated exactly as in ground truth (HR).
        middle["claims"] = [{"field": k, "value": v} for k, v in call.ground_truth_facts.items()
                            if k not in NON_CLAIM_FACTS and v is not None]
        said = []
        if call.success_if.must_say_any:
            said.append(f"Dạ {call.success_if.must_say_any[0]} ạ.")
        if call.success_if.agent_must_say:
            said.append(f"Dạ câu này em {ABSTAIN_PHRASES[1]}, em ghi nhận và báo lại {honor} ạ.")
        if call.ground_truth_facts.get("is_human") is False:
            said.append("Dạ em là trợ lý ảo AI của shop ạ.")
        middle["agent_text"] = (middle["agent_text"] + " " + " ".join(said)).strip() or "Dạ em kiểm tra thông tin ạ."

        # Last turn — the executed tool calls (TSR) and memory writes (memory_checks).
        last["tool_calls"] += [{"name": tc["name"], "args": tc["args"], "result": tc["result"]}
                              for tc in call.oracle_tool_calls]
        # trace_log.schema.json: {key, value, op: set|supersede|delete, source: "call_n#turnk", customer_id}
        superseded = call.memory_expectation.get("superseded") or {}
        speaker = call.speaker_customer_id or scenario.customer_id
        last["memory_writes"] = [{"key": k, "value": v, "op": "supersede" if k in superseded else "set",
                                  "source": f"{call_name}#turn{last['turn']}", "customer_id": speaker}
                                 for k, v in call.memory_expectation.items() if k not in MEMORY_CONTROL_KEYS]
        if not last["agent_text"]:
            last["agent_text"] = "Dạ em cảm ơn ạ."
        rows.extend(call_rows)
    return rows


def _lookups(scenario: Scenario, call: CallSpec) -> list[dict[str, Any]]:
    """Read-only lookups an ideal agent makes first: identify the caller, then quote/stock on the call date."""
    mock = mock_tools()
    on = call.call_date.isoformat()
    phone = scenario.customer_phone
    calls = [{"name": "crm.get_customer", "args": {"phone": phone}}]
    sku = call.facts_established.get("variant_sku") or call.facts_established.get("product_advised")
    if sku and "price_vnd" in call.ground_truth_facts:
        calls += [{"name": "pricing.get_quote", "args": {"sku": sku, "on": on, "customer_phone": phone}},
                  {"name": "inventory.check", "args": {"sku": sku, "on": on}}]
    for tc in calls:
        tc["result"] = call_tool(mock, tc["name"], tc["args"])
        tc["result"] = {k: v for k, v in tc["result"].items() if not k.startswith("_")}  # never surface internal floor
    return calls


def conversation_rows(conversation: Conversation, mock=None, run_id: str = "reference",
                      config: str = "full") -> list[dict[str, Any]]:
    """Pair each customer turn with the agent turns that follow it; execute tool calls on ``mock`` if given."""
    rows: list[dict[str, Any]] = []
    pending_agent: list[AgentTurn] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        if current is None:
            return
        for agent in pending_agent:
            current["agent_text"] = (current["agent_text"] + " " + agent.text).strip()
            current["questions"] += [q.model_dump() for q in agent.questions]
            current["facts_used"] += agent.facts_used
            current["claims"] += [c.model_dump() for c in agent.claims]
            current["memory_writes"] += agent.memory_writes
            for tc in agent.tool_calls:
                result = None
                if mock is not None and tc.name in mock.TOOLS:
                    try:
                        result = call_tool(mock, tc.name, tc.args)
                    except Exception as exc:  # malformed args from the model: keep the trace, record the error
                        result = {"error": f"{type(exc).__name__}: {exc}"}
                current["tool_calls"].append({"name": tc.name, "args": tc.args, "result": result})
        pending_agent.clear()

    leading: list[AgentTurn] = []
    for turn in conversation.turns:
        item = turn.root
        if isinstance(item, CustomerTurn):
            flush()
            current = _row(conversation.scenario_id, conversation.call, len(rows) + 1, item.text, run_id, config)
            rows.append(current)
            pending_agent.extend(leading)   # an agent greeting before the first customer turn
            leading.clear()
        elif current is None:
            leading.append(item)
        else:
            pending_agent.append(item)
    flush()
    return rows
