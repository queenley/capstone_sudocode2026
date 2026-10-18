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


class SentenceSplitter:
    """Collects streamed text and hands back each sentence once it is complete."""

    def __init__(self, max_chars: int = MAX_SENTENCE) -> None:
        self._buffer = ""
        self._max = max_chars

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

    def flush(self) -> str | None:
        """What is left when the stream ends: the last sentence, if any."""
        rest, self._buffer = self._buffer.strip(), ""
        return rest or None
