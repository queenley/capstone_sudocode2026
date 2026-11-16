"""The 2x2 measurement of the two improvement methods: Router, GapLoop, Reflection, and the two together.

    python scripts/evaluation/ablation.py --name abl-1 --gap-round gaploop-5 --kb-version 5 \\
        --reflection-round reflection-1 --skills-version 2 [--proof budget ...] [--runs 3] [--only-config combined]

Nothing is learned here. The four configurations differ only in the two versions the single-method rounds learned
and a person approved:

  router      knowledge v0, skills v0
  gaploop     knowledge v<kb-version> of --gap-round,        skills v0
  reflection  knowledge v0,                                   skills v<skills-version> of --reflection-round
  combined    knowledge v<kb-version> of --gap-round,        skills v<skills-version> of --reflection-round

so Combined is exactly GapLoop + Reflection, not a round of its own (the user's decision, 2026-11-16: the separate
``combined_1`` round learned kb v5 + skills v1 and proved neither column).

Every configuration runs, ``--runs`` times (fresh model calls each time, k = 3 by default), on the same suite:

  control     the frozen data/dev sample of --gap-round (checked byte-identical to --reflection-round's): "no harm"
  gap-loop    data/gap-loop/frozen: what GapLoop must have learned, with its three controls
  <proof>     data/reflection/<proof>/frozen for each --proof (default budget): what Reflection must have learned

Runs are interleaved run by run (run 1 of every configuration, then run 2...), so drift over the hours a run takes
falls on every configuration alike. Each run goes through the evaluation command as a round's runs do
(``pipeline/improve/cli._evaluate``: a finished run is never paid for again, a stopped one is kept beside).

The learned files are put in place for the run and taken out after; the agent in force stays at version 0 (the run
selects versions with --kb-version/--skills-version). Verdict: ``scripts/evaluation/ablation_verdict.py --name ...``.
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "apps" / "ai-agent-service" / "src", ROOT / "packages" / "backend-common"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

CONFIGS = ("router", "gaploop", "reflection", "combined")
GAP_PROOF = ROOT / "data" / "gap-loop" / "frozen" / "scenarios"


def reflection_proof(name: str) -> Path:
    return ROOT / "data" / "reflection" / name / "frozen" / "scenarios"


def control_of(round_name: str) -> Path:
    return ROOT / "data" / ".build" / "rounds" / round_name / "frozen" / "scenarios"


def digest(folder: Path) -> str:
    """One hash of a scenario folder: names and bytes of its JSON files."""
    h = hashlib.sha256()
    for f in sorted(folder.glob("*.json")):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def suite(args: argparse.Namespace) -> dict[str, Path]:
    """The sets every configuration runs on, by label."""
    control = Path(args.control) if args.control else control_of(args.gap_round)
    other = control_of(args.reflection_round)
    if not args.control and other.is_dir() and digest(other) != digest(control):
        raise SystemExit(f"The two rounds measured different frozen samples ({control} and {other}): pass --control.")
    sets = {"control": control, "gap-loop": GAP_PROOF, **{p: reflection_proof(p) for p in args.proof}}
    missing = [f"{label}: {path}" for label, path in sets.items() if not path.is_dir()]
    if missing:
        raise SystemExit("Missing scenario folders:\n  " + "\n  ".join(missing))
    return sets


def extra_args(config: str, kb: int, skills: int) -> list[str]:
    return {
        "router": ["--profile", "router"],
        "gaploop": ["--profile", "gaploop", "--kb-version", str(kb)],
        "reflection": ["--profile", "reflection", "--skills-version", str(skills)],
        "combined": ["--profile", "combined", "--kb-version", str(kb), "--skills-version", str(skills)],
    }[config]


class Installed:
    """The two learned files in place for the runs, and nothing else; taken out again whatever happens."""

    def __init__(self, args: argparse.Namespace) -> None:
        from ai_agent_service.components.context import skills as skill_book
        from ai_agent_service.config.config_manager import kb_dir

        runs = ROOT / "evaluation" / "runs"
        self.kb_source = runs / args.gap_round / "learned" / "kb" / f"v{args.kb_version}.jsonl"
        self.skills_source = runs / args.reflection_round / "learned" / "skills" / f"v{args.skills_version}.yaml"
        self.kb_target = kb_dir() / f"v{args.kb_version}.jsonl"
        self.skills_dir = skill_book.versions_dir()
        self.skills_target = self.skills_dir / f"v{args.skills_version}.yaml"
        self.added: list[Path] = []

    def __enter__(self) -> "Installed":
        for source in (self.kb_source, self.skills_source):
            if not source.is_file():
                raise SystemExit(f"{source} does not exist: the version must be the one its round learned")
        if self.kb_target.exists():
            # Knowledge versions are committed in data/kb since 2026-11-15: the one there must be the one learned.
            if not filecmp.cmp(self.kb_source, self.kb_target, shallow=False):
                raise SystemExit(f"{self.kb_target} differs from {self.kb_source}: not the version the round learned")
        else:
            shutil.copy2(self.kb_source, self.kb_target)
            self.added.append(self.kb_target)
        if not self.skills_dir.exists():
            self.skills_dir.mkdir(parents=True)
            self.added.append(self.skills_dir)
            (self.skills_dir / "active.json").write_text('{"version": 0}', encoding="utf-8")  # in force: still v0
        if self.skills_target.exists():
            if not filecmp.cmp(self.skills_source, self.skills_target, shallow=False):
                raise SystemExit(f"{self.skills_target} differs from {self.skills_source}")
        else:
            shutil.copy2(self.skills_source, self.skills_target)
            self.added.append(self.skills_target)
        return self

    def __exit__(self, *exc: object) -> None:
        for path in reversed(self.added):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="evaluation/runs/<name>/ holds every run of this measurement")
    p.add_argument("--gap-round", required=True)
    p.add_argument("--kb-version", type=int, required=True)
    p.add_argument("--reflection-round", required=True)
    p.add_argument("--skills-version", type=int, required=True)
    p.add_argument("--proof", action="append", default=[], choices=("budget", "warranty", "conduct"),
                   help="Reflection's proof sets (default: budget)")
    p.add_argument("--control", help="A frozen data/dev sample other than --gap-round's")
    p.add_argument("--runs", type=int, default=3, help="Fresh runs of every configuration on every set (k)")
    p.add_argument("--only-config", action="append", choices=CONFIGS, default=[], help="Run only these configurations")
    args = p.parse_args(argv)
    args.proof = args.proof or ["budget"]
    if args.runs < 2:
        raise SystemExit("--runs must be at least 2: one run a side cannot tell a change from noise")

    from ai_agent_service.components.improvement import skill_versions, versions
    from ai_agent_service.pipeline.improve.cli import _evaluate

    if versions.active() or skill_versions.active():
        raise SystemExit(f"The agent in force is not the original (knowledge v{versions.active()}, skills "
                         f"v{skill_versions.active()}): roll back first. Versions are chosen per run, never published.")
    sets = suite(args)
    folder = ROOT / "evaluation" / "runs" / args.name
    folder.mkdir(parents=True, exist_ok=True)
    configs = args.only_config or list(CONFIGS)
    plan = {
        "name": args.name, "started_at": datetime.now(timezone.utc).isoformat(), "runs": args.runs,
        "configs": {c: extra_args(c, args.kb_version, args.skills_version) for c in configs},
        "gap_round": args.gap_round, "kb_version": args.kb_version,
        "reflection_round": args.reflection_round, "skills_version": args.skills_version,
        "sets": {label: {"path": str(path.relative_to(ROOT)), "sha256": digest(path)} for label, path in sets.items()},
        "learn_sets": {"gap-loop": "data/gap-loop/learn/scenarios",
                       **{p: f"data/reflection/{p}/learn/scenarios" for p in args.proof}},
    }
    (folder / "ablation.plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    with Installed(args):
        for index in range(1, args.runs + 1):
            for config in configs:
                for label, path in sets.items():
                    out = folder / f"{config}-{label}-{index}"
                    print(f"== {out.name}", flush=True)
                    _evaluate(path, out, extra_args(config, args.kb_version, args.skills_version))
    print(f"\nDone. Verdict: python scripts/evaluation/ablation_verdict.py --name {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
