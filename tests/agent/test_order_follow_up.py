"""Follow-up turns of a task the agent started: the order a call is about, the order it created, and the
answer it was still giving when a sentence was stopped. No model: the routing, the checks and the stream
are run on fixtures."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from ai_agent_service.agents.advisor import AdvisorEvent, Draft
from ai_agent_service.components.guardrails import actions, fallback
from ai_agent_service.components.guardrails.hard import GuardInput, check
from ai_agent_service.config.config_manager import get_lanes
from ai_agent_service.pipeline.hot import nodes
from ai_agent_service.pipeline.hot.state import HotContext


# ── routing ───────────────────────────────────────────────────────────────


def test_the_sales_lanes_can_correct_an_order_the_call_created():
    lanes = get_lanes()
    assert "order_update" in lanes["CONTINUITY"] and "order_update" in lanes["NEW"]


# ── an order created once ─────────────────────────────────────────────────


def create(sku="SKU-A", said="Giao ở quận 3 nhé", created=(), tier="VERIFIED"):
    return actions.check("order_create", {"sku": sku, "price_vnd": 1_000_000, "qty": 1, "payment": "COD", "address": "Quận 3"},
                         tier=tier, mode="speak", has_phone=True, quotes={"SKU-A": 1_000_000, "SKU-B": 1_000_000},
                         trusted=frozenset({"SKU-A", "SKU-B"}), customer_said=said, created=created)


def test_the_same_product_is_not_booked_twice_in_a_call_unless_the_customer_asks_for_more():
    first = [{"order_id": "OD1", "sku": "SKU-A"}]
    assert create().passed
    again = create(created=first)
    assert not again.passed and "order_update" in again.reasons[0] and "OD1" in again.reasons[0]
    assert create(created=first, said="Cho chị lấy thêm một cái nữa nhé").passed
    assert create(created=first, said="Đặt thêm cho anh một đơn khác").passed
    assert create(sku="SKU-B", created=first).passed


def test_the_caller_may_correct_the_order_this_call_created_whatever_the_tier():
    created = [{"order_id": "OD1", "sku": "SKU-A"}]
    update = {"order_id": "OD1", "action": "update_address", "new_address": "quận 3"}
    assert actions.check("order_update", update, tier="UNKNOWN", mode="speak", has_phone=True, quotes={},
                         created=created).passed
    other = {"order_id": "OD9", "action": "update_address"}
    assert not actions.check("order_update", other, tier="UNKNOWN", mode="speak", has_phone=True, quotes={},
                             created=created).passed


def test_an_unverified_caller_hears_the_code_of_the_order_this_call_created_and_no_other():
    def said(text, **extra):
        return check(GuardInput(text=text, tool_results=(), tier="UNKNOWN", **extra))

    line = "Dạ em đã đặt đơn thành công, mã đơn OD600001 ạ."
    assert said(line, own_orders=frozenset({"OD600001"})).passed
    blocked = said(line)
    assert not blocked.passed and "mã đơn" in blocked.reasons[0]
    assert not said("Dạ đơn OD600001 và OD900201 của anh ạ.", own_orders=frozenset({"OD600001"})).passed
    # A code the caller names may be someone else's order: it is not repeated.
    assert not said("Dạ em đang tra đơn OD900201 ạ.", customer_said=("Em tra giúp anh đơn OD900201 nhé",)).passed


# ── an order's state ──────────────────────────────────────────────────────


def guard(text, results=(), **extra):
    return check(GuardInput(text=text, tool_results=tuple(results), tier="VERIFIED", **extra))


def placed(text, results=(), **extra):
    return any("order_create" in r for r in guard(text, results, **extra).reasons)


def test_an_offer_to_place_the_order_or_an_earlier_order_is_not_the_claim():
    for text in ("Dạ anh có muốn em lên đơn luôn không ạ?",
                 "Dạ em lên đơn cho chị nhé.",
                 "Dạ anh cho em xin số điện thoại để em lên đơn ạ.",
                 "Dạ đơn anh đã đặt hôm 10/10 bên em vẫn đang theo dõi ạ.",
                 "Dạ hôm trước em đã lên đơn máy lọc cho chị ạ.",
                 "Dạ nếu em đã lên đơn rồi thì anh sẽ nhận được tin nhắn ạ.",
                 "Dạ em đã lên đơn cho anh chưa ạ?"):
        assert not placed(text), text


# ── the harness's own lines ───────────────────────────────────────────────


def test_fallback_lines_address_the_customer_and_promise_no_call_back():
    line = fallback.safe_line("NEW", "chị")
    assert "chị" in line and "anh/chị" not in line and "chưa có thông tin" in line
    for name in ("tool_down", "asr_unclear", "model_error"):
        said = fallback.line(name, "anh")
        assert "{who}" not in said and "anh" in said
        assert "nhắn lại anh" not in said and "phản hồi" not in said
    # The bridging line is said only after handoff.transfer succeeded, never as a fallback.
    assert not fallback.is_bridging(fallback.safe_line("HANDOFF", "chị"))


def test_the_harness_addresses_an_unknown_customer_as_they_called_themselves():
    assert nodes._who({"tier": "VERIFIED", "honorific": "cô"}) == "cô"
    assert nodes._who({"tier": "UNKNOWN", "honorific_said": "anh"}) == "anh"
    assert nodes._who({"tier": "UNKNOWN"}) == "anh/chị"


# ── an answer stopped half way ────────────────────────────────────────────


class Stepwise:
    """An advisor whose runs are written in advance; it keeps the context each run was given."""

    def __init__(self, *runs):
        self.runs, self.views = list(runs), []

    def stream(self, messages, view, *, user_id=None):
        self.views.append(view)
        text, results = self.runs.pop(0)

        async def events():
            yield AdvisorEvent("text", text=text)
            yield AdvisorEvent("done", draft=Draft(text=text, tool_results=list(results), model="fixture",
                                                   model_calls=1, seconds=0.0))
        return events()


@pytest.mark.asyncio
async def test_a_leaking_sentence_after_the_first_is_regenerated_from_what_was_said():
    # Only what must not be said is rewritten (2026-11-26): here the shop's purchase price (KM-06).
    first = "Dạ bên em có mẫu máy lọc phù hợp với phòng của chị ạ."
    leak = "Giá nhập mẫu này thấp nên bên em bán rẻ ạ."
    stock = "Mẫu này giá 1.000.000đ ạ."
    inventory = {"name": "pricing.get_quote", "args": {"sku": "SKU-A"},
                 "result": {"ok": True, "data": {"sku": "SKU-A", "final_price_vnd": 1000000}}}
    advisor = Stepwise((f"{first} {leak}", ()), (f"{first} {stock}", (inventory,)))
    spoken = []

    async def emit(kind, text):
        if kind == "sentence":
            spoken.append(text)

    state = {"call_id": "fixture", "turn_id": "t1", "mode": "speak", "tier": "VERIFIED", "lane": "NEW",
             "now": datetime.now(timezone.utc), "messages": [HumanMessage(content="Phòng chị 20 mét vuông")]}
    update = await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=advisor, emit=emit)))
    assert spoken == [first, stock]  # the repeated first sentence is not said twice
    assert not update["draft"]["fallback"] and "safe_lines" not in update
    assert advisor.views[1].already_said == (first,) and advisor.views[1].block_reasons
    assert advisor.views[1].answer_only  # the rewrite answers in its one call, without tools
    assert update["regen_count"] == 1


@pytest.mark.asyncio
async def test_an_amount_no_tool_gave_is_left_out_without_a_rewrite():
    first = "Dạ bên em có mẫu máy lọc phù hợp với phòng của chị ạ."
    unsourced = "Mẫu này giá 1.000.000đ ạ."
    advisor = Stepwise((f"{first} {unsourced}", ()))
    spoken = []

    async def emit(kind, text):
        if kind == "sentence":
            spoken.append(text)

    state = {"call_id": "fixture", "turn_id": "t1", "mode": "speak", "tier": "VERIFIED", "lane": "NEW",
             "now": datetime.now(timezone.utc), "messages": [HumanMessage(content="Phòng chị 20 mét vuông")]}
    update = await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=advisor, emit=emit)))
    assert spoken == [first] and len(advisor.views) == 1  # one model run: no rewrite
    assert not update["draft"]["fallback"] and "safe_lines" not in update


def test_an_address_that_says_there_is_none_never_reaches_a_tool():
    from ai_agent_service.mcp.tools import NO_ADDRESS
    from ai_agent_service.components.intake.text import plain
    for none in ("chưa có địa chỉ", "Không rõ", "N/A", "unknown", "-", ""):
        assert NO_ADDRESS.search(plain(none)), none
    for real in ("Lê Chân, Hải Phòng", "12 Nguyễn Trãi, Quận 1", "<ADDR_1>", "Khu đô thị Văn Phú, Hà Đông"):
        assert not NO_ADDRESS.search(plain(real)), real


@pytest.mark.parametrize("one, other, same", [
    ("Dạ mẫu quạt này đang được tặng kèm một bộ điều khiển chính hãng và bảo hành tại nhà ạ.",
     "Dạ mẫu quạt này đang được tặng kèm một bộ điều khiển và bảo hành tại nhà ạ.", True),
    ("Dạ vâng ạ.", "Dạ vâng ạ.", True),
    ("Dạ vâng ạ.", "Dạ vâng chị.", False),
    ("Dạ mẫu A giá 1.200.000đ ạ.", "Dạ mẫu B giá 1.500.000đ ạ.", False),
    ("Dạ bên em bảo hành 24 tháng chính hãng ạ.", "Dạ bên em hỗ trợ đổi trả trong 7 ngày ạ.", False),
])
def test_a_regenerated_line_that_repeats_one_already_said_is_dropped(one, other, same):
    from ai_agent_service.pipeline.hot.nodes import same_sentence
    assert same_sentence(one, other) is same


def test_the_same_order_change_is_not_made_twice_in_a_call():
    change = {"order_id": "OD1", "action": "exchange_size", "new_variant_sku": "SKU-SN-CAS-40-DEN"}
    common = dict(tier="VERIFIED", mode="speak", has_phone=True, quotes={}, orders=frozenset({"OD1"}),
                  trusted=frozenset({"SKU-SN-CAS-40-DEN", "SKU-SN-CAS-41-DEN"}))
    assert actions.check("order_update", change, **common).passed
    again = actions.check("order_update", change, updated=[change], **common)
    assert not again.passed and "không gọi lại" in again.reasons[0]
    other = {**change, "new_variant_sku": "SKU-SN-CAS-41-DEN"}
    assert actions.check("order_update", other, updated=[change], **common).passed


def test_a_turn_that_placed_an_order_never_falls_back_to_no_information():
    from ai_agent_service.pipeline.hot.nodes import _safe_line
    placed = [{"name": "order.create", "args": {}, "result": {"ok": True, "data": {"order_id": "OD1"}}}]
    state = {"lane": "CONTINUITY", "honorific": "chị"}
    assert "đã tạo đơn" in _safe_line(state, placed)
    assert "chưa có thông tin" in _safe_line(state, [])


def test_a_change_made_in_an_earlier_turn_is_not_made_again():
    # The duplicate check reads the whole call, not the turn: three "đổi sang L" over three turns were
    # three charged exchanges (FIX-05, 2026-11-01).
    earlier = [{"order_id": "OD1", "action": "exchange_size", "new_variant_sku": "SKU-L"}]
    again = {"order_id": "OD1", "action": "exchange_size", "new_variant_sku": "SKU-L"}
    verdict = actions.check("order_update", again, tier="VERIFIED", mode="speak", has_phone=True, quotes={},
                            orders=frozenset({"OD1"}), trusted=frozenset({"SKU-L"}), updated=earlier)
    assert not verdict.passed and "OD1" in verdict.reasons[0]


def test_absorb_keeps_the_changes_of_the_call():
    state = {"turn_no": 2, "updated_orders": [{"order_id": "OD0", "action": "return", "new_variant_sku": None}]}
    result = {"name": "order.update", "args": {"order_id": "OD1", "action": "exchange_size", "new_variant_sku": "SKU-L"},
              "result": {"ok": True, "data": {"order_id": "OD1", "fee_vnd": 0}}}
    update = nodes._absorb(state, [result])
    assert [c["order_id"] for c in update["updated_orders"]] == ["OD0", "OD1"]


# ── a new address ─────────────────────────────────────────────────────────


def test_a_new_address_goes_onto_the_order_the_next_status_reads():
    """The organisers' update_address answers "updated" and keeps the old address; ours puts the new one on."""
    from ai_agent_service.mcp.servers import btc
    from ai_agent_service.mcp.servers.order import _with_address

    m = btc.mock()
    saved = dict(m._ORDERS), list(m._TICKETS)
    try:
        m._ORDERS["OD9001"] = {"order_id": "OD9001", "customer_phone": "0900000001", "sku": "SKU-AP-Y",
                               "address": "Hồ Chí Minh", "created_on": "2026-10-15", "status": "created"}
        update = _with_address(m)
        result = update("OD9001", "update_address", new_address="Hà Nội", on="2026-10-15")
        assert result["status"] == "updated" and result["new_address"] == "Hà Nội"
        assert result["estimated_delivery"] == m._eta("2026-10-15", "Hà Nội")
        assert m.order_status(order_id="OD9001")["orders"][0]["address"] == "Hà Nội"
        assert update("OD9001", "update_address", on="2026-10-15") == {"error": "missing_new_address"}
    finally:
        m._ORDERS.clear(); m._ORDERS.update(saved[0]); m._TICKETS[:] = saved[1]


def test_an_address_change_needs_the_address_and_a_second_one_is_a_new_change():
    created = [{"order_id": "OD1", "sku": "SKU-A"}]
    common = dict(tier="VERIFIED", mode="speak", has_phone=True, quotes={}, created=created)
    bare = {"order_id": "OD1", "action": "update_address"}
    verdict = actions.check("order_update", bare, **common)
    assert not verdict.passed and "new_address" in verdict.reasons[0]
    first = {**bare, "new_address": "Hồ Chí Minh"}
    second = {**bare, "new_address": "Hà Nội"}
    assert not actions.check("order_update", first, updated=[first], **common).passed
    assert actions.check("order_update", second, updated=[first], **common).passed


@pytest.mark.asyncio
async def test_a_turn_whose_only_sentence_is_left_out_says_the_safe_line_not_nothing():
    advisor = Stepwise(("Mẫu này giá 1.000.000đ ạ.", ()))
    spoken = []

    async def emit(kind, text):
        if kind == "sentence":
            spoken.append(text)

    state = {"call_id": "fixture", "turn_id": "t1", "mode": "speak", "tier": "VERIFIED", "lane": "NEW",
             "now": datetime.now(timezone.utc), "messages": [HumanMessage(content="Giá bao nhiêu em?")]}
    update = await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=advisor, emit=emit)))
    assert len(spoken) == 1 and "1.000.000" not in spoken[0]  # the safe line, not silence, not the made-up price
    assert update["draft"]["fallback"] and update["safe_lines"] == 1
