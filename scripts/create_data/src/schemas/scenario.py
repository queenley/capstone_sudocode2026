"""Scenario contracts.

Two layers:

* ``ScenarioDraft`` – the ONLY structure the LLM writes: customer goal,
  customer utterances (and ASR/teencode variants) and customer-stated facts.
* ``Scenario`` – the full test case in BTC ``scenario_format.md`` shape. All
  metric labels (``must_carry_over``, ``must_not_ask``, ``success_if``,
  ``ground_truth_facts``, ``memory_expectation``, ``expected_outcome``) are
  computed by ``src.planning`` from trusted data, never by the model.

Metric ↔ field map (BTC Phụ lục A):
    CCR  -> must_carry_over (+ facts_established of earlier calls)
    RQR  -> must_not_ask
    TSR  -> success_if
    HR   -> ground_truth_facts + success_if.forbidden_claims
    Over-escalation -> expected_outcome (chuyen_may vs everything else)
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .catalog import StrictModel
from .slots import CUSTOMER_SLOTS, Channel, InputMode, Outcome, normalize_outcome

Region = Literal["bac", "trung", "nam"]
CallName = Literal["call_1", "call_2", "call_3"]
MetricName = Literal["CCR", "RQR", "TSR", "HR", "ESC"]


# --------------------------------------------------------------------------- #
# success_if — BTC flat format                                                 #
# --------------------------------------------------------------------------- #
class ForbiddenClaim(StrictModel):
    field: str
    value: Any  # "*any*" forbids every value of ``field``


class SuccessIf(StrictModel):
    """Task-success contract, identical to BTC ``success_if`` (scored by ``reference_eval.check_call``).

    * ``tool_called=None`` → no tool required; ``args_match`` ⊆ tool args (exact values).
    * ``brief_must_contain`` → handoff brief FIELDS that must be non-empty.
    * ``also_ordered`` / ``total_match_vnd`` → one ``order.create`` per SKU; total = Σ price_vnd × qty.
    * ``agent_must_say`` → presence of the key requires an abstain phrase ("chưa có thông tin"…).
    """

    tool_called: str | None = None
    args_match: dict[str, Any] = Field(default_factory=dict)
    also_ordered: list[str] = Field(default_factory=list)
    total_match_vnd: int | None = None
    brief_must_contain: list[str] = Field(default_factory=list)
    must_say_any: list[str] = Field(default_factory=list)
    agent_must_say: list[str] = Field(default_factory=list)
    must_not_call_tools: list[str] = Field(default_factory=list)
    forbidden_claims: list[ForbiddenClaim | str] = Field(default_factory=list)
    trace_must_not_match: list[str] = Field(default_factory=list)
    max_agent_questions: int | None = Field(default=None, ge=0)

    def export(self) -> dict[str, Any]:
        """BTC JSON: drop empty checks but always keep ``tool_called``."""
        payload = self.model_dump(mode="json", exclude_defaults=True)
        return {"tool_called": self.tool_called, **payload}


class FaultInjection(StrictModel):
    """Harness-side fault for robustness cases (e.g. tool timeout)."""

    tool: str
    mode: Literal["timeout", "error"]


# --------------------------------------------------------------------------- #
# Call + Scenario                                                              #
# --------------------------------------------------------------------------- #
class CallSpec(StrictModel):
    # Scenario conditions
    channel: Channel = "hotline"
    channel_identity: str | None = None
    call_date: date
    days_later: int | None = Field(default=None, ge=0)
    input_mode: InputMode = "text"
    seed_history: list[dict[str, Any]] = Field(default_factory=list)
    speaker_customer_id: str | None = None   # who speaks when it differs from the scenario customer (shared phone)
    fault_injection: FaultInjection | None = None
    # Customer side (LLM-written language, trusted facts)
    customer_goal: str = Field(min_length=4)
    customer_turns: list[str] = Field(min_length=1)
    customer_turns_asr: list[str] = Field(default_factory=list)
    facts_established: dict[str, Any] = Field(default_factory=dict)
    # Metric labels (pipeline-computed)
    expected_outcome: Outcome
    must_carry_over: list[str] = Field(default_factory=list)
    must_not_ask: list[str] = Field(default_factory=list)
    success_if: SuccessIf = Field(default_factory=SuccessIf)
    ground_truth_facts: dict[str, Any] = Field(default_factory=dict)
    # Flat BTC shape: {slot: value, ..., "superseded": {...}, "must_not_write_to": id, "address_ttl_check": bool}
    memory_expectation: dict[str, Any] = Field(default_factory=dict)
    # Expected structured outputs of the agent (CallBrief at call start, HandoffBrief for chuyen_may).
    expected_call_brief: dict[str, Any] | None = None
    expected_handoff_brief: dict[str, Any] | None = None
    # Tool calls of the ideal agent, executed on BTC mock_tools while planning: [{name, args, result}].
    oracle_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    # Simulator configuration (pipeline-only; not exported to BTC files)
    simulator_persona_key: str | None = None
    patience_start: int | None = Field(default=None, ge=0)

    @field_validator("expected_outcome", mode="before")
    @classmethod
    def _normalize_outcome(cls, value: str) -> str:
        return normalize_outcome(value) if isinstance(value, str) else value

    @field_validator("customer_turns")
    @classmethod
    def _complete_utterances(cls, turns: list[str]) -> list[str]:
        if any(len(turn.strip()) < 4 for turn in turns):
            raise ValueError("customer_turns must contain complete customer utterances")
        return turns

    @property
    def escalation_expected(self) -> bool:
        return self.expected_outcome == "chuyen_may"


class Scenario(StrictModel):
    scenario_id: str = Field(min_length=1)
    level: Literal["M1", "M2"] = "M2"
    persona: str = Field(min_length=1)
    hard_case: str | None = None
    customer_id: str | None = None
    customer_phone: str = Field(min_length=1)
    customer_name: str | None = None
    honorific: str | None = None
    region: Region
    category: str = Field(min_length=1)
    difficulty: Literal["normal", "hard"] = "normal"
    tags: list[str] = Field(default_factory=list)
    metric_focus: list[MetricName] = Field(default_factory=list)
    notes: str | None = None
    calls: dict[CallName, CallSpec]

    @model_validator(mode="after")
    def _contiguous_calls(self):
        expected = [f"call_{i}" for i in range(1, len(self.calls) + 1)]
        if list(self.calls) != expected:
            raise ValueError(f"calls must be {expected}, got {list(self.calls)}")
        for name, call in list(self.calls.items())[1:]:
            if call.days_later is None:
                raise ValueError(f"{name}.days_later is required for follow-up calls")
        return self

    def ordered_calls(self) -> list[tuple[str, CallSpec]]:
        return list(self.calls.items())

    def btc_export(self) -> dict[str, Any]:
        """Return the scenario in BTC ``scenario_format.md`` JSON shape."""
        calls: dict[str, Any] = {}
        for name, call in self.calls.items():
            payload = call.model_dump(
                mode="json",
                exclude={"simulator_persona_key", "patience_start", "success_if", "oracle_tool_calls"},
                exclude_none=True,
            )
            payload = {key: value for key, value in payload.items() if value not in ([], {})}
            if name == "call_1":
                payload.pop("days_later", None)
            payload["success_if"] = call.success_if.export()
            calls[name] = payload
        header = self.model_dump(mode="json", exclude={"calls"}, exclude_none=True)
        return {**header, "calls": calls}


# --------------------------------------------------------------------------- #
# LLM output                                                                   #
# --------------------------------------------------------------------------- #
CustomerSlot = Literal[CUSTOMER_SLOTS]  # type: ignore[valid-type]


class StatedFact(StrictModel):
    slot: CustomerSlot
    value: str | int | float | bool


class CallDraft(StrictModel):
    call: str = Field(default="", description="Tên cuộc gọi lấy đúng từ INPUT.calls[].call: call_1, call_2 hoặc call_3")
    customer_goal: str = Field(min_length=4, description="Mục tiêu của khách trong cuộc này, 1 câu tiếng Việt")
    customer_turns: list[str] = Field(min_length=2, max_length=12)
    customer_turns_asr: list[str] = Field(
        default_factory=list,
        description="Cùng nội dung customer_turns, viết lại kiểu lỗi ASR hoặc teencode. Rỗng nếu input_mode=text.",
    )
    facts_stated: list[StatedFact] = Field(default_factory=list)


class ScenarioDraft(StrictModel):
    calls: list[CallDraft] = Field(min_length=1, max_length=3)
    tags: list[str] = Field(default_factory=list, max_length=6)
