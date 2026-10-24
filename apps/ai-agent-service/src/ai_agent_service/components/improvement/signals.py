"""Signals: where the system learns it did something badly. ``docs/design.md`` 10.1.

The brief's four sources, each feeding exactly one place:

| Source | Comes from | Feeds |
|---|---|---|
| call outcome | the ``outcome`` slot, the tool log (``order.create``) | Reflection: won and lost calls in a cluster |
| automatic score | branch B scoring every call on the rubric; ``errors.jsonl`` of an eval run | Reflection: which calls are worth learning from |
| consultant's choice | the answer after a handoff; used, edited or own on a copilot suggestion | Gap Loop (the answer), Reflection (the edit) |
| customer repeating | the question classifier live, or "em nói rồi mà" | memory quality monitoring only |

Plus ``oos_early`` and ``oos_late`` for the Gap Loop. A violation (a wrong
promise, a leak) waits for nothing: branch B alerts QA at once.

Every row keeps ``call_id`` and ``turn_id`` (section 5.5).

Status: **partly built.** Rows are appended to ``signals.jsonl`` in ``IMPROVEMENT_DIR`` (default
``data/improvement``; the evaluation clears database tables per scenario, a file survives). Built and fed
today: ``consultant`` (the explicit 👍/👎 on a suggestion and the used/edited/own choice, from the console),
``outcome``, ``score`` and ``repeat`` (``harvest`` of an evaluation run, not yet written). Not built: the
Reflection and Gap Loop readers that consume these rows.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Kind = Literal["outcome", "score", "consultant", "repeat", "oos_early", "oos_late", "violation", "eval_error"]

DEFAULT_DIR = Path(__file__).resolve().parents[4] / "data" / "improvement"


def store() -> Path:
    """``signals.jsonl`` in ``IMPROVEMENT_DIR``."""
    return Path(os.environ.get("IMPROVEMENT_DIR") or DEFAULT_DIR) / "signals.jsonl"


async def record(kind: Kind, *, call_id: str, turn_id: str | None, value: Any) -> None:
    """Append one signal; a row is one line, never rewritten."""
    row = {"at": datetime.now(timezone.utc).isoformat(), "kind": kind, "call_id": str(call_id), "turn_id": turn_id, "value": value}
    path = store()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read(kind: Kind | None = None) -> list[dict[str, Any]]:
    """Every row (of *kind*), oldest first."""
    path = store()
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if kind is None or row["kind"] == kind]


async def alert_qa(call_id: str, turn_id: str | None, reason: str) -> None:
    """A violation: tell QA now, not in a batch (here: a ``violation`` row QA's page reads)."""
    await record("violation", call_id=call_id, turn_id=turn_id, value={"reason": reason, "alerted": True})
