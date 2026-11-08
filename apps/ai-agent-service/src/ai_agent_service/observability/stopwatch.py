"""Where a turn's milliseconds go: one stopwatch per turn, read through a context variable.

``ttft_ms`` and ``total_ms`` say how long a turn took, not why. Each stage that can take time is
timed where it runs (:func:`span`), into the stopwatch the turn started (:func:`started`); the
nodes need no extra argument, and a stage timed with no stopwatch running (a test, the probe)
costs nothing. asyncio copies the context into each task it starts, so the advisor's tool calls,
run in tasks of their own, still reach the turn's stopwatch.

A stage's time is its wall time: two tool calls running together count once, for as long as
either runs. The stages on the turn's own path follow one another, so with ``other`` (what no
stage claims: perceive, route, the graph's own steps) they add up to ``total_ms``:

- ``context``: identifying the caller and building the Call Brief;
- ``knowledge``: ``kb.search`` on the customer's words;
- ``compact``: folding old turns into the working summary (a model call);
- ``advisor``: waiting for the advisor's next word, its tool rounds included;
- ``guard``: the hard check, ``policy``: ``PolicyAgent`` on Jev;
- ``respond``, ``persist``: the two last nodes.

``model`` and ``tools`` are what ``advisor`` was made of, measured inside the advisor's loop. The
loop runs ahead while a sentence is being checked, so ``model`` may be longer than the wait it
caused; it is reported beside the path, never added to it.
"""

from __future__ import annotations

import time
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator

#: The stages on the turn's path, in the order they run.
PATH: tuple[str, ...] = ("context", "knowledge", "compact", "advisor", "guard", "policy", "respond", "persist")
#: Measured inside ``advisor``, beside the path.
INSIDE: tuple[str, ...] = ("model", "tools")

_current: ContextVar["Stopwatch | None"] = ContextVar("turn_stopwatch", default=None)


class Stopwatch:
    """The wall time and the count of each stage of one turn."""

    def __init__(self) -> None:
        self.ms: dict[str, float] = {}
        self.counts: Counter[str] = Counter()
        self._open: Counter[str] = Counter()
        self._since: dict[str, float] = {}

    def enter(self, stage: str) -> None:
        self.counts[stage] += 1
        if not self._open[stage]:
            self._since[stage] = time.perf_counter()
        self._open[stage] += 1

    def leave(self, stage: str) -> None:
        self._open[stage] -= 1
        if not self._open[stage]:
            self.ms[stage] = self.ms.get(stage, 0.0) + (time.perf_counter() - self._since.pop(stage)) * 1000

    def report(self, total_ms: int | None = None) -> dict[str, Any]:
        """``{"stages_ms": ..., "stage_counts": ...}``; with *total_ms*, ``other`` is what no stage of the path claims."""
        stages = {name: int(round(self.ms[name])) for name in (*PATH, *INSIDE) if name in self.ms}
        if total_ms is not None:
            stages["other"] = max(0, int(total_ms) - sum(stages.get(name, 0) for name in PATH))
        return {"stages_ms": stages, "stage_counts": {name: self.counts[name] for name in (*PATH, *INSIDE) if self.counts[name]}}


def started() -> tuple[Stopwatch, Token]:
    """Start the turn's stopwatch; hand the token to :func:`stopped` when the turn ends."""
    watch = Stopwatch()
    return watch, _current.set(watch)


def stopped(token: Token) -> None:
    _current.reset(token)


@contextmanager
def span(stage: str) -> Iterator[None]:
    """Time the block as *stage* of the running turn; nothing when no turn is timed."""
    watch = _current.get()
    if watch is None:
        yield
        return
    watch.enter(stage)
    try:
        yield
    finally:
        watch.leave(stage)
