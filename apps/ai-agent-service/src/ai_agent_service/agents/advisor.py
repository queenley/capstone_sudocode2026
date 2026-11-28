"""AdvisorAgent: drafts what the shop says on one turn.

A ReAct loop, ``langchain.agents.create_agent``: a model node calls the
lane's tools, a tool node runs them, until the model answers without a tool
call, at most twenty tool calls and eight model calls a turn (an order of
several items needs a quote, a stock check and an order each). The model
comes from config through :class:`~src.agents.base.BaseAgent`; the tools from
MCP under the ``advisor`` role. The knowledge base is not one of them: the
harness retrieves the turn's passages before the advisor runs
and they arrive in the context.

**Stateless** (principle 2). The agent holds no checkpointer and nothing
between calls: the hot graph hands it a slice of its state as
:class:`AgentContext` and the recent turns as messages, and gets back a
draft and the tool results. Its ReAct messages live only inside one call.
The conversation itself is the hot graph's ``messages``, checkpointed there
and nowhere else, so there are never two copies of a call to keep in step.

Around the loop, as middleware:

- the context prompt, assembled in a fixed order and cut from the
  bottom (:mod:`~src.components.context.budget`);
- one retry of a failed model call, a cap on model calls and on tool calls;
- the lane's tools only (``config/lanes.yaml``);
- **the guardrail before act**: a write tool's arguments are checked before
  it runs, and a Handoff Brief is completed from what the harness knows
  (:mod:`~src.components.guardrails.actions`);
- the tool guard: timeout, retry, circuit breaker, the day of the call and
  the customer's phone filled in, internal fields removed.

**Output** is plain text marking the brief lines it used, ``[B3]``; the
harness strips the marks before anyone reads the reply and keeps them for
tracing. Plain text rather than a structured object so the
same reply can later be streamed sentence by sentence.
"""

from __future__ import annotations

import json
import re
import logging
import os
import time
import uuid
from datetime import timedelta
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Mapping, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware.types import ToolCallRequest
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool

from ..components import clock
from ..components.context import focus
from ..components.context.budget import Section, assemble
from ..components.guardrails import actions, purchase
from ..components.guardrails.hard import MAX_SENTENCES
from ..components.memory.brief import BriefLine
from ..components.intake import commerce, pii
from ..components.intake.itn import format_vnd
from ..components.intake.text import plain
from ..config.config_manager import get_lanes, load_prompt, load_prompt_yaml
from ..llm import tracing
from ..observability import stopwatch
from ..llm.callback_handler import text_of
from ..mcp.client import dotted
from ..components.context import skills as skill_book
from ..mcp.tools import (ChainLookupMiddleware, LaneToolsMiddleware, StrictToolsMiddleware,
                         ToolGuardMiddleware, ADVISE, CHAINED, QUOTE, SEARCH, SPLIT, STOCK, envelope_of, order_split_cod,
                         parse_envelope, order_arguments, product_advise, product_advise_on, without_nulls)
from .base import BaseAgent
from .policy import EARLY_INTENTS, NO_HANDOFF, band

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentContext:
    """The advisor's slice of the state for one turn.

    Runtime context, not graph state: LangGraph hands it to middleware as
    ``runtime.context`` and never writes it to a checkpoint, which is why the
    customer's raw phone number may travel here, for the tool guard to fill
    in, and nowhere else the model can read.
    """

    call_id: str
    customer_id: str | None = None
    #: The platform customer the web conversation belongs to (logged in or verified), for the
    #: ``account_*`` tools; filled in by the harness, never shown to the model.
    account_id: str | None = None
    #: How to address the customer, when the tier allows knowing it: "chị Hoa".
    address_as: str | None = None
    tier: str = "UNKNOWN"
    lane: str = "NEW"
    mode: str = "speak"
    phase: str = "turn"
    channel: str = "web"
    now: datetime | None = None
    #: The ``on`` argument of every tool: the day of the call.
    on: str | None = None
    #: Brief lines the tier allows the model to see.
    brief_lines: tuple[BriefLine, ...] = ()
    #: Never cut, always first.
    warnings: tuple[str, ...] = ()
    must_not_ask: tuple[str, ...] = ()
    working_summary: str | None = None
    #: The call's working state, the last thing the model reads (``pipeline.hot.call_state``).
    call_state: tuple[str, ...] = ()
    #: Why the previous draft of this turn was blocked, for a regeneration.
    block_reasons: tuple[str, ...] = ()
    #: The sentences of this answer the customer already heard when a later one was blocked:
    #: the regeneration goes on from them instead of starting over.
    already_said: tuple[str, ...] = ()
    #: Tool results already gathered this turn, so a regeneration need not ask again.
    tool_results: tuple[dict[str, Any], ...] = ()
    #: Today's price per sku from every quote in this call, for the order check.
    quotes: Mapping[str, int] = field(default_factory=dict)
    #: Orders of more than one unit priced this call: units key to ``[[sku, unit price], ...]`` (``pricing.quote_order``).
    order_quotes: Mapping[str, Any] = field(default_factory=dict)
    known_orders: frozenset[str] = frozenset()
    #: The orders ``order_status`` showed in earlier turns of the call, with status and date (the guard's return window).
    order_records: tuple[Mapping[str, Any], ...] = ()
    #: Order lines created earlier in this call (``actions.placed_lines``): the COD limit is on the whole order.
    placed_lines: tuple[Mapping[str, Any], ...] = ()
    #: The customer's phone, raw. Filled into tools by the harness; never shown to the model.
    customer_phone: str | None = None
    shared_phone: bool = False
    vault: pii.Vault = field(default_factory=pii.Vault, repr=False, compare=False)
    #: This call's address tokens and the addresses behind them, raw, the
    #: latest last: filled into the tools that take an address.
    addresses: Mapping[str, str] = field(default_factory=dict)
    #: What the harness fills into a Handoff Brief.
    handoff_defaults: Mapping[str, Any] = field(default_factory=dict)
    switches: Mapping[str, Any] = field(default_factory=dict)
    #: This turn, for the idempotency key of a write tool.
    turn_id: str | None = None
    #: The turn's passages from the knowledge base, already filtered by the
    #: harness: a restricted one carries no text, one not in force never arrives.
    knowledge: tuple[Mapping[str, Any], ...] = ()
    #: What the search found when no passage is shown: that none was relevant.
    knowledge_note: str | None = None
    #: What ``route`` adds to the lane's instruction (PB-10, PB-11, a spoken channel).
    notes: tuple[str, ...] = ()
    #: Why the lane is CONFIRM_IDENTITY: "probable" (a shared number's question is the harness's own).
    confirm_reason: str | None = None
    #: Product codes this call may order, from the brief; codes in this
    #: turn's tool results are added by the before-write check itself.
    trusted_skus: frozenset[str] = frozenset()
    #: The turn's flags from intake (a request for a person, a complaint, ...).
    flags: Mapping[str, Any] = field(default_factory=dict)
    #: The products tools showed earlier in this call: ``{sku, name, price_vnd}``.
    seen_products: tuple[Mapping[str, Any], ...] = ()
    #: The latest result per tool and subject from earlier turns: what need not be asked again.
    earlier_results: tuple[Mapping[str, Any], ...] = ()
    #: Moments a call back is already booked for in this call, earlier turns included.
    callbacks_booked: tuple[str, ...] = ()
    #: ``(sku, unit price, qty)`` of the basket being chosen, when all of it is quoted.
    basket_lines: tuple[tuple[str, int, int], ...] = ()
    #: The orders earlier turns of this call created: ``{order_id, sku}``.
    created_orders: tuple[Mapping[str, Any], ...] = ()
    #: The changes ``order_update`` made in earlier turns of this call: ``{order_id, action, new_variant_sku}``.
    updated_orders: tuple[Mapping[str, Any], ...] = ()
    #: Last turn's write calls the guard refused, and what it said to put to the customer (``nodes._offered``).
    offered: tuple[Mapping[str, Any], ...] = ()
    #: How an unknown customer calls themselves, and whether the agent asked.
    self_called: str | None = None
    honorific_asked: bool = False
    #: The customer's words this turn and the agent's last reply, tokenised:
    #: what the before-write checks read (a deletion needs both).
    customer_said: str | None = None
    last_agent_said: str | None = None
    deletion_asked: bool | None = None
    pending_purchase: Mapping[str, Any] | None = None
    #: The last few messages, ``(speaker, text)`` tokenised: what the PolicyAgent reads when an action
    #: depends on what the customer means (a transfer, a deletion, one more order).
    recent: tuple[tuple[str, str], ...] = ()
    #: ``PolicyAgent.judge``: what the customer means for one action, None without an answer.
    #: Why a tool with an effect must wait: the flags of what was just said (``pipeline/hot/review.py``).
    review_flags: Callable[[], Awaitable[list[str]]] | None = field(default=None, repr=False, compare=False)
    #: This turn's agreement to an order: the authorized draft, and the read-back still to be said.
    consent: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    #: The run only warms the provider's prompt cache and the connection (:meth:`AdvisorAgent.warm`): no tool may run.
    warming: bool = False
    #: A rewrite of an answer that used one model call: its one call answers, no tool (two calls a turn at most).
    answer_only: bool = False
    #: The skills loaded for the task on: ``load_skill`` adds to it, the next model call reads it.
    skills: list[str] = field(default_factory=list, repr=False, compare=False)
    #: ``PolicyAgent.probability``: what the customer means for one action, None without an answer.
    judge: Callable[[str, Mapping[str, Any]], Awaitable[float | None]] | None = field(default=None, repr=False,
                                                                                        compare=False)
    #: The PolicyAgent's answers to ``EARLY_INTENTS``, asked as the turn started (plan 002, step 3): awaited, not asked.
    early_intents: Callable[[], Awaitable[Mapping[str, float]]] | None = field(default=None, repr=False, compare=False)
    #: The same answers once they are in, for a model call that starts after them (plan 002, C4).
    early_answers: dict[str, float] = field(default_factory=dict, repr=False, compare=False)
    #: Every PolicyAgent probability this turn's actions were decided on, for the diagnostics and calibration.
    intent_probabilities: dict[str, float | None] = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Draft:
    """One run's result: the text, what the tools said, and what it cost."""

    text: str
    tool_results: list[dict[str, Any]]
    model: str | None
    model_calls: int
    seconds: float


class AdvisorFailure(RuntimeError):
    """A failed model must not erase tools that already executed."""

    def __init__(self, error: Exception, partial: Draft) -> None:
        super().__init__(type(error).__name__)
        self.error = error
        self.partial = partial


@dataclass(frozen=True)
class AdvisorEvent:
    """One thing a streamed run produced: a chunk of the answer, a tool round starting, its results, or the end."""

    kind: Literal["text", "tool_started", "tools", "done"]
    #: For ``text``, the chunk; for ``tool_started``, the name of the tool called.
    text: str = ""
    draft: Draft | None = None
    #: For ``tools``: every tool call of the run so far, as :attr:`Draft.tool_results` lists them.
    results: tuple[dict[str, Any], ...] = ()


#: "Luật làm đúng từ đầu": every rule the organisers' documents
#: and grader make knowable is in the first release (principle 8), each
#: also enforced in code where code can (the guard, the before-write check).
#: The codes in brackets are the policy sections the rule comes from.
HARD_RULES = load_prompt("advisor/rules.md")

#: The lane notes, the identity question, the opening and the channel notes.
_NOTES = load_prompt_yaml("advisor/notes.yaml")
LANE_NOTES: dict[str, str] = _NOTES["lanes"]

#: CONFIRM_IDENTITY by its reason: one question, nothing private before it is answered.
#: A shared number has no note: its question is the harness's fixed line, and no model is called.
CONFIRM_NOTES: dict[str, str] = _NOTES["confirm_identity"]

#: Whether the customer has a Call Brief -> the opening line's instruction.
OPENING = {True: _NOTES["opening"]["with_brief"], False: _NOTES["opening"]["without_brief"]}

COPILOT_NOTE = _NOTES["copilot"]

# A message is read: an amount the customer may compare or copy is written in figures.
CHAT_NOTE = _NOTES["chat"]

# A phone call is listened to, not read: a long answer is one the caller talks
# over, and on a laptop's speakers the echo canceller then swallows them.
SPOKEN_NOTE = _NOTES["spoken"]

# Plan 002, C4: the early check is all but certain nobody asked for a person; said in the turn's part of the prompt,
# so the tools offered, and the provider's cache of them, stay the same.
NO_HANDOFF_NOTE = ("Hệ thống đã xét lượt này: khách không xin gặp người và không cần chuyển máy; không gọi "
                   "handoff_transfer, trả lời bằng tool và tài liệu.")

# Plan 002, B3: which tool a question that needs weighing goes to.
ADVISE_NOTE = _NOTES["advise"]

# Plan 002, A1: a line before a lookup, in the round that calls it, so the customer is not left in silence.
PREAMBLE_NOTE = _NOTES["preamble"]


#: Passages shown to the model per turn (five retrieved, three allowed in).
KNOWLEDGE_SHOWN = 3
#: Passages read on earlier turns of the call that stay shown, the latest first.
EARLIER_SHOWN = 3


def preamble_asked(context: AgentContext) -> bool:
    """Whether this turn asks for the line before a tool call (``preamble``, OpenAI's tool preambles): the lanes where
    the advisor does business, not copilot."""
    return context.lane in ("NEW", "CONTINUITY") and context.mode != "copilot"


#: The preamble note again at the end of the turn's context: OpenAI's GPT-4.1 guide places instructions both before
#: and after a long context; the note alone, near the start, was skipped on follow-up lookups (2026-11-26).
PREAMBLE_REMINDER = ("Nếu tin nhắn đầu của lượt này cần gọi tool: viết câu mở theo <cau_mo_truoc_tool> trước, "
                     "rồi mới gọi tool, trong cùng tin nhắn.")


def lane_instruction(context: AgentContext) -> str:
    """The lane's instruction with the notes ``route`` and the channel add."""
    if context.lane == "CONFIRM_IDENTITY":
        text = CONFIRM_NOTES.get(context.confirm_reason or "probable", CONFIRM_NOTES["probable"])
    else:
        text = LANE_NOTES.get(context.lane, "").format(must_not_ask=", ".join(context.must_not_ask) or "không có")
    extra = list(context.notes)
    if context.mode == "copilot":
        extra.append(COPILOT_NOTE)
    if context.channel == "hotline":
        extra.append(SPOKEN_NOTE)
    else:
        extra.append(CHAT_NOTE)
    # With the advisor's own words on each call (``say``, plan 003) a line written before the call is not asked for:
    # its facts came before the lookup that backs them, and the guard stopped them (2026-11-16).
    if preamble_asked(context):
        extra.append(PREAMBLE_NOTE)
    if product_advise_on() and context.lane in ("NEW", "CONTINUITY"):
        extra.append(ADVISE_NOTE)
    return "\n".join([text, *extra]).strip()


def system_prompt(context: AgentContext, *, max_tokens: int = 3000) -> tuple[str, tuple[str, ...]]:
    """The whole system prompt as one text, and the sections that were cut: for a provider that takes one message."""
    static, turn, cut = prompt_parts(context, max_tokens=max_tokens)
    return "\n\n".join(part for part in (static, turn) if part), cut


def prompt_parts(context: AgentContext, *, max_tokens: int = 3000) -> tuple[str, str, tuple[str, ...]]:
    """What never changes, what this turn adds, and the sections that were cut.

    The first part is the rules and the skills. The second, in this order: the day, warnings, the lane, the
    products and orders of the call, the brief lines the tier allows, the summary of older turns (the last four
    travel as messages), the turn's knowledge passages, the playbook entries of the situation, results of earlier
    turns, tool results already gathered (a regeneration), why the previous draft was blocked. Required evidence
    survives the soft budget, which applies to the second part; optional sections are admitted in priority order.
    """
    inline = not skill_book.on_demand()
    offered = context.lane in ("CONTINUITY", "NEW")
    static = "\n\n".join(part for part in (HARD_RULES, skill_book.section(context.skills, offered=offered) if inline else "") if part)
    brief = "\n".join(f"{line.id}. {line.text}" for line in context.brief_lines)
    policy, playbook = shown_passages(context.knowledge)
    sections = [
        Section("skills", "" if inline else skill_book.section(context.skills, offered=offered)),
        Section("today", _today(context)),
        Section("warnings", "\n".join(f"CẢNH BÁO: {w}" for w in context.warnings)),
        Section("lane", (
            # Without the day, "tối mai" has no date and the model invents a year.
            (f"Bây giờ là {clock.moment_label(context.now)}; tính ngày giờ khách nói (mai, thứ Bảy) từ đây.\n" if context.now else "")
            + f"Lane: {context.lane}. Mức xác minh danh tính: {context.tier}. Kênh: {context.channel}."
            + (f" Hồ sơ đứng tên: {context.address_as}." if context.address_as else _address_note(context))
            + f"\n{lane_instruction(context)}"
        ).strip()),
        Section("products", _products_block(context.seen_products)),
        Section("earlier", _earlier_block(context.earlier_results)),
        Section("basket", _basket_block(context.basket_lines, context.order_quotes)),
        Section("orders", _orders_block(context.created_orders, context.updated_orders)),
        Section("offered", _offered_block(context.offered)),
        Section("brief", f"Call Brief:\n{brief}" if brief else ""),
        Section("summary", f"Tóm tắt các lượt trước:\n{context.working_summary}" if context.working_summary else ""),
        Section("knowledge", "\n".join(x for x in (_knowledge_block("Tài liệu liên quan", policy),
                                                    context.knowledge_note) if x)),
        Section("playbook", _knowledge_block("Kinh nghiệm xử lý đã được duyệt", playbook)),
        Section("tool_results", _tool_block(context.tool_results)),
        Section("opening", OPENING[bool(context.brief_lines)] if context.phase == "opening" else ""),
        Section("blocked", _blocked_block(context)),
        Section("no_handoff", NO_HANDOFF_NOTE if (context.early_answers.get("handoff") is not None
                                                  and context.early_answers["handoff"] <= NO_HANDOFF
                                                  and context.lane != "HANDOFF") else ""),
        Section("call_state", _state_block(context)),
    ]
    pack = assemble(sections, max_tokens=max_tokens)
    return static, pack.text, pack.cut


def _state_block(context: AgentContext) -> str:
    """The call's state, then the request: what the answer has to be about."""
    parts = []
    if context.call_state:
        parts.append("Trạng thái cuộc:\n" + "\n".join(f"- {line}" for line in context.call_state))
    if preamble_asked(context):
        parts.append(PREAMBLE_REMINDER)
    if context.customer_said and context.lane in ("CONTINUITY", "NEW"):
        parts.append(f'Yêu cầu hiện tại của khách: "{context.customer_said}". Làm đúng yêu cầu này trước, không trả lời '
                     "sang việc khác; thông tin ở trên chỉ dùng khi phục vụ yêu cầu này.")
    return "\n".join(parts)


def shown_passages(knowledge: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """What the model reads of a turn's passages: the first three from the documents, one campaign entry for this
    call's product if none of the three is one, the rules a published lesson cites (``pinned``), the latest passages
    read earlier in the call (``earlier``), what explains a withheld passage, and the playbook entries. None of these
    takes the place of the first three.

    The guard checks a reply against these and no others: a number from a
    passage the model never saw cannot be a number it read.
    """
    earlier = [p for p in knowledge if p.get("earlier")][:EARLIER_SHOWN]
    documents = [p for p in knowledge if p.get("source") != "playbook" and not p.get("explains") and not p.get("earlier")]
    first = documents[:KNOWLEDGE_SHOWN]
    campaign = [] if any(p.get("campaign") for p in first) else [
        p for p in documents[KNOWLEDGE_SHOWN:] if p.get("campaign") and p.get("for_product")][:1]
    pinned = [p for p in documents[KNOWLEDGE_SHOWN:] if p.get("pinned") and p not in campaign]
    policy = [*first, *campaign, *pinned, *earlier, *(p for p in knowledge if p.get("explains"))]
    playbook = [p for p in knowledge if p.get("source") == "playbook"]
    return policy, playbook


def _knowledge_block(heading: str, passages: Sequence[Mapping[str, Any]]) -> str:
    """Passages as the model reads them: a restricted one as a refusal."""
    if not passages:
        return ""
    lines = []
    for passage in passages:
        code = passage.get("chunk_id") or "?"
        title = passage.get("title") or ""
        if passage.get("restricted"):
            lines.append(passage.get("instruction") or f"Đoạn [{code}] là thông tin nội bộ: không đọc, không trích.")
            continue
        label = f"{title}: " if title else ("(đã đọc ở lượt trước) " if passage.get("earlier") else "")
        lines.append(f"[{code}] {label}{str(passage.get('text') or '').strip()}")
    return f"{heading}:\n" + "\n".join(lines)


def _address_note(context: AgentContext) -> str:
    """How to address a customer the shop does not know yet."""
    if context.self_called:
        return f" Khách tự xưng là {context.self_called}: gọi khách là {context.self_called}, xưng em, dùng nhất quán."
    if context.honorific_asked:
        return " Chưa biết danh xưng và em đã hỏi rồi: gọi anh/chị, không hỏi lại."
    # The rule above reads only a few fixed forms ("tôi là chị Lan"); the model reads the rest of the customer's words.
    return (" Chưa biết danh xưng: nếu trong lời khách đã tự xưng (\"anh muốn…\", \"chị hỏi…\", \"số của cô là…\") thì "
            "gọi khách đúng như vậy và không hỏi. Chỉ khi khách chưa tự xưng: tạm gọi anh/chị, ở lượt thứ hai hoặc khi "
            "xin thông tin đặt hàng hỏi đúng một lần, gộp vào câu hỏi đang cần hỏi: \"Dạ cho em hỏi mình xưng hô là anh "
            "hay chị ạ?\"")


WEEKDAYS = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")


def _today(context: AgentContext) -> str:
    """The day of the call, so "mai" or "thứ Ba tuần sau" need no guess."""
    if context.now is None:
        return ""
    now, tomorrow = context.now, context.now + timedelta(days=1)
    return (f"Hôm nay: {WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y}, {now:%H:%M}. "
            f"Ngày mai: {WEEKDAYS[tomorrow.weekday()]}, {tomorrow:%d/%m/%Y}.")


def _blocked_block(context: AgentContext) -> str:
    """Why the last draft was blocked, and when part of the answer was already said, what to go on from."""
    if not context.block_reasons:
        return ""
    reasons = "; ".join(context.block_reasons)
    if context.already_said:
        return (f"Khách đã nghe em nói: «{' '.join(context.already_said)}». Em dừng lại vì: {reasons} "
                "Nói tiếp phần còn lại của câu trả lời, không lặp lại phần khách đã nghe; cần tool thì gọi trước khi nói.")
    return f"Câu trả lời trước của em đã bị chặn vì: {reasons} Hãy soạn lại, tránh đúng những điểm đó."


def _orders_block(orders: Sequence[Mapping[str, Any]], changes: Sequence[Mapping[str, Any]] = ()) -> str:
    """The orders this call created and the changes it made: neither is done a second time."""
    parts = []
    if orders:
        lines = [f"- {o['order_id']}" + (f": {o['sku']}" if o.get("sku") else "") for o in orders]
        parts.append("Đơn đã tạo trong cuộc này (khách bổ sung hay đổi địa chỉ thì gọi order_update update_address "
                     "trên đơn đó, không tạo đơn mới; không có tool đổi thanh toán):\n" + "\n".join(lines))
    if changes:
        lines = [f"- {c.get('order_id')}: {c.get('action')}" + (f" sang {c['new_variant_sku']}" if c.get("new_variant_sku") else "")
                 + (f" về {c['new_address']}" if c.get("new_address") else "") for c in changes]
        parts.append("Thay đổi đã thực hiện trong cuộc này (đã xong, không gọi order_update lại cho cùng thay đổi; "
                     "khách hỏi lại thì báo kết quả và phí của lần đó):\n" + "\n".join(lines))
    return "\n".join(parts)


def _products_block(products: Sequence[Mapping[str, Any]]) -> str:
    """The products tools showed earlier in this call, with their codes: what a later turn quotes and orders."""
    if not products:
        return ""
    lines = [f"- {p['sku']}: {p.get('name') or '?'}" for p in products]
    return "Sản phẩm đã tra trong cuộc này (mã chính xác: báo giá, kiểm kho, đặt đơn dùng đúng mã này):\n" + "\n".join(lines)


def _earlier_block(results: Sequence[Mapping[str, Any]]) -> str:
    """Results of earlier turns: the messages keep what was said, not what the tools answered."""
    if not results:
        return ""
    lines = [f"- {r.get('tool')}: {r.get('result')}" for r in results]
    return ("Đã tra trong cuộc này (kết quả tool của các lượt trước; trả lời từ đây, chỉ gọi lại khi đổi sản phẩm, biến "
            "thể, số lượng, địa chỉ, giỏ hàng hoặc khi sắp đặt đơn):\n" + "\n".join(lines))


def _offered_block(offered: Sequence[Mapping[str, Any]]) -> str:
    """Last turn's refused write calls: the offer the customer is now answering, with its exact values."""
    if not offered:
        return ""
    # A transfer's brief is the harness's to fill: its arguments would only lengthen the prompt.
    lines = [f"- {o.get('tool')} {json.dumps({k: v for k, v in (o.get('args') or {}).items() if k != 'brief'}, ensure_ascii=False)}"
             f": {o.get('said')}" for o in offered]
    return ("Lượt trước hệ thống chưa làm các việc sau và em đã đề xuất lại với khách theo lý do này. Khách đồng ý thì "
            "gọi lại đúng tool với giá trị đã đề xuất (ngày giờ, mã, số tiền), không tính lại từ đầu. Lý do là còn chờ "
            "khách cho một thông tin (số điện thoại, size, địa chỉ) thì chỉ gọi lại khi lời mới nhất của khách có thông "
            "tin đó; chưa có thì xin lại một câu, không gọi tool:\n" + "\n".join(lines))


def _basket_block(lines: Sequence[tuple[str, int, int]], order_quotes: Mapping[str, Any] | None = None) -> str:
    """The basket's total, added up here: a model that adds gets it wrong often enough to matter. With a quote of the
    whole basket, its unit prices (a second machine is cheaper beside the first) and, above the COD limit, the two
    orders a split would be (QT-01): the model only places them, it does not arrange or price them."""
    if not lines:
        return ""
    units = (order_quotes or {}).get(purchase.units_key([{"sku": sku, "qty": qty} for sku, _, qty in lines]))
    if units:
        priced = [(str(sku), int(price)) for sku, price in units]
        items = ", ".join(f"{sku} {format_vnd(price)}" for sku, price in priced)
        text = (f"Tổng giỏ (hệ thống đã cộng, theo báo giá cả giỏ): {format_vnd(sum(p for _, p in priced))}, gồm {items}. "
                "Khách hỏi tổng thì viết {tổng}.")
        if sum(p for _, p in priced) > actions.COD_LIMIT_VND:
            text += (f" Giỏ vượt {format_vnd(actions.COD_LIMIT_VND)} nên một đơn COD không nhận; khách đồng ý tách thì gọi "
                     "order_split_cod với cả giỏ, hệ thống tự xếp các đơn và giữ ưu đãi mua kèm (QT-01).")
        return text
    items = ", ".join(f"{sku} {format_vnd(price)} x {qty}" for sku, price, qty in lines)
    return f"Tổng giỏ (hệ thống đã cộng): {format_vnd(sum(p * q for _, p, q in lines))}, gồm {items}. Khách hỏi tổng thì viết {{tổng}}."


def _tool_block(results: Sequence[Mapping[str, Any]]) -> str:
    if not results:
        return ""
    lines = [f"- {r['name']}({json.dumps(r.get('args') or {}, ensure_ascii=False)}) -> "
             f"{json.dumps(r.get('result'), ensure_ascii=False)}" for r in results]
    return "Kết quả tool đã có trong lượt này (dùng lại, không gọi lại tool):\n" + "\n".join(lines)


#: Opens what the harness adds after the customer's words, so the model does not take it for them.
TURN_CONTEXT = "Ngữ cảnh của lượt này, do hệ thống cung cấp, không phải lời khách:\n"


def with_turn_context(messages: Sequence[Any], turn: str) -> list[Any]:
    """*messages* with the turn's context right after the customer's last message.

    From GPT-5.6 a cache lookup stops only at boundaries: the end of the first run of developer messages, and the end
    of a user message or of a group of tool results (developers.openai.com/api/docs/guides/prompt-caching). So the
    first message holds only what never changes. Context placed before the customer's message would join that first
    run on a call's first turn and move the boundary; after it, every turn keeps it, and the customer's earlier
    messages stay boundaries too.
    """
    if not turn:
        return list(messages)
    context = SystemMessage(content=TURN_CONTEXT + turn)
    last = max((i for i, message in enumerate(messages) if isinstance(message, HumanMessage)), default=len(messages) - 1)
    return [*messages[:last + 1], context, *messages[last + 1:]]


class ContextPromptMiddleware(AgentMiddleware):
    """The system message for each model call, built from the run's context.

    Both hooks are implemented on purpose: the framework does not derive one
    from the other, and the service is async.
    """

    def __init__(self, model_limit: int = 8, *, split: bool = False) -> None:
        super().__init__()
        self.model_limit = model_limit
        self.split = split

    def _with_prompt(self, request: ModelRequest) -> ModelRequest:
        context = getattr(getattr(request, "runtime", None), "context", None)
        if not isinstance(context, AgentContext):
            return request
        static, turn, cut = prompt_parts(context)
        if cut:
            logger.info("Prompt of call %s turn %s cut: %s", context.call_id, context.turn_id, cut)
        turn = pii.tokenise(turn, context.vault)
        if not skill_book.on_demand():
            # Every skill is in the prompt: nothing to load, and no model round spent on it.
            request = request.override(tools=[t for t in request.tools if getattr(t, "name", None) != LOAD_SKILL])
        last = self._is_last(request)
        if last and not context.warming:
            turn += ("\nĐây là lần viết cuối của lượt: không gọi thêm tool. Trả lời từ kết quả đã có, tối đa hai câu trừ khi đọc lại đơn, "
                     "không nhắc lại câu mở. Còn thiếu một điều thì hỏi hoặc xác nhận đúng điều đó, việc tiếp theo "
                     "để lượt sau. Không nói đã làm khi chưa có kết quả tool thành công.")
        if self.split:
            request = request.override(system_message=SystemMessage(content=static),
                                       messages=with_turn_context(request.messages, turn))
        else:
            prompt = "\n\n".join(part for part in (static, turn) if part)
            request = request.override(system_message=SystemMessage(content=prompt))
        # No tool, without taking them away: a changed tool list would miss the prompt cache.
        return request.override(tool_choice="none") if last else request

    def _is_last(self, request: ModelRequest) -> bool:
        context = getattr(getattr(request, "runtime", None), "context", None)
        return (request.state.get("run_model_call_count", 0) >= self.model_limit - 1
                or bool(getattr(context, "warming", False)) or bool(getattr(context, "answer_only", False)))

    @staticmethod
    def _answer_only(response: Any) -> Any:
        """The last call offers no tool; a model that calls one anyway ends the run with what it wrote."""
        for message in getattr(response, "result", None) or []:
            if isinstance(message, AIMessage) and message.tool_calls:
                message.tool_calls = []
        return response

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        response = handler(self._with_prompt(request))
        return self._answer_only(response) if self._is_last(request) else response

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        with stopwatch.span("model"):
            response = await handler(self._with_prompt(request))
        return self._answer_only(response) if self._is_last(request) else response


def declared_arguments(tool: Any, args: Mapping[str, Any]) -> dict[str, Any]:
    """*args* without those *tool* does not declare.

    A model carries one tool's arguments over to another (``payment`` from ``order_create`` to ``pricing_get_quote``,
    a brief's ``escalation_reason`` beside the brief). The server refuses the whole call for it, in a shape the model
    cannot read, so one stray word costs the customer the quote.
    """
    declared = getattr(tool, "args", None)
    if not declared:
        return dict(args)
    return {key: value for key, value in args.items() if key in declared}


def _asked_together(request: Any) -> list[str]:
    """The tools the model asked for in the round this call belongs to, by wire name."""
    state = getattr(request, "state", None) or {}
    call_id = (request.tool_call or {}).get("id")
    for message in reversed(list(state.get("messages") or [])):
        calls = getattr(message, "tool_calls", None) or []
        if any(c.get("id") == call_id for c in calls):
            return [str(c.get("name")) for c in calls]
    return []


class ActionGuardMiddleware(AgentMiddleware):
    """The guardrail before act: a write tool runs only if its arguments pass.

    What the write needs and a tool can tell, the guard looks up itself rather than refusing the call back to the model
    (plan 003, a second model round each time): today's quote of the order (``pricing_get_quote``, or
    ``pricing_quote_order`` for more than one unit), the stock of the variant an exchange asks for
    (``inventory_check``). Those calls run through the same tool guard as any other and are carried on the write's
    result (``inner``), so the trace records them. An order this call already created is said back
    (``ALREADY_CREATED``), not booked twice.
    """

    def __init__(self, tools: Sequence[Any] = (), guard: Any = None) -> None:
        super().__init__()
        self._tools = {getattr(t, "name", None): t for t in tools}
        self._guard = guard

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        with stopwatch.span("tools"):
            if (request.tool_call or {}).get("name") == SPLIT:
                return await self._split(request)
            return await self._guarded(request, handler)

    async def _split(self, request: Any) -> ToolMessage:
        """:data:`SPLIT`, the team's tool: the basket priced as one, arranged into COD orders each within the limit
        (``actions.cod_split``), and each order put through ``order_create`` exactly as if the model had called it: its
        read-back, the customer's yes, the signed consent. What ran is recorded as the organisers' calls (``inner``)."""
        call = request.tool_call
        args = {k: v for k, v in (call.get("args") or {}).items() if v not in (None, "", [])}
        lines = [{"sku": str(l["sku"]), "qty": int(l.get("qty") or 1)} for l in args.get("lines") or []
                 if isinstance(l, Mapping) and l.get("sku")]
        inner: list[dict[str, Any]] = []

        def answer(envelope: Mapping[str, Any]) -> ToolMessage:
            return ToolMessage(content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=SPLIT,
                               additional_kwargs={"inner": inner})

        quoted = await self._look_up("pricing_quote_order", {
            "lines": lines, **({"address": args["address"]} if args.get("address") else {})}, request) if lines else None
        if quoted:
            inner.append(quoted)
        units = [(str(u.get("sku")), int(u["final_price_vnd"])) for u in
                 ((parse_envelope((quoted or {}).get("content")) or {}).get("data") or {}).get("units") or []
                 if isinstance(u.get("final_price_vnd"), int)]
        split = actions.cod_split(units)
        if not split:
            fits = units and sum(p for _, p in units) <= actions.COD_LIMIT_VND
            return answer({"ok": False, "error": {"code": "PRECONDITION", "retryable": False, "message": (
                "Giỏ không vượt 10.000.000đ: đặt bằng order_create, không cần tách." if fits else
                "Không xếp được thành các đơn COD dưới 10.000.000đ; đề nghị khách chuyển khoản.")}})
        orders = []
        for group, (mine, other) in enumerate(((split[0], split[1]), (split[1], split[0])), start=1):
            order = ({"sku": mine[0][0], "qty": 1, "price_vnd": mine[0][1]} if len(mine) == 1 else
                     {"lines": [{"sku": s, "qty": 1, "price_vnd": p} for s, p in mine]})
            order.update({"payment": "COD", "order_group": str(group), "basket_skus": [s for s, _ in other],
                          **({"address": args["address"]} if args.get("address") else {})})
            sub = {"name": "order_create", "args": order, "id": f"{call['id']}-{group}", "type": "tool_call"}

            async def run(inner_request: Any) -> Any:
                return await inner_request.tool.ainvoke(inner_request.tool_call)

            async def through_guard(inner_request: Any) -> Any:
                return await self._guard.awrap_tool_call(inner_request, run)

            placed = await self._guarded(ToolCallRequest(tool_call=sub, tool=self._tools.get("order_create"),
                                                         state=request.state, runtime=request.runtime), through_guard)
            extra = getattr(placed, "additional_kwargs", {}) or {}
            inner += list(extra.get("inner") or [])
            inner.append({"name": "order_create", "args": extra.get("args") or order,
                          "content": getattr(placed, "content", ""), "blocked_by": extra.get("blocked_by")})
            orders.append({"order_group": str(group), "items": [s for s, _ in mine],
                           "total_vnd": sum(p for _, p in mine), "result": parse_envelope(getattr(placed, "content", ""))})
        done = all((o["result"] or {}).get("ok") for o in orders)
        if done:
            return answer({"ok": True, "data": {"orders": [{**{k: o[k] for k in ("order_group", "items", "total_vnd")},
                                                            **((o["result"] or {}).get("data") or {})} for o in orders],
                                                "note": "Tổng từng đơn đọc đúng số total_vnd của đơn đó; {tổng} là tổng "
                                                        "cả giỏ."}})
        return answer({"ok": False, "error": {"code": "CONFIRMATION_REQUIRED", "retryable": False,
                       "message": "Đọc lại các đơn dưới đây cho khách (món, giá, tổng từng đơn đúng số total_vnd; "
                                  "{tổng} là tổng cả giỏ) rồi hỏi khách đồng ý; khách đồng ý thì gọi lại "
                                  "order_split_cod với cùng giỏ.",
                       "details": {"orders": [{k: o[k] for k in ("order_group", "items", "total_vnd")} for o in orders]}}})

    async def _look_up(self, name: str, args: Mapping[str, Any], request: Any) -> dict[str, Any] | None:
        """One organisers' lookup made for a write, through the tool guard; ``{name, args, content}`` or None."""
        if name not in self._tools or self._guard is None:
            return None
        call = {"name": name, "args": dict(args), "id": f"inner-{uuid.uuid4().hex[:12]}", "type": "tool_call"}

        async def run(inner: Any) -> Any:
            return await inner.tool.ainvoke(inner.tool_call)

        answer = await self._guard.awrap_tool_call(
            ToolCallRequest(tool_call=call, tool=self._tools[name], state=request.state, runtime=request.runtime), run)
        return {"name": name, "args": (getattr(answer, "additional_kwargs", {}) or {}).get("args") or call["args"],
                "content": getattr(answer, "content", "")}

    async def _fill_in(self, name: str, args: dict[str, Any], request: Any, quotes: dict[str, int],
                       order_quotes: dict[str, Any], codes: set[str], inner: list[dict[str, Any]]) -> dict[str, Any]:
        """Looks up what *args* needs and no result of this call has yet; *quotes*, *order_quotes* and *codes* grow."""
        if name == "order_create":
            lines = purchase.lines_of(args)
            if args.get("lines") and purchase.units_key(lines) not in order_quotes:
                found = await self._look_up("pricing_quote_order", {
                    "lines": [{"sku": line["sku"], "qty": line["qty"]} for line in lines],
                    **({"address": args["address"]} if args.get("address") else {})}, request)
                if found:
                    inner.append(found)
                    envelope = parse_envelope(found["content"]) or {}
                    if envelope.get("ok") and (priced := purchase.quoted_units(envelope.get("data") or {})):
                        order_quotes[priced[0]] = priced[1]
                        codes.update(sku for sku, _ in priced[1])
            elif args.get("sku") and args["sku"] not in quotes and not args.get("basket_skus"):
                found = await self._look_up("pricing_get_quote", {
                    "sku": args["sku"], "qty": 1, **({"address": args["address"]} if args.get("address") else {})},
                    request)
                if found:
                    inner.append(found)
                    data = (parse_envelope(found["content"]) or {}).get("data") or {}
                    if data.get("sku") and data.get("final_price_vnd") is not None:
                        quotes[str(data["sku"])] = int(data["final_price_vnd"])
                        codes.add(str(data["sku"]))
        elif name == "order_update" and args.get("new_variant_sku") and args["new_variant_sku"] not in codes:
            found = await self._look_up("inventory_check", {"sku": args["new_variant_sku"]}, request)
            if found:
                inner.append(found)
                data = (parse_envelope(found["content"]) or {}).get("data") or {}
                if data.get("sku"):
                    codes.add(str(data["sku"]))
        return args

    async def _guarded(self, request: Any, handler: Any) -> Any:
        request = without_nulls(request)
        call = request.tool_call
        name = call["name"]
        kept = declared_arguments(getattr(request, "tool", None), call.get("args") or {})
        if len(kept) != len(call.get("args") or {}):
            logger.info("Dropped undeclared arguments of %s: %s", name, sorted(set(call["args"]) - set(kept)))
            call = {**call, "args": kept}
            request = request.override(tool_call=call)
        context = getattr(getattr(request, "runtime", None), "context", None)
        if name not in actions.WRITE_TOOLS | actions.CUSTOMER_READ_TOOLS:
            return await handler(request)
        if not isinstance(context, AgentContext):
            return ToolMessage(content=json.dumps({"ok": False, "error": {"code": "PRECONDITION",
                "retryable": False, "message": "Missing trusted runtime context."}}),
                tool_call_id=call["id"], name=name, additional_kwargs={"blocked_by": "guardrail"})
        args = dict(call.get("args") or {})
        if name in actions.WRITE_TOOLS and context.review_flags is not None:
            flagged = await context.review_flags()
            if flagged:
                envelope = {"ok": False, "error": {"code": "PRECONDITION", "retryable": False, "message":
                            "Câu vừa nói với khách có lỗi, đính chính trước khi làm: " + " ".join(flagged)}}
                return ToolMessage(content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=name,
                                   additional_kwargs={"args": args, "blocked_by": "guardrail"})
        if name == "handoff_transfer":
            if context.lane != "HANDOFF" and actions.early_transfer(args, _asked_together(request)):
                envelope = {"ok": False, "error": {"code": "PRECONDITION", "retryable": False, "message": actions.EARLY_TRANSFER}}
                return ToolMessage(content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=name,
                                   additional_kwargs={"args": args, "blocked_by": "guardrail"})
            args["brief"] = actions.fill_handoff(args.get("brief") or {}, context.handoff_defaults,
                                                 customer_said=context.customer_said)
        if name == "schedule_callback" and not args.get("customer_phone") and context.customer_phone:
            args["customer_phone"] = context.customer_phone
        state = getattr(request, "state", None) or {}
        quotes = {**context.quotes, **_quotes_in(state)}
        order_quotes = {**context.order_quotes, **_order_quotes_in(state)}
        codes, orders = _seen_in(state, context.tool_results)
        codes = set(codes) | set(context.trusted_skus)
        inner: list[dict[str, Any]] = []
        if name in ("order_create", "order_update"):
            args = await self._fill_in(name, args, request, quotes, order_quotes, codes, inner)
            call = {**call, "args": args}
        if name == "order_create" and args.get("basket_skus") and args.get("sku"):
            # Half of a split order (QT-01): its unit price is the quote made with the other half's machines, where the
            # second-item promotion applies, not the one-machine quote (2026-11-16: the second order was refused). The
            # model prices the basket either with pricing_get_quote(basket_skus) or with pricing_quote_order of all
            # the machines; the run of 2026-11-16 did the latter.
            together = _basket_quotes_in(state).get((args["sku"], frozenset(args["basket_skus"])))
            if together is None:
                units = (order_quotes or {}).get(purchase.units_key(
                    [{"sku": args["sku"]}, *({"sku": sku} for sku in args["basket_skus"])]))
                together = next((int(price) for sku, price in units or () if sku == args["sku"]), None)
            if together is None:
                # No quote of this half with the other half's machines yet: the guard asks for it, the model's own
                # figure is a one-machine price the mock refuses (2026-11-24, PRICE_MISMATCH on the second order).
                found = await self._look_up("pricing_get_quote", {
                    "sku": args["sku"], "qty": 1, "basket_skus": list(args["basket_skus"]),
                    **({"address": args["address"]} if args.get("address") else {})}, request)
                if found:
                    inner.append(found)
                    data = (parse_envelope(found["content"]) or {}).get("data") or {}
                    if data.get("final_price_vnd") is not None:
                        together = int(data["final_price_vnd"])
            if together is not None:
                quotes = {**quotes, args["sku"]: together}
        if name == "order_create":
            args = _filled_order(args, context, quotes, order_quotes)
            if args.get("sku") and args.get("price_vnd") is None and not args.get("lines"):
                # A variant the customer's words picked, not quoted yet: the guard looks its price up itself.
                found = await self._look_up("pricing_get_quote", {"sku": args["sku"], "qty": int(args.get("qty") or 1)},
                                            request)
                if found:
                    inner.append(found)
                    data = (parse_envelope(found["content"]) or {}).get("data") or {}
                    if data.get("final_price_vnd") is not None:
                        quotes = {**quotes, args["sku"]: int(data["final_price_vnd"])}
                        args["price_vnd"] = int(data["final_price_vnd"])
        created = (*context.created_orders, *_created_in(state))
        intents = await _intents(name, args, context, created, state)
        if name == "order_create" and (earlier := actions.repeated_order(
                args, created=created, placed=placed_this_call(context, state), customer_said=context.customer_said,
                wants_more=(intents or {}).get("one_more"))):
            envelope = {"ok": False, "error": {"code": "ALREADY_CREATED", "retryable": False, "details": dict(earlier),
                        "message": f"Đơn {earlier.get('order_id')} đã tạo trong cuộc này; không tạo lại."}}
            return ToolMessage(content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=name,
                               additional_kwargs={"args": args, "blocked_by": "guardrail", "inner": inner})
        verdict = actions.check(
            name, args, tier=context.tier, mode=context.mode, has_phone=bool(context.customer_phone),
            quotes=quotes, order_quotes=order_quotes,
            orders=context.known_orders | orders, trusted=frozenset(codes) | set(quotes),
            lane=context.lane, intents=intents, now=context.now,
            last_agent_said=context.last_agent_said, customer_said=context.customer_said,
            deletion_asked=context.deletion_asked,
            shared_phone=context.shared_phone, created=created,
            updated=(*context.updated_orders, *_updated_in(state, context.tool_results)),
            placed=placed_this_call(context, state),
            heard_basket=[] if _asked_again(state, name, args) else _heard_basket(context.order_quotes),
            order_records=[*context.order_records, *_order_records_in(state, context.tool_results)],
        )
        if verdict.passed and name == "order_create":
            business_args = order_arguments(args, context)
            delivery = purchase.estimated_delivery([*context.tool_results, *tool_results_of(state.get("messages") or [])])
            record = purchase.draft(business_args, context, delivery, names=_names_in(state), quotes=quotes,
                                    order_quotes=order_quotes)
            pending = context.pending_purchase
            heard = bool(pending and pending.get("owner") == record["owner"] and record["payload_hash"] in
                         {d.get("payload_hash") for d in (pending, *(pending.get("siblings") or []))})
            agreed = None
            # PB-09 asks the order read back once before order.create, not a second yes after it: a customer who asked
            # for the order hears it read back in the same reply that places it (the user's decision, 2026-11-10).
            if context.judge is not None:
                asked = {"recent_messages": [{"speaker": who, "text": text[:600]} for who, text in context.recent],
                         "order": record["read_back"]}
                # The early answer does not see the order: it may stand only for the very order the customer heard
                # read back (a yes from earlier in the call read 0.98 on a later turn about a call back, 2026-11-15).
                agreed = _agreed(await _verdict(context, "purchase", asked, early=heard))
            if agreed is None:  # no answer from the PolicyAgent: an order is placed only on a plain yes to what was just read back
                agreed = heard and purchase.answer(
                    pending, call_id=context.call_id, channel=context.channel, turn_id=str(context.turn_id),
                    said=context.customer_said or "", last_reply=context.last_agent_said) is not None
            if not agreed:
                # The customer heard this very order and did not agree: answer them, it is not read a second time.
                message = ("Khách đã nghe đơn này và chưa đồng ý: trả lời điều khách đang nói, không gọi lại order_create."
                           if heard else "Đọc lại đúng đơn và đợi khách xác nhận trong phiên này trước khi tạo đơn.")
                envelope = {"ok": False, "error": {"code": "CONFIRMATION_REQUIRED", "retryable": False, "message": message,
                    "details": {} if heard else {"purchase_draft": record}}}
                return ToolMessage(content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=name,
                                   additional_kwargs={"args": args, "blocked_by": "guardrail", "inner": inner})
            context.consent["draft"] = purchase.authorize(record, context.turn_id)
        if not verdict.passed:
            envelope = {"ok": False, "error": {"code": "PRECONDITION", "retryable": False, "message": " ".join(verdict.reasons)}}
            return ToolMessage(
                content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=name,
                additional_kwargs={"args": args, "blocked_by": "guardrail", "inner": inner},
            )
        if name == "schedule_callback" and args.get("callback_at"):
            # The shop's clock is Vietnam's, to the minute; the tool's own answer carries no offset.
            args["callback_at"] = re.sub(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::\d{2})?(?:\.\d+)?(?:\+07:00|Z)?$", r"\1", str(args["callback_at"]))
            refused = callback_refusal(str(args["callback_at"]), context,
                                       [*context.tool_results, *tool_results_of(state.get("messages") or [])])
            if refused is not None:
                return ToolMessage(content=json.dumps(refused, ensure_ascii=False), tool_call_id=call["id"], name=name,
                                   additional_kwargs={"args": args, "blocked_by": "guardrail", "inner": inner})
        result = await handler(request.override(tool_call={**call, "args": args}))
        if inner and isinstance(result, ToolMessage):
            result = result.model_copy(update={"additional_kwargs": {**result.additional_kwargs, "inner": inner}})
        return result


#: Days ahead a call back may be booked: a customer's "cuối tháng" read as a year later is not a date they gave.
CALLBACK_HORIZON_DAYS = 60


def callback_refusal(callback_at: str, context: AgentContext, results: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Why this ``schedule.callback`` must not run, as the tool's own refusal, or None.

    The same moment already booked in this call is said back, not booked again (2026-11-26: one call back booked
    three times as the customer kept talking); a moment more than :data:`CALLBACK_HORIZON_DAYS` ahead, or in the
    past, is asked again."""
    if callback_at in context.callbacks_booked:
        return {"ok": False, "error": {"code": "ALREADY_BOOKED", "retryable": False, "details": {"callback_at": callback_at},
                "message": "Lịch gọi lại này đã đặt trong cuộc; báo lại đúng giờ đã đặt, không đặt thêm."}}
    booked = [r for r in results if r.get("name") == "schedule.callback" and (r.get("result") or {}).get("ok")]
    for result in booked:
        data = (result.get("result") or {}).get("data") or {}
        if callback_at in (data.get("callback_at"), (result.get("args") or {}).get("callback_at"), data.get("moved_from")):
            return {"ok": False, "error": {"code": "ALREADY_BOOKED", "retryable": False, "details": dict(data),
                    "message": "Lịch gọi lại này đã đặt trong cuộc; báo lại đúng giờ đã đặt, không đặt thêm."}}
    try:
        moment = datetime.fromisoformat(callback_at)
    except ValueError:
        return None
    now = context.now.replace(tzinfo=None) if context.now else None
    if now is not None and not (now - timedelta(minutes=5) <= moment <= now + timedelta(days=CALLBACK_HORIZON_DAYS)):
        return {"ok": False, "error": {"code": "PRECONDITION", "retryable": False,
                "message": "Giờ hẹn không phải giờ khách vừa nói (đã qua hoặc quá xa); hỏi lại khách ngày giờ cụ thể."}}
    return None


def _filled_order(args: Mapping[str, Any], context: AgentContext, quotes: Mapping[str, int],
                  order_quotes: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What code knows of an order, so the model does not have to write it: the price is today's quote (each line's,
    from the ``pricing.quote_order`` of the same units), and what it left out of an order the customer already heard
    read back comes from that read-back."""
    order = dict(args)
    if isinstance(order.get("lines"), list):
        order["lines"] = [dict(line) if isinstance(line, dict) else line for line in order["lines"]]
    # A product sold in sizes and colours named by its own code: the variant the customer's latest words about size or
    # colour pick, when they pick exactly one (the model had sent the parent code turns running). Only the latest
    # such words: a size changed later without the colour is a change of mind, not the earlier pair, and the parent
    # code is left for the guard to ask about.
    latest = next((text for who, text in reversed(context.recent) if who == "customer"
                   and (lambda seen: seen.get("size") is not None or seen.get("color"))(
                       commerce.observe(text)["scenario_entities"])), None)
    for line in (order.get("lines") if isinstance(order.get("lines"), list) else [order]):
        if latest and isinstance(line, dict) and line.get("sku") and commerce.variants_of(str(line["sku"])):
            picked = commerce.variant_said(str(line["sku"]), latest)
            if picked:
                line["sku"] = picked
                line.pop("price_vnd", None)  # today's price of the variant, filled below, not the product's
    if isinstance(order.get("lines"), list) and len(order["lines"]) == 1 and int(order["lines"][0].get("qty") or 1) == 1:
        order.update({"sku": order["lines"][0].get("sku")})  # one unit is an order of one product
        order.pop("lines")
    pending = context.pending_purchase
    if pending and pending.get("target_id") == purchase.target(order):
        for key, value in (pending.get("args") or {}).items():
            if order.get(key) in (None, "", []):
                order[key] = value
    if order.get("lines"):
        units = (order_quotes or {}).get(purchase.units_key(order["lines"]))
        if units:
            order["lines"] = purchase.priced_lines(units)
        order.pop("sku", None), order.pop("price_vnd", None), order.pop("qty", None)
    elif order.get("sku") and order.get("basket_skus") and (units := (order_quotes or {}).get(
            purchase.units_key([{"sku": order["sku"], "qty": int(order.get("qty") or 1)},
                                *({"sku": s} for s in order["basket_skus"])]))):
        # One order of a split (QT-01): its unit's price in the quote of the whole basket, the second machine's
        # discount kept, not the product's price alone (the order was otherwise sent at the full price).
        own = [int(price) for sku, price in units if sku == order["sku"]]
        if own:
            order["price_vnd"] = min(own)
    elif order.get("sku") in quotes:
        order["price_vnd"] = quotes[order["sku"]]
    return order


def _asked_again(state: Mapping[str, Any], name: str, args: Mapping[str, Any]) -> bool:
    """Whether this run already sent the same call for the same product and the guard refused it: the model, told
    once that the customer heard a whole basket, has weighed the customer's words and kept its order."""
    return any(isinstance(m, ToolMessage) and m.name == name and (m.additional_kwargs or {}).get("blocked_by") == "guardrail"
               and ((m.additional_kwargs or {}).get("args") or {}).get("sku") == args.get("sku") and not args.get("lines")
               and (envelope_of(m) or {}).get("error", {}).get("code") == "PRECONDITION"
               for m in state.get("messages") or [])


def _heard_basket(order_quotes: Mapping[str, Any]) -> list[str]:
    """The skus of the last basket of more than one product priced on an earlier turn of the call."""
    for key in reversed(list(order_quotes or {})):
        skus = str(key).split("|")
        if len(set(skus)) > 1:
            return skus
    return []


def placed_this_call(context: AgentContext, state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Order lines created this call: earlier turns, earlier runs of this turn, this run; one per order id."""
    lines = {line["order_id"]: dict(line) for line in context.placed_lines}
    lines.update({line["order_id"]: line for line in actions.placed_lines(
        [*context.tool_results, *tool_results_of(state.get("messages") or [])])})
    return list(lines.values())


#: Reasons a person is needed whatever the PolicyAgent's doubt: a wrong "no" would leave the customer without one. The
#: model picks the reason itself, so only those it cannot pick from a misreading stay: a health question, a broken
#: system. "Serious complaint" and "impatient" were the model's words for a warranty question and for a request for
#: another person's details (2026-11-26, rules 6 and 7 say no transfer): on doubt those wait for a clear yes.
PLAIN_HANDOFF_REASONS = frozenset({"cau_hoi_y_te", "loi_he_thong"})


async def _verdict(context: AgentContext, intent: str, state: Mapping[str, Any], *, early: bool = True) -> str:
    """The PolicyAgent's answer on what the customer means, by band (``policy.band``): yes, no, unsure, unanswered.

    The answer asked as the turn started stands when it is a clear yes, or, for a transfer, when it is all but
    certain none is wanted (``policy.NO_HANDOFF``); otherwise the action's own question is asked, with its facts.
    Every probability is kept for the turn's diagnostics.
    """
    if early and context.early_intents is not None and intent in EARLY_INTENTS:
        probability = (await context.early_intents()).get(intent)
        # A transfer is never taken from the early answer's yes: the early question sees neither the reason nor the
        # documents, and a transfer leaves the rest of the call to a person (a request for another person's
        # number read as a transfer early; asked with the reason given, it is a refusal).
        if (band(intent, probability) == "yes" and intent != "handoff") or (
                intent == "handoff" and probability is not None and probability <= NO_HANDOFF):
            logger.info("Intent %s taken from the turn's early check: %.2f", intent, probability)
            context.intent_probabilities[f"{intent}:early"] = round(probability, 3)
            return "yes" if band(intent, probability) == "yes" else "no"
    assert context.judge is not None
    probability = await context.judge(intent, state)
    context.intent_probabilities[intent] = None if probability is None else round(probability, 3)
    return band(intent, probability)


def _agreed(verdict: str) -> bool | None:
    """An action that needs the customer's yes: only a clear yes is one; unsure is a no, and the action asks the
    customer to confirm; no answer at all leaves the deterministic fallback (None)."""
    return {"yes": True, "unanswered": None}.get(verdict, False)


async def _intents(name: str, args: Mapping[str, Any], context: AgentContext, created: Sequence[Mapping[str, Any]],
                   state: Mapping[str, Any] | None = None) -> dict[str, bool | None]:
    """What the customer means, for the one action about to run, read by the PolicyAgent.

    Asked only when the action depends on it: a transfer outside lane
    HANDOFF, a deletion, a change to an order, an order for a product this
    call already ordered.
    Every other tool call asks nothing.
    """
    if context.judge is None:
        return {}
    said = [{"speaker": who, "text": text[:600]} for who, text in context.recent]
    if name == "handoff_transfer" and context.lane != "HANDOFF":
        brief = args.get("brief") or {}
        # What the search found for this turn, and apart from it what was read earlier in the call: a question the
        # search found nothing for is still unanswered when only an earlier, unrelated passage is in reach.
        shown = [p for p in shown_passages(context.knowledge)[0] if p.get("text")]
        documents = [str(p["text"])[:400] for p in shown if not p.get("earlier")]
        earlier = [str(p["text"])[:400] for p in shown if p.get("earlier")]
        verdict = await _verdict(context, "handoff", {
            "recent_messages": said,
            "reason_given": {"escalation_reason": brief.get("escalation_reason"),
                             "detail": brief.get("escalation_reason_detail")},
            "shop_documents_found": documents or ["no passage matched the question"],
            **({"documents_read_earlier_in_this_call": earlier} if earlier else {}),
            "tools_called": [r["name"] for r in (*context.tool_results, *tool_results_of((state or {}).get("messages") or []))],
            "known_this_call": [f"{r.get('tool')}: {r.get('result')}"[:500] for r in context.earlier_results[-6:]],
        })
        if verdict in ("yes", "no"):
            return {"handoff": verdict == "yes"}
        # Unsure, or no answer: a reason that needs a person goes through; "the documents do not say" goes through
        # only when the search found nothing, else the passages are read first.
        return {"handoff": brief.get("escalation_reason") in (*PLAIN_HANDOFF_REASONS, "khach_yeu_cau_gap_nguoi")
                or not documents}
    if name == "memory_request_deletion" and context.tier == "VERIFIED":
        return {"delete": _agreed(await _verdict(context, "delete", {"recent_messages": said}))}
    if name == "order_update":
        if args.get("action") == "update_address" and any(
                o.get("order_id") == args.get("order_id") and o.get("no_address") for o in created):
            return {}  # the address this order still lacks: the customer already agreed to the order
        # The model decides when the customer has chosen the change (2026-11-25): asking the PolicyAgent refused
        # customers who had named the new size and asked what the exchange cost.
        return {}
    asked_skus = {line["sku"] for line in purchase.lines_of(args)}
    if name == "order_create" and any(asked_skus & set(o.get("skus") or [o.get("sku")]) for o in created):
        return {"one_more": _agreed(await _verdict(context, "one_more", {"recent_messages": said,
                                                                         "already_ordered": args.get("sku")}))}
    return {}


def _order_records_in(state: Mapping[str, Any], earlier: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The orders ``order_status`` showed in this call and this turn, as it showed them (status, date)."""
    envelopes = [envelope_of(m) for m in state.get("messages") or [] if isinstance(m, ToolMessage)]
    envelopes += [r.get("result") for r in earlier]
    return [order for envelope in envelopes if isinstance(envelope, dict) and envelope.get("ok")
            for order in ((envelope.get("data") or {}).get("orders") or [] if isinstance(envelope.get("data"), dict) else [])
            if isinstance(order, dict) and order.get("order_id")]


def _seen_in(state: Mapping[str, Any], earlier: Sequence[Mapping[str, Any]]) -> tuple[frozenset[str], frozenset[str]]:
    """Product codes and order ids the tools showed in this run and earlier in this turn: what may be acted on."""
    envelopes = [envelope_of(m) for m in state.get("messages") or [] if isinstance(m, ToolMessage)]
    envelopes += [r.get("result") for r in earlier]
    codes: set[str] = set()
    orders: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("sku", "variant_sku", "successor_sku", "new_variant_sku"):
                if isinstance(value.get(key), str):
                    codes.add(value[key])
            if isinstance(value.get("order_id"), str):
                orders.add(value["order_id"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for envelope in envelopes:
        if isinstance(envelope, dict) and envelope.get("ok"):
            walk(envelope.get("data"))
    return frozenset(codes), frozenset(orders)


def _created_in(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The orders ``order_create`` made earlier in this run, ``{order_id, sku}``, the sku from the call's arguments."""
    asked = {call["id"]: call.get("args") or {} for m in state.get("messages") or [] if isinstance(m, AIMessage)
             for call in m.tool_calls if call.get("name") == "order_create"}
    created = []
    for message in state.get("messages") or []:
        if isinstance(message, ToolMessage) and message.name == "order_create":
            envelope = envelope_of(message)
            data = envelope.get("data") if isinstance(envelope, dict) and envelope.get("ok") else None
            if isinstance(data, dict) and data.get("order_id"):
                order = asked.get(message.tool_call_id, {})
                created.append({"order_id": data["order_id"], "sku": order.get("sku") or purchase.target(order),
                                "skus": sorted({line["sku"] for line in purchase.lines_of(order)}),
                                "no_address": not order.get("address")})
    return created


def _updated_in(state: Mapping[str, Any], earlier: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The arguments of every ``order_update`` that succeeded in this call: earlier turns' and this run's."""
    done = [dict(r.get("args") or {}) for r in earlier
            if str(r.get("name", "")).replace("_", ".", 1) == "order.update" and (r.get("result") or {}).get("ok")]
    asked = {call["id"]: call.get("args") or {} for m in state.get("messages") or [] if isinstance(m, AIMessage)
             for call in m.tool_calls if call.get("name") == "order_update"}
    for message in state.get("messages") or []:
        if isinstance(message, ToolMessage) and message.name == "order_update":
            envelope = envelope_of(message)
            if isinstance(envelope, dict) and envelope.get("ok"):
                done.append(dict(asked.get(message.tool_call_id) or {}))
    return done


def _names_in(state: Mapping[str, Any]) -> dict[str, str]:
    """Product names from the searches already in this run: what a read-back says instead of a code."""
    names: dict[str, str] = {}
    for message in state.get("messages") or []:
        if isinstance(message, ToolMessage) and message.name == "catalog_search":
            data = (envelope_of(message) or {}).get("data") or {}
            names.update({item["sku"]: item["name"] for item in data.get("items") or [] if item.get("sku") and item.get("name")})
    return names


def _quotes_in(state: Mapping[str, Any]) -> dict[str, int]:
    """Today's price per sku from the pricing results already in this run; a quote made with a split order's other
    machines (``basket_skus``) is that order's alone (:func:`_basket_quotes_in`)."""
    quotes: dict[str, int] = {}
    together: set[str] = set()
    for message in state.get("messages") or []:
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("name") == "pricing_get_quote" and (call.get("args") or {}).get("basket_skus"):
                together.add(call.get("id"))
        if isinstance(message, ToolMessage) and message.name == "pricing_get_quote" and message.tool_call_id not in together:
            envelope = envelope_of(message) or {}
            data = envelope.get("data") or {}
            if envelope.get("ok") and data.get("sku") and data.get("final_price_vnd") is not None:
                quotes[data["sku"]] = int(data["final_price_vnd"])
    return quotes


def _basket_quotes_in(state: Mapping[str, Any]) -> dict[tuple[str, frozenset[str]], int]:
    """Today's price per (sku, other machines of the split order) from the pricing calls made with ``basket_skus``."""
    asked: dict[str, frozenset[str]] = {}
    found: dict[tuple[str, frozenset[str]], int] = {}
    for message in state.get("messages") or []:
        for call in getattr(message, "tool_calls", None) or []:
            basket = (call.get("args") or {}).get("basket_skus")
            if call.get("name") == "pricing_get_quote" and basket:
                asked[call.get("id")] = frozenset(basket)
        if isinstance(message, ToolMessage) and message.name == "pricing_get_quote" and message.tool_call_id in asked:
            envelope = envelope_of(message) or {}
            data = envelope.get("data") or {}
            if envelope.get("ok") and data.get("sku") and data.get("final_price_vnd") is not None:
                found[(data["sku"], asked[message.tool_call_id])] = int(data["final_price_vnd"])
    return found


def _order_quotes_in(state: Mapping[str, Any]) -> dict[str, Any]:
    """The orders of more than one unit priced in this run: units key to ``[[sku, unit price], ...]``."""
    found: dict[str, Any] = {}
    for message in state.get("messages") or []:
        if isinstance(message, ToolMessage) and message.name == "pricing_quote_order":
            envelope = envelope_of(message) or {}
            if envelope.get("ok") and (priced := purchase.quoted_units(envelope.get("data") or {})):
                found[priced[0]] = priced[1]
    return found


LOAD_SKILL = "load_skill"


@tool(LOAD_SKILL)
def load_skill(name: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Load how the shop does a task, named in the list of skills in the instructions."""
    result = skill_book.load(runtime.context.skills, name)
    logger.info("Skill %s for call %s turn %s: %s", name, runtime.context.call_id, runtime.context.turn_id,
                "loaded" if result["ok"] else "unknown")
    return json.dumps(result, ensure_ascii=False)


class AdvisorAgent(BaseAgent):
    """Drafts the reply for one turn, from the slice of state it is given."""

    #: Four items need catalogue, quote, stock and order each, plus delivery.
    TOOL_CALLS_PER_RUN = 20
    #: Two model calls a turn at most: the opening line with the tools, then the answer from their results.
    MODEL_CALLS_PER_RUN = 2

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        tools: Sequence[BaseTool] | None = None,
        generation: Mapping[str, Any] | None = None,
        retries: int = 1,
        llm: BaseChatModel | None = None,
    ) -> None:
        """``retries`` is the one retry of a failed model call and of a
        retryable tool failure. An evaluation harness
        that must see every attempt sets it to 0. ``llm`` replaces the model
        from config, for offline tests."""
        super().__init__("advisor", provider=provider, model=model, generation=generation, llm=llm)
        self._tools = [*(tools or ()), *([load_skill] if tools else [])]
        if "order_create" in {getattr(t, "name", None) for t in self._tools}:
            # The team's tool for a COD basket above the limit: ActionGuardMiddleware answers it with order_create.
            self._tools.append(tool(order_split_cod, parse_docstring=True))
        if product_advise_on() and {SEARCH, QUOTE, STOCK} <= {getattr(t, "name", None) for t in self._tools}:
            # Plan 002, B3: the team's own tool; ChainLookupMiddleware answers it with the organisers' tools.
            self._tools.append(tool(product_advise, parse_docstring=True))
        names = [tool.name for tool in self._tools]
        retry = [ModelRetryMiddleware(max_retries=retries, initial_delay=1.0, on_failure="error")] if retries else []
        openai = getattr(self.llm, "_llm_type", "") == "openai-chat"
        guard = ToolGuardMiddleware(names, retries=retries)
        self._graph = create_agent(
            model=self.llm,
            tools=self._tools,
            middleware=[
                ChainLookupMiddleware(self._tools, guard, get_lanes()),
                ContextPromptMiddleware(self.MODEL_CALLS_PER_RUN, split=openai),
                *retry,
                ModelCallLimitMiddleware(run_limit=self.MODEL_CALLS_PER_RUN, exit_behavior="error"),
                ToolCallLimitMiddleware(run_limit=self.TOOL_CALLS_PER_RUN, exit_behavior="continue"),
                LaneToolsMiddleware(get_lanes(), names),
                *([StrictToolsMiddleware()] if openai else []),
                # After the strict schemas it extends, before the guard that would drop the argument as undeclared.
                ActionGuardMiddleware(self._tools, guard),
                guard,
            ],
            context_schema=AgentContext,
            name=self.name,
        )
        logger.info("Agent '%s' ready on %s | tools: %s", self.name, self.model_name, names or "none")

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self._tools]

    def run_config(self, context: AgentContext, *, user_id: str | None = None) -> RunnableConfig:
        """Per-run config: trace callback and metadata. No thread: nothing persists here."""
        config: RunnableConfig = {"run_name": self.name}
        config["metadata"] = tracing.trace_metadata(
            session_id=context.customer_id or context.call_id,
            user_id=user_id,
            tags=[self.name, context.lane, context.mode],
            agent=self.name,
            call_id=context.call_id,
            tier=context.tier,
            lane=context.lane,
            mode=context.mode,
            switches=dict(context.switches),
        )
        if (handler := tracing.handler()) is not None:
            config["callbacks"] = [handler]
        return config

    async def draft(self, messages: list[Any], context: AgentContext, *, user_id: str | None = None) -> Draft:
        """Run the loop once over *messages* and return the draft."""
        async for event in self.stream(messages, context, user_id=user_id):
            if event.kind == "done":
                return event.draft
        raise RuntimeError("Advisor stream ended without a draft")

    async def stream(
        self, messages: list[Any], context: AgentContext, *, user_id: str | None = None
    ) -> AsyncIterator[AdvisorEvent]:
        """Run the loop once over *messages*, yielding the answer as it is written.

        Text arrives in chunks from the model node; a model call that turns
        out to call tools says so with ``tool_started``, once per call, and
        ``tools`` follows when they have answered, with every result so far,
        so a sentence can be checked against them before the run ends. The
        last event is ``done`` with the whole :class:`Draft`, as :meth:`draft`
        would return it. Closing the iterator early stops the run: that is how
        the harness abandons a draft whose sentence the guard blocked.
        """
        started = time.perf_counter()
        produced: list[Any] = []
        announced: set[str] = set()
        try:
            async for mode, chunk in self._graph.astream(
                {"messages": messages}, config=self.run_config(context, user_id=user_id), context=context,
                stream_mode=["messages", "updates"],
            ):
                if mode == "updates":
                    fresh = [m for update in chunk.values() if isinstance(update, dict) for m in update.get("messages") or []]
                    produced.extend(fresh)
                    if any(isinstance(m, ToolMessage) for m in fresh):
                        yield AdvisorEvent("tools", results=tuple(tool_results_of(produced)), draft=self._draft_of(produced, started))
                    continue
                message, meta = chunk
                # A model that streams sends chunks; one that does not sends its
                # whole message once, which is a chunk's parent class.
                if meta.get("langgraph_node") != "model" or not isinstance(message, AIMessage):
                    continue
                calls = message.tool_call_chunks if isinstance(message, AIMessageChunk) else message.tool_calls
                # A line written before a lookup (``preamble``) shares the message with its tool calls: said too.
                text = text_of(message, strip=False)
                if text:
                    yield AdvisorEvent("text", text=text)
                for call in calls or []:
                    # Once per call, with its name (the first chunk of a call carries it).
                    key = f"{message.id}:{call.get('index', call.get('id'))}"
                    if call.get("name") and key not in announced:
                        announced.add(key)
                        yield AdvisorEvent("tool_started", text=str(call["name"]))
        except Exception as error:
            raise AdvisorFailure(error, self._draft_of(produced, started)) from error
        yield AdvisorEvent("done", draft=self._draft_of(produced, started))

    async def warm(self) -> float:
        """One model call with the rules, the skills and the tools a first turn sends, and no tool allowed to run.

        A service that has just started has no connection to the provider and a prompt the provider has not cached:
        the first customer's first token came 0.8 to 1.4 s later than the next one's (2026-11-14). This call pays
        that before anyone is on the line. Returns its seconds.
        """
        started = time.perf_counter()
        context = AgentContext(call_id="warm", lane="NEW", warming=True)
        await self.draft([HumanMessage(content="Alo")], context)
        return time.perf_counter() - started

    def _draft_of(self, produced: Sequence[Any], started: float) -> Draft:
        return Draft(
            text=_final_text(produced),
            tool_results=tool_results_of(produced),
            model=self.model_name,
            model_calls=sum(1 for m in produced if isinstance(m, AIMessage) and not m.additional_kwargs.get(CHAINED)),
            seconds=time.perf_counter() - started,
        )


def _final_text(produced: Sequence[Any]) -> str:
    for message in reversed(produced):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return text_of(message).strip()
    return ""


def tool_results_of(produced: Sequence[Any]) -> list[dict[str, Any]]:
    """Every tool call of the run: organisers' name, the arguments it ran with, the envelope."""
    answers = {m.tool_call_id: m for m in produced if isinstance(m, ToolMessage)}
    results = []
    for message in produced:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            if call["name"] == LOAD_SKILL:
                continue  # how the model reads a procedure, not a business tool: no trace, no evidence
            answer = answers.get(call["id"])
            if call["name"] in (ADVISE, SPLIT) and answer is not None and answer.additional_kwargs.get("inner") is not None:
                # The team's tool is the organisers' calls it made: those are what ran, and what the trace records; an
                # order the consent check held back is recorded as held back, as if the model had called it.
                results += [{"name": dotted(inner["name"]), "args": dict(inner.get("args") or {}),
                             "result": parse_envelope(inner.get("content")), "blocked_by": inner.get("blocked_by")}
                            for inner in answer.additional_kwargs["inner"]]
                # What the team's tool concluded: not a call that ran, so it has no ``result`` and the trace leaves it out.
                results.append({"name": call["name"], "args": dict(call.get("args") or {}), "result": None,
                                "advice": parse_envelope(answer.content), "blocked_by": None})
                continue
            if answer is not None and answer.additional_kwargs.get("inner"):
                # Lookups the action guard made for this write (plan 003): they ran, so the trace records them first.
                results += [{"name": dotted(inner["name"]), "args": dict(inner.get("args") or {}),
                             "result": parse_envelope(inner.get("content")), "blocked_by": None}
                            for inner in answer.additional_kwargs["inner"]]
            envelope = parse_envelope(answer.content) if answer is not None else None
            blocked_by = answer.additional_kwargs.get("blocked_by") if answer is not None else None
            if answer is None:
                envelope = {"ok": False, "error": {"code": "TOOL_RESULT_MISSING", "retryable": False,
                                                   "message": "No result received; execution outcome is unknown."}}
                blocked_by = "missing_result"
            if (answer is not None and answer.status == "error" and isinstance(answer.content, str)
                    and answer.content.startswith("Tool call limit exceeded.")):
                envelope = {"ok": False, "error": {"code": "TOOL_CALL_LIMIT", "retryable": False,
                                                   "message": answer.content}}
                blocked_by = "framework"
            args = (answer.additional_kwargs.get("args") if answer is not None else None) or call["args"]
            result = {
                "name": dotted(call["name"]),
                "args": dict(args),
                "result": envelope,
                "blocked_by": blocked_by,
            }
            results.append(result)
    return results
