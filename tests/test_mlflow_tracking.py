import sys
from types import SimpleNamespace

from ai_agent_service.observability.mlflow import MlflowTurnTracker


def test_turn_tracker_queues_only_aggregated_turn_metadata(monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.test")
    captured = []
    monkeypatch.setattr(MlflowTurnTracker, "_write", lambda self, event: captured.append(event))
    tracker = MlflowTurnTracker()
    try:
        tracker.log_turn(
            trace_id="trace-1234",
            route="product_search",
            confidence=0.91,
            latency_ms=180,
            tool_calls=["catalog.search"],
            usage={"prompt_tokens": 45, "completion_tokens": 12},
            environment="test",
            router="RuleRouter",
            model="test-model",
            stage_timings={"route": 3, "advisor": 90},
            guard_blocked=False,
            error_count=0,
        )
        tracker._queue.join()
    finally:
        tracker.close()

    assert len(captured) == 1
    event = captured[0]
    assert event["trace_id"] == "trace-1234"
    assert event["route"] == "product_search"
    assert event["stage_timings"] == {"route": 3, "advisor": 90}
    assert "prompt" not in event
    assert "customer_id" not in event
    assert "tool_arguments" not in event


def test_mlflow_run_logs_pipeline_metrics_without_prompt_payload(monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.test")

    class FakeClient:
        def __init__(self, tracking_uri):
            assert tracking_uri == "http://mlflow.test"
            self.params = []
            self.metrics = []
            self.terminated = None

        def get_experiment_by_name(self, name):
            assert name == "telesales-agent"
            return SimpleNamespace(experiment_id="experiment-1")

        def create_run(self, **kwargs):
            self.run_options = kwargs
            return SimpleNamespace(info=SimpleNamespace(run_id="run-1"))

        def log_param(self, run_id, key, value):
            self.params.append((run_id, key, value))

        def log_metric(self, run_id, key, value, timestamp=None):
            self.metrics.append((run_id, key, value))

        def set_terminated(self, run_id, status):
            self.terminated = (run_id, status)

    client = FakeClient("http://mlflow.test")
    monkeypatch.setitem(sys.modules, "mlflow", SimpleNamespace(MlflowClient=lambda **kwargs: client))
    tracker = MlflowTurnTracker()
    tracker._write(
        {
            "trace_id": "trace-1234",
            "route": "product_search",
            "confidence": 0.91,
            "latency_ms": 180,
            "tool_calls": ["catalog.search"],
            "usage": {"prompt_tokens": 45},
            "environment": "test",
            "router": "RuleRouter",
            "model": "test-model",
            "stage_timings": {"route": 3, "advisor": 90},
            "guard_blocked": False,
            "error_count": 0,
        }
    )
    tracker.close()

    assert client.run_options["tags"]["agent.trace_id"] == "trace-1234"
    assert ("run-1", "stage_route_ms", 3.0) in client.metrics
    assert ("run-1", "guard_blocked", 0.0) in client.metrics
    assert client.terminated == ("run-1", "FINISHED")
    assert all("prompt" not in value for _, _, value in client.params)
