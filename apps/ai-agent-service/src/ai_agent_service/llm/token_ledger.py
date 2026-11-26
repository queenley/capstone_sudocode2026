"""Process-wide per-agent token ledger (self-tracked, no external service).

Each agent builds its own LLM + ``TokenTrackingCallback`` in ``BaseAgent.__init__``
(see ``factory.create_llm``), so the callback can attribute every completed call to
the agent that made it. One ``run_iReDev.py`` invocation = one run (each ablation run
uses ``--reset-db``), so this ledger holds exactly that run's per-agent token totals.
Dump it once at the end of the run (``format_table``) into the run log / tokens.md.

Tokens, not cost. Async-safe enough for the distiller's ``asyncio.gather`` Pass 1
(single event loop; the lock guards the rare threaded-callback case).
"""
from __future__ import annotations

import contextvars
import threading
from typing import Any, Dict

_LOCK = threading.Lock()
_LEDGER: Dict[str, Dict[str, int]] = {}
# The turn being taken (runtime/harness.run_turn): its model calls, by agent, for the turn's ``meta.usage`` that
# the developer console reads live. A mutable dict, so the graph's child tasks (which copy the context) add to it.
_TURN: contextvars.ContextVar[Dict[str, Any] | None] = contextvars.ContextVar("turn_usage", default=None)


def record(agent: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0, cost_usd: float = 0.0) -> None:
    """Add one completed LLM call's token usage under ``agent``; *cached_tokens* are part of *input_tokens*."""
    key = (agent or "unknown").strip() or "unknown"
    with _LOCK:
        entry = _LEDGER.setdefault(key, {"calls": 0, "input": 0, "output": 0, "cached": 0})
        entry["calls"] += 1
        entry["input"] += int(input_tokens or 0)
        entry["output"] += int(output_tokens or 0)
        entry["cached"] += int(cached_tokens or 0)
        turn = _TURN.get()
        if turn is not None:
            for bucket in (turn, turn["by_agent"].setdefault(key, {"calls": 0, "input": 0, "output": 0, "cached": 0, "cost_usd": 0.0})):
                bucket["calls"] += 1
                bucket["input"] += int(input_tokens or 0)
                bucket["output"] += int(output_tokens or 0)
                bucket["cached"] += int(cached_tokens or 0)
                bucket["cost_usd"] = round(bucket["cost_usd"] + float(cost_usd or 0.0), 8)


def turn_started() -> tuple[Dict[str, Any], contextvars.Token]:
    """Count this turn's model calls from now on; pass the token to :func:`turn_stopped`."""
    usage: Dict[str, Any] = {"calls": 0, "input": 0, "output": 0, "cached": 0, "cost_usd": 0.0, "by_agent": {}}
    return usage, _TURN.set(usage)


def turn_stopped(token: contextvars.Token) -> None:
    _TURN.reset(token)


def snapshot() -> Dict[str, Dict[str, int]]:
    with _LOCK:
        return {agent: dict(vals) for agent, vals in _LEDGER.items()}


def reset() -> None:
    with _LOCK:
        _LEDGER.clear()


def format_table() -> str:
    """Render the per-agent ledger as a Markdown table (sorted by total tokens)."""
    snap = snapshot()
    if not snap:
        return "(no LLM calls recorded)"
    rows = sorted(
        snap.items(), key=lambda kv: kv[1]["input"] + kv[1]["output"], reverse=True
    )
    lines = [
        "| agent | calls | input tok | output tok | total tok |",
        "|---|---|---|---|---|",
    ]
    tot_calls = tot_in = tot_out = 0
    for agent, e in rows:
        total = e["input"] + e["output"]
        tot_calls += e["calls"]
        tot_in += e["input"]
        tot_out += e["output"]
        lines.append(
            f"| {agent} | {e['calls']} | {e['input']} | {e['output']} | {total} |"
        )
    lines.append(
        f"| **TOTAL** | {tot_calls} | {tot_in} | {tot_out} | {tot_in + tot_out} |"
    )
    return "\n".join(lines)
