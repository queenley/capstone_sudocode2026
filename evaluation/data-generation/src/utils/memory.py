"""What the agent is expected to know at the start of a call."""
from __future__ import annotations

from datetime import date
from typing import Any

from src.schemas.scenario import Scenario
from src.schemas.slots import SLOTS, STALE_AFTER_DAYS


def speaker_of(scenario: Scenario, call_name: str) -> str:
    """Customer actually speaking in a call (differs from the scenario customer on a shared phone)."""
    return scenario.calls[call_name].speaker_customer_id or scenario.customer_id or scenario.customer_phone


def known_facts_before(scenario: Scenario, call_name: str) -> dict[str, Any]:
    """CRM seed facts + ``facts_established`` of earlier calls BY THE SAME SPEAKER (latest value wins).

    Facts of the other person on a shared phone are deliberately excluded: using
    them is the memory-poisoning failure the scenario tests.
    """
    speaker = speaker_of(scenario, call_name)
    known: dict[str, Any] = {}
    for name, call in scenario.ordered_calls():
        if speaker_of(scenario, name) != speaker:
            if name == call_name:
                break
            continue
        for item in call.seed_history:
            if item.get("customer_id", speaker) == speaker:
                known.update(item.get("facts") or {})
        if name == call_name:
            break
        known.update(call.facts_established)
    return known


def stale_slots_before(scenario: Scenario, call_name: str) -> list[str]:
    """Return non-durable facts whose latest known value is older than the TTL."""
    target = scenario.calls[call_name]
    speaker = speaker_of(scenario, call_name)
    latest: dict[str, date] = {}

    for name, call in scenario.ordered_calls():
        if speaker_of(scenario, name) != speaker:
            if name == call_name:
                break
            continue
        for item in call.seed_history:
            if item.get("customer_id", speaker) == speaker:
                recorded = date.fromisoformat(item["date"])
                for slot in (item.get("facts") or {}):
                    latest.setdefault(slot, recorded)
        if name != call_name:
            for slot in call.facts_established:
                latest[slot] = call.call_date
        if name == call_name:
            break

    return sorted(slot for slot, recorded in latest.items()
                  if slot in SLOTS and slot not in {"order_id", "owned_sku"}
                  and (target.call_date - recorded).days > STALE_AFTER_DAYS)
