"""Signals: where the system learns it did something badly. ``docs/design.md`` 10.1.

The brief's four sources, each feeding exactly one place:

| Source | Comes from | Feeds |
|---|---|---|
| call outcome | the ``outcome`` slot, the tool log (``order.create``) | Reflection: won and lost calls in a cluster |
| automatic score | the organisers' grader on a learning run (:func:`failures`) | Reflection: which calls are worth learning from |
| consultant's choice | the answer after a handoff; used, edited or own on a copilot suggestion | Gap Loop (the answer), Reflection (the edit) |
| customer repeating | the grader's redundant questions; the classifier live, or "em nói rồi mà" | Reflection (:func:`failures`), memory quality monitoring |

Plus ``oos_early`` and ``oos_late`` for the Gap Loop. A violation (a wrong
promise, a leak) waits for nothing: branch B alerts QA at once.

Every row keeps ``call_id`` and ``turn_id`` (section 5.5).

Two kinds of record live here:

- **Rows** appended to ``signals.jsonl`` in ``IMPROVEMENT_DIR`` (default
  ``data/improvement``; the evaluation clears database tables per scenario, a
  file survives): ``consultant`` (the explicit 👍/👎 on a suggestion and the
  used/edited/own choice, from the console) and ``violation``.
- **Failures** (:func:`failures`): what the organisers' own grader,
  ``eval/reference_eval.py``, finds wrong in one scenario of a learning run,
  call by call and, where it can say, turn by turn. Nothing here is the
  agent's opinion of itself: a model judging its own call is not a signal to
  learn from (Huang et al., ICLR 2024). Each failure is routed by code
  (:data:`ROUTES`) to the one place that may act on it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Literal, Mapping, Sequence

from ...config.config_manager import btc_data_dir
from .storage import locked

Kind = Literal["outcome", "score", "consultant", "repeat", "oos_early", "oos_late", "violation", "eval_error"]

DEFAULT_DIR = Path(__file__).resolve().parents[4] / "data" / "improvement"


def home() -> Path:
    """``IMPROVEMENT_DIR``: signals, rounds, cards, reviews and the improvement log."""
    return Path(os.environ.get("IMPROVEMENT_DIR") or DEFAULT_DIR)


def store() -> Path:
    """``signals.jsonl`` in ``IMPROVEMENT_DIR``."""
    return home() / "signals.jsonl"


async def record(kind: Kind, *, call_id: str, turn_id: str | None, value: Any) -> None:
    """Append one signal; a row is one line, never rewritten."""
    row = {"at": datetime.now(timezone.utc).isoformat(), "kind": kind, "call_id": str(call_id), "turn_id": turn_id, "value": value}
    path = store()
    with locked(home()):
        forgotten = home() / "forgotten-calls.json"
        if forgotten.exists() and str(call_id) in json.loads(forgotten.read_text()):
            return
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read(kind: Kind | None = None) -> list[dict[str, Any]]:
    """Every row (of *kind*), oldest first."""
    path = store()
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if kind is None or row["kind"] == kind]


async def alert_qa(call_id: str, turn_id: str | None, reason: str) -> None:
    """A violation: tell QA now, not in a batch (here: a ``violation`` row QA's page reads)."""
    await record("violation", call_id=call_id, turn_id=turn_id, value={"reason": reason, "alerted": True})


# ── failures, as the organisers' grader sees them ─────────────────────────

#: knowledge: the Gap Loop. behaviour: Reflection, a rule the agent has and did
#: not apply. product: code to fix before the round's code is frozen, never
#: learned (a price the guard let through is the guard's bug, not a lesson).
#: review: a person reads it first; a phrase match is as likely a label as a habit.
Route = Literal["knowledge", "behaviour", "product", "review"]

#: First match wins. A code is ``<metric>.<what>``; see :func:`failures`.
ROUTES: tuple[tuple[re.Pattern[str], Route], ...] = (
    (re.compile(r"^RQR\."), "behaviour"),
    (re.compile(r"^SIM\."), "behaviour"),
    (re.compile(r"^TSR\.(tool_missing|forbidden_tool|too_many_questions|handoff_brief|also_ordered|order_total)"), "behaviour"),
    (re.compile(r"^GUARD\.over_escalation$"), "behaviour"),
    (re.compile(r"^TSR\.must_abstain$"), "knowledge"),
    (re.compile(r"^TSR\.forbidden_claim:(price|list_price|promo)"), "product"),
    (re.compile(r"^TSR\.forbidden_claim:"), "knowledge"),
    (re.compile(r"^HR\.(price|list_price|promo)"), "product"),
    (re.compile(r"^HR\."), "knowledge"),
    (re.compile(r"^(CCR\.|GUARD\.|TSR\.leak$)"), "product"),
)

#: ``check_call``'s reasons, in its own words, to a code. Its wording is the
#: contract (the organisers' file is never edited); a reason it adds later
#: lands under ``TSR.other`` and goes to review.
TSR_REASONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^không có tool call (\S+) khớp"), "tool_missing:{0}"),
    (re.compile(r"^không gọi (handoff\.transfer)"), "tool_missing:{0}"),
    (re.compile(r"^handoff brief thiếu trường"), "handoff_brief"),
    (re.compile(r"^thiếu sản phẩm trong also_ordered"), "also_ordered"),
    (re.compile(r"^tổng đơn"), "order_total"),
    (re.compile(r"^không nói 'không có thông tin'"), "must_abstain"),
    (re.compile(r"^thiếu must_say_any"), "must_say"),
    (re.compile(r"^đã gọi tool cấm (\S+)"), "forbidden_tool:{0}"),
    (re.compile(r"^lời thoại chứa cụm cấm"), "forbidden_phrase"),
    (re.compile(r"^claim cấm (\w+)="), "forbidden_claim:{0}"),
    (re.compile(r"^trace chứa mẫu cấm"), "leak"),
    (re.compile(r"^hỏi \d+ câu"), "too_many_questions"),
)


@dataclass(frozen=True)
class Failure:
    """One thing the grader found wrong, where it happened, and who it happened with."""

    code: str
    route: Route
    scenario_id: str
    call: str
    #: None for what the grader judges over the whole call (Task Success, carryover).
    turn: int | None
    #: Whose call it was: two failures with the same customer are one vote, not two.
    customer: str
    persona: str | None
    hard_case: str | None
    #: The lane the router gave that turn, when the run's diagnostics say.
    lane: str | None
    #: The grader's words, or the question or claim it counted.
    reason: str
    customer_text: str = ""
    agent_text: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Failure":
        return cls(**{name: data.get(name) for name in cls.__dataclass_fields__})  # type: ignore[arg-type]


@lru_cache(maxsize=1)
def grader() -> ModuleType:
    """The organisers' ``eval/reference_eval.py``, imported as it is."""
    path = btc_data_dir() / "eval" / "reference_eval.py"
    spec = importlib.util.spec_from_file_location("btc_reference_eval", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load the organisers' grader from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def route(code: str) -> Route:
    return next((where for pattern, where in ROUTES if pattern.search(code)), "review")


def tsr_code(reason: str) -> str:
    for pattern, code in TSR_REASONS:
        match = pattern.search(reason)
        if match:
            return "TSR." + code.format(*match.groups())
    return "TSR.other"


def customer_of(scenario: Mapping[str, Any]) -> str:
    return str(scenario.get("customer_phone") or scenario.get("customer_name") or scenario["scenario_id"])


def failures(
    scenario: Mapping[str, Any],
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    lanes: Mapping[tuple[str, int], str] | None = None,
    calls: Iterable[str] | None = None,
) -> list[Failure]:
    """What the grader finds wrong in *scenario*, from its trace lines grouped by call.

    Each metric is the grader's own function run on this one call, so a
    failure here is exactly what the official numbers count: a call that
    fails ``success_if`` (one failure per reason), a redundant question
    (``RQR.<slot>``), a ``must_carry_over`` slot not used (``CCR.<slot>``), a
    false claim (``HR.<field>``) and a guardrail violation
    (``GUARD.<type>``). *calls* limits it to some calls; a call without
    trace lines is skipped, not failed.
    """
    g = grader()
    sid = str(scenario["scenario_id"])
    wanted = set(calls) if calls is not None else None
    found: list[Failure] = []

    def add(code: str, call: str, turn: int | None, reason: str, row: Mapping[str, Any] | None = None) -> None:
        found.append(Failure(
            code=code, route=route(code), scenario_id=sid, call=call, turn=turn, customer=customer_of(scenario),
            persona=scenario.get("persona"), hard_case=scenario.get("hard_case") or None,
            lane=(lanes or {}).get((call, turn)) if turn is not None else None, reason=reason,
            customer_text=str((row or {}).get("customer_text") or ""), agent_text=str((row or {}).get("agent_text") or ""),
        ))

    for call, spec in (scenario.get("calls") or {}).items():
        call_rows = list(rows.get(call) or [])
        if not call_rows or (wanted is not None and call not in wanted):
            continue
        by_turn = {int(r["turn"]): r for r in call_rows if r.get("turn") is not None}
        one = {sid: {**scenario, "calls": {call: spec}}}
        trace = {(sid, call): call_rows}

        passed, reasons = g.check_call(spec, call_rows)
        if passed is False:
            for reason in reasons:
                add(tsr_code(reason), call, None, reason)
        for example in g.repeat_question_rate(one, trace)["examples"]:
            turn = int(example["turn"])
            add(f"RQR.{example['slot']}", call, turn, f"{example['type']} question: {example.get('text') or ''}".strip(),
                by_turn.get(turn))
        # The grader counts carried slots without naming the missing ones; the
        # same rule (facts_used plus tool argument names), saying which.
        seen = {slot for r in call_rows for slot in r.get("facts_used") or []}
        seen |= {key for r in call_rows for tool in r.get("tool_calls") or [] for key in (tool.get("args") or {})}
        for slot in spec.get("must_carry_over") or []:
            if slot not in seen:
                add(f"CCR.{slot}", call, None, f"{slot} was known and not used")
        for example in g.hallucination_rate(one, trace)["examples"]:
            turn = int(example["turn"])
            add(f"HR.{example['field']}", call, turn, f"said {example['claimed']!r}, true {example['truth']!r}", by_turn.get(turn))
        for example in g.guardrail_violations(one, trace)["examples"]:
            add(f"GUARD.{example['type']}", call, None, str(example.get("token") or example["type"]))
    return found


#: Outcomes the customer did not reach the scenario's own ending with.
LOST = ("tu_choi", "timeout")


def simulated(scenario: Mapping[str, Any], call: str, log: Mapping[str, Any]) -> list[Failure]:
    """What a simulated customer's log shows went wrong in *call*.

    ``SIM.lost``: the customer refused or ran out of turns where the scenario
    expected a sale or a callback. ``SIM.challenged``: the persona had to
    check something the agent said (a discount no promotion backs, an
    invented specification), as its prompt says it does.
    """
    spec = scenario["calls"][call]
    expected = spec.get("expected_outcome")
    found: list[Failure] = []

    def add(code: str, reason: str) -> None:
        found.append(Failure(code=code, route=route(code), scenario_id=str(scenario["scenario_id"]), call=call, turn=None,
                             customer=customer_of(scenario), persona=scenario.get("persona"),
                             hard_case=scenario.get("hard_case") or None, lane=None, reason=reason))

    if log.get("outcome") in LOST and expected in ("chot_don", "hen_goi_lai"):
        add("SIM.lost", f"ended {log['outcome']} by {log.get('ended_by')} after {log.get('n_turns')} turns; "
                        f"the scenario expects {expected}")
    challenges = list(log.get("reactions") or []).count("challenge")
    if challenges:
        add("SIM.challenged", f"the persona challenged the agent {challenges} time(s)")
    return found


def harvest(
    scenarios: Iterable[Mapping[str, Any]],
    trace_rows: Iterable[Mapping[str, Any]],
    diagnostics: Iterable[Mapping[str, Any]] = (),
) -> list[Failure]:
    """:func:`failures` over a whole run: its scenarios, its ``full`` trace and its diagnostics."""
    by_scenario: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for row in trace_rows:
        by_scenario.setdefault(str(row["scenario_id"]), {}).setdefault(str(row["call"]), []).append(row)
    lanes: dict[str, dict[tuple[str, int], str]] = {}
    for item in diagnostics:
        if item.get("config") not in (None, "full") or item.get("turn") is None or not item.get("lane"):
            continue
        lanes.setdefault(str(item["scenario_id"]), {})[(str(item["call"]), int(item["turn"]))] = str(item["lane"])
    found: list[Failure] = []
    for scenario in scenarios:
        sid = str(scenario["scenario_id"])
        found += failures(scenario, by_scenario.get(sid, {}), lanes=lanes.get(sid))
    return found
