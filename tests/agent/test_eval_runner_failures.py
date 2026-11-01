"""Evaluation keeps partial evidence and stops when memory infrastructure fails."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.pipeline.cold.after_call import _hold, _remember, after_call
from ai_agent_service.pipeline.eval import runner


@pytest.mark.asyncio
async def test_later_call_failure_keeps_completed_turns_and_stops_the_scenario(monkeypatch):
    monkeypatch.setattr(runner, "reset", AsyncMock())

    async def call(rig, scenario, plan, config, *, run, **kwargs):
        if plan.name == "call_2":
            raise RuntimeError("Synthetic connection failure")
        run.rows.append({"call": plan.name, "turn": 1})

    execute = AsyncMock(side_effect=call)
    monkeypatch.setattr(runner, "_run_call", execute)
    scenario = SimpleNamespace(scenario_id="SYNTHETIC", data={}, calls=[
        SimpleNamespace(name=f"call_{i}", seed=()) for i in (1, 2, 3)])
    result = await runner.run_scenario(None, scenario, "full", run_id="synthetic", progress=lambda _: None)
    assert result.rows == [{"call": "call_1", "turn": 1}]
    assert "call_2: RuntimeError" in result.error and execute.await_count == 2


@pytest.mark.asyncio
async def test_unknown_seed_slot_is_a_failure_instead_of_silently_missing_memory(monkeypatch):
    monkeypatch.setattr(runner, "_seed_owner", AsyncMock(return_value="synthetic-owner"))
    writer = SimpleNamespace(call=AsyncMock())
    seed = SimpleNamespace(session_id="synthetic", channel="hotline", facts={"unknown-slot": "value"})
    with pytest.raises(runner.scenarios.ScenarioError, match="unknown memory slot"):
        await runner.seed(SimpleNamespace(writer=writer), (seed,), customer_phone=None, customer_name=None)
    writer.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_read", ["memory_get_profile", "memory_get_episodes"])
async def test_failed_memory_read_never_becomes_an_empty_profile_for_new_writes(failed_read):
    async def data(tool, **kwargs):
        if tool == failed_read:
            return None
        if tool == "memory_get_profile":
            return {"facts": []}
        if tool == "memory_get_episodes":
            return {"episodes": []}
        pytest.fail("No memory writes are safe after a failed memory read")

    writer = SimpleNamespace(data=AsyncMock(side_effect=data))
    result = await _remember({"call_id": "synthetic", "on": "2035-02-03", "tier": "VERIFIED",
                              "customer_id": "synthetic-owner"}, [], writer=writer, memory=None)
    assert result["status"] == "failed" and not result["memory_writes"]


@pytest.mark.asyncio
async def test_unconfirmed_contact_cannot_be_planned_against_an_unreadable_profile():
    writer = SimpleNamespace(data=AsyncMock(return_value=None))
    result = await _hold("synthetic-owner", {"call_id": "synthetic", "on": "2035-02-03"}, [], writer=writer)
    assert result["status"] == "failed"
    writer.data.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_write", ["memory_commit_episode", "memory_settle_unconfirmed"])
async def test_failed_episode_or_settlement_blocks_evaluation_but_preserves_committed_fact_evidence(failed_write):
    writes = [{"key": "budget_vnd", "value": 123000}]

    async def data(tool, **kwargs):
        if tool == failed_write:
            return None
        return {"memory_get_profile": {"facts": []}, "memory_get_episodes": {"episodes": []},
                "memory_commit_facts": {"memory_writes": writes}, "memory_commit_episode": {"episode_id": "synthetic"},
                "memory_settle_unconfirmed": {"settled": 1}}[tool]

    writer = SimpleNamespace(data=AsyncMock(side_effect=data))
    memory = SimpleNamespace(extract=AsyncMock(return_value=[]),
                             summarize=AsyncMock(return_value={"summary": "Synthetic episode", "outcome": "khac"}))
    result = await after_call({"call_id": "synthetic", "on": "2035-02-03", "tier": "VERIFIED",
                               "customer_id": "synthetic-owner", "channel": "hotline"},
                              [{"speaker": "customer", "text": "Hôm trước chị có gọi"}], [],
                              writer=writer, memory=memory, qa=SimpleNamespace(tag=AsyncMock(return_value={})))
    assert result["status"] == "failed" and result["memory_writes"] == writes


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["summary", "qa"])
async def test_later_model_failure_preserves_facts_already_committed_without_exposing_provider_message(stage):
    writes = [{"key": "budget_vnd", "value": 123000}]

    async def data(tool, **kwargs):
        return {"memory_get_profile": {"facts": []}, "memory_get_episodes": {"episodes": []},
                "memory_commit_facts": {"memory_writes": writes},
                "memory_commit_episode": {"episode_id": "synthetic"}}[tool]

    writer = SimpleNamespace(data=AsyncMock(side_effect=data))
    memory = SimpleNamespace(extract=AsyncMock(return_value=[]), summarize=AsyncMock(
        return_value={"summary": "Synthetic episode", "outcome": "khac"},
        side_effect=RuntimeError("private provider message") if stage == "summary" else None))
    qa = SimpleNamespace(tag=AsyncMock(return_value={},
        side_effect=RuntimeError("private provider message") if stage == "qa" else None))
    result = await after_call({"call_id": "synthetic", "on": "2035-02-03", "tier": "VERIFIED",
                               "customer_id": "synthetic-owner", "channel": "hotline"}, [], [],
                              writer=writer, memory=memory, qa=qa)
    assert result["status"] == "failed" and result["memory_writes"] == writes
    assert result["error"] == "RuntimeError" and "private provider message" not in str(result)
    if stage == "summary":
        assert "memory_commit_episode" not in [call.args[0] for call in writer.data.await_args_list]
