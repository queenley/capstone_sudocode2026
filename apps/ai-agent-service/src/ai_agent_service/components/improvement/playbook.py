"""Reflection, second half: from many cards to one entry the advisor reads. ``docs/design.md`` 10.3.

1. **Consolidate** (:func:`consolidate`), in code: of the hints that fixed a
   failure, the one verified with the most customers becomes the candidate.
   No model rewrites the playbook: a block rewritten every round shrinks and
   loses detail (ACE, Zhang et al. 2025), so entries change one at a time.
2. **Verify** (``pipeline/improve``): the candidate is played on every call of
   the round that failed the same way. It is proposed only when it fixed the
   failure with at least ``MIN_SUPPORT`` different customers and broke
   nothing else; the counts travel with it (:attr:`Entry.counts`).
3. **Approve** (:mod:`.review`): a person, never the agent that wrote it.
4. **Apply** (:mod:`.versions`): the entry joins ``data/kb/v<N+1>.jsonl`` and
   ``kb.search`` finds it by its words in a call, like any passage.
5. **Watch**: the next round counts, per entry, the calls it was shown in and
   whether the failure it targets came back; a harmful entry is revoked.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Sequence

from .lessons import Card, Hint, screen, support


@dataclass(frozen=True)
class Entry:
    """A playbook entry before review: the hint, what it targets, and the evidence for it."""

    chunk_id: str
    hint: Hint
    failure_code: str
    persona: str | None
    #: Where the hint was verified: scenario, call, customer.
    evidence: tuple[dict[str, Any], ...]
    #: ``{"customers_fixed", "calls_tried", "calls_broken"}`` once verified.
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.hint.trigger

    @property
    def text(self) -> str:
        return render(self.hint)

    def kb_entry(self, *, round_name: str, approved_by: str) -> dict[str, Any]:
        """The line of ``data/kb/v<N>.jsonl`` (``components.knowledge.corpus.entry_chunk``)."""
        return {
            "chunk_id": self.chunk_id, "source": "playbook", "title": self.title, "text": self.text,
            "persona": self.persona, "failure_code": self.failure_code, "hint": self.hint.to_json(),
            "evidence": list(self.evidence), "counts": dict(self.counts), "round": round_name,
            "approved_by": approved_by,
        }


def render(hint: Hint) -> str:
    """The entry as the advisor reads it among the passages of a turn."""
    parts = [f"Khi {hint.trigger.strip().rstrip('.')}: {hint.do.strip().rstrip('.')}."]
    if hint.dont.strip():
        parts.append(f"Không {hint.dont.strip().removeprefix('Không ').removeprefix('không ').rstrip('.')}.")
    if hint.sample_line.strip():
        parts.append(f"Câu mẫu: «{hint.sample_line.strip()}»")
    if hint.cites:
        parts.append(f"(áp dụng {', '.join(hint.cites)})")
    return " ".join(parts)


def entry_id(code: str, hint: Hint) -> str:
    """``LP-<hash>``: a learned playbook entry, never a code of the organisers' corpus."""
    return "LP-" + hashlib.sha256(f"{code}|{hint.key()}".encode()).hexdigest()[:8].upper()


def consolidate(pool: Sequence[Card], code: str) -> Entry | None:
    """The candidate entry for *code*: the hint verified with the most customers, or None.

    Its evidence is the cards that verified exactly this hint. Whether it
    fixes the others is for the verification run to say, not for this count.
    """
    voters = support(pool, code)
    if not voters:
        return None
    by_hint: dict[str, list[Card]] = {}
    for card in voters:
        by_hint.setdefault(card.hint.key(), []).append(card)
    best = sorted(by_hint.values(), key=lambda group: (-len(group), len(group[0].hint.key())))[0]
    hint = best[0].hint
    if screen(hint):
        return None
    personas = Counter(card.failure.persona for card in voters if card.failure.persona)
    persona = personas.most_common(1)[0][0] if len(personas) == 1 else None
    evidence = tuple({"scenario_id": c.failure.scenario_id, "call": c.failure.call, "customer": c.failure.customer}
                     for c in best)
    return Entry(chunk_id=entry_id(code, hint), hint=hint, failure_code=code, persona=persona, evidence=evidence)
