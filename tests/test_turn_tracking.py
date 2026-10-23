from contextlib import contextmanager

from ai_agent_service.observability.turns import TurnTracker


class FakeSpan:
    def __init__(self, scores):
        self.scores = scores

    def score_trace(self, *, name, value, data_type):
        self.scores[name] = value


class FakeClient:
    def __init__(self):
        self.observations = []
        self.scores = {}

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.observations.append(kwargs)
        yield FakeSpan(self.scores)


def _turn(tracker, **overrides):
    event = dict(
        trace_id="call-1:turn-1", session_id="call-1", route="product_search", confidence=0.91,
        latency_ms=180, tool_calls=["catalog.search"], usage={"model_calls": 2}, environment="test",
        router="rules", model="test-model", stage_timings={"route": 3}, guard_blocked=False, error_count=0,
    )
    tracker.log_turn(**{**event, **overrides})


def test_turn_is_sent_as_langfuse_trace_without_prompt_payload():
    tracker = TurnTracker()
    tracker.client = FakeClient()
    _turn(tracker)

    (observation,) = tracker.client.observations
    assert observation["name"] == "agent-turn"
    assert observation["metadata"]["agent_trace_id"] == "call-1:turn-1"
    assert observation["metadata"]["tool_calls"] == ["catalog.search"]
    assert tracker.client.scores == {
        "latency_ms": 180.0, "route_confidence": 0.91, "tool_call_count": 1.0,
        "guard_blocked": 0.0, "error_count": 0.0,
    }
    assert not {"prompt", "reply", "customer_id"} & set(observation["metadata"])


def test_tracker_is_off_without_keys_and_never_raises(monkeypatch):
    tracker = TurnTracker()
    tracker.client = None
    _turn(tracker)  # disabled: nothing to do

    class Broken:
        def start_as_current_observation(self, **kwargs):
            raise RuntimeError("langfuse down")

    tracker.client = Broken()
    _turn(tracker)  # logged as a warning, not raised
