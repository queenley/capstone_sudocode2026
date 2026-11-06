"""The advisor's context, in priority order. ``docs/design.md`` section 4.4.

Only the playbook is optional. Everything else is what the rules tell the model to rely on: rule 3 answers from the
knowledge passages, an order uses a code from the products block, and with those cut the model answers from nothing.
They were cut, and silently, while the rules alone filled the budget. The target is therefore soft, and what a turn
loses is reported (``ContextPack.cut``, the run's diagnostics).

Tokens use a four-character estimate, not the provider's billed count.
"""

from __future__ import annotations

from typing import NamedTuple, Sequence

#: Sections that are never cut, whatever the allowance.
PROTECTED = frozenset({"rules", "packs", "warnings", "lane", "products", "orders", "brief", "summary", "knowledge",
                       "tool_results", "opening", "blocked", "call_state"})


class Section(NamedTuple):
    name: str
    text: str


class ContextPack(NamedTuple):
    text: str
    tokens: int
    kept: tuple[str, ...]
    #: Names of the sections that did not fit.
    cut: tuple[str, ...]


def tokens(text: str) -> int:
    return (len(text) + 3) // 4


def assemble(sections: Sequence[Section], *, max_tokens: int) -> ContextPack:
    """Keep what fits, top first; protected sections always."""
    kept: list[Section] = []
    cut: list[str] = []
    used = sum(tokens(s.text) for s in sections if s.name in PROTECTED and s.text.strip())
    for section in sections:
        if not section.text.strip():
            continue
        cost = tokens(section.text)
        if section.name in PROTECTED or used + cost <= max_tokens:
            kept.append(section)
            if section.name not in PROTECTED:
                used += cost
        else:
            cut.append(section.name)
    return ContextPack("\n\n".join(s.text for s in kept), used, tuple(s.name for s in kept), tuple(cut))
