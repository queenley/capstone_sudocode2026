"""Who approves what, and the one log of every change. ``docs/design.md`` section 10.4.

| Change | Approved before it goes live by | After |
|---|---|---|
| Knowledge Gap Loop entry | a person, entry by entry, after the gate of section 10.2 | revocable; adds a growth case |
| Playbook entry from Reflection | the PolicyAgent checks, then a person | revocable |

**No agent both writes and approves.** The QaAgent writes hints and cards,
the screen and the PolicyAgent flag, a person decides. A round's proposals
go to ``IMPROVEMENT_DIR/review/<round>.json`` (and a readable ``.md`` beside
it); the reviewer fills ``decision`` (``approved`` or ``rejected``) and
``reviewer`` in the JSON. :func:`approved` returns only what a person other
than the author approved and nothing flagged; ``versions.publish`` then
writes it.

The **improvement log** (``improvement-log.jsonl``) is append-only: who
proposed, from which failures, what the checks said, who approved, which
version went live, every rollback and revocation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .signals import home

#: Authors that may never approve: the agents of the loop.
AGENTS = frozenset({"qa", "qaagent", "policy", "policyagent", "memory", "simulator", "advisor"})
DECISIONS = ("approved", "rejected")


def log_path() -> Path:
    return home() / "improvement-log.jsonl"


def log(action: str, **fields: Any) -> None:
    """Append one change to the improvement log."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), "action": action, **fields}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def write(round_name: str, proposals: Sequence[Mapping[str, Any]]) -> Path:
    """The round's review file (JSON, filled by the reviewer) and a readable ``.md`` beside it."""
    folder = home() / "review"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{round_name}.json"
    if path.exists():
        raise FileExistsError(f"{path} exists; a review is never overwritten (decisions may be in it)")
    items = [{**proposal, "decision": None, "reviewer": None, "note": None} for proposal in proposals]
    path.write_text(json.dumps({"round": round_name, "proposals": items}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    lines = [f"# Review {round_name}", "",
             f"Fill `decision` ({' or '.join(DECISIONS)}) and `reviewer` for each proposal in `{path.name}`.", ""]
    for item in items:
        entry = item.get("entry") or {}
        evidence = ", ".join("{scenario_id}/{call}".format(**e) for e in item.get("evidence") or [])
        lines += [f"## {item['proposal_id']} ({item.get('kind')}, {item.get('failure_code')})", "",
                  str(entry.get("text") or ""), "",
                  f"- Verified: {json.dumps(item.get('counts') or {}, ensure_ascii=False)}",
                  f"- Flags: {', '.join(item.get('flags') or []) or 'none'}",
                  f"- Evidence: {evidence or 'none'}", ""]
    path.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    log("propose", round=round_name, proposals=[item["proposal_id"] for item in items])
    return path


def approved(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The proposals a person approved, and the ones refused with the reason."""
    data = json.loads(path.read_text(encoding="utf-8"))
    taken: list[dict[str, Any]] = []
    refused: list[dict[str, str]] = []
    for item in data.get("proposals") or []:
        reviewer = str(item.get("reviewer") or "").strip()
        reason = None
        if item.get("decision") != "approved":
            reason = f"decision is {item.get('decision')!r}"
        elif not reviewer:
            reason = "no reviewer"
        elif reviewer.lower() in AGENTS or reviewer.lower() == str(item.get("author") or "").lower():
            reason = f"{reviewer} wrote it or is an agent of the loop"
        elif item.get("flags"):
            reason = f"flagged: {', '.join(item['flags'])}"
        if reason:
            refused.append({"proposal_id": str(item.get("proposal_id")), "reason": reason})
        else:
            taken.append(item)
    return taken, refused
