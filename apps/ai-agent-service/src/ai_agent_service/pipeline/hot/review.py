"""The PolicyAgent beside a streamed answer. ``docs/design.md`` section 4.8.

A sentence is said at once and reviewed in the background, so a review never
delays the first token. Sentences arriving while a review runs wait and go
together in the next one: one request at a time per turn. A flag is taken once
by the stream, which stops and corrects; a tool with an effect waits for the
reviews running first (:meth:`Reviews.flags`).

A claim about a tool may come before the tool in the same answer ("em chuyển
máy ..." and then ``handoff.transfer``), so :data:`AFTER_TOOLS` is read once
more against every result when the answer is out, and only then corrected.

``head_start`` lets a review run for a moment before its sentence is said: a
fast answer can then stop the sentence, a slow one holds nothing back.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

#: At most this long, at the end of a turn or before a write, for reviews still running.
SETTLE_SECONDS = 2.0

#: The questions a tool later in the same answer can make right.
AFTER_TOOLS = frozenset({"false_transfer", "unsupported_fact", "unbacked_action"})

Review = Callable[[str, tuple[dict[str, Any], ...]], Awaitable[Any]]


class Reviews:
    """The reviews of one turn's answer."""

    def __init__(self, review: Review | None, *, head_start: float = 0.0) -> None:
        self._review = review
        self.head_start = head_start
        self._waiting: list[str] = []
        self._results: tuple[dict[str, Any], ...] = ()
        self._worker: asyncio.Task[None] | None = None
        self._flag: tuple[str, list[str]] | None = None
        self._later: list[str] = []
        #: Every verdict of the turn, for the trace.
        self.verdicts: list[Any] = []
        #: Every sentence flagged after it was said: the console's warning.
        self.flagged: list[dict[str, Any]] = []

    def add(self, sentence: str, results: tuple[dict[str, Any], ...]) -> None:
        if self._review is None:
            return
        self._waiting.append(sentence)
        self._results = results
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while self._waiting:
            text, self._waiting = " ".join(self._waiting), []
            try:
                verdict = await self._review(text, self._results)
            except Exception:  # noqa: BLE001 - a review that failed is a review not done, never a failed turn
                logger.exception("Review failed")
                continue
            self.verdicts.append(verdict)
            now = [r for name, r in zip(verdict.failed, verdict.reasons) if name not in AFTER_TOOLS]
            if now:
                self._raise(text, now)
            if AFTER_TOOLS & set(verdict.failed):
                self._later.append(text)

    def _raise(self, text: str, reasons: list[str]) -> None:
        self._flag = (text, reasons)
        self.flagged.append({"text": text, "reasons": reasons})

    async def head(self) -> None:
        """Give the running review its moment before a sentence is said."""
        if self.head_start > 0 and self._worker is not None and not self._worker.done():
            await asyncio.wait({self._worker}, timeout=self.head_start)

    def take(self) -> tuple[str, list[str]] | None:
        """The flag not yet acted on, once."""
        flag, self._flag = self._flag, None
        return flag

    async def settle(self) -> None:
        """Wait for what is still running, within :data:`SETTLE_SECONDS`."""
        if self._worker is not None and not self._worker.done():
            await asyncio.wait({self._worker}, timeout=SETTLE_SECONDS)

    async def recheck(self, results: tuple[dict[str, Any], ...]) -> None:
        """The answer is out: read again what only the turn's tools could make right."""
        await self.settle()
        later, self._later = self._later, []
        for text in later:
            try:
                verdict = await self._review(text, results)
            except Exception:  # noqa: BLE001
                logger.exception("Review failed")
                continue
            self.verdicts.append(verdict)
            still = [r for name, r in zip(verdict.failed, verdict.reasons) if name in AFTER_TOOLS]
            if still:
                self._raise(text, still)

    async def flags(self) -> list[str]:
        """For a tool with an effect: why it must not run yet. The flag stays for the stream to correct."""
        await self.settle()
        return list(self._flag[1]) if self._flag else []

    def close(self) -> None:
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
