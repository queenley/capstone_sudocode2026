"""Plan 002: the model writes a write tool's success line with the call; the harness fills it and ends the turn."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from ai_agent_service.agents.advisor import AdvisorEvent, Draft
from ai_agent_service.components.guardrails import fallback
from ai_agent_service.pipeline.hot import nodes
from ai_agent_service.pipeline.hot.state import HotContext

CREATED = {"order_id": "OD600003", "total_vnd": 4890000, "estimated_delivery": "2026-10-17"}


def test_a_line_is_filled_only_from_its_tools_holes():
    line = fallback.render("order.create", "Dạ em lên đơn {order_id} rồi ạ, tổng {total_vnd}đ, giao {estimated_delivery}.", CREATED)
    assert line == "Dạ em lên đơn OD600003 rồi ạ, tổng 4.890.000đ, giao 17/10/2026."
    assert fallback.render("order.create", "Dạ tổng {limit_vnd} ạ.", CREATED) is None  # not this tool's hole
    assert fallback.render("order.create", "Dạ tổng 4.890.000đ ạ.", CREATED) is None  # an amount by hand
    assert fallback.render("order.create", "Dạ giao ngày 17/10 ạ.", CREATED) is None  # a date by hand
    assert fallback.render("schedule.callback", "Dạ em hẹn chị lúc 9 giờ sáng ạ.", {"callback_at": "x"}) is None
    # other figures are the hard guard's, as in every sentence (bench of 2026-11-15)
    assert fallback.render("order.update", "Dạ em đổi địa chỉ đơn {order_id} sang 45 Lê Lợi rồi ạ.", CREATED)
    assert fallback.render("memory.request_deletion", "Dạ hồ sơ của chị sẽ được xóa trong vòng 72 giờ ạ.", {})
    assert fallback.render("order.create", "Dạ đơn {order_id} ạ.", {}) is None  # the tool did not fill it
    assert fallback.render("order.create", "Dạ. Vâng ạ. Xong rồi ạ.", CREATED) is None  # three sentences
    assert fallback.render("pricing.get_quote", "Dạ vâng ạ.", {}) is None  # not a write tool


def test_the_outcome_of_a_result():
    assert fallback.outcome_of({"name": "order.create", "result": {"ok": True, "data": CREATED}}) == "ok"
    moved = {"name": "schedule.callback", "result": {"ok": True, "data": {"moved_from": "2026-10-18T09:00"}}}
    assert fallback.outcome_of(moved) == "moved"
    assert fallback.outcome_of({"name": "order.create", "result": {"ok": False, "error": {"code": "out_of_stock"}}}) == "out_of_stock"


class OneRound:
    """An advisor whose run calls one write tool; text after the tools means a second model round was read."""

    def __init__(self, result):
        self.result, self.rounds = result, 0

    def stream(self, messages, view, *, user_id=None):
        async def events():
            self.rounds = 1
            yield AdvisorEvent("tool_started")
            draft = Draft(text="", tool_results=[self.result], model="fixture", model_calls=1, seconds=0.0)
            yield AdvisorEvent("tools", results=(self.result,), draft=draft)
            self.rounds = 2
            yield AdvisorEvent("text", text="Dạ em đã đặt lịch rồi ạ, chị cần gì thêm không ạ?")
            yield AdvisorEvent("done", draft=draft)
        return events()


async def turn(result):
    spoken = []

    async def emit(kind, text):
        if kind == "sentence":
            spoken.append(text)

    state = {"call_id": "fixture", "turn_id": "t1", "mode": "speak", "tier": "VERIFIED", "lane": "NEW", "honorific": "chị",
             "now": datetime.now(timezone.utc), "messages": [HumanMessage(content="Sáng mai 9 giờ em gọi lại nhé")]}
    advisor = OneRound(result)
    update = await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=advisor, emit=emit)))
    return advisor, spoken, update


BOOKED = {"name": "schedule.callback", "args": {"callback_at": "2026-10-16T09:00"},
          "reply": "Dạ em đã hẹn gọi lại chị lúc {callback_at} ạ.",
          "result": {"ok": True, "data": {"callback_at": "2026-10-16T09:00", "moved_from": None}}}


@pytest.mark.asyncio
async def test_the_models_own_line_ends_the_turn_without_a_second_round(monkeypatch):
    monkeypatch.setenv("ADVISOR_REPLY_PLAN", "1")
    advisor, spoken, update = await turn(BOOKED)
    assert advisor.rounds == 1
    assert spoken == ["Dạ em đã hẹn gọi lại chị lúc 9 giờ sáng thứ Sáu 16/10/2026 ạ."]
    assert update["draft"]["ended_on_tools"] and update["draft"]["planned_lines"] == ["schedule.callback"]
    assert all("reply" not in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_a_line_that_cannot_be_filled_or_the_switch_off_goes_on_to_the_model(monkeypatch):
    monkeypatch.setenv("ADVISOR_REPLY_PLAN", "0")
    advisor, spoken, _ = await turn(BOOKED)
    assert advisor.rounds == 2  # today's behaviour: the fixed line, then the model's next round
    monkeypatch.setenv("ADVISOR_REPLY_PLAN", "1")
    failed = {**BOOKED, "result": {"ok": False, "error": {"code": "BAD_REQUEST"}}}
    advisor, spoken, _ = await turn(failed)
    assert advisor.rounds == 2


# ── the schema the model is offered, and what the tool and the trace see ──

import json  # noqa: E402

from ai_agent_service.agents.advisor import AgentContext  # noqa: E402
from test_latency_head_starts import NOW, advisor as fake_advisor, chunk, lookups, sse, tool  # noqa: E402


def callback_tool(ran):
    return tool("schedule_callback", {"callback_at": "2026-11-08T09:00", "moved_from": None},
                {"callback_at": {"type": "string"}, "customer_phone": {"anyOf": [{"type": "string"}, {"type": "null"}],
                                                                      "default": None}}, ran)


@pytest.mark.asyncio
async def test_write_tools_are_offered_the_line_and_nothing_downstream_sees_it(monkeypatch):
    monkeypatch.setenv("ADVISOR_REPLY_PLAN", "1")
    requests, ran = [], []
    line = "Dạ em đã hẹn gọi lại chị lúc {callback_at} ạ."

    def answer(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            call = {"index": 0, "id": "b1", "type": "function", "function": {
                "name": "schedule_callback", "arguments": json.dumps({"callback_at": "2026-11-08T09:00", "reply": line})}}
            return sse(chunk(tool_calls=[call]))
        return sse(chunk(content="Dạ vâng ạ."))

    context = AgentContext(call_id="c", lane="NEW", tier="VERIFIED", now=NOW, on="2026-11-07", turn_id="t1",
                           customer_phone="0912345678")
    agent = fake_advisor(answer, [*lookups(ran), callback_tool(ran)])
    events = [e async for e in agent.stream([HumanMessage("Mai 9 giờ em gọi lại nhé")], context)]

    offered = {t["function"]["name"]: t["function"]["parameters"] for t in requests[0]["tools"]}
    assert "reply" in offered["schedule_callback"]["properties"] and "reply" in offered["schedule_callback"]["required"]
    assert "reply" not in offered["pricing_get_quote"]["properties"]
    # The same tools, in the same order, on every model call of the run: the provider's prompt cache holds.
    assert requests[0]["tools"] == requests[1]["tools"]
    assert ran and all("reply" not in args for _, args in ran)
    result = events[-1].draft.tool_results[0]
    assert "reply" not in result["args"] and result["reply"] == line


@pytest.mark.asyncio
async def test_with_the_switch_off_no_tool_is_offered_the_line(monkeypatch):
    monkeypatch.setenv("ADVISOR_REPLY_PLAN", "0")
    requests = []

    def answer(request):
        requests.append(json.loads(request.content))
        return sse(chunk(content="Dạ vâng ạ."))

    context = AgentContext(call_id="c", lane="NEW", now=NOW, on="2026-11-07", turn_id="t1")
    [e async for e in fake_advisor(answer, [callback_tool([])]).stream([HumanMessage("alo")], context)]
    assert all("reply" not in t["function"]["parameters"]["properties"] for t in requests[0]["tools"])


@pytest.mark.asyncio
async def test_a_line_the_hard_guard_blocks_is_not_said_and_the_model_goes_on(monkeypatch):
    monkeypatch.setenv("ADVISOR_REPLY_PLAN", "1")
    # The line fills, but speaks of the shop's internal prices: the hard guard refuses it, so the fixed line is said
    # and the turn ends on it (a booked call back is said whole by the fixed line).
    internal = {**BOOKED, "reply": "Dạ em đã hẹn gọi lại chị lúc {callback_at}, giá nhập em báo sau ạ."}
    advisor, spoken, update = await turn(internal)
    assert not any("giá nhập" in s for s in spoken)
    assert spoken == [fallback.result_line(internal, "chị")] and not update["draft"].get("planned_lines")
    # An order whose fixed line does not say it all: the model goes on.
    order = {"name": "order.create", "args": {"sku": "SKU-AP-X"}, "reply": "Dạ em lên đơn {order_id}, giá nhập thấp ạ.",
             "result": {"ok": True, "data": CREATED}}
    advisor, spoken, _ = await turn(order)
    assert advisor.rounds == 2 and not any("giá nhập" in s for s in spoken)


# ── plan 002, step 5: the model writes a short Handoff Brief, the harness the rest ──

from ai_agent_service.components.guardrails import actions  # noqa: E402
from ai_agent_service.mcp.tools import model_args  # noqa: E402
from test_btc_contract import HANDOFF_DEFAULTS  # noqa: E402

SHORT = {"escalation_reason": "cau_hoi_y_te", "escalation_reason_detail": "Khách hỏi về bé bị hen suyễn.",
         "conversation_summary": "Khách hỏi máy lọc có hợp với bé bị hen suyễn không."}


def test_the_short_brief_is_what_the_model_is_offered_with_the_switch_on(monkeypatch):
    monkeypatch.setenv("ADVISOR_SHORT_BRIEF", "1")
    assert set(model_args("handoff_transfer")["brief"]["required"]) == set(SHORT)
    monkeypatch.setenv("ADVISOR_SHORT_BRIEF", "0")
    assert "open_questions" in model_args("handoff_transfer")["brief"]["required"]


def test_the_harness_fills_a_short_brief_into_a_valid_one():
    said = "Bé nhà chị bị hen suyễn thì dùng máy này được không em?"
    filled = actions.fill_handoff(SHORT, HANDOFF_DEFAULTS, customer_said=said)
    assert filled["open_questions"] == [said]
    assert filled["next_action"] == actions.NEXT_ACTION["cau_hoi_y_te"]
    assert actions.handoff_problems(filled) == []
    # what the model wrote stands
    own = actions.fill_handoff({**SHORT, "next_action": "Gọi chuyên gia.", "open_questions": ["A?"]}, HANDOFF_DEFAULTS,
                               customer_said=said)
    assert own["next_action"] == "Gọi chuyên gia." and own["open_questions"] == ["A?"]


# ── plan 002, A2: the voice's figures with a hold line ──

def test_ttfa_ends_at_the_first_audio_and_the_answers_own_is_kept_apart():
    pytest.importorskip("soxr")
    from ai_agent_service.api.routes.voice import _figures
    t = {"kind": "turn", "speech_end": 10.0, "turn_end": 10.25, "asr_done": 10.5, "hold": 11.5, "first_audio": 11.5,
         "answer_audio": 13.0, "agent_done": 12.5}
    figures = _figures(t)
    assert figures["ttfa_ms"] == 1500 and figures["ttfa_answer_ms"] == 3000 and figures["hold_ms"] == 1500
    lines = [line for lines in fallback.HOLD_BY_TOOL.values() for line in lines]
    assert all(not any(ch.isdigit() for ch in line) and "?" not in line for line in lines)


def test_a_hold_line_is_for_a_lookup_only_and_speaks_to_the_caller_as_known():
    assert fallback.hold_line("order_create", "chị") is None and fallback.hold_line("handoff_transfer", "chị") is None
    assert all("cho chị" in fallback.hold_line("order_status", "chị", t) for t in ("t1", "t2"))
    assert "anh/chị" not in fallback.hold_line("inventory_check", "anh/chị")  # unknown: no form of address


# ── plan 002: the first clause of a spoken answer goes to the voice ahead of its sentence ──

class Chunks:
    """An advisor that streams its answer in the chunks given."""

    def __init__(self, *chunks):
        self.chunks = chunks

    def stream(self, messages, view, *, user_id=None):
        async def events():
            for chunk in self.chunks:
                yield AdvisorEvent("text", text=chunk)
            yield AdvisorEvent("done", draft=Draft(text="".join(self.chunks), tool_results=[], model="fixture",
                                                   model_calls=1, seconds=0.0))
        return events()


class Reviewer:
    def __init__(self):
        self.read = []

    async def review(self, view):
        from ai_agent_service.agents.policy import PolicyVerdict
        self.read.append(view.text)
        return PolicyVerdict(passed=True)


@pytest.mark.asyncio
async def test_the_first_clause_is_said_ahead_and_its_sentence_reviewed_whole(monkeypatch):
    monkeypatch.setenv("ADVISOR_FIRST_CLAUSE", "1")
    spoken, policy = [], Reviewer()

    async def emit(kind, text):
        if kind == "sentence":
            spoken.append(text)

    state = {"call_id": "fixture", "turn_id": "t1", "mode": "speak", "tier": "VERIFIED", "lane": "NEW", "channel": "hotline",
             "now": datetime.now(timezone.utc), "messages": [HumanMessage(content="Nồi chiên có mấy chế độ em?")]}
    advisor = Chunks("Dạ nồi chiên này có tám chế độ nấu ", "tự động, hẹn giờ được ", "và tự ngắt khi xong ạ. ",
                     "Chị cần em tư vấn thêm gì không ạ?")
    update = await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=advisor, policy=policy, emit=emit)))
    assert spoken[0] == "Dạ nồi chiên này có tám chế độ nấu tự động,"  # said before its sentence ended
    assert spoken[1] == "hẹn giờ được và tự ngắt khi xong ạ."
    # reviewed whole, and with the next sentence in the same request: one request at a time per turn
    assert any("Dạ nồi chiên này có tám chế độ nấu tự động, hẹn giờ được và tự ngắt khi xong ạ." in t for t in policy.read)
    assert all(text != spoken[0] for text in policy.read) and len(policy.read) == 1  # never the half sentence alone
    assert update["guard"]["sentences"] == 2  # still two sentences, against the three allowed


@pytest.mark.asyncio
async def test_without_the_switch_or_on_chat_the_sentence_is_said_whole(monkeypatch):
    for switch, channel in (("0", "hotline"), ("1", "web")):
        monkeypatch.setenv("ADVISOR_FIRST_CLAUSE", switch)
        spoken = []

        async def emit(kind, text):
            if kind == "sentence":
                spoken.append(text)

        state = {"call_id": "fixture", "turn_id": "t1", "mode": "speak", "tier": "VERIFIED", "lane": "NEW", "channel": channel,
                 "now": datetime.now(timezone.utc), "messages": [HumanMessage(content="Nồi chiên có mấy chế độ em?")]}
        advisor = Chunks("Dạ nồi chiên này có tám chế độ nấu ", "tự động, hẹn giờ được ", "và tự ngắt khi xong ạ. ")
        await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=advisor, emit=emit)))
        assert spoken == ["Dạ nồi chiên này có tám chế độ nấu tự động, hẹn giờ được và tự ngắt khi xong ạ."], (switch, channel)


class Preamble:
    """A line, then a lookup, then the answer: as a model writes a line before a tool (no space after its stop)."""

    def stream(self, messages, view, *, user_id=None):
        async def events():
            yield AdvisorEvent("text", text="Dạ em xem hành trình đơn của chị ngay ạ.")
            yield AdvisorEvent("tool_started", text="order_status")
            result = {"name": "order.status", "args": {}, "result": {"ok": True, "data": {"orders": []}}}
            yield AdvisorEvent("tools", results=(result,), draft=Draft(text="", tool_results=[result], model="fixture",
                                                                       model_calls=1, seconds=0.0))
            yield AdvisorEvent("text", text="Đơn của chị đang trên đường giao ạ.")
            yield AdvisorEvent("done", draft=Draft(text="", tool_results=[result], model="fixture", model_calls=2,
                                                   seconds=0.0))
        return events()


@pytest.mark.asyncio
async def test_a_line_before_a_tool_is_said_when_the_tool_starts_not_a_round_later():
    order = []

    async def emit(kind, text):
        order.append((kind, text))

    state = {"call_id": "fixture", "turn_id": "t1", "mode": "speak", "tier": "VERIFIED", "lane": "NEW", "channel": "hotline",
             "now": datetime.now(timezone.utc), "messages": [HumanMessage(content="Đơn của chị tới đâu rồi em?")]}
    await nodes.advisor(state, SimpleNamespace(context=HotContext(advisor=Preamble(), emit=emit)))
    sentences = [text for kind, text in order if kind == "sentence"]
    assert sentences == ["Dạ em xem hành trình đơn của chị ngay ạ.", "Đơn của chị đang trên đường giao ạ."]
    # said before the hold line was registered, that is, before the lookup ran
    assert [kind for kind, _ in order].index("sentence") < [kind for kind, _ in order].index("hold_line")


def test_cached_tokens_are_read_in_any_processing_tier():
    from types import SimpleNamespace as NS
    from ai_agent_service.llm.callback_handler import cached_tokens
    def result(details):
        return NS(generations=[[NS(message=NS(usage_metadata={"input_token_details": details}))]])
    assert cached_tokens(result({"cache_read": 4000})) == 4000
    assert cached_tokens(result({"priority_cache_read": 3900, "priority": 4100})) == 3900
    assert cached_tokens(result({"cache_read": 0})) == 0
