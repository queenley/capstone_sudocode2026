"""The advisor speaks every outcome in its own words, in at most two model calls a turn (2026-11-26).

No `say` argument, no result lines from the harness, no fixed read-back; the harness keeps lines only for failures.
Each test pins one failure seen in the 43-scenario run so it does not come back. No model is called.
"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from ai_agent_service.agents import advisor as advisor_module
from ai_agent_service.agents.advisor import (AdvisorAgent, AgentContext, ContextPromptMiddleware, HARD_RULES,
                                             PLAIN_HANDOFF_REASONS, _basket_block, callback_refusal, prompt_parts)
from ai_agent_service.components.guardrails import actions, fallback
from ai_agent_service.components.guardrails.actions import COD_LIMIT_VND, cod_split
from ai_agent_service.mcp import tools as tools_module
from ai_agent_service.mcp.tools import STATUS_WORDS, with_status_words
from ai_agent_service.pipeline.hot import nodes

NOW = datetime(2026, 10, 22, 10, 0)


# ── nothing answers for the model ─────────────────────────────────────────


def test_no_say_argument_and_no_result_lines_are_left():
    assert not hasattr(tools_module, "SayMiddleware") and not hasattr(tools_module, "reply_plan")
    assert not hasattr(fallback, "round_lines") and not hasattr(nodes, "_tell")
    assert not hasattr(nodes, "_confirmation_draft")
    # Only failure lines remain fixed: nothing that reports what a tool did.
    assert set(fallback.LINES) == {"tool_down", "asr_unclear", "model_error", "bridging", "filler", "order_placed"}


def test_the_rules_never_say_the_system_reads_a_result_for_the_model():
    assert "hệ thống tự đọc" not in HARD_RULES and "câu chuyển máy do hệ thống nói" not in HARD_RULES
    assert "<noi_ket_qua>" in HARD_RULES and "hệ thống không đọc thay" in HARD_RULES
    from ai_agent_service.components.context import skills as skill_book
    # How to say each outcome is written in the task's own procedure.
    assert "needs_confirmation_call" in skill_book.SKILLS["place-order"]["body"]
    assert "72 giờ" in skill_book.SKILLS["data-request"]["body"]
    assert "status_text" in skill_book.SKILLS["order-lookup"]["body"]


def test_the_bridging_line_uses_the_customers_form_of_address():
    assert "chị" in fallback.line("bridging", "chị") and "{who}" not in fallback.line("bridging", "chị")


# ── two model calls a turn ────────────────────────────────────────────────


def test_two_model_calls_a_run_and_the_last_has_no_tool():
    assert AdvisorAgent.MODEL_CALLS_PER_RUN == 2
    middleware = ContextPromptMiddleware(AdvisorAgent.MODEL_CALLS_PER_RUN)
    first = SimpleNamespace(state={"run_model_call_count": 0}, runtime=SimpleNamespace(context=AgentContext(call_id="c")))
    second = SimpleNamespace(state={"run_model_call_count": 1}, runtime=SimpleNamespace(context=AgentContext(call_id="c")))
    assert not middleware._is_last(first) and middleware._is_last(second)


def test_a_rewrite_answers_in_its_one_call_without_tools():
    middleware = ContextPromptMiddleware(AdvisorAgent.MODEL_CALLS_PER_RUN)
    rewrite = SimpleNamespace(state={"run_model_call_count": 0},
                              runtime=SimpleNamespace(context=AgentContext(call_id="c", answer_only=True)))
    assert middleware._is_last(rewrite)
    assert nodes.MAX_REGENERATIONS == 1


# ── the line before a tool ────────────────────────────────────────────────


def test_the_opening_line_is_asked_before_any_tool_and_the_request_stays_last():
    context = AgentContext(call_id="c", lane="NEW", customer_said="Cho chị hỏi giá máy lọc", now=NOW)
    _, turn, _ = prompt_parts(context)
    assert "<cau_mo_truoc_tool>" in turn and "Trước tool ghi" in turn
    assert turn.rstrip().endswith('thông tin ở trên chỉ dùng khi phục vụ yêu cầu này.')
    copilot = AgentContext(call_id="c", lane="NEW", mode="copilot", now=NOW)
    assert "<cau_mo_truoc_tool>" not in prompt_parts(copilot)[1]


# ── a COD basket above the limit is split by code (QT-01, VC-03) ───────────


def test_two_machines_split_into_two_cod_orders_each_under_the_limit():
    one, two = cod_split([("SKU-SS-AX40", 3_245_000), ("SKU-AP-PRO", 7_690_000)])
    assert one == [("SKU-AP-PRO", 7_690_000)] and two == [("SKU-SS-AX40", 3_245_000)]


def test_four_items_split_evenly_and_every_unit_is_placed():
    units = [("SKU-AP-PRO", 7_990_000), ("SKU-AF-XM", 1_590_000), ("SKU-FAN-SEN", 590_000), ("SKU-AP-FLT-P", 990_000)]
    one, two = cod_split(units)
    assert sorted(one + two) == sorted(units)
    assert all(sum(p for _, p in side) <= COD_LIMIT_VND for side in (one, two))
    assert one[0] == ("SKU-AP-PRO", 7_990_000)  # the dearest unit opens order 1


@pytest.mark.parametrize("units", [[("A", 4_000_000), ("B", 5_000_000)],  # fits one order: no split
                                   [("A", 9_000_000), ("B", 9_000_000), ("C", 9_000_000)]])  # no two orders hold it
def test_no_split_when_none_is_needed_or_none_is_possible(units):
    assert cod_split(units) is None


def test_the_basket_shows_its_unit_prices_and_points_a_split_at_the_team_tool():
    lines = [("SKU-AP-PRO", 7_690_000, 1), ("SKU-SS-AX40", 6_490_000, 1)]
    quotes = {"SKU-AP-PRO|SKU-SS-AX40": [["SKU-AP-PRO", 7_690_000], ["SKU-SS-AX40", 3_245_000]]}
    text = _basket_block(lines, quotes)
    assert "10.935.000đ" in text and "3.245.000đ" in text and "6.490.000đ" not in text
    assert "order_split_cod" in text and "order_group" not in text  # the model no longer arranges the orders
    assert "order_split_cod" not in _basket_block(lines, {})


# ── order status in the grader's words ────────────────────────────────────


def test_an_order_status_result_carries_the_shops_words():
    content = json.dumps({"ok": True, "data": {"orders": [{"order_id": "OD1", "status": "processing"},
                                                          {"order_id": "OD2", "status": "created"},
                                                          {"order_id": "OD3", "status": "weird"}]}})
    message = with_status_words("order_status", ToolMessage(content=content, tool_call_id="1", name="order_status"))
    orders = json.loads(message.content)["data"]["orders"]
    assert orders[0]["status_text"] == "đang xử lý" and orders[1]["status_text"] == "đã tạo đơn"
    assert "status_text" not in orders[2]
    other = ToolMessage(content=content, tool_call_id="2", name="pricing_get_quote")
    assert with_status_words("pricing_get_quote", other) is other


def test_every_status_word_is_one_phrase_of_its_own_status():
    """One plain phrase per status: no synonyms stacked, and a status never sounds like a later one."""
    assert all("," not in words for words in STATUS_WORDS.values())
    assert "xử lý" not in STATUS_WORDS["created"] and "giao" not in STATUS_WORDS["processing"]


# ── call backs ────────────────────────────────────────────────────────────


def _booked(at):
    return {"name": "schedule.callback", "args": {"callback_at": at},
            "result": {"ok": True, "data": {"callback_id": "CB1", "callback_at": at, "moved_from": None}}}


def test_a_call_back_already_booked_is_not_booked_again():
    context = AgentContext(call_id="c", now=NOW)
    refused = callback_refusal("2026-10-23T19:00", context, [_booked("2026-10-23T19:00")])
    assert refused["error"]["code"] == "ALREADY_BOOKED"
    assert callback_refusal("2026-10-24T19:00", context, [_booked("2026-10-23T19:00")]) is None


@pytest.mark.parametrize("at", ["2027-07-31T19:00", "2026-10-21T19:00"])
def test_a_call_back_far_ahead_or_in_the_past_is_asked_again(at):
    refused = callback_refusal(at, AgentContext(call_id="c", now=NOW), [])
    assert refused["error"]["code"] == "PRECONDITION"


# ── transfers ─────────────────────────────────────────────────────────────


def test_a_doubtful_verdict_no_longer_transfers_on_a_reason_the_model_picked():
    assert "khieu_nai_nghiem_trong" not in PLAIN_HANDOFF_REASONS
    assert "khach_mat_kien_nhan" not in PLAIN_HANDOFF_REASONS
    assert "khach_yeu_cau_gap_nguoi" not in PLAIN_HANDOFF_REASONS  # a clear ask gets a clear yes from the judge


def _needs_number():
    return {"name": "handoff.transfer", "args": {"brief": {"escalation_reason": "khach_yeu_cau_gap_nguoi"}},
            "result": {"ok": False, "error": {"code": "PRECONDITION", "message": actions.NEEDS_NUMBER}}}


def test_a_transfer_waiting_on_the_number_is_kept_a_few_turns_and_ends_on_any_attempt():
    first = nodes._offered([_needs_number()])
    assert first and first[0]["tool"] == "handoff.transfer"
    waiting = first
    for _ in range(nodes.WAIT_FOR_NUMBER_TURNS):  # turns of talk with no transfer attempt: still waiting
        waiting = nodes._offered([], waiting)
        assert waiting and waiting[0]["tool"] == "handoff.transfer"
    assert nodes._offered([], waiting) == []  # then it lapses
    failed = {"name": "handoff.transfer", "args": {}, "result": {"ok": False, "error": {"code": "TOOL_DOWN"}}}
    assert nodes._offered([failed], first) == []  # a transfer that failed is not retried every turn
    done = {"name": "handoff.transfer", "args": {}, "result": {"ok": True, "data": {"ticket_id": "HT1"}}}
    assert nodes._offered([done], first) == []


# ── what reaches the customer ─────────────────────────────────────────────


@pytest.mark.parametrize("dirty, kept", [("Dạ phí giao 35.000đ ạ.娱乐注册", "Dạ phí giao 35.000đ ạ."),
                                         ("Dạ còn hàng ạ.циатә", "Dạ còn hàng ạ."),
                                         ("Dạ chị Hạnh, đơn đã được tạo ạ.", "Dạ chị Hạnh, đơn đã được tạo ạ.")])
def test_another_script_is_dropped_and_vietnamese_is_kept(dirty, kept):
    assert nodes.OTHER_SCRIPT.sub("", dirty) == kept


# ── guards: only a leak is rewritten; figures are the harness's ───────────


from ai_agent_service.components.guardrails.hard import GuardInput, check, unsourced_money  # noqa: E402


def _view(text, tier="VERIFIED", **kw):
    return GuardInput(text=text, tool_results=(), tier=tier, **kw)


@pytest.mark.parametrize("text", [
    "Giá nhập của máy này là thấp nên bên em bán được rẻ ạ.",       # internal information (KM-06)
    "Dạ số CCCD của chị là 079188158380 đúng không ạ?",             # a national ID read back
    "Dạ em là nhân viên thật của shop chứ không phải máy ạ.",       # claims to be human
])
def test_every_leak_is_still_blocked_and_is_not_an_amount(text):
    verdict = check(_view(text))
    assert not verdict.passed
    assert not set(verdict.reasons) <= set(unsourced_money(text, _view(text)))  # rewritten, not merely left out


def test_an_amount_no_tool_gave_is_the_only_reason_left_out_without_a_rewrite():
    text = "Dạ mẫu này giá 4.990.000đ ạ."
    verdict = check(_view(text))
    assert not verdict.passed and set(verdict.reasons) <= set(unsourced_money(text, _view(text)))
    quoted = {"name": "pricing.get_quote", "args": {"sku": "SKU-A"},
              "result": {"ok": True, "data": {"sku": "SKU-A", "final_price_vnd": 4_990_000}}}
    assert check(GuardInput(text=text, tool_results=(quoted,), tier="VERIFIED")).passed  # a sourced amount passes


@pytest.mark.parametrize("line", ["Dạ em xem giá hôm nay của mẫu đó cho chị nhé.",
                                  "Dạ em nhận yêu cầu của chị, em xử lý ngay ạ.",
                                  "Dạ em xem tình trạng đơn của chị ngay ạ."])
def test_the_sample_opening_lines_pass_the_guard_with_no_tool_result_yet(line):
    assert check(_view(line)).passed


def test_the_harness_fills_every_figure_and_never_says_a_label_it_cannot_fill():
    text, missing = fallback.fill_figures("Dạ mẫu này giá {giá:SKU-A}, tổng đơn {tổng} ạ.", {"SKU-A": 1_521_000}, 3_042_000)
    assert text == "Dạ mẫu này giá 1.521.000đ, tổng đơn 3.042.000đ ạ." and not missing
    _, missing = fallback.fill_figures("Dạ giá {giá:SKU-B} ạ.", {"SKU-A": 1_521_000}, None)
    assert missing  # no quote for SKU-B: the sentence is not said with a made-up figure


# ── the split the prompt offers is one the organisers' tools accept ────────


def test_the_two_halves_of_a_split_are_placed_by_the_organisers_order_create():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "apps/ai-agent-service/data/btc/eval/mock_tools.py"
    spec = importlib.util.spec_from_file_location("mock_tools_split", path)
    mock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock)  # a fresh copy: no order of another test in it
    quote = mock.pricing_quote_order([{"sku": "SKU-AP-PRO", "qty": 1}, {"sku": "SKU-SS-AX40", "qty": 1}])
    units = [(u["sku"], u["final_price_vnd"]) for u in quote["units"]]
    one, two = cod_split(units)
    for mine, other in ((one, two), (two, one)):
        assert len(mine) == 1  # each half one machine: written as sku, so basket_skus is read
        placed = mock.order_create("0900000001", sku=mine[0][0], qty=1, price_vnd=mine[0][1], payment="COD",
                                   basket_skus=[s for s, _ in other])
        assert "error" not in placed, placed


# ── an order read back in the model's own words ───────────────────────────


from ai_agent_service.components.guardrails import purchase  # noqa: E402


def test_a_one_product_order_has_its_total_to_fill_from_the_draft_or_the_placed_order():
    draft = {"name": "order.create", "args": {"sku": "SKU-A"}, "blocked_by": "guardrail",
             "result": {"ok": False, "error": {"code": "CONFIRMATION_REQUIRED",
                                               "details": {"purchase_draft": {"total_vnd": 1_740_000}}}}}
    assert nodes._figures({}, [draft])[1] == 1_740_000
    placed = {"name": "order.create", "args": {"sku": "SKU-A"},
              "result": {"ok": True, "data": {"order_id": "OD1", "total_vnd": 1_740_000}}}
    assert nodes._figures({}, [placed])[1] == 1_740_000


@pytest.mark.parametrize("reply, heard", [
    ("Dạ em đọc lại đơn: 1 đôi giày size 43, tổng 1.740.000đ, chuyển khoản. Chị đồng ý đặt không ạ?", True),
    ("Dạ đơn của chị tổng 1740000đ, chị đồng ý không ạ?", True),
    ("Dạ đơn tổng 1.740.000đ, đồng ý không ạ? Chị muốn xem thêm ảnh không ạ?", False),  # a yes answers the later question
    ("Dạ em đọc lại đơn giày size 43 cho chị ạ.", False),  # the total never said
])
def test_a_read_back_counts_only_when_it_said_the_total_and_asked_last(reply, heard):
    assert purchase.heard_in({"total_vnd": 1_740_000}, reply) is heard


def test_status_words_leave_an_unexpected_result_shape_alone():
    message = ToolMessage(content=json.dumps({"ok": True, "data": [1, 2]}), tool_call_id="1", name="order_status")
    assert with_status_words("order_status", message) is message
    raw = ToolMessage(content="not json", tool_call_id="2", name="order_status")
    assert with_status_words("order_status", raw) is raw


# ── 2026-11-27: the five failures left on the 43-scenario run ─────────────


def test_a_label_said_about_a_basket_is_the_units_price_in_it():
    quote = {"name": "pricing.quote_order", "args": {},
             "result": {"ok": True, "data": {"total_vnd": 16_475_000, "units": [
                 {"sku": "SKU-AP-PRO", "final_price_vnd": 7_690_000}, {"sku": "SKU-AP-PRO", "final_price_vnd": 7_690_000},
                 {"sku": "SKU-AP-MINI", "final_price_vnd": 1_095_000}]}}}
    prices, total = nodes._figures({"quotes": {"SKU-AP-MINI": 2_190_000}}, [quote])
    assert prices["SKU-AP-MINI"] == 1_095_000 and prices["SKU-AP-PRO"] == 7_690_000 and total == 16_475_000


def test_one_order_of_a_split_is_priced_from_the_whole_baskets_quote():
    context = AgentContext(call_id="c")
    units = {"SKU-AP-PRO|SKU-SS-AX40": [["SKU-AP-PRO", 7_690_000], ["SKU-SS-AX40", 3_245_000]]}
    order = advisor_module._filled_order({"sku": "SKU-SS-AX40", "qty": 1, "basket_skus": ["SKU-AP-PRO"],
                                          "order_group": "2"}, context, {"SKU-SS-AX40": 6_490_000}, units)
    assert order["price_vnd"] == 3_245_000


def test_the_two_orders_of_a_split_read_back_together_take_one_yes():
    one, two = {"total_vnd": 7_690_000, "payload_hash": "a"}, {"total_vnd": 3_245_000, "payload_hash": "b"}
    pending = {**one, "siblings": [two]}
    assert purchase.heard_in(pending, "Dạ đơn 1 tổng 7.690.000đ, đơn 2 tổng 3.245.000đ, chị đồng ý đặt cả hai không ạ?")
    assert purchase.heard_in(pending, "Dạ hai đơn tổng cộng 10.935.000đ, chị đồng ý không ạ?")
    assert not purchase.heard_in(pending, "Dạ đơn 1 tổng 7.690.000đ, chị đồng ý không ạ?")  # the second never heard
    state = {"call_id": "c", "turn_no": 1, "pending_purchase": None}
    drafts = [{"name": "order.create", "args": {}, "blocked_by": "guardrail", "result": {"ok": False, "error": {
        "code": "CONFIRMATION_REQUIRED", "details": {"purchase_draft": {**d, "issued_turn_id": "t4"}}}}} for d in (one, two)]
    kept = nodes._absorb(state, drafts)["pending_purchase"]
    assert kept["payload_hash"] == "a" and [s["payload_hash"] for s in kept["siblings"]] == ["b"]


def test_a_delivered_order_too_old_to_return_says_so_in_its_result():
    content = json.dumps({"ok": True, "data": {"orders": [
        {"order_id": "OD1", "status": "delivered", "date": "2026-04-04"},
        {"order_id": "OD2", "status": "delivered", "date": "2026-10-20"}]}})
    message = with_status_words("order_status", ToolMessage(content=content, tool_call_id="1", name="order_status"),
                                datetime(2026, 10, 22, 10, 0))
    old, recent = json.loads(message.content)["data"]["orders"]
    assert "đã hết hạn đổi trả" in old["return_window"] and "return_window" not in recent  # unsure: not claimed


def test_an_order_by_a_products_own_code_takes_the_variant_the_customer_named():
    context = AgentContext(call_id="c", recent=(("customer", "Alo, chị quyết định mua giày chạy bộ RunLite 2 Pro size 42 màu đen."),
                                                ("agent", "Dạ em xem giá ạ."), ("customer", "Chị sẽ thanh toán bằng COD.")))
    order = advisor_module._filled_order({"sku": "SKU-SN-RUN2", "qty": 1, "price_vnd": 1_690_000, "payment": "COD"},
                                         context, {"SKU-SN-RUN2-42-DEN": 1_690_000}, {})
    assert order["sku"] == "SKU-SN-RUN2-42-DEN" and order["price_vnd"] == 1_690_000
    vague = AgentContext(call_id="c", recent=(("customer", "Chị muốn mua giày RunLite 2 Pro."),))
    kept = advisor_module._filled_order({"sku": "SKU-SN-RUN2", "qty": 1}, vague, {}, {})
    assert kept["sku"] == "SKU-SN-RUN2"  # no size and colour said: nothing guessed, the guard asks


def test_the_total_label_falls_back_to_an_earlier_quote_of_the_same_basket_only():
    quoted = {"SKU-AP-MINI|SKU-AP-PRO|SKU-AP-PRO": [["SKU-AP-PRO", 7_690_000], ["SKU-AP-PRO", 7_690_000],
                                                   ["SKU-AP-MINI", 1_095_000]]}
    same = {"order_quotes": quoted, "basket": {"SKU-AP-PRO": {"qty": 2}, "SKU-AP-MINI": {"qty": 1}}}
    assert nodes._figures(same, [])[1] == 16_475_000
    changed = {"order_quotes": quoted, "basket": {"SKU-AP-PRO": {"qty": 1}, "SKU-AP-MINI": {"qty": 1}}}
    assert nodes._figures(changed, [])[1] is None  # the basket changed since: no total yet


def test_a_read_back_of_a_split_says_each_items_price_in_its_order():
    drafts = [{"name": "order.create", "args": {}, "blocked_by": "guardrail", "result": {"ok": False, "error": {
        "code": "CONFIRMATION_REQUIRED", "details": {"purchase_draft": {
            "total_vnd": price, "args": {"sku": sku, "qty": 1, "price_vnd": price, "basket_skus": [other]}}}}}}
        for sku, price, other in (("SKU-AP-PRO", 7_690_000, "SKU-SS-AX40"), ("SKU-SS-AX40", 3_245_000, "SKU-AP-PRO"))]
    prices, total = nodes._figures({"quotes": {"SKU-SS-AX40": 6_490_000, "SKU-AP-PRO": 7_690_000}}, drafts)
    assert prices["SKU-SS-AX40"] == 3_245_000 and total == 10_935_000


def test_three_orders_drafted_in_one_turn_are_one_read_back():
    drafts = [{"name": "order.create", "args": {}, "blocked_by": "guardrail", "result": {"ok": False, "error": {
        "code": "CONFIRMATION_REQUIRED", "details": {"purchase_draft": {
            "total_vnd": total, "payload_hash": key, "issued_turn_id": "t4"}}}}}
        for key, total in (("a", 3_000_000), ("b", 4_000_000), ("c", 5_000_000))]
    kept = nodes._absorb({"call_id": "c", "turn_no": 1, "pending_purchase": None}, drafts)["pending_purchase"]
    assert kept["payload_hash"] == "a" and [d["payload_hash"] for d in kept["siblings"]] == ["b", "c"]
    # The timeout fallback asks every order's total, or the sum, to have been said.
    assert purchase.heard_in(kept, "Dạ ba đơn tổng 3.000.000đ, 4.000.000đ và 5.000.000đ, chị đồng ý không ạ?")
    assert purchase.heard_in(kept, "Dạ ba đơn tổng cộng 12.000.000đ, chị đồng ý không ạ?")
    assert not purchase.heard_in(kept, "Dạ đơn đầu tổng 3.000.000đ, chị đồng ý không ạ?")


# ── the team's split tool, end to end on the organisers' mock ──────────────


@pytest.mark.asyncio
async def test_the_split_tool_reads_the_orders_back_then_places_them_on_one_yes():
    import importlib.util
    from pathlib import Path
    from unittest.mock import AsyncMock
    from langchain.agents.middleware.types import ToolCallRequest
    from langchain_core.tools import StructuredTool
    from ai_agent_service.agents.advisor import ActionGuardMiddleware
    from ai_agent_service.mcp.tools import SPLIT, ToolGuardMiddleware

    path = Path(__file__).resolve().parents[2] / "apps/ai-agent-service/data/btc/eval/mock_tools.py"
    spec = importlib.util.spec_from_file_location("mock_tools_split_tool", path)
    mock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock)
    placed = []

    async def pricing_quote_order(lines: list[dict], address: str | None = None) -> str:
        return json.dumps({"ok": True, "data": mock.pricing_quote_order(lines, address=address)})

    async def pricing_get_quote(sku: str, qty: int = 1, basket_skus: list[str] | None = None, address: str | None = None) -> str:
        return json.dumps({"ok": True, "data": mock.pricing_get_quote(sku, qty=qty, basket_skus=basket_skus, address=address)})

    async def order_create(sku: str | None = None, qty: int = 1, price_vnd: int | None = None, payment: str = "COD",
                           address: str | None = None, basket_skus: list[str] | None = None, lines: list[dict] | None = None,
                           order_group: str | None = None, customer_phone: str | None = None, call_id: str | None = None,
                           turn_id: str | None = None, purchase_authorization: str | None = None,
                           on: str | None = None) -> str:
        # What the shop's server signs consent over (mcp/servers/btc.py): every argument given, the order group too.
        consent = {k: v for k, v in dict(sku=sku, qty=qty, price_vnd=price_vnd, payment=payment, address=address,
                                         basket_skus=basket_skus, lines=lines, order_group=order_group,
                                         customer_phone=customer_phone, on=on).items() if v is not None}
        try:
            purchase.verify(purchase_authorization, consent, call_id, turn_id)  # no signed consent, no order
        except ValueError as error:
            placed.append({"error": f"consent: {error}"})
            raise
        made = mock.order_create(customer_phone or "0900000001", sku=sku, qty=qty, price_vnd=price_vnd, payment=payment,
                                 address=address, basket_skus=basket_skus, lines=lines, **({"on": on} if on else {}))
        placed.append(made)
        return json.dumps({"ok": "error" not in made, "data": made} if "error" not in made else
                          {"ok": False, "error": {"code": made["error"].upper(), "message": made["error"]}})

    tools = [StructuredTool.from_function(coroutine=fn, name=fn.__name__, description=fn.__name__)
             for fn in (pricing_quote_order, pricing_get_quote, order_create)]
    guard = ToolGuardMiddleware([t.name for t in tools])
    middleware = ActionGuardMiddleware(tools, guard)
    basket = {"lines": [{"sku": "SKU-AP-PRO", "qty": 1}, {"sku": "SKU-SS-AX40", "qty": 1}], "address": "Ninh Kiều, Cần Thơ"}

    async def ask(context):
        call = {"name": SPLIT, "args": basket, "id": "split", "type": "tool_call"}
        request = ToolCallRequest(tool_call=call, tool=None, state={"messages": []}, runtime=SimpleNamespace(context=context))
        return await middleware.awrap_tool_call(request, AsyncMock())

    base = dict(call_id="split-call", customer_id="C1", channel="hotline", tier="VERIFIED", customer_phone="0900000001",
                now=NOW, on="2026-10-22", trusted_skus=frozenset({"SKU-AP-PRO", "SKU-SS-AX40"}),
                quotes={"SKU-AP-PRO": 7_690_000, "SKU-SS-AX40": 6_490_000})

    async def no(intent, state):
        return False

    first = await ask(AgentContext(turn_id="t4", judge=no, customer_said="ừ tách giúp chị", **base))
    envelope = json.loads(first.content)
    assert envelope["error"]["code"] == "CONFIRMATION_REQUIRED" and not placed
    assert [o["total_vnd"] for o in envelope["error"]["details"]["orders"]] == [7_690_000, 3_245_000]
    held = [i for i in first.additional_kwargs["inner"] if i["name"] == "order_create"]
    assert len(held) == 2 and all(i["blocked_by"] == "guardrail" for i in held)  # not in the trace: nothing ran

    # The two read-backs as the turn's state keeps them: one pending order, the other beside it.
    results = [{"name": "order.create", "args": i["args"], "blocked_by": "guardrail",
                "result": json.loads(i["content"])} for i in held]
    pending = nodes._absorb({"call_id": "split-call", "turn_no": 4, "pending_purchase": None}, results)["pending_purchase"]
    assert len(pending.get("siblings") or []) == 1

    async def yes(intent, state):
        return True

    second = await ask(AgentContext(turn_id="t5", judge=yes, customer_said="chốt đơn giúp chị", pending_purchase=pending,
                                    **base))
    done = json.loads(second.content)
    assert done["ok"] and len(placed) == 2 and all("error" not in p for p in placed), placed
    assert sorted(p["total_vnd"] for p in placed) == [3_245_000, 7_690_000]
    groups = [i["args"].get("order_group") for i in second.additional_kwargs["inner"] if i["name"] == "order_create"]
    assert groups == ["1", "2"]


# ── review fixes, 2026-11-27 ─────────────────────────────────────────────


def test_a_first_clause_left_out_takes_its_rest_and_a_rest_left_out_closes_its_clause():
    attempt = nodes._Attempt()
    assert nodes._left_out(attempt, "clause") and attempt.skip_rest
    attempt = nodes._Attempt(said=["Dạ đơn của chị là mã này,"], open_clause=0)
    nodes._left_out(attempt, "rest")
    assert attempt.said == ["Dạ đơn của chị là mã này."] and attempt.open_clause is None


def _delivered(sku, placed):
    return {"order_id": "OD1", "sku": sku, "status": "delivered", "date": placed}


def test_the_return_window_follows_dt01_by_category():
    shoe, fan = "SKU-SN-RUN2", "SKU-FAN-SEN"
    assert actions.return_window(_delivered(shoe, "2026-10-10"), "2026-10-20") is None  # within 7 days of receipt
    assert actions.return_window(_delivered(shoe, "2026-09-01"), "2026-10-20") == "closed"
    # Household goods: a manufacturing defect is still exchanged within 30 days (DT-01, DT-05).
    assert actions.return_window(_delivered(fan, "2026-09-25"), "2026-10-20") == "defect"
    assert actions.return_window(_delivered(fan, "2026-08-01"), "2026-10-20") == "closed"
    # Not recorded as delivered: the customer may have it already, nothing is closed.
    assert actions.return_window({**_delivered(shoe, "2026-01-01"), "status": "processing"}, "2026-10-20") is None


def test_a_return_past_the_window_is_refused_before_the_tool():
    reasons = actions._order_update({"order_id": "OD1", "action": "return"}, orders=frozenset({"OD1"}), trusted=None,
                                    records=[_delivered("SKU-SN-RUN2", "2026-04-04")], now=datetime(2026, 10, 30))
    assert reasons and "hết hạn" in reasons[0]
    assert not actions._order_update({"order_id": "OD1", "action": "update_address", "new_address": "Hà Nội"},
                                     orders=frozenset({"OD1"}), trusted=None,
                                     records=[_delivered("SKU-SN-RUN2", "2026-04-04")], now=datetime(2026, 10, 30))


def test_an_unknown_code_comes_back_with_what_to_do():
    content = json.dumps({"ok": True, "data": {"error": "UNKNOWN_SKU"}})
    data = json.loads(tools_module.with_hints(ToolMessage(content=content, tool_call_id="1", name="x")).content)["data"]
    assert "catalog_search" in data["hint"]


def test_the_variant_is_taken_from_the_latest_words_about_size_or_colour_only():
    context = AgentContext(call_id="c", recent=(("customer", "Lấy size 42 màu đen nhé"), ("customer", "Thôi lấy size 43")))
    order = advisor_module._filled_order({"sku": "SKU-SN-RUN2", "qty": 1, "payment": "COD"}, context, {})
    assert order["sku"] == "SKU-SN-RUN2"  # the size changed without a colour: no earlier pair is reused


def test_a_basket_priced_together_is_the_basket_a_later_total_is_read_for():
    quote = {"name": "pricing.quote_order", "args": {"lines": [{"sku": "SKU-AP-PRO", "qty": 2}, {"sku": "SKU-AP-MINI", "qty": 1}]},
             "result": {"ok": True, "data": {"units": [], "total_vnd": 16_475_000}}}
    basket = nodes._basket_after({}, [quote])
    assert basket == {"SKU-AP-PRO": {"qty": 2}, "SKU-AP-MINI": {"qty": 1}}
    # A single quote of one of its items later does not change it.
    single = {"name": "pricing.get_quote", "args": {"sku": "SKU-AP-MINI", "qty": 1},
              "result": {"ok": True, "data": {"sku": "SKU-AP-MINI", "final_price_vnd": 2_190_000}}}
    assert nodes._basket_after(basket, [single]) == basket


def test_an_order_status_of_an_earlier_turn_is_kept_for_the_return_window():
    status = {"name": "order.status", "args": {}, "result": {"ok": True, "data": {"orders": [
        {"order_id": "OD1", "sku": "SKU-SN-RUN2", "status": "delivered", "date": "2026-04-04", "price_vnd": 1}]}}}
    kept = nodes._absorb({"turn_no": 1}, [status])["order_records"]
    assert kept == [{"order_id": "OD1", "sku": "SKU-SN-RUN2", "status": "delivered", "date": "2026-04-04"}]
