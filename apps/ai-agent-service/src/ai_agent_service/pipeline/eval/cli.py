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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ...config.config_manager import ROOT, btc_data_dir


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
    parser.add_argument("--relabel", type=Path, metavar="RUN_DIR",
                        help="Label a finished run's turns again with today's extractor and grade them; the agent does not run.")
    parser.add_argument("--provider", help="The advisor's provider, overriding config/models.yaml.")
    parser.add_argument("--model", help="The advisor's model, overriding config/models.yaml.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if bool(args.provider) != bool(args.model):
        print("--provider and --model go together")
        return 2
    if args.relabel:
        if args.no_extract or args.config:
            print("--relabel runs the extractor over both configurations: it takes neither --no-extract nor --config")
            return 2
        from . import relabel

        out = (args.out or RUNS / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-relabel")).resolve()
        print(f"Relabel {args.relabel.resolve()} into {out}")
        return asyncio.run(relabel.relabel(args.relabel.resolve(), out, _extractor()))
    if not args.scenarios.is_dir():
        print(f"{args.scenarios} is not a directory")
        return 2
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    layout = _layout(args, run_id)
    layout.directory.mkdir(parents=True, exist_ok=True)

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
    return asyncio.run(_evaluate(args, run_id=run_id, layout=layout, database=database))


def _layout(args: argparse.Namespace, run_id: str) -> Layout:
    if args.config:
        name = "full.jsonl" if args.config == "full" else "baseline.jsonl"
        trace = (args.out or RUNS / run_id / name).resolve()
        return Layout(trace.parent, {args.config: trace}, prefix=f"{trace.stem}.")
    directory = (args.out or RUNS / run_id).resolve()
    return Layout(directory, {"full": directory / "full.jsonl", "baseline_no_memory": directory / "baseline.jsonl"})


async def _evaluate(args: argparse.Namespace, *, run_id: str, layout: Layout, database: str) -> int:
    from ...llm import jev
    from ...mcp import client as mcp_client
    from . import report, runner, scenarios, trace

    started = datetime.now(timezone.utc)
    ready, rejected = scenarios.load(args.scenarios, set(args.only) or None)
    for item in rejected:
        print(f"  rejected {item.path.name}: {item.reason}")
    if not ready:
        print(f"No scenario to run in {args.scenarios}" + (f" for {', '.join(args.only)}" if args.only else ""))
        return 2
    configs = list(layout.traces)
    runs: dict[str, ConfigRun] = {}
    found: dict[str, dict[str, int]] = {}
    extractor = None
    try:
        rig = await runner.build(provider=args.provider, model=args.model)
        extractor = None if args.no_extract else _extractor()
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
                if result.error:
                    run.stopped.append({"scenario_id": scenario.scenario_id, "error": result.error})
            if extractor is not None:
                await _label(run, extractor)
            invalid = 0
            for row, diagnosis in zip(run.rows, run.diagnostics):
                errors = trace.schema_errors(row)
                if errors:
                    invalid += 1
                    diagnosis["schema_errors"] = errors
            trace.write_jsonl(layout.traces[config], run.rows)
            found[config] = report.problems(run.rows, run.diagnostics, schema_errors=invalid,
                                            rejected=len(rejected), scenario_errors=len(run.stopped))
            print(f"  -> {layout.traces[config]}")
        advisor = {"provider": rig.provider, "model": rig.advisor.model_name}
    finally:
        await mcp_client.close_all()
        await jev.close()

    trace.write_jsonl(layout.side("diagnostics.jsonl"), [d for run in runs.values() for d in run.diagnostics])
    _write_json(layout.side("usage.json"), {config: run.usage for config, run in runs.items()})
    record = report.manifest(
        run_id=run_id, started=started, scenarios_dir=args.scenarios, scenarios=ready, rejected=rejected,
        configs=configs, advisor=advisor,
        extractor={"model": extractor.model_name, **extractor.stats()} if extractor else None,
        warmup=args.warmup, database=database, found=found,
    )
    _write_json(layout.side("manifest.json"), record)

    print()
    for config, counts in found.items():
        print(f"{config}: " + ", ".join(f"{name} {n}" for name, n in counts.items()))
    if args.no_extract:
        print("Extractor off: questions and claims are empty, so RQR and HR are not measured.")
    voided = report.blocking(found)
    if voided:
        print("Not scored: " + ", ".join(f"{name} {n}" for name, n in voided.items())
              + f". The traces are kept in {layout.directory}; diagnostics.jsonl says what failed.")
        return 1
    if args.config:
        return 0
    frozen = report.freeze(ready, rejected, layout.side("scenarios"))
    retrieval = _retrieval(layout.side("rag"))
    code, table = report.grade(frozen, full=layout.traces["full"], baseline=layout.traces["baseline_no_memory"],
                               out=layout.side("report.json"), rag=layout.side("rag") / "rag_results.json")
    table = f"{table}\n\n{retrieval}"
    print()
    print(table)
    layout.side("table.txt").write_text(table + "\n", encoding="utf-8")
    if code == 0 and layout.side("report.json").exists():
        graded = json.loads(layout.side("report.json").read_text(encoding="utf-8"))
        failures = report.errors(graded, [d for run in runs.values() for d in run.diagnostics])
        trace.write_jsonl(layout.side("errors.jsonl"), failures)
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


def _extractor() -> Any:
    from ...components.evaluation.scorers import Extractor
    from ...config.config_manager import get_models_config
    from ...llm.factory import LLMFactory

    config = get_models_config().agent_llm_config("extractor")
    return Extractor(LLMFactory.create_llm(config, agent_name="extractor"), model_name=config["model"],
                     cache_path=EXTRACTOR_CACHE)


async def _label(run: ConfigRun, extractor: Any) -> None:
    """Fill ``questions``, ``claims`` and ``facts_used`` of every row, after the turns ran, so no extractor call
    ever queues in front of a timed turn.

    From the second call of a scenario each turn is labelled with the earlier calls of the same configuration
    (BTC's ``facts_used`` is a slot from the previous session). ``facts_used`` is what the extractor saw reused,
    then the slots of the brief lines the reply cited, each once. The items the labels came from go to the
    turn's diagnosis, so whoever checks the extractor can see each label's quote.
    """
    from ...components.evaluation import scorers
    from . import trace

    # A burst can reserve the remaining cap before any in-flight usage settles.
    gate = asyncio.Semaphore(1 if os.environ.get("EVAL_BUDGET_DB") else EXTRACTOR_CONCURRENCY)
    history = scorers.previous_sessions(run.rows)

    async def one(index: int, row: dict[str, Any], diagnosis: dict[str, Any]) -> None:
        data = scorers.turn_input(row["agent_text"], row["tool_calls"], history.get(index))
        async with gate:
            labels = await extractor.label(data)
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

    await asyncio.gather(*(one(index, row, diagnosis)
                           for index, (row, diagnosis) in enumerate(zip(run.rows, run.diagnostics))))
    print(f"  labelled {len(run.rows)} turns ({extractor.stats()})")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
