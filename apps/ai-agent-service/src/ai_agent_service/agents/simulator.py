"""SimulatorAgent: the customer of the improvement loop's exploration. ``docs/design.md`` sections 9.8 and 10.3.

**Not the evaluation's simulator.** The evaluation keeps its own, a measuring
instrument no round changes. This one plays the customer only while the
exploration (``pipeline/improve``) tries hints on the learning set, so the
two never share code, a model (this one is ``agents.simulator``), an
observer, a cache or a database, and the frozen test set never meets this
one.

It follows the organisers' specification (``simulator/customer_simulator_spec.md``)
so a hint that works here works against the customer the official runs play:

- :class:`Customer` is the rule kernel, deterministic: the eight reaction
  rules in the specification's order, patience by persona and by call, at
  most twelve customer turns, the mandatory log. It reads the scenario's
  ``facts_established``, ``must_not_ask``, ``customer_turns``, the tool that
  ``success_if`` expects and ``expected_outcome``; the agent sees none of
  them, only what the customer says.
- :meth:`Session.observe` labels each agent reply, its questions by slot
  (open or confirm) and its claims, with the product's own extractor
  (``components.evaluation.scorers.Extractor``) run on this agent's model
  and cache. The same labels grade the branch.
- the **persona** decides what the specification leaves to it. The
  specification has a model play the customer from the persona's prompt,
  within the eight rules: the prompt is what the customer is, not a voice.
  So whenever the rules leave the customer about to say the next line of the
  outline, the persona reads the agent's reply against its own prompt and
  either says that line in its words, or reacts the way its prompt says it
  would: not accepting yet ("hold": the price-comparing customer the agent
  gave no value to), checking ("challenge": "chương trình gì?" after a
  discount no promotion backs, "em chắc không?" after an invented
  specification), or ending the call ("leave": "thôi khỏi"). It never
  reacts beyond its prompt, never adds a fact, and never makes the outcome
  better than the scenario's: agreement is still rule 5's, on the agent's
  real tool call. A rewrite that loses a number of the line is discarded for
  the line itself.

Two choices the specification leaves open, made here: a question about
"other" (an offer, a closing question) is not a slot, so the kernel neither
counts it nor answers "chị không rõ"; and after answering an asked slot the
customer waits, the outline going on at the next turn.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..components.evaluation.scorers import Extractor
from ..components.memory.ontology import slot as slot_spec
from ..components.improvement.signals import grader, home
from ..config.config_manager import btc_data_dir
from ..llm.callback_handler import text_of
from .base import BaseAgent, model_for

logger = logging.getLogger(__name__)

MAX_TURNS = 12
#: A spent daily quota: retrying cannot pass, and the exploration must stop (``ProviderExhausted``).
DAILY_QUOTA = re.compile(r"per ?day|perday", re.IGNORECASE)
#: Before the one retry of a call that failed: an overloaded model often answers a moment later.
RETRY_PAUSE_S = 2.0
#: Patience when a persona does not say (the specification's range is 2 to 5).
DEFAULT_PATIENCE = 3


@lru_cache(maxsize=1)
def personas() -> dict[str, dict[str, Any]]:
    data = json.loads((btc_data_dir() / "simulator" / "personas.json").read_text(encoding="utf-8"))
    return {p["persona_id"]: p for p in data["personas"]}


def known_prices(scenario: Mapping[str, Any], call: str) -> set[int]:
    """Every amount the customer has heard before this call or is told in it: they notice a different one."""
    names = list(scenario["calls"])
    prices: set[int] = set()
    for name in names[: names.index(call) + 1]:
        spec = scenario["calls"][name]
        for block in ("ground_truth_facts", "facts_established"):
            prices |= {v for v in (spec.get(block) or {}).values() if type(v) is int and v >= 1000}
    return prices


def money_in(value: Any) -> set[int]:
    """Amounts a tool returned, under any key that names a price."""
    found: set[int] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(item) is int and ("price" in key or "total" in key or key.endswith("_vnd")):
                found.add(item)
            else:
                found |= money_in(item)
    elif isinstance(value, list):
        for item in value:
            found |= money_in(item)
    return found


Reaction = Literal["follow", "hold", "challenge", "leave"]


@dataclass
class Observation:
    """What the kernel needs of one agent reply, the persona's reaction to it included."""

    questions: list[dict[str, str]] = field(default_factory=list)
    prices: list[int] = field(default_factory=list)
    offer_matches: bool = False
    silent: bool = False
    handed_off: bool = False
    #: The persona's reaction, used only where the rules leave the next outline line to be said.
    reaction: Reaction = "follow"
    #: Its words: the next line rephrased (follow), or what it says instead.
    persona_line: str = ""
    agent_text: str = ""


class Customer:
    """The rule kernel: what a scripted customer with a patience says next."""

    def __init__(self, scenario: Mapping[str, Any], call: str, *, seed: int) -> None:
        self.scenario_id = str(scenario["scenario_id"])
        self.call, self.seed = call, seed
        self.spec = scenario["calls"][call]
        self.persona_id = str(scenario.get("persona") or "")
        persona = personas().get(self.persona_id) or {}
        self.patience = int((persona.get("patience_initial") or {}).get(call, DEFAULT_PATIENCE))
        self.honorific = str(scenario.get("honorific") or "chị")
        self.facts = dict(self.spec.get("facts_established") or {})
        names = list(scenario["calls"])
        #: Rule 1: what earlier calls established counts as already said, not what this call is about to.
        self.prior = {slot: value for name in names[: names.index(call)]
                      for slot, value in (scenario["calls"][name].get("facts_established") or {}).items()}
        self.answered = set(self.prior)
        self.outline = list(self.spec.get("customer_turns") or [])
        self.next_line = 0
        self.confirms: Counter[str] = Counter()
        self.irritation = self.silence = self.n = 0
        self.committed = self.ended = False
        self.outcome, self.ended_by = "khac", "agent"
        self.history: list[dict[str, Any]] = []
        self.reactions: list[str] = []
        #: Agent replies before the customer agreed (rule 5): turns_to_commit.
        self.committed_at: int | None = None
        self.last_said = self.agent_said = ""
        #: The slots this turn's words answer (rule 4), for the voice to say them as a customer would.
        self.answering: list[str] = []
        self.prompt = str(persona.get("system_prompt") or "Bạn là khách hàng Việt Nam đang gọi cho shop.").replace(
            "{goal}", str(self.spec.get("customer_goal") or scenario.get("customer_goal") or "")).replace(
            "{facts}", json.dumps({**self.prior, **self.facts}, ensure_ascii=False)).replace(
            "{turn_outline}", json.dumps(self.outline, ensure_ascii=False))

    def first(self) -> str | None:
        line = self._planned()
        self.history.append({"patience": self.patience, "irritation": self.irritation, "rules": []})
        return self._count(line)

    def upcoming(self) -> str | None:
        """The next line of the outline, not yet said."""
        return self.outline[self.next_line] if self.next_line < len(self.outline) else None

    def step(self, seen: Observation) -> str | None:
        """The customer's next words after the agent's reply, or None when the call is over."""
        if self.ended:
            raise ValueError("The call is over")
        rules: list[int] = []
        said: list[str] = []
        self.answering = []
        self.agent_said = seen.agent_text
        if seen.handed_off:
            self._finish("chuyen_may", "agent")
            return self._log(rules, None)

        asked = [q for q in seen.questions if q.get("slot") and q["slot"] != "other"]
        repeated: set[str] = set()
        for question in asked:  # rule 1: still answered, with a complaint
            slot = question["slot"]
            if question.get("type") == "confirm":
                self.confirms[slot] += 1
            known = slot in self.answered or slot in (self.spec.get("must_not_ask") or [])
            if known and (question.get("type") != "confirm" or self.confirms[slot] > 1):
                self.patience = max(0, self.patience - 1)
                self.irritation += 1
                rules.append(1)
                repeated.add(slot)
                value = self.facts.get(slot, self.prior.get(slot))
                said.append(f"Hôm trước {self.honorific} nói rồi mà." + (f" {value}." if value not in (None, "") else ""))
        if self.patience == 0:  # rule 2
            rules.append(2)
            self._finish("tu_choi", "customer")
            return self._log(rules, f"Thôi để {self.honorific} xem lại.")
        if seen.prices:  # rule 3
            rules.append(3)
            self.patience = max(0, self.patience - 1)
            self.committed = False
            said.append("Hôm trước em báo giá khác mà?")
            if self.patience == 0:
                self._finish("tu_choi", "customer")
                return self._log(rules, " ".join(said))
        answering = bool(repeated)
        for question in asked:  # rules 4 and 7
            slot = question["slot"]
            if slot in repeated or slot in self.answered:
                continue
            if slot in self.facts:
                rules.append(4)
                said.append(spoken(self.facts[slot]))
                self.answered.add(slot)
                self.answering.append(slot)
                answering = True
            elif slot not in self.answered:
                rules.append(7)
                said.append(f"{self.honorific.capitalize()} không rõ.")
        if seen.offer_matches and not seen.prices and not self.committed:  # rule 5
            rules.append(5)
            self.committed = True
            self.committed_at = self.n
            self.outcome = str(self.spec.get("expected_outcome") or "khac")
            said.append(f"{self.honorific.capitalize()} hẹn gọi lại nhé." if self.outcome == "hen_goi_lai"
                        else f"Dạ, {self.honorific} đồng ý.")
        self.silence = self.silence + 1 if seen.silent else 0
        if self.silence >= 2:  # rule 6
            rules.append(6)
            if self.silence >= 3:
                self._finish("tu_choi", "customer")
                return self._log(rules, None)
            said.append("Em còn đó không?")
        if self.n >= MAX_TURNS:  # rule 8
            rules.append(8)
            self._finish("timeout", "timeout")
            return self._log(rules, None)
        reaction = None
        # Agreeing (rule 5), answering (4, 7) and asking if the agent is there (6) are this turn's words;
        # only a turn the rules leave to the outline is the persona's.
        if not answering and 5 not in rules and 6 not in rules:
            line = self.upcoming()
            if line is None:
                if not said:
                    self._finish(self.outcome, "agent")
                    return self._log(rules, None)
            elif seen.reaction == "leave":
                self.reactions.append("leave")
                self._finish("tu_choi", "customer")
                return self._log(rules, None, "leave")
            elif seen.reaction in ("hold", "challenge"):
                reaction = seen.reaction
                self.reactions.append(reaction)
                said.append(seen.persona_line if self._own_words(seen.persona_line) else (self.last_said or line))
            else:
                self.next_line += 1
                said.append(seen.persona_line if seen.persona_line and faithful(line, seen.persona_line) else line)
        return self._log(rules, self._count(" ".join(said)), reaction)

    def _own_words(self, text: str) -> bool:
        """What the persona says instead of its line: short, and with no number the call has not had."""
        known = numbers(" ".join([*self.outline, *map(str, self.facts.values()), *map(str, self.prior.values()),
                                  self.agent_said]))
        return bool(text.strip()) and len(text) <= 240 and not (numbers(text) - known)

    def log(self) -> dict[str, Any]:
        """The specification's mandatory log of one call, with the persona's reactions and turns_to_commit."""
        return {"scenario_id": self.scenario_id, "call": self.call, "persona_id": self.persona_id, "seed": self.seed,
                "patience_trace": [h["patience"] for h in self.history], "outcome": self.outcome, "n_turns": self.n,
                "ended_by": self.ended_by, "reactions": list(self.reactions), "turns_to_commit": self.committed_at}

    def _planned(self) -> str | None:
        if self.next_line >= len(self.outline):
            return None
        line = self.outline[self.next_line]
        self.next_line += 1
        return line

    def _count(self, line: str | None) -> str | None:
        if line is not None:
            self.n += 1
            self.last_said = line
        return line

    def _finish(self, outcome: str, ended_by: str) -> None:
        self.outcome, self.ended_by, self.ended = outcome, ended_by, True

    def _log(self, rules: list[int], line: str | None, reaction: str | None = None) -> str | None:
        self.history.append({"patience": self.patience, "irritation": self.irritation, "rules": rules,
                             "reaction": reaction})
        return line


class SimulatorAgent(BaseAgent):
    """The exploration's customer: one :class:`Session` per call played."""

    def __init__(self, *, llm: BaseChatModel | None = None, cache_path: Path | None = None) -> None:
        """The model is ``agents.simulator`` in ``config/models.yaml``; *llm* replaces it in a test.

        Without a model the customer says the planned lines as written, and
        the observer is off: no question is classified, so rules 1, 3, 4 and 7
        never fire. That is a script, not a simulation; the exploration
        refuses to run so.
        """
        self.name = "simulator"
        self.llm = llm if llm is not None else model_for("simulator")
        self.model_name = (getattr(self.llm, "model_name", None) or getattr(self.llm, "model", None)
                           or type(self.llm).__name__) if self.llm is not None else None
        self.observer = (Extractor(self.llm, model_name=f"simulator:{self.model_name}",
                                   cache_path=cache_path or home() / "cache" / "simulator-observer.json")
                         if self.llm is not None else None)
        self._persona: Any = None
        #: Every model call of the persona or the voice that failed, as ``Type: message``: a branch
        #: played on a failed customer is not a measurement (``pipeline/improve`` reads it).
        self.errors: list[str] = []

    def session(self, scenario: Mapping[str, Any], call: str, *, seed: int) -> "Session":
        return Session(self, Customer(scenario, call, seed=seed), known_prices(scenario, call))

    async def react(self, customer: Customer, dialogue: Sequence[tuple[str, str]], agent_text: str,
                    upcoming: str) -> tuple[Reaction, str]:
        """The persona's reaction to *agent_text*, with its words; ``follow`` and the line when it cannot say."""
        if self.llm is None:
            return "follow", upcoming
        if self._persona is None:
            self._persona = self.llm.with_structured_output(PersonaTurn)
        heard = "\n".join(f"{'Khách' if who == 'customer' else 'Nhân viên'}: {text}" for who, text in dialogue[-8:])
        request = PERSONA.format(prompt=customer.prompt, honorific=customer.honorific, dialogue=heard or "(chưa có)",
                                 agent=agent_text, upcoming=upcoming)
        try:
            turn: PersonaTurn = await twice(lambda: self._persona.ainvoke(request), "persona")
        except Exception as error:  # noqa: BLE001 - the planned line is always a valid thing to say
            logger.warning("Simulator persona failed: %s", type(error).__name__)
            self.errors.append(f"{type(error).__name__}: {error}"[:300])
            return "follow", upcoming
        return turn.reaction, turn.line.strip().strip('"«»')

    async def say(self, customer: Customer, line: str, *, answering: Sequence[str] = ()) -> str:
        """*line* in the persona's words, or *line* itself when a rewrite would change a fact.

        *answering* names the slots the line answers, so a bare value ("Không.", "20") is said as the
        answer to what the agent asked, as the evaluation's simulator does.
        """
        if self.llm is None or not line.strip():
            return line
        asked = ", ".join(dict.fromkeys((slot_spec(name).label if slot_spec(name) else name) for name in answering))
        task = (f"Nhân viên vừa hỏi về: {asked}. Câu trả lời đúng là «{line}». Nói câu trả lời đó thành lời tự nhiên "
                f"của khách" if asked else f"Câu khách sắp nói: «{line}»")
        request = (f"{customer.prompt}\n\nBạn là KHÁCH, không phải nhân viên. Viết lại câu khách sắp nói bằng giọng "
                   f"của nhân vật, 1-2 câu ngắn, giữ nguyên mọi con số, tên riêng và ý nghĩa, không thêm thông tin mới. "
                   f"Chỉ trả về đúng câu nói.\n\n{task}")
        try:
            text = text_of(await twice(lambda: self.llm.ainvoke(request), "voice")).strip().strip('"«»')
        except Exception as error:  # noqa: BLE001 - the planned line is always a valid thing to say
            logger.warning("Simulator voice failed: %s", type(error).__name__)
            self.errors.append(f"{type(error).__name__}: {error}"[:300])
            return line
        return text if faithful(line, text) else line


async def twice(call: Any, what: str) -> Any:
    """*call*, and once more after a pause when it fails for a reason that may pass (an overloaded or
    throttled model); never after a spent daily quota, which only the next day fixes.

    Each attempt goes through the model's rate limiter, so the retry is counted like any call.
    """
    try:
        return await call()
    except Exception as error:  # noqa: BLE001 - the second failure is the caller's
        if DAILY_QUOTA.search(str(error)):
            raise
        logger.warning("Simulator %s failed once (%s); retrying", what, type(error).__name__)
        await asyncio.sleep(RETRY_PAUSE_S)
        return await call()


def _succeeded(result: Any) -> bool:
    """A tool result that is not a refusal, in the trace's shape (the tool's data) or our envelope's."""
    if not isinstance(result, Mapping) or not result:
        return False
    return bool(result.get("ok")) if "ok" in result else "error" not in result


def spoken(value: Any) -> str:
    """A fact the customer states, as words: a yes or no question is answered "Có." or "Không.", not "True"."""
    if isinstance(value, bool):
        return "Có." if value else "Không."
    return str(value)


class PersonaTurn(BaseModel):
    reaction: Reaction = Field(description="follow, hold, challenge or leave, as the persona's description says.")
    line: str = Field(description="What the customer says now, in Vietnamese, 1-2 short sentences.")


PERSONA = """{prompt}

Bạn là KHÁCH, không phải nhân viên; xưng "{honorific}". Cuộc gọi tới giờ:
{dialogue}

Nhân viên vừa nói: «{agent}»
Câu tiếp theo trong dàn ý của bạn: «{upcoming}»

Chọn đúng một phản ứng, chỉ theo những gì mô tả nhân vật ở trên quy định:
- follow: nói câu tiếp theo trong dàn ý bằng giọng nhân vật, giữ nguyên mọi con số, tên riêng và ý nghĩa.
- hold: mô tả nhân vật nói bạn CHƯA chấp nhận khi nhân viên làm như vừa rồi; nói lại điều bạn còn băn khoăn.
- challenge: mô tả nhân vật nói bạn hỏi lại để kiểm tra khi nhân viên làm như vừa rồi; hỏi đúng câu đó.
- leave: mô tả nhân vật nói bạn kết thúc cuộc gọi khi nhân viên làm như vừa rồi.
Mô tả nhân vật không nói gì về điều nhân viên vừa làm thì chọn follow. Không thêm thông tin mới, không tự đồng ý \
mua, đặt hàng hay hẹn điều gì ngoài dàn ý. line là đúng câu bạn nói, 1-2 câu ngắn."""


def numbers(text: str) -> Counter[str]:
    """The numbers of *text*, "4.890.000" and "4890000" alike."""
    return Counter(re.findall(r"\d+", text.replace(".", "").replace(",", "")))


def faithful(line: str, text: str) -> bool:
    """A rewrite may change the words, never a number, and never grow into a speech."""
    return bool(text) and len(text) <= 2 * len(line) + 40 and not (numbers(line) - numbers(text))


class Session:
    """One call the exploration plays: the kernel, its persona and its observer."""

    def __init__(self, agent: SimulatorAgent, customer: Customer, prices: set[int]) -> None:
        self.agent, self.customer, self.prices = agent, customer, set(prices)
        success = customer.spec.get("success_if") or {}
        self.wanted, self.args = success.get("tool_called"), success.get("args_match")
        self.last_line = ""
        self.dialogue: list[tuple[str, str]] = []

    async def opening(self) -> str | None:
        line = self.customer.first()
        if line is None:
            return None
        self.last_line = await self.agent.say(self.customer, line)
        self.dialogue.append(("customer", self.last_line))
        return self.last_line

    async def observe(self, agent_text: str) -> dict[str, Any]:
        """The agent's questions and claims, as the trace carries them."""
        if self.agent.observer is None:
            return {"questions": [], "claims": [], "set_aside": []}
        labels = await self.agent.observer.label(customer_text=self.last_line, agent_text=agent_text)
        if labels.get("error") and not DAILY_QUOTA.search(str(labels["error"])):
            logger.warning("Simulator observer failed once; retrying")
            await asyncio.sleep(RETRY_PAUSE_S)
            labels = await self.agent.observer.label(customer_text=self.last_line, agent_text=agent_text)
        return labels

    async def reply(self, agent_text: str, tool_calls: Sequence[Mapping[str, Any]],
                    labels: Mapping[str, Any]) -> str | None:
        """The customer's next line after *agent_text* and its tools, or None when they are done."""
        for tool in tool_calls:
            self.prices |= money_in(tool.get("result"))
        stated = [c["value"] for c in labels.get("claims") or []
                  if str(c.get("field", "")).startswith(("price", "list_price")) and type(c.get("value")) is int]
        offer = bool(self.wanted) and any(
            tool.get("name") == self.wanted and grader().args_match(self.args, tool.get("args") or {}) for tool in tool_calls)
        handed = any(tool.get("name") == "handoff.transfer" and _succeeded(tool.get("result")) for tool in tool_calls)
        self.dialogue.append(("agent", agent_text))
        reaction: Reaction = "follow"
        persona_line = ""
        upcoming = self.customer.upcoming()
        if upcoming is not None and not handed:
            reaction, persona_line = await self.agent.react(self.customer, self.dialogue[:-1], agent_text, upcoming)
        seen = Observation(questions=[{"slot": q["slot"], "type": q["type"]} for q in labels.get("questions") or []],
                           prices=[p for p in stated if p not in self.prices], offer_matches=offer,
                           silent=not agent_text.strip(), handed_off=handed, reaction=reaction,
                           persona_line=persona_line, agent_text=agent_text)
        line = self.customer.step(seen)
        if line is not None and self.customer.answering:
            line = await self.agent.say(self.customer, line, answering=self.customer.answering)
        if line is not None:
            self.last_line = line
            self.dialogue.append(("customer", line))
        return line

    def log(self) -> dict[str, Any]:
        return self.customer.log()
