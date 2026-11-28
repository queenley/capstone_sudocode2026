"""Scenarios in the organisers' format, as the evaluation reads them.

The organisers'
``schemas/scenario_format.md``. The organisers' command loads a directory of
scenarios through here.

- **Files.** Every ``*.json`` whose name does not start with ``_``, sorted, as
  ``eval/reference_eval.py`` reads them.
- **Days.** Call 1 is on ``call_date``, else 2026-10-15 plus ``days_later``;
  each later call on its ``call_date``, else the previous call's day plus
  ``days_later``. Calls are numbered from ``call_1`` without gaps and never go
  back in time.
- **Turns.** The ASR or teencode version, ``customer_turns_asr``, when a call
  has one: the system must take that one (``scenario_format.md``). Its
  ``input_mode`` then labels the turn; a call without it is ``clean``.
- **Keys.** :func:`connection`, the one place the evaluation decides what
  identifies a caller.
- **Prior sessions.** ``seed_history`` is written to the ledger before its
  call; :func:`seed_sessions` reads the shapes it is
  likely to take and refuses the rest by name.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from ...components import clock
from ...components.memory import ontology

#: The organisers' channel names (``scenario_format.md``, and ``web_chat`` from
#: ``handoff_brief.schema.json``) to the product's. Anything else is refused.
CHANNELS = {"hotline": "hotline", "zalo_oa": "zalo", "chat_fanpage": "facebook", "web_chat": "web"}
#: How the CRM names the channel of a past session, where it differs from the
#: scenario format's: ``crm_seed*.json`` writes ``fb`` for the Facebook page,
#: and the organisers' ``seed_history`` example (answers of 11/2026) ``phone``.
CRM_SESSION_CHANNELS = {"fb": "facebook", "phone": "hotline"}

#: ``seed_history`` fact fields the organisers name differently from our slots
#: (their example of 11/2026: ``interest_sku``, ``address``). ``address`` has
#: no slot: the ledger keeps an address only as a call's token, so it stays in
#: the session's summary, as a CRM session's address does.
SEED_FIELDS = {"interest_sku": "product_advised"}
SUMMARY_FIELDS = {"address": "Địa chỉ giao"}

#: The harness's name for the field a call's turns come from, as it passes
#: it when a call has no ``input_mode``, to the product's input mode.
INPUT_FIELDS = {"customer_turns_asr": "asr_transcript", "customer_turns": None}
INPUT_MODES = frozenset({"asr_transcript", "chat_teencode"})


class ScenarioError(ValueError):
    """A scenario this evaluation cannot run, and why; the rest still run."""


@dataclass(frozen=True)
class SeedSession:
    """One session that happened before the scenario's call, from ``seed_history``."""

    session_id: str
    day: str
    channel: str
    summary: str
    outcome: str
    #: Flat slots, as ``facts_established`` names them.
    facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallPlan:
    """One call of a scenario, ready to run."""

    name: str
    #: ``YYYY-MM-DD``, the day of the call and every tool's ``on``.
    on: str
    #: The product's channel: hotline, zalo, facebook, web.
    channel: str
    #: ``caller_phone``, ``zalo_id``, ``fb_id``: what the connection brings.
    keys: Mapping[str, str | None]
    turns: tuple[str, ...]
    #: ``asr_transcript`` or ``chat_teencode`` when the turns are the noisy
    #: version; None for clean text, which ``perceive`` then inspects itself.
    input_mode: str | None
    seed: tuple[SeedSession, ...] = ()

    @property
    def trace_input_mode(self) -> str:
        """``customer_input_mode`` of the trace (``trace_log.schema.json``)."""
        return self.input_mode or "clean"


@dataclass(frozen=True)
class Scenario:
    path: Path
    scenario_id: str
    #: The file as written, for the grader and the setup; never shown to the agent.
    data: Mapping[str, Any]
    calls: tuple[CallPlan, ...]


@dataclass(frozen=True)
class Rejected:
    """A scenario file that could not be planned."""

    path: Path
    scenario_id: str
    reason: str


def load(directory: Path, only: set[str] | None = None) -> tuple[list[Scenario], list[Rejected]]:
    """The scenarios of *directory* that can run, and the ones that cannot, with the reason."""
    ready: list[Scenario] = []
    rejected: list[Rejected] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            rejected.append(Rejected(path, path.stem, f"unreadable: {type(error).__name__}: {error}"))
            continue
        scenario_id = str(data.get("scenario_id") or path.stem) if isinstance(data, dict) else path.stem
        if only and scenario_id not in only:
            continue
        try:
            if not isinstance(data, dict):
                raise ScenarioError("a scenario must be an object")
            if not isinstance(data.get("scenario_id"), str) or not data["scenario_id"].strip():
                raise ScenarioError("scenario_id must be a non-empty string")
            if scenario_id in seen:
                raise ScenarioError(f"duplicate scenario_id {scenario_id!r}")
            seen.add(scenario_id)
            ready.append(Scenario(path, scenario_id, data, plan(data)))
        except (ScenarioError, KeyError, TypeError, ValueError) as error:
            rejected.append(Rejected(path, scenario_id, f"{type(error).__name__}: {error}"))
    for missing in sorted((only or set()) - seen - {item.scenario_id for item in rejected}):
        rejected.append(Rejected(directory, missing, "requested scenario_id was not found"))
    return ready, rejected


def plan(scenario: Mapping[str, Any]) -> tuple[CallPlan, ...]:
    """Every call of *scenario*, in order, with its day, keys, turns and prior sessions."""
    if not isinstance(scenario, Mapping) or not isinstance(scenario.get("calls"), dict) or not scenario["calls"]:
        raise ScenarioError("a scenario needs calls")
    days = call_days(scenario)
    plans = []
    for name, day in days.items():
        spec = scenario["calls"][name]
        channel, keys = connection(scenario, spec)
        turns, input_mode = customer_turns(spec)
        seed = seed_sessions(spec.get("seed_history"), day=day, channel=channel) if spec.get("seed_history") else ()
        plans.append(CallPlan(name, day, channel, keys, tuple(turns), input_mode, seed))
    return tuple(plans)


def call_names(scenario: Mapping[str, Any]) -> list[str]:
    """``call_1``, ``call_2``, ...: numbered order, no gaps."""
    if len(scenario["calls"]) > 3:
        raise ScenarioError("the BTC trace schema supports at most three calls")
    if any(not isinstance(name, str) or not re.fullmatch(r"call_[1-9][0-9]*", name) for name in scenario["calls"]):
        raise ScenarioError("call names must be call_1, call_2, ...")
    names = sorted(scenario["calls"], key=lambda name: int(name.split("_")[1]))
    if names != [f"call_{i}" for i in range(1, len(names) + 1)]:
        raise ScenarioError(f"calls must run call_1, call_2, ... without gaps: {names}")
    return names


def call_days(scenario: Mapping[str, Any]) -> dict[str, str]:
    """The day of each call, in call order."""
    day = date.fromisoformat(clock.REFERENCE_DAY)
    days: dict[str, str] = {}
    for name in call_names(scenario):
        spec = scenario["calls"][name]
        if not isinstance(spec, Mapping):
            raise ScenarioError(f"{name} must be an object")
        if spec.get("call_date"):
            current = date.fromisoformat(str(spec["call_date"])[:10])
        else:
            current = day + timedelta(days=int(spec.get("days_later") or 0))
        if days and current < day:
            raise ScenarioError(f"{name} is dated before the call it follows")
        days[name] = current.isoformat()
        day = current
    return days


def connection(scenario: Mapping[str, Any], spec: Mapping[str, Any]) -> tuple[str, dict[str, str | None]]:
    """The product's channel and the keys the connection brings.

    A call that names no channel is a hotline call; its number is the call's
    ``channel_identity`` when given, else the scenario's ``customer_phone``.
    A chat that gives a ``channel_identity`` is known by it alone. A Zalo or
    Fanpage chat that gives none is the scenario's customer, known by
    ``customer_phone``: the organisers' SAMPLE-06 continues a hotline call on
    ``zalo_oa`` with no identity and expects the order placed without the
    customer giving a number (2026-11-12: it was treated as a stranger and
    the order was refused for want of a phone). The shop's own web chat
    without an identity is still a stranger until the words bring a key. A
    channel the format does not name is an error, not a guess: a wrong
    channel brings the wrong key.
    """
    name = spec.get("channel") or "hotline"
    if name not in CHANNELS:
        raise ScenarioError(f"{scenario.get('scenario_id')}: unknown channel {name!r}; known: {sorted(CHANNELS)}")
    channel = CHANNELS[name]
    identity = spec.get("channel_identity")
    keys: dict[str, str | None] = {"caller_phone": None, "zalo_id": None, "fb_id": None}
    if channel == "hotline":
        keys["caller_phone"] = identity or scenario.get("customer_phone")
    elif identity and channel == "zalo":
        keys["zalo_id"] = identity
    elif identity and channel == "facebook":
        keys["fb_id"] = identity
    elif not identity and channel in ("zalo", "facebook"):
        keys["caller_phone"] = scenario.get("customer_phone")
    return channel, keys


def customer_turns(spec: Mapping[str, Any]) -> tuple[list[str], str | None]:
    """The turns the system must take, and their input mode."""
    for field in ("customer_turns", "customer_turns_asr"):
        if field in spec:
            value = spec[field]
            if not isinstance(value, list) or any(not isinstance(text, str) or not text.strip() for text in value):
                raise ScenarioError(f"{field} must be a list of non-empty strings")
    clean = spec.get("customer_turns") or []
    if "customer_turns_asr" not in spec:
        if not clean:
            raise ScenarioError("a call needs at least one customer turn")
        return clean, None
    noisy = spec["customer_turns_asr"]
    if not noisy:
        raise ScenarioError("a call needs at least one customer turn")
    if clean and len(noisy) != len(clean):
        raise ScenarioError("customer_turns_asr and customer_turns differ in length")
    mode = spec.get("input_mode") or "asr_transcript"
    if mode not in INPUT_MODES:
        raise ScenarioError(f"input_mode {mode!r} is neither of {sorted(INPUT_MODES)}")
    return noisy, mode


def input_mode_of(value: str | None) -> str | None:
    """The product's input mode for what the harness passes: a mode, or the field the turns come from."""
    if value in INPUT_MODES:
        return value
    return INPUT_FIELDS.get(str(value))


def seed_sessions(raw: Any, *, day: str, channel: str) -> tuple[SeedSession, ...]:
    """``seed_history`` as sessions, oldest first.

    The organisers' shape (answers of 11/2026, part 2 question 2) is a list of
    sessions with ``session_id, date, channel, summary, outcome`` and
    ``facts``: a list of ``{field, value, as_of}``, possibly empty or absent,
    in which case :func:`~.runner.seed` reads the facts from the summary.
    Older shapes are still read: ``{"sessions": [...]}``, one session, facts
    as an object of slots, ``facts_established``, ``call_date`` or
    ``days_before``, a CRM order (``order_id``, ``sku``, ``status``).

    Two values of one field: the later ``as_of`` wins, else the later session
    (organisers' rule); the losing value is not written after the winner. A
    field no slot holds goes into the summary rather than failing the
    scenario. What cannot be placed at all (no date, a session after the
    call, an unknown channel) is refused by name.
    """
    if isinstance(raw, Mapping) and isinstance(raw.get("sessions"), list):
        raw = raw["sessions"]
    items = raw if isinstance(raw, list) else [raw]
    sessions: list[SeedSession] = []
    dated: list[dict[str, str]] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            raise ScenarioError(f"seed_history entry {index} is a {type(item).__name__}, not an object")
        raw_facts = item.get("facts") if "facts" in item else item.get("facts_established")
        session_day = _seed_day(item, day=day, index=index)
        facts, as_of, notes = _seed_facts(raw_facts, session_day=session_day, index=index)
        summary = str(item.get("summary") or _order_summary(item))
        extra = [note for note in notes if note.split(": ", 1)[-1] not in summary]
        if extra:
            summary = (summary.rstrip(". ") + ". " if summary else "") + "; ".join(extra) + "."
        if not facts and not summary:
            raise ScenarioError(f"seed_history entry {index} has neither facts nor a summary: {sorted(item)}")
        sessions.append(SeedSession(
            session_id=seed_session_id(item, index),
            day=session_day,
            channel=(CHANNELS | CRM_SESSION_CHANNELS).get(str(item.get("channel")), str(item.get("channel") or channel)),
            summary=summary,
            outcome=str(item.get("outcome") or "khac"),
            facts=facts,
        ))
        dated.append(as_of)
        if sessions[-1].day > day:
            raise ScenarioError(f"seed_history entry {index} is dated after its call")
        if sessions[-1].channel not in CHANNELS.values():
            raise ScenarioError(f"seed_history entry {index} has an unknown channel")
    order = sorted(range(len(sessions)), key=lambda i: (sessions[i].day, i))
    return _latest_wins([sessions[i] for i in order], [dated[i] for i in order])


def _seed_facts(raw: Any, *, session_day: str, index: int) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """One session's facts as ``(slots, as_of per slot, summary notes)``.

    A list of ``{field, value, as_of}`` keeps, per field, the value with the
    latest ``as_of`` (the session's day when it has none). A field with no
    slot, or a value its slot cannot hold, becomes a note for the summary.
    """
    if raw is None:
        return {}, {}, []
    if isinstance(raw, Mapping):
        entries = [{"field": k, "value": v} for k, v in raw.items()]
    elif isinstance(raw, list):
        entries = raw
    else:
        raise ScenarioError(f"seed_history entry {index}: facts must be a list of {{field, value, as_of}} or an object")
    facts: dict[str, Any] = {}
    as_of: dict[str, str] = {}
    notes: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not entry.get("field") or entry.get("value") in (None, ""):
            raise ScenarioError(f"seed_history entry {index}: a fact needs a field and a value: {entry!r}")
        field_name, value = str(entry["field"]), entry["value"]
        when = _as_of(entry.get("as_of"), default=session_day, index=index)
        slot = SEED_FIELDS.get(field_name, field_name)
        valid, canonical = ontology.coerce(slot, value) if ontology.slot(slot) else (False, value)
        if not valid:
            notes.append(f"{SUMMARY_FIELDS.get(field_name, field_name)}: {value}")
            continue
        if slot not in as_of or when >= as_of[slot]:
            facts[slot], as_of[slot] = canonical, when
    return facts, as_of, notes


def _as_of(raw: Any, *, default: str, index: int) -> str:
    if raw in (None, ""):
        return default
    try:
        return date.fromisoformat(str(raw)[:10]).isoformat()
    except ValueError as error:
        raise ScenarioError(f"seed_history entry {index}: as_of {raw!r} is not a date") from error


def _latest_wins(sessions: list[SeedSession], dated: list[dict[str, str]]) -> tuple[SeedSession, ...]:
    """Drop a value written after the field's winner (latest ``as_of``, then latest session): the ledger supersedes
    in session order, so the winner must be the last value of its field to be written."""
    winner: dict[str, tuple[str, int]] = {}
    for position, as_of in enumerate(dated):
        for slot, when in as_of.items():
            if slot not in winner or (when, position) >= winner[slot]:
                winner[slot] = (when, position)
    kept = []
    for position, session in enumerate(sessions):
        facts = {slot: value for slot, value in session.facts.items() if position <= winner[slot][1]}
        kept.append(replace(session, facts=facts) if facts != dict(session.facts) else session)
    return tuple(kept)


def seed_session_id(item: Mapping[str, Any], index: int) -> str:
    """The id of ``seed_history`` entry *index* (from 1): its own, its order's, else its place."""
    return str(item.get("session_id") or item.get("id") or item.get("order_id") or f"seed-{index}")


def _order_summary(item: Mapping[str, Any]) -> str:
    if not item.get("order_id"):
        return ""
    status = f" ({item['status']})" if item.get("status") else ""
    return f"Đơn {item['order_id']}: {item.get('sku') or 'sản phẩm'}{status}."


def _seed_day(item: Mapping[str, Any], *, day: str, index: int) -> str:
    for key in ("date", "call_date"):
        if item.get(key):
            return date.fromisoformat(str(item[key])[:10]).isoformat()
    if item.get("days_before") is not None:
        return (date.fromisoformat(day) - timedelta(days=int(item["days_before"]))).isoformat()
    raise ScenarioError(f"seed_history entry {index} has no date, call_date or days_before")
