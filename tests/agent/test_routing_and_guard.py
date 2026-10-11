"""Lanes by rules (``docs/design.md`` 4.3) and the hard guard (3.2): no model, no database."""

import pytest

from ai_agent_service.components.guardrails import hard
from ai_agent_service.components.orchestration.rules import RouteInput, decide


def route(**changes):
    view = dict(tier="UNKNOWN", has_brief=False, brief_mismatch=False, has_order=False,
                asr_low_conf=False, tool_failures=0, safe_lines=0, customer_said="xin chào")
    view.update(changes)
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
