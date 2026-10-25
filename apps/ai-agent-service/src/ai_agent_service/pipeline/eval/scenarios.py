"""Scenarios in the organisers' format, as the evaluation reads them.

``docs/design.md`` section 9.2 and Appendix A; the organisers'
``schemas/scenario_format.md``. The organisers' command loads a directory of
scenarios through here.

- **Files.** Every ``*.json`` whose name does not start with ``_``, sorted, as
  ``eval/reference_eval.py`` reads them.
- **Days.** Call 1 is on ``call_date``, else 2026-10-15 plus ``days_later``;
  each later call on its ``call_date``, else the previous call's day plus
  ``days_later``. Calls are numbered from ``call_1`` without gaps and never go
  back in time, which the harness enforces too
  (``evaluation/harness/eval_harness/preflight.py``).
- **Turns.** The ASR or teencode version, ``customer_turns_asr``, when a call
  has one: the system must take that one (``scenario_format.md``). Its
  ``input_mode`` then labels the turn; a call without it is ``clean``.
- **Keys.** :func:`connection`, the one place the evaluation decides what
  identifies a caller.
- **Prior sessions.** ``seed_history`` is written to the ledger before its
  call (section 9.2, step 2); :func:`seed_sessions` reads the shapes it is
  likely to take and refuses the rest by name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from ...components import clock

#: The organisers' channel names (``scenario_format.md``, and ``web_chat`` from
#: ``handoff_brief.schema.json``) to the product's. Anything else is refused.
CHANNELS = {"hotline": "hotline", "zalo_oa": "zalo", "chat_fanpage": "facebook", "web_chat": "web"}

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
            ready.append(Scenario(path, scenario_id, data, plan(data)))
        except (ScenarioError, KeyError, TypeError, ValueError) as error:
            rejected.append(Rejected(path, scenario_id, f"{type(error).__name__}: {error}"))
    return ready, rejected


def plan(scenario: Mapping[str, Any]) -> tuple[CallPlan, ...]:
    """Every call of *scenario*, in order, with its day, keys, turns and prior sessions."""
    if not isinstance(scenario.get("calls"), dict) or not scenario["calls"]:
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
    names = sorted(scenario["calls"], key=lambda name: int(str(name).split("_")[1]))
    if names != [f"call_{i}" for i in range(1, len(names) + 1)]:
        raise ScenarioError(f"calls must run call_1, call_2, ... without gaps: {names}")
    return names


def call_days(scenario: Mapping[str, Any]) -> dict[str, str]:
    """The day of each call, in call order (Appendix A)."""
    day = date.fromisoformat(clock.REFERENCE_DAY)
    days: dict[str, str] = {}
    for name in call_names(scenario):
        spec = scenario["calls"][name]
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
    """The product's channel and the keys the connection brings (section 9.2).

    A call that names no channel is a hotline call; its number is the call's
    ``channel_identity`` when given, else the scenario's ``customer_phone``.
    A chat is known by its ``channel_identity`` alone: without one it brings
    no key, and the caller is a stranger until the words bring one, as on
    the shop's own web chat. A channel the format does not name is an error,
    not a guess: a wrong channel brings the wrong key.
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
    return channel, keys


def customer_turns(spec: Mapping[str, Any]) -> tuple[list[str], str | None]:
    """The turns the system must take, and their input mode."""
    clean = list(spec.get("customer_turns") or [])
    if "customer_turns_asr" not in spec:
        return clean, None
    noisy = list(spec.get("customer_turns_asr") or [])
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

    The format leaves its shape open, so the likely ones are read: a list of
    sessions, one session, or ``{"sessions": [...]}``. A session has
    ``date`` or ``call_date`` (or ``days_before`` the call on *day*), and
    ``facts`` or ``facts_established`` and/or a ``summary``; ``channel``,
    ``outcome`` and ``session_id`` are optional. A CRM order (``order_id``,
    ``sku``, ``status``) without a summary is summarised from those. Anything
    else is refused, naming what was found, rather than half-loaded.
    """
    if isinstance(raw, Mapping) and isinstance(raw.get("sessions"), list):
        raw = raw["sessions"]
    items = raw if isinstance(raw, list) else [raw]
    sessions = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            raise ScenarioError(f"seed_history entry {index} is a {type(item).__name__}, not an object")
        facts = item.get("facts") if "facts" in item else item.get("facts_established")
        if facts is not None and not isinstance(facts, Mapping):
            raise ScenarioError(f"seed_history entry {index}: facts must be an object of flat slots")
        if not facts and not item.get("summary"):
            raise ScenarioError(f"seed_history entry {index} has neither facts nor a summary: {sorted(item)}")
        sessions.append(SeedSession(
            session_id=seed_session_id(item, index),
            day=_seed_day(item, day=day, index=index),
            channel=CHANNELS.get(str(item.get("channel")), str(item.get("channel") or channel)),
            summary=str(item.get("summary") or _order_summary(item)),
            outcome=str(item.get("outcome") or "khac"),
            facts=dict(facts or {}),
        ))
    return tuple(sorted(sessions, key=lambda s: s.day))


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
