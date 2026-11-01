"""Actions that depend on what the customer means are decided in context by Jev, not by word lists.

``docs/design.md`` section 4.4. No network: Jev is a fixture.
"""

from types import SimpleNamespace

import pytest

from ai_agent_service.agents import policy as policy_module
from ai_agent_service.agents.advisor import AgentContext, _intents
from ai_agent_service.agents.policy import INTENT_THRESHOLDS, INTENTS, PolicyAgent
from ai_agent_service.components.guardrails import actions
from ai_agent_service.llm.jev import Answer, Decision, JevUnavailable
from ai_agent_service.pipeline.hot import nodes


BRIEF = {"customer_phone": "0900000001", "customer_name": "Lan", "escalation_reason": "cau_hoi_y_te",
         "conversation_summary": "Khách hỏi về thuốc khi cho con bú, trợ lý chưa có thông tin.",
         "product_advised": None, "price_quoted_vnd": None, "open_questions": [], "next_action": "Gọi lại",
         "generated_at": "2026-10-15T10:00:00+07:00"}


def handoff(warranted, lane="NEW"):
    return actions.check("handoff_transfer", {"brief": BRIEF}, tier="UNKNOWN", mode="speak", has_phone=True,
                         quotes={}, lane=lane, intents={"handoff": warranted})


def test_the_advisor_decides_a_transfer_and_jev_only_vetoes_an_unwarranted_one():
    assert handoff(True).passed
    assert handoff(None).passed  # Jev gave no answer: the advisor's decision stands
    refused = handoff(False)
    assert not refused.passed and "chưa cần chuyển máy" in refused.reasons[0]
    assert handoff(False, lane="HANDOFF").passed  # the harness's own transfer is never second-guessed


def test_a_deletion_needs_the_customers_agreement_read_by_jev():
    def delete(agreed, said="Ừ xóa đi em", asked="Anh xác nhận muốn xóa dữ liệu đúng không ạ?"):
        return actions.check("memory_request_deletion", {}, tier="VERIFIED", mode="speak", has_phone=True, quotes={},
                             intents={"delete": agreed}, customer_said=said, last_agent_said=asked)
    assert delete(True).passed and not delete(False).passed
    # Without Jev the word lists decide, as before.
    assert delete(None).passed and not delete(None, said="Thôi để sau").passed


def test_one_more_order_of_the_same_product_is_read_by_jev():
    def create(wants_more, said="Giao ở quận 3 nhé"):
        return actions.check("order_create", {"sku": "SKU-A", "price_vnd": 1_000_000, "qty": 1, "payment": "COD"},
                             tier="VERIFIED", mode="speak", has_phone=True, quotes={"SKU-A": 1_000_000},
                             trusted=frozenset({"SKU-A"}), created=[{"order_id": "OD1", "sku": "SKU-A"}],
                             customer_said=said, intents={"one_more": wants_more})
    assert create(True).passed and not create(False).passed
    assert not create(None).passed and create(None, said="Cho chị lấy thêm một cái nữa").passed


class Judge:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    async def __call__(self, intent, state):
        self.asked.append((intent, state))
        return self.answer


@pytest.mark.asyncio
async def test_jev_is_asked_only_when_the_action_depends_on_the_customer():
    judge = Judge(True)
    context = AgentContext(call_id="x", tier="VERIFIED", lane="NEW", judge=judge,
                           recent=(("customer", "Cho chị nói chuyện với người hiểu chuyện này nhé"),))
    assert await _intents("handoff_transfer", {"brief": BRIEF}, context, ()) == {"handoff": True}
    assert judge.asked[-1][1]["recent_messages"][0]["speaker"] == "customer"
    assert await _intents("memory_request_deletion", {}, context, ()) == {"delete": True}
    assert await _intents("order_create", {"sku": "SKU-A"}, context, ()) == {}  # nothing ordered yet
    assert await _intents("order_create", {"sku": "SKU-A"}, context, ({"sku": "SKU-A"},)) == {"one_more": True}
    assert await _intents("order_update", {"order_id": "OD1", "action": "exchange_size"}, context, ()) == {"change": True}
    assert judge.asked[-1][1]["change"] == {"order_id": "OD1", "action": "exchange_size"}
    assert await _intents("schedule_callback", {}, context, ()) == {}
    asked = len(judge.asked)
    in_handoff_lane = AgentContext(call_id="x", tier="VERIFIED", lane="HANDOFF", judge=judge)
    assert await _intents("handoff_transfer", {"brief": BRIEF}, in_handoff_lane, ()) == {}
    assert len(judge.asked) == asked


class FakePolicy(PolicyAgent):
    def __init__(self, probability=None):
        self.probability = probability

    async def evaluate(self, state, questions):
        if self.probability is None:
            raise JevUnavailable("TIMEOUT", "fixture")
        name = next(iter(questions))
        return Decision(model="jev", seconds=0.1,
                        answers={name: Answer(type="boolean", probability=self.probability)})


@pytest.mark.asyncio
async def test_judge_turns_a_probability_into_a_decision_and_says_when_it_has_none():
    assert set(INTENTS) == set(INTENT_THRESHOLDS)
    assert await FakePolicy(0.9).judge("handoff", {}) is True
    assert await FakePolicy(0.2).judge("handoff", {}) is False
    # A wrong "yes" to an identity opens someone else's data: its bar is higher than a transfer's.
    assert INTENT_THRESHOLDS["identity"] > INTENT_THRESHOLDS["handoff"]
    assert await FakePolicy(0.55).judge("identity", {}) is False
    assert await FakePolicy(0.55).judge("handoff", {}) is True
    assert await FakePolicy(None).judge("delete", {}) is None


@pytest.mark.asyncio
async def test_identity_confirmation_is_read_by_jev_with_the_word_list_as_fallback():
    state = {"messages": []}
    assert await nodes._confirms(state, SimpleNamespace(policy=FakePolicy(0.95)), "ừ nhưng không phải chị") is True
    assert await nodes._confirms(state, SimpleNamespace(policy=FakePolicy(0.1)), "đúng rồi em") is False
    assert await nodes._confirms(state, SimpleNamespace(policy=FakePolicy(None)), "đúng rồi em") is True
    assert await nodes._confirms(state, SimpleNamespace(policy=None), "không phải chị đâu") is False


def test_the_word_lists_that_decided_for_the_customer_are_gone():
    from ai_agent_service.components.intake import signals
    for name in ("WANTS_PERSON", "COMPLAINT", "ASKS_IF_HUMAN", "WANTS_DELETION"):
        assert not hasattr(signals, name)
    assert set(signals.read("chuyển máy cho tôi").as_flags()) == {"impatient", "must_transfer"}
    assert policy_module.INTENTS["handoff"].criteria


def test_an_order_is_changed_only_once_the_customer_chose_the_change():
    # FIX-05: "size M hơi chật" is a complaint, not a choice; the advisor proposes and asks first (rule 20).
    def update(agreed):
        return actions.check("order_update", {"order_id": "OD1", "action": "exchange_size", "new_variant_sku": "SKU-L"},
                             tier="VERIFIED", mode="speak", has_phone=True, quotes={}, orders=frozenset({"OD1"}),
                             trusted=frozenset({"SKU-L"}), intents={"change": agreed})
    refused = update(False)
    assert not refused.passed and "luật 20" in refused.reasons[0]
    assert update(True).passed and update(None).passed
