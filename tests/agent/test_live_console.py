"""The developer console's live view: a stored turn as the console draws it, and each turn's own token count."""
import asyncio
from datetime import datetime, timezone

from ai_agent_service.api.routes import live
from ai_agent_service.llm import token_ledger


def stored(**meta):
    return {"id": 9, "call_id": 3, "turn_id": "t1", "created_at": datetime(2026, 11, 20, tzinfo=timezone.utc),
            "channel": "web", "customer_id": "C-1", "mode": "speak", "meta": meta}


def test_a_turn_shows_its_model_tokens_cost_tools_and_guard(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "https://cloud.langfuse.com/")
    monkeypatch.setenv("LANGFUSE_PROJECT_ID", "proj")
    got = live.row(stored(
        lane="NEW", model="gpt-x", latency={"ttft_ms": 1200, "total_ms": 2400, "advisor_ms": 900},
        usage={"calls": 2, "input": 3000, "output": 80, "cached": 1000, "cost_usd": 0.0012, "by_agent": {"advisor": {"calls": 2}}},
        tool_calls=[{"name": "catalog.search", "args": {"query": "x"}, "result": {"ok": True, "data": {}}},
                    {"name": "pricing.get_quote", "args": {"sku": "A"}, "result": {"ok": False, "error": {"code": "NOT_FOUND"}}}],
        guard={"hard": {"reasons": ["price_mismatch"]}}))
    assert (got["model"], got["ttft_ms"], got["model_calls"], got["cost_usd"]) == ("gpt-x", 1200, 2, 0.0012)
    assert got["tokens"] == {"input": 3000, "output": 80, "cached": 1000} and got["stages"] == {"advisor_ms": 900}
    assert [(t["name"], t["ok"], t["error"]) for t in got["tools"]] == [("catalog.search", True, None), ("pricing.get_quote", False, "NOT_FOUND")]
    assert got["guard"] == {"passed": False, "reasons": ["price_mismatch"]}
    assert got["langfuse_url"] == "https://cloud.langfuse.com/project/proj/sessions/C-1"


def test_without_langfuse_settings_there_is_no_link(monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    assert live.row(stored())["langfuse_url"] is None


def test_the_summary_leaves_warmup_out_of_latency_and_counts_failed_tools():
    rows = [live.row(stored(latency={"ttft_ms": 100, "warmup": True})),
            live.row(stored(latency={"ttft_ms": 1000}, usage={"input": 10, "output": 5, "cost_usd": 0.001},
                            tool_calls=[{"name": "a", "result": {"ok": False}}])),
            live.row(stored(latency={"ttft_ms": 3000}, usage={"input": 20, "output": 5, "cost_usd": 0.002}))]
    got = live.summarize(rows)
    assert got["turns"] == 3 and got["ttft_p50_ms"] == 2000 and got["ttft_p95_ms"] == 3000
    assert (got["tokens_input"], got["tool_failures"], got["cost_usd"]) == (30, 1, 0.003)
    assert got["by_tool"] == {"a": {"calls": 1, "failed": 1}}


def test_each_turn_counts_only_its_own_model_calls_even_from_child_tasks():
    async def turn(n):
        usage, token = token_ledger.turn_started()
        try:
            async def call():
                token_ledger.record("advisor", 100 * n, 10, cost_usd=0.5)
            await asyncio.gather(asyncio.create_task(call()), asyncio.create_task(call()))
        finally:
            token_ledger.turn_stopped(token)
        return usage

    async def go():
        return await asyncio.gather(turn(1), turn(2))

    one, two = asyncio.run(go())
    assert (one["calls"], one["input"], one["cost_usd"]) == (2, 200, 1.0)
    assert (two["calls"], two["input"]) == (2, 400) and two["by_agent"]["advisor"]["calls"] == 2
    token_ledger.record("advisor", 1, 1)  # outside a turn: the process ledger only, no error
