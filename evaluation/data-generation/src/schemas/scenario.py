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
from .slots import CUSTOMER_SLOTS, Channel, InputMode, Outcome, btc_input_mode, normalize_outcome

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
    #: The policy sections ([XX-nn] of policy/) an ideal agent consults: retrieval ground truth (planning/policies.py).
    relevant_policy_ids: list[str] = Field(default_factory=list)
    # Expected structured outputs of the agent (CallBrief at call start, HandoffBrief for chuyen_may).
    expected_call_brief: dict[str, Any] | None = None
    expected_handoff_brief: dict[str, Any] | None = None
    # Tool calls of the ideal agent, executed on BTC mock_tools while planning: [{name, args, result}].
    oracle_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    # Pipeline-only (not exported to BTC files): the call kind it was planned as, and the simulator's setup
    kind: str | None = None
    #: What the ideal agent tells the customer (products, alternatives, totals): the dialogue writer's brief.
    agent_will_tell: dict[str, Any] = Field(default_factory=dict)
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
    #: btc: a BTC persona (config/personas.yaml); advanced: the team's (config/personas_advanced.yaml).
    persona_source: Literal["btc", "advanced"] = "btc"
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
        """The test case as BTC ships it (``test_set/public_sample/SAMPLE-0*.json``, ``schemas/scenario_format.md``).

        Only what ``reference_eval.py`` and the agent under test read, in the samples' order. M2 fields
        (channel, input mode, ASR lines, CRM history, memory expectation, fault) appear when they say
        something; the expected briefs, the oracle's tool calls and the pipeline's own fields are written
        elsewhere (``src/utils/dataset.py``).
        """
        calls: dict[str, Any] = {}
        for name, call in self.calls.items():
            payload: dict[str, Any] = {}
            if call.channel != "hotline":
                payload.update(channel=call.channel, channel_identity=call.channel_identity)
            if name == "call_1":
                payload["call_date"] = call.call_date.isoformat()
            else:
                payload["days_later"] = call.days_later
            if call.input_mode != "text":
                payload["input_mode"] = btc_input_mode(call.input_mode)
            payload.update(customer_goal=call.customer_goal, customer_turns=call.customer_turns)
            optional = {"customer_turns_asr": call.customer_turns_asr, "seed_history": call.seed_history}
            payload.update({key: value for key, value in optional.items() if value})
            # An empty section is left out, as in BTC's samples (contracts/scenario/scenario-keys.yaml rules.values).
            payload.update({key: value for key, value in (("facts_established", call.facts_established),
                                                          ("must_carry_over", call.must_carry_over),
                                                          ("must_not_ask", call.must_not_ask)) if value})
            payload["success_if"] = call.success_if.export()
            if call.ground_truth_facts:
                payload["ground_truth_facts"] = call.ground_truth_facts
            if call.memory_expectation:
                payload["memory_expectation"] = call.memory_expectation
            if call.relevant_policy_ids:
                payload["relevant_policy_ids"] = call.relevant_policy_ids
            if call.fault_injection:
                payload["fault_injection"] = call.fault_injection.model_dump(mode="json")
            # The outcome itself, BTC's four or the team's (cap_nhat_don, thong_tin, xoa_du_lieu), never "khac":
            # reference_eval reads only chuyen_may, and contracts/scenario/scenario-keys.yaml registers each.
            payload["expected_outcome"] = call.expected_outcome
            calls[name] = {key: value for key, value in payload.items() if value is not None}
        return {"scenario_id": self.scenario_id, "level": self.level, "persona": self.persona,
                "hard_case": self.hard_case, "customer_phone": self.customer_phone,
                "customer_name": self.customer_name, "honorific": self.honorific, "notes": self.notes,
                "calls": calls}

    def metadata(self) -> dict[str, Any]:
        """The pipeline's own fields: everything :meth:`btc_export` leaves out, except briefs and tools.

        ``outcome_detail`` repeats the outcome (files written before it was exported whole said "khac");
        ``input_mode_detail`` the typed-chat mode where it says "chat_teencode" (chat_khong_dau, chat_sai_chinh_ta).
        """
        return {"scenario_id": self.scenario_id, "persona_source": self.persona_source,
                "customer_id": self.customer_id, "region": self.region, "category": self.category,
                "difficulty": self.difficulty, "tags": self.tags, "metric_focus": self.metric_focus,
                "calls": {name: {"kind": call.kind, "outcome_detail": call.expected_outcome,
                                 "input_mode_detail": call.input_mode,
                                 "agent_will_tell": call.agent_will_tell,
                                 "speaker_customer_id": call.speaker_customer_id,
                                 "simulator_persona_key": call.simulator_persona_key,
                                 "patience_start": call.patience_start}
                          for name, call in self.calls.items()}}


# --------------------------------------------------------------------------- #
# LLM output                                                                   #
# --------------------------------------------------------------------------- #
CustomerSlot = Literal[CUSTOMER_SLOTS]  # type: ignore[valid-type]


class StatedFact(StrictModel):
    """Một thông tin khách tự nói ra trong cuộc gọi."""

    slot: CustomerSlot = Field(description="Tên slot, chỉ lấy từ INPUT.allowed_customer_slots")
    value: str | int | float | bool = Field(
        description="Giá trị đúng như khách nói: số nguyên VND cho tiền, số cho diện tích/số lượng, true/false cho có/không")


class CallDraft(StrictModel):
    """Phía khách của MỘT cuộc gọi: mục tiêu, lời khách theo thứ tự và các thông tin khách nêu."""

    call: str = Field(default="", description="Tên cuộc gọi lấy đúng từ INPUT.calls[].call: call_1, call_2 hoặc call_3")
    customer_goal: str = Field(min_length=4, description="Mục tiêu của khách trong cuộc này, 1 câu tiếng Việt")
    customer_turns: list[str] = Field(
        min_length=2, max_length=12,
        description="Các câu khách nói theo thứ tự thời gian, mỗi phần tử 1–2 câu tiếng Việt nói tự nhiên, đúng danh xưng")
    customer_turns_asr: list[str] = Field(
        default_factory=list,
        description="Cùng nội dung customer_turns, viết lại kiểu lỗi ASR hoặc teencode. Rỗng nếu input_mode=text.",
    )
    facts_stated: list[StatedFact] = Field(
        default_factory=list,
        description="Mọi thông tin khách nêu trong customer_turns; phải gồm mọi khóa của customer_must_state, đúng giá trị")


class ScenarioDraft(StrictModel):
    """Điều model viết cho một kịch bản: phía khách của từng cuộc gọi. Nhãn chấm điểm do pipeline tính."""

    calls: list[CallDraft] = Field(
        min_length=1, max_length=3,
        description="Đúng một phần tử cho mỗi phần tử của INPUT.calls, cùng thứ tự; crm_history không phải cuộc gọi")
    tags: list[str] = Field(default_factory=list, max_length=6,
                            description="Tối đa 4 tag snake_case ngắn mô tả tình huống")
