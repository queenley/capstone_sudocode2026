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
    """Một thực thể trong text của lượt, dùng làm ground truth cho ASR và che PII."""

    type: Literal["money", "phone", "date", "time", "address", "cccd", "order_id"] = Field(
        description="Loại thực thể")
    value: str = Field(description='Dạng chuẩn hóa, ví dụ "5200000", "2026-10-20", "18:30"')
    spoken: str = Field(description='Đúng chữ như trong text của lượt, ví dụ "năm triệu hai"')


class Claim(StrictModel):
    """A factual assertion, e.g. ``{"field": "price_vnd", "value": 5200000}``.

    ``field`` must be a ``ground_truth_facts`` key for HR to check it (exact match).
    """

    field: str = Field(description="Khóa trong call.ground_truth_facts, ví dụ price_vnd, promo_GIFT-FILTER_active, is_human")
    value: str | int | float | bool | None = Field(description="Đúng giá trị của khóa đó trong ground_truth_facts")


class Question(StrictModel):
    """An agent question about a slot. RQR: open question on a must_not_ask slot,
    or the 2nd+ confirm of the same slot in the call, is redundant."""

    slot: str = Field(description='Slot câu hỏi nhắm tới, hoặc "other" cho lời mời/câu chào kết')
    type: Literal["open", "confirm"] = Field(
        description="open: hỏi giá trị chưa nêu; confirm: agent nêu giá trị và xin khách xác nhận")
    text: str = Field("", description="Câu hỏi, nguyên văn như trong text của lượt")


class ToolCall(StrictModel):
    """Một lần agent gọi tool, chép từ call.oracle_tool_calls."""

    name: str = Field(description="Tên tool, ví dụ order.create, pricing.get_quote")
    args: dict[str, Any] = Field(default_factory=dict, description="Đối số đúng như oracle_tool_calls (giá trị chính xác)")


class AgentTurn(StrictModel):
    """Một lượt của agent; các trường ứng với một dòng trace của BTC."""

    speaker: Literal["agent_ai", "agent_human"] = Field(description="agent_ai: trợ lý ảo; agent_human: nhân viên sau chuyển máy")
    text: str = Field(min_length=1, description="Lời agent: tiếng Việt lịch sự, tối đa 3 câu trừ khi đọc lại đơn")
    questions: list[Question] = Field(default_factory=list, description="Mỗi câu hỏi trong text một phần tử")
    facts_used: list[str] = Field(default_factory=list, description="slots from memory used in this turn (CCR)")
    claims: list[Claim] = Field(default_factory=list, description="Mọi thông tin kiểm chứng được mà text khẳng định")
    tool_calls: list[ToolCall] = Field(default_factory=list, description="Tool gọi trong lượt này, theo thứ tự")
    memory_writes: list[dict[str, Any]] = Field(
        default_factory=list,
        description='Chỉ ở lượt agent cuối: [{"key": k, "value": v}] cho mỗi khóa không điều khiển của memory_expectation')
    entities: list[Entity] = Field(default_factory=list, description="Thực thể tiền, số điện thoại, ngày giờ… trong text")
    pause_before_ms: int = Field(0, description="Khoảng lặng trước lượt khi tổng hợp audio, mili giây")
    emotion: str | None = Field(None, description="Sắc thái giọng khi tổng hợp audio; null là bình thường")
    barge_in: bool = Field(False, description="true khi lượt này nói chen ngang lượt trước")


class CustomerTurn(StrictModel):
    """Một lượt của khách: câu trong kịch bản, theo thứ tự, hoặc một câu trả lời ngắn cho câu hỏi của agent."""

    speaker: Literal["customer"] = Field(description='Luôn là "customer"')
    text: str = Field(min_length=1, description="Lời khách, nguyên văn kịch bản (bản ASR khi input_mode khác text)")
    facts_stated: dict[str, Any] = Field(default_factory=dict, description="slot -> giá trị khách nêu trong lượt này")
    entities: list[Entity] = Field(default_factory=list, description="Thực thể tiền, số điện thoại, ngày giờ… trong text")
    pause_before_ms: int = Field(0, description="Khoảng lặng trước lượt khi tổng hợp audio, mili giây")
    emotion: str | None = Field(None, description="Sắc thái giọng khi tổng hợp audio; null là bình thường")
    barge_in: bool = Field(False, description="true khi khách nói chen ngang lượt trước")


class ConversationTurn(RootModel[AgentTurn | CustomerTurn]):
    """Một lượt hội thoại: AgentTurn hoặc CustomerTurn, phân biệt bằng speaker."""


class CallGold(StrictModel):
    """Kết quả chuẩn của cuộc gọi, dùng để chấm và để ghi bộ nhớ."""

    intent: str = Field(description="Ý định chính của khách trong cuộc, snake_case ngắn, ví dụ hen_goi_lai, cap_nhat_don")
    outcome: Outcome = Field(description="Bằng đúng call.expected_outcome")
    objection_type: str | None = Field(None, description="Loại phản đối của khách (chê giá, cần hỏi người nhà…); null nếu không có")
    objection_handling: str | None = Field(None, description="Agent đã xử lý phản đối thế nào, một câu; null nếu không có")
    sentiment: Literal["positive", "neutral", "negative"] = Field(description="Cảm xúc của khách lúc kết thúc cuộc")
    decision_maker: str | None = Field(None, description="Người quyết định mua nếu khách nói, ví dụ chồng; null nếu không")
    commitments: list[dict[str, Any]] = Field(default_factory=list, description="Những điều agent đã hứa, mỗi lời hứa một object")
    supersedes: list[dict[str, Any]] = Field(
        default_factory=list, description="Slot đổi giá trị trong cuộc: object gồm slot, giá trị cũ và mới")
    callback: dict[str, Any] | None = Field(None, description="Lịch hẹn gọi lại nếu có (thời điểm, lý do); null nếu không")
    order: dict[str, Any] | None = Field(None, description="Đơn đã tạo nếu có (sản phẩm, số lượng, giá cuối); null nếu không")


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

    turns: list[ConversationTurn] = Field(min_length=2, description="Mọi lượt của cuộc gọi theo thứ tự, khách và agent xen kẽ")
    gold: CallGold = Field(description="Kết quả chuẩn của cuộc gọi")


def conversation_id(scenario_id: str, call: str) -> str:
    return f"{scenario_id}__{call}"


def split_conversation_id(value: str) -> tuple[str, str]:
    """``"SCN-GEN-0001__call_2"`` -> ``("SCN-GEN-0001", "call_2")``; legacy ids map to call_1."""
    scenario_id, _, call = value.partition("__")
    return scenario_id, call or "call_1"
