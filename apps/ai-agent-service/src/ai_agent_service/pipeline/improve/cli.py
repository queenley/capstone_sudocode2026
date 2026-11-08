"""The improvement loop, one command per step. ``docs/design.md`` section 10.

Two mechanisms and nothing else. Run from the repository's root with the agent's interpreter::

    python -m ai_agent_service.pipeline.improve harvest --run <evaluation run dir> --round learn-1
    python -m ai_agent_service.pipeline.improve reflect --round learn-1
    python -m ai_agent_service.pipeline.improve publish --review <IMPROVEMENT_DIR>/review/learn-1.json [--scripted]
    python -m ai_agent_service.pipeline.improve rollback --to 0 --reviewer <name> --reason "..."
    python -m ai_agent_service.pipeline.improve gaps --answers <scripted answers.json>
    python -m ai_agent_service.pipeline.improve revoke --chunk FAQ-GAP-XXXX --reviewer <name> --reason "..."
    python -m ai_agent_service.pipeline.improve compare --before <run r0> --after <run r1>

**Reflection** changes skills: harvest files the grader's failures of a learning run, reflect proposes one change to
one skill for each failure at least three customers share, a person approves, publish writes the next version.
**The Knowledge Gap Loop** changes the knowledge base: gaps writes each unanswered question as a standalone one, joins
those that mean the same, and publishes the answers given. **compare** proves it: the same frozen set before and after,
call by call. ``--scripted`` is for an evaluation, where no person is there: the record says so, and a report must too.

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
from typing import Any, Iterable, Sequence

from ...components.context import skills as skill_book
from ...components.improvement import gaps as gap_loop, review, signals, skill_versions, versions
from ...components.improvement.lessons import MIN_SUPPORT, read_jsonl, round_dir, screen_patch, write_jsonl
from ...components.improvement.signals import Failure
from ...components.knowledge.corpus import policy_chunks
from ...config.config_manager import btc_data_dir


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="improve", description="The improvement loop: Reflection and the Knowledge Gap Loop.")
    commands = parser.add_subparsers(dest="command", required=True)
    harvest = commands.add_parser("harvest", help="File the grader's failures of a learning run")
    harvest.add_argument("--run", type=Path, required=True, help="The directory run_eval.py wrote")
    harvest.add_argument("--scenarios", type=Path, help="The scenarios, when not in the run's directory")
    harvest.add_argument("--round", required=True)
    reflect = commands.add_parser("reflect", help="Propose one change to a skill per failure shared by enough customers")
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
    compare_ = commands.add_parser("compare", help="Two finished runs of the same set, call by call")
    compare_.add_argument("--before", type=Path, required=True)
    compare_.add_argument("--after", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "harvest":
            return harvest(args.run, args.round, scenarios_dir=args.scenarios)
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
    except (OSError, KeyError, ValueError) as error:
        print(error)
        return 2
    return 2


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


# ── reflection ────────────────────────────────────────────────────────────


def _rules() -> dict[str, str]:
    """What a change may cite: the organisers' public documents."""
    return {c.chunk_id: f"{c.title}: {c.text[:400]}" for c in policy_chunks(btc_data_dir() / "policy") if not c.restricted}


def _transcripts(folder: Path) -> dict[tuple[str, str], list[dict[str, str]]]:
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    said: dict[tuple[str, str], list[dict[str, str]]] = {}
    rows = read_jsonl(Path(source["run"]) / "full.jsonl")
    for row in sorted(rows, key=lambda r: int(r.get("turn") or 0)):
        lines = said.setdefault((str(row["scenario_id"]), str(row["call"])), [])
        lines += [{"speaker": "customer", "text": str(row.get("customer_text") or "")},
                  {"speaker": "agent", "text": str(row.get("agent_text") or "")}]
    return said


def shared_failures(found: Iterable[Failure]) -> dict[str, list[Failure]]:
    """Behaviour failures by code, only where at least :data:`MIN_SUPPORT` customers share them: one call is one vote."""
    by_code: dict[str, list[Failure]] = {}
    for failure in found:
        if failure.route == "behaviour":
            by_code.setdefault(failure.code, []).append(failure)
    return {code: items for code, items in by_code.items() if len({f.customer for f in items}) >= MIN_SUPPORT}


async def reflect(round_name: str, qa: Any = None, policy: Any = None) -> int:
    from ...agents.policy import PolicyAgent
    from ...agents.qa import QaAgent

    qa = qa or QaAgent()
    policy = policy or PolicyAgent()
    folder = round_dir(round_name)
    found = [Failure.from_json(row) for row in read_jsonl(folder / "failures.jsonl")]
    shared = shared_failures(found)
    said = _transcripts(folder)
    rules = _rules()
    book = skill_book.read_book()
    proposals: list[dict[str, Any]] = []
    for code, items in shared.items():
        calls = [{"reason": f.reason, "transcript": said.get((f.scenario_id, f.call), [])} for f in items[:5]]
        patch = await qa.patch_skill(code, calls, skills=book, rules=rules)
        if patch is None or patch.no_change:
            print(f"  {code}: no change ({'no answer' if patch is None else patch.why})")
            continue
        fields = patch.model_dump()
        flags = screen_patch(patch.text, patch.cites, rules=rules)
        try:
            skill_versions.apply(book, fields)
        except ValueError as error:
            flags.append(f"cannot_apply: {error}")
        verdict = await policy.review_change(patch.text, kind="skill")
        proposals.append({"proposal_id": f"SK-{round_name}-{len(proposals) + 1}", "kind": "skill", "failure_code": code,
                          "author": "qa", "patch": fields, "entry": {"text": f"{patch.skill}.{patch.part}: {patch.text}"},
                          "counts": {"customers": len({f.customer for f in items}), "calls": len(items)},
                          "evidence": [{"scenario_id": f.scenario_id, "call": f.call} for f in items],
                          "flags": flags, "policy": list(verdict.reasons)})
    path = review.write(round_name, proposals)
    print(f"{len(proposals)} changes from {len(shared)} shared failures -> {path}")
    return 0


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
    print(f"Restated {await gap_loop.restate_open(qa.restate)}; joined {gap_loop.merge_same(embed)}")
    if answers is not None:
        script = json.loads(answers.read_text(encoding="utf-8"))
        results = gap_loop.answer_from_script(script, embed)
        for result, count in Counter(r["status"] for r in results).items():
            print(f"  {result}: {count}")
    for gap in gap_loop.list_gaps():
        if gap["status"] == "open":
            print(f"  open x{len(gap['occurrences'])}: {gap.get('restated') or gap['question']}")
    return 0


# ── the proof ─────────────────────────────────────────────────────────────


def compare(before: Path, after: Path) -> int:
    """Each run's numbers, and the calls that changed: what a round must show, the harm included (section 10.4)."""
    reports = [json.loads((run / "report.json").read_text(encoding="utf-8"))["system"] for run in (before, after)]
    for name, read in (("TSR", lambda r: r["task_success_rate"]["value"]), ("RQR", lambda r: r["repeat_question_rate"]["value"]),
                       ("CCR", lambda r: r["context_carryover_rate"]["value"]),
                       ("HR price", lambda r: r["hallucination_rate"]["price_promo_only"]["value"]),
                       ("violations", lambda r: r["guardrail_violations"]["total"])):
        print(f"{name:<12}{read(reports[0])!s:>10}{read(reports[1])!s:>10}")
    failed = [{(f["scenario"], f["call"]) for f in r["task_success_rate"]["failures"]} for r in reports]
    for label, calls in (("fixed", failed[0] - failed[1]), ("broken", failed[1] - failed[0])):
        print(f"{label}: {len(calls)}")
        for scenario, call in sorted(calls):
            print(f"  {scenario} {call}")
    return 0
