"""The organisers' customer simulator, run on a cohort for several seeds (``simulator/customer_simulator_spec.md``).

    python run_eval.py --simulate --scenarios <dir> --only <id> ... --seeds 0 1 2 --out <dir>

The official numbers play ``customer_turns`` as written; this plays the same scenarios against a customer who reacts:
:class:`agents.simulator.Customer` applies the specification's eight rules in its order (patience by persona and by
call, at most twelve customer turns) and the persona's model words each line. What the specification grades:

(a) the eight rules: the kernel in ``agents/simulator.py`` and its tests;
(b) repeatability: every seed writes ``seed-<n>.jsonl`` in the organisers' trace format, graded by
    ``reference_eval.py`` as it is; ``summary.json`` gives TSR per seed, mean, standard deviation and range, and
    whether the range is within the specification's 10 points;
(c) no leak: the agent hears only what the customer says. ``must_not_ask`` and ``success_if`` reach the kernel,
    never the persona's prompt nor the agent (``leaks``).

Every call is logged as the specification asks (``simulator.jsonl``: scenario, call, persona, seed, patience trace,
outcome, turns, who ended it). Only the ``full`` configuration is played: the simulator measures the system's
repeatability, not the memory's contribution, which the scripted runs measure.

Seeds and model: the persona's model is ``agents.simulator`` in ``config/models.yaml`` (temperature 0.3, as the
specification recommends), with the provider's sampling seed set to the run's seed (:func:`seeded`); each seed has its
own checkpoint threads and its own observer cache. The agent's own model is unchanged.

Limits: the customer speaks the outline's clean ``customer_turns``, so a scenario whose official input is
``customer_turns_asr`` is played without its ASR errors; the questions and claims are labelled by the simulator's
observer (the product's extractor on the simulator's model), not by the evaluation's extractor.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ...agents.base import model_for
from ...agents.simulator import MAX_TURNS, SimulatorAgent
from ...components.improvement.signals import grader
from . import trace
from .scenarios import Scenario

Progress = Callable[[str], None]

#: The specification's limit on the TSR range across seeds (section 5b).
MAX_RANGE = 10.0
#: The fields of ``success_if`` and of the call spec the customer's prompt must never carry (section 5c).
HIDDEN = ("must_not_ask", "success_if", "must_carry_over", "ground_truth_facts", "memory_expectation")
#: Outcomes after which the agent gets no closing turn: the customer left or the call went to a person.
NO_CLOSING = frozenset({"tu_choi", "timeout", "chuyen_may"})


def leaks(scenario: Mapping[str, Any], prompt: str) -> list[str]:
    """Which hidden blocks of *scenario* show in the customer's *prompt*: none, or the specification's (c) fails.

    A block leaks when its name is in the prompt, or when a slot it lists is, unless the customer knows that slot
    (a key of ``facts_established`` in this or an earlier call, which the persona is meant to have).
    """
    found: list[str] = []
    known = {slot for spec in scenario["calls"].values() for slot in (spec.get("facts_established") or {})}
    for call, spec in scenario["calls"].items():
        for block in HIDDEN:
            value = spec.get(block)
            if not value:
                continue
            if block in prompt:
                found.append(f"{call}.{block}")
            elif block in ("must_not_ask", "must_carry_over"):
                hidden = [w for w in value if isinstance(w, str) and w not in known and f'"{w}"' in prompt]
                if hidden:
                    found.append(f"{call}.{block}:{','.join(hidden)}")
    return found


async def play_call(rig: Any, simulator: SimulatorAgent, scenario: Scenario, index: int, *, seed: int,
                    config: str, run_id: str) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """One call of *scenario* against the simulated customer, from the database as the previous call left it.

    Returns the trace rows, the specification's log of the call and the errors of any model call.
    """
    from .runner import CallSession

    plan = scenario.calls[index]
    # One checkpoint thread per seed: the graph keeps a call's state by thread, and seed 1 must not go on from seed 0.
    session = CallSession.for_plan(rig, plan, thread=f"{run_id}|{config}|seed-{seed}|{scenario.scenario_id}|{plan.name}",
                                   memory=True)
    connected = await session.connect()
    customer = simulator.session(scenario.data, plan.name, seed=seed)
    failed_before = len(simulator.errors)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    async def say(text: str) -> dict[str, Any]:
        result = await session.turn(text)
        row = trace.turn_row(
            run_id=run_id, config=config, scenario_id=scenario.scenario_id, call=plan.name, turn=session.turn_no,
            customer_text=text, state=result.state, vault=session.vault, total_ms=result.total_ms,
            first_token_ms=result.first_token_ms, input_mode=plan.trace_input_mode,
            call_brief_latency_ms=connected.brief_ms,
        )
        errors.extend(e for e in (result.error, (result.state.get("draft") or {}).get("error")) if e)
        rows.append(row)
        return row

    line = await customer.opening()
    while line is not None and len(rows) < MAX_TURNS + 1:
        row = await say(line)
        labels = await customer.observe(row["agent_text"], row["tool_calls"], today=plan.on)
        row["questions"], row["claims"] = labels.get("questions") or [], labels.get("claims") or []
        if labels.get("error"):
            errors.append(str(labels["error"]))
        if errors:
            break
        line = await customer.reply(row["agent_text"], row["tool_calls"], labels)
    log = customer.log()
    # The organisers' closing turn: the customer said their last line and stayed, so the agent may read the
    # order back and place it, as in the scripted runs (runner._run_call).
    if not errors and log["outcome"] not in NO_CLOSING:
        row = await say("")
        labels = (await customer.observe(row["agent_text"], row["tool_calls"], today=plan.on)
                  if row["agent_text"].strip() or row["tool_calls"] else {})
        row["questions"], row["claims"] = labels.get("questions") or [], labels.get("claims") or []
        if labels.get("error"):
            errors.append(str(labels["error"]))
    remembered = await session.hang_up()
    if rows:
        rows[-1]["memory_writes"] = trace.memory_writes(remembered.get("memory_writes") or [])
    if remembered.get("status") == "failed":
        errors.append(f"after_call: {remembered.get('error') or remembered.get('reason')}")
    errors += simulator.errors[failed_before:]
    return rows, log, list(dict.fromkeys(errors))


async def play_scenario(rig: Any, simulator: SimulatorAgent, scenario: Scenario, *, seed: int, config: str,
                        run_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Every call of *scenario* in order, each from what the previous one left."""
    from . import runner

    await runner.reset()
    phone, name = scenario.data.get("customer_phone"), scenario.data.get("customer_name")
    rows: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    for index, plan in enumerate(scenario.calls):
        if plan.seed:
            await runner.seed(rig, plan.seed, customer_phone=phone, customer_name=name)
        played, log, errors = await play_call(rig, simulator, scenario, index, seed=seed, config=config,
                                              run_id=run_id)
        rows += played
        logs.append({**log, "errors": errors})
        if errors:
            return rows, logs, f"{plan.name}: {errors[0][:300]}"
    return rows, logs, None


def grade(scenarios_dir: Path, traces: Path) -> dict[str, Any]:
    """``reference_eval.py``'s report of one seed's trace, its functions imported as they are."""
    btc = grader()
    scenarios = btc.load_scenarios(str(scenarios_dir))
    rows = btc.load_trace(str(traces))
    return btc.evaluate(scenarios, rows)


def summarise(per_seed: Mapping[int, Mapping[str, Any]], logs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """TSR per seed, mean ± standard deviation and range, and the simulator's own counts."""
    tsr = {seed: (report.get("task_success_rate") or {}).get("value") for seed, report in per_seed.items()}
    values = [v for v in tsr.values() if isinstance(v, (int, float))]
    spread = max(values) - min(values) if values else None
    outcomes: dict[str, int] = {}
    for log in logs:
        outcomes[log["outcome"]] = outcomes.get(log["outcome"], 0) + 1
    return {
        "tsr_by_seed": tsr,
        "tsr_mean": round(statistics.fmean(values), 2) if values else None,
        "tsr_stdev": round(statistics.stdev(values), 2) if len(values) > 1 else None,
        "tsr_range": round(spread, 2) if spread is not None else None,
        "within_10_points": spread is not None and spread <= MAX_RANGE,
        "calls": len(logs),
        "outcomes": outcomes,
        "ended_by": {who: sum(1 for log in logs if log["ended_by"] == who) for who in ("agent", "customer", "timeout")},
        "repeat_complaints": sum(1 for log in logs for p, q in zip(log["patience_trace"], log["patience_trace"][1:])
                                 if q < p),
        "errors": sum(1 for log in logs if log.get("errors")),
    }


async def run(rig: Any, ready: Sequence[Scenario], seeds: Sequence[int], out: Path, *, run_id: str,
              progress: Progress = print, simulator: SimulatorAgent | None = None) -> int:
    """Play *ready* once per seed into *out*; 0 when every call ran, 1 when one failed (no summary printed)."""
    from . import report

    out.mkdir(parents=True, exist_ok=True)
    frozen = report.freeze(list(ready), [], out / "scenarios")
    ready = [replace(s, path=frozen / s.path.name) for s in ready]
    leaked = {s.scenario_id: found for s in ready
              for found in [[x for c in s.data["calls"] for x in leaks(s.data, simulator_prompt(s.data, c))]] if found}
    if leaked:
        (out / "leaks.json").write_text(json.dumps(leaked, ensure_ascii=False, indent=2), encoding="utf-8")
        progress(f"The customer's prompt carries hidden labels: {leaked}. Nothing played.")
        return 2
    all_logs: list[dict[str, Any]] = []
    agent: SimulatorAgent | None = simulator
    per_seed: dict[int, dict[str, Any]] = {}
    failed = False
    base = None if simulator else model_for("simulator")
    for seed in seeds:
        agent = simulator or SimulatorAgent(llm=seeded(base, seed), cache_path=out / "cache" / f"observer-seed-{seed}.json")
        if agent.llm is None:
            progress("agents.simulator has no model (config/models.yaml and its key): a script is not a simulation.")
            return 2
        rows: list[dict[str, Any]] = []
        for scenario in ready:
            progress(f"seed {seed} {scenario.scenario_id}")
            played, logs, error = await play_scenario(rig, agent, scenario, seed=seed, config="full", run_id=run_id)
            rows += played
            all_logs += logs
            for log in logs:
                progress(f"  {log['call']}: {log['outcome']} by {log['ended_by']} after {log['n_turns']} turns, "
                         f"patience {log['patience_trace']}" + (f"  ERROR {log['errors'][0][:160]}" if log["errors"] else ""))
            if error:
                failed = True
        trace_path = out / f"seed-{seed}.jsonl"
        trace.write_jsonl(trace_path, rows)
        if not failed:
            per_seed[seed] = grade(frozen, trace_path)
            (out / f"seed-{seed}.report.json").write_text(json.dumps(per_seed[seed], ensure_ascii=False, indent=2),
                                                          encoding="utf-8")
            progress(f"seed {seed}: TSR {(per_seed[seed].get('task_success_rate') or {}).get('value')}")
    trace.write_jsonl(out / "simulator.jsonl", all_logs)
    record = {"run_id": run_id, "finished_at": datetime.now(timezone.utc).isoformat(), "seeds": list(seeds),
              "scenarios": [s.scenario_id for s in ready], "status": "INCOMPLETE" if failed else "COMPLETE",
              "simulator_model": getattr(agent, "model_name", None),
              "summary": None if failed else summarise(per_seed, all_logs)}
    (out / "summary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    if failed:
        progress(f"A call failed: no summary. See {out / 'simulator.jsonl'}")
        return 1
    progress(json.dumps(record["summary"], ensure_ascii=False, indent=2))
    return 0


def seeded(llm: Any, seed: int) -> Any:
    """*llm* with the provider's sampling seed set to *seed* when its client takes one (OpenAI, Gemini); else as is.

    The specification asks for a fixed seed. Providers treat it as best effort: the same seed makes a run likelier,
    not certain, to repeat, which is why three seeds are played and their spread reported.
    """
    if llm is not None and "seed" in getattr(type(llm), "model_fields", {}):
        return llm.model_copy(update={"seed": seed})
    return llm


def simulator_prompt(scenario: Mapping[str, Any], call: str) -> str:
    """The persona prompt the customer of *call* is given, as :class:`agents.simulator.Customer` builds it."""
    from ...agents.simulator import Customer

    return Customer(scenario, call, seed=0).prompt
