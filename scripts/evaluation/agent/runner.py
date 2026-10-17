"""The agent, assembled for an evaluation run. ``docs/design.md`` section 9.

The capstone's port of the reference project's ``pipeline/eval/runner.py``.
:mod:`.bridge` drives the agent through this module:

- :func:`build` assembles what the API runs (the seven-node graph with an
  in-memory checkpointer, ``AdvisorAgent``, ``PolicyAgent``, the MCP roles,
  ``MemoryAgent`` and ``QaAgent``), with the business tools answered by the
  harness instead of our MCP servers, and retries off;
- :func:`take_turn` sends one customer turn through the graph;
- :func:`record` and :func:`remember` run ``after_call`` once the call ends,
  as the API's ``runtime.harness.remember`` does;
- :func:`reset` empties the run's own schema, ``agent_eval``, before each
  scenario.

``full`` and ``baseline_no_memory`` differ in one switch, ``memory``, read by
``retrieve`` alone (section 9.5); ``after_call`` runs in both.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from ai_agent_service.agents import advisor as advisor_module
from ai_agent_service.agents.advisor import AdvisorAgent
from ai_agent_service.agents.memory import MemoryAgent
from ai_agent_service.agents.policy import PolicyAgent
from ai_agent_service.agents.qa import QaAgent
from ai_agent_service.components import clock
from ai_agent_service.components.intake import itn, pii
from ai_agent_service.components.intake import text as intake_text
from ai_agent_service.config.config_manager import get_models_config
from ai_agent_service.mcp import client as mcp_client
from ai_agent_service.mcp.server_base import database
from ai_agent_service.mcp.tools import ToolBox
from ai_agent_service.pipeline.cold.after_call import after_call
from ai_agent_service.pipeline.hot.graph import build_graph
from ai_agent_service.pipeline.hot.state import HotContext

logger = logging.getLogger(__name__)

#: The organisers' channel names (``scenario_format.md``, and ``web_chat`` from
#: ``handoff_brief.schema.json``), and the product's. Anything else is refused.
CHANNELS = {"hotline": "hotline", "zalo_oa": "zalo", "chat_fanpage": "facebook", "web_chat": "web"}

#: Keys are hashed with this during a run. The run's ledger starts empty, so
#: the secret only has to stay the same from one call to the next.
IDENTITY_SECRET = hashlib.sha256(b"identity:evaluation").hexdigest()

#: The organisers' business tools (``tools.schema.json``). The harness's own
#: mock answers these instead of the MCP servers.
BUSINESS_TOOLS = frozenset({
    "catalog.search", "inventory.check", "pricing.get_quote", "crm.get_customer", "order.create",
    "order.status", "order.update", "schedule.callback", "handoff.transfer",
})

#: Answers one business tool call: the organisers' name, the arguments, the ``{ok, ...}`` envelope.
Business = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

#: Emptied before every scenario and configuration, in a schema named ``*_eval`` only.
RESET_TABLES = ("mock_state", "facts", "episodes", "identities")


def connection(scenario: dict[str, Any], spec: dict[str, Any]) -> tuple[str, dict[str, str | None]]:
    """The product's channel and the keys the connection brings.

    A call that names no channel is a hotline call; its number is the call's
    ``channel_identity`` when given, else the scenario's ``customer_phone``.
    A channel the format does not name is an error, not a guess.
    """
    name = spec.get("channel") or "hotline"
    if name not in CHANNELS:
        raise ValueError(f"{scenario['scenario_id']}: unknown channel {name!r}; known: {sorted(CHANNELS)}")
    channel = CHANNELS[name]
    identity = spec.get("channel_identity")
    keys: dict[str, str | None] = {"caller_phone": None, "zalo_id": None, "fb_id": None}
    if channel == "hotline":
        keys["caller_phone"] = identity or scenario.get("customer_phone")
    elif channel == "zalo":
        keys["zalo_id"] = identity
    elif channel == "facebook":
        keys["fb_id"] = identity
    return channel, keys


# ── the agent ─────────────────────────────────────────────────────────────


@dataclass
class Rig:
    """What every turn is handed: the hot graph and its collaborators (section 3.2)."""

    graph: Any
    advisor: AdvisorAgent
    policy: PolicyAgent
    harness: ToolBox
    #: The ``memory_writer`` role, for ``after_call``.
    writer: ToolBox
    memory: MemoryAgent
    qa: QaAgent
    provider: str


def _advisor(tools: list[BaseTool], *, provider: str | None, model: str | None, retries: int) -> AdvisorAgent:
    """``AdvisorAgent`` as the API builds it, with *retries* in place of its one retry.

    The capstone's advisor has no ``retries`` argument: its middleware retries
    a failed model call and a retryable tool failure once. The harness must see
    every attempt (``retry: {agent: 0, tool: 0}``), so for this construction
    only the two middlewares are given ``retries`` instead.
    """
    if retries == 1:
        return AdvisorAgent(tools=tools, provider=provider, model=model)
    model_retry, tool_guard = advisor_module.ModelRetryMiddleware, advisor_module.ToolGuardMiddleware

    def no_model_retry(*args: Any, **kwargs: Any) -> Any:
        return model_retry(*args, **{**kwargs, "max_retries": retries})

    advisor_module.ModelRetryMiddleware = no_model_retry
    advisor_module.ToolGuardMiddleware = functools.partial(tool_guard, retries=retries)
    try:
        return AdvisorAgent(tools=tools, provider=provider, model=model)
    finally:
        advisor_module.ModelRetryMiddleware, advisor_module.ToolGuardMiddleware = model_retry, tool_guard


async def build(
    *, provider: str | None = None, model: str | None = None, business: Business | None = None, retries: int = 1,
) -> Rig:
    """Connect the MCP roles and build the graph, once per run.

    With *business*, the business tools of the advisor and of the harness are
    answered by it rather than by the MCP servers, under the same names and
    schemas, so the model and every middleware see no difference; memory and
    knowledge stay on MCP.
    """
    advisor_tools, harness_tools, writer_tools = await asyncio.gather(
        mcp_client.tools_for("advisor"), mcp_client.tools_for("harness"), mcp_client.tools_for("memory_writer")
    )
    if business is not None:
        advisor_tools, harness_tools = _routed(advisor_tools, business), _routed(harness_tools, business)
    advisor = _advisor(advisor_tools, provider=provider, model=model, retries=retries)
    return Rig(
        graph=build_graph(checkpointer=InMemorySaver()),
        advisor=advisor,
        policy=PolicyAgent(),
        harness=ToolBox(harness_tools),
        writer=ToolBox(writer_tools, timeout=10.0),
        memory=MemoryAgent(),
        qa=QaAgent(),
        provider=provider or get_models_config().agent("advisor").provider,
    )


def _routed(tools: list[BaseTool], business: Business) -> list[BaseTool]:
    """*tools* with each business tool replaced by one that asks *business*."""
    routed: list[BaseTool] = []
    for tool in tools:
        name = mcp_client.dotted(tool.name)
        if name not in BUSINESS_TOOLS:
            routed.append(tool)
            continue

        async def call(_name: str = name, **args: Any) -> str:
            envelope = await business(_name, {k: v for k, v in args.items() if v is not None})
            return json.dumps(envelope, ensure_ascii=False, default=str)

        routed.append(StructuredTool.from_function(
            coroutine=call, name=tool.name, description=tool.description, args_schema=tool.args_schema,
        ))
    return routed


# ── its database ──────────────────────────────────────────────────────────


async def reset() -> None:
    """Empty the mock's state and the ledger, in the evaluation schema only."""
    pool = await database()
    async with pool.connection() as conn:
        name = (await (await conn.execute("SELECT current_schema() AS name")).fetchone())["name"]
        if not name or not name.endswith("_eval"):
            raise RuntimeError(f"Refusing to empty schema {name!r}: the evaluation only resets a schema named *_eval")
        for table in RESET_TABLES:
            exists = (await (await conn.execute("SELECT to_regclass(%s) AS t", (f'"{name}".{table}',))).fetchone())["t"]
            if exists:
                await conn.execute(f'DELETE FROM "{name}".{table}')


# ── a call ────────────────────────────────────────────────────────────────


async def take_turn(
    rig: Rig, *, thread: str, channel: str, keys: dict[str, str | None], vault: pii.Vault, now: datetime,
    memory: bool, mode: str, text: str, turn_no: int, input_mode: str | None,
) -> tuple[dict[str, Any], str | None]:
    """One customer turn through the graph: the state, and the error if it failed."""
    context = HotContext(
        text=text, vault=vault, identity_secret=IDENTITY_SECRET,
        advisor=rig.advisor, policy=rig.policy, harness=rig.harness, **keys,
    )
    turn: dict[str, Any] = {
        "call_id": thread, "channel": channel, "now": now, "on": clock.on(now),
        "switches": {"memory": memory}, "mode": mode, "phase": "turn",
        "turn_id": f"t{turn_no}", "turn_no": turn_no,
        # Every turn, None included: the checkpoint would otherwise carry the
        # previous turn's mode forward and ``perceive`` would not decide afresh.
        "input_mode": input_mode,
    }
    try:
        return await rig.graph.ainvoke(turn, config={"configurable": {"thread_id": thread}}, context=context), None
    except Exception as failure:  # noqa: BLE001 - the caller decides what a failed turn means
        logger.exception("Turn %s of %s failed", turn_no, thread)
        return {}, f"{type(failure).__name__}: {failure}"[:300]


def record(state: dict[str, Any], turn_no: int, text: str, now: datetime, vault: pii.Vault,
           transcript: list[dict[str, Any]], tool_log: list[dict[str, Any]]) -> None:
    """What ``after_call`` reads of one turn, as the API stores it: the
    customer's words as ``perceive`` left them (cleaned, ITN, tokenised)."""
    said = next((m.content for m in reversed(state.get("messages") or []) if isinstance(m, HumanMessage)), None)
    if said is None:
        # The graph failed before perceive wrote the turn: the API's fallback.
        said = pii.tokenise(itn.normalise(intake_text.clean(text)[0], now), vault)
    transcript.append({"speaker": "customer", "text": str(said), "turn": turn_no})
    reply = (state.get("reply") or {}).get("text")
    if reply:
        transcript.append({"speaker": "agent", "text": reply, "turn": turn_no})
    for result in state.get("tool_results") or []:
        args = json.loads(pii.tokenise(json.dumps(result.get("args") or {}, ensure_ascii=False), vault))
        tool_log.append({"name": result.get("name"), "args": args, "result": result.get("result"),
                         "turn": result.get("turn") or turn_no, "blocked_by": result.get("blocked_by")})


async def remember(rig: Rig, *, thread: str, channel: str, now: datetime, state: dict[str, Any],
                   transcript: list[dict[str, Any]], tool_log: list[dict[str, Any]]) -> dict[str, Any]:
    """``after_call`` for the call that just ended, as the API's ``remember`` runs it."""
    if not state:
        return {"status": "skipped", "reason": "no turn of the call completed", "memory_writes": []}
    call = {
        "call_id": thread,
        "channel": channel,
        "on": clock.on(now),
        "tier": state.get("tier"),
        "customer_id": state.get("customer_id"),
        "keys_seen": state.get("keys_seen") or [],
        "returning": bool((state.get("brief") or {}).get("is_returning")),
    }
    try:
        return await after_call(call, transcript, tool_log, writer=rig.writer, memory=rig.memory, qa=rig.qa)
    except Exception as failure:  # noqa: BLE001 - the barrier reports it; the next call runs without this memory
        logger.exception("after_call failed on %s", thread)
        return {"status": "failed", "error": f"{type(failure).__name__}: {failure}"[:300], "memory_writes": []}
