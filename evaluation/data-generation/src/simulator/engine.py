"""Customer simulator state machine. Hidden scenario gold is never sent to a customer model."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class SimulatorState:
    scenario_id: str
    call: int
    persona_id: str
    seed: int
    goal: str
    facts_established: dict[str, Any]
    customer_turns: list[dict[str, Any]]
    must_not_ask: set[str]
    patience: int
    expected_outcome: str | None = None
    asked_slots: set[str] = field(default_factory=set)
    answered_slots: set[str] = field(default_factory=set)
    confirmation_seen: set[str] = field(default_factory=set)
    irritation: int = 0
    silence_streak: int = 0
    price_challenged: bool = False
    n_turns: int = 0
    cursor: int = 0
    outcome: str | None = None
    ended_by: str = "agent"
    patience_trace: list[int] = field(default_factory=list)

    @classmethod
    def from_persona(cls, scenario_id: str, call: int, persona: dict, goal: str,
                     facts_established: dict, customer_turns: list[dict], seed: int,
                     must_not_ask: list[str] = (), expected_outcome: str | None = None,
                     patience_start: int | None = None):
        patience = patience_start if patience_start is not None else int(persona["patience_initial"].get(f"call_{call}", 3))
        return cls(scenario_id, call, persona["persona_id"], seed, goal, facts_established,
                   customer_turns, set(must_not_ask), patience, expected_outcome,
                   answered_slots=set(facts_established),
                   patience_trace=[patience])

    def respond(self, agent_turn: dict[str, Any], paraphrase: Callable[[dict[str, Any], dict[str, Any]], str] | None = None) -> dict[str, Any]:
        """Apply BTC rules, then optionally paraphrase the next outline without exposing gold."""
        if self.outcome:
            return {"ended": True, "outcome": self.outcome}
        if self.n_turns >= 12:
            self.outcome, self.ended_by = "timeout", "timeout"
            return {"ended": True, "outcome": self.outcome}
        slot, q_type = agent_turn.get("asks_slot"), agent_turn.get("q_type")
        repeated = bool(slot and (slot in self.must_not_ask or slot in self.answered_slots))
        if slot:
            if q_type == "confirm" and slot not in self.confirmation_seen:
                self.confirmation_seen.add(slot)
                repeated = False
            else:
                repeated = repeated or (q_type == "confirm" and slot in self.confirmation_seen)
            self.asked_slots.add(slot)
        if repeated:
            self.patience -= 1
            self.irritation += 1
        if agent_turn.get("silent") or agent_turn.get("off_topic"):
            self.silence_streak += 1
        else:
            self.silence_streak = 0
        if self.silence_streak == 2:
            return self._say("em còn đó không ạ?")
        if self.silence_streak >= 3:
            self.outcome, self.ended_by = "tu_choi", "customer"
            self.n_turns += 1
            return {"ended": True, "text": "Thôi chị cúp máy đây.", "outcome": self.outcome}
        if self.patience <= 0:
            self.patience_trace.append(self.patience)
            self.outcome, self.ended_by = "tu_choi", "customer"
            self.n_turns += 1
            return {"ended": True, "text": "Thôi để chị xem lại.", "outcome": self.outcome}
        # Rule 3: a price different from the one quoted earlier costs patience, once a call: the customer reacts,
        # and an agent that explains why (an ended promotion) is not punished again for repeating the new price.
        expected_price = self.facts_established.get("price_quoted_vnd", self.facts_established.get("final_price_vnd"))
        if (not self.price_challenged and expected_price is not None and agent_turn.get("price_vnd") is not None
                and agent_turn.get("price_vnd") != expected_price):
            self.price_challenged = True
            self.patience -= 1
            if self.patience <= 0:
                self.patience_trace.append(self.patience)
                self.outcome, self.ended_by = "tu_choi", "customer"
                self.n_turns += 1
                return {"ended": True, "text": "Thôi để chị xem lại.", "outcome": self.outcome}
            return self._say("Hôm trước em báo giá khác mà, sao giờ lại cao hơn vậy?")
        if slot:
            value, source_index = self._known_or_outlined_fact(slot)
            if value is None:
                self.asked_slots.add(slot)
                return self._say("Chị không rõ em ạ.")
            if source_index is not None:
                self.cursor=source_index+1
            self.facts_established[slot]=value
            self.answered_slots.add(slot)
            answer=(f"Dạ, đúng {value} ạ." if q_type=="confirm" else f"{value} ạ.")
            if repeated: answer=f"{answer} Hôm trước chị nói rồi mà em."
            return self._say(answer)
        if self.expected_outcome and agent_turn.get("proposal_correct"):
            self.outcome, self.ended_by = self.expected_outcome, "customer"
            self.n_turns += 1
            text="Dạ, chị đồng ý hẹn lại." if self.expected_outcome in ("hen_lai","hen_goi_lai") else "Dạ, chị đồng ý theo phương án vừa trao đổi."
            self.patience_trace.append(self.patience)
            return {"ended":True,"text":text,"outcome":self.outcome}
        if self.cursor >= len(self.customer_turns):
            self.outcome, self.ended_by = "timeout", "timeout"
            return {"ended": True, "outcome": self.outcome}
        outline = self.customer_turns[self.cursor]
        self.cursor += 1
        self.n_turns += 1
        safe_context = {"goal": self.goal, "facts_established": self.facts_established,
                        "outline": outline, "irritation": self.irritation,"seed":self.seed}
        text = paraphrase(safe_context, agent_turn) if paraphrase else str(outline.get("text", "Chị muốn hỏi thêm thông tin em nhé."))
        if repeated:
            text = "Hôm trước chị nói rồi mà. " + text
        self.patience_trace.append(self.patience)
        stated = outline.get("facts_stated", {})
        self.facts_established.update(stated)
        self.answered_slots.update(stated)
        return {"ended": False, "text": text, "facts_stated": stated}

    def _say(self, text: str) -> dict[str, Any]:
        if self.n_turns >= 12:
            self.outcome, self.ended_by = "timeout", "timeout"
            return {"ended": True, "outcome": self.outcome}
        self.n_turns += 1
        self.patience_trace.append(self.patience)
        return {"ended": False, "text": text, "facts_stated": {}}

    def _known_or_outlined_fact(self, slot: str) -> tuple[Any, int | None]:
        if slot in self.facts_established:
            return self.facts_established[slot], None
        for index in range(self.cursor,len(self.customer_turns)):
            facts=self.customer_turns[index].get("facts_stated",{})
            if slot in facts:
                return facts[slot],index
        return None,None

    def log_record(self) -> dict[str, Any]:
        return {"scenario_id": self.scenario_id, "call": self.call, "persona_id": self.persona_id,
                "seed": self.seed, "patience_trace": self.patience_trace, "outcome": self.outcome,
                "n_turns": self.n_turns, "ended_by": self.ended_by}
