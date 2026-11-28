"""Binding MCP tools to an agent: by lane, with a guard around every call.

Two middleware, both deliberately
*not* a tool class of our own — the framework's ``@tool`` and the MCP adapter
already produce the tools; what is ours is the policy around them.

- :class:`LaneToolsMiddleware`. The lane ``route`` chose decides
  which tools the model is offered on each call. The table is
  ``config/lanes.yaml``, a declaration rather than code, because the brief
  asks the team to present "when a tool is called and when it is not".
- :class:`ToolGuardMiddleware`. A timeout on every
  call (2 s, 3 s for knowledge), one retry when the server says the failure
  is retryable, a circuit breaker that skips a tool for a minute after it
  fails twice in a row. Around the call, the harness's two duties of section
  4.4: it fills in ``on`` (the day of the call) and ``customer_phone`` so
  the model never needs to see the number, and it removes every field whose
  name starts with ``_internal`` from the result before the model reads it.
  Business outcomes such as a price mismatch are ``ok: false`` too, but they
  are answers, not failures: they never count against the breaker.

A tool with an effect (:data:`WRITE_TOOLS`) is never retried, whatever the
server says: a timeout leaves its outcome unknown, and a second attempt is
how one order becomes two. Each of its calls carries an idempotency key
instead, ``call:turn:tool:hash of the arguments``, which the server keeps
with the first result and answers again on a repeat (Stripe
does the same for every request that creates or changes something). Its
declared defaults (``qty``, ``payment``) are written into the arguments, so
the trace records the order that was actually placed, not only what the
model typed.

Both are shared by every request that runs through one compiled agent, so
the only mutable state is the breaker's, and it is meant to be shared: a
server that is down is down for everyone.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from typing import TypedDict, Any, Iterable, Mapping, Sequence

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from ..components import clock
from ..components.intake import pii
from ..components.guardrails import fallback, purchase
from ..components.guardrails import actions
from ..components.guardrails.actions import NEEDS_NUMBER
from ..components.intake.text import plain
from ..observability import stopwatch

logger = logging.getLogger(__name__)

#: Error codes that mean the tool could not be reached or ran no business
#: logic. Only these count against the circuit breaker.
INFRASTRUCTURE_CODES = frozenset({"TIMEOUT", "TOOL_ERROR", "INTERNAL", "CIRCUIT_OPEN"})

#: The logged-in shopper's website account (``mcp/servers/account.py``): offered only with an account.
ACCOUNT_PREFIX = "account_"

#: Tools with an effect on the business, by wire name: never
#: retried, each call keyed for idempotency, their defaults made explicit.
WRITE_TOOLS = frozenset({
    "order_create", "order_update", "schedule_callback", "handoff_transfer", "memory_request_deletion",
})

#: The argument a write tool's server keeps its first result under.
IDEMPOTENCY_ARG = "idempotency_key"

#: An address argument that says there is none ("chưa có địa chỉ", "không rõ", "N/A"), on the plain
#: text: a tool would take it for an address (``delivery.estimate`` dated a delivery to it). A real
#: address never begins so.
NO_ADDRESS = re.compile(r"^\s*(?:chua|khong|unknown|none|null|n/?a|tbd)\b|^\s*[-?.]*\s*$")


def _tool_name(tool: Any) -> str | None:
    """The name of a bound tool, whether it is a BaseTool or a provider dict."""
    name = getattr(tool, "name", None)
    if name:
        return str(name)
    if isinstance(tool, dict):
        return tool.get("name") or (tool.get("function") or {}).get("name")
    return None


#: Arguments the harness fills in (:meth:`ToolGuardMiddleware._with_context`): the model is never asked for them.
SYSTEM_ARGS = frozenset({"on", "customer_phone", "customer_id", "account_id", "call_id", "turn_id",
                         "purchase_authorization", IDEMPOTENCY_ARG})

#: Arguments of one tool the harness fills or that nothing reads, kept from the model (plan 002, 2026-11-15): each
#: costs output tokens on the call the customer waits for. ``price_vnd`` is today's quote (``_filled_order``),
#: ``promo_code`` the organisers' mock works out itself, a call back's ``note`` is not read by anything that decides.
HARNESS_ARGS = {"order_create": frozenset({"price_vnd", "promo_code"}), "schedule_callback": frozenset({"note"})}

#: ``handoff_transfer`` takes the brief as an open object, since the harness adds to it; the model writes these.
MODEL_ARGS = {
    "handoff_transfer": {
        "brief": {
            "type": "object",
            "description": "What the person taking the call needs. The system fills in the customer and the product.",
            "properties": {
                "escalation_reason": {"type": "string", "enum": [
                    "cau_hoi_y_te", "ngoai_pham_vi_tai_lieu", "khach_yeu_cau_gap_nguoi", "khieu_nai_nghiem_trong",
                    "loi_he_thong", "khach_mat_kien_nhan", "khac"]},
                "escalation_reason_detail": {"type": "string"},
                "conversation_summary": {"type": "string", "description": "Two to five sentences."},
                "open_questions": {"type": "array", "items": {"type": "string"},
                                   "description": "The questions not yet answered."},
                "next_action": {"type": "string", "description": "What the person should do first."},
            },
            "required": ["escalation_reason", "escalation_reason_detail", "conversation_summary", "open_questions",
                         "next_action"],
        },
    },
}


def short_brief() -> bool:
    """``ADVISOR_SHORT_BRIEF=1``: the model writes only a Handoff Brief's reason, its detail and a short summary; the
    harness fills in the rest from the state (``actions.fill_handoff``). Off unless set, until its effect on the
    scored metrics is measured (2026-11-15: the round writing the whole brief took about 2.7 s)."""
    return os.environ.get("ADVISOR_SHORT_BRIEF", "0").strip().lower() not in ("0", "false", "no", "off", "")


#: The short brief: what only the conversation knows and the harness cannot fill in.
SHORT_BRIEF = {
    "type": "object",
    "description": "What the person taking the call needs. The system fills in the customer, the product, the "
                   "customer's open question and the next step.",
    "properties": {
        "escalation_reason": MODEL_ARGS["handoff_transfer"]["brief"]["properties"]["escalation_reason"],
        "escalation_reason_detail": {"type": "string", "description": "One sentence."},
        "conversation_summary": {"type": "string", "description": "One or two sentences."},
    },
    "required": ["escalation_reason", "escalation_reason_detail", "conversation_summary"],
}


def model_args(name: str) -> dict[str, Any]:
    """The arguments the model writes for tool *name* in place of the declared ones (:data:`MODEL_ARGS`)."""
    if name == "handoff_transfer" and short_brief():
        return {"brief": SHORT_BRIEF}
    return MODEL_ARGS.get(name) or {}


def _strict_value(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A value's schema as strict mode takes it: no defaults, and every object closed with all fields required."""
    value = {k: v for k, v in schema.items() if k not in ("default", "title")}
    if value.get("type") == "object":
        return _strict_object(value)
    if isinstance(value.get("items"), Mapping):
        value["items"] = _strict_value(value["items"])
    if isinstance(value.get("anyOf"), list):
        value["anyOf"] = [_strict_value(option) for option in value["anyOf"]]
    return value


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """An optional field as strict mode says it: required, and null when there is nothing to say."""
    if any(option.get("type") == "null" for option in schema.get("anyOf") or []):
        return schema
    description = {k: schema[k] for k in ("description",) if k in schema}
    return {"anyOf": [{k: v for k, v in schema.items() if k != "description"}, {"type": "null"}], **description}


def _strict_object(schema: Mapping[str, Any]) -> dict[str, Any]:
    required = set(schema.get("required") or [])
    properties = {name: (_strict_value(spec) if name in required else _nullable(_strict_value(spec)))
                  for name, spec in (schema.get("properties") or {}).items()}
    return {**{k: v for k, v in schema.items() if k not in ("default", "title")}, "type": "object",
            "properties": properties, "required": list(properties), "additionalProperties": False}


def strict_tool(tool: Any) -> dict[str, Any]:
    """*tool* as the model is offered it: only what it should write, under strict mode (OpenAI's recommendation)."""
    formatted = convert_to_openai_tool(tool)
    function = formatted["function"]
    name = function["name"]
    parameters = dict(function.get("parameters") or {"type": "object", "properties": {}})
    hidden = SYSTEM_ARGS | HARNESS_ARGS.get(name, frozenset())
    shown = {key: spec for key, spec in (parameters.get("properties") or {}).items() if key not in hidden}
    shown.update(model_args(name))
    required = [key for key in parameters.get("required") or [] if key in shown]
    function = {**function, "parameters": _strict_object({**parameters, "properties": shown, "required": required}),
                "strict": True}
    return {"type": "function", "function": function}


class StrictToolsMiddleware(AgentMiddleware):
    """Offers tools under strict mode. Execution is unchanged: the harness still sees and fills every argument."""

    def __init__(self) -> None:
        super().__init__()
        self._shown: dict[str, dict[str, Any]] = {}

    def _strict(self, request: Any) -> Any:
        tools = []
        for tool in request.tools:
            name = _tool_name(tool)
            if isinstance(tool, dict) or name is None:
                tools.append(tool)
                continue
            if name not in self._shown:
                self._shown[name] = strict_tool(tool)
            tools.append(self._shown[name])
        return request.override(tools=tools)

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._strict(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._strict(request))


def other_products_only(args: Mapping[str, Any]) -> dict[str, Any]:
    """A basket holds the *other* products: naming the one quoted, at one unit, would read as a second unit of it
    and bring a promotion on a second item the customer is not buying."""
    fixed = dict(args)
    basket = fixed.get("basket_skus")
    if basket and int(fixed.get("qty") or 1) == 1:
        others = [sku for sku in basket if sku != fixed.get("sku")]
        if others:
            fixed["basket_skus"] = others
        else:
            fixed.pop("basket_skus")
    return fixed


def without_nulls(request: Any) -> Any:
    """Strict mode writes null for an optional field: to a tool that is the same as leaving it out."""
    call = request.tool_call
    args = call.get("args")
    if not isinstance(args, Mapping) or all(value is not None for value in args.values()):
        return request
    return request.override(tool_call={**call, "args": {k: v for k, v in args.items() if v is not None}})


def _offered_late(name: str) -> int:
    """Where a tool goes in the list the model is sent: the ones some state takes away go last.

    OpenAI caches the longest prefix two requests share, and the tools come first in it: a tool missing from the
    middle of the list would cost the cache everything after it. Writes go only in copilot, a transfer only while it
    waits on a number, the memory tools without a brief, the account tools without a login. The sort is stable, so
    each group keeps the order it came in.
    """
    if name.startswith(ACCOUNT_PREFIX):
        return 4
    if name.startswith("memory_") and name not in WRITE_TOOLS:
        return 3
    if name == "handoff_transfer":
        return 2
    return 1 if name in WRITE_TOOLS else 0


class LaneToolsMiddleware(AgentMiddleware):
    """Offers the model only the tools the run's lane allows, in an order that keeps the cached prefix long."""

    def __init__(self, lanes: Mapping[str, frozenset[str]], mcp_tool_names: Iterable[str]) -> None:
        super().__init__()
        self._lanes = {lane: frozenset(names) for lane, names in lanes.items()}
        self._mcp = frozenset(mcp_tool_names)

    def _filtered(self, request: Any) -> Any:
        context = getattr(getattr(request, "runtime", None), "context", None)
        lane = getattr(context, "lane", None)
        allowed = self._lanes.get(lane)
        if allowed is None:
            # A lane the table does not know gets nothing rather than
            # everything: the safe reading of a missing row.
            if lane is not None:
                logger.warning("Lane %r is not in config/lanes.yaml; binding no tools", lane)
            allowed = frozenset()
        # Anything that is not an MCP tool — a structured-output tool, for
        # one — is left alone.
        if not getattr(context, "account_id", None):
            # The website account's tools are for a logged-in shopper only.
            allowed = frozenset(name for name in allowed if not name.startswith(ACCOUNT_PREFIX))
        if not getattr(context, "customer_phone", None) and any(
                o.get("tool") == "handoff.transfer" and o.get("said") == NEEDS_NUMBER
                for o in getattr(context, "offered", None) or ()):
            # A transfer waits on the customer's number, and there is none yet: offered again, the model calls it again
            # and is refused again, a model round each time (2026-11-24: four turns running). It comes back with the
            # number, and route puts the call through.
            allowed = allowed - {"handoff_transfer"}
        if getattr(context, "mode", None) == "copilot":
            # A consultant has the call: the assistant suggests, the person acts (the action guard refuses it anyway,
            # and each refusal cost a model round: 2026-11-24, four in one call).
            allowed = allowed - WRITE_TOOLS
        tools = [
            tool
            for tool in request.tools
            if (name := _tool_name(tool)) not in self._mcp or name in allowed
        ]
        return request.override(tools=sorted(tools, key=lambda tool: _offered_late(_tool_name(tool))))

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._filtered(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._filtered(request))


#: What an order's status is called to a customer: one plain phrase per status of the mock's enum, put beside each
#: order of an ``order_status`` result so the model says the status rather than a paraphrase that changes it.
STATUS_WORDS = {
    "created": "đã tạo đơn", "pending": "đã tạo đơn", "confirmed": "đã xác nhận",
    "processing": "đang xử lý", "packing": "đang đóng gói",
    "shipping": "đang giao", "delivered": "đã giao", "cancelled": "đã hủy",
    "returned": "đã hoàn về", "pickup_scheduled": "đã hẹn lấy hàng trả",
}




#: What an error of the organisers' tools means and what to do next: a bare code reads as a dead end, and the model
#: went on with a code it had made up instead of searching for the right one.
ERROR_HINTS = {
    "UNKNOWN_SKU": "Mã này không có trong danh mục: gọi catalog_search với tên sản phẩm khách nói để lấy mã đúng, "
                   "không đoán mã và không hỏi khách mã.",
}


def with_hints(message: Any) -> Any:
    """A result whose ``error`` is a code of :data:`ERROR_HINTS` with a ``hint`` beside it; any other as it is."""
    if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
        return message
    try:
        envelope = json.loads(message.content)
    except ValueError:
        return message
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, dict) or data.get("error") not in ERROR_HINTS or "hint" in data:
        return message
    data["hint"] = ERROR_HINTS[data["error"]]
    return message.model_copy(update={"content": json.dumps(envelope, ensure_ascii=False)})


def with_status_words(name: str, message: Any, today: Any = None) -> Any:
    """An ``order_status`` result with ``status_text`` beside each order's ``status``, and ``return_window: "đã hết"``
    on a delivered order placed too long ago to return (the model read the date and booked a return anyway,
    2026-11-27); any other result as it is."""
    if name != "order_status" or not isinstance(message, ToolMessage) or not isinstance(message.content, str):
        return message
    try:
        envelope = json.loads(message.content)
    except ValueError:
        return message
    data = envelope.get("data") if isinstance(envelope, dict) else None
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        return message
    changed = False
    for order in orders:
        if isinstance(order, dict) and order.get("status") in STATUS_WORDS and "status_text" not in order:
            order["status_text"] = STATUS_WORDS[order["status"]]
            changed = True
        window = actions.return_window(order, today) if isinstance(order, dict) else None
        if window == "closed":
            order["return_window"] = f"đã hết hạn đổi trả {actions.RETURN_DAYS} ngày"
            changed = True
        elif window == "defect":
            order["return_window"] = (f"đã quá {actions.RETURN_DAYS} ngày đổi trả; chỉ còn đổi mới nếu lỗi nhà sản xuất, "
                                      f"trong {actions.DEFECT_DAYS} ngày")
            changed = True
    return message.model_copy(update={"content": json.dumps(envelope, ensure_ascii=False)}) if changed else message


class ToolGuardMiddleware(AgentMiddleware):
    """Timeout, one retry, a circuit breaker, and the virtual clock."""

    #: Seconds per call, by tool; everything else gets DEFAULT_TIMEOUT.
    TIMEOUTS = {"kb_search": 3.0, "kb_upsert": 3.0}
    DEFAULT_TIMEOUT = 2.0
    #: A write that times out may still land on the server (2026-11-19, call 27: an order placed 70 ms after its 2 s
    #: limit, the customer told it failed and transferred). A write is given long enough to answer.
    WRITE_TIMEOUT = 10.0

    def __init__(
        self,
        tool_names: Iterable[str],
        *,
        timeout: float | None = None,
        retries: int = 1,
        breaker_failures: int = 2,
        breaker_seconds: float = 60.0,
    ) -> None:
        super().__init__()
        self._guarded = frozenset(tool_names)
        self._timeout = timeout
        self._retries = retries
        self._breaker_failures = breaker_failures
        self._breaker_seconds = breaker_seconds
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    # ── hooks ─────────────────────────────────────────────────────────────

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        from ..runtime import steps  # the turn's live steps (chat, staff console); late: runtime imports mcp

        call = request.tool_call
        name = call["name"]
        today = getattr(getattr(getattr(request, "runtime", None), "context", None), "now", None)
        if name not in self._guarded:
            return with_hints(with_status_words(name, await handler(request), today))
        async with steps.tool(name) as step:
            result = await self._guarded_call(request, handler, call, name)
            envelope = envelope_of(result)
            step["ok"] = envelope is None or bool(envelope.get("ok", True))
            return with_hints(with_status_words(name, result, today))

    async def _guarded_call(self, request: Any, handler: Any, call: Any, name: str) -> Any:
        if self._is_open(name):
            return self._envelope_message(
                call, "CIRCUIT_OPEN", f"{name} is paused after repeated failures", retryable=False
            )
        request = self._with_context(request)

        limit = self._timeout or self.TIMEOUTS.get(
            name, self.WRITE_TIMEOUT if name in WRITE_TOOLS else self.DEFAULT_TIMEOUT)
        attempt = 0
        while True:
            attempt += 1
            try:
                result = strip_internal(await asyncio.wait_for(handler(request), timeout=limit))
            except asyncio.TimeoutError:
                result = self._envelope_message(
                    call, "TIMEOUT", f"{name} did not answer within {limit:g}s", retryable=True
                )
            except Exception as error:  # noqa: BLE001 - reported to the model as data
                logger.warning("Tool %s raised %s", name, type(error).__name__)
                result = self._envelope_message(
                    call, "TOOL_ERROR", type(error).__name__, retryable=True
                )
            if self._settle(name, result, attempt):
                return visible_result(with_args(result, request.tool_call.get("args") or {}), request)

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        """The sync path, for scripts: same policy without the timeout."""
        call = request.tool_call
        name = call["name"]
        if name not in self._guarded:
            return handler(request)
        if self._is_open(name):
            return self._envelope_message(
                call, "CIRCUIT_OPEN", f"{name} is paused after repeated failures", retryable=False
            )
        request = self._with_context(request)

        attempt = 0
        while True:
            attempt += 1
            try:
                result = strip_internal(handler(request))
            except Exception as error:  # noqa: BLE001
                logger.warning("Tool %s raised %s", name, type(error).__name__)
                result = self._envelope_message(
                    call, "TOOL_ERROR", type(error).__name__, retryable=True
                )
            if self._settle(name, result, attempt):
                return visible_result(with_args(result, request.tool_call.get("args") or {}), request)

    # ── policy ────────────────────────────────────────────────────────────

    def _settle(self, name: str, result: Any, attempt: int) -> bool:
        """Decide whether *result* is final. Updates the breaker.

        A write tool's failure is always final: its outcome may be unknown,
        and the idempotency key, not a retry, is what makes a repeat safe.
        """
        envelope = envelope_of(result)
        if envelope is None or envelope.get("ok", True):
            self._failures[name] = 0
            return True
        error = envelope.get("error") or {}
        if error.get("retryable") and attempt <= self._retries and name not in WRITE_TOOLS:
            logger.info("Tool %s failed with %s; retrying once", name, error.get("code"))
            return False
        if error.get("code") in INFRASTRUCTURE_CODES:
            self._record_failure(name, error)
        return True

    def _is_open(self, name: str) -> bool:
        return self._open_until.get(name, 0.0) > time.monotonic()

    def _record_failure(self, name: str, error: Mapping[str, Any]) -> None:
        count = self._failures.get(name, 0) + 1
        self._failures[name] = count
        if count >= self._breaker_failures:
            self._open_until[name] = time.monotonic() + self._breaker_seconds
            self._failures[name] = 0
            # Repeated failure is what moves
            # route towards HANDOFF; the advisor step counts failures from
            # the tool results into the state's flags.
            logger.warning(
                "Circuit open for tool %s for %.0fs after %s: %s",
                name, self._breaker_seconds, error.get("code"), error.get("message"),
            )

    def _with_context(self, request: Any) -> Any:
        """Fill in what the run knows and the model should not have to.

        The day of the call goes into any tool that takes ``on``, the
        customer's phone into any that takes ``customer_phone`` (except the
        lookup, whose phone is the question), the customer id into any that
        takes ``customer_id`` and the call into any that takes ``call_id``.
        Each overrides whatever the model wrote.
        A write tool also gets its declared defaults written out and its
        idempotency key.
        """
        context = getattr(getattr(request, "runtime", None), "context", None)
        tool = getattr(request, "tool", None)
        accepted = getattr(tool, "args", None)
        if context is None or not isinstance(accepted, dict):
            return request
        name = request.tool_call["name"]
        args = dict(request.tool_call.get("args") or {})
        args.pop(IDEMPOTENCY_ARG, None)  # the harness's to set, never the model's
        args = other_products_only(args)
        if name in WRITE_TOOLS:
            args = {**declared_defaults(accepted, exclude=(IDEMPOTENCY_ARG,)), **args}
        on = getattr(context, "on", None)
        if on and "on" in accepted:
            args["on"] = on
        phone = getattr(context, "customer_phone", None)
        if (name == "crm_get_customer" and phone and "phone" in accepted
                and getattr(context, "tier", None) == "VERIFIED"):
            # Order lookup stays on the verified caller, never a model-supplied identity.
            args = {"phone": phone}
        if "customer_phone" in accepted and name != "crm_get_customer":
            args["customer_phone"] = phone
        if isinstance(args.get("address"), str) and NO_ADDRESS.search(plain(args["address"])):
            args.pop("address")
        addresses = getattr(context, "addresses", None) or {}
        vault = getattr(context, "vault", None)
        if vault is not None and args.get("address"):
            addresses = {**addresses, **{token: value for token, (kind, value) in vault.entries.items() if kind == "ADDR"}}
        if addresses and "address" in accepted:
            args["address"] = with_addresses(args.get("address"), addresses)
        customer = getattr(context, "customer_id", None)
        if "customer_id" in accepted:
            args["customer_id"] = customer
        if "account_id" in accepted:
            # The logged-in shopper of this conversation, never one the model names.
            args["account_id"] = getattr(context, "account_id", None)
        call_id = getattr(context, "call_id", None)
        if "call_id" in accepted:
            args["call_id"] = str(call_id) if call_id is not None else None
        if name == "order_create":
            business_args = order_arguments(args, context)
            for field in ("call_id", "turn_id", "purchase_authorization"):
                args.pop(field, None)
            if "call_id" in accepted:
                args["call_id"] = str(context.call_id)
            if "turn_id" in accepted:
                args["turn_id"] = context.turn_id
            if "purchase_authorization" in accepted:
                args["purchase_authorization"] = purchase.receipt(
                    (getattr(context, "consent", None) or {}).get("draft") or getattr(context, "pending_purchase", None),
                    business_args, context)
        if name == "schedule_callback" and (moment := clock.parse_local(args.get("callback_at"))) is not None:
            args["callback_at"] = clock.tool_time(moment)
        if name in WRITE_TOOLS and IDEMPOTENCY_ARG in accepted:
            key = idempotency_key(context, name, args)
            if key:
                args[IDEMPOTENCY_ARG] = key
        if args == request.tool_call.get("args"):
            return request
        return request.override(tool_call={**request.tool_call, "args": args})

    @staticmethod
    def _envelope_message(
        call: Mapping[str, Any], code: str, message: str, *, retryable: bool
    ) -> ToolMessage:
        envelope = {"ok": False, "error": {"code": code, "retryable": retryable, "message": message}}
        return ToolMessage(
            content=json.dumps(envelope, ensure_ascii=False),
            tool_call_id=call["id"],
            name=call["name"],
        )


#: Marks the tool calls the harness made itself, so they do not count as a model call.
CHAINED = "chained"
SEARCH, QUOTE, STOCK = "catalog_search", "pricing_get_quote", "inventory_check"


def chained_lookups(messages: Sequence[Any]) -> list[dict[str, Any]]:
    """The price and stock calls a search that found one product leads to, unless this run already made them.

    A quote needs the code a search returns, so it takes a model round of its own; these are one call each and
    take milliseconds. Run only once a round of tools has finished, so calls and their results stay in order.
    """
    results: list[ToolMessage] = []
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            break
        results.append(message)
    skus = []
    for result in reversed(results):
        data = ((parse_envelope(result.content) or {}).get("data") or {}) if result.name == SEARCH else {}
        items = data.get("items") or []
        if len(items) == 1 and isinstance(items[0].get("sku"), str) and not items[0].get("successor_sku"):
            skus.append(items[0]["sku"])
    if not skus:
        return []
    done: set[tuple[str, str]] = set()
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        for call in getattr(message, "tool_calls", None) or []:
            done.add((call["name"], str((call.get("args") or {}).get("sku"))))
    calls = []
    for sku in dict.fromkeys(skus):
        for name, args in ((QUOTE, {"sku": sku, "qty": 1}), (STOCK, {"sku": sku})):
            if (name, sku) not in done:
                calls.append({"name": name, "args": args, "id": f"chain-{uuid.uuid4().hex[:12]}", "type": "tool_call"})
    return calls


def _call(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
    return {"name": name, "args": dict(args), "id": f"chain-{uuid.uuid4().hex[:12]}", "type": "tool_call"}


#: The team's own tool for a question that needs weighing (plan 002, B3): which product fits a need, or which of the
#: named ones to take. The organisers allow a team's own tools (``DIEU-CHINH-DE.md`` section 3); the calls it makes
#: are theirs and are what the trace records.
ADVISE = "product_advise"
#: Products priced and checked per call: two to offer and one to compare with.
ADVISE_TOP = 3


#: The team's tool for a COD basket above the limit: the system arranges and prices the orders (QT-01, VC-03).
SPLIT = "order_split_cod"


class SplitLine(TypedDict):
    """One product of the basket to split."""

    sku: str
    qty: int


async def order_split_cod(lines: list[SplitLine], address: str | None = None) -> str:
    """Place a cash-on-delivery basket above 10.000.000đ as several COD orders, each at most 10.000.000đ.

    Use it only when the customer agreed to split the basket. The system prices the basket, arranges the orders so the
    second-machine discount is kept (QT-01), and places each one with the shop's order tool. The first call returns the
    orders to read back (CONFIRMATION_REQUIRED, each order's items and total); after the customer agrees, call it again
    with the same basket and the orders are placed.

    Args:
        lines: Every product of the basket, each with its code (the variant's for a size or colour) and quantity.
        address: The delivery address the customer gave, if any.
    """
    raise RuntimeError("order_split_cod runs in ActionGuardMiddleware")  # never reached: the middleware answers it


def product_advise_on() -> bool:
    """``ADVISOR_PRODUCT_ADVISE=1``: the advisor is offered :data:`ADVISE`. Off unless set, until measured."""
    return os.environ.get("ADVISOR_PRODUCT_ADVISE", "0").strip().lower() not in ("0", "false", "no", "off", "")


async def product_advise(category: str | None = None, query: str | None = None, room_area_m2: int | None = None,
                         budget_vnd: int | None = None, has_children: bool | None = None,
                         skus: list[str] | None = None) -> str:
    """Products for what the customer needs, or a comparison of products already named, in one call.

    Searches the catalogue for the need, puts the best fits first and gives the first three with today's price
    (as pricing_get_quote), their stock (as inventory_check) and how each fits: the room area, the budget, a child
    lock. Use it when the customer describes a need or asks which to choose, instead of catalog_search followed by
    pricing_get_quote and inventory_check. Its prices and stock are tool results like theirs.

    Args:
        category: The category slug when the need names a kind of product, e.g. gia-dung/may-loc-khong-khi.
        query: Words to search with: a brand, a model, a feature the customer named.
        room_area_m2: The room's area the customer gave, in m².
        budget_vnd: The customer's budget for one unit, in VND.
        has_children: Whether the customer has small children (a child lock counts).
        skus: Product codes to compare, from earlier tool results; leave out to search.
    """
    raise RuntimeError("product_advise runs in ChainLookupMiddleware")  # never reached: the middleware answers it


def _fit(item: Mapping[str, Any], area: int | None, budget: int | None, children: bool | None) -> tuple[Any, ...]:
    """How well a search result fits the need, best first: the room, the budget, a child lock, then the price."""
    attributes = item.get("attributes") or {}
    price = int(item.get("list_price_vnd") or 0)
    room = attributes.get("room_area_m2")
    return (bool(area) and isinstance(room, (int, float)) and room < area,
            bool(budget) and price > int(budget or 0),
            bool(children) and not attributes.get("child_safe_lock"),
            abs(price - int(budget)) if budget else price)


def _inner(call: Mapping[str, Any], message: Any) -> dict[str, Any]:
    """One call made inside :data:`ADVISE`, as the trace records it."""
    return {"name": call["name"], "args": (getattr(message, "additional_kwargs", {}) or {}).get("args") or call["args"],
            "content": getattr(message, "content", "")}


class ChainLookupMiddleware(AgentMiddleware):
    """Saves the model round between a search and its price: the model then reads real results of real tools. Also
    answers the team's ``product_advise`` with the organisers' tools."""

    def __init__(self, tools: Iterable[Any], guard: ToolGuardMiddleware,
                 lanes: Mapping[str, frozenset[str]] | None = None) -> None:
        super().__init__()
        self._tools = {tool.name: tool for tool in tools}
        self._guard = guard
        self._lanes = lanes or {}

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """The price and stock a search the model just made leads to, in the harness's own round: driven by the
        tools' results, never by the customer's words (plan 003 removed the lookups ahead of the model)."""
        if QUOTE not in self._tools or STOCK not in self._tools:
            return None
        messages = state.get("messages") or []
        calls = chained_lookups(messages)
        if not calls:
            return None
        results = await self._run(calls, state, runtime)
        return {"messages": [AIMessage(content="", tool_calls=calls, additional_kwargs={CHAINED: True}), *results]}

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        if (request.tool_call or {}).get("name") != ADVISE:
            return await handler(request)
        with stopwatch.span("tools"):
            return await self._advise(request)

    async def _advise(self, request: Any) -> Any:
        """:data:`ADVISE`: the organisers' tools, through the same guard as every call, in two rounds of the harness."""
        return await self._advised(request.tool_call, request.state, request.runtime)

    async def _advised(self, call: Mapping[str, Any], state: Any, runtime: Any) -> ToolMessage:
        args = {k: v for k, v in (call.get("args") or {}).items() if v not in (None, "", [])}
        area = int(args["room_area_m2"]) if args.get("room_area_m2") else None
        budget = int(args["budget_vnd"]) if args.get("budget_vnd") else None
        inner: list[dict[str, Any]] = []
        items: dict[str, Mapping[str, Any]] = {}
        skus = [s for s in args.get("skus") or [] if isinstance(s, str)][:ADVISE_TOP]
        if not skus:
            search = {k: args[k] for k in ("query", "category") if args.get(k)}
            if area:
                search["min_room_area_m2"] = area
            searched = _call(SEARCH, search)
            [found] = await self._run([searched], state, runtime)
            inner.append(_inner(searched, found))
            listed = [i for i in ((parse_envelope(found.content) or {}).get("data") or {}).get("items") or []
                      if isinstance(i.get("sku"), str)]
            listed.sort(key=lambda i: _fit(i, area, budget, args.get("has_children")))
            items = {i["sku"]: i for i in listed[:ADVISE_TOP]}
            skus = list(items)
        calls = [c for sku in skus for c in (_call(QUOTE, {"sku": sku, "qty": 1}), _call(STOCK, {"sku": sku}))]
        answers = await self._run(calls, state, runtime) if calls else []
        inner += [_inner(c, a) for c, a in zip(calls, answers)]
        data = {c["args"]["sku"] + ":" + c["name"]: (parse_envelope(a.content) or {}) for c, a in zip(calls, answers)}
        candidates = []
        for sku in skus:
            quote = (data.get(f"{sku}:{QUOTE}") or {}).get("data") or {}
            stock = (data.get(f"{sku}:{STOCK}") or {}).get("data") or {}
            item = items.get(sku) or {}
            attributes = item.get("attributes") or {}
            price = quote.get("final_price_vnd")
            room = attributes.get("room_area_m2")
            candidates.append({
                "sku": sku, "name": item.get("name") or quote.get("name"), "final_price_vnd": price,
                "applied_promos": quote.get("applied_promos"), "in_stock": stock.get("in_stock"), "stock_qty": stock.get("qty"),
                **{k: attributes[k] for k in ("room_area_m2", "features", "warranty_months", "child_safe_lock") if k in attributes},
                "fits_room": None if not area or not isinstance(room, (int, float)) else room >= area,
                "over_budget_vnd": (price - budget) if budget and isinstance(price, int) and price > budget else 0,
            })
        note = ("Không có sản phẩm nào khớp nhu cầu trong danh mục: nói rõ shop chưa có, không đưa sản phẩm loại khác."
                if not candidates else "Giá cuối và tồn kho hôm nay; ứng viên khớp nhu cầu nhất đứng đầu.")
        envelope = {"ok": True, "data": {"candidates": candidates, "note": note}}
        return ToolMessage(content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=ADVISE,
                           additional_kwargs={"inner": inner})

    async def _run(self, calls: Sequence[dict[str, Any]], state: Any, runtime: Any) -> list[Any]:
        async def run(request: Any) -> Any:
            return await request.tool.ainvoke(request.tool_call)

        return list(await asyncio.gather(*(
            self._guard.awrap_tool_call(ToolCallRequest(tool_call=call, tool=self._tools[call["name"]], state=state,
                                                        runtime=runtime), run)
            for call in calls)))


def first_clause() -> bool:
    """``ADVISOR_FIRST_CLAUSE=1``: on a call, the answer's first clause goes to the voice ahead of its sentence
    (``SentenceSplitter.pieces``). Off unless set, until measured."""
    return os.environ.get("ADVISOR_FIRST_CLAUSE", "0").strip().lower() not in ("0", "false", "no", "off", "")


def sentence_review() -> bool:
    """``ADVISOR_SENTENCE_REVIEW=1``: the PolicyAgent reads each said sentence beside the stream. Off unless set."""
    return os.environ.get("ADVISOR_SENTENCE_REVIEW", "0").strip().lower() not in ("0", "false", "no", "off", "")


ADDRESS_TOKEN = re.compile(r"<ADDR_\d+>")


def with_addresses(value: Any, addresses: Mapping[str, str]) -> Any:
    """An ``address`` argument with the call's real addresses: tokens replaced, the latest one when it is empty.

    The model only ever sees ``<ADDR_1>``; the regional promotions and the
    delivery time are decided by the real address (KM-08).
    """
    if not value:
        return list(addresses.values())[-1]
    if isinstance(value, str):
        return ADDRESS_TOKEN.sub(lambda m: addresses.get(m.group(0), m.group(0)), value)
    return value


def declared_defaults(schema: Mapping[str, Any], *, exclude: Iterable[str] = ()) -> dict[str, Any]:
    """The defaults a tool's schema declares, by argument; a None default is no default."""
    skip = set(exclude)
    return {
        field: spec["default"]
        for field, spec in schema.items()
        if field not in skip and isinstance(spec, Mapping) and spec.get("default") is not None
    }


def order_arguments(args: Mapping[str, Any], context: Any) -> dict[str, Any]:
    """Resolve exactly the same business payload before consent and before MCP dispatch."""
    order = dict(args)
    address = order.get("address")
    if isinstance(address, str) and NO_ADDRESS.search(plain(address)):
        address = None
    addresses = getattr(context, "addresses", None) or {}
    vault = getattr(context, "vault", None)
    if vault is not None:
        addresses = {**addresses, **{token: value for token, (kind, value) in vault.entries.items() if kind == "ADDR"}}
    order["address"] = with_addresses(address, addresses) if addresses else address
    order["customer_phone"] = context.customer_phone
    order["on"] = context.on
    return purchase.payload(order)


def idempotency_key(context: Any, name: str, args: Mapping[str, Any]) -> str | None:
    """``<call>:<turn>:<tool>:<hash of the arguments>``, or None without a call and a turn.

    Repeated order creation has one key across the call; other writes are
    scoped to the turn. Any change of argument is a new key.
    """
    call_id = getattr(context, "call_id", None)
    turn_id = getattr(context, "turn_id", None)
    if not call_id or not turn_id:
        return None
    if name == "order_create":
        # An order of lines is keyed on its normal form, as the backend reads it (a line's qty may be left out);
        # one product keeps the key it always had, so a retry across a deploy is still the same order.
        return purchase.order_key(str(call_id), purchase.payload(args) if args.get("lines") else args)
    payload = json.dumps({k: v for k, v in args.items() if k != IDEMPOTENCY_ARG},
                         ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    # shortcut: identical orders in one call are one purchase; add intent IDs for separate identical purchases.
    scope = call_id if name == "order_create" else f"{call_id}:{turn_id}"
    return f"{scope}:{name}:{digest}"


def with_args(result: Any, args: Mapping[str, Any]) -> Any:
    """The tool message, carrying the arguments the tool actually ran with.

    The model wrote some of them; the harness filled in the day and the
    phone. The trace records what ran, so it is kept here.
    """
    if not isinstance(result, ToolMessage):
        return result
    return result.model_copy(update={"additional_kwargs": {**result.additional_kwargs, "args": {k: v for k, v in args.items() if k != "purchase_authorization"}}})


def visible_result(result: Any, request: Any) -> Any:
    """The tool sees raw inputs; model messages and persisted state carry vault tokens."""
    context = getattr(getattr(request, "runtime", None), "context", None)
    vault = getattr(context, "vault", None)
    if vault is None or not isinstance(result, ToolMessage):
        return result
    content = envelope_of(result)
    customer_id = getattr(context, "customer_id", None)
    if request.tool_call["name"] == "crm_get_customer" and customer_id and content and content.get("ok"):
        data = content.get("data") or {}
        if data.get("ambiguous"):
            data = next((c for c in data.get("candidates") or [] if c.get("customer_id") == customer_id), {})
        content = ({"ok": True, "data": {**data, "found": True, "ambiguous": False}}
                   if data.get("customer_id") == customer_id else
                   {"ok": False, "error": {"code": "PROFILE_SCOPE", "retryable": False,
                    "message": "The lookup did not identify the verified customer's profile."}})
    if content is not None:
        shown = json.dumps(pii.tokenise_data(content, vault), ensure_ascii=False)
    else:
        shown = pii.tokenise(str(result.content), vault)
    return result.model_copy(update={"content": shown,
        "additional_kwargs": pii.tokenise_data(result.additional_kwargs, vault)})


def without_internal(value: Any) -> Any:
    """*value* with every key starting with ``_internal`` removed, at any depth."""
    if isinstance(value, dict):
        return {k: without_internal(v) for k, v in value.items() if not str(k).startswith("_internal")}
    if isinstance(value, list):
        return [without_internal(v) for v in value]
    return value


def strip_internal(result: Any) -> Any:
    """A tool message whose envelope no longer carries internal fields.

    ``pricing.get_quote`` returns the price floor below which staff may not
    go; it is for the harness, never for the model.
    """
    envelope = envelope_of(result)
    if envelope is None:
        if not isinstance(result, ToolMessage):
            return result
        return result.model_copy(update={"content": json.dumps({"ok": False, "error": {
            "code": "BAD_ENVELOPE", "retryable": False, "message": "Tool returned an invalid envelope"}}),
            "additional_kwargs": {}, "response_metadata": {}})
    cleaned = without_internal(envelope)
    if cleaned == envelope:
        return result
    return result.model_copy(update={"content": json.dumps(cleaned, ensure_ascii=False)})


def envelope_of(result: Any) -> dict[str, Any] | None:
    """The ``{ok, ...}`` envelope inside a tool message, or None if there is none."""
    if not isinstance(result, ToolMessage):
        return None
    return parse_envelope(result.content)


def parse_envelope(content: Any) -> dict[str, Any] | None:
    """The envelope in a tool's raw content: a JSON string, or text blocks."""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except ValueError:
        return None
    if not isinstance(parsed, dict) or type(parsed.get("ok")) is not bool:
        return None
    if parsed["ok"] and not isinstance(parsed.get("data"), dict):
        return None
    if not parsed["ok"] and not isinstance(parsed.get("error"), dict):
        return None
    return parsed


class ToolBox:
    """A role's tools, called by the harness directly rather than by a model.

    ``load_context`` looks the caller up, reads the ledger and re-checks
    prices through this (role ``harness``); the
    ``after_call`` task writes the ledger through it (role
    ``memory_writer``). Every call answers with the ``{ok, data | error}``
    envelope, whatever went wrong, so a caller never needs a try block.
    """

    def __init__(self, tools: Iterable[Any], *, timeout: float = 3.0) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._timeout = timeout

    def has(self, name: str) -> bool:
        return name in self._tools

    async def call(self, name: str, /, **args: Any) -> dict[str, Any]:
        from ..runtime import steps  # the turn's live steps (chat, staff console); late: runtime imports mcp

        if name not in self._tools:
            return await self._call(name, **args)
        async with steps.tool(name) as step:
            envelope = await self._call(name, **args)
            step["ok"] = bool(envelope.get("ok"))
            return envelope

    async def _call(self, name: str, /, **args: Any) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": {"code": "NO_TOOL", "retryable": False, "message": f"{name} is not available"}}
        try:
            raw = await asyncio.wait_for(tool.ainvoke({k: v for k, v in args.items() if v is not None}), timeout=self._timeout)
        except asyncio.TimeoutError:
            return {"ok": False, "error": {"code": "TIMEOUT", "retryable": True, "message": f"{name} took over {self._timeout:g}s"}}
        except Exception as error:  # noqa: BLE001 - reported as data, like the servers do
            logger.warning("Harness call %s failed: %s", name, type(error).__name__)
            return {"ok": False, "error": {"code": "TOOL_ERROR", "retryable": True, "message": type(error).__name__}}
        envelope = parse_envelope(raw)
        if envelope is None:
            return {"ok": False, "error": {"code": "BAD_ENVELOPE", "retryable": False, "message": "Tool returned an invalid envelope"}}
        return without_internal(envelope)

    async def data(self, name: str, /, **args: Any) -> Any:
        """The data of a successful call, or None."""
        envelope = await self.call(name, **args)
        return envelope.get("data") if envelope.get("ok") else None
