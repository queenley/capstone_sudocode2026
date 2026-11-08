"""Every amount still needs a source; these are sources the guard failed to see (eval2, 2026-11-07)."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from ai_agent_service.agents import policy as policy_agent
from ai_agent_service.agents.policy import PolicyAgent, PolicyInput
from ai_agent_service.components.guardrails import actions, hard
from ai_agent_service.components.guardrails.hard import GuardInput, open_amounts
from ai_agent_service.components.intake.itn import amounts

RESULT = {"name": "pricing.get_quote", "result": {"ok": True, "data": {"sku": "A", "final_price_vnd": 4890000}}}


def view(text, **more):
    return GuardInput(text=text, tool_results=(), tier="VERIFIED", **more)


def money(text, **more):
    return hard._money(text, view(text, **more))


@pytest.mark.parametrize("text, value", [("5 triệu rưỡi", 5_500_000), ("tám triệu rưỡi", 8_500_000), ("3 triệu", 3_000_000)])
def test_half_a_million_is_read_either_way(text, value):
    assert amounts(text) == [value]


@pytest.mark.parametrize("text", ["công suất 1.400 W", "công suất 2.000W", "dung tích 1.500 ml", "pin 5.000 mAh"])
def test_a_measure_is_not_money(text):
    assert amounts(text) == []


def test_a_bare_grouped_number_is_still_money():
    assert amounts("giá 4.890.000") == [4_890_000]


def test_a_price_of_an_earlier_turn_may_be_repeated():
    assert money("Máy này giá 4.890.000đ ạ.", earlier_numbers=frozenset({4_890_000})) == []


def test_a_price_nothing_gave_is_still_refused():
    assert money("Máy này giá 4.000.000đ ạ.", earlier_numbers=frozenset({4_890_000}))


def test_small_numbers_of_the_call_do_not_become_money():
    assert 500 not in hard.allowed_amounts(view("x", earlier_numbers=frozenset({500})))


@pytest.mark.parametrize("said, reply", [
    ("chi co be 13 thang ngan sach tam 500 ngan thoi", "Dạ với ngân sách tầm 500.000đ ạ."),
    ("chi co ngan sach khoang 2 trieu thoi", "Dạ với ngân sách khoảng 2 triệu ạ."),
    ("ngan sach 5 trieu ruoi", "Dạ trong ngân sách 5 triệu rưỡi ạ."),
    ("Chị có ngân sách khoảng 8 triệu rưỡi thôi.", "Dạ với ngân sách khoảng tám triệu rưỡi ạ."),
])
def test_the_customers_own_figure_is_theirs_however_it_was_typed(said, reply):
    assert money(reply, customer_said=(said,)) == []


def test_the_total_of_this_calls_quotes_is_derived_and_a_wrong_total_is_not():
    quotes = {"A": 7_690_000, "B": 3_245_000}
    assert money("Tổng hai máy là 10.935.000đ ạ.", quotes=quotes) == []
    assert money("Tổng hai máy là 11.380.000đ ạ.", quotes=quotes)


def test_a_rate_of_the_documents_applied_to_a_price():
    passage = ("Gói bảo hành mở rộng với giá bằng 8% giá sản phẩm.",)
    assert money("Gói này là 551.200đ ạ.", priced_texts=passage, earlier_numbers=frozenset({6_890_000})) == []
    assert money("Gói này là 600.000đ ạ.", priced_texts=passage, earlier_numbers=frozenset({6_890_000}))


@pytest.mark.parametrize("sentence", [
    "Em thấy chị đã được tư vấn máy này và báo giá 4.290.000đ ạ.",
    "Chị đã hỏi máy này với giá 4.290.000đ hôm 13/11 rồi ạ.",
])
def test_a_later_call_may_recall_the_briefs_price(sentence):
    assert money(sentence, brief_prices=(4_290_000,)) == []


def test_only_the_customers_figure_is_left_for_the_policy_agent():
    text = "Với ngân sách 7 triệu, máy này giá 5.990.000đ ạ."
    assert open_amounts(view(text, customer_said=("ngân sách 7 triệu",), earlier_numbers=frozenset({5_990_000}))) == (7_000_000,)
    assert open_amounts(view("Máy này giá 5.990.000đ ạ.", earlier_numbers=frozenset({5_990_000}))) == ()


def review(monkeypatch, open_amount, probability=0.99):
    """The PolicyAgent on a stand-in for the Decisions API; what it was shown, as text."""
    async def evaluate(name, messages, questions, **_):
        answers = {q: SimpleNamespace(probability=0.0) for q in questions}
        answers["unquoted_price"] = SimpleNamespace(probability=probability)
        return SimpleNamespace(answers=answers, seconds=0.1, cached_tokens=0, input_tokens=0)

    monkeypatch.setattr(policy_agent.decisions, "evaluate", evaluate)
    agent = PolicyAgent.__new__(PolicyAgent)
    agent.name = "policy"
    shown = PolicyInput(text="x", tool_results=(), tier="VERIFIED", open_amounts=open_amount)
    verdict = asyncio.run(agent.review(shown))
    return verdict, json.dumps(policy_agent.review_input(shown), ensure_ascii=False)


def test_with_every_amount_traced_the_price_question_cannot_block(monkeypatch):
    verdict, seen = review(monkeypatch, ())
    assert verdict.passed and "amounts_without_source" in seen


def test_a_figure_with_no_source_can_still_be_judged(monkeypatch):
    verdict, seen = review(monkeypatch, (7_000_000,))
    assert not verdict.passed and verdict.reasons == (policy_agent.REASONS["unquoted_price"],)
    assert "7.000.000đ" in seen


def test_a_review_without_the_hard_check_keeps_the_question(monkeypatch):
    verdict, seen = review(monkeypatch, None)
    assert not verdict.passed and "amounts_without_source" not in seen




NOON = "2026-10-20T10:00"


def callback(args, has_phone):
    from ai_agent_service.components import clock

    return actions._schedule_callback(args, now=clock.parse_local(NOON), has_phone=has_phone)


def test_a_call_back_without_a_number_asks_for_it():
    assert "hỏi số" in callback({"callback_at": "2026-10-21T10:00"}, False)[0]


@pytest.mark.parametrize("args, has_phone", [({"callback_at": "2026-10-21T10:00"}, True),
                                             ({"callback_at": "2026-10-21T10:00", "customer_phone": "0912345678"}, False)])
def test_a_known_number_books(args, has_phone):
    assert callback(args, has_phone) == []
