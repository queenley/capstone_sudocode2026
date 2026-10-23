"""Log one evaluation run's spend and scores to Langfuse.

    python -m agent.langfuse_log runs/<run>            (from scripts/evaluation)
    python -m agent.langfuse_log runs/<run> --force    (log again although already logged)

``product.evaluate`` calls it after scoring; it also logs older runs. One
Langfuse trace per evaluation run, named ``evaluation-run``, in the
``evaluation`` environment and grouped by dataset as session ``eval:<dataset>``:

- metadata: dataset, level, advisor and extractor models, scenario count, git;
- one generation per scenario and configuration (``full``, ``baseline``) and one
  for the extractor, with tokens and USD, so Langfuse's cost views add them up;
- scores: tokens and USD per configuration and in total, cost per turn, and
  the BTC scores (TSR, CCR, RQR, HR, latency) of both configurations.

Only numbers and identifiers leave the machine: no prompt, reply or customer
data. Cost is tokens times the prices in ``config/models.yaml``; a provider
without a price is logged as tokens only, with ``*_priced = 0``.

Where: ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY`` and ``LANGFUSE_BASE_URL``
from ``.env`` (the same keys the agent traces with).
"""

from __future__ import annotations

from . import launch

launch.prepare()

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from . import spend  # noqa: E402

TRACE_NAME = "evaluation-run"
CONFIGS = {"full": "full", "baseline_no_memory": "baseline"}
SCORES = {"task_success_rate": "tsr", "context_carryover_rate": "ccr", "repeat_question_rate": "rqr",
          "hallucination_rate": "hr"}


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def collect(run: Path) -> dict[str, Any]:
    """Spend, scores and identity of one evaluation run, read from its folder."""
    manifest = read(run / "inputs/manifest.json")
    extractor = read(run / "inputs/extractor.json")
    conversion = read(run / "inputs/conversion-report.json")
    advisor = manifest["configuration"]["parameters"]["provider"]
    model = manifest["configuration"]["model"]

    # The agent: one usage block per completed turn, in the raw hook results.
    turns: dict[str, int] = defaultdict(int)
    tokens: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for config in CONFIGS:
        path = run / "raw" / config / "raw-execution.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            data = record.get("data") or {}
            if record.get("kind") != "adapter_message" or data.get("hook") != "run_turn" or data.get("type") != "result":
                continue
            usage = (data.get("result") or {}).get("usage") or {}
            scenario = (record.get("context") or {}).get("scenario_id", "?")
            tokens[(config, scenario)][0] += int(usage.get("input_tokens") or 0)
            tokens[(config, scenario)][1] += int(usage.get("output_tokens") or 0)
            turns[config] += 1

    # The extractor: one process per turn, its usage in the attempt's stdout.
    extracted = [0, 0, 0]
    for attempt in sorted((run / "evidence/extractor-raw").glob("attempt-*.json")):
        try:
            usage = json.loads(read(attempt).get("stdout") or "{}").get("usage") or {}
        except ValueError:
            continue
        extracted[0] += int(usage.get("input_tokens") or 0)
        extracted[1] += int(usage.get("output_tokens") or 0)
        extracted[2] += 1

    metrics: dict[str, float] = {}
    by_scenario = []
    priced_agent = spend.prices(advisor) is not None
    for config, label in CONFIGS.items():
        rows = [(s, t) for (c, s), t in tokens.items() if c == config]
        total_in, total_out = sum(t[0] for _, t in rows), sum(t[1] for _, t in rows)
        metrics[f"{label}_input_tokens"] = total_in
        metrics[f"{label}_output_tokens"] = total_out
        metrics[f"{label}_turns"] = turns[config]
        metrics[f"{label}_cost_usd"] = spend.cost(advisor, total_in, total_out) or 0.0
        for scenario, (i, o) in sorted(rows):
            by_scenario.append({"scenario_id": scenario, "config": config, "input_tokens": i, "output_tokens": o,
                                "cost_usd": spend.cost(advisor, i, o)})
    x_provider = extractor["config"]["provider"]
    metrics["extractor_calls"] = extracted[2]
    metrics["extractor_input_tokens"] = extracted[0]
    metrics["extractor_output_tokens"] = extracted[1]
    metrics["extractor_cost_usd"] = spend.cost(x_provider, extracted[0], extracted[1]) or 0.0
    metrics["agent_cost_usd"] = metrics["full_cost_usd"] + metrics["baseline_cost_usd"]
    metrics["total_cost_usd"] = metrics["agent_cost_usd"] + metrics["extractor_cost_usd"]
    all_turns = turns["full"] + turns["baseline_no_memory"]
    metrics["total_turns"] = all_turns
    metrics["cost_per_turn_usd"] = metrics["total_cost_usd"] / all_turns if all_turns else 0.0
    metrics["agent_priced"] = int(priced_agent)
    metrics["extractor_priced"] = int(spend.prices(x_provider) is not None)

    report_path = run / "scored/official-report.json"
    if report_path.is_file():
        report = read(report_path)
        for side, label in (("system", "full"), ("baseline", "baseline")):
            block = report.get(side) or {}
            for key, short in SCORES.items():
                value = (block.get(key) or {}).get("value")
                if isinstance(value, (int, float)):
                    metrics[f"{label}_{short}"] = value
            latency = ((block.get("latency") or {}).get("total") or {})
            for key in ("p50_ms", "p95_ms"):
                if isinstance(latency.get(key), (int, float)):
                    metrics[f"{label}_latency_{key}"] = latency[key]

    execution = read(run / "execution-report.json") if (run / "execution-report.json").is_file() else {}
    stage = next((s for s in execution.get("stages", []) if s.get("stage") == "run"), {})
    for key in ("completed_calls", "failed_calls"):
        if isinstance(stage.get(key), int):
            metrics[key] = stage[key]

    params = {
        "dataset": conversion.get("dataset_id") or "output1-diagnostic-v2",
        "level": manifest.get("level"),
        "advisor": f"{advisor}:{model}",
        "extractor": f"{x_provider}:{extractor['config']['model']}",
        "scenarios": len(manifest.get("scenarios") or []),
        "harness_run_id": manifest.get("run_id"),
    }
    return {"params": params, "metrics": metrics, "by_scenario": by_scenario,
            "pipeline_error": execution.get("pipeline_error")}


def fingerprint(run: Path) -> str:
    """Identifies one execution: its raw logs carry timestamps, so a run made
    again in a folder of the same name gets a new fingerprint."""
    digest = hashlib.sha256()
    for path in sorted((run / "raw").glob("*/raw-execution.jsonl")):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _exists(client: Any, trace_id: str) -> bool:
    """Whether the trace is already in Langfuse. Uses the v2 observations API
    (the legacy ``/traces`` one is gone for new organisations); the public API
    can lag ingestion by a few minutes, so a log repeated at once may slip by."""
    try:
        found = client.api.observations.get_many(trace_id=trace_id, is_root_observation=True, limit=1, fields="core")
        return bool(found.data)
    except Exception:  # noqa: BLE001 - not reachable: log, as before
        return False


def log(run: Path, *, force: bool = False) -> str:
    """Log *run*; returns a line saying where (or why not)."""
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return ("Langfuse keys not set (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY in .env); spend not logged. "
                f"Set them, then `python -m agent.langfuse_log {run}`.")
    from langfuse import Langfuse, propagate_attributes

    client = Langfuse(environment="evaluation")
    host = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST") or "https://cloud.langfuse.com"
    try:
        if not client.auth_check():
            return f"Langfuse rejected the keys at {host}; spend not logged."
    except Exception as exc:  # noqa: BLE001 - network or server error
        return (f"Langfuse not reachable at {host} ({type(exc).__name__}); spend not logged. "
                f"Log it later with `python -m agent.langfuse_log {run}`.")
    key = fingerprint(run)
    # Same execution -> same trace id, so a second log is noticed and skipped.
    trace_id = Langfuse.create_trace_id(seed=f"telesales-evaluation:{key}" + (f":{time.time_ns()}" if force else ""))
    if not force and _exists(client, trace_id):
        return f"Already in Langfuse as trace {trace_id}; pass --force to log again."
    data = collect(run)
    params, metrics = data["params"], data["metrics"]
    bundle = run / "inputs/product-bundle.json"
    git = (read(bundle).get("git") or {}) if bundle.is_file() else {}
    advisor, model = params["advisor"].split(":", 1)
    x_provider, x_model = params["extractor"].split(":", 1)
    metadata = {**params, "run_dir": run.name, "run_key": key, "git_commit": git.get("commit") or "",
                "git_dirty": git.get("dirty"), "currency": spend.CURRENCY}
    if data["pipeline_error"]:
        metadata["pipeline_error"] = str(data["pipeline_error"])[:500]

    with propagate_attributes(session_id=f"eval:{params['dataset']}", trace_name=TRACE_NAME,
                              tags=["telesales-evaluation", str(params["level"] or "all"), advisor],
                              metadata={"run_dir": run.name, "run_key": key}):
        with client.start_as_current_observation(
            trace_context={"trace_id": trace_id}, name=TRACE_NAME, as_type="chain", metadata=metadata,
            level="ERROR" if data["pipeline_error"] else "DEFAULT",
        ) as root:
            for row in data["by_scenario"]:
                generation = root.start_observation(
                    name=f"agent:{CONFIGS[row['config']]}:{row['scenario_id']}", as_type="generation", model=model,
                    metadata={"scenario_id": row["scenario_id"], "config": row["config"], "provider": advisor},
                    usage_details={"input": row["input_tokens"], "output": row["output_tokens"]},
                    cost_details={"total": row["cost_usd"]} if row["cost_usd"] is not None else None,
                )
                generation.end()
            extractor = root.start_observation(
                name="extractor", as_type="generation", model=x_model,
                metadata={"provider": x_provider, "calls": metrics["extractor_calls"]},
                usage_details={"input": int(metrics["extractor_input_tokens"]),
                               "output": int(metrics["extractor_output_tokens"])},
                cost_details={"total": metrics["extractor_cost_usd"]} if metrics["extractor_priced"] else None,
            )
            extractor.end()
            for name, value in metrics.items():
                # A fixed id per trace and metric: logging again overwrites, never doubles.
                root.score_trace(name=name, value=float(value), data_type="NUMERIC", score_id=f"{trace_id}-{name}")
    client.flush()
    total = metrics["total_cost_usd"]
    return (f"Langfuse: trace {trace_id} at {host} "
            f"(total ${total:.4f}, {int(metrics['total_turns'])} turns)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Log an evaluation run's spend and scores to Langfuse")
    parser.add_argument("run", type=Path, help="An evaluation run folder, e.g. runs/20261017-101500")
    parser.add_argument("--force", action="store_true", help="Log again even if this run is already in Langfuse")
    args = parser.parse_args(argv)
    run = args.run.resolve()
    if not (run / "inputs/manifest.json").is_file():
        print(f"Not an evaluation run folder: {run}")
        return 2
    print(log(run, force=args.force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
