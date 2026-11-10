"""The skills the advisor reads, version by version. ``docs/design.md`` section 10.3.

Reflection changes skills, one sentence at a time, never by writing a skill again: a rewrite shortens it and loses
what it held. Version 0 is ``config/prompts/agent/advisor/skills.yaml``; each published change writes
``data/skills/v<N>.yaml`` and points ``data/skills/active.json`` at it. Going back is changing the pointer. The
advisor reads the version at startup, so a run started after the change runs on it.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from ..context import skills as skill_book
from . import review
from .storage import atomic_text

#: A skill may grow this much in all: past it, the change is a skill of its own, for a person to write.
MAX_BODY = 2400
MAX_DESCRIPTION = 220


def apply(book: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """*book* with one sentence changed, and the situation it is for added to the description (``when``) when the
    description does not name it yet; raises ``ValueError`` on a change that cannot apply exactly."""
    changed = copy.deepcopy(dict(book))
    name, part = str(patch.get("skill")), str(patch.get("part"))
    if name not in changed or part not in ("body", "description"):
        raise ValueError(f"No {part} of a skill named {name}")
    text, find = str(patch.get("text") or "").strip(), str(patch.get("find") or "").strip()
    if not text:
        raise ValueError("An empty change")
    current = str(changed[name][part])
    if find:
        if current.count(find) != 1:
            raise ValueError(f"The sentence to replace is not once in {name}.{part}")
        updated = current.replace(find, text)
    else:  # a body written one instruction a line gets a line of its own
        updated = f"{current}\n{text}" if "\n- " in current or current.startswith("- ") else f"{current} {text}"
    limit = MAX_BODY if part == "body" else MAX_DESCRIPTION
    if len(updated) > limit:
        raise ValueError(f"{name}.{part} would pass {limit} characters")
    changed[name][part] = updated
    when = str(patch.get("when") or "").strip().rstrip(".")
    if when and part == "body":
        description = f"{changed[name]['description'].rstrip()} Cả khi {when[0].lower()}{when[1:]}."
        if len(description) > MAX_DESCRIPTION:
            raise ValueError(f"{name}.description would pass {MAX_DESCRIPTION} characters")
        changed[name]["description"] = description
    return changed


def _versions(folder: Path) -> list[int]:
    return sorted(int(m.group(1)) for p in folder.glob("v*.yaml") if (m := re.fullmatch(r"v(\d+)\.yaml", p.name)))


def active(folder: Path | None = None) -> int:
    return skill_book.active_version(folder or skill_book.versions_dir())


def publish(patches: Sequence[Mapping[str, Any]], *, reviewer: str, note: str = "", folder: Path | None = None) -> int:
    """The version in force with *patches*, as the next version; never edits a file that exists."""
    if not reviewer.strip():
        raise ValueError("Publishing needs the reviewer who approved the change")
    where = folder or skill_book.versions_dir()
    where.mkdir(parents=True, exist_ok=True)
    current = active(where)
    book = skill_book.read_book(where)
    for patch in patches:
        book = apply(book, patch)
    target = max([current, *_versions(where)]) + 1
    atomic_text(where / f"v{target}.yaml", yaml.safe_dump(book, allow_unicode=True, sort_keys=False, width=110))
    atomic_text(where / skill_book.ACTIVE, json.dumps({"version": target}))
    review.log("publish_skills", version=target, previous=current, reviewer=reviewer, note=note,
               patches=[{k: p.get(k) for k in ("skill", "part", "find", "text", "cites")} for p in patches])
    return target


def rollback(to: int, *, reviewer: str, reason: str, folder: Path | None = None) -> int:
    where = folder or skill_book.versions_dir()
    if to != 0 and to not in _versions(where):
        raise ValueError(f"No skills version {to}")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Going back needs a reviewer and a reason")
    previous = active(where)
    where.mkdir(parents=True, exist_ok=True)
    atomic_text(where / skill_book.ACTIVE, json.dumps({"version": to}))
    review.log("rollback_skills", version=to, previous=previous, reviewer=reviewer, reason=reason)
    return previous
