"""QaAgent: tags every call, and proposes what failed ones teach. ``docs/design.md`` sections 9.7 and 10.3.

Runs in ``after_call`` beside the MemoryAgent, and in the improvement
loop (``pipeline/improve``). It is **not** the evaluation's
judge: that one is a measuring instrument, pinned on the evaluation side and
never changed by an improvement round. An agent whose output is being
improved does not also grade it (Pan et al., 2024: a generator and an
evaluator sharing a model drift from human judgement in context).

- ``tag``: the call's situation (``config/situations.yaml``) and outcome,
  read from the MemoryAgent's candidates.
- ``restate``: a customer's unanswered question, standalone, for the Knowledge Gap Loop.
- ``patch_skill``: one change to one skill for a failure that independent calls share.

It never approves what it writes: the screen and the PolicyAgent flag, a
person approves. Its model is ``agents.qa``, built when first needed,
so a call's ``after_call`` costs no model call.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Mapping, Sequence

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..config.config_manager import load_prompt
from ..components.memory.gate import Candidate
from .base import BaseAgent, model_for

logger = logging.getLogger(__name__)

SITUATION_OF = {
    "so_sanh_gia": "price_comparison",
    "gia_cao": "too_expensive",
}

class Restated(BaseModel):
    question: str = Field(description="The question, standalone, in plain Vietnamese with diacritics.")
    variants: list[str] = Field(default_factory=list, description="Two or three other ways to ask it, in Vietnamese.")


class SkillPatch(BaseModel):
    no_change: bool = Field(default=False, description="True when no procedure change would fix these calls.")
    skill: str = Field(default="", description="The skill's name, from SKILLS.")
    part: Literal["body", "description"] = Field(default="body", description="Which part of the skill to change.")
    find: str = Field(default="", description="A sentence copied exactly from that part; empty adds at the end.")
    text: str = Field(default="", description="The new sentence, in Vietnamese.")
    cites: list[str] = Field(default_factory=list, description="Codes of the rules this applies, from RULES.")
    why: str = Field(default="", description="One sentence: what these calls have in common.")


class QaAgent(BaseAgent):
    """Tags calls, and proposes what a failed one teaches."""

    def __init__(self, *, llm: BaseChatModel | None = None) -> None:
        """The model is ``agents.qa`` in ``config/models.yaml``, built when first needed; *llm* replaces it in a test."""
        self.name = "qa"
        self._llm = llm

    @property
    def llm(self) -> BaseChatModel | None:
        if self._llm is None:
            self._llm = model_for(self.name)
        return self._llm

    async def tag(self, candidates: Sequence[Candidate], *, returning: bool) -> dict[str, str]:
        """{"situation": ..., "outcome": ...}."""
        values = {c.slot: c.value for c in candidates if c.slot}
        situation = SITUATION_OF.get(str(values.get("objection_type")), "")
        if not situation and str(values.get("blocker", "")).startswith("cần hỏi"):
            situation = "family_decision"
        if not situation and returning:
            situation = "returning_undecided"
        return {"situation": situation or "other", "outcome": str(values.get("outcome") or "khac")}

    async def restate(self, question: str, recent: Sequence[str] = ()) -> Restated | None:
        """A customer's question, standalone, for the Knowledge Gap Loop; None without a model or when the call fails."""
        if self.llm is None:
            return None
        request = "\n\n".join([load_prompt("qa_restate.md"), "RECENT:\n" + "\n".join(recent), f"QUESTION:\n{question}"])
        try:
            return await self.llm.with_structured_output(Restated).ainvoke(request)
        except Exception as error:  # noqa: BLE001 - a gap not restated stays open, nothing is lost
            logger.warning("Restating a question failed: %s", type(error).__name__)
            return None

    async def patch_skill(self, code: str, calls: Sequence[Mapping[str, Any]], *, skills: Mapping[str, Mapping[str, Any]],
                          rules: Mapping[str, str]) -> SkillPatch | None:
        """One change to one skill for a failure several calls share; None without a model or when the call fails.

        It sees the failed calls and the grader's reason; never a scenario's answer key beyond that, never the
        frozen test set. It does not approve what it writes.
        """
        if self.llm is None:
            return None
        written = "\n".join(f"[{name}] description: {s['description']}\nbody: {s['body']}" for name, s in skills.items())
        seen = "\n\n".join(f"grader: {c.get('reason')}\n" + "\n".join(
            f"{line.get('speaker')}: {line.get('text')}" for line in c.get("transcript") or []) for c in calls)
        request = "\n\n".join([load_prompt("qa_skill_patch.md"), f"CHECK FAILED: {code}", "SKILLS:\n" + written,
                                "RULES:\n" + "\n".join(f"[{k}] {v}" for k, v in rules.items()), "CALLS:\n" + seen])
        try:
            return await self.llm.with_structured_output(SkillPatch).ainvoke(request)
        except Exception as error:  # noqa: BLE001 - no change is a valid outcome of a round
            logger.warning("QaAgent reflection failed: %s", type(error).__name__)
            return None
