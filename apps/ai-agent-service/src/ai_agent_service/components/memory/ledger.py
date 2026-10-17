"""Deciding the write for a candidate that passed the gate. ``docs/design.md`` section 5.4, step ``commit``.

The ledger is never overwritten and never deleted from (section 5.3). For a
closed slot the operation follows from the win rule, so it is code:

- nothing held for the slot: **add**;
- the same value held: **skip**;
- another value held and the new one wins: **update**, which closes the old
  row and opens the new one;
- a customer contradicting a recorded fact: **add** the claim as disputed and
  keep the fact.

An open note is added unless the same note is already held. Every decision
carries its source ``{call_id, call, turn, channel, said_by,
extractor_version}`` and, from the ontology, when it lapses. Writing goes
through ``memory.commit_facts`` under the ``memory_writer`` role, which is
the one path into the ledger; the server decides again under its lock, so a
decision made on a profile another call has since changed is still applied
to the facts as they are.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal, NamedTuple

from .gate import Candidate, Verdict
from .ontology import NOTE_SLOT, slot

Operation = Literal["add", "update", "invalidate", "skip"]


class Decision(NamedTuple):
    operation: Operation
    slot: str
    value: Any
    kind: str
    source: dict[str, Any]
    replaces: str | None = None
    disputed: bool = False
    valid_to: str | None = None
    confidence: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return self._asdict()


def plan(candidate: Candidate, verdict: Verdict, current: list[dict[str, Any]], *, source: dict[str, Any], on: str) -> Decision:
    """The operation for one candidate that passed the gate."""
    spec = slot(candidate.slot or "")
    kind = spec.kind if spec else "open_note"
    name = candidate.slot or NOTE_SLOT
    valid_to = None
    if spec and spec.ttl_days:
        valid_to = (date.fromisoformat(on) + timedelta(days=spec.ttl_days)).isoformat()
    source = {**source, "turn": candidate.turn, "said_by": candidate.said_by, "extractor_version": candidate.extractor}
    common = dict(slot=name, value=candidate.value, kind=kind, source=source,
                  valid_to=valid_to, confidence=candidate.confidence)
    if kind == "open_note":
        known = any(f["slot"] == NOTE_SLOT and f["status"] == "active" and f["value"] == candidate.value for f in current)
        return Decision("skip" if known else "add", **common)
    held = next((f for f in current if f["slot"] == candidate.slot and f["status"] == "active"), None)
    if verdict.disputed:
        return Decision("add", disputed=True, **common)
    if held is None:
        return Decision("add", **common)
    if held["value"] == candidate.value:
        return Decision("skip", **common)
    return Decision("update", replaces=held["fact_id"], **common)
