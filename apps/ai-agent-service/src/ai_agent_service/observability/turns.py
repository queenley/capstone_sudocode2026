"""Optional, privacy-conscious Langfuse summary of each completed agent turn.

The model calls themselves already reach Langfuse through the LangChain
callback (``llm/tracing.py``), with tokens and cost. This adds one ``agent-turn``
trace per turn carrying what the callback cannot see: the lane, the tools
called, the guard verdict and the end-to-end latency, as metadata and scores.
No prompt, reply or customer data is sent. Off when the Langfuse keys are unset;
the SDK batches and exports on its own thread, so nothing waits on the network.
"""

from __future__ import annotations

import logging
from typing import Any

from ..llm import tracing

logger = logging.getLogger(__name__)


class TurnTracker:
    """Send turn metrics to Langfuse off the request path; safe when Langfuse is down."""

    def __init__(self) -> None:
        self.client = tracing.client()

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def log_turn(
        self,
        *,
        trace_id: str,
        session_id: str,
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
            self._write(
                trace_id=trace_id, session_id=session_id, route=route, confidence=float(confidence),
                latency_ms=int(latency_ms), tool_calls=list(tool_calls), usage=dict(usage),
                environment=environment, router=router, model=model or "unspecified",
                stage_timings=dict(stage_timings), guard_blocked=bool(guard_blocked), error_count=int(error_count),
            )
        except Exception:
            # Tracking is observability only; it must not fail customer requests.
            logger.warning("Could not write agent turn to Langfuse")

    def _write(self, **event: Any) -> None:
        from langfuse import propagate_attributes

        metadata = {
            "agent_trace_id": event["trace_id"],
            "route": event["route"],
            "router": event["router"],
            "model": event["model"],
            "tool_calls": event["tool_calls"],
            "usage": {k: v for k, v in event["usage"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
            "stage_timings_ms": event["stage_timings"],
        }
        with propagate_attributes(
            session_id=event["session_id"],
            trace_name="agent-turn",
            tags=["telesales-ai-agent", event["route"]],
            metadata={"route": event["route"], "environment": event["environment"]},
        ):
            with self.client.start_as_current_observation(
                name="agent-turn", as_type="agent", metadata=metadata,
                level="ERROR" if event["error_count"] else "DEFAULT",
            ) as span:
                scores = {
                    "latency_ms": event["latency_ms"],
                    "route_confidence": event["confidence"],
                    "tool_call_count": len(event["tool_calls"]),
                    "guard_blocked": int(event["guard_blocked"]),
                    "error_count": event["error_count"],
                }
                for name, value in scores.items():
                    span.score_trace(name=name, value=float(value), data_type="NUMERIC")

    def close(self) -> None:
        tracing.flush()
