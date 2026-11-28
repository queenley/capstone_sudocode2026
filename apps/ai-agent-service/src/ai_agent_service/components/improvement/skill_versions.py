"""The skills the advisor reads, version by version.

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
    # The rules a change rests on are written at its end, as every line of a skill does ("(PB-02, PB-04)"): the
    # skill's text is where the hot path reads which passages come along (context/skills.py, learned_cites). A change
    # that kept them only in ``cites`` was published without its rule on 2026-11-12 and was not followed.
    unnamed = [str(code) for code in patch.get("cites") or [] if code and str(code) not in text]
    if unnamed and part == "body":
        text = f"{text.rstrip('.')} ({', '.join(unnamed)})."
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


def publish(patches: Sequence[Mapping[str, Any]], *, reviewer: str, note: str = "", folder: Path | None = None,
            activate: bool = True) -> int:
    """The version in force with *patches*, as the next version; never edits a file that exists.

    ``activate=False`` writes the version as a candidate only: the weekly round measures it with
    ``run_eval.py --skills-version`` before an admin switches it on (:func:`activate`)."""
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
    if activate:
        atomic_text(where / skill_book.ACTIVE, json.dumps({"version": target}))
    review.log("publish_skills" if activate else "candidate_skills", version=target, previous=current,
               reviewer=reviewer, note=note,
               patches=[{k: p.get(k) for k in ("skill", "part", "find", "text", "cites")} for p in patches])
    return target


def activate(version: int, *, reviewer: str, note: str = "", folder: Path | None = None) -> int:
    """Switch a candidate written by ``publish(activate=False)`` on; returns the version it replaces.

    The running service reads the skills when it starts (``components/context/skills.py``), so it serves the new
    version after a restart."""
    where = folder or skill_book.versions_dir()
    if version not in _versions(where):
        raise ValueError(f"No skills version {version}")
    if not reviewer.strip():
        raise ValueError("Switching a version on needs the reviewer")
    previous = active(where)
    atomic_text(where / skill_book.ACTIVE, json.dumps({"version": version}))
    review.log("activate_skills", version=version, previous=previous, reviewer=reviewer, note=note)
    return previous


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


# ── what an admin reads and writes in /admin (Cải tiến hằng tuần, Skills) ─────────────────────────────────────

#: A skill an admin writes may be longer than one Reflection grows: a person writes the whole procedure.
ADMIN_MAX_BODY = 6000
SKILL_NAME = re.compile(r"^[a-z][a-z0-9-]{1,47}$")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def read_version(version: int, folder: Path | None = None) -> dict[str, Any]:
    """The skills of *version*: 0 is the file in the prompts, a later one ``data/skills/v<N>.yaml``."""
    where = folder or skill_book.versions_dir()
    if version == 0:
        from ...config.config_manager import load_prompt_yaml

        return load_prompt_yaml("advisor/skills.yaml")
    path = where / f"v{version}.yaml"
    if not path.is_file():
        raise ValueError(f"No skills version {version}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def versions(folder: Path | None = None) -> list[dict[str, Any]]:
    """Every version, newest first: when it was written, by whom, why, and which skills it changed from the one
    before it (the improvement log says who and why; a version Reflection wrote names its round's reviewer)."""
    where = folder or skill_book.versions_dir()
    notes: dict[int, dict[str, Any]] = {}
    path = review.log_path()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("action") in ("publish_skills", "candidate_skills", "admin_skills") and row.get("version") is not None:
                notes[int(row["version"])] = row
    current = active(where)
    out = [{"version": 0, "active": current == 0, "saved_at": None, "by": "gốc (config/prompts)", "note": "",
            "changed": []}]
    previous = read_version(0, where)
    for number in _versions(where):
        book = read_version(number, where)
        changed = sorted(name for name in set(book) | set(previous) if book.get(name) != previous.get(name))
        row = notes.get(number, {})
        mtime = (where / f"v{number}.yaml").stat().st_mtime
        from datetime import datetime, timezone

        out.append({"version": number, "active": current == number,
                    "saved_at": row.get("at") or datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                    "by": row.get("reviewer") or "", "note": row.get("note") or "", "changed": changed})
        previous = book
    return list(reversed(out))


def _checked(name: str, skill: Mapping[str, Any]) -> dict[str, Any]:
    if not SKILL_NAME.match(name):
        raise ValueError(f"Tên skill {name!r}: chữ thường, số và gạch ngang, 2-48 ký tự")
    description = " ".join(str(skill.get("description") or "").split())
    body = str(skill.get("body") or "").strip()
    done_on = [str(tool).strip() for tool in skill.get("done_on") or [] if str(tool).strip()]
    if not description or not body:
        raise ValueError(f"{name}: cần cả mô tả và nội dung")
    if len(description) > MAX_DESCRIPTION:
        raise ValueError(f"{name}: mô tả dài quá {MAX_DESCRIPTION} ký tự (model đọc mô tả của mọi skill mỗi lượt)")
    if len(body) > ADMIN_MAX_BODY:
        raise ValueError(f"{name}: nội dung dài quá {ADMIN_MAX_BODY} ký tự")
    bad = [tool for tool in done_on if not TOOL_NAME.match(tool)]
    if bad:
        raise ValueError(f"{name}: tên tool không hợp lệ: {', '.join(bad)}")
    return {"description": description, "done_on": done_on, "body": body}


def edit(changes: Mapping[str, Mapping[str, Any] | None], *, reviewer: str, note: str = "", activate: bool = True,
         folder: Path | None = None) -> int:
    """A person's edit of the skills in force as the next version: each name maps to its new skill, or to None to
    take it out. Never edits a file that exists; ``activate=False`` keeps it as a candidate to switch on later."""
    if not reviewer.strip():
        raise ValueError("Sửa skill cần tên người sửa")
    if not changes:
        raise ValueError("Không có thay đổi")
    where = folder or skill_book.versions_dir()
    where.mkdir(parents=True, exist_ok=True)
    current = active(where)
    book = dict(skill_book.read_book(where))
    for name, skill in changes.items():
        if skill is None:
            if name not in book:
                raise ValueError(f"Không có skill {name}")
            book.pop(name)
        else:
            book[name] = _checked(name, skill)
    if not book:
        raise ValueError("Phải còn ít nhất một skill")
    target = max([current, *_versions(where)]) + 1
    atomic_text(where / f"v{target}.yaml", yaml.safe_dump(book, allow_unicode=True, sort_keys=False, width=110))
    if activate:
        atomic_text(where / skill_book.ACTIVE, json.dumps({"version": target}))
    review.log("admin_skills", version=target, previous=current, reviewer=reviewer, note=note, activated=activate,
               skills=sorted(changes), removed=sorted(name for name, skill in changes.items() if skill is None))
    return target
