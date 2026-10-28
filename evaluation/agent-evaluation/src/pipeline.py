"""The whole evaluation in one call: :func:`evaluate` runs the four steps of ``src/steps`` in order.

``run_eval.py evaluate --out runs/<name>`` writes one folder per step under ``--out`` and never overwrites one:

| Folder | Step | What to read |
|---|---|---|
| ``inputs/`` | 1 Prepare (``steps/prepare``): pinned scenarios, labels, manifest, adapter | ``preparation-report.json`` |
| ``raw/`` | 2 Run (``steps/run``): the agent's hooks, every tool event, full and baseline | ``runner-report.json``, ``full/adapter-*.log`` |
| ``evidence/`` | 3 Collect (``steps/collect``): transcripts, extraction, memory, briefs, the BTC trace | ``full.jsonl``, ``baseline.jsonl``, ``validation.json`` |
| ``scored/`` | 4 Score (``steps/score`` + ``criteria``): BTC's grader and the harness's checks | ``scorer.stdout.txt``, ``official-report.json`` |

``execution-report.json`` at the top sums up every step; ``case-trace.json`` replays each conversation.
"""
from src.common.assets import Assets, lock_folder, new_output, write_new
from src.common.progress import say
from src.reports.case_trace import write as write_case_trace
from src.services.agent_settings import PRODUCT, log_spend
from src.steps.collect.collector import collect
from src.steps.prepare.prepare import DEFAULT_DATASET, levels, prepare
from src.steps.run.runner import run_fixed
from src.steps.score.scoring import score

__all__ = ["evaluate", "levels", "prepare", "DEFAULT_DATASET"]


def evaluate(out, *, only=None, extractor_calls=None, dataset_id=DEFAULT_DATASET, level=None, limit=None,
             advisor=None, extractor_model=None):
    """Prepare, run, collect and score; ``execution-report.json`` sums it up."""
    out = new_output(out, Assets(PRODUCT))
    out.mkdir(parents=True, mode=0o700)
    stages, failure = [], None
    say(f"1/4 Prepare: checking inputs into {out}")
    try:
        prepared = prepare(out / "inputs", only=only, extractor_calls=extractor_calls, dataset_id=dataset_id,
                           level=level, limit=limit, advisor=advisor, extractor_model=extractor_model)
        stages.append({"stage": "prepare", **prepared})
        if not prepared["execution_gate"]["allowed"]:
            raise ValueError("Prepared inputs did not pass the execution gate")
        turns = prepared["planned_turns"]
        scenarios = len(list((out / "inputs/scenarios").glob("*.json")))
        # Measured on Windows: ~75 s to start the agent per scenario and
        # configuration, ~3 s per agent turn, ~8 s per extraction call.
        minutes = (scenarios * 2 * 75 + turns * 3 + turns * 8) // 60 + 1
        say(f"2/4 Run: {scenarios} scenario(s) x 2 configs = {turns} agent turns; whole evaluation ~{minutes} min")
        raw = run_fixed(out / "inputs/settings.json", out / "raw")
        stages.append({"stage": "run", "execution_complete": raw["execution_complete"],
                       "completed_calls": raw["completed_calls"], "failed_calls": raw["failed_calls"],
                       "errors": raw["errors"]})
        say(f"   calls completed {raw['completed_calls']}, failed {raw['failed_calls']}")
        say(f"3/4 Collect: one extraction call per turn ({turns})")
        evidence = collect(out / "raw", out / "evidence", extractor_path="extractor.json")
        stages.append({"stage": "collect", "status": evidence["status"], "trace_rows": evidence["trace_rows"],
                       "trace_wire_complete": evidence["trace_wire_complete"]})
        say("4/4 Score: BTC reference_eval and this harness's checks")
        scored = score(out / "evidence", out / "scored")
        stages.append({"stage": "score", "status": scored["status"],
                       "official_report_available": scored["official_report_available"]})
    except (OSError, ValueError, KeyError, TypeError, AssertionError, RuntimeError) as exc:
        failure = f"{type(exc).__name__}: {exc}"
        say(f"Stopped: {failure}")
    report = {"report_kind": "product-evaluate-v1", "stages": stages, "pipeline_error": failure,
              "quality_accepted": False, "table": "scored/scorer.stdout.txt",
              "notice": "The team's agent on generated diagnostic scenarios whose labels await QA; "
                        "not BTC acceptance."}
    try:
        write_case_trace(out, report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report["pipeline_error"] = (report["pipeline_error"] + "; " if report["pipeline_error"] else "") + f"Case trace: {type(exc).__name__}: {exc}"
    write_new(out / "execution-report.json", report)
    lock_folder(out)
    say("Logging spend to Langfuse")
    report["mlflow"] = log_spend(out)
    say(report["mlflow"])
    return report
