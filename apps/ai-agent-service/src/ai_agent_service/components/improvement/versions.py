"""What is live, and going back. ``docs/design.md`` sections 7.5 and 10.4.

The knowledge base the advisor reads is the organisers' corpus plus one
version file, ``data/kb/v<N>.jsonl``, named by ``version`` in
``config/knowledge.yaml``. Everything that changes between rounds changes
here, and nowhere else (section 10.1):

- :func:`publish` writes the next version: the one in force plus the
  approved entries. It never edits a file that exists, so every version a
  round was measured on stays as it was measured.
- :func:`rollback` points ``knowledge.yaml`` at an earlier version: going
  back is changing a pointer, nothing is deleted.
- :func:`revoke` writes a new version without one entry, for an entry the
  next round found harmful.

A playbook entry is screened again here (``lessons.screen``), so a flagged
hint cannot be published whatever its review said. Every change goes to the
improvement log (:mod:`.review`). The knowledge server reads the version at
startup, so a run started after the change runs on it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...config.config_manager import KNOWLEDGE_YAML, get_knowledge_config, kb_dir
from ..knowledge.corpus import entry_chunk, version_file
from . import review
from .lessons import Hint, screen

VERSION_LINE = re.compile(r"^version:\s*(\d+)\s*$", re.MULTILINE)


def active(config_path: Path = KNOWLEDGE_YAML) -> int:
    match = VERSION_LINE.search(config_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"{config_path} has no top-level `version:` line")
    return int(match.group(1))


def entries(version: int, directory: Path | None = None) -> list[dict[str, Any]]:
    """The lines of version *version*, as written."""
    path = version_file(directory or kb_dir(), version)
    if not path.exists():
        raise FileNotFoundError(f"Knowledge version {version} does not exist: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def versions(directory: Path | None = None) -> list[int]:
    folder = directory or kb_dir()
    return sorted(int(p.stem[1:]) for p in folder.glob("v*.jsonl") if p.stem[1:].isdigit())


def _point(version: int, config_path: Path) -> None:
    """Set ``version:`` in ``knowledge.yaml``, keeping every comment."""
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(VERSION_LINE.sub(f"version: {version}", text, count=1), encoding="utf-8")
    get_knowledge_config.cache_clear()


def _write(version: int, lines: Sequence[Mapping[str, Any]], directory: Path) -> Path:
    path = version_file(directory, version)
    if path.exists():
        raise FileExistsError(f"{path} exists; a version is never rewritten")
    for line in lines:
        entry_chunk(line, doc=path.name)
    seen = [line["chunk_id"] for line in lines]
    if len(seen) != len(set(seen)):
        raise ValueError(f"{path.name} would repeat a chunk_id")
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
    return path


def publish(new: Sequence[Mapping[str, Any]], *, reviewer: str, note: str = "",
            directory: Path | None = None, config_path: Path = KNOWLEDGE_YAML) -> int:
    """Write the version in force plus *new* as the next version, point at it, and return its number."""
    folder = directory or kb_dir()
    if not reviewer.strip():
        raise ValueError("Publishing needs the reviewer who approved the entries")
    for line in new:
        if line.get("source") == "playbook" and isinstance(line.get("hint"), Mapping):
            flags = screen(Hint.from_json(line["hint"]))
            if flags:
                raise ValueError(f"{line.get('chunk_id')} is flagged ({', '.join(flags)}); it is never published")
    current = active(config_path)
    base = entries(current, folder)
    clash = {line["chunk_id"] for line in base} & {line["chunk_id"] for line in new}
    if clash:
        raise ValueError(f"Already in version {current}: {', '.join(sorted(clash))}")
    target = max(versions(folder) or [current]) + 1
    _write(target, [*base, *new], folder)
    _point(target, config_path)
    review.log("publish", version=target, previous=current, reviewer=reviewer, note=note,
               added=[line["chunk_id"] for line in new])
    return target


def rollback(to: int, *, reviewer: str, reason: str,
             directory: Path | None = None, config_path: Path = KNOWLEDGE_YAML) -> int:
    """Point at version *to*, which must exist; returns the version that was in force."""
    if not version_file(directory or kb_dir(), to).exists():
        raise FileNotFoundError(f"Knowledge version {to} does not exist")
    previous = active(config_path)
    _point(to, config_path)
    review.log("rollback", version=to, previous=previous, reviewer=reviewer, reason=reason)
    return previous


def revoke(chunk_id: str, *, reviewer: str, reason: str,
           directory: Path | None = None, config_path: Path = KNOWLEDGE_YAML) -> int:
    """Write a new version without *chunk_id*, point at it, and return its number."""
    folder = directory or kb_dir()
    current = active(config_path)
    base = entries(current, folder)
    kept = [line for line in base if line["chunk_id"] != chunk_id]
    if len(kept) == len(base):
        raise KeyError(f"{chunk_id} is not in version {current}")
    target = max(versions(folder)) + 1
    _write(target, kept, folder)
    _point(target, config_path)
    review.log("revoke", version=target, previous=current, reviewer=reviewer, reason=reason, revoked=chunk_id)
    return target
