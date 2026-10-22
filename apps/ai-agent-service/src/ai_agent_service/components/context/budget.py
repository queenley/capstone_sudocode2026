"""The advisor's context, in priority order, cut from the bottom. ``docs/design.md`` section 4.4.

1. hard rules and tone (never cut);
2. ``stale_warnings`` (never cut);
3. the lane's instruction;
4. the brief lines;
5. ``working_summary`` (the last four turns travel as messages);
6. the turn's knowledge passages, retrieved by ``load_context``;
7. the playbook entries of the situation;
8. tool results already gathered, when a draft is regenerated;
9. why the previous draft was blocked.

Tokens use a four-character estimate, not the provider's billed count.
The target is soft: required evidence survives; optional text uses the remainder.
"""

from __future__ import annotations

from typing import NamedTuple, Sequence

#: Sections that are never cut, whatever the allowance.
PROTECTED = frozenset({"rules", "warnings", "lane", "brief", "tool_results", "opening", "blocked"})


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
