"""Run the whole pipeline in order (each stage is also runnable on its own).

    python -m src.pipeline.run_all --plan-only                          # labels + oracle check, zero API calls
    python -m src.pipeline.run_all --limit 2 --advanced-limit 2 --skip-audio   # smoke test (a few API calls)
    python -m src.pipeline.run_all --fresh                              # everything from scratch: 150 BTC + 68 advanced
    python -m src.pipeline.run_all --personas advanced                  # only the team's personas
    python -m src.pipeline.run_all --resume                             # continue after a quota stop
    python -m src.pipeline.run_all --asr-dialogues 24                   # + team ASR test set (TTS)
    python -m src.pipeline.run_all --seed v5 --plan-only                # write into data/seed-v5/ (default seed-dev)

``--resume`` reuses files on disk and the model cache. ``--only-failed`` deletes
transcripts/judgments that failed the last validation and regenerates just those.
New synthetic CRM customers are a separate step (``generate_synthetic_customers``),
since they change the CRM every scenario is planned on.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from src.utils.dataset import Dataset
from src.utils.paths import OUTPUT_DIR, PLAN_PREVIEW_DIR, ROOT, SEED, SEED_ENV, VALIDATION_JSON
from src.utils.quota import EXIT_DAILY_LIMIT

STAGES = [
    "build_catalog",                 # 1  catalogue consistent (offline)
    "generate_scenarios",            # 2  plan labels + LLM customer language
    "generate_dialogue",             # 3  one reference transcript per call
    "simulate_replays",              # 4  BTC simulator × 3 seeds
    "validate_rules",                # 5  official reference_eval on each reference transcript (must be perfect)
    "llm_judge",                     # 6  BTC rubric J01–J12
    "build_ground_truth",            # 7  oracle trace_log per call + official reports + tool audit
    "export_manual_review",          # 8  human gate CSV
    "synthesize_scenario_audio",     # 9  ElevenLabs per-turn WAV, up to the target hours
    "build_asr_testset",             # 10 team ASR set (only with --asr-dialogues N)
    "eval_rag",                      # 11 Recall@3/@5 baseline on rag/qa_labeled.json (offline)
    "summarize_dataset",             # 12 coverage JSON/CSV/dashboard + M2 targets
    "report",                        # 13 Markdown + HTML report
]
RESUMABLE = {"generate_scenarios", "generate_dialogue", "llm_judge", "synthesize_scenario_audio"}


def drop_failed() -> None:
    """Delete transcripts + judgments of the conversations that failed the last validation."""
    dataset = Dataset()
    for row in json.loads(VALIDATION_JSON.read_text(encoding="utf-8")):
        if row.get("validator_pass") or "conversation_id" not in row:
            continue
        dataset.conversation_file(row["conversation_id"]).unlink(missing_ok=True)
        dataset.judgment_file(row["conversation_id"]).unlink(missing_ok=True)


def run(stage: str, *options: str, check: bool = False) -> int:
    print(f"\n==> {stage} {' '.join(options)}".rstrip(), flush=True)
    # UTF-8 mode: the stages print Vietnamese, which a Windows console's code page cannot encode.
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run([sys.executable, "-m", f"src.pipeline.{stage}", *options], cwd=ROOT, check=check,
                          env=env).returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", help=f"the output folder data/seed-<SEED>/ (default: ${SEED_ENV} or dev)")
    parser.add_argument("--personas", default="all", choices=("btc", "advanced", "all"))
    parser.add_argument("--limit", type=int, default=150, help="BTC-persona scenarios (each has 1–3 calls)")
    parser.add_argument("--advanced-limit", type=int, help="advanced-persona scenarios (default: their targets' sum)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="delete every generated scenario and transcript first")
    parser.add_argument("--only-failed", action="store_true")
    parser.add_argument("--skip-audio", action="store_true")
    parser.add_argument("--plan-only", action="store_true", help="labels + oracle check only (no API calls)")
    parser.add_argument("--asr-dialogues", type=int, default=0, help="build a team ASR set of N dialogues (TTS)")
    args = parser.parse_args()
    if args.seed and args.seed != SEED:
        # Paths are fixed when src.utils.paths is imported: run again with the seed set, for this and every stage.
        argv = [a for i, a in enumerate(sys.argv[1:]) if a != "--seed" and (i == 0 or sys.argv[i] != "--seed")
                and not a.startswith("--seed=")]
        sys.exit(subprocess.run([sys.executable, "-m", "src.pipeline.run_all", *argv], cwd=ROOT,
                                env={**os.environ, SEED_ENV: args.seed}).returncode)
    print(f"Output: {OUTPUT_DIR}", flush=True)
    personas = ["--personas", args.personas, "--limit", str(args.limit)]
    if args.advanced_limit is not None:
        personas += ["--advanced-limit", str(args.advanced_limit)]

    if args.plan_only:
        run("generate_scenarios", *personas, "--plan-only", check=True)
        run("build_ground_truth", "--root", str(PLAN_PREVIEW_DIR), check=True)
        run("eval_rag", "--root", str(PLAN_PREVIEW_DIR), check=True)
        return
    if args.only_failed:
        if not VALIDATION_JSON.exists():
            parser.error("--only-failed requires <seed>/reports/validation.json")
        drop_failed()

    for stage in STAGES:
        if stage == "synthesize_scenario_audio" and args.skip_audio:
            continue
        if stage == "build_asr_testset" and not args.asr_dialogues:
            continue
        if stage == "export_manual_review" and args.only_failed:
            continue  # keep the reviewer's existing CSV
        if stage == "generate_scenarios" and args.only_failed:
            continue  # only transcripts are regenerated; new scenarios would come with the default --limit
        options: list[str] = []
        if stage == "generate_scenarios" and not args.only_failed:
            options += personas + (["--fresh"] if args.fresh else [])
        if stage == "build_asr_testset":
            options += ["--limit", str(args.asr_dialogues)] + (["--text-only"] if args.skip_audio else [])
        if stage in RESUMABLE and (args.resume or args.only_failed):
            options.append("--resume")
        code = run(stage, *options)
        if code == EXIT_DAILY_LIMIT:
            # The stage already said why and saved its progress; later stages need its output.
            print(f"\nPipeline paused at {stage}: daily request budget used up. "
                  "Run the same command with --resume to continue.", flush=True)
            raise SystemExit(EXIT_DAILY_LIMIT)
        if code != 0:
            raise SystemExit(f"Stage {stage} failed (exit {code}); see its output above. "
                             "Fix the cause, then rerun with --resume.")


if __name__ == "__main__":
    main()
