"""The commands of ``run_eval.py``. ``evaluate`` runs the whole evaluation; the others are its tools.

| Command | Does | Model? |
|---|---|---|
| ``evaluate`` | Prepare → Run (full + baseline) → Collect → Score, one folder per step (:mod:`src.pipeline`) | yes |
| ``prepare`` | Step 1 only: pin the inputs and check them; the gate before paying for a run | no |
| ``simulate`` | The BTC customer simulator drives the agent instead of fixed turns; 3 seeds | yes |
| ``history`` | Every run in ``runs/`` and its scores | no |
| ``langfuse-log`` | A finished run's tokens, cost and scores to Langfuse | no |
| ``data-import`` | data-generation's scenarios → a new registered dataset in ``datasets/`` | no |
| ``data-check`` | The registered datasets and ASR sets are valid | no |
| ``label-check`` | A dataset's prices and stock against BTC's mock | no |
| ``asr-build`` / ``asr`` | pin data-generation's ASR ground truth / heard by an engine, understood by the agent, BTC ``wer_cer`` | engine + ``agents.memory`` |
| ``rag-recall`` | Recall@3/@5 of the agent's ``kb_search`` on BTC's 60 questions | no |
| ``rag-offline`` | The same on the agent's knowledge base in-process: no database (``make eval``) | no |

Exit codes: 0 all passed, 1 the agent failed a check, 2 evidence missing (INCOMPLETE), 3 the pipeline stopped.
"""
import argparse
from datetime import date, datetime
import json
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
RUNS = HARNESS / "runs"


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage()
        self.exit(3, f"{self.prog}: error: {message}\n")


def build_parser():
    from src.steps.prepare.prepare import DEFAULT_DATASET

    parser = Parser(description="Evaluate the team's agent the way BTC scores it")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    evaluate = commands.add_parser("evaluate", help="The whole evaluation: prepare, run, collect, score")
    prepare = commands.add_parser("prepare", help="Step 1 only: pinned inputs and preflight; no model")
    for sub, default in ((evaluate, "runs/<date-time>"), (prepare, "runs/<date-time>-prepare")):
        sub.add_argument("--out", type=Path, help=f"A new run directory (default: {default})")
        sub.add_argument("--dataset-id", default=DEFAULT_DATASET, help=f"Registered dataset (default: {DEFAULT_DATASET})")
        sub.add_argument("--only", action="append", default=[], metavar="SCENARIO_ID", help="Run one scenario; repeat for more")
        sub.add_argument("--level", choices=("M1", "M2"), help="Scenarios of this level only; without it a mixed set runs once per level")
        sub.add_argument("--limit", type=int, help="The first N selected scenarios")
        sub.add_argument("--extractor-calls", type=int, help="Budget of extraction calls (default: one per planned turn)")
        sub.add_argument("--advisor", metavar="PROVIDER:MODEL", help="Advisor model, e.g. openai:gpt-4.1-mini (default: config/models.yaml)")
        sub.add_argument("--extractor", metavar="PROVIDER:MODEL", help="Extraction model (default: openai:gpt-4.1-mini when OPENAI_API_KEY is set)")
    sim = commands.add_parser("simulate", help="The BTC customer simulator drives the agent; full vs baseline, 3 seeds")
    sim.add_argument("--out", type=Path, help="A new run directory (default: runs/<date-time>-simulate)")
    sim.add_argument("--only", action="append", default=[], metavar="SCENARIO_ID", help="Simulate one scenario; repeat for more")
    sim.add_argument("--dataset-id", required=True, help="Registered dataset ID from datasets/registry.json")
    sim.add_argument("--level", choices=("M1", "M2"), required=True, help="One level per run")
    sim.add_argument("--limit", type=int, help="The first N selected scenarios")
    sim.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2], help="Seeds (the organisers' check pins three)")
    sim.add_argument("--advisor", metavar="PROVIDER:MODEL", help="Advisor model (default: config/models.yaml)")
    sim.add_argument("--simulator-model", help="Model that plays the customer (default: gpt-4.1-mini)")
    commands.add_parser("history", help="Every evaluation run in runs/ and its scores; no model")
    spend = commands.add_parser("langfuse-log", help="Log a finished run's spend (tokens, USD) and scores to Langfuse")
    spend.add_argument("--run", required=True, type=Path, help="The run folder, e.g. evaluation/agent-evaluation/runs/<run>")
    spend.add_argument("--force", action="store_true", help="Log again even if already logged")
    data_import = commands.add_parser("data-import", help="data-generation's scenarios as a new registered dataset; no model")
    data_import.add_argument("--name", required=True, help="New dataset name, e.g. create-data-diagnostic-v5 (never overwritten)")
    data_import.add_argument("--source", type=Path, help="Scenario folder (default: evaluation/data-generation/output/scenarios)")
    data = commands.add_parser("data-check", help="Check the registered datasets and ASR sets; no model")
    data.add_argument("--root", type=Path, default=HARNESS / "datasets")
    data.add_argument("--set", help="Inspect one registered dataset ID")
    labels = commands.add_parser("label-check", help="A dataset's prices and stock against BTC's mock; no model")
    labels.add_argument("--dataset-id", default=DEFAULT_DATASET)
    asr_build = commands.add_parser("asr-build", help="Pin data-generation's ASR ground truth and audio as a new set; no model")
    asr_build.add_argument("--set-id", required=True, help="New set directory name under datasets/, e.g. asr-team-v3 (never overwritten)")
    asr_build.add_argument("--kind", choices=("turns", "dialogues"), default="turns",
                           help="turns: one customer turn per clip (asr_reference/); dialogues: whole two-speaker calls (asr_test/)")
    asr_build.add_argument("--source", type=Path, help="A data-generation ground_truth.json (default: the one of --kind)")
    asr_build.add_argument("--restore", action="store_true", help="Copy back the audio of an existing set (a fresh clone), hash-checked")
    asr = commands.add_parser("asr", help="ASR set heard by an engine, understood by the agent's pipeline, scored by BTC wer_cer")
    asr.add_argument("--set", default="asr-team-v2", help="ASR set under datasets/")
    asr.add_argument("--out", type=Path, help="New output directory (default: runs/asr/<time>-<engine>)")
    asr.add_argument("--engine", default="agent",
                     help="agent (the agent's ASR client and voice.asr model), agent:<model>, openai:<model> "
                          "(gpt-4o-transcribe, gpt-4o-transcribe-diarize…), file:<hypotheses.json>")
    asr.add_argument("--url", default="http://127.0.0.1:8500", help="ASR service the agent's client calls (ASR_URL)")
    asr.add_argument("--understanding", choices=("model", "rules"), default="model",
                     help="MemoryAgent with its model (agents.memory in models.yaml), or its rules (no model call)")
    asr.add_argument("--diarizer", choices=("auto", "native", "sherpa", "none"), default="auto",
                     help="Speaker turns for a dialogue set: the engine's own (native), or sherpa-onnx")
    asr.add_argument("--segmentation", type=Path, help="sherpa: pyannote segmentation ONNX model")
    asr.add_argument("--embedding", type=Path, help="sherpa: speaker embedding ONNX model")
    asr.add_argument("--limit", type=int, help="The first N items only (a smoke test)")
    asr.add_argument("--no-hotwords", action="store_true", help="Do not send the agent's hotwords")
    rag = commands.add_parser("rag-recall", help="The agent's kb_search on BTC's 60 questions; retrieval only")
    rag.add_argument("--out", required=True, type=Path, help="New output directory")
    rag.add_argument("--on", default="2026-10-15", help="Call date for versioned policy (YYYY-MM-DD)")
    offline = commands.add_parser("rag-offline", help="The agent's knowledge base on BTC's 60 questions; no model, no database")
    offline.add_argument("--k", type=int, default=5)
    offline.add_argument("--output", type=Path, help="Report file (default: reports/generated/evaluation.json)")
    return parser


def evaluate_or_prepare(args):
    from src.pipeline import evaluate, levels, prepare

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = args.out or RUNS / (stamp + ("-prepare" if args.command == "prepare" else ""))
    # A run holds one level. Without --level, a set that mixes levels runs
    # once per level, into sibling folders <out>-M1, <out>-M2.
    try:
        selected = [args.level] if args.level else levels(args.dataset_id, set(args.only))
    except (OSError, ValueError, KeyError) as exc:
        print(f"{args.command.capitalize()} error: {type(exc).__name__}: {exc}")
        return 3
    split = len(selected) > 1
    codes = []
    for level in selected:
        out = base.with_name(f"{base.name}-{level}") if split else base
        if split:
            print(f"\n=== Level {level} -> {out.resolve()} ===")
        options = dict(only=set(args.only), extractor_calls=args.extractor_calls, dataset_id=args.dataset_id,
                       level=level, limit=args.limit, advisor=args.advisor, extractor_model=args.extractor)
        if args.command == "prepare":
            try:
                prepared = prepare(out, **options)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                print(f"Prepare error: {type(exc).__name__}: {exc}")
                codes.append(3)
                continue
            print(json.dumps(prepared, ensure_ascii=False, indent=2))
            print("Prepared inputs in", out.resolve())
            codes.append(0 if prepared["execution_gate"]["allowed"] else 2)
            continue
        report = evaluate(out, **options)
        print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
        print("Run written to", out.resolve())
        for table in (out / "scored" / "scorer.stdout.txt", out / "scored" / "run-summary.txt"):
            if table.is_file():
                print(table.read_text(encoding="utf-8"))
        status = (report["stages"][-1].get("status") or {}) if report["stages"] else {}
        codes.append(3 if report["pipeline_error"] else 1 if status.get("verdict") == "FAIL"
                     else 2 if status.get("completeness") == "INCOMPLETE" else 0)
    # The worst outcome: an error, then a failed check, then missing evidence.
    return next((code for code in (3, 1, 2) if code in codes), 0)


def simulate(args):
    from src.simulation.simulate import simulate as run_simulation

    out = args.out or RUNS / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-simulate")
    try:
        report = run_simulation(out, only=set(args.only), dataset_id=args.dataset_id, level=args.level, limit=args.limit,
                                seeds=tuple(args.seeds), advisor=args.advisor, model=args.simulator_model)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(f"Simulate error: {type(exc).__name__}: {exc}")
        return 3
    print(report["table"])
    print("Run written to", Path(report["out"]).resolve())
    return 0 if report["summary"]["execution_complete"] else 2


def data_import(args):
    from src.datasets import normalize_create_data

    # data-generation already writes BTC's payment words; --payment-vocabulary also maps any old "chuyen_khoan".
    normalize_create_data.main(["--name", args.name, "--payment-vocabulary"] + (["--source", str(args.source)] if args.source else []))
    return 0


def data_check(args):
    from src.datasets.registry import inspect

    try:
        report = inspect(args.root, only=args.set)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("Dataset check error:", exc)
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report.get("issues") or report.get("execution_gate", {}).get("allowed") is False else 0


def label_check(args):
    from src.datasets.validate_labels import HERE, check

    checked, problems = check(HERE / "datasets" / args.dataset_id / "scenarios")
    print(f"{args.dataset_id}: {checked} price/stock checks, {len(problems)} label problems")
    for row in problems[:40]:
        print("  ", *row)
    return 2 if problems else 0


def asr_build(args):
    from src.services.asr import build_set, restore_audio

    try:
        if args.restore:
            report = restore_audio(args.set_id)
            print(json.dumps({**report, "missing_or_changed": report["missing_or_changed"][:20]}, ensure_ascii=False, indent=2))
            return 2 if report["missing_or_changed"] else 0
        report = build_set(args.set_id, kind=args.kind, source=args.source)
    except (OSError, ValueError, KeyError) as exc:
        print("ASR set not built:", exc)
        return 3
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))
    print("Set written to", HARNESS / "datasets" / args.set_id)
    return 0


def asr(args):
    from src.services.asr.evaluate import evaluate

    label = args.engine.replace(":", "-").replace("/", "-").replace("\\", "-")[:40]
    out = args.out or RUNS / "asr" / f"{datetime.now():%Y%m%d-%H%M%S}-{label}"
    try:
        report = evaluate(out, set_id=args.set, engine=args.engine, url=args.url, understanding=args.understanding,
                          diarizer=args.diarizer, segmentation=args.segmentation, embedding=args.embedding,
                          limit=args.limit, hotwords=not args.no_hotwords)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print("ASR evaluation incomplete:", exc)
        return 3
    print(json.dumps({key: report[key] for key in ("set_id", "kind", "engine", "diarizer", "understanding", "n_items",
                                                   "rtf_mean", "raw", "lexicon", "entities_not_from_speech")},
                     ensure_ascii=False, indent=2))
    print("Report written to", (out / "report.json").resolve())
    return 0


def rag_recall(args):
    from src.services.rag import run

    try:
        date.fromisoformat(args.on)
        result = run(args.out, on=args.on)
    except (OSError, ValueError, TypeError, RuntimeError, AssertionError) as exc:
        print("RAG Recall incomplete:", exc)
        return 3
    print(json.dumps({key: value for key, value in result["metrics"].items() if key != "rows"}, ensure_ascii=False, indent=2))
    print("Report written to", (args.out / "report.json").resolve())
    return 0


def rag_offline(args):
    from src.services.rag_offline import DEFAULT_OUTPUT, run

    output = args.output or DEFAULT_OUTPUT
    report = run(args.k, output)
    print(json.dumps(report["retrieval"], ensure_ascii=False, indent=2))
    print("Wrote", output)
    return 0


def history(args):
    from src.reports.history import render_history

    print(render_history(RUNS))
    return 0


def langfuse_log(args):
    from src.services.agent_settings import log_spend

    print(log_spend(args.run, force=args.force))
    return 0


COMMANDS = {"evaluate": evaluate_or_prepare, "prepare": evaluate_or_prepare, "simulate": simulate, "history": history,
            "langfuse-log": langfuse_log, "data-import": data_import, "data-check": data_check, "label-check": label_check,
            "asr-build": asr_build, "asr": asr, "rag-recall": rag_recall,
            "rag-offline": rag_offline}


def main(argv=None):
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)
