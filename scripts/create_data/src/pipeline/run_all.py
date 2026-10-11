"""Run the whole pipeline in order (each stage is also runnable on its own).

    python -m src.pipeline.run_all --limit 2 --skip-audio      # smoke test (~a few API calls)
    python -m src.pipeline.run_all --limit 120 --audio-limit 60  # ≈ 250 transcripts (2–3 calls each)
    python -m src.pipeline.run_all --plan-only --limit 120      # labels + oracle check, zero API calls
    python -m src.pipeline.run_all --limit 120 --asr-dialogues 24  # + team ASR test set (TTS)

``--resume`` reuses files on disk and the model cache. ``--only-failed`` deletes
transcripts/judgments that failed the last validation and regenerates just those.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from src.utils.paths import CONVERSATIONS_DIR, JUDGMENTS_DIR, ROOT, VALIDATION_JSON
from src.utils.quota import EXIT_DAILY_LIMIT

STAGES = [
    "build_catalog",                 # 1  validate source inputs (offline)
    "generate_scenarios",            # 2  plan labels + LLM customer language
    "generate_dialogue",             # 3  one reference transcript per call
    "simulate_replays",              # 4  BTC simulator × 3 seeds
    "validate_rules",                # 5  official reference_eval on each reference transcript (must be perfect)
    "llm_judge",                     # 6  BTC rubric J01–J12
    "build_ground_truth",            # 7  test_set/ + oracle & reference traces + briefs + tool audit
    "export_manual_review",          # 8  human gate CSV
    "synthesize_scenario_audio",     # 9  ElevenLabs per-turn WAV
    "build_asr_testset",             # 10 team ASR set (only with --asr-dialogues N)
    "eval_rag",                      # 11 Recall@3/@5 baseline on rag/qa_labeled.json (offline)
    "summarize_dataset",             # 12 coverage JSON/CSV/dashboard
    "report",                        # 13 Markdown + HTML report
]
# --limit counts scenarios; later stages work on whatever conversations exist.
LIMITED = {"generate_scenarios", "generate_dialogue"}
RESUMABLE = {"generate_scenarios", "generate_dialogue", "llm_judge", "synthesize_scenario_audio"}


def drop_failed() -> None:
    """Delete transcripts + judgments of the conversations that failed the last validation."""
    rows = json.loads(VALIDATION_JSON.read_text(encoding="utf-8"))
    for row in rows:
        if row.get("validator_pass"):
            continue
        cid = row.get("conversation_id", row["scenario_id"])
        for folder in (CONVERSATIONS_DIR, JUDGMENTS_DIR):
            (folder / f"{cid}.json").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=48, help="scenarios to generate (each has 2–3 calls)")
    parser.add_argument("--audio-limit", type=int, default=100, help="scenarios to synthesize audio for")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--only-failed", action="store_true")
    parser.add_argument("--skip-audio", action="store_true")
    parser.add_argument("--plan-only", action="store_true", help="labels + oracle check only (no API calls)")
    parser.add_argument("--asr-dialogues", type=int, default=0, help="build a team ASR set of N dialogues (TTS)")
    args = parser.parse_args()

    if args.plan_only:
        subprocess.run([sys.executable, "-m", "src.pipeline.generate_scenarios", "--limit", str(args.limit),
                        "--plan-only"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "-m", "src.pipeline.build_ground_truth", "--scenarios", "output/plans",
                        "--out", "output/plans"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "-m", "src.pipeline.eval_rag"], cwd=ROOT, check=True)
        return
    if args.only_failed:
        if not VALIDATION_JSON.exists():
            parser.error("--only-failed requires output/reports/validation.json")
        drop_failed()

    for stage in STAGES:
        if stage == "synthesize_scenario_audio" and args.skip_audio:
            continue
        if stage == "build_asr_testset" and not args.asr_dialogues:
            continue
        if stage == "export_manual_review" and args.only_failed:
            continue  # keep the reviewer's existing CSV
        command = [sys.executable, "-m", f"src.pipeline.{stage}"]
        if stage in LIMITED and not args.only_failed:
            command += ["--limit", str(args.limit)]
        if stage == "synthesize_scenario_audio":
            command += ["--limit", str(args.audio_limit)]
        if stage == "build_asr_testset":
            command += ["--limit", str(args.asr_dialogues)] + (["--text-only"] if args.skip_audio else [])
        if stage in RESUMABLE and (args.resume or args.only_failed):
            command.append("--resume")
        print(f"\n==> {stage}", flush=True)
        code = subprocess.run(command, cwd=ROOT).returncode
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
