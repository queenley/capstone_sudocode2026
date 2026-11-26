"""An improved agent, kept: what learning rounds approved, merged by code onto the agent in force today.

A round leaves two things behind (``evaluation/runs/<round>/``): the knowledge version it published
(``learned/kb/v<N>.jsonl``, only the Knowledge Gap Loop entries) and the skills version it published
(``learned/skills/v<N>.yaml``). The skills file is a snapshot of the whole skill book on the day the round learned,
so installing it as it is also brings back every skill as it read that day: on 2026-11-18 the snapshot of
``reflect-warranty-8`` still held the 16/11 ``place-order`` line that made the agent ask for a payment before
ordering, which had been fixed since. What a round approved is the change, not the snapshot: the ``patches`` of
its ``publish_skills`` rows in ``improvement/improvement-log.jsonl``. A build applies those, in order, to the skill
book of today (version 0, ``config/prompts/agent/advisor/skills.yaml``) with :func:`skill_versions.apply`; a change
that no longer applies exactly stops the build for a person.

A build is kept in ``data/agents/<name>/``: ``skills.yaml`` (the merged book), ``kb.jsonl`` (the knowledge
entries) and ``manifest.json`` (where each part came from, and the digest of the version-0 skills it was merged
onto). :func:`install` puts the two files where ``run_eval.py --kb-version/--skills-version`` and the service read
versions, reusing a version whose content is the same and never rewriting one; :func:`stale` says when the skills
of today are no longer the ones the build was merged onto, so it must be built again.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from ...config.config_manager import PROMPTS_DIR, kb_dir, load_prompt_yaml
from ..context import skills as skill_book
from ..knowledge.corpus import version_file
from . import review, skill_versions, versions
from .storage import atomic_text

MANIFEST = "manifest.json"
SKILLS_FILE = "skills.yaml"
KB_FILE = "kb.jsonl"
#: The situation a change was for, which ``apply`` adds to a skill's description and the log does not keep.
WHEN = re.compile(r"Cả khi ([^.]+)\.")


def agents_dir() -> Path:
    """``data/agents``, beside the knowledge and skills versions."""
    return kb_dir().parent / "agents"


def base_skills_path() -> Path:
    return PROMPTS_DIR / "advisor" / "skills.yaml"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def learned_patches(round_dir: Path, base: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The skill changes *round_dir*'s round published, in order, each with the reviewer of its version.

    The situation (``when``) a change added to its skill's description is not in the log: it is read back from the
    round's snapshot, as the "Cả khi …" sentences that *base* does not have, and given to the skill's last change.
    """
    log = round_dir / "improvement" / "improvement-log.jsonl"
    if not log.is_file():
        raise FileNotFoundError(f"{log} does not exist: not a learning round's folder")
    published = [row for row in _rows(log) if row.get("action") == "publish_skills"]
    patches = [{**patch, "reviewer": row.get("reviewer"), "round": round_dir.name, "version": row.get("version")}
               for row in published for patch in row.get("patches") or []]
    if not published:
        return []
    snapshot_path = round_dir / "learned" / "skills" / f"v{published[-1].get('version')}.yaml"
    snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.is_file() else {}
    for name in {p["skill"] for p in patches}:
        said = str((snapshot.get(name) or {}).get("description") or "")
        known = str((base.get(name) or {}).get("description") or "")
        extra = [m.group(1) for m in WHEN.finditer(said) if m.group(0) not in known]
        last = [p for p in patches if p["skill"] == name and p.get("part") == "body"][-1:]
        if extra and last and not last[0].get("when"):
            last[0]["when"] = extra[0]
    return patches


def merge(base: Mapping[str, Any], patches: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """*base* with every patch applied in order; raises ``ValueError`` naming each one that no longer applies."""
    book = dict(base)
    failed = []
    for patch in patches:
        try:
            book = skill_versions.apply(book, patch)
        except ValueError as error:
            failed.append(f"{patch.get('round')} v{patch.get('version')} {patch.get('skill')}.{patch.get('part')}: {error}")
    if failed:
        raise ValueError("These learned changes no longer apply to today's skills; a person must restate them:\n  "
                         + "\n  ".join(failed))
    return book


def knowledge_file(version: int, round_dir: Path | None = None, directory: Path | None = None) -> Path:
    """Knowledge version *version*'s file: as *round_dir*'s round learned it, else as committed in ``data/kb``.
    Its bytes are kept as they are, so :func:`install` finds the committed version and does not write another."""
    path = (round_dir / "learned" / "kb" / f"v{version}.jsonl") if round_dir is not None \
        else version_file(directory or kb_dir(), version)
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist: the version must be the one its round learned")
    versions.entries(version, path.parent)  # checks every entry
    return path


def build(name: str, *, kb_version: int | None, kb_round: Path | None, skills_rounds: Sequence[Path], reviewer: str,
          commit: str | None = None, folder: Path | None = None, base_path: Path | None = None) -> dict[str, Any]:
    """Write ``data/agents/<name>/``; a build that exists is never rewritten (build a new name)."""
    if not reviewer.strip():
        raise ValueError("A build needs the person who asked for it")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,47}", name):
        raise ValueError("A build's name is lowercase letters, digits and hyphens")
    target = (folder or agents_dir()) / name
    if target.exists():
        raise FileExistsError(f"{target} exists; a build is never rewritten")
    base_path = base_path or base_skills_path()
    base = yaml.safe_load(base_path.read_text(encoding="utf-8")) if base_path != base_skills_path() \
        else load_prompt_yaml("advisor/skills.yaml")
    patches = [patch for round_dir in skills_rounds for patch in learned_patches(round_dir, base)]
    book = merge(base, patches)
    kb_text = knowledge_file(kb_version, kb_round).read_bytes() if kb_version is not None else b""
    ids = [json.loads(line)["chunk_id"] for line in kb_text.decode("utf-8").splitlines() if line.strip()]
    target.mkdir(parents=True)
    atomic_text(target / SKILLS_FILE, yaml.safe_dump(book, allow_unicode=True, sort_keys=False, width=110))
    (target / KB_FILE).write_bytes(kb_text)
    manifest = {
        "name": name,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "built_by": reviewer,
        "commit": commit,
        "base": {"skills": "config/prompts/agent/advisor/skills.yaml", "skills_sha256": digest(base_path)},
        "knowledge": {"from_round": kb_round.name if kb_round else None, "learned_version": kb_version,
                      "entries": ids, "sha256": digest(target / KB_FILE)},
        "skills": {"from_rounds": [r.name for r in skills_rounds], "sha256": digest(target / SKILLS_FILE),
                   "patches": [{k: p.get(k) for k in ("round", "version", "reviewer", "skill", "part", "find", "text",
                                                       "cites", "when")} for p in patches]},
    }
    atomic_text(target / MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    review.log("build_agent", name=name, reviewer=reviewer, knowledge=manifest["knowledge"],
               skills={k: manifest["skills"][k] for k in ("from_rounds", "sha256")})
    return manifest


def read(name: str, folder: Path | None = None) -> dict[str, Any]:
    path = (folder or agents_dir()) / name / MANIFEST
    if not path.is_file():
        raise FileNotFoundError(f"No build named {name} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def stale(manifest: Mapping[str, Any], base_path: Path | None = None) -> bool:
    """True when today's version-0 skills are not the ones the build merged onto: build it again."""
    return digest(base_path or base_skills_path()) != manifest["base"]["skills_sha256"]


def _same_or_next(content: bytes, folder: Path, pattern: str, existing: Sequence[int]) -> tuple[int, bool]:
    """The version whose file holds *content*, else the next free one; and whether it must be written."""
    for number in existing:
        if number and (folder / pattern.format(number)).read_bytes() == content:
            return number, False
    return max([0, *existing]) + 1, True


def install(name: str, *, folder: Path | None = None, kb_folder: Path | None = None,
            skills_folder: Path | None = None, base_path: Path | None = None) -> dict[str, int]:
    """Put the build's two files where versions are read; returns ``{"kb_version", "skills_version"}``.

    Nothing is switched on: ``knowledge.yaml`` and ``data/skills/active.json`` keep pointing where they did, so the
    service still runs the original agent until a run passes the two versions or an admin activates them."""
    manifest = read(name, folder)
    if stale(manifest, base_path):
        raise ValueError(f"Build {name} was merged onto other version-0 skills than today's: build it again "
                         "(improve build-agent with the same rounds and a new name)")
    source = (folder or agents_dir()) / name
    kb_folder = kb_folder or kb_dir()
    skills_folder = skills_folder or skill_book.versions_dir()
    kb_bytes = (source / KB_FILE).read_bytes()
    skills_bytes = (source / SKILLS_FILE).read_bytes()
    kb_version, write_kb = (0, False) if not kb_bytes.strip() else _same_or_next(
        kb_bytes, kb_folder, "v{}.jsonl", versions.versions(kb_folder))
    if write_kb:
        kb_folder.mkdir(parents=True, exist_ok=True)
        if version_file(kb_folder, kb_version).exists():
            raise FileExistsError(f"Knowledge version {kb_version} exists")
        atomic_text(version_file(kb_folder, kb_version), kb_bytes.decode("utf-8"))
    skill_numbers = sorted(int(m.group(1)) for p in skills_folder.glob("v*.yaml")
                           if (m := re.fullmatch(r"v(\d+)\.yaml", p.name))) if skills_folder.is_dir() else []
    skills_version, write_skills = (0, False) if not manifest["skills"]["patches"] else _same_or_next(
        skills_bytes, skills_folder, "v{}.yaml", skill_numbers)
    if write_skills:
        skills_folder.mkdir(parents=True, exist_ok=True)
        atomic_text(skills_folder / f"v{skills_version}.yaml", skills_bytes.decode("utf-8"))
    review.log("install_agent", name=name, kb_version=kb_version, skills_version=skills_version,
               written={"kb": write_kb, "skills": write_skills})
    return {"kb_version": kb_version, "skills_version": skills_version}


def run_args(installed: Mapping[str, int]) -> list[str]:
    """The ``run_eval.py`` arguments that run the build: ``combined`` with knowledge and skills, else the one it has."""
    kb, skills = installed["kb_version"], installed["skills_version"]
    profile = {(True, True): "combined", (True, False): "gaploop", (False, True): "reflection",
               (False, False): "router"}[(bool(kb), bool(skills))]
    args = ["--profile", profile]
    if kb:
        args += ["--kb-version", str(kb)]
    if skills:
        args += ["--skills-version", str(skills)]
    return args
