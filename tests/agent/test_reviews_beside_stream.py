"""The PolicyAgent runs beside the stream: a sentence is never held for it, a write always waits for it."""

import asyncio
import json
from datetime import datetime, timezone
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage

from ai_agent_service.agents import policy
from ai_agent_service.agents.advisor import ActionGuardMiddleware, AgentContext, _filled_order
from ai_agent_service.components.guardrails import hard, purchase
from ai_agent_service.components.intake.itn import amounts
from ai_agent_service.pipeline.hot.review import Reviews


def verdict(passed=True, reasons=(), failed=None):
    return SimpleNamespace(passed=passed, reasons=reasons, failed=failed if failed is not None else ("over_promise",) * len(reasons),
                           probabilities={}, decided_by="jev", seconds=0)


@pytest.mark.asyncio
async def test_sentences_arriving_during_a_review_go_together_in_the_next_one():
    release, seen = asyncio.Event(), []

    async def review(text, results):
        seen.append(text)
        await release.wait()
        return verdict()

    reviews = Reviews(review)
    reviews.add("một", ())
    await asyncio.sleep(0)
    reviews.add("hai", ())
    reviews.add("ba", ())
    release.set()
    await reviews.settle()
    assert seen == ["một", "hai ba"]


@pytest.mark.asyncio
async def test_a_flag_is_taken_once_and_a_write_sees_it_until_then():
    async def review(text, results):
        return verdict(False, ("sai",))

    reviews = Reviews(review)
    reviews.add("câu sai", ())
    assert await reviews.flags() == ["sai"]
    assert reviews.take() == ("câu sai", ["sai"])
    assert reviews.take() is None
    assert reviews.flagged == [{"text": "câu sai", "reasons": ["sai"]}]


@pytest.mark.asyncio
async def test_a_review_that_raises_is_a_review_not_done():
    async def review(text, results):
        raise RuntimeError("down")

    reviews = Reviews(review)
    reviews.add("câu", ())
    await reviews.settle()
    assert reviews.take() is None


@pytest.mark.asyncio
async def test_head_start_waits_at_most_its_moment():
    never = asyncio.Event()

    async def review(text, results):
        await never.wait()

    reviews = Reviews(review, head_start=0.01)
    reviews.add("câu", ())
    await asyncio.wait_for(reviews.head(), timeout=1)
    reviews.close()


def request_for(context, name="order_create", args=None):
    request = SimpleNamespace(tool_call={"id": "t", "name": name, "args": args or {"sku": "S", "price_vnd": 1}},
                              runtime=SimpleNamespace(context=context), state={"messages": []})
    request.override = lambda **changes: SimpleNamespace(**{**vars(request), **changes})
    return request


def context_for(**changes):
    base = AgentContext(call_id="c", turn_id="t2", customer_id="K", channel="zalo", tier="VERIFIED",
                        customer_phone="0900000000", now=datetime(2026, 11, 1, 10, tzinfo=timezone.utc),
                        on="2026-11-01", quotes={"S": 1_000_000}, trusted_skus=frozenset({"S"}))
    return replace(base, **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["order_create", "order_update", "schedule_callback", "handoff_transfer",
                                  "memory_request_deletion"])
async def test_a_tool_with_an_effect_does_not_run_on_a_flagged_sentence(name):
    handler = AsyncMock(return_value="executed")
    context = context_for(review_flags=AsyncMock(return_value=["sai"]))
    result = await ActionGuardMiddleware().awrap_tool_call(request_for(context, name), handler)
    assert json.loads(result.content)["error"]["code"] == "PRECONDITION"
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_read_tool_does_not_wait_for_reviews():
    flags, handler = AsyncMock(return_value=["sai"]), AsyncMock(return_value="executed")
    context = context_for(review_flags=flags)
    assert await ActionGuardMiddleware().awrap_tool_call(request_for(context, "catalog_search"), handler) == "executed"
    flags.assert_not_awaited()


@pytest.mark.asyncio
async def test_jev_decides_agreement_in_the_same_turn_and_the_read_back_is_owed():
    judged = []

    async def judge(intent, state):
        judged.append((intent, state["order"]))
        return True

    context = context_for(judge=judge, customer_said="Làm ơn lên đơn cho chị nhé", recent=(("customer", "lên đơn"),))
    handler = AsyncMock(return_value="executed")
    assert await ActionGuardMiddleware().awrap_tool_call(request_for(context), handler) == "executed"
    assert judged[0][0] == "purchase"
    assert context.consent["draft"]["status"] == "authorized"
    assert "1.000.000đ" in context.consent["read_back"]


@pytest.mark.asyncio
async def test_jev_saying_no_or_silent_places_no_order():
    handler = AsyncMock(return_value="executed")
    for answer in (False, None):
        context = context_for(judge=AsyncMock(return_value=answer), customer_said="để chị nghĩ thêm")
        result = await ActionGuardMiddleware().awrap_tool_call(request_for(context), handler)
        assert json.loads(result.content)["error"]["code"] == "CONFIRMATION_REQUIRED"
    handler.assert_not_awaited()


def test_code_fills_the_price_and_what_the_read_back_already_said():
    context = context_for(pending_purchase={"target_id": "S", "args": {"promo_code": "KM", "payment": "bank"}})
    order = _filled_order({"sku": "S", "price_vnd": 999, "payment": "COD"}, context, {"S": 1_000_000})
    assert order["price_vnd"] == 1_000_000  # the model's number never reaches the tool
    assert order["promo_code"] == "KM"  # left out: from the read-back
    assert order["payment"] == "COD"  # said by the model this turn: the customer's change stands


def test_half_a_million_is_read_rightly():
    assert amounts("khoảng 4 triệu rưỡi thôi") == [4_500_000]
    assert amounts("3 triệu 2") == [3_200_000]


@pytest.mark.parametrize("text", ["Dạ bên em không có mẫu đó ạ", "Em đã tạo đơn cho chị rồi ạ",
                                  "Em chuyển chị qua bạn phụ trách ngay ạ", "Sáng mai là hàng tới nơi ạ"])
def test_meaning_is_not_read_by_the_hard_check(text):
    assert hard.check(hard.GuardInput(text=text, tool_results=(), tier="VERIFIED")).passed


@pytest.mark.parametrize("text,passes", [
    ("em đề xuất gọi lại lúc 5 giờ 30 chiều", True),
    ("Dạ bảo hành 24 tháng ạ", False),
    ("Dạ máy giá 4.900.000đ ạ", False),
])
def test_numbers_are_compared_with_data(text, passes):
    assert hard.check(hard.GuardInput(text=text, tool_results=(), tier="VERIFIED")).passed is passes


def test_every_meaning_question_has_a_threshold_and_a_reason():
    assert set(policy.QUESTIONS) == set(policy.THRESHOLDS) == set(policy.REASONS)
    assert "purchase" in policy.INTENTS and "purchase" in policy.INTENT_THRESHOLDS


@pytest.mark.asyncio
async def test_a_claim_a_later_tool_makes_right_is_not_corrected():
    async def review(text, results):
        if results:
            return verdict()
        return verdict(False, ("chưa gọi",), ("false_transfer",))

    reviews = Reviews(review)
    reviews.add("Dạ em chuyển máy ạ.", ())
    assert await reviews.flags() == []  # it must not stop handoff_transfer itself
    await reviews.recheck(({"name": "handoff.transfer"},))
    assert reviews.take() is None and reviews.flagged == []


@pytest.mark.asyncio
async def test_a_claim_no_tool_made_right_is_corrected_when_the_answer_is_out():
    async def review(text, results):
        return verdict(False, ("chưa gọi",), ("false_transfer",))

    reviews = Reviews(review)
    reviews.add("Dạ em chuyển máy ạ.", ())
    await reviews.recheck(())
    assert reviews.take() == ("Dạ em chuyển máy ạ.", ["chưa gọi"])


def test_a_baskets_total_is_the_sum_of_todays_quotes():
    quotes = {"A": 7_690_000, "B": 1_590_000, "C": 590_000, "D": 990_000}
    view = lambda text: hard.GuardInput(text=text, tool_results=(), tier="VERIFIED", quotes=quotes)
    assert hard.check(view("Dạ tổng là 10.860.000đ ạ")).passed
    assert not hard.check(view("Dạ tổng là 10.860.001đ ạ")).passed


def test_the_cod_limit_is_the_shops_own_amount():
    assert hard.check(hard.GuardInput(text="Dạ đơn COD tối đa 10.000.000đ ạ", tool_results=(), tier="VERIFIED")).passed
