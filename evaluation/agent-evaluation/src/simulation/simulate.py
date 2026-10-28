"""The customer simulator of the organisers' M2 specification, driving the team's agent.

``run_eval.py simulate`` prepares a registered dataset as ``evaluate`` does, then runs it with a
simulated customer instead of the scenarios' fixed ``customer_turns`` (``run_fixed(simulator=...)``),
once per seed and per configuration (``full`` and ``baseline_no_memory``):

- :class:`src.simulation.customer.CustomerSimulator` is the rule kernel: the eight reaction rules in
  the organisers' order, patience by persona and by call, at most twelve customer turns, and the
  mandatory ``SimulatorLog``. :class:`Customer` only fixes one thing in it: a slot counts as
  "already answered" at the start of a call when an *earlier* call of the scenario established it,
  not when this very call is about to (otherwise the first question about a payment would cost
  patience).
- :class:`Observer` classifies each agent reply for the kernel: its questions (open or confirm, by
  slot), the prices it states, whether it is off topic, which of the customer's planned lines it has
  already answered. One model call per agent turn. The kernel and the observer see the scenario's
  ``facts_established``, ``customer_turns`` and slot names; the agent sees none of them, only the
  customer's words (specification section 5c).
- :class:`Voice` says the line the kernel chose in the persona's words (temperature 0.3, the run's
  seed). A rewrite that drops a number of the original is discarded for the original line.

``passed`` for a scenario and seed is the organisers' own ``check_call`` over the tool calls the agent
really made against the BTC mock, in every call that has a ``success_if``. Question counts and price
claims come from the observer, so ``forbidden_claims`` other than prices are not checked here.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.common.contracts import ROOT, checker
from src.simulation.customer import CustomerSimulator, seed_statistics

DEFAULT_MODEL = "gpt-4.1-mini"
TEMPERATURE = 0.3
SEEDS = (0, 1, 2)
from src.baseline.configs import CONFIGS  # noqa: E402

#: What the observer and the customer's voice are told: config/prompts/evaluation.
PROMPTS = ROOT.parents[2] / "config" / "prompts" / "evaluation"
OBSERVER_PROMPT = (PROMPTS / "observer.md").read_text(encoding="utf-8").replace("\r\n", "\n").removesuffix("\n")
VOICE_PROMPT = (PROMPTS / "customer_voice.md").read_text(encoding="utf-8").replace("\r\n", "\n").removesuffix("\n")

#: Calls for one observation: an answer that does not match :class:`Observed`, even repaired, is asked again.
OBSERVER_ATTEMPTS = 3


class ObservedQuestion(BaseModel):
    """One question the agent asks the customer to get or confirm a piece of information."""

    slot: str = Field(description='Exactly one name from SLOTS when the question is about it, otherwise "other".')
    type: Literal["open", "confirm"] = Field(
        description='confirm: the agent re-confirms something already known ("vẫn ... đúng không ạ?", '
                    '"anh chọn ... nhé?"); open: anything else.')


class Observed(BaseModel):
    """What the observer reads in one agent reply (the JSON object OBSERVER_PROMPT asks for)."""

    questions: list[ObservedQuestion] = Field(
        default_factory=list, description="Each information question, once; invitations, permission requests and "
                                          "suggestions are not listed. Empty when there is none.")
    stated_prices_vnd: list[int] = Field(
        default_factory=list, description="Every amount of money the agent states, as integer VND "
                                          "(một triệu chín trăm chín mươi nghìn = 1990000).")
    off_topic: bool = Field(
        False, description="true when the reply is off topic, empty, or only a safe line unrelated to the customer.")
    answered_outline_indices: list[int] = Field(
        default_factory=list, description="Indices of OUTLINE lines this reply already answered in full; [] when unsure.")


#: Words a customer says for the values the specification's facts hold.
SYNONYMS = {"bank": {"chuyển", "khoản"}, "cod": {"thu", "hộ", "nhận", "hàng"}}
NUMBER = re.compile(r"\d[\d.,]*")


def _reference_eval():
    spec = importlib.util.spec_from_file_location("btc_reference_eval", ROOT / "sources/btc/eval/reference_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Model:
    """Chat completions for the customer's side, paid from the run's budget ledger."""

    def __init__(self, model: str | None = None) -> None:
        from src.services.agent import launch

        launch.prepare()
        from openai import OpenAI

        self.model = model or os.environ.get("EVAL_SIM_MODEL") or DEFAULT_MODEL
        self.client = OpenAI(max_retries=0, timeout=60)
        self.calls = 0
        self.input_tokens = self.output_tokens = 0
        self.cost = 0.0

    def chat(self, system: str, user: str, *, seed: int, schema: type[BaseModel] | None = None) -> str:
        """The reply's text; with *schema*, the model is held to its JSON schema (descriptions included)."""
        from src.services.agent import spend
        from ai_agent_service.llm import evaluation_budget

        key = evaluation_budget.reserve("simulator", 0.05)
        try:
            response = self.client.chat.completions.create(
                model=self.model, temperature=TEMPERATURE, seed=seed,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **({"response_format": {"type": "json_schema", "json_schema": {
                    "name": schema.__name__, "strict": False, "schema": schema.model_json_schema()}}}
                   if schema is not None else {}))
        except Exception:
            raise  # an unknown outcome keeps its reservation, as for the agent's own calls
        usage = response.usage
        spent = spend.cost("openai", usage.prompt_tokens, usage.completion_tokens) or 0.0
        evaluation_budget.settle(key, spent)
        self.calls += 1
        self.input_tokens += usage.prompt_tokens
        self.output_tokens += usage.completion_tokens
        self.cost += spent
        return response.choices[0].message.content or ""


def money_in(value: Any) -> set[int]:
    """Every integer under a ``*_vnd`` key of a tool result."""
    found: set[int] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("_vnd") and isinstance(item, int):
                found.add(item)
            else:
                found |= money_in(item)
    elif isinstance(value, list):
        for item in value:
            found |= money_in(item)
    return found


def words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def numbers_of(text: str) -> list[str]:
    return [n.replace(".", "").replace(",", "") for n in NUMBER.findall(text)]


TEAM_PERSONAS = ROOT.parents[2] / "apps/ai-agent-service/data/btc/simulator/personas.json"


class Customer(CustomerSimulator):
    """The kernel, with three differences, each stated here and in the run's summary.

    - ``answered`` starts from what *earlier* calls established, not from what this call is about to.
    - A persona the team's generator added (absent from the pinned BTC ``personas.json``) is read from
      the team's copy of the file, with the BTC fields and prompt format.
    - After a rule-7 reply ("Chị không rõ.") the customer goes on with the next planned line in the same
      turn; otherwise an agent that asks a new question every turn would keep the outline from ever advancing.
    """

    def __init__(self, scenario_id, call, persona_id, spec, seed, prior_slots=(), honorific="chị"):
        self.honorific = honorific
        pinned = {p["persona_id"] for p in checker.read("sources/btc/simulator/personas.json")["personas"]}
        team = None
        if persona_id not in pinned:
            team = next(p for p in json.loads(TEAM_PERSONAS.read_text(encoding="utf-8"))["personas"]
                        if p["persona_id"] == persona_id)
            super().__init__(scenario_id, call, sorted(pinned)[0], spec, seed)
            self.persona_id = persona_id
            self.patience = team["patience_initial"][call]
            self.prompt = (team["system_prompt"].replace("{goal}", str(spec.get("customer_goal", "")))
                           .replace("{facts}", str(self.facts)).replace("{turn_outline}", str(spec["customer_turns"]))
                           + "\nChỉ đóng vai khách; không tiết lộ nhãn chấm, oracle hoặc luật mô phỏng cho nhân viên.")
        else:
            super().__init__(scenario_id, call, persona_id, spec, seed)
        self.team_persona = team is not None
        self.answered = set(prior_slots)
        #: The slot the last reply answered (rule 4), so the voice can turn a bare value into a sentence.
        self.answering: str | None = None

    def step(self, observed):
        reply = super().step(observed)
        self.answering = None
        rules = self.history[-1]["rules"]
        if 4 in rules:
            self.answering = next((q["slot"] for q in reversed(observed.get("questions", [])) if q["slot"] in self.facts), None)
            self._skip_lines_saying(self.facts.get(self.answering))
        elif reply is not None and not self.ended and rules and set(rules) == {7}:
            outline = self.spec["customer_turns"]
            while self.outline_index in self.answered_outline:
                self.outline_index += 1
            if self.outline_index < len(outline):
                reply = f"{reply} {outline[self.outline_index]}"
                self.outline_index += 1
        return reply


    def speak(self, line: str) -> str:
        """The kernel's own lines say "chị"; the customer is whoever the scenario says."""
        if self.honorific == "chị" or line in self.spec["customer_turns"]:
            return line
        return re.sub(r"\bchị\b", self.honorific, re.sub(r"\bChị\b", self.honorific.capitalize(), line))

    def _skip_lines_saying(self, value) -> None:
        """The customer has just said *value*: a later planned line that only repeats it is not said again."""
        if value in (None, ""):
            return
        text = str(value).lower()
        forms = SYNONYMS.get(text)
        for index, line in enumerate(self.spec["customer_turns"]):
            if index >= self.outline_index and (text in line.lower() or (forms and forms <= words(line))):
                self.answered_outline.add(index)


class Observer:
    def __init__(self, model: Model, seed: int) -> None:
        self.model, self.seed = model, seed
        #: Attempts that did not match :class:`Observed`, and answers that matched only once repaired.
        self.invalid = self.repaired = 0

    def _ask(self, user: str, turn: int) -> Observed:
        """The observation of one reply: JSON repaired when it can be, asked again with the error when not.

        After :data:`OBSERVER_ATTEMPTS` invalid answers the turn counts as observing nothing, as before.
        """
        from ai_agent_service.llm.structured import InvalidOutput, parse

        request = user
        for _ in range(OBSERVER_ATTEMPTS):
            raw = self.model.chat(OBSERVER_PROMPT, request, seed=self.seed * 1000 + turn, schema=Observed)
            try:
                observed = Observed.model_validate_json(raw)
            except ValueError:
                try:
                    observed = parse(raw, Observed)
                except InvalidOutput as error:
                    self.invalid += 1
                    request = (f"{user}\n\nRETRY: The previous answer did not match the required JSON schema: "
                               f"{str(error)[:500]}\nAnswer again with one JSON object of exactly that schema.")
                    continue
                self.repaired += 1
            return observed
        return Observed()

    def observe(self, customer_text: str, agent_text: str, slots: list[str], outline: dict[int, str], turn: int) -> dict[str, Any]:
        user = json.dumps({"SLOTS": slots + ["other"], "OUTLINE": outline, "customer_text": customer_text,
                           "agent_text": agent_text}, ensure_ascii=False)
        data = self._ask(user, turn)
        questions = [{"slot": q.slot or "other", "type": q.type} for q in data.questions]
        prices = data.stated_prices_vnd
        answered = [i for i in data.answered_outline_indices if i in outline]
        return {"questions": questions, "prices": prices, "off_topic": data.off_topic,
                "answered_outline_indices": answered, "agent_text": agent_text}


class Voice:
    def __init__(self, model: Model, seed: int) -> None:
        self.model, self.seed = model, seed

    def say(self, customer: Customer, line: str, turn: int) -> str:
        system = customer.prompt + "\n" + VOICE_PROMPT
        slot = customer.answering
        if not slot and line not in customer.spec["customer_turns"]:
            return line  # the kernel's own words (rules 1-3, 6, 7) are not rewritten into persona catch-phrases
        user = (f"Nhân viên vừa hỏi về «{slot}». Giá trị đúng là «{line}». Hãy nói giá trị đó thành một câu trả lời tự nhiên của khách."
                if slot else f"Câu khách sắp nói: «{line}»")
        text = self.model.chat(system, user, seed=self.seed * 1000 + turn).strip().strip('"«»')
        return text if self.faithful(customer, line, text, answer=bool(slot)) else line

    @staticmethod
    def faithful(customer: Customer, line: str, text: str, answer: bool = False) -> bool:
        """A paraphrase may change the words, never the facts, the order of the outline or who is speaking."""
        if not text or len(text) > 2 * len(line) + 40 or Counter(numbers_of(line)) - Counter(numbers_of(text)):
            return False
        mine, said = words(line), words(text)
        if answer and numbers_of(line):  # a number is kept (checked above), however it is written: 1990000, 1.990.000
            return True
        if answer:  # a bare value ("bank") may come back in the customer's own words for it
            if not (mine <= said or any(key in mine and forms <= said for key, forms in SYNONYMS.items())):
                return False
        elif mine and len(mine & said) / len(mine) < 0.3:
            return False
        return answer or not any(other != line and words(other) and len(words(other) & words(text)) / len(words(other)) >= 0.6
                       for other in customer.spec["customer_turns"])


class Session:
    """One simulated call: the kernel, the observer and the voice, and what the check needs afterwards."""

    def __init__(self, customer, observer, voice, spec, config, prior_prices):
        self.customer, self.observer, self.voice = customer, observer, voice
        self.spec, self.config = spec, config
        self.slots = sorted({*spec.get("facts_established", {}), *spec.get("must_not_ask", [])})
        self.known_prices = set(prior_prices)
        self.rows: list[dict[str, Any]] = []
        self.trace: list[dict[str, Any]] = []
        self.turn = 0
        self.last_customer = ""
        self.last_observed: dict[str, Any] = {}

    def first(self) -> str:
        line = self.customer.process({"observed": {}})
        return self._say(line)

    def reply(self, agent_text: str, tool_events: list[dict[str, Any]]) -> str | None:
        calls = [{"name": e["request"]["name"], "args": e["request"].get("args") or {}} for e in tool_events]
        for event in tool_events:
            self.known_prices |= money_in(event.get("result"))
        customer = self.customer
        outline = {i: t for i, t in enumerate(self.spec["customer_turns"]) if i >= customer.outline_index}
        seen = self.observer.observe(self.last_customer, agent_text, self.slots, outline, self.turn)
        success = self.spec.get("success_if") or {}
        wanted = success.get("tool_called")
        offer = bool(wanted) and any(
            c["name"] == wanted and all(v is None or c["args"].get(k) == v for k, v in (success.get("args_match") or {}).items())
            for c in calls)
        offer = offer and not customer.committed  # the customer agrees once per call
        wrong = any(price not in self.known_prices for price in seen["prices"])
        self.rows.append({"agent_text": agent_text, "tool_calls": calls,
                          "questions": [{**q, "text": ""} for q in seen["questions"]],
                          "claims": [{"field": "price_vnd", "value": p} for p in seen["prices"]]})
        handed_off = any(e["request"]["name"] == "handoff.transfer" and isinstance(e.get("result"), dict)
                         and e["result"].get("ticket_id") for e in tool_events)
        if handed_off and not customer.ended:
            customer.finish("chuyen_may", "agent")  # the call went to a person: nothing more is said to the agent
            customer.history.append({"patience": customer.patience, "irritation": customer.irritation, "rules": []})
        if customer.ended:
            self.trace.append({"turn": self.turn, "customer": self.last_customer, "agent": agent_text,
                               "tools": [c["name"] for c in calls], "rules": [], "patience": customer.patience, "next": None})
            return None
        observed = {"questions": seen["questions"], "wrong_price": wrong, "offer_matches": offer,
                    "silent_or_off_topic": seen["off_topic"] or not agent_text.strip(),
                    "answered_outline_indices": seen["answered_outline_indices"]}
        line = customer.process({"observed": observed})
        self.trace.append({"turn": self.turn, "customer": self.last_customer, "agent": agent_text,
                           "tools": [c["name"] for c in calls], "observed": {**observed, "stated_prices": seen["prices"]},
                           "rules": customer.history[-1]["rules"], "patience": customer.patience, "next": line})
        return None if line is None else self._say(line)

    def _say(self, line: str) -> str:
        self.turn += 1
        self.last_customer = self.voice.say(self.customer, self.customer.speak(line), self.turn)
        return self.last_customer

    def log(self) -> dict[str, Any]:
        return self.customer.log()


class Simulation:
    """What ``run_fixed(simulator=...)`` calls for each call of each scenario and configuration."""

    def __init__(self, seed: int, model: Model) -> None:
        self.seed, self.model = seed, model
        self.observer, self.voice = Observer(model, seed), Voice(model, seed)
        self.sessions: list[dict[str, Any]] = []
        self.history: dict[tuple[str, str], tuple[set[str], set[int]]] = {}

    def session(self, scenario: dict[str, Any], call: str, spec: dict[str, Any], config: str) -> Session:
        sid = scenario["scenario_id"]
        calls = list(scenario["calls"])
        earlier = calls[:calls.index(call)]
        prior_slots = {slot for name in earlier for slot in scenario["calls"][name].get("facts_established", {})}
        prior_prices = {v for name in earlier for v in (scenario["calls"][name].get("ground_truth_facts") or {}).values()
                        if type(v) is int}
        prior_prices |= {v for name in earlier for v in (scenario["calls"][name].get("facts_established") or {}).values()
                         if type(v) is int}
        customer = Customer(sid, call, scenario["persona"], spec, self.seed, prior_slots,
                            honorific=scenario.get("honorific") or "chị")
        session = Session(customer, self.observer, self.voice, spec, config, prior_prices)
        self.sessions.append({"config": config, "scenario_id": sid, "call": call, "spec": spec, "session": session})
        return session


def verdicts(simulation: Simulation, scenarios: dict[str, dict[str, Any]]) -> dict[tuple[str, str], bool | None]:
    """``(config, scenario)`` -> every call with a success_if passed, from the organisers' ``check_call``."""
    check = _reference_eval().check_call
    result: dict[tuple[str, str], bool | None] = {}
    for item in simulation.sessions:
        passed, _ = check(item["spec"], item["session"].rows)
        key = (item["config"], item["scenario_id"])
        if passed is None:
            result.setdefault(key, None)
        else:
            result[key] = bool(result.get(key) in (None, True) and passed)
    return result


def summarize(per_seed: dict[int, Simulation], scenarios: dict[str, dict[str, Any]], seeds: tuple[int, ...]) -> dict[str, Any]:
    """TSR by seed with mean, spread and range, and the customer's side of each configuration."""
    summary: dict[str, Any] = {"seeds": list(seeds), "scenarios": sorted(scenarios), "configs": {}}
    for config in CONFIGS:
        results, logs = [], []
        for seed, simulation in per_seed.items():
            for (conf, sid), passed in verdicts(simulation, scenarios).items():
                if conf == config and passed is not None:
                    results.append({"scenario_id": sid, "seed": seed, "passed": passed})
            logs += [{"config": config, **item["session"].log()} for item in simulation.sessions if item["config"] == config]
        stats = seed_statistics(results, sorted(scenarios), seeds)
        patience = [t[-1] for log in logs for t in [log["patience_trace"]] if t]
        summary["configs"][config] = {
            "tsr": stats, "results": results, "calls": len(logs),
            "outcomes": dict(Counter(log["outcome"] for log in logs)),
            "ended_by": dict(Counter(log["ended_by"] for log in logs)),
            "mean_turns": statistics.mean(log["n_turns"] for log in logs) if logs else None,
            "mean_final_patience": statistics.mean(patience) if patience else None,
            "logs": logs}
    full, base = (summary["configs"][c]["tsr"].get("mean") for c in CONFIGS)
    summary["delta_tsr_full_minus_baseline"] = None if full is None or base is None else round(full - base, 1)
    return summary


def table(summary: dict[str, Any]) -> str:
    rows = ["Customer simulator (BTC spec)  seeds=" + ",".join(map(str, summary["seeds"]))
            + f"  scenarios={len(summary['scenarios'])}",
            f"{'Chỉ số':<44}{'Baseline':>14}{'Hệ thống':>14}{'Chênh lệch':>14}"]

    def cell(config, getter):
        try:
            value = getter(summary["configs"][config])
        except (KeyError, TypeError):
            value = None
        return value

    def line(label, getter, fmt="{:.1f}"):
        base, full = cell("baseline_no_memory", getter), cell("full", getter)
        text = lambda v: "n/a" if v is None else fmt.format(v)
        delta = "n/a" if base is None or full is None else fmt.format(full - base)
        rows.append(f"{label:<44}{text(base):>14}{text(full):>14}{delta:>14}")

    line("TSR mô phỏng, trung bình 3 seed (%)", lambda c: c["tsr"]["mean"])
    line("Độ lệch chuẩn giữa seed (điểm)", lambda c: c["tsr"]["std_population"])
    line("Biên độ TSR giữa seed (điểm, cần ≤ 10)", lambda c: c["tsr"]["range"])
    line("Số lượt khách TB / cuộc", lambda c: c["mean_turns"])
    line("Kiên nhẫn còn lại TB khi kết thúc", lambda c: c["mean_final_patience"])
    for config, label in (("baseline_no_memory", "Baseline"), ("full", "Hệ thống")):
        data = summary["configs"][config]
        rows.append(f"{label}: TSR theo seed {[round(v, 1) for v in data['tsr'].get('per_seed', [])]}  "
                    f"outcome {data['outcomes']}  ended_by {data['ended_by']}")
    stable = [summary["configs"][c]["tsr"].get("stable") for c in CONFIGS]
    rows.append(f"Ổn định giữa seed (biên độ ≤ 10 điểm): baseline={stable[1]} hệ thống={stable[0]}")
    return "\n".join(rows)


def simulate(out, *, only=None, dataset_id=None, level=None, limit=None, seeds=SEEDS, advisor=None,
             extractor_model=None, model=None) -> dict[str, Any]:
    """Prepare, then run every seed with the simulated customer; write the log, the results and the table."""
    from src.common.assets import Assets
    from src.common.progress import say
    from src.common.assets import new_output, write_new
    from src.steps.run.runner import run_fixed
    from src.pipeline import PRODUCT, prepare

    out = new_output(out, Assets(PRODUCT))
    out.mkdir(parents=True, mode=0o700)
    say(f"1/3 Prepare: checking inputs into {out}")
    prepared = prepare(out / "inputs", only=only, dataset_id=dataset_id, level=level, limit=limit,
                       advisor=advisor, extractor_model=extractor_model)
    if not prepared["execution_gate"]["allowed"]:
        raise ValueError("Prepared inputs did not pass the execution gate")
    scenarios = {}
    for path in sorted((out / "inputs/scenarios").glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        scenarios[item["scenario_id"]] = item
    llm = Model(model)
    per_seed, stages = {}, []
    say(f"2/3 Run: {len(scenarios)} scenario(s) x 2 configs x {len(seeds)} seeds with the customer simulator")
    for seed in seeds:
        say(f"--- seed {seed} ---")
        simulation = Simulation(seed, llm)
        raw = run_fixed(out / "inputs/settings.json", out / f"raw-seed{seed}", simulator=simulation)
        per_seed[seed] = simulation
        stages.append({"seed": seed, "execution_complete": raw["execution_complete"],
                       "completed_calls": raw["completed_calls"], "failed_calls": raw["failed_calls"],
                       "errors": raw["errors"]})
        say(f"   calls completed {raw['completed_calls']}, failed {raw['failed_calls']}")
    say("3/3 Summarize: organisers' check_call over the simulated calls")
    summary = summarize(per_seed, scenarios, tuple(seeds))
    complete = all(s["execution_complete"] for s in stages)
    summary.update(execution_complete=complete, stages=stages,
                   simulator_model={"model": llm.model, "temperature": TEMPERATURE, "calls": llm.calls,
                                    "input_tokens": llm.input_tokens, "output_tokens": llm.output_tokens,
                                    "cost_usd": round(llm.cost, 6)},
                   notice="Diagnostic labels pending QA; passed = BTC check_call over real tool calls; observer is an "
                          "unaudited model; non-price forbidden_claims are not checked.")
    text = table(summary)
    write_new(out / "simulator-summary.json", summary)
    write_new(out / "simulator-results.json", summary["configs"]["full"]["results"])
    (out / "simulator-logs.jsonl").write_text(
        "".join(json.dumps(log, ensure_ascii=False) + "\n" for c in CONFIGS for log in summary["configs"][c]["logs"]),
        encoding="utf-8")
    (out / "simulator-turns.jsonl").write_text("".join(
        json.dumps({"seed": seed, "config": item["config"], "scenario_id": item["scenario_id"], "call": item["call"],
                    "turns": item["session"].trace}, ensure_ascii=False) + "\n"
        for seed, simulation in per_seed.items() for item in simulation.sessions), encoding="utf-8")
    (out / "simulator-table.txt").write_text(text + "\n", encoding="utf-8")
    return {"summary": summary, "table": text, "out": str(out)}
