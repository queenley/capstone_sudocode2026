"""Which utterances count as a turn. ``docs/design.md`` section 4.11.

Voice activity alone cannot tell a caller cutting in from a caller saying
"ừ" to show they are listening, from a cough, or from the line hissing. The
production voice stacks settle it on the words once they are recognised:
LiveKit's agents take an interruption only past ``min_interruption_words``
and resume speaking after a ``false_interruption_timeout`` with no words
(https://docs.livekit.io/agents/logic/turns/); Pipecat's
``MinWordsInterruptionStrategy`` does the same. This is that rule, pure so it
can be tested without a microphone:

- a hesitation ("ừm", "ờ", "à") is never a turn;
- while the assistant is talking or still working out its answer, an
  utterance must have at least ``min_words`` words and not be backchannel
  alone ("dạ", "vâng", "ok") to interrupt it;
- while the assistant is listening, anything with a word in it is a turn,
  because "vâng" is a real answer to "chị lên đơn luôn nhé?".

Pure: no audio packages, so the voice session and its tests import it freely.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

POLICY_VERSION = "voicego-adapted-v1"
INTERRUPT_COMMANDS = frozenset({"không", "dừng", "thôi", "khoan", "hủy", "huỷ", "stop"})

HESITATION = frozenset({"ừ", "ừm", "ừa", "ờ", "ơ", "à", "á", "ư", "hử", "hả", "ồ", "ô", "hmm", "hm", "uh", "um", "ờm"})
BACKCHANNEL = HESITATION | frozenset({"dạ", "vâng", "ok", "okay", "oke", "đúng", "rồi", "ạ", "thế", "vậy", "à ừ"})


def counts_as_turn(text: str, *, busy: bool, min_words: int) -> tuple[bool, str]:
    """Whether *text* takes a turn, and if not, why."""
    words = re.findall(r"\w+", text.lower())
    if not words:
        return False, "nothing recognised"
    if all(word in HESITATION for word in words):
        return False, "a hesitation"
    if busy:
        if len(words) == 1 and words[0] in INTERRUPT_COMMANDS:
            return True, ""
        if len(words) < min_words:
            return False, f"under {min_words} words while the assistant was busy"
        if all(word in BACKCHANNEL for word in words):
            return False, "listening sounds while the assistant was busy"
    return True, ""


@dataclass(frozen=True)
class TurnDecision:
    text: str
    accepted: bool
    reason: str
    removed_words: int = 0


def decide_turn(text: str, *, busy: bool, min_words: int, echo_text: str = "") -> TurnDecision:
    """Conservative leading echo removal, inspired by VoiceGo's assessTurn.

    Keep accents and numeric values: collapsing all numbers can erase a customer's
    correction to a price. Only text acknowledged as played belongs in echo_text.
    """
    text = unicodedata.normalize("NFC", text).strip()
    tokens = list(re.finditer(r"\w+", text))
    words = [match.group().casefold() for match in tokens]
    reference = re.findall(r"\w+", unicodedata.normalize("NFC", echo_text).casefold())[-120:]
    removed = 0
    minimum = 3 if busy else 4
    for start in range(len(reference)):
        length = 0
        while length < len(words) and start + length < len(reference) and words[length] == reference[start + length]:
            length += 1
        if length >= minimum:
            removed = max(removed, length)
    # A short product/size answer may legitimately repeat the assistant's options.
    if removed == len(words) and len(words) <= 4:
        removed = 0
    if 0 < removed < len(words):
        boundary = text[tokens[removed - 1].end():tokens[removed].start()]
        if not re.search(r"[.!?…]", boundary) and words[removed] not in INTERRUPT_COMMANDS:
            removed = 0
    cleaned = text[tokens[removed - 1].end():].lstrip(" ,.;:!?…") if removed else text
    if removed == len(words) and removed:
        return TurnDecision("", False, "echo-only", removed)
    accepted, reason = counts_as_turn(cleaned, busy=busy, min_words=min_words)
    return TurnDecision(cleaned, accepted, reason or "user", removed)
