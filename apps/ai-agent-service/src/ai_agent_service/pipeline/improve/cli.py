"""The Reflection loop, one command per step. ``docs/design.md`` section 10.

Run from the repository's root with the agent's interpreter::

    python -m ai_agent_service.pipeline.improve harvest --run <evaluation run dir> --round learn-1
    python -m ai_agent_service.pipeline.improve simulate --round learn-1 --scenarios <dir> --only <id>
    python -m ai_agent_service.pipeline.improve measure --label r0 --scenarios <dir> --only <id> --seeds 1 2
    python -m ai_agent_service.pipeline.improve compare --labels r0 r1
    python -m ai_agent_service.pipeline.improve explore --round learn-1 --limit 5
    python -m ai_agent_service.pipeline.improve propose --round learn-1
    python -m ai_agent_service.pipeline.improve publish --review <IMPROVEMENT_DIR>/review/learn-1.json
    python -m ai_agent_service.pipeline.improve rollback --to 0 --reviewer <name> --reason "..."
    python -m ai_agent_service.pipeline.improve revoke --chunk LP-XXXXXXXX --reviewer <name> --reason "..."

1. **harvest** reads a closed evaluation run of the *learning* set (the
   directory ``run_eval.py`` wrote: ``scenarios/``, ``full.jsonl``,
   ``diagnostics.jsonl``) and files the grader's failures, routed. It
   refuses a run that shares a scenario with ``IMPROVEMENT_DIR/frozen.json``,
   the frozen test set and holdout, which must be written first: nothing the
   loop is measured on may teach it.
   **simulate** does the same from a learning set played against the
   simulated customer (``agents.simulator``), whose persona reacts as its
   prompt says: it files what only a customer who can decide shows
   (``SIM.lost``, ``SIM.challenged``) beside the grader's failures.
   **measure** plays a set the same way, the frozen one included, and keeps
   what closed, what was lost and how many turns the customer took to agree;
   **compare** sets two measurements side by side, call by call. A
   measurement by the exploration's own customer is diagnostic, not an
   official number.
2. **explore** searches a hint for each behaviour failure (``.explore``) and
   files one card per failure. It plays calls: models and Postgres.
3. **propose** consolidates the failures with enough support into entries,
   verifies each on every call that failed the same way and on calls that
   passed, and writes the review file of the round for a person.
4. **publish** writes what a person approved as the next knowledge version.
   **rollback** and **revoke** go back.

Everything but the published version stays in ``IMPROVEMENT_DIR`` (default
``apps/ai-agent-service/data/improvement``, not in git).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from ...components.improvement import lessons, playbook, review, signals, versions
from ...components.improvement.lessons import MIN_SUPPORT, read_jsonl, round_dir, write_jsonl
from ...components.improvement.signals import Failure
from ...components.knowledge.corpus import policy_chunks
from ...config.config_manager import btc_data_dir


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ai_agent_service.pipeline.improve",
                                     description="Reflection: harvest, explore, propose, publish.")
    commands = parser.add_subparsers(dest="command", required=True)
    harvest = commands.add_parser("harvest", help="File the grader's failures of a learning run")
    harvest.add_argument("--run", type=Path, required=True,
                         help="The directory run_eval.py wrote (both configurations, or --config full --out <dir>/full.jsonl)")
    harvest.add_argument("--scenarios", type=Path,
                         help="The scenarios the run played, when the run has no scenarios/ of its own (--config full)")
    harvest.add_argument("--round", required=True)
    simulate = commands.add_parser("simulate", help="File the failures of a learning set played against the "
                                                    "simulated customer (plays calls)")
    simulate.add_argument("--round", required=True)
    simulate.add_argument("--scenarios", type=Path, required=True)
    simulate.add_argument("--only", action="append", default=[], metavar="SCENARIO_ID")
    simulate.add_argument("--seed", type=int, default=0)
    measure = commands.add_parser("measure", help="Play a set against the simulated customer and keep what closed "
                                                  "(plays calls)")
    measure.add_argument("--label", required=True)
    measure.add_argument("--scenarios", type=Path, required=True)
    measure.add_argument("--only", action="append", default=[], metavar="SCENARIO_ID")
    measure.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    compare = commands.add_parser("compare", help="Two measurements side by side, call by call")
    compare.add_argument("--labels", nargs=2, required=True, metavar=("BEFORE", "AFTER"))
    explore = commands.add_parser("explore", help="Search a hint for each behaviour failure (plays calls)")
    explore.add_argument("--round", required=True)
    explore.add_argument("--code", action="append", default=[], help="Only this failure code; repeat for more")
    explore.add_argument("--limit", type=int, default=5, help="Failures explored in this run (default 5)")
    explore.add_argument("--seed", type=int, default=0)
    explore.add_argument("--width", type=int, default=3, help="Hints per reflection (default 3)")
    explore.add_argument("--depth", type=int, default=2, help="Reflections per failure (default 2)")
    propose = commands.add_parser("propose", help="Consolidate, verify and write the review file (plays calls)")
    propose.add_argument("--round", required=True)
    propose.add_argument("--regressions", type=int, default=3, help="Passing calls each candidate is also played on")
    propose.add_argument("--seed", type=int, default=0)
    publish = commands.add_parser("publish", help="Publish what a person approved as the next knowledge version")
    publish.add_argument("--review", type=Path, required=True)
    rollback = commands.add_parser("rollback", help="Point the knowledge base at an earlier version")
    rollback.add_argument("--to", type=int, required=True)
    rollback.add_argument("--reviewer", required=True)
    rollback.add_argument("--reason", required=True)
    revoke = commands.add_parser("revoke", help="A new version without one entry")
    revoke.add_argument("--chunk", required=True)
    revoke.add_argument("--reviewer", required=True)
    revoke.add_argument("--reason", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "harvest":
            return harvest(args.run, args.round, scenarios_dir=args.scenarios)
        if args.command == "publish":
            return publish(args.review)
        if args.command == "compare":
            return compare(*args.labels)
        if args.command == "rollback":
            previous = versions.rollback(args.to, reviewer=args.reviewer, reason=args.reason)
            print(f"Knowledge version {previous} -> {args.to}")
            return 0
        if args.command == "revoke":
            version = versions.revoke(args.chunk, reviewer=args.reviewer, reason=args.reason)
            print(f"{args.chunk} revoked: knowledge version {version}")
            return 0
    except (OSError, KeyError, ValueError) as error:
        print(error)
        return 2
    return _played(args)


# ── harvest ───────────────────────────────────────────────────────────────


def frozen_ids() -> set[str]:
    """The frozen test set and holdout: ``IMPROVEMENT_DIR/frozen.json``, a list of scenario ids."""
    path = signals.home() / "frozen.json"
    if not path.is_file():
        raise FileNotFoundError(f"Write {path} first: the scenario ids of the frozen test set and holdout "
                                "(a JSON list), so the loop never learns from what it is measured on.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a JSON list of scenario ids")
    return {str(item) for item in data}


def diagnostics(run: Path) -> list[dict[str, Any]]:
    """The run's per-turn diagnostics: ``diagnostics.jsonl``, or ``full.diagnostics.jsonl`` beside a single trace."""
    for name in ("diagnostics.jsonl", "full.diagnostics.jsonl"):
        if (run / name).is_file():
            return read_jsonl(run / name)
    return []


def harvest(run: Path, round_name: str, *, scenarios_dir: Path | None = None) -> int:
    run = run.resolve()
    folder = round_dir(round_name)
    if (folder / "failures.jsonl").exists():
        print(f"{folder} already has failures; a round is harvested once. Name a new round.")
        return 2
    rows = read_jsonl(run / "full.jsonl")
    played_ids = {str(r["scenario_id"]) for r in rows}
    source_dir = (scenarios_dir or run / "scenarios").resolve()
    scenarios = [data for data in (json.loads(p.read_text(encoding="utf-8")) for p in sorted(source_dir.glob("*.json"))
                                   if not p.name.startswith("_"))
                 if str(data.get("scenario_id")) in played_ids]
    if not scenarios:
        print(f"No scenario of {run / 'full.jsonl'} in {source_dir}: give a finished run_eval.py run "
              "and, for a single trace, --scenarios")
        return 2
    shared = {str(s["scenario_id"]) for s in scenarios} & frozen_ids()
    if shared:
        print(f"Refused: {len(shared)} scenarios of this run are frozen ({', '.join(sorted(shared)[:5])}). "
              "The loop learns from the learning set only.")
        return 2
    found = signals.harvest(scenarios, rows, diagnostics(run))
    played = {(str(r["scenario_id"]), str(r["call"])) for r in rows}
    failing = {(f.scenario_id, f.call) for f in found}
    write_jsonl(folder / "failures.jsonl", [f.to_json() for f in found])
    (folder / "source.json").write_text(json.dumps({
        "run": str(run), "scenarios": str(source_dir), "harvested_at": datetime.now(timezone.utc).isoformat(),
        "passing_calls": sorted([list(call) for call in played - failing]),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review.log("harvest", round=round_name, run=str(run), failures=len(found), scenarios=len(scenarios))
    print(f"{len(found)} failures in {len(scenarios)} scenarios -> {folder / 'failures.jsonl'}")
    for where, count in Counter(f.route for f in found).most_common():
        print(f"  {where:<10} {count}")
    by_code: dict[str, set[str]] = {}
    for failure in found:
        if failure.route == "behaviour":
            by_code.setdefault(failure.code, set()).add(failure.customer)
    for code, customers in sorted(by_code.items(), key=lambda item: -len(item[1])):
        mark = "" if len(customers) >= MIN_SUPPORT else f"  (under {MIN_SUPPORT} customers)"
        print(f"  behaviour {code}: {len(customers)} customers{mark}")
    return 0


# ── explore and propose: they play calls ─────────────────────────────────


def _played(args: argparse.Namespace) -> int:
    from . import explore

    folder = measure_dir() if args.command == "measure" else round_dir(args.round)
    harvested = (folder / "failures.jsonl").exists()
    if args.command in ("explore", "propose") and not harvested:
        print(f"Harvest or simulate the round first: {folder / 'failures.jsonl'} does not exist")
        return 2
    if args.command == "simulate" and harvested:
        print(f"{folder} already has failures; a round is filed once. Name a new round.")
        return 2
    if args.command == "measure" and (folder / f"{args.label}.json").exists():
        print(f"Measurement {args.label} exists; name a new one.")
        return 2
    try:
        if args.command == "simulate":
            frozen_ids()
        name = explore.use_explore_database()
    except (OSError, ValueError, RuntimeError) as error:
        print(error)
        return 2
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["MCP_TRANSPORT"] = "stdio"
    os.environ["MCP_LOG_FILE"] = str(folder / "mcp-servers.log")
    print(f"{args.command} {getattr(args, 'round', None) or args.label}: database {name}")
    run = {"explore": _explore_round, "propose": _propose_round, "simulate": _simulate_round,
           "measure": _measure}[args.command]
    try:
        return asyncio.run(run(args, folder))
    except explore.ProviderExhausted as error:
        print(f"Stopped: the model provider refused ({str(error)[:200]}). Nothing of this run was kept; "
              "run it again once the quota is back.")
        return 3


def _rules(chunk_ids: Iterable[str]) -> dict[str, str]:
    """What the QaAgent may cite: the telesales playbook, and the passages the failed call was shown."""
    chunks = {c.chunk_id: c for c in policy_chunks(btc_data_dir() / "policy") if not c.restricted}
    wanted = [cid for cid in chunks if cid.startswith("PB-")] + [cid for cid in chunk_ids if cid in chunks]
    return {cid: f"{chunks[cid].title}: {chunks[cid].text[:600]}" for cid in dict.fromkeys(wanted)}


def _context(folder: Path) -> tuple[dict[str, Any], dict[tuple[str, str], list[dict[str, Any]]], dict[tuple[str, str], set[str]]]:
    """The round's source, the learning run's lines by call, and the passages each call was shown."""
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    run = Path(source["run"])
    lines: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in read_jsonl(run / "full.jsonl"):
        lines.setdefault((str(row["scenario_id"]), str(row["call"])), []).append(row)
    shown: dict[tuple[str, str], set[str]] = {}
    for item in diagnostics(run):
        if item.get("config") in (None, "full") and item.get("knowledge"):
            shown.setdefault((str(item["scenario_id"]), str(item["call"])), set()).update(item["knowledge"].get("chunks") or [])
    return source, lines, shown


def _transcript(rows: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    said: list[dict[str, str]] = []
    for row in sorted(rows, key=lambda r: int(r.get("turn") or 0)):
        said.append({"speaker": "customer", "text": str(row.get("customer_text") or "")})
        said.append({"speaker": "agent", "text": str(row.get("agent_text") or "")})
    return said


async def _agents() -> tuple[Any, Any, Any]:
    from ...agents.qa import QaAgent
    from ...agents.simulator import SimulatorAgent
    from ..eval import runner

    simulator = SimulatorAgent(cache_path=signals.home() / "cache" / "simulator-observer.json")
    qa = QaAgent()
    if simulator.llm is None or qa.llm is None:
        raise RuntimeError("The exploration needs agents.simulator and agents.qa in config/models.yaml, with their keys")
    rig = await runner.build(retries=1)
    return rig, qa, simulator


async def _close() -> None:
    from ...llm import jev
    from ...mcp import client as mcp_client

    await mcp_client.close_all()
    await jev.close()


async def _explore_round(args: argparse.Namespace, folder: Path) -> int:
    from ..eval import scenarios
    from . import explore

    source, lines, shown = _context(folder)
    done = {(r["failure"]["scenario_id"], r["failure"]["call"], r["failure"]["code"])
            for r in read_jsonl(folder / "explorations.jsonl")}
    todo: dict[tuple[str, str, str], Failure] = {}
    for row in read_jsonl(folder / "failures.jsonl"):
        failure = Failure.from_json(row)
        key = (failure.scenario_id, failure.call, failure.code)
        if failure.route != "behaviour" or key in done or key in todo or (args.code and failure.code not in args.code):
            continue
        todo[key] = failure
    chosen = list(todo.values())[: max(0, args.limit)]
    if not chosen:
        print("Nothing left to explore in this round" + (f" for {', '.join(args.code)}" if args.code else ""))
        return 0
    ready = {s.scenario_id: s for s in scenarios.load(Path(source["scenarios"]), {f.scenario_id for f in chosen})[0]}
    try:
        rig, qa, simulator = await _agents()
        print(f"Advisor {rig.provider}/{rig.advisor.model_name}; QaAgent {qa.llm.__class__.__name__}; "
              f"customer {simulator.model_name}; {len(chosen)} failures")
        for failure in chosen:
            scenario = ready.get(failure.scenario_id)
            if scenario is None:
                print(f"  {failure.scenario_id}: not in {source['scenarios']}")
                continue
            print(f"{failure.scenario_id}/{failure.call} {failure.code}")
            key = (failure.scenario_id, failure.call)
            try:
                result = await explore.explore(
                    rig, qa, simulator, scenario, failure, rules=_rules(shown.get(key, ())),
                    transcript=_transcript(lines.get(key, [])), seed=args.seed, width=args.width, depth=args.depth)
            except explore.ProviderExhausted:
                raise
            except Exception as error:  # noqa: BLE001 - one failure's exploration never stops the round
                print(f"  error: {type(error).__name__}: {error}"[:300])
                write_jsonl(folder / "explorations.jsonl", [{"failure": failure.to_json(), "status": "error",
                                                             "error": f"{type(error).__name__}: {error}"[:300]}],
                            append=True)
                continue
            write_jsonl(folder / "explorations.jsonl", [result.record()], append=True)
            card = result.card(args.round)
            if card is not None:
                lessons.add(card)
            print(f"  {result.status}" + (f": card {'verified' if card and card.verified else 'unverified'}"
                                          + (f", flagged {', '.join(card.flags)}" if card and card.flags else "")
                                          if card else ""))
    finally:
        await _close()
    review.log("explore", round=args.round, explored=len(chosen))
    return 0


async def _propose_round(args: argparse.Namespace, folder: Path) -> int:
    from ..eval import scenarios
    from . import explore

    pool = lessons.cards(args.round)
    codes = lessons.ready(pool)
    if not codes:
        counted = Counter(card.failure.code for card in pool if card.counts)
        print(f"No failure has verified cards from {MIN_SUPPORT} customers yet: "
              + (", ".join(f"{code} {n}" for code, n in counted.most_common()) or "no verified card"))
        return 0
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    failures = [Failure.from_json(row) for row in read_jsonl(folder / "failures.jsonl")]
    loaded = {s.scenario_id: s for s in scenarios.load(Path(source["scenarios"]))[0]}
    proposals: list[dict[str, Any]] = []
    try:
        rig, _, simulator = await _agents()
        for code in codes:
            entry = playbook.consolidate(pool, code)
            if entry is None:
                print(f"{code}: no candidate passes the screen")
                continue
            cases: dict[str, tuple[Any, str, str]] = {}
            for failure in failures:
                if failure.code == code and failure.scenario_id in loaded:
                    cases.setdefault(failure.customer, (loaded[failure.scenario_id], failure.call, failure.customer))
            customers = {customer for _, _, customer in cases.values()}
            regressions = [(loaded[sid], call) for sid, call in source.get("passing_calls") or []
                           if sid in loaded and signals.customer_of(loaded[sid].data) not in customers]
            print(f"{code}: candidate {entry.chunk_id} on {len(cases)} customers, {min(len(regressions), args.regressions)} regressions")
            result = await explore.verify(rig, simulator, entry.hint, code, list(cases.values()),
                                          regressions[: max(0, args.regressions)], seed=args.seed)
            counts = result["counts"]
            write_jsonl(folder / "verifications.jsonl", [{"code": code, "entry": entry.chunk_id,
                                                         "hint": entry.hint.to_json(), **result}], append=True)
            accepted = counts["customers_fixed"] >= MIN_SUPPORT and counts["calls_broken"] == 0
            print(f"  {json.dumps(counts)} -> {'proposed' if accepted else 'not proposed'}")
            if accepted:
                verified = playbook.Entry(chunk_id=entry.chunk_id, hint=entry.hint, failure_code=code,
                                          persona=entry.persona, evidence=entry.evidence, counts=counts)
                proposals.append({"proposal_id": entry.chunk_id, "kind": "playbook", "failure_code": code,
                                  "author": "qa", "entry": verified.kb_entry(round_name=args.round, approved_by=""),
                                  "counts": counts, "evidence": list(entry.evidence),
                                  "flags": list(lessons.screen(entry.hint))})
    finally:
        await _close()
    if not proposals:
        print("Nothing to review in this round")
        return 0
    path = review.write(args.round, proposals)
    print(f"{len(proposals)} proposals for review: {path} (and {path.with_suffix('.md').name})")
    return 0


# ── the simulated customer: learning and measuring ───────────────────────


def measure_dir() -> Path:
    return signals.home() / "measure"


def _one_line(branch: Any) -> str:
    log = branch.log
    reacted = ",".join(log.get("reactions") or []) or "-"
    return (f"  {log.get('call')}: passed={branch.passed} outcome={log.get('outcome')} "
            f"turns_to_commit={log.get('turns_to_commit')} reactions={reacted} codes={','.join(branch.codes) or '-'}")


async def _simulate_round(args: argparse.Namespace, folder: Path) -> int:
    from ..eval import scenarios
    from . import explore

    ready = scenarios.load(args.scenarios, set(args.only) or None)[0]
    shared = {s.scenario_id for s in ready} & frozen_ids()
    if shared:
        print(f"Refused: {', '.join(sorted(shared))} are frozen. The loop learns from the learning set only.")
        return 2
    if not ready:
        print(f"No scenario to play in {args.scenarios}")
        return 2
    rows: list[dict[str, Any]] = []
    found: list[Failure] = []
    logs: list[dict[str, Any]] = []
    passing: list[list[str]] = []
    try:
        rig, _, simulator = await _agents()
        print(f"Advisor {rig.provider}/{rig.advisor.model_name}; customer {simulator.model_name}; {len(ready)} scenarios")
        for scenario in ready:
            print(scenario.scenario_id)
            for branch in await explore.play_scenario(rig, simulator, scenario, seed=args.seed, label=f"simulate|{args.round}"):
                rows += branch.rows
                found += branch.failures
                logs.append(branch.log)
                if not branch.failures and branch.error is None:
                    passing.append([scenario.scenario_id, str(branch.log.get("call"))])
                print(_one_line(branch))
    finally:
        await _close()
    write_jsonl(folder / "failures.jsonl", [f.to_json() for f in found])
    write_jsonl(folder / "full.jsonl", rows)
    write_jsonl(folder / "simulator.jsonl", logs)
    (folder / "source.json").write_text(json.dumps({
        "run": str(folder), "scenarios": str(args.scenarios.resolve()), "seed": args.seed, "simulated": True,
        "harvested_at": datetime.now(timezone.utc).isoformat(), "passing_calls": passing,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review.log("simulate", round=args.round, scenarios=[s.scenario_id for s in ready], failures=len(found))
    _summary(found)
    return 0


def _summary(found: Sequence[Failure]) -> None:
    print(f"{len(found)} failures")
    for where, count in Counter(f.route for f in found).most_common():
        print(f"  {where:<10} {count}")
    by_code: dict[str, set[str]] = {}
    for failure in found:
        if failure.route == "behaviour":
            by_code.setdefault(failure.code, set()).add(failure.customer)
    for code, customers in sorted(by_code.items(), key=lambda item: -len(item[1])):
        mark = "" if len(customers) >= MIN_SUPPORT else f"  (under {MIN_SUPPORT} customers)"
        print(f"  behaviour {code}: {len(customers)} customers{mark}")


async def _measure(args: argparse.Namespace, folder: Path) -> int:
    from ..eval import scenarios
    from . import explore

    ready = scenarios.load(args.scenarios, set(args.only) or None)[0]
    if not ready:
        print(f"No scenario to play in {args.scenarios}")
        return 2
    results: list[dict[str, Any]] = []
    try:
        rig, _, simulator = await _agents()
        print(f"Advisor {rig.provider}/{rig.advisor.model_name}; customer {simulator.model_name}; "
              f"knowledge v{versions.active()}; seeds {args.seeds}")
        for seed in args.seeds:
            for scenario in ready:
                print(f"seed {seed} {scenario.scenario_id}")
                for branch in await explore.play_scenario(rig, simulator, scenario, seed=seed,
                                                          label=f"measure|{args.label}|{seed}"):
                    spec = scenario.data["calls"][branch.log["call"]]
                    results.append({"scenario_id": scenario.scenario_id, "call": branch.log["call"], "seed": seed,
                                    "judged": bool(spec.get("success_if")), "passed": branch.passed,
                                    "expected": spec.get("expected_outcome"), "outcome": branch.log.get("outcome"),
                                    "turns_to_commit": branch.log.get("turns_to_commit"),
                                    "reactions": branch.log.get("reactions") or [], "codes": list(branch.codes),
                                    "error": branch.error,
                                    "turns": [{"turn": r["turn"], "customer": r["customer_text"], "agent": r["agent_text"],
                                               "tools": [t["name"] for t in r["tool_calls"]]} for r in branch.rows]})
                    print(_one_line(branch))
    finally:
        await _close()
    record = {"label": args.label, "knowledge_version": versions.active(), "seeds": args.seeds,
              "scenarios": [s.scenario_id for s in ready], "results": results, "summary": summarise(results)}
    (folder / f"{args.label}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review.log("measure", label=args.label, knowledge_version=record["knowledge_version"], summary=record["summary"])
    print(json.dumps(record["summary"], ensure_ascii=False))
    return 0


def summarise(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """What closed, what was lost, what the persona had to check, and how fast customers agreed."""
    judged = [r for r in results if r["judged"]]
    agreed = [r["turns_to_commit"] for r in results if r["turns_to_commit"] is not None]
    return {"calls": len(results), "judged": len(judged), "passed": sum(1 for r in judged if r["passed"] is True),
            "lost": sum(1 for r in results if "SIM.lost" in r["codes"]),
            "challenged": sum(1 for r in results if "SIM.challenged" in r["codes"]),
            "held": sum(r["reactions"].count("hold") for r in results),
            "turns_to_commit_mean": round(sum(agreed) / len(agreed), 2) if agreed else None,
            "errors": sum(1 for r in results if r["error"])}


def compare(before: str, after: str) -> int:
    """Two measurements of the same calls and seeds: the totals, then every call whose verdict changed."""
    first, second = (json.loads((measure_dir() / f"{label}.json").read_text(encoding="utf-8")) for label in (before, after))
    print(f"{before} (knowledge v{first['knowledge_version']}) -> {after} (knowledge v{second['knowledge_version']})")
    for key, value in first["summary"].items():
        print(f"  {key:<22} {value!s:>8} -> {second['summary'].get(key)!s:>8}")
    old = {(r["scenario_id"], r["call"], r["seed"]): r for r in first["results"]}
    shared = [(key, old[key], r) for r in second["results"]
              if (key := (r["scenario_id"], r["call"], r["seed"])) in old]
    if len(shared) != len(first["results"]) or len(shared) != len(second["results"]):
        print(f"  warning: {len(shared)} calls in common of {len(first['results'])} and {len(second['results'])}")
    flips = [(key, a, b) for key, a, b in shared if a["judged"] and a["passed"] != b["passed"]]
    for (sid, call, seed), a, b in flips:
        print(f"  {sid}/{call} seed {seed}: passed {a['passed']} -> {b['passed']} "
              f"(outcome {a['outcome']} -> {b['outcome']}, codes {','.join(a['codes']) or '-'} -> {','.join(b['codes']) or '-'})")
    better = sum(1 for _, a, b in flips if b["passed"] is True)
    print(f"  {better} calls passed only after, {len(flips) - better} only before, of {sum(1 for _, a, _ in shared if a['judged'])} judged")
    return 0


# ── publish ───────────────────────────────────────────────────────────────


def publish(path: Path) -> int:
    taken, refused = review.approved(path)
    for item in refused:
        print(f"  not published {item['proposal_id']}: {item['reason']}")
    if not taken:
        print("Nothing approved to publish")
        return 0
    reviewers = sorted({str(item["reviewer"]).strip() for item in taken})
    lines = [{**item["entry"], "approved_by": str(item["reviewer"]).strip()} for item in taken]
    version = versions.publish(lines, reviewer=", ".join(reviewers), note=f"review {path.name}")
    print(f"Published {len(lines)} entries: knowledge version {version}. Restart the agent, or the next run, to read it.")
    return 0
