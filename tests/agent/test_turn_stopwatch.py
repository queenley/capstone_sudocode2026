"""Where a turn's time goes: each stage timed once, on the turn's own path (observability/stopwatch)."""
from __future__ import annotations

import asyncio
import json

from ai_agent_service.observability import stopwatch
from ai_agent_service.pipeline.eval import performance
from ai_agent_service.pipeline.eval.runner import diagnose
from ai_agent_service.pipeline.hot import nodes


def timed(coroutine):
    async def run():
        watch, token = stopwatch.started()
        try:
            await coroutine()
        finally:
            stopwatch.stopped(token)
        return watch

    return asyncio.run(run())


def test_a_stage_with_no_turn_running_costs_nothing():
    with stopwatch.span("tools"):
        pass  # no stopwatch: nothing recorded, nothing raised


def test_two_tools_at_once_count_their_wall_time_once():
    async def tool():
        with stopwatch.span("tools"):
            await asyncio.sleep(0.05)

    async def turn():
        await asyncio.gather(tool(), tool())  # tasks: each gets a copy of the context, the same stopwatch

    report = timed(turn).report()
    assert 40 <= report["stages_ms"]["tools"] < 95
    assert report["stage_counts"]["tools"] == 2


def test_other_is_what_no_stage_of_the_path_claims():
    watch = stopwatch.Stopwatch()
    watch.ms = {"advisor": 1200.0, "guard": 30.0, "model": 1100.0}
    stages = watch.report(total_ms=1500)["stages_ms"]
    assert stages["other"] == 270  # model is inside advisor, not added again


def test_the_advisor_wait_leaves_out_the_time_spent_checking_a_sentence():
    async def stream():
        for word in ("Dạ ", "vâng."):
            await asyncio.sleep(0.03)
            yield word

    async def turn():
        async for _ in nodes._waited(stream()):
            with stopwatch.span("policy"):
                await asyncio.sleep(0.05)

    stages = timed(turn).report()["stages_ms"]
    assert 50 <= stages["advisor"] < 90
    assert 90 <= stages["policy"] < 140


def test_the_diagnostics_carry_the_timings():
    row = diagnose({}, None, config="full", scenario_id="S", call="call_1", turn=1,
                   timings={"stages_ms": {"advisor": 900}, "stage_counts": {"advisor": 2}})
    assert row["timings"]["stages_ms"]["advisor"] == 900


def test_the_performance_table_reads_the_stages(tmp_path):
    rows = [{"config": "full", "timings": {"stages_ms": {"advisor": 2000, "guard": 20, "model": 1800, "other": 80},
                                           "stage_counts": {"advisor": 3, "model": 2}}},
            {"config": "full", "timings": {"stages_ms": {"advisor": 1000, "policy": 400, "other": 100},
                                           "stage_counts": {"advisor": 1, "policy": 1}}},
            {"config": "baseline_no_memory", "timings": {"stages_ms": {"advisor": 9000}}},
            {"config": "full", "timings": {}}]
    path = tmp_path / "diagnostics.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    figures = performance.stages(path)
    assert figures["n"] == 2
    advisor = figures["stages"]["advisor"]
    assert advisor["mean_ms"] == 1500 and advisor["per_turn"] == 2
    assert figures["stages"]["model"]["share"] is None
    assert abs(sum(s["share"] for s in figures["stages"].values() if s["share"]) - 1) < 0.01
    assert "chờ advisor" in "\n".join(performance.stage_lines(figures))


def test_an_older_run_says_not_measured(tmp_path):
    assert performance.stages(tmp_path / "diagnostics.jsonl") is None
    assert "chưa đo" in performance.stage_lines(None)[0]


def test_a_turn_through_the_hot_graph_times_its_stages():
    from datetime import datetime, timezone

    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from ai_agent_service.agents.advisor import AdvisorAgent
    from ai_agent_service.components.intake import pii
    from ai_agent_service.pipeline.hot.graph import build_graph
    from ai_agent_service.pipeline.hot.state import HotContext

    class Harness:
        async def data(self, name, **kwargs):
            return {"identity_find": {"matches": []}, "kb_search": {"hits": [], "abstain": True}}.get(name, {})

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    agent = AdvisorAgent(llm=Model(responses=[AIMessage(content="Dạ em chào anh/chị ạ.")]), tools=[], retries=0)
    context = HotContext(text="Chào em.", identity_secret="fixture", vault=pii.Vault(), harness=Harness(), advisor=agent)

    async def turn():
        await build_graph(checkpointer=InMemorySaver()).ainvoke(
            {"call_id": "c", "turn_id": "t1", "turn_no": 1, "channel": "web", "on": "2026-10-22",
             "now": datetime(2026, 10, 22, tzinfo=timezone.utc), "switches": {"memory": True}},
            context=context, config={"configurable": {"thread_id": "stopwatch"}})

    report = timed(turn).report(total_ms=10_000)
    assert {"context", "knowledge", "advisor", "model", "guard", "respond", "persist"} <= set(report["stages_ms"])
    assert report["stage_counts"]["model"] == 1
