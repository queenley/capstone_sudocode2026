"""Pick a persona-diverse sample of a run's scenarios for the rubric judge, and print the command.

The judge costs a model call per call of every scenario; a sample of SCN-GEN and SCN-ADV
scenarios spread over as many personas as possible keeps the cost down. No model call here::

    python scripts/evaluation/judge_sample.py evaluation/runs/eval_3 --gen 20 --adv 10
    python scripts/evaluation/judge_sample.py evaluation/runs/eval_3 --gen 20 --adv 10 \
        --anchor evaluation/runs/gaploop-5/r1-gaploop-5/full.scenarios

Only scenarios the run finished (with turns in its trace) are drawn. Personas are taken round-robin
in a seeded random order, so each persona appears once before any appears twice. ``--anchor`` takes
another run's scenarios first (e.g. a round's frozen 20), so the sample overlaps the runs it is
compared with, and fills the rest with personas the anchor does not cover.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

TRACES = ("full.jsonl", "baseline.jsonl")
SCENARIOS = ("scenarios", "full.scenarios")


def _scenarios(folder: Path) -> dict[str, dict]:
    return {data["scenario_id"]: data for data in
            (json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json")))}


def _finished(run: Path) -> set[str]:
    trace = next((run / name for name in TRACES if (run / name).is_file()), None)
    if trace is None:
        raise SystemExit(f"{run} holds no trace ({', '.join(TRACES)})")
    return {json.loads(line)["scenario_id"] for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()}


def pick(pool: dict[str, dict], size: int, rng: random.Random, first: list[str] = ()) -> list[str]:
    """*size* ids: *first* (as many as fit), then one per persona in random order, round after round."""
    chosen = list(first)[:size]
    used = defaultdict(int)
    for scenario_id in chosen:
        used[pool[scenario_id]["persona"]] += 1
    by_persona = defaultdict(list)
    for scenario_id in sorted(pool):
        if scenario_id not in chosen:
            by_persona[pool[scenario_id]["persona"]].append(scenario_id)
    for ids in by_persona.values():
        rng.shuffle(ids)
    personas = sorted(by_persona)
    rng.shuffle(personas)
    while len(chosen) < size and any(by_persona.values()):
        # The persona used least so far goes first; ties keep the random order.
        persona = min((p for p in personas if by_persona[p]), key=lambda p: used[p])
        chosen.append(by_persona[persona].pop())
        used[persona] += 1
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", type=Path, help="A finished run (eval_3, or a round's r0/r1 run).")
    parser.add_argument("--gen", type=int, default=20, help="SCN-GEN scenarios (default 20).")
    parser.add_argument("--adv", type=int, default=10, help="SCN-ADV scenarios (default 10).")
    parser.add_argument("--seed", type=int, default=20261115, help="Same seed, same sample.")
    parser.add_argument("--anchor", type=Path, help="Scenario folder whose ids are taken first.")
    parser.add_argument("--ids", action="store_true", help="Print only the chosen ids, one per line (for scripts).")
    parser.add_argument("--out", type=Path, help="Judge output (default: <run>-judge, where method_metrics.py reads it).")
    args = parser.parse_args(argv)

    folder = next((args.run / name for name in SCENARIOS if (args.run / name).is_dir()), None)
    if folder is None:
        raise SystemExit(f"{args.run} holds no scenarios ({', '.join(SCENARIOS)})")
    finished = _finished(args.run)
    every = {k: v for k, v in _scenarios(folder).items() if k in finished}
    anchor = set(_scenarios(args.anchor)) if args.anchor else set()
    rng = random.Random(args.seed)
    sample = []
    for prefix, size in (("SCN-GEN", args.gen), ("SCN-ADV", args.adv)):
        pool = {k: v for k, v in every.items() if k.startswith(prefix)}
        if len(pool) < size:
            print(f"{prefix}: the run has only {len(pool)} finished; taking all of them", file=sys.stderr)
        sample += pick(pool, size, rng, sorted(anchor & set(pool)))

    if args.ids:
        print("\n".join(sorted(sample)))
        return 0
    print(f"{'scenario':14} {'level':5} {'persona':36} hard_case")
    for scenario_id in sorted(sample):
        data = every[scenario_id]
        print(f"{scenario_id:14} {data.get('level', ''):5} {data['persona']:36} {data.get('hard_case') or ''}")
    personas = {every[s]["persona"] for s in sample}
    print(f"\n{len(sample)} scenarios, {len(personas)} personas"
          f" (of {len({v['persona'] for v in every.values()})} in the run)")
    out = args.out or Path(str(args.run).rstrip("\\/") + "-judge")
    only = " ".join(f"--only {s}" for s in sorted(sample))
    print(f"\nrun_eval.py --judge-run {args.run} --out {out} {only}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
