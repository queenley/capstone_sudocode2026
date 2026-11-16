"""Plan 002, step 3: what the customer means is asked as the turn starts; the check before a write tool reuses it."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from ai_agent_service.agents import advisor as advisor_module
from ai_agent_service.agents.advisor import AdvisorEvent, AgentContext, Draft
from ai_agent_service.agents.policy import PolicyVerdict, band, early_verdict
from ai_agent_service.pipeline.hot import nodes
from ai_agent_service.pipeline.hot.state import HotContext


def test_only_a_clear_yes_stands_without_the_actions_own_check():
    assert early_verdict("purchase", 0.98) is True
    assert early_verdict("purchase", 0.8) is None  # above the old threshold, not clearly: asked again with the order
    assert early_verdict("purchase", 0.02) is None  # a no is never taken early: the full check may still say yes
    assert early_verdict("handoff", None) is None


def test_the_policy_agent_is_read_in_bands_not_at_one_threshold():
    assert [band("purchase", p) for p in (0.95, 0.75, 0.1, None)] == ["yes", "unsure", "no", "unanswered"]
    assert band("handoff", 0.74) == "unsure"  # the price question of the 2026-11-15 bench


async def ready(answers):
    return answers


def context(asked, early=None, **kw):
    async def judge(intent, state):
        asked.append(intent)
        return kw.pop("probability", 0.95)
    return AgentContext(call_id="c", judge=judge, early_intents=(lambda: ready(early)) if early is not None else None, **kw)


@pytest.mark.asyncio
async def test_the_check_before_a_write_tool_reuses_a_clear_early_answer():
    asked = []
    assert await advisor_module._verdict(context(asked, {"delete": 0.97}), "delete", {}) == "yes" and asked == []
    assert await advisor_module._verdict(context(asked, {"delete": 0.7}), "delete", {}) == "yes" and asked == ["delete"]
    # change needs the change itself: never taken from the early check
    await advisor_module._verdict(context(asked, {"change": 0.99}), "change", {})
    assert asked == ["delete", "change"]
    # a transfer the early check is all but certain nobody asked for is refused without asking again
    assert await advisor_module._verdict(context(asked, {"handoff": 0.01}), "handoff", {}) == "no"
    assert asked == ["delete", "change"]
    # the probabilities are kept for the turn's diagnostics
    kept = context(asked, {"handoff": 0.01})
    await advisor_module._verdict(kept, "handoff", {})
    assert kept.intent_probabilities == {"handoff:early": 0.01}


@pytest.mark.asyncio
async def test_unsure_takes_the_actions_safe_path():
    async def judge_at(p):
        async def judge(intent, state):
            return p
        return judge

    for p, expected in ((0.95, True), (0.6, False), (0.1, False), (None, None)):
        ctx = AgentContext(call_id="c", tier="VERIFIED", lane="NEW", judge=await judge_at(p))
        intents = await advisor_module._intents("memory_request_deletion", {}, ctx, [])
        assert intents == {"delete": expected}, p
    # a transfer: unsure lets a plain reason through, and "the documents do not say" only when nothing was found
    for reason, knowledge, expected in (("cau_hoi_y_te", (), True), ("ngoai_pham_vi_tai_lieu", (), True),
                                        ("ngoai_pham_vi_tai_lieu", ({"text": "BH-01 bảo hành 24 tháng", "score": 0.8},), False)):
        ctx = AgentContext(call_id="c", lane="NEW", judge=await judge_at(0.5), knowledge=knowledge)
        intents = await advisor_module._intents("handoff_transfer", {"brief": {"escalation_reason": reason}}, ctx, [])
        assert intents == {"handoff": expected}, reason


class Policy:
    def __init__(self):
        self.asked, self.cancelled = [], False

    async def probabilities(self, intents, state):
        self.asked.append(tuple(intents))
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {}

    async def review(self, view):
        return PolicyVerdict(passed=True)

    async def probability(self, intent, state):
        return None


class Says:
    def __init__(self, text):
        self.text, self.views = text, []

    def stream(self, messages, view, *, user_id=None):
        self.views.append(view)

        async def events():
            yield AdvisorEvent("text", text=self.text)
            yield AdvisorEvent("done", draft=Draft(text=self.text, tool_results=[], model="fixture", model_calls=1,
                                                   seconds=0.0))
        return events()


async def turn(lane, policy):
    state = {"call_id": "fixture", "turn_id": "t1", "mode": "speak", "tier": "VERIFIED", "lane": lane,
             "now": datetime.now(timezone.utc), "messages": [HumanMessage(content="Ừ lên đơn cho chị đi")]}
    advisor = Says("Dạ vâng ạ.")
    await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=advisor, policy=policy, emit=None)))
    await asyncio.sleep(0)
    return advisor


@pytest.mark.asyncio
async def test_asked_once_in_a_lane_with_write_tools_and_never_left_running(monkeypatch):
    monkeypatch.setenv("ADVISOR_EARLY_INTENTS", "1")
    policy = Policy()
    advisor = await turn("NEW", policy)
    assert policy.asked == [("purchase", "handoff", "delete", "one_more")]
    assert advisor.views[0].early_intents is not None
    assert policy.cancelled  # no write tool asked for it: cancelled as the turn ended


@pytest.mark.asyncio
async def test_not_asked_with_the_switch_off_or_in_a_lane_without_write_tools(monkeypatch):
    for switch, lane in (("0", "NEW"), ("1", "CLARIFY")):
        monkeypatch.setenv("ADVISOR_EARLY_INTENTS", switch)
        policy = Policy()
        advisor = await turn(lane, policy)
        assert policy.asked == [] and advisor.views[0].early_intents is None
