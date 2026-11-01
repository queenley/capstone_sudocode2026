"""The agent, assembled for an evaluation run, and one call through it. ``docs/design.md`` section 9.2.

The organisers' command (:mod:`.cli`) runs calls through this module: the
business tools are our MCP servers and :func:`run_scenario` writes one trace
line per agent turn (Appendix A).

A call is a :class:`CallSession`:

1. **connect.** The caller is identified when the call connects, from the
   caller id or the chat's identity, by the hot graph's own ``load_context``.
   The Call Brief, ``refresh`` included, is ready before the first word, and
   its latency runs from that identification to the brief
   (``eval/huong-dan-do-latency.md``, rule 5).
2. **turns.** Each customer turn through the compiled hot graph, the customer
   speaking first. After a ``handoff.transfer`` the call is the consultant's
   (copilot mode): the agent says nothing more, though the turns keep coming,
   as the harness sends them.
3. **hang up.** ``after_call`` (``MemoryAgent``, ``QaAgent``), synchronously,
   so the next call reads what this one left.

``full`` and ``baseline_no_memory`` differ in one switch, ``memory``, read by
``retrieve`` alone (section 9.5): ``after_call`` and ``seed_history`` are
written in both, and only the baseline's next call does not read them. A run
has its own database, ``*_eval``, emptied before every scenario
(:func:`reset`), and an in-memory checkpointer, so no evaluation call lands
among the API's.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from ...agents.advisor import AdvisorAgent
from ...agents.base import model_for
from ...agents.memory import MemoryAgent
from ...agents.policy import PolicyAgent
from ...agents.qa import QaAgent
from ...components import clock
from ...components.identity import resolver
from ...components.intake import itn, pii
from ...components.intake import text as intake_text
from ...components.memory import ontology
from ...config.config_manager import get_models_config
from ...llm import token_ledger
from ...mcp import client as mcp_client
from ...mcp.server_base import database
from ...mcp.servers import btc
from ...mcp.tools import ToolBox
from ..cold.after_call import after_call
from ..hot import nodes
from ..hot.graph import build_graph
from ..hot.state import HotContext
from . import scenarios, trace
from .scenarios import CallPlan, Scenario, SeedSession

logger = logging.getLogger(__name__)

CONFIGS = ("full", "baseline_no_memory")

#: Keys are hashed with this during a run. The run's ledger starts empty, so
#: the secret only has to stay the same from one call to the next.
IDENTITY_SECRET = hashlib.sha256(b"identity:evaluation").hexdigest()

#: The organisers' business tools (``tools.schema.json``). In the harness's
#: runs its own mock answers these instead of our MCP servers.
BUSINESS_TOOLS = frozenset({
    "catalog.search", "inventory.check", "pricing.get_quote", "crm.get_customer", "order.create",
    "order.status", "order.update", "schedule.callback", "handoff.transfer",
})

#: Answers one business tool call: the organisers' name, the arguments, the ``{ok, ...}`` envelope.
Business = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

#: Emptied before every scenario and configuration, where they exist. Only
#: ever in a database whose name ends in ``_eval``: :func:`reset` refuses any other.
RESET_TABLES = ("mock_state", "facts", "episodes", "identities", "deletion_requests")

Progress = Callable[[str], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── the agent ─────────────────────────────────────────────────────────────


@dataclass
class Rig:
    """What every turn is handed: the hot graph and its collaborators (section 3.2)."""

    graph: Any
    advisor: AdvisorAgent
    policy: PolicyAgent
    harness: ToolBox
    #: The ``memory_writer`` role, for ``after_call`` and for seeding prior sessions.
    writer: ToolBox
    memory: MemoryAgent
    qa: QaAgent
    provider: str
    #: Opens the ``admin`` role, only when a call must carry out a deletion.
    admin: Callable[[], Awaitable[ToolBox]] | None = None
    #: Folds a long call into ``working_summary``; None folds extractively.
    compactor: Any = None


async def build(
    *, provider: str | None = None, model: str | None = None, business: Business | None = None, retries: int = 1,
) -> Rig:
    """Connect the MCP roles and build the graph, once per run.

    With *business*, the business tools of the advisor and of the harness are
    answered by it rather than by the MCP servers, under the same names and
    schemas, so the model and every middleware see no difference; memory,
    knowledge and our own tools stay on MCP. *retries* goes to the advisor:
    the product's one retry of a failed model call, 0 when the caller must
    see every attempt.
    """
    advisor_tools, harness_tools, writer_tools = await asyncio.gather(
        mcp_client.tools_for("advisor"), mcp_client.tools_for("harness"), mcp_client.tools_for("memory_writer")
    )
    if business is not None:
        advisor_tools, harness_tools = _routed(advisor_tools, business), _routed(harness_tools, business)
    return Rig(
        graph=build_graph(checkpointer=InMemorySaver()),
        advisor=AdvisorAgent(tools=advisor_tools, provider=provider, model=model, retries=retries),
        policy=PolicyAgent(),
        harness=ToolBox(harness_tools),
        writer=ToolBox(writer_tools, timeout=10.0),
        memory=MemoryAgent(),
        qa=QaAgent(),
        provider=provider or get_models_config().agent("advisor").provider,
        admin=mcp_client.lazy_toolbox("admin", timeout=10.0),
        compactor=model_for("compactor"),
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


def use_evaluation_database() -> str:
    """Point this process, and the MCP servers it starts later, at the
    evaluation's database: ``EVAL_DATABASE_URL``, else the app's with ``_eval``
    appended to its name, created on first use. Returns the name; never the
    URL, which holds a password. Raises ``RuntimeError`` with what to do."""
    import os

    import psycopg
    from psycopg import sql

    from ...config.database import configured_url

    target = os.environ.get("EVAL_DATABASE_URL")
    if not target:
        url, _ = configured_url()
        if not url or "://" not in url:
            raise RuntimeError("Set DATABASE_URL (a postgresql:// URL) or EVAL_DATABASE_URL in .env")
        parts = urlsplit(url)
        target = urlunsplit(parts._replace(path=f"/{parts.path.lstrip('/')}_eval"))
    parts = urlsplit(target)
    name = parts.path.lstrip("/")
    if not name.endswith("_eval"):
        raise RuntimeError("EVAL_DATABASE_URL must name a database ending in _eval: the run empties its tables.")
    try:
        with psycopg.connect(urlunsplit(parts._replace(path="/postgres")), autocommit=True, connect_timeout=5) as conn:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is None:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.OperationalError as error:
        raise RuntimeError(f"Postgres is not reachable ({type(error).__name__}). Start it: docker compose up -d postgres") from error
    except psycopg.errors.InsufficientPrivilege as error:
        raise RuntimeError(f"This database user may not create {name!r}. Create it once by hand, "
                           "or set EVAL_DATABASE_URL to a database named *_eval that exists.") from error
    except psycopg.Error as error:
        raise RuntimeError(f"Could not prepare {name!r}: {type(error).__name__}") from error
    # The agent reads AGENT_DATABASE_URL first (config.database): both point here.
    os.environ["DATABASE_URL"] = os.environ["AGENT_DATABASE_URL"] = target
    return name


async def reset() -> None:
    """Empty the mock's state and the ledger, in the evaluation database only."""
    pool = await database()
    async with pool.connection() as conn:
        name = (await (await conn.execute("SELECT current_database() AS name")).fetchone())["name"]
        if not name.endswith("_eval"):
            raise RuntimeError(f"Refusing to empty {name!r}: the evaluation only resets a database named *_eval")
        for table in RESET_TABLES:
            exists = (await (await conn.execute("SELECT to_regclass(%s) AS t", (table,))).fetchone())["t"]
            if exists:
                await conn.execute(f"DELETE FROM {table}")


# ── prior sessions ────────────────────────────────────────────────────────


async def seed(rig: Rig, sessions: tuple[SeedSession, ...], *, customer_phone: str | None,
               customer_name: str | None) -> str:
    """Write a scenario's prior sessions to its customer's ledger, before the call (section 9.2, step 2).

    The customer is who the organisers' CRM says owns *customer_phone*; on a
    number two people share, the one the scenario names. A customer the CRM
    does not know is created on the ledger, keyed by that number, as
    ``after_call`` would have done. Each session becomes an episode, and its
    facts are written through the ``memory_writer`` role in date order, a
    later value superseding an earlier one, so the ledger holds what it would
    hold had those calls run here. Returns the customer id. Raises
    :class:`~.scenarios.ScenarioError` when the seed cannot be placed.
    """
    customer_id = await _seed_owner(rig, customer_phone, customer_name)
    held: dict[str, tuple[str, Any]] = {}
    for session in sessions:
        source = {"call_id": f"seed:{session.session_id}", "call": "seed", "turn": 0, "channel": session.channel,
                  "said_by": "system", "extractor_version": "seed"}
        decisions = []
        for slot, value in session.facts.items():
            spec = ontology.slot(slot)
            if spec is None:
                logger.warning("Seed %s: slot %r is not in the ontology; not written", session.session_id, slot)
                continue
            if slot in held and held[slot][1] == value:
                continue
            valid_to = (date.fromisoformat(session.day) + timedelta(days=spec.ttl_days)).isoformat() if spec.ttl_days else None
            decisions.append({"operation": "update" if slot in held else "add", "slot": slot, "value": value,
                              "kind": spec.kind, "source": source, "replaces": held[slot][0] if slot in held else None,
                              "disputed": False, "valid_to": valid_to, "confidence": 1.0})
        if decisions:
            written = await rig.writer.data("memory_commit_facts", customer_id=customer_id, decisions=decisions, on=session.day)
            if written is None:
                raise scenarios.ScenarioError(f"seed {session.session_id}: the ledger refused its facts")
            for write in written.get("memory_writes") or []:
                held[write["key"]] = (write.get("fact_id"), write.get("value"))
        episode = await rig.writer.data("memory_commit_episode", customer_id=customer_id, episode={
            "call_id": f"seed:{session.session_id}", "channel": session.channel, "date": session.day,
            "summary": session.summary or f"Phiên ngày {clock.day_label(session.day)} qua {session.channel}.",
            "outcome": session.outcome, "commitments": [], "source_turn_span": [],
        })
        if episode is None:
            raise scenarios.ScenarioError(f"seed {session.session_id}: the ledger refused its episode")
    return customer_id


async def _seed_owner(rig: Rig, phone: str | None, name: str | None) -> str:
    """The customer a seed belongs to: the CRM's, else one the ledger keeps for that number."""
    if not phone:
        raise scenarios.ScenarioError("seed_history needs the scenario's customer_phone")
    known = btc.mock().crm_get_customer(phone=phone)
    if known.get("found") and not known.get("ambiguous"):
        return str(known["customer_id"])
    if known.get("ambiguous"):
        named = [c for c in known.get("candidates") or [] if name and c.get("name") == name]
        if len(named) != 1:
            raise scenarios.ScenarioError(f"seed_history: {len(known['candidates'])} customers share the number "
                                          "and the scenario's customer_name picks none of them")
        return str(named[0]["customer_id"])
    key = {"key_type": "phone", "key_hash": resolver.digest("phone", phone, IDENTITY_SECRET)}
    found = await rig.writer.data("identity_find", **key)
    matches = (found or {}).get("matches") or []
    if matches:
        return str(matches[0]["customer_id"])
    confirmed = await rig.writer.data("memory_confirm_identity", keys=[key])
    if not confirmed:
        raise scenarios.ScenarioError("seed_history: the ledger could not create the customer")
    return str(confirmed["customer_id"])


# ── a call ────────────────────────────────────────────────────────────────


@dataclass
class Connected:
    """The call connected: what ``load_context`` found, and when."""

    update: dict[str, Any]
    identified_at: str
    ready_at: str
    #: Identification to brief, in ms; None when nobody was identified, so no brief exists.
    brief_ms: int | None


@dataclass
class TurnResult:
    """One customer turn and what the agent did with it."""

    state: dict[str, Any]
    total_ms: int
    #: The first token of the answer from the turn's start: the first sentence said (section 4.8).
    first_token_ms: int | None
    error: str | None
    request_at: str
    completed_at: str
    #: Tokens by agent in this turn: ``{agent: {calls, input, output}}``.
    usage: dict[str, dict[str, int]]


@dataclass
class CallSession:
    """One call through the hot graph, from connecting to hanging up."""

    rig: Rig
    thread: str
    channel: str
    keys: Mapping[str, str | None]
    day: str
    memory: bool
    input_mode: str | None
    vault: pii.Vault = field(default_factory=pii.Vault)
    mode: str = "speak"
    turn_no: int = 0
    transcript: list[dict[str, Any]] = field(default_factory=list)
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    #: The state after the last step that completed.
    last: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def for_plan(cls, rig: Rig, plan: CallPlan, *, thread: str, memory: bool) -> "CallSession":
        return cls(rig, thread, plan.channel, dict(plan.keys), plan.on, memory, plan.input_mode)

    @property
    def now(self) -> datetime:
        return clock.at(self.day)

    @property
    def customer_id(self) -> str | None:
        return self.last.get("customer_id")

    def _context(self, text: str | None = None) -> HotContext:
        return HotContext(
            text=text, vault=self.vault, identity_secret=IDENTITY_SECRET, advisor=self.rig.advisor,
            policy=self.rig.policy, harness=self.rig.harness, compactor=self.rig.compactor, **self.keys,
        )

    def _config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.thread}}

    async def connect(self) -> Connected:
        """Identify the caller and build the Call Brief, as the call connects."""
        now = self.now
        state = {"call_id": self.thread, "channel": self.channel, "now": now, "on": clock.on(now),
                 "switches": {"memory": self.memory}, "mode": "speak", "phase": "opening", "turn_id": "t0",
                 "turn_no": 0, "flags": {}}
        identified_at = utc_now()
        started = time.perf_counter()
        update = await nodes.load_context(state, SimpleNamespace(context=self._context()))
        elapsed = int((time.perf_counter() - started) * 1000)
        ready_at = utc_now()
        await self.rig.graph.aupdate_state(self._config(), {**state, **update}, as_node="load_context")
        self.last = {**state, **update}
        return Connected(update, identified_at, ready_at, elapsed if update.get("brief") is not None else None)

    async def turn(self, text: str) -> TurnResult:
        """One customer turn through the graph."""
        self.turn_no += 1
        before = token_ledger.snapshot()
        request_at = utc_now()
        started = time.perf_counter()
        state, error = await take_turn(
            self.rig, thread=self.thread, channel=self.channel, keys=self.keys, vault=self.vault, now=self.now,
            memory=self.memory, mode=self.mode, text=text, turn_no=self.turn_no, input_mode=self.input_mode,
            arrived=started,
        )
        total_ms = int((time.perf_counter() - started) * 1000)
        completed_at = utc_now()
        if state:
            self.mode = state.get("mode") or self.mode
            self.last = state
        record(state, self.turn_no, text, self.now, self.vault, self.transcript, self.tool_log)
        first = (state.get("latency") or {}).get("first_token_ms")
        return TurnResult(state, total_ms, int(first) if first is not None else None, error, request_at,
                          completed_at, usage_between(before, token_ledger.snapshot()))

    async def hang_up(self) -> dict[str, Any]:
        """``after_call`` for this call; what it wrote and how it ended."""
        return await remember(self.rig, thread=self.thread, channel=self.channel, now=self.now, state=self.last,
                              transcript=self.transcript, tool_log=self.tool_log)


async def take_turn(
    rig: Rig, *, thread: str, channel: str, keys: Mapping[str, str | None], vault: pii.Vault, now: datetime,
    memory: bool, mode: str, text: str, turn_no: int, input_mode: str | None, arrived: float | None = None,
) -> tuple[dict[str, Any], str | None]:
    """One customer turn through the graph: the state, and the error if it failed.

    *arrived* is when the turn was handed in (``time.perf_counter``), where
    the first token's latency starts, as at the API's boundary (section 4.8).
    """
    context = HotContext(
        text=text, vault=vault, identity_secret=IDENTITY_SECRET, arrived=arrived,
        advisor=rig.advisor, policy=rig.policy, harness=rig.harness, compactor=rig.compactor, **keys,
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


def record(state: Mapping[str, Any], turn_no: int, text: str, now: datetime, vault: pii.Vault,
           transcript: list[dict[str, Any]], tool_log: list[dict[str, Any]]) -> None:
    """What ``after_call`` reads of one turn, as the API stores it: the
    customer's words as ``perceive`` left them (cleaned, ITN, tokenised)."""
    said = next((m.content for m in reversed(state.get("messages") or []) if isinstance(m, HumanMessage)), None)
    if said is None:
        # The graph failed before perceive wrote the turn: the API's fallback, harness._store_customer_fallback.
        said = pii.tokenise(itn.normalise(intake_text.clean(text)[0], now), vault)
    transcript.append({"speaker": "customer", "text": str(said), "turn": turn_no})
    reply = (state.get("reply") or {}).get("text")
    if reply:
        transcript.append({"speaker": "agent", "text": reply, "turn": turn_no})
    for result in state.get("tool_results") or []:
        args = pii.tokenise_data(result.get("args") or {}, vault)
        tool_log.append({"name": result.get("name"), "args": args, "result": result.get("result"),
                         "turn": result.get("turn") or turn_no, "blocked_by": result.get("blocked_by")})


async def remember(rig: Rig, *, thread: str, channel: str, now: datetime, state: Mapping[str, Any],
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
        "provisional": state.get("provisional"),
        "returning": bool((state.get("brief") or {}).get("is_returning")),
    }
    try:
        return await after_call(call, transcript, tool_log, writer=rig.writer, memory=rig.memory, qa=rig.qa,
                                admin=rig.admin)
    except Exception as failure:  # noqa: BLE001 - the barrier reports it; the next call runs without this memory
        logger.exception("after_call failed on %s", thread)
        return {"status": "failed", "error": f"{type(failure).__name__}: {failure}"[:300], "memory_writes": []}


def usage_between(before: Mapping[str, Mapping[str, int]], after: Mapping[str, Mapping[str, int]]) -> dict[str, dict[str, int]]:
    """Tokens spent between two ledger snapshots, by agent; agents that spent nothing are left out."""
    spent = {}
    for agent, now in after.items():
        then = before.get(agent) or {}
        delta = {key: int(now.get(key, 0)) - int(then.get(key, 0)) for key in ("calls", "input", "output")}
        if any(delta.values()):
            spent[agent] = delta
    return spent


# ── the organisers' command ───────────────────────────────────────────────


@dataclass
class ScenarioRun:
    """One scenario in one configuration: its trace lines and what a reader needs beside them."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    #: One entry per turn (lane, tier, guard, errors), and per call its ``after_call``.
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    #: Tokens per call: the turns and ``after_call`` apart.
    usage: list[dict[str, Any]] = field(default_factory=list)
    #: Why the scenario stopped before its end, if it did.
    error: str | None = None


async def run_scenario(rig: Rig, scenario: Scenario, config: str, *, run_id: str, progress: Progress) -> ScenarioRun:
    """Every call of *scenario* in order, each from what the previous one left; one trace line per turn."""
    run = ScenarioRun()
    await reset()
    phone, name = scenario.data.get("customer_phone"), scenario.data.get("customer_name")
    for plan in scenario.calls:
        if plan.seed:
            try:
                await seed(rig, plan.seed, customer_phone=phone, customer_name=name)
            except scenarios.ScenarioError as error:
                run.error = f"{plan.name}: {error}"
                progress(f"  {config:<18} {scenario.scenario_id} {plan.name} seed refused: {error}")
                return run
        await _run_call(rig, scenario, plan, config, run=run, run_id=run_id, progress=progress)
        if run.error:
            return run
    return run


async def _run_call(rig: Rig, scenario: Scenario, plan: CallPlan, config: str, *, run: ScenarioRun, run_id: str,
                    progress: Progress) -> None:
    session = CallSession.for_plan(rig, plan, thread=f"{run_id}|{config}|{scenario.scenario_id}|{plan.name}",
                                   memory=config == "full")
    connected = await session.connect()
    spent: dict[str, dict[str, int]] = {}
    for text in plan.turns:
        result = await session.turn(text)
        _add(spent, result.usage)
        state = result.state
        row = trace.turn_row(
            run_id=run_id, config=config, scenario_id=scenario.scenario_id, call=plan.name, turn=session.turn_no,
            customer_text=text, state=state, vault=session.vault, total_ms=result.total_ms,
            first_token_ms=result.first_token_ms, input_mode=plan.trace_input_mode,
            call_brief_latency_ms=connected.brief_ms,
        )
        run.rows.append(row)
        diagnosis = diagnose(state, result.error, config=config, scenario_id=scenario.scenario_id, call=plan.name,
                             turn=session.turn_no)
        run.diagnostics.append(diagnosis)
        tools = ",".join(t["name"] for t in row["tool_calls"]) or "-"
        progress(f"  {config:<18} {scenario.scenario_id} {plan.name} t{session.turn_no}  {result.total_ms:>6} ms  "
                 f"{diagnosis['tier'] or '-'}/{diagnosis['lane'] or '-'}  tools={tools}"
                 + (f"  ERROR {diagnosis['error']}" if diagnosis["error"] else ""))
        if diagnosis["error"]:
            run.error = f"{plan.name} t{session.turn_no}: {diagnosis['error']}"
            run.usage.append({"config": config, "scenario_id": scenario.scenario_id, "call": plan.name,
                              "turns": spent, "after_call": {}})
            return
    before = token_ledger.snapshot()
    remembered = await session.hang_up()
    after_call_usage = usage_between(before, token_ledger.snapshot())
    if run.rows and run.rows[-1]["call"] == plan.name:
        run.rows[-1]["memory_writes"] = trace.memory_writes(remembered.get("memory_writes") or [])
        run.diagnostics[-1]["after_call"] = {k: remembered.get(k) for k in ("status", "reason", "customer_id", "episode", "error", "deleted")
                                             if remembered.get(k)}
    run.usage.append({"config": config, "scenario_id": scenario.scenario_id, "call": plan.name,
                      "turns": spent, "after_call": after_call_usage})
    progress(f"  {config:<18} {scenario.scenario_id} {plan.name} after_call {remembered.get('status')}: "
             f"{len(remembered.get('memory_writes') or [])} facts"
             + (f" ({remembered['reason']})" if remembered.get("reason") else ""))
    if remembered.get("status") == "failed":
        run.error = f"{plan.name} after_call: {remembered.get('error') or remembered.get('reason')}"


def diagnose(state: Mapping[str, Any], error: str | None, *, config: str, scenario_id: str, call: str,
             turn: int) -> dict[str, Any]:
    """What a reader of the run needs about one turn, beside its trace line."""
    guard = state.get("guard") or {}
    draft = state.get("draft") or {}
    found = state.get("knowledge") or {}
    return {
        "config": config, "scenario_id": scenario_id, "call": call, "turn": turn,
        "lane": state.get("lane"), "route_rule": state.get("route_rule"), "route_reason": state.get("route_reason"),
        "tier": state.get("tier"), "mode": state.get("mode"),
        "knowledge": {"chunks": [h.get("chunk_id") for h in found.get("hits") or []], "top_score": found.get("top_score"),
                      "abstain": found.get("reason") if found.get("abstain") else None,
                      "order_date": found.get("order_date")} if found else None,
        "streamed": bool(draft.get("streamed")),
        "guard_passed": guard.get("passed"),
        "policy": (guard.get("soft") or {}).get("decided_by"),
        "regenerations": state.get("regen_count") or 0,
        "blocked_drafts": [d.get("reasons") for d in state.get("blocked_drafts") or []],
        "fallback": bool(draft.get("fallback")),
        "blocked_tool_calls": [{"name": r["name"], "args": r.get("args") or {}, "result": r.get("result")}
                               for r in state.get("tool_results") or [] if r.get("blocked_by")],
        "error": error or draft.get("error"),
    }


def _add(total: dict[str, dict[str, int]], more: Mapping[str, Mapping[str, int]]) -> None:
    for agent, counts in more.items():
        bucket = total.setdefault(agent, {"calls": 0, "input": 0, "output": 0})
        for key, value in counts.items():
            bucket[key] = bucket.get(key, 0) + int(value)


async def warm_up(rig: Rig, scenario: Scenario, turns: int, progress: Progress) -> None:
    """Turns taken before the first measured one, never traced (``huong-dan-do-latency.md``, rule 2).

    On the first call of the first scenario, memory off, then the state they
    left is emptied.
    """
    if turns <= 0:
        return
    plan = scenario.calls[0]
    texts = list(plan.turns) or ["Chào shop"]
    await reset()
    session = CallSession.for_plan(rig, plan, thread="warm-up", memory=False)
    await session.connect()
    for index in range(turns):
        result = await session.turn(texts[index % len(texts)])
        progress(f"  warm-up t{index + 1}  {result.total_ms:>6} ms" + (f"  ERROR {result.error}" if result.error else ""))
        if result.error or (result.state.get("draft") or {}).get("error"):
            raise RuntimeError("Evaluation stopped after a failed warm-up invocation")
    await reset()
