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
from ai_agent_service.components.orchestration.rules import RouteInput, decide
from ai_agent_service.config.config_manager import get_lanes
from ai_agent_service.pipeline.hot import nodes
from ai_agent_service.pipeline.hot.state import HotContext


def routed(said, **extra):
    base = dict(tier="VERIFIED", has_brief=True, has_order=True, asr_low_conf=False, tool_failures=0, safe_lines=0,
                customer_said=said)
    return decide(RouteInput(**{**base, **extra}))


# ── routing ───────────────────────────────────────────────────────────────


def test_an_answer_to_the_agents_order_question_stays_with_the_order():
    answer = "Địa chỉ mới là quận 3 nhé em."
    assert routed(answer).lane == "CONTINUITY"
    kept = routed(answer, previous_lane="ORDER_SERVICE", answering=True)
    assert (kept.lane, kept.rule) == ("ORDER_SERVICE", 4)
    assert routed(answer, previous_lane="ORDER_SERVICE", answering=False).lane == "CONTINUITY"
    assert routed(answer, previous_lane="CONTINUITY", answering=True).lane == "CONTINUITY"
    assert routed(answer, previous_lane="ORDER_SERVICE", answering=True, has_order=False).lane == "CONTINUITY"
    assert routed(answer, previous_lane="ORDER_SERVICE", answering=True, must_transfer=True).lane == "OUT_OF_SCOPE"


def test_the_sales_lanes_can_correct_an_order_the_call_created():
    lanes = get_lanes()
    assert "order_update" in lanes["CONTINUITY"] and "order_update" in lanes["NEW"]


# ── an order created once ─────────────────────────────────────────────────


def create(sku="SKU-A", said="Giao ở quận 3 nhé", created=(), tier="VERIFIED"):
    return actions.check("order_create", {"sku": sku, "price_vnd": 1_000_000, "qty": 1, "payment": "COD"},
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


# ── an order's state ──────────────────────────────────────────────────────


def guard(text, results=(), **extra):
    return check(GuardInput(text=text, tool_results=tuple(results), tier="VERIFIED", **extra))


def test_an_orders_state_needs_an_order_tool_of_the_turn():
    said = "Dạ đơn của chị đang được giao rồi ạ."
    assert any("trạng thái đơn" in r for r in guard(said).reasons)
    status = {"name": "order.status", "result": {"ok": True, "data": {"orders": [{"status": "shipping"}]}}}
    assert not any("trạng thái đơn" in r for r in guard(said, [status]).reasons)
    assert not any("trạng thái đơn" in r for r in guard(said, check_handoff=False).reasons)
    for plain_talk in ("Dạ bên em giao hàng toàn quốc ạ.", "Dạ sản phẩm sẽ được giao trong 2 ngày ạ."):
        assert not any("trạng thái đơn" in r for r in guard(plain_talk).reasons)


# ── the harness's own lines ───────────────────────────────────────────────


def test_fallback_lines_address_the_customer_and_promise_no_call_back():
    line = fallback.safe_line("NEW", "chị")
    assert "chị" in line and "anh/chị" not in line and "chưa có thông tin" in line
    for name in ("tool_down", "asr_unclear", "model_error"):
        said = fallback.line(name, "anh")
        assert "{who}" not in said and "anh" in said
        assert "nhắn lại anh" not in said and "phản hồi" not in said
    assert fallback.safe_line("HANDOFF", "chị") == fallback.LINES["bridging"]


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
async def test_a_sentence_stopped_after_the_first_is_regenerated_from_what_was_said():
    first = "Dạ bên em có mẫu máy lọc phù hợp với phòng của chị ạ."
    stock = "Mẫu này hiện còn hàng ạ."
    inventory = {"name": "inventory.check", "args": {"sku": "SKU-A"}, "result": {"ok": True, "data": {"in_stock": True}}}
    advisor = Stepwise((f"{first} {stock}", ()), (f"{first} {stock}", (inventory,)))
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
    assert update["regen_count"] == 1
