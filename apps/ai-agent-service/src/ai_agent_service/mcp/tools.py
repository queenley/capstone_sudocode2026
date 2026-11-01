"""Binding MCP tools to an agent: by lane, with a guard around every call.

Two middleware, both straight from ``docs/design.md``, and both deliberately
*not* a tool class of our own — the framework's ``@tool`` and the MCP adapter
already produce the tools; what is ours is the policy around them.

- :class:`LaneToolsMiddleware`, section 4.3. The lane ``route`` chose decides
  which tools the model is offered on each call. The table is
  ``config/lanes.yaml``, a declaration rather than code, because the brief
  asks the team to present "when a tool is called and when it is not".
- :class:`ToolGuardMiddleware`, sections 4.4, 4.9 and 6.1. A timeout on every
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
with the first result and answers again on a repeat (section 6.1; Stripe
does the same for every request that creates or changes something). Its
declared defaults (``qty``, ``payment``) are written into the arguments, so
the trace records the order that was actually placed, not only what the
model typed (section 9.3).

Both are shared by every request that runs through one compiled agent, so
the only mutable state is the breaker's, and it is meant to be shared: a
server that is down is down for everyone.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any, Iterable, Mapping

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from ..components.intake import pii
from ..components.guardrails import purchase
from ..components.intake.text import plain

logger = logging.getLogger(__name__)

#: Error codes that mean the tool could not be reached or ran no business
#: logic. Only these count against the circuit breaker.
INFRASTRUCTURE_CODES = frozenset({"TIMEOUT", "TOOL_ERROR", "INTERNAL", "CIRCUIT_OPEN"})

#: The logged-in shopper's website account (``mcp/servers/account.py``): offered only with an account.
ACCOUNT_PREFIX = "account_"

#: Tools with an effect on the business, by wire name (section 6.1): never
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


class LaneToolsMiddleware(AgentMiddleware):
    """Offers the model only the tools the run's lane allows."""

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
        tools = [
            tool
            for tool in request.tools
            if (name := _tool_name(tool)) not in self._mcp or name in allowed
        ]
        return request.override(tools=tools)

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._filtered(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._filtered(request))


class ToolGuardMiddleware(AgentMiddleware):
    """Timeout, one retry, a circuit breaker, and the virtual clock."""

    #: Section 6.1: seconds per call, by tool; everything else gets DEFAULT_TIMEOUT.
    TIMEOUTS = {"kb_search": 3.0, "kb_upsert": 3.0}
    DEFAULT_TIMEOUT = 2.0

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
        call = request.tool_call
        name = call["name"]
        if name not in self._guarded:
            return await handler(request)
        if self._is_open(name):
            return self._envelope_message(
                call, "CIRCUIT_OPEN", f"{name} is paused after repeated failures", retryable=False
            )
        request = self._with_context(request)

        limit = self._timeout or self.TIMEOUTS.get(name, self.DEFAULT_TIMEOUT)
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
            # docs/design.md section 4.9: repeated failure is what moves
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
                    getattr(context, "pending_purchase", None), business_args, context)
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


ADDRESS_TOKEN = re.compile(r"<ADDR_\d+>")


def with_addresses(value: Any, addresses: Mapping[str, str]) -> Any:
    """An ``address`` argument with the call's real addresses: tokens replaced, the latest one when it is empty.

    The model only ever sees ``<ADDR_1>``; the regional promotions and the
    delivery time are decided by the real address (KM-08, section 4.4).
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
        return purchase.order_key(str(call_id), args)
    payload = json.dumps({k: v for k, v in args.items() if k != IDEMPOTENCY_ARG},
                         ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    # shortcut: identical orders in one call are one purchase; add intent IDs for separate identical purchases.
    scope = call_id if name == "order_create" else f"{call_id}:{turn_id}"
    return f"{scope}:{name}:{digest}"


def with_args(result: Any, args: Mapping[str, Any]) -> Any:
    """The tool message, carrying the arguments the tool actually ran with.

    The model wrote some of them; the harness filled in the day and the
    phone. The trace records what ran (section 9.3), so it is kept here.
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
    go; it is for the harness, never for the model (section 4.4).
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
    prices through this (sections 4.2 and 6.2, role ``harness``); the
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
