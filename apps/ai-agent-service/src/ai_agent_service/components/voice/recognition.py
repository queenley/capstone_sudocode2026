"""The same recognition postprocessing for web voice and ASR benchmarks. No model calls."""
from dataclasses import asdict, dataclass
from typing import Any

from .policy import POLICY_VERSION, decide_turn


@dataclass(frozen=True)
class Recognition:
    raw_text: str
    corrected_text: str
    agent_text: str
    accepted: bool
    reason: str
    removed_words: int
    corrections: list
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


def process(text: str, *, lexicon: Any, busy: bool = False, min_words: int = 2, echo_text: str = "") -> Recognition:
    # Echo comparison uses raw ASR on both sides before lexicon corrections.
    decision = decide_turn(text, busy=busy, min_words=min_words, echo_text=echo_text)
    corrected, corrections = lexicon.correct(text)
    agent_text, _ = lexicon.correct(decision.text)
    return Recognition(text, corrected, agent_text if decision.accepted else "", decision.accepted,
                       decision.reason, decision.removed_words, corrections)
