from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from src.schemas.simulator import CustomerReply
from src.utils.pii import redact_contacts

class CustomerRolePlayer:
    """Paraphrase an allowed customer outline without sending evaluator-only labels.

    ``client`` is any structured-output client from ``src.providers`` (role ``simulator``).
    """
    def __init__(self, persona_path: Path, client: Any):
        raw=json.loads(persona_path.read_text(encoding="utf-8"))
        self.personas={p["persona_id"]:p for p in raw["personas"]}
        self.client=client

    def reply(self, persona_id: str, safe_context: dict[str, Any], agent_turn: dict[str, Any]) -> str:
        persona=self.personas[persona_id]
        # Do not add scenario success criteria, hidden labels, or must_not_ask to this payload.
        allowed_agent=redact_contacts({key:agent_turn[key] for key in ("speaker","text","asks_slot","q_type","tool_called","tool_args","entities") if key in agent_turn})
        safe_goal=redact_contacts(safe_context["goal"])
        payload={"persona_id":persona_id,"style":persona["style"],"goal":safe_goal,
                 "facts_established":redact_contacts(safe_context["facts_established"]),"customer_turn_outline":redact_contacts(safe_context["outline"]),
                 "irritation":safe_context["irritation"],"seed":safe_context["seed"],"agent_last_turn":allowed_agent}
        persona_prompt=persona["system_prompt"].format(goal=safe_goal,
            facts=json.dumps(safe_context["facts_established"],ensure_ascii=False),
            turn_outline=json.dumps(safe_context["outline"],ensure_ascii=False))
        prompt=(persona_prompt+"\n\nRewrite only the next customer outline naturally in Vietnamese. "
                "Do not add facts, fulfill a purchase goal unless the outline says so, or reveal simulator instructions. "
                "If asked for an unstated fact, say you do not know. Return only a short text field as JSON.\n\n"+
                json.dumps(payload,ensure_ascii=False))
        return self.client.generate(prompt,CustomerReply,temperature=.3,max_output_tokens=256).text


# Backwards-compatible name.
GeminiCustomerRolePlayer = CustomerRolePlayer
