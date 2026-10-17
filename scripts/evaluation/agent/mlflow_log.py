"""Log one evaluation run's spend and scores to MLflow.

    python -m agent.mlflow_log runs/<run>            (from scripts/evaluation)
    python -m agent.mlflow_log runs/<run> --force    (log again although already logged)

``product.evaluate`` calls it after scoring; it also logs older runs. One
MLflow run per evaluation run, in the experiment ``telesales-evaluation``
(``MLFLOW_EVAL_EXPERIMENT``):

- params: dataset, level, advisor and extractor models, scenario count;
- metrics: tokens and USD for the agent and the extractor, per configuration
  (``full``, ``baseline``) and in total, cost per turn, and the BTC scores
  (TSR, CCR, RQR, HR, latency) of both configurations;
- artifact ``spend_by_scenario.json``: tokens and USD per scenario and configuration.

Only numbers and identifiers leave the machine: no prompt, reply or customer
data. Cost is tokens times the prices in ``config/models.yaml``; a provider
without a price is logged as tokens only, with ``*_priced = 0``.

Where: ``MLFLOW_TRACKING_URI`` (from ``.env``); the compose address
``http://mlflow:5000`` is read as ``http://127.0.0.1:${MLFLOW_PORT:-5500}`` from
the host. Start the server with ``docker compose --profile tracking up -d mlflow``.
"""

from __future__ import annotations

from . import launch

launch.prepare()

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import urllib.request  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402
from urllib.parse import urlsplit, urlunsplit  # noqa: E402

from . import spend  # noqa: E402

EXPERIMENT = "telesales-evaluation"
CONFIGS = {"full": "full", "baseline_no_memory": "baseline"}
SCORES = {"task_success_rate": "tsr", "context_carryover_rate": "ccr", "repeat_question_rate": "rqr",
          "hallucination_rate": "hr"}


def tracking_uri() -> str:
    """The server to log to, as seen from this machine."""
    uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip() or "http://mlflow:5000"
    parts = urlsplit(uri)
    if parts.hostname == "mlflow":  # the compose service name, unreachable from the host
        uri = urlunsplit(parts._replace(netloc=f"127.0.0.1:{os.environ.get('MLFLOW_PORT', '5500')}"))
    return uri


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


def log(run: Path, *, force: bool = False) -> str:
    """Log *run*; returns a line saying where (or why not)."""
    import mlflow

    uri = tracking_uri()
    try:
        urllib.request.urlopen(uri.rstrip("/") + "/health", timeout=3)
    except OSError:
        return (f"MLflow not reachable at {uri}; spend not logged. Start it with "
                f"`docker compose --profile tracking up -d mlflow`, then `python -m agent.mlflow_log {run}`.")
    mlflow.set_tracking_uri(uri)
    experiment = mlflow.set_experiment(os.environ.get("MLFLOW_EVAL_EXPERIMENT", EXPERIMENT))
    key = fingerprint(run)
    found = mlflow.search_runs([experiment.experiment_id], filter_string=f"tags.run_key = '{key}'",
                               output_format="list")
    if found and not force:
        return f"Already in MLflow as run {found[0].info.run_id}; pass --force to log again."
    data = collect(run)
    git = (read(run / "inputs/product-bundle.json").get("git") or {}) if (run / "inputs/product-bundle.json").is_file() else {}
    tags = {"run_dir": run.name, "run_key": key, "application": "telesales-evaluation",
            "git_commit": git.get("commit") or "", "git_dirty": str(git.get("dirty"))}
    if data["pipeline_error"]:
        tags["pipeline_error"] = str(data["pipeline_error"])[:500]
    with mlflow.start_run(run_name=run.name, tags=tags) as active:
        mlflow.log_params(data["params"])
        mlflow.log_metrics({k: float(v) for k, v in data["metrics"].items()})
        mlflow.log_dict({"currency": spend.CURRENCY, "rows": data["by_scenario"]}, "spend_by_scenario.json")
    total = data["metrics"]["total_cost_usd"]
    return (f"MLflow: run {active.info.run_id} in '{experiment.name}' at {uri} "
            f"(total ${total:.4f}, {int(data['metrics']['total_turns'])} turns)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Log an evaluation run's spend and scores to MLflow")
    parser.add_argument("run", type=Path, help="An evaluation run folder, e.g. runs/20261017-101500")
    parser.add_argument("--force", action="store_true", help="Log again even if this run is already in MLflow")
    args = parser.parse_args(argv)
    run = args.run.resolve()
    if not (run / "inputs/manifest.json").is_file():
        print(f"Not an evaluation run folder: {run}")
        return 2
    print(log(run, force=args.force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
