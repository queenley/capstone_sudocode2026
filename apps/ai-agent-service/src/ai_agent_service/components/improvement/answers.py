"""The improvement loop's model answers, kept on disk: the same request to the same model is paid for once.

A round is scored and reflected on once, but a run that stops halfway (a rate limit, a network error) is run again,
and every call it had already paid for would be paid again. The key is the model, its reasoning effort, what was asked
for and the whole request, so a changed prompt, skill, rule or model asks again.

``IMPROVEMENT_DIR/cache/answers.jsonl``, one line per answer, never rewritten. This is not the provider's prompt cache,
which only discounts a request's repeated prefix: the agents put what every request shares first for that.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from .signals import home
from .storage import locked

_loaded: dict[str, dict[str, Any]] = {}


def _path() -> Path:
    """``IMPROVEMENT_CACHE``, or ``cache/answers.jsonl`` in ``IMPROVEMENT_DIR``: a round of its own shares the cache, so
    the same learning run yields the same lessons whichever round reads it."""
    return Path(os.environ.get("IMPROVEMENT_CACHE") or home() / "cache" / "answers.jsonl")


def _table() -> dict[str, Any]:
    path = _path()
    table = _loaded.setdefault(str(path), {})
    if not table and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                table[row["key"]] = row["value"]
    return table


def model_label(llm: Any) -> str:
    """The model and the settings that change its answer, as far as the client says."""
    return f"{getattr(llm, 'model_name', None) or type(llm).__name__}/{getattr(llm, 'reasoning_effort', None)}"


def key(kind: str, model: str, request: str) -> str:
    return hashlib.sha256(f"{kind}\n{model}\n{request}".encode("utf-8")).hexdigest()


async def remember(kind: str, model: str, request: str, ask: Callable[[], Awaitable[dict[str, Any] | None]]) -> dict[str, Any] | None:
    """The stored answer to this request, or *ask*'s, stored; a failed ask (None) is not stored and is asked again."""
    found = key(kind, model, request)
    table = _table()
    if found in table:
        return table[found]
    value = await ask()
    if value is None:
        return None
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked(path.parent):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"key": found, "kind": kind, "value": value}, ensure_ascii=False, default=str) + "\n")
    table[found] = value
    return value
