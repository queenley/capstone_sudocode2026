"""LLM-judge output in the shape required by BTC ``data/eval/llm_judge_rubric.json`` (J01–J12)."""
from typing import Literal

from pydantic import Field

from .catalog import StrictModel


class CriterionVerdict(StrictModel):
    """Phán quyết cho một tiêu chí của rubric."""

    criterion_id: str = Field(description="J01_opening_continuity … J12_out_of_stock")
    verdict: Literal["PASS", "FAIL"] = Field(description="PASS khi transcript đạt tiêu chí, FAIL khi không")
    evidence: str = Field(description="trích 1 câu từ transcript")


class JudgeOutput(StrictModel):
    """What the model returns: one verdict per criterion that was sent."""

    verdicts: list[CriterionVerdict] = Field(min_length=1, description="Đúng một phần tử cho MỖI tiêu chí được gửi")


class JudgeVerdict(StrictModel):
    scenario_id: str = Field(min_length=1)
    conversation_id: str = ""
    rubric_id: str = "btc_llm_judge_rubric"
    criteria_applied: list[str] = Field(default_factory=list)
    verdicts: list[CriterionVerdict] = Field(default_factory=list)
    overall_pass: bool
    needs_manual_review: bool
    reasons: str = ""
