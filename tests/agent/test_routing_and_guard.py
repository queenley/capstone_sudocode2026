"""Lanes by rules (``docs/design.md`` 4.3) and the hard guard (3.2): no model, no database."""

import pytest

from ai_agent_service.components.guardrails import hard
from ai_agent_service.components.intake import signals
from ai_agent_service.components.orchestration.rules import RouteInput, decide


def route(**changes):
    view = dict(tier="UNKNOWN", has_brief=False, has_order=False,
                asr_low_conf=False, tool_failures=0, safe_lines=0, customer_said="xin chào")
    view.update(changes)
    # As perceive reads it: a PB-06 topic is a signal of the customer's words.
    view.setdefault("must_transfer", signals.read(view["customer_said"]).must_transfer)
    return decide(RouteInput(**view))


@pytest.mark.parametrize("changes,lane,rule", [
    ({}, "NEW", 7),
    ({"tool_failures": 2}, "HANDOFF", 1),
    ({"safe_lines": 2}, "HANDOFF", 1),
    ({"asr_low_conf": True}, "CLARIFY", 2),
    ({"tier": "PROBABLE"}, "CONFIRM_IDENTITY", 3),
    ({"tier": "AMBIGUOUS"}, "CONFIRM_IDENTITY", 3),
    ({"has_order": True, "customer_said": "đơn hàng của anh tới đâu rồi"}, "ORDER_SERVICE", 4),
    ({"customer_said": "tôi muốn khiếu nại pháp lý"}, "OUT_OF_SCOPE", 5),
    ({"tier": "VERIFIED", "has_brief": True}, "CONTINUITY", 6),
])
def test_lane_table(changes, lane, rule):
    decision = route(**changes)
    assert (decision.lane, decision.rule) == (lane, rule)


def test_first_matching_rule_wins():
    # Failing tools hand off even for a verified returning customer.
    assert route(tier="VERIFIED", has_brief=True, tool_failures=3).lane == "HANDOFF"


QUOTE = ({"name": "pricing.get_quote", "result": {"ok": True, "data": {"final_price_vnd": 17_500_000}}},)


def guard(text, tool_results=(), tier="UNKNOWN", **extra):
    return hard.check(hard.GuardInput(text=text, tool_results=tuple(tool_results), tier=tier, **extra))


def test_prices_must_come_from_this_turns_tools():
    assert guard("Dạ giá máy là 17.500.000đ ạ.", QUOTE).passed
    assert not guard("Dạ giá máy là 19.990.000đ ạ.", QUOTE).passed
    # Two units of a quoted price is derived, not invented.
    assert guard("Dạ hai máy là 35.000.000đ ạ.", QUOTE).passed


def test_customer_stated_amounts_may_be_repeated():
    assert guard("Dạ với ngân sách 20.000.000đ em gợi ý mẫu này ạ.",
                 customer_said=("ngân sách 20.000.000đ",)).passed


@pytest.mark.parametrize("text,tier", [
    ("Dạ mã đơn của anh là OD12345 ạ.", "UNKNOWN"),
    ("Dạ em là người thật ạ, không phải máy.", "VERIFIED"),
    ("Dạ số của anh là 0901234567 ạ.", "VERIFIED"),
    ("Dạ giá nhập của máy này thấp lắm ạ.", "VERIFIED"),
    ("The price of this laptop is very good and it ships tomorrow for sure.", "VERIFIED"),
    ("", "VERIFIED"),
])
def test_hard_guard_blocks(text, tier):
    assert not guard(text, tier=tier).passed


def test_order_code_is_read_only_to_a_verified_customer():
    assert guard("Dạ mã đơn của anh là OD12345 ạ.", tier="VERIFIED").passed


def test_tokens_from_another_call_are_a_leak():
    assert guard("Dạ em gọi lại số <PHONE_1> ạ.", tier="VERIFIED", tokens=frozenset({"<PHONE_1>"})).passed
    assert not guard("Dạ em gọi lại số <PHONE_2> ạ.", tier="VERIFIED", tokens=frozenset({"<PHONE_1>"})).passed


BY_AREA = {"name": "delivery_estimate", "args": {}, "result": {"ok": True, "data": {
    "address_known": False, "delivery_days": None, "estimated_delivery": None,
    "by_area": [{"area": "Hà Nội, TP.HCM, Đà Nẵng", "delivery_days": 2, "estimated_delivery": "2026-10-20"},
                {"area": "tỉnh thành khác", "delivery_days": 4, "estimated_delivery": "2026-10-22"}]}}}


@pytest.mark.parametrize("text, passes", [
    ("Dạ đơn thanh toán khi nhận hàng, giao trong 4 ngày tới ạ.", False),
    ("Dạ em nói là giao trong 2 ngày ạ.", False),
    ("Dạ nếu chị ở Hà Nội thì giao trong 2 ngày ạ.", True),
    ("Dạ nội thành TP.HCM giao 2 ngày, các tỉnh khác 4 ngày ạ.", True),
    ("Dạ Hà Nội, TP.HCM, Đà Nẵng 2 ngày, tỉnh thành khác 4 ngày ạ.", True),
    ("Dạ chị cho em xin địa chỉ để em báo thời gian giao chính xác ạ.", True),
])
def test_a_delivery_time_without_an_address_names_its_area(text, passes):
    assert guard(text, [BY_AREA]).passed is passes


def test_a_delivery_time_with_an_address_is_not_an_area_s():
    known = {"name": "delivery_estimate", "args": {"address": "Lê Chân, Hải Phòng"}, "result": {"ok": True, "data": {
        "address_known": True, "delivery_days": 4, "estimated_delivery": "2026-10-22"}}}
    assert guard("Dạ giao trong 4 ngày tới ạ.", [BY_AREA, known]).passed


@pytest.mark.parametrize("results, passes", [
    ([], False),
    ([{"name": "inventory_check", "result": {"ok": True, "data": {"sku": "SKU-T-1", "in_stock": True, "qty": 5}}}], False),
    ([{"name": "inventory_check", "result": {"ok": True, "data": {"sku": "SKU-T-1", "in_stock": False,
                                                                  "discontinued": True, "successor_sku": "SKU-T-2"}}}], True),
])
def test_a_product_said_no_longer_sold_needs_a_tool_saying_so(results, passes):
    assert guard("Dạ mẫu quạt này đã ngừng bán rồi ạ.", results, tier="VERIFIED").passed is passes


def test_a_product_the_shop_never_sold_is_not_a_discontinued_one():
    assert guard("Dạ hiện bên em chưa kinh doanh máy rửa bát ạ.", []).passed


@pytest.mark.parametrize("text", [
    "Dạ hiện bên em chưa kinh doanh dòng máy này ạ.",
    "Dạ mẫu đó bên em ngừng bán rồi ạ.",
    "Dạ em chưa có thông tin về sản phẩm này ạ.",
])
def test_a_claim_the_shop_lacks_a_product_goes_to_the_policy_check(text):
    """Whether such a claim is backed is a judgement on the whole reply: Jev's question, not a pattern of words."""
    from ai_agent_service.agents import policy
    assert policy.needs_review(text) and "unsupported_absence" in policy.QUESTIONS
