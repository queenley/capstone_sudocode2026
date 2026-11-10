"""ReflectionAgent: the advisor's reflection on its own calls. ``docs/design.md`` section 10.3.

The brief, C.5 mechanism 3: "sau mỗi cuộc gọi, agent tự viết 'bài học rút
ra' có cấu trúc, được kiểm tra rồi mới ghi vào bộ nhớ". This is the agent
writing: it reads a call the advisor made, the check the QaAgent says failed
and the skill the advisor followed, and writes one structured lesson card
(:class:`LessonCard`). Code screens the card before it is stored; it never
reaches the advisor as it is.

When enough customers share one lesson it drafts the change to the skill,
one sentence (:class:`SkillPatch`); code merges it, the PolicyAgent checks
it, a person approves it. It never approves anything itself.

It reflects only on what the skill does not say (``skill_gap``): a skill that
already says it and was not followed is a product matter, not a lesson.

Off the hot path, so its model is ``agents.reflection`` in
``config/models.yaml``, chosen for reasoning rather than for the first token
the advisor's own model is chosen for (ACE, Zhang et al. 2025: the lessons are
only as good as the model that draws them).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, Mapping, Sequence

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..components.improvement import answers
from ..config.config_manager import load_prompt
from .base import BaseAgent, model_for

logger = logging.getLogger(__name__)


class LessonCard(BaseModel):
    no_lesson: bool = Field(default=False, description="True when this call teaches no change to how the shop works.")
    situation: str = Field(default="other", description="The call's situation, a name from SITUATIONS.")
    what_happened: str = Field(default="", description="One sentence, in Vietnamese: what the assistant did and why it "
                                                       "fell short, without the customer's name or numbers.")
    do: str = Field(default="", description="In Vietnamese, an instruction to the assistant: what to do in this situation.")
    dont: str = Field(default="", description="In Vietnamese: what not to do in this situation.")
    sample_line: str = Field(default="", description="In Vietnamese, one line the assistant could say, with no amount, "
                                                     "product, promotion code or name.")
    cites: list[str] = Field(default_factory=list, description="Codes of the RULES this applies, such as BH-03.")
    scope: Literal["general", "this_customer"] = Field(
        default="general", description="general: holds for any customer in this situation. this_customer: only for "
                                       "this customer's own preference.")


class SkillPatch(BaseModel):
    no_change: bool = Field(default=False, description="True when no change to the skill would fix these calls.")
    part: Literal["body", "description"] = Field(default="body", description="Which part of the skill to change.")
    find: str = Field(default="", description="A sentence copied exactly from that part; empty adds at the end.")
    text: str = Field(default="", description="The new sentence, in Vietnamese.")
    cites: list[str] = Field(default_factory=list, description="Codes of the rules this applies, from RULES.")
    when: str = Field(default="", description="In Vietnamese, a few words naming the situation, such as 'khách lo máy "
                                              "mau hỏng'; only when the skill's description does not already name it, "
                                              "so the assistant knows the skill applies. Empty otherwise.")
    why: str = Field(default="", description="One sentence: what these calls have in common.")


def _rules_block(rules: Mapping[str, str]) -> str:
    return "RULES:\n" + "\n".join(f"[{code}] {text}" for code, text in rules.items())


def _fixed_block(fixed_rules: str) -> str:
    return "FIXED RULES (the assistant's own instructions; never contradict them, never repeat them):\n" + fixed_rules


def _tools_block() -> str:
    """The assistant's tools and what each does: a lesson never asks for what none of them does."""
    from ..components.improvement.lessons import advisor_tools

    return "TOOLS (all the assistant can do or look up; nothing else exists):\n" + "\n".join(
        f"- {name}: {text}" for name, text in advisor_tools().items())


def _skill_block(name: str, skill: Mapping[str, Any]) -> str:
    return f"SKILL [{name}]\ndescription: {skill['description']}\nbody: {skill['body']}"


class ReflectionAgent(BaseAgent):
    """Writes lesson cards from calls, and the one-sentence change several cards share."""

    def __init__(self, *, llm: BaseChatModel | None = None) -> None:
        """The model is ``agents.reflection``, built when first needed; *llm* replaces it in a test."""
        self.name = "reflection"
        self._llm = llm

    @property
    def llm(self) -> BaseChatModel | None:
        if self._llm is None:
            self._llm = model_for(self.name)
        return self._llm

    async def _ask(self, kind: str, schema: type[BaseModel], request: str) -> dict[str, Any] | None:
        """One structured answer, from the answer store when this model was already asked exactly this."""
        async def ask() -> dict[str, Any] | None:
            try:
                return (await self.llm.with_structured_output(schema).ainvoke(request)).model_dump()
            except Exception as error:  # noqa: BLE001 - no card or no change is a valid outcome of a round
                logger.warning("Reflection %s failed: %s", kind, type(error).__name__)
                return None

        return await answers.remember(f"reflection.{kind}", answers.model_label(self.llm), request, ask)

    async def lesson(self, code: str, check: str, transcript: str, *, skill: str, skills: Mapping[str, Mapping[str, Any]],
                     rules: Mapping[str, str], situations: Mapping[str, str], fixed_rules: str = "",
                     covering: str = "") -> LessonCard | None:
        """One card for one call; None without a model or when the call fails.

        It reads the failed check by name and meaning, never the grader's
        expected words or arguments, so a lesson says what to do and not what
        the test looks for. What every card of a round shares comes first (the
        instructions, the rules, the situations), then the skill, then this
        call, so the provider's prompt cache serves the long common part.
        """
        if self.llm is None or skill not in skills:
            return None
        request = "\n\n".join([load_prompt("reflection_lesson.md"), _rules_block(rules), _fixed_block(fixed_rules), _tools_block(),
                               "SITUATIONS:\n" + json.dumps(dict(situations), ensure_ascii=False, indent=0),
                               _skill_block(skill, skills[skill]), f"CHECK FAILED: {code}\n{check}",
                               ("ALREADY SAID, NOT DONE: " + covering) if covering else "ALREADY SAID, NOT DONE: (nothing)",
                               "CALL:\n" + transcript])
        found = await self._ask("lesson", LessonCard, request)
        return LessonCard.model_validate(found) if found else None

    async def patch(self, cards: Sequence[Mapping[str, Any]], *, skill: str, skills: Mapping[str, Mapping[str, Any]],
                    rules: Mapping[str, str], fixed_rules: str = "",
                    objection: Mapping[str, Any] | None = None) -> SkillPatch | None:
        """One sentence of *skill* for what *cards* share; None without a model or when the call fails.

        With *objection* (the change the PolicyAgent refused and the checks it failed) it writes the change again once,
        keeping the lesson and removing what the checker refused."""
        if self.llm is None or skill not in skills:
            return None
        shown = [{key: card.get(key) for key in ("situation", "what_happened", "do", "dont", "sample_line", "cites")}
                 for card in cards]
        request = "\n\n".join([load_prompt("reflection_patch.md"), _rules_block(rules), _fixed_block(fixed_rules), _tools_block(),
                               _skill_block(skill, skills[skill]),
                               "LESSON CARDS:\n" + json.dumps(shown, ensure_ascii=False, indent=1),
                               *([_objection_block(objection)] if objection else [])])
        found = await self._ask("patch", SkillPatch, request)
        return SkillPatch.model_validate(found) if found else None


def _objection_block(objection: Mapping[str, Any]) -> str:
    return ("A CHECKER REFUSED YOUR LAST CHANGE. Write it again: keep what the cards teach, remove what the checks "
            "below found, and keep every step the fixed rules require. If that leaves nothing, set no_change.\n"
            f"Refused text: {objection.get('text')}\nReplaced sentence: {objection.get('find') or '(none, added)'}\n"
            "Failed checks:\n" + "\n".join(f"- {line}" for line in objection.get("checks") or ()))
