"""The write gate: what gets remembered, and what does not. ``docs/design.md`` section 5.4.

The MemoryAgent proposes candidates; these doors, code only, decide. A joke
never reaches the ledger because a model was in a good mood.

1. drop noise: a slot the ontology does not know, an empty value, a
   candidate the extractor itself doubts (a joke, a hypothetical);
2. the cap on open notes per customer;
3. type and plausible range: a budget is not 5 đồng, a room is not 2.500 m²;
4. who wins, by the kind of slot:

| Kind | Who wins |
|---|---|
| preference, need | the customer, newest word wins ("thôi anh lấy màu trắng") |
| business event | the tool; the customer's contrary claim is kept as said, the fact marked disputed |
| past event | the system record |

:func:`settle` applies the win rule inside one call, before the ledger is
consulted; :func:`check` then measures each survivor against what the ledger
already holds.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, NamedTuple, Sequence

from .ontology import coerce, slot
from ..intake import pii

Door = Literal["noise", "under_cap", "valid_format", "wins"]

#: Hard cap on open notes per customer (section 5.2).
OPEN_NOTE_CAP = 10

#: Below this the extractor is guessing: a joke, a hypothetical, a third
#: party's need. Rules give 1.0; a model gives its own estimate.
MIN_CONFIDENCE = 0.6

RANGES: dict[str, tuple[float, float]] = {
    "budget_vnd": (100_000, 1_000_000_000),
    "price_quoted_vnd": (1_000, 1_000_000_000),
    "competitor_price_vnd": (1_000, 1_000_000_000),
    "room_area_m2": (3, 500),
    "child_age_months": (0, 72),
    "quantity": (1, 100),
}

#: Slots whose value is a record of what happened: a customer saying
#: otherwise is a claim, never the fact.
RECORDS = ("business_event", "past_event")


class Candidate(NamedTuple):
    """One thing the extractor believes the call established."""

    slot: str | None  # None for an open note
    value: Any
    #: Who said it: "customer" (their words), "agent" (the shop's words, for
    #: commitments and objection handling), "tool" (a tool's result) or
    #: "system" (the call's own outcome when no tool settled it).
    said_by: Literal["customer", "agent", "tool", "system"]
    turn: int
    confidence: float = 1.0
    #: Which extractor proposed it; part of the ledger's idempotency key.
    extractor: str = "rules-0.2"


class Verdict(NamedTuple):
    passed: bool
    stopped_at: Door | None = None
    disputed: bool = False


def settle(candidates: Sequence[Candidate]) -> list[Candidate]:
    """One call's candidates after the win rule: one value per slot, plus contrary claims.

    In turn order: the newest word wins a preference; for a record (business
    or past event) the newest tool or system value wins, and a customer
    statement that differs from it is kept beside it, for :func:`check` to
    mark disputed ("phòng 20 mét... à không, 25" keeps 25; "hôm trước em báo
    4 triệu rưỡi" never replaces the quote the tool recorded). Open notes are
    kept once each.
    """
    ordered = [c for _, c in sorted(enumerate(candidates), key=lambda pair: (pair[1].turn, pair[0]))]
    winners: dict[str, Candidate] = {}
    claims: dict[tuple[str, str], Candidate] = {}
    notes: dict[str, Candidate] = {}
    for candidate in ordered:
        quality = check(candidate, [], open_notes=0)
        if not quality.passed and quality.stopped_at != "wins":
            continue
        if candidate.slot is None:
            notes[str(candidate.value)] = candidate
            continue
        spec = slot(candidate.slot)
        if spec is not None and spec.kind in RECORDS and candidate.said_by == "customer":
            claims[(candidate.slot, repr(candidate.value))] = candidate
            continue
        previous = winners.get(candidate.slot)
        priority = ({"tool": 3, "system": 2, "agent": 1} if spec and spec.kind in RECORDS
                    else {"customer": 3, "tool": 2, "system": 1, "agent": 0})
        if previous is None or priority.get(candidate.said_by, 0) >= priority.get(previous.said_by, 0):
            winners[candidate.slot] = candidate
    contrary = [c for (name, _), c in claims.items() if name not in winners or winners[name].value != c.value]
    return [*winners.values(), *contrary, *notes.values()]


def check(
    candidate: Candidate,
    current: list[dict[str, Any]],
    *,
    open_notes: int,
    settled: Mapping[str, Candidate] | None = None,
) -> Verdict:
    """Doors 1 to 4, in order.

    *current* is what the ledger holds today; *settled* the call's own
    winners by slot (from :func:`settle`), against which a customer's claim
    about a record is measured when the ledger has nothing yet.
    """
    if candidate.value in (None, "", [], {}) or candidate.confidence < MIN_CONFIDENCE:
        return Verdict(False, "noise")
    if candidate.said_by != "tool" and isinstance(candidate.value, str) and pii.mask(candidate.value) != candidate.value:
        return Verdict(False, "noise")
    if candidate.slot is None:
        return Verdict(open_notes < OPEN_NOTE_CAP, None if open_notes < OPEN_NOTE_CAP else "under_cap")
    spec = slot(candidate.slot)
    if spec is None:
        return Verdict(False, "noise")
    ok, value = coerce(candidate.slot, candidate.value)
    if not ok or value != candidate.value or isinstance(value, bool) != isinstance(candidate.value, bool):
        return Verdict(False, "valid_format")
    bounds = RANGES.get(candidate.slot)
    if bounds is not None and not bounds[0] <= float(value) <= bounds[1]:
        return Verdict(False, "valid_format")
    if spec.kind in RECORDS and candidate.said_by == "customer":
        recorded = (settled or {}).get(candidate.slot)
        held = next((f for f in current if f["slot"] == candidate.slot and f["status"] == "active"), None)
        reference = recorded.value if recorded is not None and recorded.said_by != "customer" else (
            held["value"] if held is not None else None)
        if reference is None or reference == candidate.value:
            # Nothing to contradict, or it agrees: a customer never establishes a record.
            return Verdict(False, "wins")
        return Verdict(True, disputed=True)
    return Verdict(True)
