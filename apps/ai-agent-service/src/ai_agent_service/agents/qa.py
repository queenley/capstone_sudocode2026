"""QaAgent: scores calls and says what kind of failure each is. ``docs/design.md`` sections 9.7 and 10.3.

The brief's QA / Evaluator Agent (C.3): "chấm điểm cuộc gọi theo rubric (mục
C.4)". It scores; it does not write the lesson (the ReflectionAgent does) and
it does not approve one (a person does).

Runs in ``after_call`` beside the MemoryAgent, and in the improvement loop
(``pipeline/improve``). It is **not** the evaluation's judge: that one is a
measuring instrument, pinned on the evaluation side and never changed by an
improvement round. Both read the organisers' rubric; the official numbers of a
round are still the organisers' code checks (``eval/reference_eval.py``), so a
lesson learned from a rubric verdict is never proved by the same verdict alone.

- ``tag``: the call's situation (``config/situations.yaml``) and outcome,
  read from the MemoryAgent's candidates.
- ``restate``: a customer's unanswered question, standalone, for the Knowledge Gap Loop.
- ``score``: one call against the BTC rubric (J01-J12), PASS or FAIL with a quoted line.
- ``diagnose``: for one failure, whether the skill in force already says what to do
  (``not_followed``), says nothing or the wrong thing (``skill_gap``), or whether no
  procedure is at stake (``not_a_skill``). A ``not_followed`` answer must quote the
  sentence; code checks the quote (``lessons.settle_kind``).

Its model is ``agents.qa``, built when first needed, so a call's ``after_call``
costs no model call.
"""

from __future__ import annotations

import json
import unicodedata
import re
import logging
from typing import Any, Literal, Mapping, Sequence

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..components.evaluation.judge import BtcJudge
from ..components.improvement import answers
from ..components.memory.gate import Candidate
from ..config.config_manager import load_prompt
from .base import BaseAgent, model_for

logger = logging.getLogger(__name__)

SITUATION_OF = {
    "so_sanh_gia": "price_comparison",
    "gia_cao": "too_expensive",
}


class Restated(BaseModel):
    question: str = Field(description="The question, standalone, in plain Vietnamese with diacritics.")
    variants: list[str] = Field(default_factory=list, description="Two or three other ways to ask it, in Vietnamese.")


class Unanswered(BaseModel):
    unanswered: bool = Field(description="True when the customer asked and the assistant could not answer from what it "
                                         "knows; false when it answered or nothing was asked.")


class Answers(BaseModel):
    answers: bool = Field(description="True when the answer, as written, gives the customer what the question asks.")


class SameQuestion(BaseModel):
    same: bool = Field(description="True when an answer to one fully answers the other: the same thing is asked, "
                                   "not only the same topic.")


class Diagnosis(BaseModel):
    kind: Literal["skill_gap", "not_followed", "not_a_skill"] = Field(
        description="skill_gap: no sentence of the skill says what to do here, or one says the wrong thing. "
                    "not_followed: a sentence of the skill already says what to do here and the assistant did not. "
                    "not_a_skill: a tool, a fact, the customer's script or a rule outside the skills caused it.")
    skill: str = Field(default="", description="The skill whose procedure this task follows, a name from SKILLS; "
                                               "empty for not_a_skill.")
    covering_sentence: str = Field(default="", description="For not_followed: the sentence that already says what to "
                                                           "do, copied exactly from that skill or from FIXED RULES. "
                                                           "Empty otherwise.")
    situation: str = Field(default="other", description="The call's situation, a name from SITUATIONS.")
    why: str = Field(default="", description="One sentence, in Vietnamese: what went wrong in this call.")


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[\"'“”‘’«»]", " ", unicodedata.normalize("NFC", text).lower()).split())


def quoted(evidence: str, words: str) -> bool:
    """Whether a rubric verdict's evidence is the call's own words, read as a person would: case, quotation marks and
    spacing aside, and each part of a quote cut with "..." found in the call. The organisers' judge asks for a quote;
    the exact match left every learning call unscored on 2026-11-10 (the QaAgent is the improvement loop's signal
    apart from the grader)."""
    said = _plain(words)
    # Evidence is often a sentence about the call with the call's words in quotation marks: those words are the quote.
    marked = re.findall(r"[“\"]([^”\"]{4,})[”\"]", evidence)
    parts = [_plain(part) for piece in (marked or [evidence]) for part in re.split(r"\.\.\.|…", piece)]
    parts = [part.strip(" .,;:") for part in parts if len(part.strip(" .,;:")) > 3]
    return bool(parts) and all(part in said for part in parts)


class QaAgent(BaseAgent):
    """Scores calls and diagnoses their failures; never writes or approves a change."""

    def __init__(self, *, llm: BaseChatModel | None = None) -> None:
        """The model is ``agents.qa`` in ``config/models.yaml``, built when first needed; *llm* replaces it in a test."""
        self.name = "qa"
        self._llm = llm
        self._judge: BtcJudge | None = None

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
            situation = "undecided_many_questions"
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

    async def same_question(self, first: str, second: str) -> bool | None:
        """Whether two standalone questions ask the same thing; None without a model or when the call fails."""
        if self.llm is None:
            return None
        request = "\n\n".join([load_prompt("qa_same_question.md"), f"A: {first}", f"B: {second}"])

        async def ask() -> dict[str, Any] | None:
            try:
                return (await self.llm.with_structured_output(SameQuestion).ainvoke(request)).model_dump()
            except Exception as error:  # noqa: BLE001 - not joined is the safe answer
                logger.warning("QaAgent same-question check failed: %s", type(error).__name__)
                return None

        found = await answers.remember("qa.same_question", answers.model_label(self.llm), request, ask)
        return bool(found["same"]) if found else None

    async def unanswered(self, customer: str, assistant: str) -> bool | None:
        """Whether this turn left a customer's question without an answer the shop knows: the Knowledge Gap Loop's
        reading of a call, by meaning, where neither retrieval abstained nor the advisor transferred."""
        if self.llm is None or not customer.strip():
            return None
        request = "\n\n".join([load_prompt("qa_unanswered.md"), f"CUSTOMER: {customer}", f"ASSISTANT: {assistant}"])

        async def ask() -> dict[str, Any] | None:
            try:
                return (await self.llm.with_structured_output(Unanswered).ainvoke(request)).model_dump()
            except Exception as error:  # noqa: BLE001 - not recorded is the safe answer
                logger.warning("QaAgent unanswered check failed: %s", type(error).__name__)
                return None

        found = await answers.remember("qa.unanswered", answers.model_label(self.llm), request, ask)
        return bool(found["unanswered"]) if found else None

    async def answers_question(self, question: str, answer: str) -> bool | None:
        """Whether a consultant's *answer* answers a customer's *question*; None without a model or when the call fails."""
        if self.llm is None:
            return None
        request = "\n\n".join([load_prompt("qa_answers_question.md"), f"QUESTION: {question}", f"ANSWER: {answer}"])

        async def ask() -> dict[str, Any] | None:
            try:
                return (await self.llm.with_structured_output(Answers).ainvoke(request)).model_dump()
            except Exception as error:  # noqa: BLE001 - not matched is the safe answer
                logger.warning("QaAgent answer check failed: %s", type(error).__name__)
                return None

        found = await answers.remember("qa.answers_question", answers.model_label(self.llm), request, ask)
        return bool(found["answers"]) if found else None

    async def score(self, scenario: Mapping[str, Any], call: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        """One call against the organisers' rubric, as their judge prompt asks; None without a model.

        The criteria that apply, the prompt and the completeness check are the
        rubric judge's (``components/evaluation/judge.py``), used as they are;
        only the model is this agent's. A call already scored by this model is
        not paid for again (:mod:`~..components.improvement.answers`).
        """
        if self.llm is None:
            return None
        if self._judge is None:
            self._judge = BtcJudge(self.llm, quoted=quoted)
        # The rubric and its prompt are part of the request: a changed rubric is asked again.
        request = json.dumps({"rubric": self._judge.rubric, "scenario": scenario, "call": call, "rows": rows},
                             ensure_ascii=False, sort_keys=True, default=str)

        async def grade() -> dict[str, Any] | None:
            judged = await self._judge.grade(scenario, call, rows)
            if judged.get("status") != "COMPLETE":  # an incomplete one is asked again; say why, it is not scored
                words = "\n".join(str(row.get(key) or "") for row in rows for key in ("customer_text", "agent_text"))
                unquoted = [v.get("evidence") for v in judged.get("verdicts") or [] if not quoted(str(v.get("evidence") or ""), words)]
                logger.warning("Rubric for %s %s incomplete: %s", scenario.get("scenario_id"), call,
                               judged.get("error") or f"{len(judged.get('verdicts') or [])} verdicts for "
                               f"{len(judged.get('criteria') or [])} criteria; evidence not in the call: {unquoted[:2]}")
                return None
            return judged

        return await answers.remember("qa.score", answers.model_label(self.llm), request, grade) or {
            "status": "INCOMPLETE", "criteria": [], "verdicts": []}

    async def diagnose(self, code: str, check: str, transcript: str, *, skills: Mapping[str, Mapping[str, Any]],
                       situations: Mapping[str, str], fixed_rules: str = "",
                       policy: Mapping[str, str] | None = None) -> Diagnosis | None:
        """What kind of failure *code* is in this call; None without a model or when the call fails.

        It reads the failed check by name and meaning (*check*), the call and the
        skills in force; never the grader's expected words or arguments. What
        every diagnosis of a round shares (the instructions, the skills, the
        situations) comes first, so the provider's prompt cache serves it once
        it has been read; the check and the call come last.
        """
        if self.llm is None:
            return None
        written = "\n".join(f"[{name}] description: {s['description']}\nbody: {s['body']}" for name, s in skills.items())
        shown = "\n".join(f"[{code}] {text}" for code, text in (policy or {}).items())
        request = "\n\n".join([load_prompt("qa_diagnose.md"), "POLICY:\n" + shown, "FIXED RULES:\n" + fixed_rules,
                               "SKILLS:\n" + written,
                               "SITUATIONS:\n" + json.dumps(dict(situations), ensure_ascii=False, indent=0),
                               f"CHECK FAILED: {code}\n{check}", "CALL:\n" + transcript])

        async def ask() -> dict[str, Any] | None:
            try:
                return (await self.llm.with_structured_output(Diagnosis).ainvoke(request)).model_dump()
            except Exception as error:  # noqa: BLE001 - an undiagnosed failure is left for a person
                logger.warning("QaAgent diagnosis failed: %s", type(error).__name__)
                return None

        found = await answers.remember("qa.diagnose", answers.model_label(self.llm), request, ask)
        return Diagnosis.model_validate(found) if found else None
