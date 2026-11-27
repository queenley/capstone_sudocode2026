"""A streamed reply, cut into sentences that are checked one at a time. ``docs/design.md`` section 4.8.

The advisor's answer arrives in chunks. A sentence is said only once the
guard has passed it, hard rules first and then the PolicyAgent when it
carries a risk signal: the way NeMo Guardrails checks a stream chunk by
chunk with ``stream_first: False``, trading a little delay for never saying
what it has not checked. A sentence already said cannot be taken back, so a
block after the first sentence ends the stream with the safe line (section
4.5).

A sentence ends at ``.``, ``!``, ``?`` or ``…`` followed by a space (with any
``[Bn]`` marks right after it), or when it runs past
:data:`MAX_SENTENCE` characters without one, cut at the last space. A dot
inside a number (``5.200.000đ``) or a code is never an end, because no space
follows it.
"""

from __future__ import annotations

import re

#: Section 4.8: a sentence longer than this is cut at its last space.
MAX_SENTENCE = 200

_END = re.compile(r"[.!?…]+(?:\s*\[B\d+\])*\s+")

#: A clause ends at a comma, a semicolon or a colon followed by a space: "4,5" (a decimal comma) and "09:00" have
#: none, so they are never cut. The spoken note asks for commas only; the others are cut the same if they come.
_CLAUSE = re.compile(r"[,;:]\s+")

#: Plan 002: the first clause of a spoken answer is said on its own when it is at least this long, in characters and
#: in words; shorter ("Dạ vâng,") it waits for the rest of its sentence.
FIRST_CLAUSE_CHARS = 20
FIRST_CLAUSE_WORDS = 4


class SentenceSplitter:
    """Collects streamed text and hands back each sentence once it is complete."""

    def __init__(self, max_chars: int = MAX_SENTENCE, *, first_clause: bool = False) -> None:
        self._buffer = ""
        self._max = max_chars
        #: Cut the first sentence at its first long-enough clause (:meth:`pieces`), once.
        self._first_clause = first_clause
        #: The sentence whose first clause was handed out is still open: its next piece is its rest.
        self.open = False

    def feed(self, chunk: str) -> list[str]:
        """The sentences *chunk* completed, in order; the rest waits for more text."""
        self._buffer += chunk
        sentences: list[str] = []
        while True:
            match = _END.search(self._buffer)
            if match:
                sentences.append(self._buffer[:match.end()])
                self._buffer = self._buffer[match.end():]
                continue
            if len(self._buffer) > self._max:
                cut = self._buffer.rfind(" ", 0, self._max)
                cut = cut if cut > 0 else self._max
                sentences.append(self._buffer[:cut])
                self._buffer = self._buffer[cut:]
                continue
            break
        return [s.strip() for s in sentences if s.strip()]

    def pieces(self, chunk: str) -> list[tuple[str, str]]:
        """As :meth:`feed`, each piece with its kind: ``sentence``; ``clause``, the first clause of the answer said
        ahead of its sentence (a voice starts on it); ``rest``, what completes that sentence."""
        out: list[tuple[str, str]] = []
        if self._first_clause and not self.open:
            self._buffer += chunk
            chunk = ""
            end = _END.search(self._buffer)
            for clause in _CLAUSE.finditer(self._buffer):
                if end is not None and clause.start() > end.start():
                    break
                head = self._buffer[:clause.start() + 1].strip()
                if len(head) >= FIRST_CLAUSE_CHARS and len(head.split()) >= FIRST_CLAUSE_WORDS:
                    self._buffer = self._buffer[clause.end():]
                    self._first_clause, self.open = False, True
                    out.append((head, "clause"))
                    break
            if end is not None and not self.open:
                self._first_clause = False  # the first sentence ended before any clause was long enough
        for sentence in self.feed(chunk):
            out.append((sentence, "rest" if self.open else "sentence"))
            self.open = False
        return out

    @property
    def holding(self) -> bool:
        """Whether part of a sentence is waiting for the rest."""
        return bool(self._buffer.strip())

    def flush(self) -> str | None:
        """What is left when the stream ends: the last sentence, if any."""
        rest, self._buffer = self._buffer.strip(), ""
        self.open = False
        return rest or None
