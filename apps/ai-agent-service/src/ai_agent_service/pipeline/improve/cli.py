"""The improvement loop, one command per step. ``docs/design.md`` section 10.

Two mechanisms and nothing else. Run from the repository's root with the agent's interpreter::

    python -m ai_agent_service.pipeline.improve harvest --run <evaluation run dir> --round learn-1 [--frozen <ids.json>]
    python -m ai_agent_service.pipeline.improve score --round learn-1
    python -m ai_agent_service.pipeline.improve reflect --round learn-1
    python -m ai_agent_service.pipeline.improve publish --review <IMPROVEMENT_DIR>/review/learn-1.json [--scripted]
    python -m ai_agent_service.pipeline.improve rollback --to 0 --reviewer <name> --reason "..."
    python -m ai_agent_service.pipeline.improve gaps --answers <scripted answers.json>
    python -m ai_agent_service.pipeline.improve revoke --chunk FAQ-GAP-XXXX --reviewer <name> --reason "..."
    python -m ai_agent_service.pipeline.improve compare --before <r0 run> [<r0 run> ...] --after <r1 run> [...]
    python -m ai_agent_service.pipeline.improve round --name <name> --learn <dir> --frozen <dir> --frozen-ids <ids.json> [--answers <json>] [--scripted]

**round** is a whole round from the original agent, one command, so anyone can run it again: it refuses to start
unless skills and knowledge are at version 0, measures the frozen sets (R0), runs the learning sets, runs the loop,
publishes what was approved, measures again (R1), compares, and points the agent back to version 0, keeping what it
learned with the round's runs. Without ``--scripted`` it stops at the review files for a person and goes on with
``--approved``.

**Reflection** (the brief, C.5 mechanism 3: after each call the agent writes a structured lesson, checked before it
is written to memory) changes skills, and only where a skill does not say what to do:

1. ``harvest``: the organisers' grader finds what failed in each call of a learning run. No model.
2. ``score``: the QaAgent scores each call on the BTC rubric and diagnoses each failure of how a task was done:
   the skill already says it (``not_followed``), it does not (``skill_gap``), or no procedure is at stake.
3. ``reflect``: for each call with a skill gap the ReflectionAgent writes one lesson card; code screens it and only a
   clean card is stored. Where at least three customers share a lesson (same skill, same failed check, same
   situation) it drafts one sentence of the skill; the screen and the PolicyAgent check it.
4. A person approves in the review file; ``publish`` writes the next skills version. ``--scripted`` is for an
   evaluation, where no person is there: the record says so, and a report must too.

Failures a skill already covers go to the review file as product work; Reflection never learns them.

**The Knowledge Gap Loop** changes the knowledge base: ``gaps`` writes each unanswered question as a standalone one,
joins those that mean the same, and publishes the answers given. **compare** proves a round: the same frozen set
before and after, several runs a side, every check call by call, the harm included.

Everything but the published versions stays in ``IMPROVEMENT_DIR`` (default
``apps/ai-agent-service/data/improvement``, not in git).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Sequence

from ...agents.policy import CHANGE_CHECKS, change_rule
from ...components.context import skills as skill_book
from ...components.improvement import gaps as gap_loop, lessons, review, signals, skill_versions, versions
from ...components.improvement.lessons import MIN_SUPPORT, read_jsonl, round_dir, screen_patch, write_jsonl
from ...components.improvement.signals import Failure
from ...config.config_manager import btc_data_dir


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="improve", description="The improvement loop: Reflection and the Knowledge Gap Loop.")
    commands = parser.add_subparsers(dest="command", required=True)
    harvest = commands.add_parser("harvest", help="File the grader's failures of a learning run")
    harvest.add_argument("--run", type=Path, required=True, help="The directory run_eval.py wrote")
    harvest.add_argument("--scenarios", type=Path, help="The scenarios, when not in the run's directory")
    harvest.add_argument("--round", required=True)
    harvest.add_argument("--frozen", type=Path, action="append", default=[],
                         help="Another JSON list of frozen scenario ids, beside IMPROVEMENT_DIR/frozen.json")
    score_ = commands.add_parser("score", help="The QaAgent scores each call on the rubric and diagnoses each failure")
    score_.add_argument("--round", required=True)
    reflect = commands.add_parser("reflect", help="Lesson cards per call, then one change per lesson enough customers share")
    reflect.add_argument("--round", required=True)
    publish_ = commands.add_parser("publish", help="Publish the changes a reviewer approved as the next skills version")
    publish_.add_argument("--review", type=Path, required=True)
    publish_.add_argument("--scripted", action="store_true", help="An evaluation: approve what passed the gates, recorded as scripted")
    back = commands.add_parser("rollback", help="Point the skills at an earlier version")
    back.add_argument("--to", type=int, required=True)
    back.add_argument("--reviewer", required=True)
    back.add_argument("--reason", required=True)
    gaps = commands.add_parser("gaps", help="Restate and join open questions; publish scripted answers if given")
    gaps.add_argument("--answers", type=Path, help='A JSON list of {"question", "answer", "cites"}')
    revoke = commands.add_parser("revoke", help="Write a knowledge version without one entry")
    revoke.add_argument("--chunk", required=True)
    revoke.add_argument("--reviewer", required=True)
    revoke.add_argument("--reason", required=True)
    compare_ = commands.add_parser("compare", help="Finished runs of the same set before and after, call by call")
    compare_.add_argument("--before", type=Path, nargs="+", required=True, help="One or more runs of the earlier version")
    compare_.add_argument("--after", type=Path, nargs="+", required=True, help="One or more runs of the later version")
    round_ = commands.add_parser("round", help="A whole round from the original agent, and back to it")
    round_.add_argument("--name", required=True)
    round_.add_argument("--learn", type=Path, action="append", default=[], help="A learning set's scenarios directory")
    round_.add_argument("--frozen", type=Path, action="append", default=[], help="A frozen set's scenarios directory")
    round_.add_argument("--frozen-ids", type=Path, action="append", default=[], help="A JSON list of frozen ids")
    round_.add_argument("--answers", type=Path, help="The Knowledge Gap Loop's scripted answers")
    round_.add_argument("--r0-runs", type=int, default=1, help="Runs of each frozen set before learning (noise)")
    round_.add_argument("--r1-runs", type=int, default=1, help="Runs of each frozen set after learning (noise)")
    round_.add_argument("--scripted", action="store_true", help="An evaluation: approve what passed the gates, recorded as scripted")
    round_.add_argument("--approved", action="store_true", help="Go on after a person filled the review files")
    round_.add_argument("--deadline-minutes", type=float, default=90.0,
                        help="The watchdog ends the round past this, as it does at the spend limit (llm/spend_guard.py)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "harvest":
            return harvest(args.run, args.round, scenarios_dir=args.scenarios, frozen=args.frozen)
        if args.command == "score":
            return asyncio.run(score(args.round))
        if args.command == "reflect":
            return asyncio.run(reflect(args.round))
        if args.command == "publish":
            return publish(args.review, scripted=args.scripted)
        if args.command == "rollback":
            previous = skill_versions.rollback(args.to, reviewer=args.reviewer, reason=args.reason)
            print(f"Skills version {previous} -> {args.to}")
            return 0
        if args.command == "gaps":
            return asyncio.run(gaps_round(args.answers))
        if args.command == "revoke":
            version = versions.revoke(args.chunk, reviewer=args.reviewer, reason=args.reason)
            print(f"{args.chunk} revoked: knowledge version {version}")
            return 0
        if args.command == "compare":
            return compare(args.before, args.after)
        if args.command == "round":
            return asyncio.run(run_round(args))
    except (OSError, KeyError, ValueError) as error:
        print(error)
        return 2
    return 2


# ── a run on disk ─────────────────────────────────────────────────────────


def scenarios_of(run: Path, scenarios_dir: Path | None = None) -> list[dict[str, Any]]:
    """The scenarios a run played: its frozen copy (``scenarios/``, or ``full.scenarios/`` for one configuration)."""
    played = {str(r["scenario_id"]) for r in read_jsonl(run / "full.jsonl")}
    folders = [scenarios_dir] if scenarios_dir else [run / "scenarios", run / "full.scenarios"]
    folder = next((f for f in folders if f is not None and f.is_dir()), None)
    if folder is None:
        return []
    found = (json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json")) if not p.name.startswith("_"))
    return [data for data in found if str(data.get("scenario_id")) in played]


def history(by_call: dict[tuple[str, str], list[dict[str, Any]]], scenario: str, call: str) -> str:
    """One call as the loop's models read it, after the same customer's earlier calls of the run."""
    def number(name: str) -> int:
        return int(name.rsplit("_", 1)[-1]) if name.rsplit("_", 1)[-1].isdigit() else 0

    earlier = sorted(((c, rows) for (s, c), rows in by_call.items() if s == scenario and number(c) < number(call)),
                     key=lambda item: number(item[0]))
    return lessons.transcript(by_call.get((scenario, call), []), earlier)


def calls_of(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    by_call: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_call.setdefault((str(row["scenario_id"]), str(row["call"])), []).append(row)
    return {key: sorted(value, key=lambda r: int(r.get("turn") or 0)) for key, value in by_call.items()}


def frozen_ids(extra: Sequence[Path] = ()) -> set[str]:
    """The frozen test sets and holdouts: ``IMPROVEMENT_DIR/frozen.json`` and each of *extra*, JSON lists of scenario
    ids, so the loop never learns from what it is measured on. At least one must exist."""
    paths = [signals.home() / "frozen.json", *extra]
    if not any(path.is_file() for path in paths):
        raise FileNotFoundError(f"Write {paths[0]} first, or give --frozen: the scenario ids of the frozen test set "
                                "and holdout (a JSON list), so the loop never learns from what it is measured on.")
    ids: set[str] = set()
    for path in paths:
        if not path.is_file():
            if path in extra:
                raise FileNotFoundError(f"No frozen list at {path}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{path} must be a JSON list of scenario ids")
        ids |= {str(item) for item in data}
    return ids


def diagnostics(run: Path) -> list[dict[str, Any]]:
    """The run's per-turn diagnostics: ``diagnostics.jsonl``, or ``full.diagnostics.jsonl`` beside a single trace."""
    for name in ("diagnostics.jsonl", "full.diagnostics.jsonl"):
        if (run / name).is_file():
            return read_jsonl(run / name)
    return []


def _source(folder: Path) -> dict[str, Any]:
    path = folder / "source.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing: run harvest for this round first")
    return json.loads(path.read_text(encoding="utf-8"))


#: A call with one of these was not done right whatever else it shows: it is no lesson (spec 10.4, "hứa đại").
VIOLATIONS = ("GUARD.", "HR.price", "HR.list_price", "HR.promo", "TSR.leak", "TSR.forbidden_claim:price",
              "TSR.forbidden_claim:list_price", "TSR.forbidden_claim:promo")


def violated(codes: Iterable[str]) -> bool:
    return any(code.startswith(VIOLATIONS) and code != "GUARD.over_escalation" for code in codes)


# ── harvest ───────────────────────────────────────────────────────────────


def harvest(run: Path, round_name: str, *, scenarios_dir: Path | None = None, frozen: Sequence[Path] = ()) -> int:
    run = run.resolve()
    folder = round_dir(round_name)
    if (folder / "failures.jsonl").exists():
        print(f"{folder} already has failures; a round is harvested once. Name a new round.")
        return 2
    rows = read_jsonl(run / "full.jsonl")
    scenarios = scenarios_of(run, scenarios_dir.resolve() if scenarios_dir else None)
    if not scenarios:
        print(f"No scenario of {run / 'full.jsonl'} found: give a finished run_eval.py run "
              "and, when its scenarios are elsewhere, --scenarios")
        return 2
    shared = {str(s["scenario_id"]) for s in scenarios} & frozen_ids(frozen)
    if shared:
        print(f"Refused: {len(shared)} scenarios of this run are frozen ({', '.join(sorted(shared)[:5])}). "
              "The loop learns from the learning set only.")
        return 2
    found = signals.harvest(scenarios, rows, diagnostics(run))
    unanswered = gap_loop.record_from_run(rows, diagnostics(run))
    played = set(calls_of(rows))
    failing = {(f.scenario_id, f.call) for f in found}
    write_jsonl(folder / "failures.jsonl", [f.to_json() for f in found])
    source_dir = scenarios_dir.resolve() if scenarios_dir else next(
        d for d in (run / "scenarios", run / "full.scenarios") if d.is_dir())
    (folder / "source.json").write_text(json.dumps({
        "run": str(run), "scenarios": str(source_dir), "harvested_at": datetime.now(timezone.utc).isoformat(),
        # The skills the run was played with, as far as this machine knows: publish between run and harvest and
        # the cards would be filed under the wrong version.
        "skills_version": skill_versions.active(),
        "passing_calls": sorted([list(call) for call in played - failing]),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review.log("harvest", round=round_name, run=str(run), failures=len(found), scenarios=len(scenarios), gaps=unanswered)
    print(f"{len(found)} failures in {len(scenarios)} scenarios -> {folder / 'failures.jsonl'}")
    print(f"{unanswered} unanswered questions recorded for the Knowledge Gap Loop (improve gaps)")
    for where, count in Counter(f.route for f in found).most_common():
        print(f"  {where:<10} {count}")
    return 0


# ── score: the QaAgent ────────────────────────────────────────────────────


async def score(round_name: str, qa: Any = None) -> int:
    """Rubric verdicts for every call of the round, then one diagnosis per (call, failed check) of how a task was done.

    A failure routed to review is diagnosed too when its learning set states the lesson we accept (:func:`_admitted`)."""
    from ...agents.qa import QaAgent

    qa = qa or QaAgent()
    if getattr(qa, "llm", True) is None:
        print("No model for the QaAgent (agents.qa in config/models.yaml, and its key): nothing scored, nothing written.")
        return 2
    folder = round_dir(round_name)
    if (folder / "diagnoses.jsonl").exists():
        print(f"{folder} is already scored; a round is scored once.")
        return 2
    source = _source(folder)
    run = Path(source["run"])
    by_call = calls_of(read_jsonl(run / "full.jsonl"))
    scenarios = {str(s["scenario_id"]): s for s in scenarios_of(run, Path(source["scenarios"]))}
    found = [Failure.from_json(row) for row in read_jsonl(folder / "failures.jsonl")]

    judged: list[dict[str, Any]] = []
    for (sid, call), rows in sorted(by_call.items()):
        if sid not in scenarios:
            continue
        judgment = await qa.score(scenarios[sid], call, rows)
        if judgment is None:
            print("No QaAgent model: the rubric is not scored.")
            break
        judged.append({"scenario_id": sid, "call": call, **judgment})
        found += signals.rubric_failures(scenarios[sid], call, judgment)
    write_jsonl(folder / "rubric.jsonl", judged)

    admitted = _admitted(found, Path(source["scenarios"]))
    book = skill_book.read_book()
    known = lessons.situations()
    fixed = lessons.fixed_rules()
    codes: dict[tuple[str, str], set[str]] = {}
    for failure in found:
        codes.setdefault((failure.scenario_id, failure.call), set()).add(failure.code)
    seen: set[tuple[str, str, str]] = set()
    rows_out: list[dict[str, Any]] = []
    for failure in found:
        key = (failure.scenario_id, failure.call, failure.code)
        if (failure.route != "behaviour" and key not in admitted) or key in seen:
            continue
        seen.add(key)
        row = {"scenario_id": failure.scenario_id, "call": failure.call, "customer": failure.customer,
               "failure_code": failure.code, "source": "rubric" if failure.code.startswith("J.") else "grader",
               **({"routed": "review"} if key in admitted else {})}
        if violated(codes[(failure.scenario_id, failure.call)]):
            rows_out.append({**row, "kind": "excluded", "why": "the call also broke a rule; it is no evidence"})
            continue
        diagnosis = await qa.diagnose(failure.code, signals.describe(failure.code),
                                      history(by_call, failure.scenario_id, failure.call),
                                      skills=book, situations=known, fixed_rules=fixed, policy=lessons.rule_texts())
        if diagnosis is None:
            rows_out.append({**row, "kind": "undiagnosed"})
            continue
        kind = lessons.settle_kind(diagnosis.kind, diagnosis.skill, diagnosis.covering_sentence, book, fixed)
        rows_out.append({**row, "kind": kind, "model_kind": diagnosis.kind, "skill": diagnosis.skill,
                         "covering_sentence": diagnosis.covering_sentence,
                         "situation": diagnosis.situation if diagnosis.situation in known else "other", "why": diagnosis.why})
    write_jsonl(folder / "diagnoses.jsonl", rows_out)
    unanswered = await _unanswered(qa, by_call)
    review.log("score", round=round_name, calls=len(judged), diagnosed=len(rows_out),
               kinds=dict(Counter(r["kind"] for r in rows_out)))
    print(f"{len(judged)} calls scored, {len(rows_out)} failures of how a task was done -> {folder / 'diagnoses.jsonl'}")
    print(f"{unanswered} more unanswered questions recorded for the Knowledge Gap Loop, read by the QaAgent")
    for kind, count in Counter(r["kind"] for r in rows_out).most_common():
        print(f"  {kind:<12} {count}")
    return 0


def _admitted(found: Sequence[Failure], scenarios: Path) -> set[tuple[str, str, str]]:
    """Failures routed to review whose learning set states the lesson we accept: they go on to Reflection, and the
    ApprovalAgent, in the reviewer's place, accepts or refuses what comes out. Elsewhere they wait for a person."""
    from ...agents.approval import expectations

    return {(f.scenario_id, f.call, f.code) for f in found
            if f.route == "review" and expectations(scenarios, [f.scenario_id])}


async def _unanswered(qa: Any, by_call: dict[tuple[str, str], list[dict[str, Any]]]) -> int:
    """Turns of the run whose question the agent could not answer, read by the QaAgent, recorded for the Gap Loop.

    The structured signals of ``harvest`` (retrieval abstained, a transfer for missing documents) miss an agent that
    says it has no information and goes on, or answers and takes it back: this reads each turn by meaning. A turn
    already recorded is not asked about again."""
    check = getattr(qa, "unanswered", None)
    if check is None:
        return 0
    already = {(occurrence["call_id"], occurrence["turn_id"]) for gap in gap_loop.list_gaps()
               for occurrence in gap.get("occurrences") or []}
    recorded = 0
    for (scenario, call), rows in sorted(by_call.items()):
        for index, row in enumerate(rows):
            key = (f"{scenario}/{call}", str(row.get("turn")))
            customer = str(row.get("customer_text") or "")
            if key in already or not customer.strip():
                continue
            if await check(customer, str(row.get("agent_text") or "")):
                recent = [str(r.get(k) or "") for r in rows[max(0, index - 2):index] for k in ("customer_text", "agent_text")]
                if gap_loop.record(customer, call_id=key[0], turn_id=key[1], recent=recent):
                    recorded += 1
    return recorded


# ── reflect: the ReflectionAgent ──────────────────────────────────────────


async def reflect(round_name: str, reflection: Any = None, policy: Any = None, approval: Any = None) -> int:
    from ...agents.approval import ApprovalAgent
    from ...agents.policy import PolicyAgent
    from ...agents.reflection import ReflectionAgent

    reflection = reflection or ReflectionAgent()
    policy = policy or PolicyAgent()
    approval = approval or ApprovalAgent()
    folder = round_dir(round_name)
    if (folder / "cards.jsonl").exists() or (signals.home() / "review" / f"{round_name}.json").exists():
        print(f"{folder} was already reflected on; a round is reflected on once.")
        return 2
    source = _source(folder)
    by_call = calls_of(read_jsonl(Path(source["run"]) / "full.jsonl"))
    if not (folder / "diagnoses.jsonl").is_file():
        print(f"No diagnoses in {folder}: run score for this round first.")
        return 2
    diagnosed = read_jsonl(folder / "diagnoses.jsonl")
    version = int(source.get("skills_version") or 0)
    book = skill_book.read_book()
    rules = lessons.rule_texts()
    known = lessons.situations()
    fixed = lessons.fixed_rules()

    cards: list[dict[str, Any]] = []
    for row in diagnosed:
        if row.get("kind") not in ("skill_gap", "not_followed"):
            continue
        target = _skill_for(row, book)
        card = await reflection.lesson(row["failure_code"], signals.describe(row["failure_code"]),
                                       history(by_call, row["scenario_id"], row["call"]),
                                       skill=target, skills=book, rules=rules, situations=known, fixed_rules=fixed,
                                       covering=str(row.get("covering_sentence") or "") if row["kind"] == "not_followed" else "")
        if card is None or card.no_lesson:
            continue
        written = {**card.model_dump(exclude={"no_lesson"}), "skill": target, "failure_code": row["failure_code"],
                   "kind": row["kind"], "covering_sentence": row.get("covering_sentence") or "",
                   "scenario_id": row["scenario_id"], "call": row["call"], "customer": row["customer"],
                   "skills_version": version, "round": round_name}
        written["flags"] = lessons.screen_card(written, skills=book, rules=rules, known_situations=known)
        cards.append(written)
    # The round's clean cards join the stored ones of the same skills version; they are written to disk last, so a
    # round stopped halfway (a rate limit, the policy check) can run again and its answers come from the cache.
    clean = [card for card in cards if not card["flags"]]
    proposals: list[dict[str, Any]] = []
    shared = lessons.clusters([*lessons.stored(skills_version=version), *clean])
    for (skill, situation), items in shared.items():
        code = ", ".join(sorted({str(c.get("failure_code")) for c in items}))
        patch = await reflection.patch(items[:6], skill=skill, skills=book, rules=rules, fixed_rules=fixed)
        if patch is None or patch.no_change:
            print(f"  {skill} / {situation}: no change ({'no answer' if patch is None else patch.why})")
            continue
        flags, verdict = await _check_patch(patch, skill, book, rules, fixed, policy)
        refused = [name for name in verdict.failed if name in CHANGE_CHECKS]
        if refused and not [f for f in flags if not f.startswith("policy:")]:
            # One revision with what the checker refused, then the whole check again: a critic's verdict the writer
            # never sees teaches it nothing (Reflexion's evaluator feedback, Shinn et al. 2023).
            revised = await reflection.patch(items[:6], skill=skill, skills=book, rules=rules, fixed_rules=fixed,
                                             objection={"text": patch.text, "find": patch.find,
                                                        "checks": [change_rule(name) for name in refused]})
            if revised is not None and not revised.no_change:
                print(f"  {skill} / {situation}: revised after the PolicyAgent refused {', '.join(refused)}")
                patch = revised
                flags, verdict = await _check_patch(patch, skill, book, rules, fixed, policy)
        fields = {"skill": skill, **patch.model_dump(exclude={"no_change", "why"})}
        proposals.append({"proposal_id": f"SK-{round_name}-{len(proposals) + 1}", "kind": "skill", "failure_code": code,
                          "situation": situation, "author": "reflection", "patch": fields, "why": patch.why,
                          "entry": {"text": patch.text, "find": patch.find, "cites": patch.cites, "when": patch.when,
                                    "where": f"{skill}.{patch.part}"},
                          "counts": {"customers": len({c["customer"] for c in items}), "cards": len(items),
                                     "cards_shown": min(len(items), 6)},
                          "evidence": [{"scenario_id": c["scenario_id"], "call": c["call"]} for c in items],
                          "flags": flags, "policy": list(verdict.reasons)})
        proposals[-1]["approval"] = await _decided(approval, proposals[-1], Path(source["scenarios"]), rules)
    carded = {(c["scenario_id"], c["call"], c["failure_code"]) for c in cards}
    backlog = [{key: row.get(key) for key in ("failure_code", "scenario_id", "call", "skill", "covering_sentence", "why")}
               for row in diagnosed if row.get("kind") == "not_followed"
               and (row["scenario_id"], row["call"], row["failure_code"]) not in carded]
    unsettled = [{key: row.get(key) for key in ("failure_code", "scenario_id", "call", "skill", "covering_sentence", "why")}
                 for row in diagnosed if row.get("kind") == "unsettled"]
    path = review.write(round_name, proposals, [*backlog, *({**row, "unsettled": True} for row in unsettled)])
    write_jsonl(folder / "cards.jsonl", cards)
    kept = lessons.store(cards)
    print(f"{len(cards)} lesson cards, {kept} stored -> {lessons.store_path()}")
    print(f"{len(proposals)} changes from {len(shared)} lessons shared by {MIN_SUPPORT}+ customers; "
          f"{len(backlog)} failures a skill already covers -> {path}")
    return 0


async def _check_patch(patch: Any, skill: str, book: dict[str, Any], rules: dict[str, str], fixed: str,
                       policy: Any) -> tuple[list[str], Any]:
    """The screen's flags and the PolicyAgent's verdict on one change, its flags among them."""
    flags = screen_patch(f"{patch.text} {patch.when}".strip(), patch.cites, rules=rules)
    try:
        skill_versions.apply(book, {"skill": skill, **patch.model_dump(exclude={"no_change", "why"})})
    except ValueError as error:
        flags.append(f"cannot_apply: {error}")
    cited = {code: rules[code] for code in patch.cites if code in rules}
    verdict = await policy.review_change(patch.text, cited_rules=cited, skill_now=str(book[skill][patch.part]),
                                         fixed_rules=fixed)
    return [*flags, *(f"policy:{name}" for name in verdict.failed)], verdict


async def _decided(approval: Any, proposal: dict[str, Any], scenarios: Path, rules: dict[str, str]) -> dict[str, Any] | None:
    """The ApprovalAgent's decision on one change, against the expectations of the situations its evidence is in;
    None when the learning set states none or the agent gave no answer (the change then waits for a person)."""
    from ...agents.approval import expectations

    expected = expectations(scenarios, [e["scenario_id"] for e in proposal["evidence"]])
    cites = proposal["entry"]["cites"] or []
    decided = await approval.decide(proposal, expected, cited_rules={c: rules[c] for c in cites if c in rules})
    if decided is None:
        return None
    print(f"  {proposal['proposal_id']}: approval agent {'approves' if decided.approve else 'refuses'}: {decided.reason}")
    return {**decided.model_dump(), "situations": sorted(expected)}


def _skill_for(row: dict[str, Any], book: dict[str, Any]) -> str:
    """The skill a lesson changes: the one the task followed when the gap or the unfollowed sentence is in it, else the
    conduct skill (a fixed rule is never changed; how to keep it is written where the advisor always reads it)."""
    skill = str(row.get("skill") or "")
    if skill not in book:
        return lessons.CONDUCT_SKILL
    if row.get("kind") == "not_followed":
        quote = " ".join(str(row.get("covering_sentence") or "").split())
        written = " ".join(f"{book[skill].get('description', '')} {book[skill].get('body', '')}".split())
        return skill if quote and quote in written else lessons.CONDUCT_SKILL
    return skill


def publish(path: Path, *, scripted: bool = False) -> int:
    if scripted:
        review.approve_scripted(path, gap_loop.SCRIPTED)
    taken, refused = review.approved(path)
    for item in refused:
        print(f"  not published {item['proposal_id']}: {item['reason']}")
    if not taken:
        print("Nothing approved to publish")
        return 0
    reviewers = sorted({str(item["reviewer"]).strip() for item in taken})
    version = skill_versions.publish([item["patch"] for item in taken], reviewer=", ".join(reviewers), note=f"review {path.name}")
    print(f"Published {len(taken)} changes: skills version {version}, approved by {', '.join(reviewers)}. The next run reads it.")
    return 0


# ── the knowledge gap loop ────────────────────────────────────────────────


def _embed() -> Any:
    from ...components.knowledge import semantic
    from ...config.config_manager import embedding_dir, get_knowledge_config

    config = get_knowledge_config().embedding
    embedder = semantic.load(embedding_dir() / config.name, model_file=config.model_file) if config else None
    if embedder is None:
        raise ValueError("No embedding model: joining questions by meaning needs one")
    return lambda texts: embedder.embed(list(texts), kind="query")


async def gaps_round(answers: Path | None, *, qa: Any = None, embed: Any = None) -> int:
    from ...agents.qa import QaAgent

    qa = qa or QaAgent()
    embed = embed or _embed()
    restated = await gap_loop.restate_open(qa.restate)
    print(f"Restated {restated}; joined {await gap_loop.merge_same(embed, qa.same_question)}")
    if answers is not None:
        script = json.loads(answers.read_text(encoding="utf-8"))
        results = await gap_loop.answer_from_script(script, embed, qa.answers_question)
        for result, count in Counter(r["status"] for r in results).items():
            print(f"  {result}: {count}")
    for gap in gap_loop.list_gaps():
        if gap["status"] == "open":
            print(f"  open x{len(gap['occurrences'])}: {gap.get('restated') or gap['question']}")
    return 0


# ── the proof ─────────────────────────────────────────────────────────────

METRICS = (("TSR", lambda r: r["task_success_rate"]["value"]), ("RQR", lambda r: r["repeat_question_rate"]["value"]),
           ("CCR", lambda r: r["context_carryover_rate"]["value"]),
           ("HR price", lambda r: r["hallucination_rate"]["price_promo_only"]["value"]),
           ("violations", lambda r: r["guardrail_violations"]["total"]))


def _report(run: Path) -> Path:
    """The organisers' table of a run: ``report.json`` in a run directory, ``full.report.json`` beside one trace."""
    for name in ("report.json", "full.report.json"):
        if (run / name).is_file():
            return run / name
    raise FileNotFoundError(f"No report.json in {run}: give a finished run_eval.py run")


def _failed_share(runs: Sequence[Path]) -> tuple[dict[tuple[str, str, str], float], set[tuple[str, str]]]:
    """Per (scenario, call, check): the share of *runs* in which it failed, every check the grader makes; and the
    calls every one of *runs* played."""
    counts: Counter[tuple[str, str, str]] = Counter()
    played: set[tuple[str, str]] | None = None
    for run in runs:
        rows = read_jsonl(run / "full.jsonl")
        found = signals.harvest(scenarios_of(run), rows, diagnostics(run))
        counts.update({(f.scenario_id, f.call, f.code) for f in found})
        played = set(calls_of(rows)) if played is None else played & set(calls_of(rows))
    return {key: count / len(runs) for key, count in counts.items()}, played or set()


def compare(before: Sequence[Path], after: Sequence[Path]) -> int:
    """The numbers of each side and the checks that changed, call by call: what a round must show, harm included.

    With several runs a side (the same version run again), a check counts as failing on a side when it failed in more
    than half of that side's runs, and each metric shows its mean and range: a change inside the range of one
    version's own reruns is noise, not a result (section 10.4).
    """
    sides = {"before": list(before), "after": list(after)}
    reports = {side: [json.loads(_report(run).read_text(encoding="utf-8"))["system"] for run in runs]
               for side, runs in sides.items()}
    print(f"{'':<12}{'before':>22}{'after':>22}")
    for name, read in METRICS:
        cells = []
        for side in sides:
            values = [read(report) for report in reports[side]]
            numbers = [v for v in values if isinstance(v, (int, float))]
            cells.append(f"{mean(numbers):.3g} [{min(numbers):.3g}-{max(numbers):.3g}]" if len(numbers) > 1
                         else str(values[0]))
        print(f"{name:<12}{cells[0]:>22}{cells[1]:>22}")
    measured = {side: _failed_share(runs) for side, runs in sides.items()}
    shares = {side: measured[side][0] for side in sides}
    both = measured["before"][1] & measured["after"][1]
    if both != measured["before"][1] | measured["after"][1]:
        print(f"Only the {len(both)} calls every run played are compared call by call.")
    failing = {side: {key for key, share in shares[side].items() if share > 0.5 and key[:2] in both} for side in sides}
    for label, keys in (("fixed", failing["before"] - failing["after"]), ("broken", failing["after"] - failing["before"])):
        print(f"{label}: {len(keys)}")
        for scenario, call, code in sorted(keys):
            print(f"  {scenario} {call} {code}  (before {shares['before'].get((scenario, call, code), 0):.0%}, "
                  f"after {shares['after'].get((scenario, call, code), 0):.0%})")
    harm = [key for key in failing["after"] - failing["before"] if violated([key[2]])]
    if harm:
        print(f"HARM: {len(harm)} new violations; roll the skills back (improve rollback) and run the set again.")
    return 0


# ── a whole round ─────────────────────────────────────────────────────────

REPOSITORY = Path(__file__).resolve().parents[6]


def _label(scenarios: Path) -> str:
    """``data/reflection/frozen/scenarios`` is ``reflection``: the set's own folder name."""
    return scenarios.parent.parent.name if scenarios.name == "scenarios" else scenarios.name


def _evaluate(scenarios: Path, out: Path) -> Path:
    """One run of the evaluation command on *scenarios*, then the organisers' table beside its trace."""
    import subprocess
    import sys

    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "full.manifest.json"
    finished = manifest.is_file() and json.loads(manifest.read_text(encoding="utf-8")).get("finished_at")
    if not finished:  # a run that finished is never paid for again; one that stopped is run again from the start
        subprocess.run([sys.executable, str(REPOSITORY / "run_eval.py"), "--scenarios", str(scenarios), "--config", "full",
                        "--out", str(out / "full.jsonl")], cwd=REPOSITORY, check=True)
    if not (out / "report.json").is_file():
        subprocess.run([sys.executable, str(btc_data_dir() / "eval" / "reference_eval.py"), "--scenarios",
                        str(out / "full.scenarios"), "--trace", str(out / "full.jsonl"), "--out", str(out / "report.json")],
                       cwd=REPOSITORY, check=True, stdout=subprocess.DEVNULL)
    return out


def _back_to_original(folder: Path, reviewer: str) -> None:
    """Skills and knowledge at version 0 again, through the loop so the log says so; what was learned moves to *folder*."""
    import shutil

    if skill_versions.active():
        skill_versions.rollback(0, reviewer=reviewer, reason="round finished: back to the original agent")
    if versions.active():
        versions.rollback(0, reviewer=reviewer, reason="round finished: back to the original agent")
    learned = folder / "learned"
    (learned / "kb").mkdir(parents=True, exist_ok=True)
    skills_dir = skill_book.versions_dir()
    if skills_dir.is_dir():
        shutil.move(str(skills_dir), str(learned / "skills"))
    from ...config.config_manager import kb_dir

    for version in versions.versions():
        if version > 0:
            shutil.move(str(kb_dir() / f"v{version}.jsonl"), str(learned / "kb" / f"v{version}.jsonl"))


def _watched(deadline_minutes: float) -> Any:
    """The spend watchdog over this round's process group: at the limit or past the deadline it ends every run of it.

    Only for a round an assistant started on its own (``SPEND_SINCE`` set, ``llm/spend_guard.py``); a person's round
    runs unwatched, and this returns None."""
    import os
    import subprocess
    import sys

    from ...llm import spend_guard

    if not spend_guard.active():
        return None

    spend_guard.may_start()  # at the planned ceiling no new round starts; the hard stop ends one already running
    os.setpgrp()  # this round and its evaluation runs in one group, which the watchdog can end
    return subprocess.Popen([sys.executable, "-m", "ai_agent_service.llm.spend_guard", "watch", "--pgid",
                             str(os.getpgrp()), "--deadline-minutes", str(deadline_minutes)],
                            start_new_session=True, cwd=REPOSITORY)


async def run_round(args: argparse.Namespace) -> int:
    watchdog = _watched(args.deadline_minutes)
    try:
        return await _round(args)
    finally:
        if watchdog is not None:
            watchdog.terminate()


async def _round(args: argparse.Namespace) -> int:
    import os

    from ...pipeline.eval.cli import runs_dir

    folder = runs_dir() / args.name
    os.environ["IMPROVEMENT_DIR"] = str(folder / "improvement")
    os.environ.setdefault("IMPROVEMENT_CACHE", str(runs_dir() / "cache" / "improvement-answers.jsonl"))
    learn = [path.resolve() for path in args.learn]
    frozen = [path.resolve() for path in args.frozen]
    if not args.approved:
        if skill_versions.active() or versions.active():
            print(f"Not the original agent: skills version {skill_versions.active()}, knowledge version "
                  f"{versions.active()}. A round starts from version 0; roll back first (improve rollback).")
            return 2
        for path in frozen:
            for index in range(1, args.r0_runs + 1):
                _evaluate(path, folder / f"r0-{_label(path)}-{index}")
        for path in learn:
            run = _evaluate(path, folder / f"learn-{_label(path)}")
            name = f"{args.name}-{_label(path)}"
            if harvest(run, name, scenarios_dir=path, frozen=args.frozen_ids) != 0:
                return 2
            if await score(name) != 0:
                return 2
            if await reflect(name) != 0:
                return 2
        if args.answers:
            await gaps_round(args.answers)
        if not args.scripted:
            print(f"Review files in {folder / 'improvement' / 'review'}: a person fills decision, reviewer and note, "
                  f"then: improve round --name {args.name} --approved (with the same --learn and --frozen).")
            return 0
    for path in learn:
        review_file = folder / "improvement" / "review" / f"{args.name}-{_label(path)}.json"
        if review_file.is_file():
            publish(review_file, scripted=args.scripted)
    for path in frozen:
        after = [folder / (f"r1-{_label(path)}" if index == 1 else f"r1-{_label(path)}-{index}")
                 for index in range(1, args.r1_runs + 1)]
        for run in after:
            _evaluate(path, run)
        print(f"\n== {_label(path)}")
        compare([folder / f"r0-{_label(path)}-{index}" for index in range(1, args.r0_runs + 1)], after)
    _back_to_original(folder, reviewer=gap_loop.SCRIPTED if args.scripted else "round")
    print(f"\nBack to the original agent; what this round learned is in {folder / 'learned'}.")
    return 0
