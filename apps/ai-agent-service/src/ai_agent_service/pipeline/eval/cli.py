"""The evaluation in one command. ``docs/design.md`` section 9.2 and Appendix A.

The organisers' form, one configuration to one trace file (their pack's
``README``, "Quy trình chấm chéo")::

    python run_eval.py --scenarios <dir> --config full --out full.jsonl
    python run_eval.py --scenarios <dir> --config baseline_no_memory --out baseline.jsonl

Without ``--config``, both configurations into one directory, then the
organisers' ``eval/reference_eval.py`` prints its table (the brief, C.4: one
command prints the metrics)::

    python run_eval.py --scenarios <dir>

The turns of a finished run labelled again with today's extractor and graded
the same way, without running the agent again (:mod:`.relabel`)::

    python run_eval.py --relabel evaluation/runs/<day>-work/<run> --out <dir>

Exit codes: 0 when every turn ran and was labelled; 1 when a failed turn, an
unlabelled turn, a failed ``after_call`` or a line outside the schema voids
the numbers (the traces are kept, no table is printed); 2 when the input or
the setup is wrong.

The speed and cost table of a finished run, free; with a new run it is printed after the metrics, and ``--sessions``
adds a load test, which spends model calls (:mod:`.performance`)::

    python run_eval.py --performance evaluation/runs/<day>-work/<run>
    python run_eval.py --scenarios <dir> --performance --sessions 1,3,5

The run uses a database of its own, the app's name plus ``_eval`` (or
``EVAL_DATABASE_URL``, whose name must end in ``_eval``), created on first use
and emptied per scenario. The advisor's model is ``agents.advisor`` in
``config/models.yaml`` unless ``--provider`` and ``--model`` say otherwise; it
runs as the product does, with one retry of a failed model call and no retry
of a write tool.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import traceback
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ...components.context import focus
from ...config.config_manager import ROOT, btc_data_dir
from ...llm.evaluation_budget import validate_ledger


def runs_dir() -> Path:
    """Where every run, the extractor's cache and the budget ledger are kept: ``evaluation/runs`` of the repository
    (not under git), or ``EVAL_RUNS_DIR``. An image has no ``evaluation/`` beside the service home, so there it is
    ``runs`` under the service home (``/app/agent/runs``)."""
    if os.environ.get("EVAL_RUNS_DIR"):
        return Path(os.environ["EVAL_RUNS_DIR"]).resolve()
    repository = ROOT.parents[1] if len(ROOT.parents) > 1 else None
    if repository is not None and (repository / "evaluation").is_dir():
        return repository / "evaluation" / "runs"
    return ROOT / "runs"


RUNS = runs_dir()
EXTRACTOR_CACHE = RUNS / "cache" / "extractor.json"

#: Extractor calls in flight at once; the provider's rate limiter paces them.
EXTRACTOR_CONCURRENCY = 4
#: Seconds one turn's labelling may take, its retry included (two attempts of 60 s, and the limiter's wait).
#: Past it the labelling stops with an error instead of waiting: eval2 (2026-11-07) waited over twenty minutes
#: on four calls whose connections the provider had closed. What was labelled stays in the cache for the rerun.
LABEL_TIMEOUT_S = 300
#: A line every this many labelled turns, so a long labelling shows it is moving.
LABEL_PROGRESS_EVERY = 200


@dataclass
class Layout:
    """Where one run writes: the trace of each configuration and what goes beside it."""

    directory: Path
    traces: dict[str, Path]
    #: Prefix of the side files: "" in a run directory, "<stem>." beside a single trace.
    prefix: str = ""

    def side(self, name: str) -> Path:
        return self.directory / f"{self.prefix}{name}"


@dataclass
class ConfigRun:
    rows: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)
    stopped: list[dict[str, str]] = field(default_factory=list)


def _levels(value: str) -> list[int]:
    levels = [int(part) for part in value.split(",")]
    if any(level < 1 for level in levels):
        raise argparse.ArgumentTypeError("a level is at least one session")
    return levels


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_eval.py", description="Run scenarios through the agent and write the organisers' trace.")
    parser.add_argument("--scenarios", type=Path, default=btc_data_dir() / "test_set" / "public_sample",
                        help="A directory of scenarios in the organisers' format (default: their public sample).")
    parser.add_argument("--config", choices=("full", "baseline_no_memory"),
                        help="One configuration. Without it, both, then the organisers' table.")
    parser.add_argument("--out", type=Path,
                        help="With --config, the trace file; without, the run's directory (default: evaluation/runs/<run id>).")
    parser.add_argument("--only", action="append", default=[], metavar="SCENARIO_ID",
                        help="Run only this scenario; repeat for more.")
    parser.add_argument("--warmup", type=int, default=3, help="Untraced turns before the first measured one (default 3).")
    parser.add_argument("--no-extract", action="store_true",
                        help="Skip the question and claim extractor: no model call for it, and RQR and HR come out empty.")
    parser.add_argument("--judge", action="store_true", help="Also run the BTC rubric judge; diagnostic, extra model cost, never changes the BTC score.")
    parser.add_argument("--judge-run", type=Path, metavar="RUN_DIR",
                        help="Run the rubric judge over a finished run's replies; the agent and the extractor do not run.")
    parser.add_argument("--judge-sample", type=Path, metavar="JUDGE_DIR",
                        help="Draw calls and criteria from a judged run into a blind sheet for people to grade; no model call.")
    parser.add_argument("--sample-size", type=int, default=20, help="With --judge-sample: (call, criterion) pairs to draw (default 20).")
    parser.add_argument("--judge-agreement", type=Path, metavar="SHEET_DIR",
                        help="Compare the people's verdicts in a --judge-sample sheet with the judge's: agreement and Cohen's kappa.")
    parser.add_argument("--relabel", type=Path, metavar="RUN_DIR",
                        help="Label a finished run's turns again with today's extractor and grade them; the agent does not run.")
    parser.add_argument("--asr", type=Path, help="ASR ground_truth.json or its directory; scores with main's unchanged scorer.")
    parser.add_argument("--asr-package", type=Path, help="Supplied manifest/audio/reference package; lossless private BTC-format adapter.")
    parser.add_argument("--asr-unit", choices=["montage", "segments"], default="montage")
    parser.add_argument("--asr-audio", type=Path, help="One unlabelled local audio file: transcript/timing only, WER/CER stay unmeasured.")
    parser.add_argument("--asr-hypotheses", type=Path, help="Existing hypotheses; no model/API calls.")
    parser.add_argument("--asr-transcribe", action="store_true", help="Explicitly decode existing audio with local ASR; never downloads weights.")
    parser.add_argument("--asr-model", default="zipformer-30m")
    parser.add_argument("--asr-denoiser", choices=["none", "rnnoise"], default="none")
    parser.add_argument("--asr-turns", action="store_true",
                        help="With --asr-transcribe: split each call by speaker into turns[] (idx, speaker A/C, start, end) "
                             "for the organisers' per-turn entity accuracy and diarization; implausible splits give no turns")
    parser.add_argument("--asr-entity-review", type=Path, help="Versioned canonical entity labels; pending review stays diagnostic, never self-approved.")
    parser.add_argument("--performance", nargs="?", const=True, type=Path, metavar="RUN_DIR",
                        help="Print the speed and cost table: of this run, or, given RUN_DIR, of a finished one (no model call).")
    parser.add_argument("--sessions", type=_levels, default=[], metavar="N,N,...",
                        help="With --performance: after the run, this many sessions at once, each level in turn; spends model calls.")
    parser.add_argument("--report", nargs="?", const="all", type=_sections, metavar="all|asr,agent,performance",
                        help="Print the report's tables (default all). With --run or --asr-run, from finished runs: no "
                             "model call. With --scenarios, of the run this command makes, as the Router column.")
    parser.add_argument("--run", action="append", default=[], type=_named_run, metavar="COLUMN=RUN_DIR",
                        help="With --report: a finished run as a column: router, subagent, gaploop, reflection or ab; repeat.")
    parser.add_argument("--asr-run", type=Path, metavar="RUN_DIR", help="With --report: a finished --asr run.")
    parser.add_argument("--kb-version", type=int, metavar="N",
                        help="Run on data/kb/v<N>.jsonl instead of config/knowledge.yaml's version: the GapLoop or Reflection column.")
    parser.add_argument("--provider", help="The advisor's provider, overriding config/models.yaml.")
    parser.add_argument("--model", help="The advisor's model, overriding config/models.yaml.")
    return parser


def _sections(value: str) -> tuple[str, ...]:
    from . import tables

    try:
        return tables.sections(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _named_run(value: str) -> tuple[str, Path]:
    from . import tables

    try:
        return tables.named_run(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _tables(args: argparse.Namespace) -> int:
    """``--report`` over finished runs: reads their files, spends nothing."""
    from . import tables

    runs = {name: directory.resolve() for name, directory in args.run}
    try:
        text = tables.render(args.report, runs, args.asr_run.resolve() if args.asr_run else None)
    except (OSError, ValueError) as error:
        print(error)
        return 2
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if (args.run or args.asr_run) and args.report is None:
        print("--run and --asr-run go with --report")
        return 2
    if args.report is not None:
        if args.run or args.asr_run:
            return _tables(args)
        if args.scenarios == btc_data_dir() / "test_set" / "public_sample" or args.config or args.relabel:
            print("--report needs finished runs (--run, --asr-run), or --scenarios and no --config to make one; "
                  "making one spends model calls.")
            return 2
    if args.kb_version is not None:
        from ...components.knowledge import corpus
        from ...config.config_manager import kb_dir

        if not corpus.version_file(kb_dir(), args.kb_version).is_file():
            print(f"No knowledge version {args.kb_version} in {kb_dir()}")
            return 2
        # In the environment, so the MCP servers this command starts read the same version.
        os.environ["KNOWLEDGE_VERSION"] = str(args.kb_version)
    from ...mcp.server_base import use_selector_loop_on_windows

    use_selector_loop_on_windows()
    if args.asr or args.asr_audio or args.asr_package:
        if args.relabel or args.config or args.judge or args.provider or args.model or args.no_extract:
            print("--asr is separate from agent/extractor evaluation")
            return 2
        from . import asr
        out = args.out or RUNS / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-asr")
        try:
            if sum(bool(x) for x in (args.asr, args.asr_audio, args.asr_package)) != 1:
                raise ValueError("Choose one ASR input mode")
            if args.asr_package:
                from .asr_package import prepare
                asr.private_output(out)
                source = prepare(args.asr_package, out / "input", unit=args.asr_unit, only=set(args.only) or None)
                result = asr.evaluate(source, args.asr_hypotheses, out / "result", model=args.asr_model,
                                      transcribe=args.asr_transcribe, entity_review=args.asr_entity_review, denoiser=args.asr_denoiser,
                                      turns=args.asr_turns)
                print(json.dumps({"status": result["status"], "main_scorer": result["main_scorer"],
                                  "entity_accuracy_a5": result.get("entity_accuracy_a5"), "out": str(out)}, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "COMPLETE" else 1
            if args.asr_audio:
                if args.asr or args.asr_hypotheses or args.asr_entity_review or not args.asr_transcribe:
                    raise ValueError("--asr-audio requires --asr-transcribe and no reference/hypotheses options")
                result = asr.audio_smoke(args.asr_audio, out, args.asr_model, args.asr_denoiser)
                print(json.dumps({k: result.get(k) for k in ("status", "WER", "CER")}, ensure_ascii=False, indent=2))
                print(f"Private evidence: {out}")
                return 0
            result = asr.evaluate(args.asr, args.asr_hypotheses, out, model=args.asr_model,
                                  transcribe=args.asr_transcribe, only=set(args.only) or None, entity_review=args.asr_entity_review, denoiser=args.asr_denoiser,
                                      turns=args.asr_turns)
        except (ValueError, OSError, RuntimeError, ImportError) as error:
            print(f"ASR setup error: {error}")
            return 2
        print(json.dumps({"status": result["status"], "main_scorer": result["main_scorer"],
                          "entity_accuracy_a5": result.get("entity_accuracy_a5"),
                          "diagnostics": result["diagnostics"], "out": str(out)}, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "COMPLETE" else 1
    if args.asr_hypotheses or args.asr_transcribe or args.asr_entity_review:
        print("ASR options require --asr")
        return 2
    if args.sessions and args.performance is not True:
        print("--sessions needs --performance without a run directory: it runs the agent")
        return 2
    if isinstance(args.performance, Path):
        from . import performance

        try:
            figures = performance.measure(args.performance.resolve())
        except (OSError, ValueError) as error:
            print(error)
            return 2
        print(performance.table(figures))
        return 0
    if bool(args.provider) != bool(args.model):
        print("--provider and --model go together")
        return 2
    if args.judge_sample or args.judge_agreement:
        from . import judge_agreement

        if args.judge_agreement:
            return judge_agreement.report(args.judge_agreement.resolve())
        out = (args.out or args.judge_sample / "human-review").resolve()
        return judge_agreement.draw(args.judge_sample.resolve(), out, size=args.sample_size)
    if args.judge_run:
        if args.relabel or args.no_extract or args.config or args.judge or args.provider or args.model or args.only:
            print("--judge-run judges a finished run's replies; agent, extractor and selection options are not supported")
            return 2
        from . import judge_agreement

        out = (args.out or RUNS / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-judge")).resolve()
        try:
            validate_ledger()
        except RuntimeError as error:
            print(error)
            return 2
        return asyncio.run(judge_agreement.judge_run(args.judge_run.resolve(), out, _judge()))
    if args.relabel:
        if args.no_extract or args.judge or args.provider or args.model or args.only:
            print("--relabel runs only the extractor; agent/selection options are not supported (--config is)")
            return 2
        from . import relabel

        out = (args.out or RUNS / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-relabel")).resolve()
        try:
            capped = validate_ledger()
        except RuntimeError as error:
            print(error)
            return 2
        _say_cap(capped)
        print(f"Relabel {args.relabel.resolve()} into {out}")
        try:
            extractor = _extractor()
        except (RuntimeError, ValueError) as error:
            print(f"Extractor setup error: {error}")
            return 2
        return asyncio.run(relabel.relabel(args.relabel.resolve(), out, extractor,
                                           (args.config,) if args.config else None))
    if not args.scenarios.is_dir():
        print(f"{args.scenarios} is not a directory")
        return 2
    if args.warmup < 0:
        print("--warmup must be nonnegative")
        return 2
    from . import scenarios

    ready, rejected = scenarios.load(args.scenarios, set(args.only) or None)
    if rejected or not ready:
        for item in rejected:
            print(f"Rejected {item.path.name}: {item.reason}")
        if not ready:
            print("No scenario to run")
        return 2
    args.prepared = ready
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    layout = _layout(args, run_id)
    try:
        capped = validate_ledger()
        prepare_output(layout)
    except (OSError, ValueError, RuntimeError) as error:
        print(error)
        return 2
    _say_cap(capped)

    # Imported here: the evaluation database must be chosen before anything opens a pool.
    from . import runner

    try:
        database = runner.use_evaluation_database()
    except RuntimeError as error:
        print(error)
        return 2
    os.environ["MCP_TRANSPORT"] = "stdio"
    os.environ["MCP_LOG_FILE"] = str(layout.side("mcp-servers.log"))
    print(f"Run {run_id}: database {database}, output {layout.directory}")
    try:
        return asyncio.run(_evaluate_locked(args, run_id=run_id, layout=layout, database=database))
    except Exception as error:
        layout.side("evaluation-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        path = layout.side("manifest.json")
        record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"run_id": run_id}
        record.update(status="INCOMPLETE", failure={"type": type(error).__name__})
        _write_json(path, record)
        print(f"Evaluation failed ({type(error).__name__}); see {layout.side('evaluation-error.log')}. No table.")
        return 1


def _say_cap(capped: bool) -> None:
    if not capped:
        print("EVAL_BUDGET_DB is not set: model calls have no spending cap.")


def _layout(args: argparse.Namespace, run_id: str) -> Layout:
    if args.config:
        name = "full.jsonl" if args.config == "full" else "baseline.jsonl"
        trace = (args.out or RUNS / run_id / name).resolve()
        return Layout(trace.parent, {args.config: trace}, prefix=f"{trace.stem}.")
    directory = (args.out or RUNS / run_id).resolve()
    return Layout(directory, {"full": directory / "full.jsonl", "baseline_no_memory": directory / "baseline.jsonl"})


def prepare_output(layout: Layout) -> None:
    """Refuse stale evidence before opening a database or paying for a model."""
    layout.directory.mkdir(parents=True, exist_ok=True)
    claim = layout.directory / ".eval-prepare.lock"
    # Created exclusively, then closed: Windows cannot delete a file that is still open.
    with claim.open("x", encoding="utf-8"):
        pass
    try:
        existing = (path for path in layout.directory.iterdir()
                    if path != claim and path.name.startswith(layout.prefix))
        if ((layout.directory / "run.lock").exists()
                or any(path.exists() for path in layout.traces.values()) or next(existing, None) is not None):
            only_lock = [path.name for path in layout.directory.iterdir() if path != claim] == ["run.lock"]
            raise ValueError(
                f"Output already contains only run.lock ({layout.directory}): a run stopped before its first turn, or is "
                "starting now. Choose a new --out, or delete the folder if no run is going."
                if only_lock else f"Output already contains run evidence: {layout.directory}. Choose a new --out.")
        with layout.side("run.lock").open("x", encoding="utf-8"):
            pass
    finally:
        claim.unlink()


async def _evaluate_locked(args, **kwargs) -> int:
    from . import runner

    async with runner.evaluation_lock():
        return await _evaluate(args, **kwargs)


async def _evaluate(args: argparse.Namespace, *, run_id: str, layout: Layout, database: str) -> int:
    from ...llm import decisions
    from ...mcp import client as mcp_client
    from . import report, runner, scenarios, trace

    started = datetime.now(timezone.utc)
    ready, rejected = (args.prepared, []) if hasattr(args, "prepared") else scenarios.load(args.scenarios, set(args.only) or None)
    for item in rejected:
        print(f"  rejected {item.path.name}: {item.reason}")
    if not ready:
        print(f"No scenario to run in {args.scenarios}" + (f" for {', '.join(args.only)}" if args.only else ""))
        return 2
    if rejected:
        print("Invalid scenario cohort; no model calls.")
        return 2
    frozen = report.freeze(ready, rejected, layout.side("scenarios"))
    ready = [replace(s, path=frozen / s.path.name) for s in ready]
    configs = list(layout.traces)
    _write_json(layout.side("manifest.json"), {"run_id": run_id, "status": "INCOMPLETE",
                "configs": {config: {"memory": config == "full"} for config in configs}, "database": database})
    runs: dict[str, ConfigRun] = {}
    found: dict[str, dict[str, int]] = {}
    extractor = None
    load: list[dict[str, Any]] = []
    try:
        rig = await runner.build(provider=args.provider, model=args.model)
        extractor = None if args.no_extract else _extractor()
        print(f"Advisor context: {'full' if focus.full() else 'focused'} (ADVISOR_CONTEXT, also read from .env)")
        print(f"Advisor {rig.provider}/{rig.advisor.model_name}; extractor "
              f"{extractor.model_name if extractor else 'off'}; {len(ready)} scenarios; {', '.join(configs)}")
        await runner.warm_up(rig, ready[0], args.warmup, print)
        for config in configs:
            print(f"{config}:")
            run = runs[config] = ConfigRun()
            for scenario in ready:
                result = await runner.run_scenario(rig, scenario, config, run_id=run_id, progress=print)
                run.rows += result.rows
                run.diagnostics += result.diagnostics
                run.usage += result.usage
                # Keep paid replies even if labelling or a later scenario fails unexpectedly.
                trace.write_jsonl(layout.traces[config], run.rows)
                trace.write_jsonl(layout.side("diagnostics.jsonl"), [d for r in runs.values() for d in r.diagnostics])
                _write_json(layout.side("usage.json"), {name: r.usage for name, r in runs.items()})
                if result.error:
                    run.stopped.append({"scenario_id": scenario.scenario_id, "error": result.error})
                    break
            if not run.stopped:
                integrity = report.trace_errors(frozen, run.rows, config)
                if len(run.rows) != len(run.diagnostics):
                    integrity.append("trace/diagnostic count mismatch")
                if integrity:
                    run.stopped.append({"scenario_id": ready[0].scenario_id, "error": "; ".join(integrity)})
            if extractor is not None and not run.stopped:
                await _label(run, extractor, ready)
            if args.judge and not run.stopped:
                from ...components.evaluation.judge import judge_calls, summarise, table

                judgments = await judge_calls(_judge(), ready, run.rows, config)
                trace.write_jsonl(layout.side(f"{config}.judge.jsonl"), judgments)
                print(table(summarise(judgments)))
            invalid = 0
            for row, diagnosis in zip(run.rows, run.diagnostics):
                errors = trace.schema_errors(row)
                if errors:
                    invalid += 1
                    diagnosis["schema_errors"] = errors
            trace.write_jsonl(layout.traces[config], run.rows)
            found[config] = report.problems(run.rows, run.diagnostics, schema_errors=invalid,
                                            rejected=len(rejected), scenario_errors=sum(
                                                item.get("stage") != "extraction" for item in run.stopped))
            print(f"  -> {layout.traces[config]}")
            if run.stopped:
                break
        advisor = {"provider": rig.provider, "model": rig.advisor.model_name}
        if args.sessions and not any(run.stopped for run in runs.values()):
            load = await runner.load_test(rig, ready, args.sessions, print)
            _write_json(layout.side("sessions.json"), load)
    finally:
        try:
            await mcp_client.close_all()
        finally:
            await decisions.close()

    trace.write_jsonl(layout.side("diagnostics.jsonl"), [d for run in runs.values() for d in run.diagnostics])
    trace.write_jsonl(layout.side("scenario-errors.jsonl"),
                      [{"config": config, **error} for config, run in runs.items() for error in run.stopped])
    _write_json(layout.side("usage.json"), {config: run.usage for config, run in runs.items()})
    record = report.manifest(
        run_id=run_id, started=started, scenarios_dir=args.scenarios, scenarios=ready, rejected=rejected,
        configs=configs, advisor=advisor,
        extractor={"model": extractor.model_name, **extractor.stats()} if extractor else None,
        warmup=args.warmup, database=database, found=found,
    )
    record["status"] = "INCOMPLETE" if report.blocking(found) else "TRACED"
    _write_json(layout.side("manifest.json"), record)

    print()
    for config, counts in found.items():
        print(f"{config}: " + ", ".join(f"{name} {n}" for name, n in counts.items()))
    if args.no_extract:
        print("Extractor off: questions and claims are empty, so RQR and HR are not measured.")
    voided = report.blocking(found)
    if voided:
        print("Not scored: " + ", ".join(f"{name} {n}" for name, n in voided.items())
              + f". The traces are kept in {layout.directory}; see diagnostics.jsonl and scenario-errors.jsonl.")
        return 1
    if args.config:
        record["status"] = "COMPLETE"
        _write_json(layout.side("manifest.json"), record)
        return 0
    retrieval = _retrieval(layout.side("rag"))
    code, table = report.grade(frozen, full=layout.traces["full"], baseline=layout.traces["baseline_no_memory"],
                               out=layout.side("report.json"), rag=layout.side("rag") / "rag_results.json")
    if code != 0:
        record.update(status="INCOMPLETE", failure={"stage": "scoring", "exit_code": code})
        _write_json(layout.side("manifest.json"), record)
        layout.side("scoring-error.txt").write_text(table + "\n", encoding="utf-8")
        print(f"Scoring failed (exit {code}); see {layout.side('scoring-error.txt')}. No table.")
        return 1
    graded = json.loads(layout.side("report.json").read_text(encoding="utf-8"))
    failures = report.errors(graded, [d for run in runs.values() for d in run.diagnostics])
    trace.write_jsonl(layout.side("errors.jsonl"), failures)
    table = f"{table}\n\n{retrieval}"
    if args.performance:
        from . import performance

        figures = performance.measure(layout.directory)
        figures["sessions"] = load
        _write_json(layout.side("performance.json"), figures)
        table = f"{table}\n\n{performance.table(figures, load)}"
    if args.report:
        from . import tables

        table = f"{table}\n\n{tables.render(args.report, {'router': layout.directory})}"
    layout.side("table.txt").write_text(table + "\n", encoding="utf-8")
    record["status"] = "COMPLETE"
    _write_json(layout.side("manifest.json"), record)
    print()
    print(table)
    print(f"{len(failures)} failed calls listed in {layout.side('errors.jsonl')}")
    return code


def _retrieval(into: Path) -> str:
    """Section 7.4 in the same run: the 60 labelled questions through the knowledge base the calls used."""
    from ...components import knowledge
    from ...mcp.servers import btc
    from . import rag

    kb = knowledge.build()
    results, rows = rag.run(kb, rag.questions(), on=btc.reference_date())
    return rag.table(rag.measure(results, rows, into), mode=kb.mode)


def _judge() -> Any:
    """The rubric judge on the extractor's model (``agents.extractor`` in models.yaml), costed as ``rubric_judge``."""
    from ...components.evaluation.judge import BtcJudge
    from ...config.config_manager import get_models_config
    from ...llm.factory import LLMFactory

    return BtcJudge(LLMFactory.create_llm(get_models_config().agent_llm_config("extractor"), agent_name="rubric_judge"))


def _extractor() -> Any:
    from ...components.evaluation.scorers import Extractor
    from ...config.config_manager import get_models_config
    from ...llm.factory import LLMFactory

    config = get_models_config().agent_llm_config("extractor")
    return Extractor(LLMFactory.create_llm(config, agent_name="extractor"), model_name=config["model"],
                     cache_path=EXTRACTOR_CACHE)


def call_context(cohort: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """``today`` and ``crm_history`` of every call of *cohort* (planned scenarios), for the extractor.

    The day is the call's own (``call_date`` or the days after the one before), so a time said in words can be
    written as the scenario writes ``callback_at``; the CRM history is the ``seed_history`` the profile held.
    """
    context = {}
    for scenario in cohort or ():
        for plan in scenario.calls:
            context[(scenario.scenario_id, plan.name)] = {
                "today": plan.on,
                "crm_history": [{"date": s.day, "channel": s.channel, "summary": s.summary, "outcome": s.outcome,
                                 "facts": dict(s.facts)} for s in plan.seed],
            }
    return context


async def _label(run: ConfigRun, extractor: Any, cohort: Any = None) -> None:
    """Fill ``questions``, ``claims`` and ``facts_used`` of every row, after the turns ran, so no extractor call
    ever queues in front of a timed turn.

    From the second call of a scenario each turn is labelled with the earlier calls of the same configuration
    (BTC's ``facts_used`` is a slot from the previous session). ``facts_used`` is what the extractor saw reused,
    then the slots of the brief lines the reply cited, each once. The items the labels came from go to the
    turn's diagnosis, so whoever checks the extractor can see each label's quote.
    """
    from ...components.evaluation import scorers
    from . import trace

    if len(run.rows) != len(run.diagnostics):
        raise ValueError("Every trace turn needs exactly one diagnostic before labelling")
    # A burst can reserve the remaining cap before any in-flight usage settles.
    gate = asyncio.Semaphore(1 if os.environ.get("EVAL_BUDGET_DB") else EXTRACTOR_CONCURRENCY)
    history = scorers.previous_sessions(run.rows)
    context = call_context(cohort)
    halted = False
    finished = 0

    async def one(index: int, row: dict[str, Any], diagnosis: dict[str, Any]) -> None:
        nonlocal halted, finished
        call = context.get((row["scenario_id"], row["call"]), {})
        data = scorers.turn_input(row["agent_text"], row["tool_calls"], history.get(index),
                                  today=call.get("today"), crm_history=call.get("crm_history"))
        async with gate:
            if halted:
                return
            try:
                labels = await asyncio.wait_for(extractor.label(data), LABEL_TIMEOUT_S)
            except asyncio.TimeoutError:
                labels = {**scorers._labels([], 0, 0), "error": f"extractor gave no answer in {LABEL_TIMEOUT_S} s"}
            finished += 1
            if finished % LABEL_PROGRESS_EVERY == 0:
                print(f"  labelled {finished}/{len(run.rows)} turns", flush=True)
            if labels.get("error"):
                # Under a spending cap the rest is not paid for; without one, the other turns are labelled, so a
                # rerun repeats only those that failed (the rest are in the cache) and one bad turn of 3.747 does
                # not cost the other 3.746. The table is withheld either way while a turn is unlabelled.
                halted = bool(os.environ.get("EVAL_BUDGET_DB"))
                run.stopped.append({"scenario_id": row["scenario_id"], "stage": "extraction", "error": labels["error"]})
        row["questions"], row["claims"] = labels["questions"], labels["claims"]
        row["facts_used"] = trace.merged_facts_used(labels["facts_used"], row["facts_used"])
        diagnosis["extraction_items"] = labels["items"]
        if labels["dropped"]:
            diagnosis["extraction_dropped_items"] = labels["dropped"]
        if labels["changed"]:
            diagnosis["extraction_changed_items"] = labels["changed"]
        if labels.get("error"):
            diagnosis["extraction_error"] = labels["error"]
        if labels.get("attempt_errors"):
            diagnosis["extraction_attempt_errors"] = labels["attempt_errors"]
        if labels.get("recovered_errors"):
            diagnosis["extraction_recovered_errors"] = labels["recovered_errors"]

    try:
        await asyncio.gather(*(one(index, row, diagnosis)
                               for index, (row, diagnosis) in enumerate(zip(run.rows, run.diagnostics))))
    finally:
        if hasattr(extractor, "flush"):
            await extractor.flush()
    print(f"  labelled {sum('extraction_items' in d for d in run.diagnostics)} turns ({extractor.stats()})")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
