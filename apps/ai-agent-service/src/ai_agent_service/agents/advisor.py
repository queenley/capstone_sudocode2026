"""AdvisorAgent: drafts what the shop says on one turn. ``docs/design.md`` section 4.4.

A ReAct loop, ``langchain.agents.create_agent``: a model node calls the
lane's tools, a tool node runs them, until the model answers without a tool
call, at most twenty tool calls and eight model calls a turn (an order of
several items needs a quote, a stock check and an order each). The model
comes from config through :class:`~src.agents.base.BaseAgent`; the tools from
MCP under the ``advisor`` role. The knowledge base is not one of them: the
harness retrieves the turn's passages before the advisor runs (section 4.2)
and they arrive in the context.

**Stateless** (principle 2). The agent holds no checkpointer and nothing
between calls: the hot graph hands it a slice of its state (section 3.2) as
:class:`AgentContext` and the recent turns as messages, and gets back a
draft and the tool results. Its ReAct messages live only inside one call.
The conversation itself is the hot graph's ``messages``, checkpointed there
and nowhere else, so there are never two copies of a call to keep in step.

Around the loop, as middleware:

- the context prompt, assembled in section 4.4's order and cut from the
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
tracing (section 5.5). Plain text rather than a structured object so the
same reply can later be streamed sentence by sentence (Appendix E).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Mapping, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from ..components.context.budget import Section, assemble
from ..components.guardrails import actions
from ..components.memory.brief import BriefLine
from ..components.intake import pii
from ..components.intake.itn import format_vnd
from ..config.config_manager import get_lanes, load_prompt, load_prompt_yaml
from ..llm import tracing
from ..llm.callback_handler import text_of
from ..mcp.client import dotted
from ..mcp.tools import LaneToolsMiddleware, ToolGuardMiddleware, envelope_of, parse_envelope
from .base import BaseAgent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentContext:
    """The advisor's slice of the state for one turn (section 3.2).

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
    #: Why the previous draft of this turn was blocked, for a regeneration.
    block_reasons: tuple[str, ...] = ()
    #: The sentences of this answer the customer already heard when a later one was blocked:
    #: the regeneration goes on from them instead of starting over.
    already_said: tuple[str, ...] = ()
    #: Tool results already gathered this turn, so a regeneration need not ask again.
    tool_results: tuple[dict[str, Any], ...] = ()
    #: Today's price per sku from every quote in this call, for the order check.
    quotes: Mapping[str, int] = field(default_factory=dict)
    known_orders: frozenset[str] = frozenset()
    #: Order lines created earlier in this call (``actions.placed_lines``): the COD limit is on the whole order.
    placed_lines: tuple[Mapping[str, Any], ...] = ()
    #: The customer's phone, raw. Filled into tools by the harness; never shown to the model.
    customer_phone: str | None = None
    shared_phone: bool = False
    vault: pii.Vault = field(default_factory=pii.Vault, repr=False, compare=False)
    #: This call's address tokens and the addresses behind them, raw, the
    #: latest last: filled into the tools that take an address (section 4.4).
    addresses: Mapping[str, str] = field(default_factory=dict)
    #: What the harness fills into a Handoff Brief.
    handoff_defaults: Mapping[str, Any] = field(default_factory=dict)
    switches: Mapping[str, Any] = field(default_factory=dict)
    #: This turn, for the idempotency key of a write tool (section 6.1).
    turn_id: str | None = None
    #: The turn's passages from the knowledge base, already filtered by the
    #: harness: a restricted one carries no text, a superseded one its dates.
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
    #: The orders earlier turns of this call created: ``{order_id, sku}``.
    created_orders: tuple[Mapping[str, Any], ...] = ()
    #: The changes ``order_update`` made in earlier turns of this call: ``{order_id, action, new_variant_sku}``.
    updated_orders: tuple[Mapping[str, Any], ...] = ()
    #: How an unknown customer calls themselves, and whether the agent asked.
    self_called: str | None = None
    honorific_asked: bool = False
    #: The customer's words this turn and the agent's last reply, tokenised:
    #: what the before-write checks read (a deletion needs both).
    customer_said: str | None = None
    last_agent_said: str | None = None
    #: The last few messages, ``(speaker, text)`` tokenised: what Jev reads when an action
    #: depends on what the customer means (a transfer, a deletion, one more order).
    recent: tuple[tuple[str, str], ...] = ()
    #: ``PolicyAgent.judge``: what the customer means for one action, None without an answer.
    judge: Callable[[str, Mapping[str, Any]], Awaitable[bool | None]] | None = field(default=None, repr=False,
                                                                                       compare=False)


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
    text: str = ""
    draft: Draft | None = None
    #: For ``tools``: every tool call of the run so far, as :attr:`Draft.tool_results` lists them.
    results: tuple[dict[str, Any], ...] = ()


#: Section 4.4, "Luật làm đúng từ đầu": every rule the organisers' documents
#: and grader make knowable is in the first release (principle 8), each
#: also enforced in code where code can (the guard, the before-write check).
#: The codes in brackets are the policy sections the rule comes from.
HARD_RULES = load_prompt("advisor/rules.md")

#: The lane notes, the identity question, the opening and the channel notes.
_NOTES = load_prompt_yaml("advisor/notes.yaml")
LANE_NOTES: dict[str, str] = _NOTES["lanes"]

#: CONFIRM_IDENTITY by its reason (section 4.2): one question, nothing private before it is answered.
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


#: Passages shown to the model per turn (section 4.2: five retrieved, three allowed in).
KNOWLEDGE_SHOWN = 3


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
    return "\n".join([text, *extra]).strip()


def system_prompt(context: AgentContext, *, max_tokens: int = 3000) -> tuple[str, tuple[str, ...]]:
    """The system message in section 4.4's order, and the sections that were cut.

    1 rules, 2 warnings (both never cut), 3 the lane, 4 the brief lines the
    tier allows, 5 the summary of older turns (the last four travel as
    messages), 6 the turn's knowledge passages, 7 the playbook entries of the
    situation, 8 tool results already gathered (a regeneration), 9 why the
    previous draft was blocked. Required evidence survives the soft budget;
    optional sections are admitted in priority order.
    """
    brief = "\n".join(f"{line.id}. {line.text}" for line in context.brief_lines)
    policy, playbook = shown_passages(context.knowledge)
    sections = [
        Section("rules", HARD_RULES),
        Section("warnings", "\n".join(f"CẢNH BÁO: {w}" for w in context.warnings)),
        Section("lane", (
            f"Lane: {context.lane}. Mức xác minh danh tính: {context.tier}. Kênh: {context.channel}."
            + (f" Hồ sơ đứng tên: {context.address_as}." if context.address_as else _address_note(context))
            + f"\n{lane_instruction(context)}"
        ).strip()),
        Section("products", _products_block(context.seen_products)),
        Section("orders", _orders_block(context.created_orders, context.updated_orders)),
        Section("brief", f"Call Brief:\n{brief}" if brief else ""),
        Section("summary", f"Tóm tắt các lượt trước:\n{context.working_summary}" if context.working_summary else ""),
        Section("knowledge", "\n".join(x for x in (_knowledge_block("Tài liệu liên quan", policy),
                                                    context.knowledge_note) if x)),
        Section("playbook", _knowledge_block("Kinh nghiệm xử lý đã được duyệt", playbook)),
        Section("tool_results", _tool_block(context.tool_results)),
        Section("opening", OPENING[bool(context.brief_lines)] if context.phase == "opening" else ""),
        Section("blocked", _blocked_block(context)),
    ]
    pack = assemble(sections, max_tokens=max_tokens)
    return pack.text, pack.cut


def shown_passages(knowledge: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """What the model reads of a turn's passages: the first three from the documents, and the playbook entries.

    The guard checks a reply against these and no others: a number from a
    passage the model never saw cannot be a number it read (section 4.5).
    """
    policy = [p for p in knowledge if p.get("source") != "playbook"][:KNOWLEDGE_SHOWN]
    playbook = [p for p in knowledge if p.get("source") == "playbook"]
    return policy, playbook


def _knowledge_block(heading: str, passages: Sequence[Mapping[str, Any]]) -> str:
    """Passages as the model reads them: a restricted one as a refusal, a superseded one with its dates."""
    if not passages:
        return ""
    lines = []
    for passage in passages:
        code = passage.get("chunk_id") or "?"
        title = passage.get("title") or ""
        if passage.get("restricted"):
            lines.append(passage.get("instruction") or f"Đoạn [{code}] là thông tin nội bộ: không đọc, không trích.")
            continue
        validity = f" (đoạn này {passage['validity']})" if passage.get("superseded") and passage.get("validity") else ""
        lines.append(f"[{code}] {title}{validity}: {str(passage.get('text') or '').strip()}")
    return f"{heading}:\n" + "\n".join(lines)


def _address_note(context: AgentContext) -> str:
    """How to address a customer the shop does not know yet."""
    if context.self_called:
        return f" Khách tự xưng là {context.self_called}: gọi khách là {context.self_called}, xưng em, dùng nhất quán."
    if context.honorific_asked:
        return " Chưa biết danh xưng và em đã hỏi rồi: gọi anh/chị, không hỏi lại."
    return (" Chưa biết danh xưng: tạm gọi anh/chị. Ở lượt thứ hai, hoặc khi xin thông tin đặt hàng, hỏi đúng một lần, "
            "gộp vào câu hỏi đang cần hỏi: \"Dạ cho em hỏi mình xưng hô là anh hay chị ạ?\"")


def _blocked_block(context: AgentContext) -> str:
    """Why the last draft was blocked, and when part of the answer was already said, what to go on from."""
    if not context.block_reasons:
        return ""
    reasons = "; ".join(context.block_reasons)
    if context.already_said:
        return (f"Khách đã nghe em nói: «{' '.join(context.already_said)}». Câu tiếp theo của em bị chặn vì: {reasons} "
                "Nói tiếp phần còn lại của câu trả lời, không lặp lại phần khách đã nghe; cần tool thì gọi trước khi nói.")
    return f"Câu trả lời trước của em đã bị chặn vì: {reasons} Hãy soạn lại, tránh đúng những điểm đó."


def _orders_block(orders: Sequence[Mapping[str, Any]], changes: Sequence[Mapping[str, Any]] = ()) -> str:
    """The orders this call created and the changes it made: neither is done a second time."""
    parts = []
    if orders:
        lines = [f"- {o['order_id']}" + (f": {o['sku']}" if o.get("sku") else "") for o in orders]
        parts.append("Đơn đã tạo trong cuộc này (khách bổ sung địa chỉ, đổi thanh toán thì gọi order_update trên đơn "
                     "đó, không tạo đơn mới):\n" + "\n".join(lines))
    if changes:
        lines = [f"- {c.get('order_id')}: {c.get('action')}" + (f" sang {c['new_variant_sku']}" if c.get("new_variant_sku") else "")
                 for c in changes]
        parts.append("Thay đổi đã thực hiện trong cuộc này (đã xong, không gọi order_update lại cho cùng thay đổi; "
                     "khách hỏi lại thì báo kết quả và phí của lần đó):\n" + "\n".join(lines))
    return "\n".join(parts)


def _products_block(products: Sequence[Mapping[str, Any]]) -> str:
    """The products tools showed earlier in this call, with their codes: what a later turn quotes and orders."""
    if not products:
        return ""
    lines = [f"- {p['sku']}: {p.get('name') or '?'}" + (f", {format_vnd(int(p['price_vnd']))}" if p.get("price_vnd") else "")
             for p in products]
    return ("Sản phẩm đã tra trong cuộc này (mã chính xác: báo giá, kiểm kho, đặt đơn dùng đúng mã này; "
            "giá ở đây có thể đã cũ, đặt đơn vẫn gọi pricing_get_quote):\n" + "\n".join(lines))


def _tool_block(results: Sequence[Mapping[str, Any]]) -> str:
    if not results:
        return ""
    lines = [f"- {r['name']}({json.dumps(r.get('args') or {}, ensure_ascii=False)}) -> "
             f"{json.dumps(r.get('result'), ensure_ascii=False)}" for r in results]
    return "Kết quả tool đã có trong lượt này (dùng lại, không cần gọi lại):\n" + "\n".join(lines)


class ContextPromptMiddleware(AgentMiddleware):
    """The system message for each model call, built from the run's context.

    Both hooks are implemented on purpose: the framework does not derive one
    from the other, and the service is async.
    """

    def __init__(self, model_limit: int = 8) -> None:
        super().__init__()
        self.model_limit = model_limit

    def _with_prompt(self, request: ModelRequest) -> ModelRequest:
        context = getattr(getattr(request, "runtime", None), "context", None)
        if not isinstance(context, AgentContext):
            return request
        prompt, _ = system_prompt(context)
        prompt = pii.tokenise(prompt, context.vault)
        if request.state.get("run_model_call_count", 0) >= self.model_limit - 1:
            prompt += ("\nĐây là lượt model cuối: không gọi thêm tool. Trả lời ngắn từ kết quả đã có; "
                       "thiếu dữ liệu thì nói chưa kiểm tra được và xin đúng thông tin còn thiếu. "
                       "Không khẳng định thao tác thành công nếu chưa có kết quả tool thành công.")
            return request.override(system_message=SystemMessage(content=prompt), tools=[])
        return request.override(system_message=SystemMessage(content=prompt))

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        return handler(self._with_prompt(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        return await handler(self._with_prompt(request))


class ActionGuardMiddleware(AgentMiddleware):
    """The guardrail before act (section 4.4): a write tool runs only if its arguments pass."""

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = request.tool_call
        name = call["name"]
        if name not in actions.WRITE_TOOLS | actions.SKU_READ_TOOLS | actions.CUSTOMER_READ_TOOLS:
            return await handler(request)
        context = getattr(getattr(request, "runtime", None), "context", None)
        if not isinstance(context, AgentContext):
            return ToolMessage(content=json.dumps({"ok": False, "error": {"code": "PRECONDITION",
                "retryable": False, "message": "Missing trusted runtime context."}}),
                tool_call_id=call["id"], name=name, additional_kwargs={"blocked_by": "guardrail"})
        args = dict(call.get("args") or {})
        if name == "handoff_transfer":
            args["brief"] = actions.fill_handoff(args.get("brief") or {}, context.handoff_defaults)
        state = getattr(request, "state", None) or {}
        quotes = {**context.quotes, **_quotes_in(state)}
        codes, orders = _seen_in(state, context.tool_results)
        created = (*context.created_orders, *_created_in(state))
        intents = await _intents(name, args, context, created)
        verdict = actions.check(
            name, args, tier=context.tier, mode=context.mode, has_phone=bool(context.customer_phone),
            quotes=quotes, orders=context.known_orders | orders, trusted=context.trusted_skus | codes | set(quotes),
            lane=context.lane, intents=intents, now=context.now,
            last_agent_said=context.last_agent_said, customer_said=context.customer_said,
            shared_phone=context.shared_phone, created=created,
            updated=(*context.updated_orders, *_updated_in(state, context.tool_results)),
            placed=placed_this_call(context, state),
        )
        if not verdict.passed:
            envelope = {"ok": False, "error": {"code": "PRECONDITION", "retryable": False, "message": " ".join(verdict.reasons)}}
            return ToolMessage(
                content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=name,
                additional_kwargs={"args": args, "blocked_by": "guardrail"},
            )
        return await handler(request.override(tool_call={**call, "args": args}))


def placed_this_call(context: AgentContext, state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Order lines created this call: earlier turns, earlier runs of this turn, this run; one per order id."""
    lines = {line["order_id"]: dict(line) for line in context.placed_lines}
    lines.update({line["order_id"]: line for line in actions.placed_lines(
        [*context.tool_results, *tool_results_of(state.get("messages") or [])])})
    return list(lines.values())


async def _intents(name: str, args: Mapping[str, Any], context: AgentContext,
                   created: Sequence[Mapping[str, Any]]) -> dict[str, bool | None]:
    """What the customer means, for the one action about to run, read by Jev (section 4.4).

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
        documents = [str(p.get("text") or "")[:400] for p in context.knowledge[:3] if p.get("text")]
        return {"handoff": await context.judge("handoff", {
            "recent_messages": said,
            "reason_given": {"escalation_reason": brief.get("escalation_reason"),
                             "detail": brief.get("escalation_reason_detail")},
            "shop_documents_found": documents or [context.knowledge_note or "no passage was relevant"],
        })}
    if name == "memory_request_deletion" and context.tier == "VERIFIED":
        return {"delete": await context.judge("delete", {"recent_messages": said})}
    if name == "order_update":
        change = {k: args.get(k) for k in ("order_id", "action", "new_variant_sku", "new_address") if args.get(k)}
        return {"change": await context.judge("change", {"recent_messages": said, "change": change})}
    if name == "order_create" and any(o.get("sku") and o.get("sku") == args.get("sku") for o in created):
        return {"one_more": await context.judge("one_more", {"recent_messages": said,
                                                             "already_ordered": args.get("sku")})}
    return {}


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
                created.append({"order_id": data["order_id"], "sku": asked.get(message.tool_call_id, {}).get("sku")})
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


def _quotes_in(state: Mapping[str, Any]) -> dict[str, int]:
    """Today's price per sku from the pricing results already in this run."""
    quotes: dict[str, int] = {}
    for message in state.get("messages") or []:
        if isinstance(message, ToolMessage) and message.name == "pricing_get_quote":
            envelope = envelope_of(message) or {}
            data = envelope.get("data") or {}
            if envelope.get("ok") and data.get("sku") and data.get("final_price_vnd") is not None:
                quotes[data["sku"]] = int(data["final_price_vnd"])
    return quotes


class AdvisorAgent(BaseAgent):
    """Drafts the reply for one turn, from the slice of state it is given."""

    #: Four items need catalogue, quote, stock and order each, plus delivery.
    TOOL_CALLS_PER_RUN = 20
    MODEL_CALLS_PER_RUN = 8

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
        retryable tool failure (sections 4.9 and 6.1). An evaluation harness
        that must see every attempt sets it to 0. ``llm`` replaces the model
        from config, for offline tests."""
        super().__init__("advisor", provider=provider, model=model, generation=generation, llm=llm)
        self._tools = list(tools or ())
        names = [tool.name for tool in self._tools]
        retry = [ModelRetryMiddleware(max_retries=retries, initial_delay=1.0, on_failure="error")] if retries else []
        self._graph = create_agent(
            model=self.llm,
            tools=self._tools,
            middleware=[
                ContextPromptMiddleware(self.MODEL_CALLS_PER_RUN),
                *retry,
                ModelCallLimitMiddleware(run_limit=self.MODEL_CALLS_PER_RUN, exit_behavior="error"),
                ToolCallLimitMiddleware(run_limit=self.TOOL_CALLS_PER_RUN, exit_behavior="continue"),
                LaneToolsMiddleware(get_lanes(), names),
                ActionGuardMiddleware(),
                ToolGuardMiddleware(names, retries=retries),
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
        the harness abandons a draft whose sentence the guard blocked
        (section 4.8).
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
                        yield AdvisorEvent("tools", results=tuple(tool_results_of(produced)))
                    continue
                message, meta = chunk
                # A model that streams sends chunks; one that does not sends its
                # whole message once, which is a chunk's parent class.
                if meta.get("langgraph_node") != "model" or not isinstance(message, AIMessage):
                    continue
                calls = message.tool_call_chunks if isinstance(message, AIMessageChunk) else message.tool_calls
                if calls:
                    if message.id not in announced:
                        announced.add(message.id or "")
                        yield AdvisorEvent("tool_started")
                    continue
                text = text_of(message, strip=False)
                if text:
                    yield AdvisorEvent("text", text=text)
        except Exception as error:
            raise AdvisorFailure(error, self._draft_of(produced, started)) from error
        yield AdvisorEvent("done", draft=self._draft_of(produced, started))

    def _draft_of(self, produced: Sequence[Any], started: float) -> Draft:
        return Draft(
            text=_final_text(produced),
            tool_results=tool_results_of(produced),
            model=self.model_name,
            model_calls=sum(1 for m in produced if isinstance(m, AIMessage)),
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
            answer = answers.get(call["id"])
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
            results.append({
                "name": dotted(call["name"]),
                "args": (answer.additional_kwargs.get("args") if answer is not None else None) or call["args"],
                "result": envelope,
                "blocked_by": blocked_by,
            })
    return results
