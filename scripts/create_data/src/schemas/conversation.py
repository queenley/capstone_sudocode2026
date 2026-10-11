"""Reference transcript for ONE call of a scenario.

Agent turns carry exactly the fields of a BTC trace row (``schemas/trace_log.schema.json``
as read by ``data/eval/reference_eval.py``): ``questions``, ``facts_used``, ``claims``,
``tool_calls``, ``memory_writes``. ``src.ground_truth.traces`` converts a transcript into
trace JSONL, so the gold transcript is scored by the official script.
"""
from datetime import date
from typing import Any, Literal

from pydantic import Field, RootModel

from .catalog import StrictModel
from .scenario import CallName, Region
from .slots import Channel, Outcome


class Entity(StrictModel):
    type: Literal["money", "phone", "date", "time", "address", "cccd", "order_id"]
    value: str
    spoken: str


class Claim(StrictModel):
    """A factual assertion, e.g. ``{"field": "price_vnd", "value": 5200000}``.

    ``field`` must be a ``ground_truth_facts`` key for HR to check it (exact match).
    """

    field: str
    value: str | int | float | bool | None


class Question(StrictModel):
    """An agent question about a slot. RQR: open question on a must_not_ask slot,
    or the 2nd+ confirm of the same slot in the call, is redundant."""

    slot: str
    type: Literal["open", "confirm"]
    text: str = ""


class ToolCall(StrictModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class AgentTurn(StrictModel):
    speaker: Literal["agent_ai", "agent_human"]
    text: str = Field(min_length=1)
    questions: list[Question] = Field(default_factory=list)
    facts_used: list[str] = Field(default_factory=list, description="slots from memory used in this turn (CCR)")
    claims: list[Claim] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    memory_writes: list[dict[str, Any]] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    pause_before_ms: int = 0
    emotion: str | None = None
    barge_in: bool = False


class CustomerTurn(StrictModel):
    speaker: Literal["customer"]
    text: str = Field(min_length=1)
    facts_stated: dict[str, Any] = Field(default_factory=dict)
    entities: list[Entity] = Field(default_factory=list)
    pause_before_ms: int = 0
    emotion: str | None = None
    barge_in: bool = False


class ConversationTurn(RootModel[AgentTurn | CustomerTurn]):
    pass


class CallGold(StrictModel):
    intent: str
    outcome: Outcome
    objection_type: str | None = None
    objection_handling: str | None = None
    sentiment: Literal["positive", "neutral", "negative"]
    decision_maker: str | None = None
    commitments: list[dict[str, Any]] = Field(default_factory=list)
    supersedes: list[dict[str, Any]] = Field(default_factory=list)
    callback: dict[str, Any] | None = None
    order: dict[str, Any] | None = None


class Conversation(StrictModel):
    conversation_id: str = Field(min_length=1)  # "<scenario_id>__<call>"
    scenario_id: str = ""
    call: CallName = "call_1"
    customer_id: str = Field(min_length=1)
    session_index: int = Field(ge=1)
    channel: Channel
    date: date
    region: Region
    category: str
    persona: str
    turns: list[ConversationTurn] = Field(min_length=2)
    gold: CallGold

    def agent_turns(self) -> list[AgentTurn]:
        return [turn.root for turn in self.turns if isinstance(turn.root, AgentTurn)]

    def customer_turns(self) -> list[CustomerTurn]:
        return [turn.root for turn in self.turns if isinstance(turn.root, CustomerTurn)]


class ConversationDraft(StrictModel):
    """What the dialogue model writes: the turns and the gold. Identity and
    context fields (call, customer_id, session_index, channel, date, ...) are
    known to the pipeline and filled in by code, so a model's guess at them can
    never reject an otherwise good transcript."""

    turns: list[ConversationTurn] = Field(min_length=2)
    gold: CallGold


def conversation_id(scenario_id: str, call: str) -> str:
    return f"{scenario_id}__{call}"


def split_conversation_id(value: str) -> tuple[str, str]:
    """``"SCN-GEN-0001__call_2"`` -> ``("SCN-GEN-0001", "call_2")``; legacy ids map to call_1."""
    scenario_id, _, call = value.partition("__")
    return scenario_id, call or "call_1"
