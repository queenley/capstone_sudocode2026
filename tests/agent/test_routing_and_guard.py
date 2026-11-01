"""Lanes by rules (``docs/design.md`` 4.3) and the hard guard (3.2): no model, no database."""

import pytest

from ai_agent_service.components.guardrails import hard
from ai_agent_service.components.intake import signals
from ai_agent_service.components.orchestration.rules import RouteInput, decide


def route(customer_said="xin chào", **changes):
    view = dict(tier="UNKNOWN", has_brief=False, asr_low_conf=False, tool_failures=0)
    view.update(changes)
    # As perceive reads it: a PB-06 topic is a signal of the customer's words.
    view.setdefault("must_transfer", signals.read(customer_said).must_transfer)
    return decide(RouteInput(**view))


@pytest.mark.parametrize("changes,lane,rule", [
    ({}, "NEW", 5),
    ({"tool_failures": 2}, "HANDOFF", 1),
    ({"model_failures": 2}, "HANDOFF", 1),
    ({"asr_low_conf": True}, "CLARIFY", 2),
    ({"tier": "PROBABLE"}, "CONFIRM_IDENTITY", 3),
    ({"tier": "AMBIGUOUS"}, "CONFIRM_IDENTITY", 3),
    ({"tier": "VERIFIED", "has_brief": True}, "CONTINUITY", 4),
])
def test_lane_table(changes, lane, rule):
    decision = route(**changes)
    assert (decision.lane, decision.rule) == (lane, rule)


def test_safe_lines_never_hand_the_call_over():
    # A guard that blocked wrongly twice must not become a transfer (over_escalation).
    assert decide(RouteInput(tier="VERIFIED", has_brief=True, asr_low_conf=False, tool_failures=0)).lane == "CONTINUITY"
    assert not hasattr(RouteInput, "safe_lines")


def test_first_matching_rule_wins():
    # Failing tools hand off even for a verified returning customer.
    assert route(tier="VERIFIED", has_brief=True, tool_failures=3).lane == "HANDOFF"


@pytest.mark.parametrize("said", ["Đơn hàng của anh tới đâu rồi?", "Thôi chị đổi sang hỏi áo khoác nhé",
                                  "Cho chị hỏi máy lọc nước loại nào tốt", "Tôi muốn khiếu nại pháp lý"])
def test_the_words_never_choose_the_lane(said):
    # What a turn is about is the advisor's to read: the same state routes the same whatever is said.
    assert route(said, tier="VERIFIED", has_brief=True).lane == "CONTINUITY"
    assert route(said).lane == "NEW"


def test_a_pb06_topic_is_a_note_not_a_lane():
    # "cho con bú" names the topic of a product the shop sells; the advisor tells advice from a product question.
    decision = route("Máy hút sữa cho con bú loại nào êm vậy em?", tier="VERIFIED", has_brief=True)
    assert decision.lane == "CONTINUITY"
    assert any("PB-06" in note for note in decision.notes)
    assert not any("PB-06" in note for note in route("Máy lọc nước loại nào tốt").notes)


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
    assert guard("Dạ bên kia báo 3.200.000đ thì em chưa so sánh được ạ.",
                 customer_said=("bên kia bán có 3.200.000đ thôi",)).passed


def test_whether_a_customer_amount_is_passed_off_as_the_shops_is_the_policy_agents_call():
    # A word list cannot tell "khuyến mãi giảm 500.000đ đã hết" from "bên em giảm 500.000đ" (SAMPLE-05):
    # the hard check lets the customer's figure through, and Jev reads what the sentence means.
    from ai_agent_service.agents.policy import QUESTIONS, THRESHOLDS
    said = ("Sao hôm trước em bảo giảm 500k mà?",)
    assert guard("Dạ khuyến mãi giảm 500.000đ hôm trước đã hết hạn rồi ạ.", customer_said=said).passed
    assert "unquoted_price" in QUESTIONS and THRESHOLDS["unquoted_price"] < 1


SEARCH = ({"name": "catalog.search", "result": {"ok": True, "data": {"items": [
    {"sku": "SKU-X", "list_price_vnd": 4_890_000}, {"sku": "SKU-Y", "list_price_vnd": 5_200_000}]}}},)
QUOTED = ({"name": "pricing.get_quote", "result": {"ok": True, "data": {
    "sku": "SKU-AP-PRO", "list_price_vnd": 7_990_000, "final_price_vnd": 7_690_000,
    "applied_promos": [{"promo_code": "AIR-OCT", "discount_vnd": 300_000}]}}},)


def test_a_difference_needs_operands_that_belong_together():
    # A quote's list and final price: the saving is derived.
    assert guard("Dạ máy được giảm 300.000đ, còn 7.690.000đ ạ.", QUOTED).passed
    # Two unrelated products of a search: their difference is not a discount anyone gave.
    assert not guard("Dạ mẫu này đang được giảm 310.000đ ạ.", SEARCH).passed
    # Today's quote against the price the brief says was quoted: a change since the last call.
    assert guard("Dạ giá hôm nay thấp hơn hôm trước 310.000đ ạ.", tier="VERIFIED",
                 quotes={"SKU-AP-PRO": 7_690_000}, brief_prices=(8_000_000,)).passed


def test_only_the_organisers_documents_are_a_source_of_amounts():
    faq = "Phí lắp đặt tại nhà là 200.000đ."
    assert not guard("Dạ phí lắp đặt là 200.000đ ạ.", policy_texts=(faq,)).passed
    assert guard("Dạ phí lắp đặt là 200.000đ ạ.", policy_texts=(faq,), priced_texts=(faq,)).passed


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
