"""The customer's words without diacritics, as speech-to-text writes them, reach the ledger."""

import pytest

from ai_agent_service.agents.memory import CallMemory, MemoryAgent, rules_from_words


def said(*lines):
    return [{"speaker": "customer", "text": line, "turn": turn} for turn, line in enumerate(lines, 1)]


def slots(found):
    return {candidate.slot: candidate.value for candidate in found}


def test_rules_read_a_line_without_marks_as_they_read_it_with_them():
    plain = slots(rules_from_words(said("o anh can ban voi gia dinh nua, nha co be nho, mua hai cai")))
    assert plain["blocker"] == "cần hỏi người nhà"
    assert plain["decision_maker"] == "người nhà"
    assert plain["has_children"] is True and plain["quantity"] == 2


def test_a_stray_mark_does_not_turn_the_rule_off():
    assert slots(rules_from_words(said("de anh suy nghi thêm nhe")))["blocker"] == "cần suy nghĩ thêm"


def test_a_line_with_its_marks_is_held_to_them():
    assert "decision_maker" not in slots(rules_from_words(said("Em hỏi ba cái này giá bao nhiêu?")))


class Reader:
    async def ainvoke(self, prompt):
        return CallMemory()


@pytest.mark.asyncio
async def test_what_the_model_passes_over_the_rules_keep():
    agent = MemoryAgent(use_model=False)
    agent._labeller = Reader()
    found = await agent.extract(said("anh can ban voi gia dinh nua"), [], on="2026-10-16")
    assert slots(found)["blocker"] == "cần hỏi người nhà"
