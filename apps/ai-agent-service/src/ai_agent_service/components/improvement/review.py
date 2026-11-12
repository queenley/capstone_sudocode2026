"""Who approves what, and the one log of every change. ``docs/design.md`` section 10.4.

| Change | Approved before it goes live by | After |
|---|---|---|
| Knowledge Gap Loop entry | a person, entry by entry, after the gate of section 10.2 | revocable; adds a growth case |
| Skill change from Reflection | the screen and the PolicyAgent check, the ApprovalAgent where the set states what it expects, then a person | a pointer back (rollback) |

**No agent both writes and approves.** The QaAgent scores and diagnoses, the
ReflectionAgent writes the cards and the change, the screen and the
PolicyAgent flag, the ApprovalAgent decides against the expectations of the
people who wrote the learning set (``agents/approval.py``), and a person
decides. In a scripted round, which has no person, the ApprovalAgent's
decision stands; the screen's flags still keep a change out. A round's proposals go to
``IMPROVEMENT_DIR/review/<round>.json`` (and a readable ``.md`` beside it),
with the failures the skills already cover (``not_followed``) listed apart:
those are product work for a person, never a change Reflection makes. The
reviewer fills ``decision`` (``approved`` or ``rejected``), ``reviewer`` and
a ``note`` in the JSON. :func:`approved` returns only what a person other
than the author approved and nothing flagged; ``skill_versions.publish``
then writes it.

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
AGENTS = frozenset({"qa", "qaagent", "policy", "policyagent", "memory", "simulator", "advisor", "reflection",
                    "reflectionagent"})
DECISIONS = ("approved", "rejected")
#: The ApprovalAgent's name in a review file (agents/approval.py): it decides, it never writes a change.
APPROVAL_AGENT = "approval-agent"


def log_path() -> Path:
    return home() / "improvement-log.jsonl"


def log(action: str, **fields: Any) -> None:
    """Append one change to the improvement log."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), "action": action, **fields}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def write(round_name: str, proposals: Sequence[Mapping[str, Any]], not_followed: Sequence[Mapping[str, Any]] = ()) -> Path:
    """The round's review file (JSON, filled by the reviewer) and a readable ``.md`` beside it.

    *not_followed* are the failures a skill already covers: listed for the person, never proposed as a change.
    """
    folder = home() / "review"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{round_name}.json"
    if path.exists():
        raise FileExistsError(f"{path} exists; a review is never overwritten (decisions may be in it)")
    items = [{**proposal, "decision": None, "reviewer": None, "note": None} for proposal in proposals]
    path.write_text(json.dumps({"round": round_name, "proposals": items, "not_followed": list(not_followed)},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# Review {round_name}", "",
             f"Fill `decision` ({' or '.join(DECISIONS)}), `reviewer` and `note` for each proposal in `{path.name}`.", ""]
    for item in items:
        entry = item.get("entry") or {}
        evidence = ", ".join("{scenario_id}/{call}".format(**e) for e in item.get("evidence") or [])
        lines += [f"## {item['proposal_id']} ({item.get('kind')}, {item.get('failure_code')}, {item.get('situation')})", "",
                  str(entry.get("text") or ""), "",
                  f"- Replaces: {entry.get('find') or '(added at the end)'}",
                  *([f"- Description adds: Cả khi {(item.get('patch') or {}).get('when')}."] if (item.get('patch') or {}).get('when') else []),
                  f"- Cites: {', '.join(entry.get('cites') or []) or 'none'}",
                  f"- Support: {json.dumps(item.get('counts') or {}, ensure_ascii=False)}",
                  f"- Flags: {', '.join(item.get('flags') or []) or 'none'}",
                  f"- Policy: {'; '.join(item.get('policy') or []) or 'passed'}",
                  f"- Approval agent: {_approval_line(item.get('approval'))}",
                  f"- Evidence: {evidence or 'none'}", ""]
    if not_followed:
        lines += ["## Covered by a skill and not followed (product work, not Reflection)", ""]
        lines += [f"- {row.get('failure_code')} in {row.get('scenario_id')}/{row.get('call')}, {row.get('skill')}: "
                  f"\"{row.get('covering_sentence')}\"" for row in not_followed]
        lines.append("")
    path.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    log("propose", round=round_name, proposals=[item["proposal_id"] for item in items], not_followed=len(not_followed))
    return path


def _approval_line(decided: Mapping[str, Any] | None) -> str:
    if not decided:
        return "not asked (the learning set states no expectation)"
    return f"{'approve' if decided.get('approve') else 'refuse'}: {decided.get('reason')}"


def approve_scripted(path: Path, reviewer: str) -> None:
    """An evaluation has no person: the ApprovalAgent's decision where the learning set states what it expects, else
    approve what passed the gates, each under a name that says so."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data.get("proposals") or []:
        if item.get("decision") is not None:
            continue
        decided = item.get("approval")
        if decided:
            item.update(decision="approved" if decided.get("approve") else "rejected",
                        reviewer=APPROVAL_AGENT, note=str(decided.get("reason") or ""))
        elif not item.get("flags"):
            item.update(decision="approved", reviewer=reviewer, note="scripted, no person")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("approve_scripted", review=path.name, reviewer=reviewer)


def blocking(item: Mapping[str, Any]) -> list[str]:
    """The flags that keep a change out: all of them, except the PolicyAgent's when the ApprovalAgent read them and
    approved anyway (its reason says why). The screen's flags always hold, and so does a policy check that did not
    run (``policy:unavailable``): nobody read what it would have said."""
    flags = [str(flag) for flag in item.get("flags") or []]
    if item.get("reviewer") == APPROVAL_AGENT and item.get("decision") == "approved":
        return [flag for flag in flags if not flag.startswith("policy:") or flag == "policy:unavailable"]
    return flags


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
        elif blocking(item):
            reason = f"flagged: {', '.join(blocking(item))}"
        if reason:
            refused.append({"proposal_id": str(item.get("proposal_id")), "reason": reason})
        else:
            taken.append(item)
    return taken, refused
