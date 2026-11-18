"""Agent faults found in the dev run's failed calls (2026-11-16), each checked without a model call."""

from datetime import datetime, timedelta, timezone

import pytest

from ai_agent_service.components.guardrails import actions, purchase
from ai_agent_service.components.identity.resolver import Match, pick_by_name
from ai_agent_service.components.intake import commerce, itn
from ai_agent_service.mcp.tools import named_lookups
from ai_agent_service.pipeline.hot.nodes import _handoff_product
from langchain_core.messages import HumanMessage

VN = timezone(timedelta(hours=7))
SHARED = [Match("A", "Dung", "chị", None, None), Match("B", "Loan", "cô", None, None)]


@pytest.mark.parametrize("said,name", [
    ("Alo, chị Dung đây, hôm trước em có tư vấn cho chị máy lọc không khí phải không?", "Dung"),
    ("Chị Dung nghe đây, hôm trước em tư vấn cho cô Loan về máy lọc nước.", "Dung"),
    ("Alo em, cô Loan đây, hôm trước em đã tư vấn cho cô máy lọc nước.", "Loan"),
    ("alo chi dung day", "Dung"),
])
def test_a_caller_who_says_who_is_speaking_is_picked_on_a_shared_number(said, name):
    assert pick_by_name(said, SHARED).name == name


@pytest.mark.parametrize("said", ["Ừ đúng rồi em.", "Không phải chị Dung đây đâu",
                                  "hôm trước em tư vấn cho cô Loan đấy"])
def test_a_name_only_mentioned_or_denied_picks_no_one(said):
    assert pick_by_name(said, SHARED) is None


@pytest.mark.parametrize("said,written", [
    ("ngân sách giờ là 5 triệu bảy trăm, em lên đơn nhé", "ngân sách giờ là 5.700.000đ, em lên đơn nhé"),
    ("Ngân sách của anh giờ là 7 triệu bảy trăm nghìn.", "Ngân sách của anh giờ là 7.700.000đ."),
])
def test_digits_before_a_spoken_scale_are_its_head(said, written):
    assert itn.normalise(said, datetime(2026, 10, 22, 10, tzinfo=VN)) == written


@pytest.mark.parametrize("said,moment", [
    ("Tối thứ Bảy này tầm 10 giờ em gọi lại anh nhé.", "2026-10-24T22:00"),
    ("Tối thứ Tư này, ngày 11/11, tầm 10 giờ em gọi lại anh nhé.", "2026-11-11T22:00"),
    ("Hẹn em tối thứ Hai (19/10) tầm 7 giờ em gọi lại anh nhé.", "2026-10-19T19:00"),
    ("chi can ban voi gia dinh da em goi lai chi toi thu hai 19 10 tam 7 gio nhe", "2026-10-19T19:00"),
    ("hen chi toi mai tam 7 gio nhe", "2026-10-18T19:00"),
    ("tối mai 8 giờ", "2026-10-18T20:00"),
])
def test_a_time_reads_its_day_and_part_of_day_from_the_sentence(said, moment):
    assert f"({moment}+07:00)" in itn.normalise(said, datetime(2026, 10, 17, 10, tzinfo=VN))


def test_tối_đa_is_not_evening():
    assert "T08:00" in itn.normalise("phòng tối đa 30 mét, 8 giờ sáng giao", datetime(2026, 10, 17, 10, tzinfo=VN))


def test_prefetch_looks_up_the_variant_the_customer_names_and_never_the_parent():
    said = "Alo, anh muốn hỏi về giày chạy bộ RunLite 2 Pro size 41 màu đen."
    calls = named_lookups([HumanMessage(content=said)], said)
    assert {c["args"]["sku"] for c in calls} == {"SKU-SN-RUN2-41-DEN"}
    vague = "anh muốn đặt giày RunLite 2 Pro"
    assert named_lookups([HumanMessage(content=vague)], vague) == []


def test_a_product_sold_in_variants_is_not_ordered_by_its_parent_code():
    verdict = actions.check("order_create", {"sku": "SKU-SN-RUN2", "price_vnd": 1690000, "payment": "COD", "address": "Quận 7"},
                            tier="VERIFIED", mode="speak", has_phone=True, quotes={"SKU-SN-RUN2": 1690000},
                            trusted=frozenset({"SKU-SN-RUN2"}))
    assert not verdict.passed and "variant_sku" in verdict.reasons[0]


def test_an_order_the_customer_asked_for_is_placed_without_a_payment_or_an_address():
    # The organisers' scenarios end on "lên đơn cho chị" with neither said: order.create takes COD by default and
    # address is optional (schemas/tools.schema.json), so a question there is never answered (2026-11-18).
    verdict = actions.check("order_create", {"sku": "SKU-AP-X", "price_vnd": 4890000},
                            tier="VERIFIED", mode="speak", has_phone=True, quotes={"SKU-AP-X": 4890000},
                            trusted=frozenset({"SKU-AP-X"}))
    assert verdict.passed, verdict.reasons
    assert purchase.payload({"sku": "SKU-AP-X", "price_vnd": 4890000})["payment"] == "COD"


def test_a_variant_is_read_back_by_name_size_and_colour():
    assert commerce.product_name("SKU-SN-RUN2-41-DEN") == "Giày chạy bộ RunLite 2 Pro size 41 màu đen"


def test_a_handoff_brief_names_the_product_quoted_or_ordered_when_none_was_advised():
    assert _handoff_product([], {"SKU-AP-X": 4890000}, []) == {"product_advised": "SKU-AP-X", "price_quoted_vnd": 4890000}
    order = {"order_id": "OD1", "variant_sku": "SKU-SN-TRK-39-XAM", "price_vnd": 1990000}
    assert _handoff_product([], {}, [order]) == {"product_advised": "SKU-SN-TRK-39-XAM", "price_quoted_vnd": 1990000}


def test_half_of_a_split_order_is_priced_by_the_quote_made_with_the_other_half():
    from langchain_core.messages import AIMessage, ToolMessage
    import json
    from ai_agent_service.agents.advisor import _basket_quotes_in, _quotes_in

    def quote(call_id, basket, price):
        args = {"sku": "SKU-SS-AX40", **({"basket_skus": basket} if basket else {})}
        return [AIMessage(content="", tool_calls=[{"id": call_id, "name": "pricing_get_quote", "args": args}]),
                ToolMessage(content=json.dumps({"ok": True, "data": {"sku": "SKU-SS-AX40", "final_price_vnd": price}}),
                            tool_call_id=call_id, name="pricing_get_quote")]

    state = {"messages": [*quote("q1", None, 6490000), *quote("q2", ["SKU-AP-PRO"], 3245000)]}
    assert _quotes_in(state) == {"SKU-SS-AX40": 6490000}
    assert _basket_quotes_in(state) == {("SKU-SS-AX40", frozenset({"SKU-AP-PRO"})): 3245000}


@pytest.mark.asyncio
async def test_half_of_a_split_order_takes_its_price_from_the_quote_of_the_whole_basket():
    """The run of 2026-11-16 priced the basket with pricing_quote_order; the second order must be booked at that price."""
    import json
    from types import SimpleNamespace
    from langchain_core.messages import ToolMessage
    from ai_agent_service.agents.advisor import ActionGuardMiddleware, AgentContext

    seen = []

    async def handler(request):
        seen.append(request.tool_call["args"])
        return "executed"

    quote_order = ToolMessage(json.dumps({"ok": True, "data": {"units": [
        {"sku": "SKU-AP-PRO", "final_price_vnd": 7690000}, {"sku": "SKU-SS-AX40", "final_price_vnd": 3245000}]}}),
        tool_call_id="q", name="pricing_quote_order")
    context = AgentContext(call_id="c", turn_id="t", tier="VERIFIED", customer_phone="0900000000",
                           quotes={"SKU-SS-AX40": 6490000}, trusted_skus=frozenset({"SKU-SS-AX40", "SKU-AP-PRO"}))
    args = {"sku": "SKU-SS-AX40", "qty": 1, "price_vnd": 6490000, "payment": "COD", "address": "Nha Trang",
            "basket_skus": ["SKU-AP-PRO"], "order_group": "2"}
    request = SimpleNamespace(tool_call={"id": "o", "name": "order_create", "args": args},
                              runtime=SimpleNamespace(context=context), state={"messages": [quote_order]})
    request.override = lambda **changes: SimpleNamespace(**{**vars(request), **changes})
    result = await ActionGuardMiddleware().awrap_tool_call(request, handler)
    text = result if isinstance(result, str) else result.content
    assert "khác giá hôm nay" not in text  # the one-machine price no longer stands for this order


@pytest.mark.parametrize("said,blocked", [
    ("Dạ chương trình 11/11 chưa bắt đầu nên em chưa có thông tin ạ.", True),
    ("Dạ khuyến mãi 11 tháng 11 em chưa có thông tin.", True),
    ("Dạ đơn giao dự kiến ngày 11/11 ạ.", False),
    ("Dạ chương trình sắp tới em chưa có thông tin ạ.", False),
])
def test_a_promotion_not_started_is_not_named_by_its_first_day(said, blocked):
    from ai_agent_service.components.guardrails import hard
    view = hard.GuardInput(text=said, tool_results=(), tier="VERIFIED",
                           promotions={"11-11": ("2026-11-11", "2026-11-12")}, on="2026-10-20")
    assert bool(hard._not_started(said, view)) is blocked


def test_a_callback_time_is_said_the_spoken_way():
    from ai_agent_service.components import clock
    assert clock.spoken_moment(clock.parse_local("2026-10-16T19:00")) == "19 giờ tối thứ Sáu 16/10/2026"
