"""The exploration: from one failure to a hint the grader says fixes it. ``docs/design.md`` section 10.3.

A search over what the advisor reads, in the manner of Language Agent Tree
Search (Zhou et al., ICML 2024), cut to what the budget allows and adapted
to what the loop must produce. LATS searches over an agent's actions; here
the unit the organisers grade is a call (``success_if``), and what the loop
may change is a playbook entry, so a node is **the failed call played again
under one hint**:

- **expand**: the QaAgent proposes up to ``width`` hints for the failure;
- **evaluate**: each hint's branch is played to its end against the
  exploration's customer (``agents.simulator``) and scored by the
  organisers' own grader. The value is not a model's opinion: LATS is
  sensitive to its reward, and an evaluator sharing the improved agent's
  model drifts (Pan et al., 2024), so the reward is ``check_call`` and the
  failure codes of ``components.improvement.signals``;
- **reflect and select**: what each branch did goes back to the QaAgent,
  which proposes the next hints from it, ``depth`` times at most; the best
  branch so far is kept, and the search stops when one fixes the failure
  and breaks nothing.

Before any hint, a **control** branch plays the call with none. A failure
the control does not reproduce is not explored: a hint cannot be credited
with fixing what was not broken in this customer's hands.

**Isolation.** Branches run one after another, never side by side, and each
starts from the same state: the tables a call reads and writes (the ledger,
the organisers' mock state) are copied when the call is about to start
(:class:`Snapshot`) and restored before every branch. Each branch has its
own checkpoint thread, its own PII vault and a new customer with the same
seed; its hint reaches the advisor as one more passage of ``kb.search``
(:class:`HintedHarness`), the way a published entry would. The advisor
never sees the grader, the failure or another branch. Only the QaAgent reads
what the tried branches did, which is the reflection step itself.

It runs in a database of its own, the app's name plus ``_explore``
(:func:`use_explore_database`), never the evaluation's.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from ...agents.qa import QaAgent
from ...agents.simulator import MAX_TURNS, SimulatorAgent
from ...components.improvement import signals
from ...components.improvement.lessons import Card, Hint, screen
from ...components.improvement.playbook import entry_id, render
from ...components.improvement.signals import Failure
from ...llm import token_ledger
from ...mcp.server_base import database
from ..eval import runner, trace
from ..eval.runner import CallSession, Rig
from ..eval.scenarios import Scenario

logger = logging.getLogger(__name__)

SUFFIX = "_explore"
#: The tables restored before every branch: what a call reads and writes (the evaluation's own list).
TABLES = runner.RESET_TABLES
SNAPSHOT_PREFIX = "explore_snapshot_"

Progress = Callable[[str], None]

#: A provider refusing for quota or rate: what no later call of the run will get past.
EXHAUSTED = re.compile(r"429|rate limit|ratelimit|quota|resource_exhausted", re.IGNORECASE)


class ProviderExhausted(RuntimeError):
    """The model provider stopped answering (a quota spent for the day): stop the run, keep nothing half made."""


def fresh(label: str) -> str:
    """A checkpoint thread no other branch, prefix or earlier search in this process has used."""
    return f"{label}|{uuid.uuid4().hex[:8]}"


# ── its database ──────────────────────────────────────────────────────────


def use_explore_database() -> str:
    """Point this process, and the MCP servers it starts later, at the exploration's database:
    ``EXPLORE_DATABASE_URL``, else the app's with ``_explore`` appended, created on first use.
    Returns the name, never the URL. Raises ``RuntimeError`` with what to do."""
    import psycopg
    from psycopg import sql

    from ...config.database import configured_url

    target = os.environ.get("EXPLORE_DATABASE_URL")
    if not target:
        url, _ = configured_url()
        if not url or "://" not in url:
            raise RuntimeError("Set DATABASE_URL (a postgresql:// URL) or EXPLORE_DATABASE_URL in .env")
        parts = urlsplit(url)
        target = urlunsplit(parts._replace(path=f"/{parts.path.lstrip('/')}{SUFFIX}"))
    parts = urlsplit(target)
    name = parts.path.lstrip("/")
    if not name.endswith(SUFFIX):
        raise RuntimeError(f"EXPLORE_DATABASE_URL must name a database ending in {SUFFIX}: branches empty its tables.")
    try:
        with psycopg.connect(urlunsplit(parts._replace(path="/postgres")), autocommit=True, connect_timeout=5) as conn:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is None:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.OperationalError as error:
        raise RuntimeError(f"Postgres is not reachable ({type(error).__name__}). Start it: docker compose up -d postgres") from error
    except psycopg.Error as error:
        raise RuntimeError(f"Could not prepare {name!r}: {type(error).__name__}") from error
    os.environ["DATABASE_URL"] = os.environ["AGENT_DATABASE_URL"] = target
    return name


async def _guarded(conn: Any) -> None:
    name = (await (await conn.execute("SELECT current_database() AS name")).fetchone())["name"]
    if not name.endswith(SUFFIX):
        raise RuntimeError(f"Refusing to touch {name!r}: the exploration only writes a database named *{SUFFIX}")


async def _tables(conn: Any) -> list[str]:
    present = []
    for table in TABLES:
        if (await (await conn.execute("SELECT to_regclass(%s) AS t", (table,))).fetchone())["t"]:
            present.append(table)
    return present


async def reset() -> None:
    """Empty what a scenario leaves behind, before the next one."""
    pool = await database()
    async with pool.connection() as conn:
        await _guarded(conn)
        for table in await _tables(conn):
            await conn.execute(f"DELETE FROM {table}")


class Snapshot:
    """The state a call starts from, copied server-side so every branch starts from it."""

    async def take(self) -> None:
        pool = await database()
        async with pool.connection() as conn:
            await _guarded(conn)
            for table in await _tables(conn):
                await conn.execute(f"DROP TABLE IF EXISTS {SNAPSHOT_PREFIX}{table}")
                await conn.execute(f"CREATE TABLE {SNAPSHOT_PREFIX}{table} AS TABLE {table}")

    async def restore(self) -> None:
        pool = await database()
        async with pool.connection() as conn:
            await _guarded(conn)
            for table in await _tables(conn):
                await conn.execute(f"DELETE FROM {table}")
                await conn.execute(f"INSERT INTO {table} OVERRIDING SYSTEM VALUE SELECT * FROM {SNAPSHOT_PREFIX}{table}")


# ── one branch ────────────────────────────────────────────────────────────


class HintedHarness:
    """The harness's tools, with the branch's hint among the passages ``kb.search`` returns.

    The hint is one more playbook passage, as a published entry would be,
    except that it is shown on every turn: the exploration asks whether the
    hint works when read, the verification of the round whether the words of
    a call find it. When nothing in the documents is relevant to a turn the
    hint is the only passage, and the "nothing relevant" note is not given;
    the knowledge failures where that note matters go to the Gap Loop, not
    here.
    """

    def __init__(self, inner: Any, hint: Hint | None, *, chunk_id: str) -> None:
        self._inner, self.hint, self.chunk_id = inner, hint, chunk_id

    def has(self, name: str) -> bool:
        return self._inner.has(name)

    async def call(self, name: str, /, **args: Any) -> dict[str, Any]:
        envelope = await self._inner.call(name, **args)
        if name != "kb_search" or self.hint is None or not envelope.get("ok"):
            return envelope
        data = dict(envelope.get("data") or {})
        passage = {"chunk_id": self.chunk_id, "doc": "exploration", "source": "playbook", "title": self.hint.trigger,
                   "text": render(self.hint), "restricted": False, "superseded": False, "validity": None,
                   "instruction": None, "redirect": None, "changelog": [], "situation": None, "rank": 0,
                   "score": None, "cosine": None, "coverage": None, "absence": None}
        relevant = [] if data.get("reason") == "no_match" else list(data.get("hits") or [])
        data.update(hits=[*relevant, passage], reason=None if data.get("reason") == "no_match" else data.get("reason"))
        return {**envelope, "data": data}

    async def data(self, name: str, /, **args: Any) -> Any:
        envelope = await self.call(name, **args)
        return envelope.get("data") if envelope.get("ok") else None


@dataclass
class Branch:
    """One call played under one hint (None: the control) and what the grader found in it."""

    hint: Hint | None
    passed: bool | None
    codes: tuple[str, ...]
    rows: list[dict[str, Any]] = field(default_factory=list)
    log: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    usage: dict[str, dict[str, int]] = field(default_factory=dict)
    #: The grader's failures and the simulated customer's, with where they happened.
    failures: list[Failure] = field(default_factory=list)

    @property
    def turns_to_commit(self) -> int | None:
        return self.log.get("turns_to_commit")

    def judged(self, target: str, control: "Branch") -> dict[str, Any]:
        """Fixed: the target code gone. New: failures this branch has beyond the control's, counted."""
        extra = Counter(self.codes) - Counter(control.codes)
        return {"fixed": target not in self.codes, "passed": self.passed, "new": sorted(extra.elements())}

    def summary(self, target: str, control: "Branch") -> dict[str, Any]:
        return {"hint": self.hint.to_json() if self.hint else None, **self.judged(target, control),
                "codes": list(self.codes), "simulator": self.log, "error": self.error}


def value(branch: Branch, target: str, control: Branch) -> tuple[int, int, int, int]:
    """How good a branch is: the failure fixed first, then the call passing, then nothing new broken,
    then the customer agreeing sooner (turns_to_commit, the measure of section 10.5)."""
    judged = branch.judged(target, control)
    sooner = -(branch.turns_to_commit if branch.turns_to_commit is not None else MAX_TURNS + 1)
    return (int(judged["fixed"]), int(judged["passed"] is True), -len(judged["new"]), sooner)


def solved(branch: Branch, target: str, control: Branch) -> bool:
    judged = branch.judged(target, control)
    return judged["fixed"] and not judged["new"] and judged["passed"] is not False and branch.error is None


async def play(rig: Rig, simulator: SimulatorAgent, scenario: Scenario, call_index: int, *, hint: Hint | None,
               seed: int, thread: str, target: str = "", hang_up: bool = False) -> Branch:
    """The call *call_index* of *scenario*, from the current database state, against the simulated customer.

    With *hang_up*, ``after_call`` runs at the end, so the next call of the
    scenario reads what this one left (a whole scenario played, :func:`play_scenario`).
    """
    plan = scenario.calls[call_index]
    harness = HintedHarness(rig.harness, hint, chunk_id=entry_id(target, hint) if hint else "")
    session = CallSession.for_plan(dataclasses.replace(rig, harness=harness), plan, thread=thread, memory=True)
    before = token_ledger.snapshot()
    connected = await session.connect()
    customer = simulator.session(scenario.data, plan.name, seed=seed)
    failed_before = len(simulator.errors)
    line = await customer.opening()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    while line is not None:
        result = await session.turn(line)
        row = trace.turn_row(
            run_id=thread, config="explore", scenario_id=scenario.scenario_id, call=plan.name, turn=session.turn_no,
            customer_text=line, state=result.state, vault=session.vault, total_ms=result.total_ms,
            first_token_ms=result.first_token_ms, input_mode=plan.trace_input_mode,
            call_brief_latency_ms=connected.brief_ms,
        )
        labels = await customer.observe(row["agent_text"])
        row["questions"], row["claims"] = labels["questions"], labels["claims"]
        rows.append(row)
        # A fallback line, empty labels or a persona that could not decide all look like a turn:
        # any model call that failed makes the branch an error, not a result.
        errors += [e for e in (result.error, (result.state.get("draft") or {}).get("error"), labels.get("error")) if e]
        if result.error:
            break
        line = await customer.reply(row["agent_text"], row["tool_calls"], labels)
    if hang_up:
        await session.hang_up()
    errors += simulator.errors[failed_before:]
    if any(EXHAUSTED.search(e) for e in errors):
        raise ProviderExhausted(next(e for e in errors if EXHAUSTED.search(e)))
    error = "; ".join(dict.fromkeys(errors)) or None
    log = customer.log()
    found = (signals.failures(scenario.data, {plan.name: rows}, calls=[plan.name])
             + signals.simulated(scenario.data, plan.name, log))
    passed, _ = signals.grader().check_call(scenario.data["calls"][plan.name], rows)
    return Branch(hint=hint, passed=passed, codes=tuple(f.code for f in found), rows=rows, log=log,
                  error=error, usage=runner.usage_between(before, token_ledger.snapshot()), failures=found)


async def play_scenario(rig: Rig, simulator: SimulatorAgent, scenario: Scenario, *, seed: int,
                        label: str) -> list[Branch]:
    """Every call of *scenario* against the simulated customer, each from what the previous one left."""
    await reset()
    phone, name = scenario.data.get("customer_phone"), scenario.data.get("customer_name")
    played: list[Branch] = []
    for index, plan in enumerate(scenario.calls):
        if plan.seed:
            await runner.seed(rig, plan.seed, customer_phone=phone, customer_name=name)
        played.append(await play(rig, simulator, scenario, index, hint=None, seed=seed,
                                 thread=fresh(f"{label}|{scenario.scenario_id}|{plan.name}"), hang_up=True))
    return played


async def prepare(rig: Rig, scenario: Scenario, call_index: int, snapshot: Snapshot) -> None:
    """The state the failed call starts from: the earlier calls as written, their memory, then a snapshot."""
    await reset()
    phone, name = scenario.data.get("customer_phone"), scenario.data.get("customer_name")
    for index, plan in enumerate(scenario.calls[: call_index + 1]):
        if plan.seed:
            await runner.seed(rig, plan.seed, customer_phone=phone, customer_name=name)
        if index == call_index:
            break
        session = CallSession.for_plan(rig, plan, thread=fresh(f"explore-prefix|{scenario.scenario_id}|{plan.name}"),
                                       memory=True)
        await session.connect()
        for text in plan.turns:
            await session.turn(text)
        await session.hang_up()
    await snapshot.take()


# ── the search ────────────────────────────────────────────────────────────


@dataclass
class Exploration:
    """What the search did for one failure: fixed, not_fixed, not_reproduced or no_hint."""

    failure: Failure
    status: str
    control: Branch
    branches: list[Branch]
    best: Branch | None

    def record(self) -> dict[str, Any]:
        target = self.failure.code
        return {"failure": self.failure.to_json(), "status": self.status,
                "control": self.control.summary(target, self.control),
                "branches": [b.summary(target, self.control) for b in self.branches],
                "best": self.best.summary(target, self.control) if self.best else None}

    def card(self, round_name: str) -> Card | None:
        """The card this exploration leaves: verified when the best branch solved it, a hypothesis otherwise."""
        if self.best is None or self.best.hint is None:
            return None
        target = self.failure.code
        return Card(failure=self.failure, hint=self.best.hint, verified=solved(self.best, target, self.control),
                    control=self.control.codes, branch=self.best.codes, round=round_name,
                    flags=screen(self.best.hint), tried=len(self.branches))


async def explore(
    rig: Rig, qa: QaAgent, simulator: SimulatorAgent, scenario: Scenario, failure: Failure, *,
    rules: Mapping[str, str], transcript: Sequence[Mapping[str, Any]], seed: int = 0, width: int = 3,
    depth: int = 2, progress: Progress = print,
) -> Exploration:
    """Search for a hint that fixes *failure*, branch by branch from one snapshot."""
    index = next(i for i, plan in enumerate(scenario.calls) if plan.name == failure.call)
    snapshot = Snapshot()
    await prepare(rig, scenario, index, snapshot)
    label = f"explore|{failure.scenario_id}|{failure.call}|{failure.code}"
    target = failure.code

    async def branch(hint: Hint | None, number: int) -> Branch:
        await snapshot.restore()
        return await play(rig, simulator, scenario, index, hint=hint, seed=seed, thread=fresh(f"{label}|{number}"),
                          target=target)

    control = await branch(None, 0)
    progress(f"  control {failure.scenario_id}/{failure.call}: {target} "
             f"{'reproduced' if target in control.codes else 'not reproduced'}, passed={control.passed}")
    if target not in control.codes:
        return Exploration(failure, "not_reproduced", control, [], None)

    tried: list[Branch] = []
    best: Branch | None = None
    for level in range(depth):
        hints = await qa.reflect(failure, transcript=transcript, rules=rules,
                                 tried=[b.summary(target, control) for b in tried], width=width)
        if not hints:
            break
        for hint in hints:
            result = await branch(hint, len(tried) + 1)
            tried.append(result)
            judged = result.judged(target, control)
            progress(f"    depth {level + 1} hint {len(tried)}: fixed={judged['fixed']} passed={judged['passed']} "
                     f"new={','.join(judged['new']) or '-'}")
        best = max(tried, key=lambda b: value(b, target, control))
        if solved(best, target, control):
            return Exploration(failure, "fixed", control, tried, best)
    if not tried:
        return Exploration(failure, "no_hint", control, [], None)
    return Exploration(failure, "not_fixed", control, tried, best)


async def verify(
    rig: Rig, simulator: SimulatorAgent, hint: Hint, code: str,
    cases: Sequence[tuple[Scenario, str, str]], regressions: Sequence[tuple[Scenario, str]], *,
    seed: int = 0, progress: Progress = print,
) -> dict[str, Any]:
    """One candidate hint on every call that failed with *code* (``cases``: scenario, call, customer)
    and on calls that passed (``regressions``): whom it fixes, and whether it breaks anything."""
    fixed: set[str] = set()
    tried = broken = not_reproduced = 0
    details: list[dict[str, Any]] = []
    snapshot = Snapshot()

    async def pair(scenario: Scenario, call: str) -> tuple[Branch, Branch]:
        index = next(i for i, plan in enumerate(scenario.calls) if plan.name == call)
        await prepare(rig, scenario, index, snapshot)
        label = f"verify|{scenario.scenario_id}|{call}|{code}"
        control = await play(rig, simulator, scenario, index, hint=None, seed=seed, thread=fresh(f"{label}|0"),
                             target=code)
        await snapshot.restore()
        hinted = await play(rig, simulator, scenario, index, hint=hint, seed=seed, thread=fresh(f"{label}|1"),
                            target=code)
        return control, hinted

    for scenario, call, customer in cases:
        control, hinted = await pair(scenario, call)
        judged = hinted.judged(code, control)
        if code not in control.codes:
            not_reproduced += 1
        else:
            tried += 1
            if judged["fixed"]:
                fixed.add(customer)
        broken += int(bool(judged["new"]) or hinted.error is not None)
        details.append({"scenario_id": scenario.scenario_id, "call": call, "customer": customer,
                        "reproduced": code in control.codes, **judged})
        progress(f"  verify {scenario.scenario_id}/{call}: reproduced={code in control.codes} fixed={judged['fixed']} "
                 f"new={','.join(judged['new']) or '-'}")
    for scenario, call in regressions:
        control, hinted = await pair(scenario, call)
        judged = hinted.judged(code, control)
        broken += int(bool(judged["new"]) or (control.passed is True and hinted.passed is False))
        details.append({"scenario_id": scenario.scenario_id, "call": call, "regression": True, **judged})
        progress(f"  regression {scenario.scenario_id}/{call}: passed {control.passed} -> {hinted.passed}")
    counts = {"customers_fixed": len(fixed), "calls_tried": tried, "calls_broken": broken,
              "not_reproduced": not_reproduced}
    return {"counts": counts, "details": details}
