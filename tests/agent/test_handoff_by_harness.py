"""A call put through to a person by the harness itself (route rule 1, ``docs/design.md`` 4.9).

No model and no database: the advisor fails on purpose, the harness's tools are a fixture.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from ai_agent_service.components.guardrails import fallback
from ai_agent_service.pipeline.hot import nodes
from ai_agent_service.pipeline.hot.state import HotContext


class Tools:
    """The harness's ToolBox: records what was called, answers like the organisers' mock."""

    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    async def call(self, name, /, **args):
        self.calls.append((name, args))
        if not self.ok:
            return {"ok": False, "error": {"code": "TIMEOUT", "retryable": True, "message": "slow"}}
        return {"ok": True, "data": {"ticket_id": "HT0001", "status": "queued", "brief_ok": True}}


class Broken:
    """An advisor whose model never answers."""

    async def draft(self, *args, **kwargs):
        raise RuntimeError("model down")


def state(**extra):
    base = {"call_id": "fixture", "turn_id": "t3", "turn_no": 3, "tier": "UNKNOWN", "lane": "NEW",
            "channel": "web", "now": datetime(2026, 10, 15, 10, tzinfo=timezone.utc),
            "messages": [HumanMessage(content="Cho em hỏi máy lọc nước giá bao nhiêu", id="c3")]}
    return {**base, **extra}


async def advise(tools, **extra):
    context = HotContext(advisor=Broken(), harness=tools)
    return await nodes.advisor(state(**extra), SimpleNamespace(context=context))


@pytest.mark.asyncio
async def test_a_first_model_failure_asks_again_and_is_counted():
    tools = Tools()
    update = await advise(tools)
    assert update["model_failures"] == 1
    assert update["draft"]["text"] == fallback.line("model_error", "anh/chị")
    assert tools.calls == []


@pytest.mark.asyncio
async def test_a_second_model_failure_in_a_row_puts_the_call_through_in_the_same_turn():
    tools = Tools()
    update = await advise(tools, model_failures=1)
    assert [name for name, _ in tools.calls] == ["handoff_transfer"]
    brief = tools.calls[0][1]["brief"]
    assert brief["escalation_reason"] == "loi_he_thong"
    assert "máy lọc nước" in brief["conversation_summary"] and len(brief["conversation_summary"]) >= 20
    assert update["draft"]["text"] == fallback.LINES["bridging"]
    assert update["model_failures"] == 0
    transfer = update["tool_results"][-1]
    assert transfer["name"] == "handoff.transfer" and transfer["result"]["ok"]


@pytest.mark.asyncio
async def test_the_handoff_lane_transfers_without_a_model():
    tools = Tools()
    update = await advise(tools, lane="HANDOFF", route_reason="tools failing", tool_failures=2)
    assert [name for name, _ in tools.calls] == ["handoff_transfer"]
    assert "tra cứu" in tools.calls[0][1]["brief"]["escalation_reason_detail"]
    assert update["draft"]["text"] == fallback.LINES["bridging"]


@pytest.mark.asyncio
async def test_no_bridging_line_when_the_transfer_failed():
    update = await advise(Tools(ok=False), lane="HANDOFF", route_reason="tools failing")
    assert not fallback.is_bridging(update["draft"]["text"])
    assert update["draft"]["fallback"]


@pytest.mark.asyncio
async def test_a_call_already_handed_over_is_not_handed_over_twice():
    tools = Tools()
    update = await advise(tools, lane="HANDOFF", handoff={"status": "accepted"})
    assert tools.calls == []
    assert not fallback.is_bridging(update["draft"]["text"])


def respond_state(**extra):
    transfer = {"name": "handoff.transfer", "args": {"brief": {"escalation_reason": "loi_he_thong"}},
                "result": {"ok": True, "data": {"ticket_id": "HT0001"}}}
    return state(draft={"text": fallback.LINES["bridging"]}, tool_results=[transfer], mode="speak",
                 tool_failures=2, safe_lines=1, **extra)


@pytest.mark.asyncio
async def test_without_the_switch_a_handoff_waits_for_a_consultant(monkeypatch):
    monkeypatch.delenv("HANDOFF_AUTO_ACCEPT", raising=False)
    update = await nodes.respond(respond_state(), SimpleNamespace(context=HotContext()))
    assert update["mode"] == "copilot"
    assert update["handoff"]["status"] == "pending" and update["handoff"]["accepted_by"] is None
    assert (update["tool_failures"], update["model_failures"], update["safe_lines"]) == (0, 0, 0)


@pytest.mark.asyncio
async def test_with_the_switch_the_system_accepts_and_the_agent_goes_on(monkeypatch):
    monkeypatch.setenv("HANDOFF_AUTO_ACCEPT", "1")
    update = await nodes.respond(respond_state(), SimpleNamespace(context=HotContext()))
    assert update["mode"] == "speak"
    assert update["handoff"]["status"] == "accepted" and update["handoff"]["accepted_by"] == nodes.AUTO_ACCEPTOR
    assert update["handoff"]["ticket_id"] == "HT0001"


def test_the_advisor_is_told_to_transfer_when_the_documents_have_no_answer():
    # A fact of the retrieval, not a reading of the words: the search abstained (BTC: transfer is a success).
    assert "handoff_transfer" in nodes._knowledge_note({"knowledge": {"reason": "no_match", "abstain": True}})
    assert "ngoai_pham_vi_tai_lieu" in nodes._knowledge_note({"knowledge": {"reason": "absence", "abstain": True}})
    assert nodes._knowledge_note({"knowledge": {"reason": "restricted", "abstain": True}}) is None
    assert nodes._knowledge_note({"knowledge": {"reason": None, "abstain": False}}) is None
    assert nodes._knowledge_note({}) is None


def test_one_bridging_line_whatever_the_model_called_it():
    assert fallback.is_bridging("Dạ em chuyển máy cho nhân viên phụ trách hỗ trợ anh chị ngay ạ.")
    assert not fallback.is_bridging("Dạ máy này chuyển chế độ ngủ được ạ.")
