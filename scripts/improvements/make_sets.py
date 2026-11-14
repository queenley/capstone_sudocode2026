"""Build a learn set and a frozen set for an improvement round from data/dev, mixed general (GEN) / advanced (ADV).

    python scripts/improvements/make_sets.py --name dev-1 --learn 20 --frozen 10 --adv-share 0.5 --seed 1

writes data/.build/rounds/<name>/{learn/scenarios, frozen/scenarios, frozen.json} (gitignored) and prints the round
command. Learn and frozen never share a scenario. Only data/dev is sampled: data/test is the test set and is never
learned from. Every scenario in both sets is played by the model, so the counts are what the round costs.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "dev" / "scenarios"


def split(n: int, adv_share: float) -> tuple[int, int]:
    adv = round(n * adv_share)
    return n - adv, adv


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--learn", type=int, required=True, help="Scenarios to learn from")
    p.add_argument("--frozen", type=int, required=True, help="Scenarios measured before and after learning")
    p.add_argument("--adv-share", type=float, default=0.5, help="Share of ADV scenarios in each set (0..1)")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    if not 0 <= args.adv_share <= 1:
        p.error("--adv-share must be between 0 and 1")

    pools = {kind: sorted(SOURCE.glob(f"SCN-{kind}-*.json")) for kind in ("GEN", "ADV")}
    rng = random.Random(args.seed)
    for files in pools.values():
        rng.shuffle(files)
    picked: dict[str, list[Path]] = {}
    for part, n in (("learn", args.learn), ("frozen", args.frozen)):
        gen, adv = split(n, args.adv_share)
        if gen > len(pools["GEN"]) or adv > len(pools["ADV"]):
            sys.exit(f"{part}: not enough scenarios left (GEN {len(pools['GEN'])}, ADV {len(pools['ADV'])})")
        picked[part] = [pools["GEN"].pop() for _ in range(gen)] + [pools["ADV"].pop() for _ in range(adv)]

    out = ROOT / "data" / ".build" / "rounds" / args.name
    if out.exists():
        sys.exit(f"{out} already exists: choose a new --name")
    for part, files in picked.items():
        target = out / part / "scenarios"
        target.mkdir(parents=True)
        for f in files:
            shutil.copy2(f, target / f.name)
    (out / "frozen.json").write_text(json.dumps(sorted(f.stem for f in picked["frozen"]), indent=1) + "\n",
                                     encoding="utf-8")

    for part, files in picked.items():
        gen = sum(f.name.startswith("SCN-GEN") for f in files)
        print(f"{part}: {len(files)} scenarios ({gen} GEN, {len(files) - gen} ADV)")
    rel = out.relative_to(ROOT).as_posix()
    print(f"\npython -m ai_agent_service.pipeline.improve round --name {args.name} "
          f"--learn {rel}/learn/scenarios --frozen {rel}/frozen/scenarios --frozen-ids {rel}/frozen.json --scripted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
