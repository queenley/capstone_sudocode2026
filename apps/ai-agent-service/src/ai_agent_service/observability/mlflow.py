"""Optional, privacy-conscious MLflow run logging for completed agent turns."""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class MlflowTurnTracker:
    """Send turn metrics to MLflow off the request path; safe when MLflow is down."""

    def __init__(self) -> None:
        self.tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()
        self.experiment_name = os.getenv(
            "MLFLOW_EXPERIMENT_NAME", "telesales-agent"
        ).strip() or "telesales-agent"
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=512)
        self._stopping = threading.Event()
        self._worker: threading.Thread | None = None
        if self.tracking_uri:
            self._worker = threading.Thread(
                target=self._run, name="mlflow-turn-tracker", daemon=True
            )
            self._worker.start()

    @property
    def enabled(self) -> bool:
        return bool(self.tracking_uri)

    def log_turn(
        self,
        *,
        trace_id: str,
        route: str,
        confidence: float,
        latency_ms: int,
        tool_calls: list[str],
        usage: dict[str, Any],
        environment: str,
        router: str,
        model: str,
        stage_timings: dict[str, int],
        guard_blocked: bool,
        error_count: int,
    ) -> None:
        if not self.enabled:
            return
        try:
            self._queue.put_nowait(
                {
                    "trace_id": trace_id,
                    "route": route,
                    "confidence": float(confidence),
                    "latency_ms": int(latency_ms),
                    "tool_calls": list(tool_calls),
                    "usage": dict(usage),
                    "environment": environment,
                    "router": router,
                    "model": model,
                    "stage_timings": dict(stage_timings),
                    "guard_blocked": bool(guard_blocked),
                    "error_count": int(error_count),
                }
            )
        except queue.Full:
            logger.warning("MLflow tracking queue is full; dropping agent turn metric")

    def _run(self) -> None:
        while not self._stopping.is_set() or not self._queue.empty():
            try:
                event = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._write(event)
            except Exception:
                # Tracking is observability only; it must not fail customer requests.
                logger.warning("Could not write agent turn to MLflow")
            finally:
                self._queue.task_done()

    def _write(self, event: dict[str, Any]) -> None:
        from mlflow import MlflowClient

        client = MlflowClient(tracking_uri=self.tracking_uri)
        experiment = client.get_experiment_by_name(self.experiment_name)
        if experiment:
            experiment_id = experiment.experiment_id
        else:
            try:
                experiment_id = client.create_experiment(self.experiment_name)
            except Exception:
                # Another service replica may have created it concurrently.
                experiment = client.get_experiment_by_name(self.experiment_name)
                if not experiment:
                    raise
                experiment_id = experiment.experiment_id
        run = client.create_run(
            experiment_id=experiment_id,
            run_name=f"agent-turn-{event['trace_id'][:8]}",
            tags={
                "application": "telesales-ai-agent",
                "environment": event["environment"],
                "agent.trace_id": event["trace_id"],
                "agent.route": event["route"],
            },
        )
        run_id = run.info.run_id
        try:
            params = {
                "route": event["route"],
                "router": event["router"],
                "model": event["model"] or "unspecified",
                "tool_calls": ",".join(event["tool_calls"]) or "none",
            }
            for key, value in params.items():
                client.log_param(run_id, key, str(value)[:500])
            metrics = {
                "route_confidence": event["confidence"],
                "latency_ms": event["latency_ms"],
                "tool_call_count": len(event["tool_calls"]),
                "guard_blocked": int(event["guard_blocked"]),
                "error_count": event["error_count"],
            }
            for key, value in event["usage"].items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metrics[f"usage_{key}"[:250]] = float(value)
            for stage, latency in event["stage_timings"].items():
                metrics[f"stage_{stage}_ms"] = int(latency)
            timestamp = int(time.time() * 1000)
            for key, value in metrics.items():
                client.log_metric(run_id, key, float(value), timestamp=timestamp)
            client.set_terminated(run_id, status="FINISHED")
        except Exception:
            try:
                client.set_terminated(run_id, status="FAILED")
            except Exception:
                pass
            raise

    def close(self) -> None:
        if self._worker:
            self._stopping.set()
            self._worker.join(timeout=2)
