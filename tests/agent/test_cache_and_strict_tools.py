"""How requests are shaped for OpenAI: the cache boundary, strict tools, results kept across turns. No network."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from langchain.agents.middleware.types import ToolCallRequest
from ai_agent_service.agents import advisor
from ai_agent_service.components.guardrails import actions, purchase
from ai_agent_service.components.intake import pii
from ai_agent_service.agents.advisor import ActionGuardMiddleware, AdvisorAgent, AgentContext, TURN_CONTEXT, prompt_parts, system_prompt, with_turn_context
from ai_agent_service.agents import policy
from ai_agent_service.components.evaluation import scorers
from ai_agent_service.components.guardrails.hard import GuardInput, check
from ai_agent_service.components.intake.itn import amounts
from ai_agent_service.llm import decisions, factory, structured
from ai_agent_service.llm.factory import takes_reasoning
from ai_agent_service.mcp.tools import other_products_only, CHAINED, ChainLookupMiddleware, ToolGuardMiddleware, chained_lookups, strict_tool, without_nulls
from ai_agent_service.pipeline.hot import nodes

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone(timedelta(hours=7)))
#: Taken before the fixture that forbids building a real model in a test.
ORIGINAL_CREATE_LLM = factory.LLMFactory.__dict__["create_llm"]


def context(**changes):
    return AgentContext(**{"call_id": "c", "lane": "NEW", "tier": "VERIFIED", "now": NOW, **changes})


# ── the cache boundary ───────────────────────────────────────────────────


def test_what_never_changes_is_the_same_whatever_the_turn_brings():
    one, turn_one, _ = prompt_parts(context(knowledge_note="a", lane="NEW"))
    two, turn_two, _ = prompt_parts(context(now=NOW + timedelta(days=3), knowledge_note="b", brief_lines=(), warnings=("w",)))
    assert one == two and "Hôm nay:" not in one and "Nguồn sự thật" in one
    assert "Hôm nay:" in turn_one and turn_one != turn_two


def test_the_whole_prompt_is_still_one_text_for_a_provider_that_takes_one_message():
    static, turn, _ = prompt_parts(context())
    assert system_prompt(context())[0] == f"{static}\n\n{turn}"


def test_the_turns_context_comes_right_after_the_customer_so_the_first_block_stays_alone():
    first_turn = with_turn_context([HumanMessage("alo")], "ngữ cảnh")
    assert [type(m) for m in first_turn] == [HumanMessage, SystemMessage]
    assert first_turn[1].content == TURN_CONTEXT + "ngữ cảnh"
    run = [HumanMessage("một"), AIMessage("hai"), HumanMessage("ba"),
           AIMessage("", tool_calls=[{"name": "t", "args": {}, "id": "1"}]), ToolMessage("{}", tool_call_id="1")]
    shaped = with_turn_context(run, "ngữ cảnh")
    assert [type(m).__name__ for m in shaped] == ["HumanMessage", "AIMessage", "HumanMessage", "SystemMessage", "AIMessage", "ToolMessage"]


def test_the_budget_applies_to_the_turn_so_the_summary_is_not_cut_by_the_skills():
    _, turn, cut = prompt_parts(context(working_summary="tóm tắt"))
    assert "tóm tắt" in turn and "summary" not in cut


# ── strict tools ─────────────────────────────────────────────────────────


def quote_tool():
    return StructuredTool.from_function(coroutine=None, func=lambda **kw: "{}", name="pricing_get_quote", description="d", args_schema={
        "type": "object", "required": ["sku"], "additionalProperties": False, "properties": {
            "sku": {"type": "string", "description": "code"},
            "on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "description": "Set by the system"},
            "qty": {"default": 1, "type": "integer", "description": "units"},
            "customer_phone": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            "basket_skus": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}], "default": None},
        }})


def test_a_strict_tool_asks_only_what_the_model_should_write_and_says_it_all():
    function = strict_tool(quote_tool())["function"]
    parameters = function["parameters"]
    assert function["strict"] is True and parameters["additionalProperties"] is False
    assert set(parameters["properties"]) == {"sku", "qty", "basket_skus"} == set(parameters["required"])
    assert parameters["properties"]["sku"]["type"] == "string"
    assert {"type": "null"} in parameters["properties"]["qty"]["anyOf"]
    assert "default" not in json.dumps(parameters)


def test_the_handoff_brief_is_typed_for_the_model():
    tool = StructuredTool.from_function(func=lambda **kw: "{}", name="handoff_transfer", description="d", args_schema={
        "type": "object", "required": ["brief"], "properties": {"brief": {"type": "object", "additionalProperties": True},
                                                                  "idempotency_key": {"type": "string"}}})
    parameters = strict_tool(tool)["function"]["parameters"]
    brief = parameters["properties"]["brief"]
    assert set(parameters["properties"]) == {"brief"}
    assert brief["additionalProperties"] is False and "escalation_reason" in brief["required"]


def test_the_chat_client_sends_a_strict_tool_and_a_late_system_message_as_written(monkeypatch):
    model = ChatOpenAI(model="gpt-5.6-luna", api_key="x", reasoning_effort="none", use_responses_api=False)
    bound = model.bind_tools([strict_tool(quote_tool())])
    assert bound.kwargs["tools"][0]["function"]["strict"] is True
    payload = model._get_request_payload([SystemMessage("tĩnh"), HumanMessage("khách"), SystemMessage("động")])
    roles = [m["role"] for m in payload["messages"]]
    assert roles[1] == "user" and roles[0] == roles[2] and roles[0] in ("system", "developer")


def test_a_basket_holds_the_other_products():
    assert "basket_skus" not in other_products_only({"sku": "A", "qty": 1, "basket_skus": ["A"]})
    assert other_products_only({"sku": "A", "basket_skus": ["A", "B"]})["basket_skus"] == ["B"]
    assert other_products_only({"sku": "A", "qty": 2, "basket_skus": ["A"]})["basket_skus"] == ["A"]  # two units of it


def test_a_null_is_the_same_as_leaving_the_argument_out():
    calls = []

    class Request(SimpleNamespace):
        def override(self, **kw):
            calls.append(kw["tool_call"])
            return Request(tool_call=kw["tool_call"])

    cleaned = without_nulls(Request(tool_call={"name": "t", "args": {"sku": "A", "qty": None}, "id": "1"}))
    assert cleaned.tool_call["args"] == {"sku": "A"}
    same = Request(tool_call={"name": "t", "args": {"sku": "A"}, "id": "1"})
    assert without_nulls(same) is same


# ── settings per model ───────────────────────────────────────────────────


@pytest.mark.parametrize("provider,model,reasons", [("openai", "gpt-5.6-luna", True), ("openai", "gpt-6-luna", True),
                                                    ("openai", "gpt-4.1-mini", False), ("groq", "openai/gpt-oss-120b", False)])
def test_who_takes_a_reasoning_effort(provider, model, reasons):
    assert takes_reasoning(provider, model) is reasons


def test_a_model_that_takes_no_effort_is_not_sent_one_and_usage_is_on(monkeypatch):
    monkeypatch.setattr(factory, "require_api_key", lambda provider: "x")
    built = {}
    monkeypatch.setattr(factory.LLMFactory, "create_llm", ORIGINAL_CREATE_LLM)
    monkeypatch.setattr(factory, "init_chat_model", lambda model, **kwargs: built.update({model: kwargs}))
    base = {"provider": "openai", "temperature": None, "reasoning_effort": "none", "use_responses_api": False,
            "max_tokens": 10, "timeout": 5, "max_retries": 0, "rate_limits": {}}
    factory.LLMFactory.create_llm({**base, "model": "gpt-4.1-mini"}, rate_limited=False)
    factory.LLMFactory.create_llm({**base, "model": "gpt-5.6-luna"}, rate_limited=False)
    small, luna = built["gpt-4.1-mini"], built["gpt-5.6-luna"]
    assert "reasoning_effort" not in small and small["temperature"] == 0.0 and small["stream_usage"] is True
    assert luna["reasoning_effort"] == "none" and "temperature" not in luna and luna["stream_usage"] is True


# ── a search that finds one product ──────────────────────────────────────


def search_round(items, *others):
    calls = [{"name": "catalog_search", "args": {"query": "x"}, "id": "s"}, *others]
    return [HumanMessage("hỏi"), AIMessage("", tool_calls=calls),
            ToolMessage(json.dumps({"ok": True, "data": {"items": items}}), tool_call_id="s", name="catalog_search")]


def test_one_product_found_brings_its_price_and_stock():
    calls = chained_lookups(search_round([{"sku": "A"}]))
    assert [(c["name"], c["args"]) for c in calls] == [("pricing_get_quote", {"sku": "A", "qty": 1}), ("inventory_check", {"sku": "A"})]


def test_nothing_is_chained_for_several_products_none_or_a_call_already_made():
    assert chained_lookups(search_round([{"sku": "A"}, {"sku": "B"}])) == []
    assert chained_lookups(search_round([])) == []
    assert chained_lookups(search_round([{"sku": "A", "successor_sku": "B"}])) == []
    made = search_round([{"sku": "A"}], {"name": "pricing_get_quote", "args": {"sku": "A"}, "id": "q"})
    assert [c["name"] for c in chained_lookups(made)] == ["inventory_check"]
    assert chained_lookups([HumanMessage("hỏi")]) == []


@pytest.mark.asyncio
async def test_a_chained_round_runs_through_the_guard_and_is_not_a_model_call():
    ran = []

    async def tool(**kw):
        ran.append(kw)
        return json.dumps({"ok": True, "data": kw})

    quote = StructuredTool.from_function(coroutine=tool, name="pricing_get_quote", description="d",
                                         args_schema={"type": "object", "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}, "on": {"type": "string"}}})
    stock = StructuredTool.from_function(coroutine=tool, name="inventory_check", description="d",
                                         args_schema={"type": "object", "properties": {"sku": {"type": "string"}, "on": {"type": "string"}}})
    middleware = ChainLookupMiddleware([quote, stock], ToolGuardMiddleware(["pricing_get_quote", "inventory_check"]))
    runtime = SimpleNamespace(context=SimpleNamespace(on="2026-11-07", customer_phone=None))
    update = await middleware.abefore_model({"messages": search_round([{"sku": "A"}])}, runtime)
    ai, *results = update["messages"]
    assert ai.additional_kwargs[CHAINED] is True and [r.tool_call_id for r in results] == [c["id"] for c in ai.tool_calls]
    assert all(kw["on"] == "2026-11-07" for kw in ran)


# ── results kept across turns ────────────────────────────────────────────


def quote(sku, price, basket=(), qty=1):
    return {"name": "pricing.get_quote", "args": {"sku": sku, "qty": qty, "basket_skus": list(basket)},
            "result": {"ok": True, "data": {"sku": sku, "final_price_vnd": price}}}


def test_passages_read_stay_for_the_call_but_not_internal_or_old_ones():
    shown = [{"chunk_id": "A", "text": "a", "source": "policy"}, {"chunk_id": "B", "text": "b", "restricted": True},
             {"chunk_id": "C", "text": "c", "superseded": True}]
    assert nodes._passages_after({"Z": "z"}, shown) == {"Z": "z", "A": "a"}
    many = {str(i): "x" for i in range(20)}
    assert len(nodes._passages_after(many, [])) == nodes.PASSAGES_READ


def test_the_latest_result_per_subject_is_what_the_model_reads_again():
    log = [{"tool": "pricing.get_quote", "key": "A", "result": "old"}, {"tool": "inventory.check", "key": "A", "result": "s"},
           {"tool": "pricing.get_quote", "key": "A", "result": "new"}]
    assert [e["result"] for e in nodes.reusable_results(log)] == ["s", "new"]


def test_the_basket_follows_the_quotes_and_empties_with_the_order():
    basket = nodes._basket_after({}, [quote("A", 100), quote("B", 200, basket=["A"])])
    assert set(basket) == {"A", "B"}
    assert nodes._basket_lines(basket, {"A": 100, "B": 200}) == (("A", 100, 1), ("B", 200, 1))
    assert nodes._basket_lines(basket, {"A": 100}) == ()
    placed = {"name": "order.create", "args": {}, "result": {"ok": True, "data": {"order_id": "OD1"}}}
    assert nodes._basket_after(basket, [placed]) == {}


def test_a_number_told_in_an_earlier_turn_and_the_systems_total_are_sourced():
    said = "Dạ mình được hoàn 6.490.000đ ạ."
    view = dict(tool_results=(), tier="VERIFIED")
    assert not check(GuardInput(text=said, **view)).passed
    assert check(GuardInput(text=said, earlier_numbers=frozenset({6490000}), **view)).passed
    assert check(GuardInput(text="Dạ tổng 10.860.000đ ạ.", basket_total=10860000, **view)).passed
    assert nodes._earlier_numbers([{"tool": "catalog.search", "result": "6490000"}]) == frozenset()
    warranty = "Dạ máy bảo hành 24 tháng ạ."
    assert not check(GuardInput(text=warranty, **view)).passed
    assert check(GuardInput(text=warranty, earlier_counts=frozenset({24}), **view)).passed


@pytest.mark.parametrize("said,value", [("ngan sach tam 5 trieu ruoi", 5_500_000), ("5 trieu rưỡi thoi", 5_500_000),
                                        ("tam 300 nghin", 300_000), ("1 ty", 1_000_000_000), ("4890000 dong", 4_890_000)])
def test_money_said_without_diacritics_is_read(said, value):
    assert amounts(said) == [value]


# ── the order read back ──────────────────────────────────────────────────


def order_context(**changes):
    return context(call_id="c", channel="hotline", vault=pii.Vault(), customer_phone="0900000000",
                   seen_products=({"sku": "A", "name": "Máy A"}, {"sku": "B", "name": "Nồi B"}), **changes)


def test_a_read_back_says_names_and_never_a_product_code():
    record = purchase.draft({"sku": "A", "qty": 1, "price_vnd": 100000, "payment": "COD", "basket_skus": ["B"]}, order_context())
    assert "Máy A" in record["question"] and "Nồi B" in record["question"]
    assert not any(code in record["question"] + record["read_back"] for code in ("SKU-", "(A)", "nhóm đơn"))
    named = purchase.draft({"sku": "N", "qty": 1, "price_vnd": 100000, "payment": "COD"}, order_context(), names={"N": "Quạt N"})
    assert "Quạt N" in named["read_back"]


@pytest.mark.asyncio
@pytest.mark.parametrize("asked_for_it", [True, False])
async def test_an_order_the_customer_asked_for_is_read_back_and_placed_in_the_same_turn(asked_for_it):
    """PB-09 asks the order read back once before order.create, not a second yes after it (2026-11-10): a price
    quoted in this very turn is read back with the order; whether the customer asked for it is the PolicyAgent's."""
    asked, placed = [], []

    async def judge(intent, state):
        asked.append(intent)
        return asked_for_it

    async def handler(request):
        placed.append(request.tool_call["args"])
        return ToolMessage(json.dumps({"ok": True, "data": {"order_id": "OD1"}}), tool_call_id="1", name="order_create")

    call = {"name": "order_create", "args": {"sku": "A", "qty": 1, "price_vnd": 100000, "payment": "COD"}, "id": "1"}
    ctx = order_context(judge=judge, trusted_skus=frozenset({"A"}), quotes={})
    state = {"messages": [ToolMessage(json.dumps({"ok": True, "data": {"sku": "A", "final_price_vnd": 100000}}),
                                      tool_call_id="q", name="pricing_get_quote")]}
    request = ToolCallRequest(tool_call=call, tool=None, state=state, runtime=SimpleNamespace(context=ctx))
    answer = await ActionGuardMiddleware().awrap_tool_call(request, handler)
    assert asked == ["purchase"]
    if asked_for_it:
        assert len(placed) == 1 and ctx.consent["read_back"].startswith("Dạ em đọc lại đơn")
    else:
        assert placed == [] and json.loads(answer.content)["error"]["code"] == "CONFIRMATION_REQUIRED"


def test_cod_limit_counts_the_basket_this_order_goes_with():
    args = {"sku": "A", "price_vnd": 7000000, "qty": 1, "payment": "COD", "basket_skus": ["B", "A"]}
    assert actions._cod_order(args, 7000000, (), "", {"A": 7000000, "B": 4000000})
    assert not actions._cod_order({**args, "payment": "bank"}, 7000000, (), "", {"B": 4000000})
    assert not actions._cod_order(args, 7000000, (), "", {"B": 2000000})
    placed = ({"sku": "B", "price_vnd": 4000000, "qty": 1, "payment": "COD", "order_group": "1"},)
    assert not actions._cod_order({**args, "order_group": "2"}, 7000000, placed, "tach", {"B": 4000000})


def test_a_read_back_of_a_basket_gives_the_whole_total():
    record = purchase.draft({"sku": "A", "qty": 1, "price_vnd": 100000, "payment": "COD", "basket_skus": ["B"]},
                            order_context(), quotes={"B": 50000})
    assert "tổng cả giỏ 150.000đ" in record["read_back"] and "tổng cả giỏ 150.000đ" in record["question"]


@pytest.mark.asyncio
async def test_the_address_an_order_lacks_needs_no_agreement_but_any_other_change_does():
    asked = []

    async def judge(intent, state):
        asked.append(intent)
        return False

    ctx = order_context(judge=judge, recent=(("customer", "Lê Chân, Hải Phòng"),))
    bare = [{"order_id": "OD1", "sku": "A", "no_address": True}]
    assert await advisor._intents("order_update", {"order_id": "OD1", "action": "update_address"}, ctx, bare) == {}
    assert asked == []
    assert (await advisor._intents("order_update", {"order_id": "OD1", "action": "return"}, ctx, bare))["change"] is False
    full = [{"order_id": "OD1", "sku": "A", "no_address": False}]
    assert (await advisor._intents("order_update", {"order_id": "OD1", "action": "update_address"}, ctx, full))["change"] is False


def test_the_placeholder_mark_never_reaches_the_customer():
    assert nodes.MARKS.sub("", "Dạ đơn OD1 [Bn] đã có.") == "Dạ đơn OD1 đã có."


def test_the_tier_reaches_openai_only(monkeypatch):
    seen = {}
    monkeypatch.setattr(factory.LLMFactory, "create_llm", ORIGINAL_CREATE_LLM)
    monkeypatch.setattr(factory, "init_chat_model", lambda model, **kwargs: seen.update({model: kwargs}))
    # The keys are read once and cached, so setting them here would depend on the order the tests run in.
    monkeypatch.setattr(factory, "require_api_key", lambda provider: "x")
    factory.LLMFactory.create_llm({"provider": "openai", "model": "gpt-5.6-luna", "service_tier": "fast"}, rate_limited=False)
    assert seen["gpt-5.6-luna"]["service_tier"] == "fast"
    factory.LLMFactory.create_llm({"provider": "groq", "model": "m", "service_tier": "fast"}, rate_limited=False)
    assert "service_tier" not in seen["m"]


# ── the extractor ────────────────────────────────────────────────────────


def _response_format(runnable, depth=0):
    """Where the client's bound settings sit inside what ``with_structured_output`` returns."""
    kwargs = getattr(runnable, "kwargs", None)
    if kwargs and "response_format" in kwargs:
        return kwargs["response_format"]
    for name in ("first", "bound", "steps__", "mapper", "runnable", "middle", "last"):
        value = getattr(runnable, name, None)
        for inner in value.values() if isinstance(value, dict) else value if isinstance(value, (list, tuple)) else [value]:
            found = _response_format(inner, depth + 1) if inner is not None and depth < 6 else None
            if found:
                return found
    return None


def test_the_extractor_asks_for_a_schema_strict_mode_takes():
    schema = scorers.Items.model_json_schema()
    item = schema["$defs"]["Item"]
    assert "start" not in item["properties"] and "end" not in item["properties"]
    assert set(item["required"]) == set(item["properties"]) and item["additionalProperties"] is False
    assert not any(word in json.dumps(schema) for word in ('"minLength"', '"pattern"', '"minimum"', '"default"'))
    labeller = scorers.Extractor(ChatOpenAI(model="gpt-4.1-mini", api_key="x"), model_name="m")._labeller
    assert labeller.schema is scorers.Items
    assert '"strict": true' in json.dumps(_response_format(labeller._runnable))


def test_strict_mode_is_asked_only_of_the_client_that_takes_it():
    seen = {}

    class Model:
        _llm_type = "openai-chat"

        def with_structured_output(self, schema, **options):
            seen.update(options)
            return None

    structured.StructuredOutput(Model(), scorers.Items, strict=True)
    assert seen == {"include_raw": True, "strict": True}
    seen.clear()
    Model._llm_type = "other"
    structured.StructuredOutput(Model(), scorers.Items, strict=True)
    assert seen == {"include_raw": True}


def test_a_quote_said_twice_takes_its_places_in_turn_and_one_said_once_keeps_its_place():
    data = {"agent_text": "Size L phải không ạ? Size L phải không ạ?", "tool_texts": []}
    base = {"source_field": "agent_text", "quote": "Size L phải không ạ?"}
    kept, dropped = scorers.spanned([dict(base), dict(base), dict(base)], data)
    assert dropped == 0 and [k["start"] for k in kept] == [0, 21, 21]
    assert scorers.spanned([{**base, "quote": "không có"}], data) == ([], 1)


def test_a_bad_source_or_an_empty_quote_is_refused_by_the_model_of_an_item():
    good = {"kind": "claim", "slot_or_field": "price_vnd", "value": 1, "question_type": None, "speaker": "agent",
            "source_field": "agent_text", "quote": "q", "purpose": "p"}
    assert scorers.Item(**good)
    for change in ({"quote": ""}, {"source_field": "previous_sessions/0"}):
        with pytest.raises(ValueError):
            scorers.Item(**{**good, **change})


# ── Decisions ────────────────────────────────────────────────────────────


def test_the_rules_come_first_and_alone_with_a_breakpoint_and_are_long_enough_to_cache():
    message = decisions.rules_message(policy.RULES)
    part = message["content"][0]
    assert message["role"] == "developer" and part["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert len(policy.RULES) > 3072  # the guide's minimum prefix of 1,024 tokens, at about three characters a token here


def test_every_question_is_one_short_sentence_naming_a_rule_the_developer_message_defines():
    for name, question in {**policy.QUESTIONS, **policy.INTENTS}.items():
        assert f"## {name}\n" in policy.RULES and f"luật {name}" in question.instructions
        assert len(question.instructions) < 90 and question.rules_sha == policy.RULES_SHA


def test_a_review_reads_evidence_then_the_text_and_not_the_conversation():
    view = policy.PolicyInput(text="Dạ giá 100.000đ ạ.", tool_results=({"name": "pricing.get_quote", "result": {"data": {"x": 1}}},),
                              tier="VERIFIED", policy_snippets=("p",), earlier={"quotes": {}}, customer_said=("giá bao nhiêu",))
    rules, settled, results, text = policy.review_input(view)
    assert rules["role"] == "developer" and {settled["role"], results["role"], text["role"]} == {"user"}
    assert settled["content"][0]["data"]["policy"] == ["p"] and settled["content"][1]["prompt_cache_breakpoint"]
    assert results["content"][0]["data"]["tool_results"][0]["tool"] == "pricing.get_quote"
    assert results["content"][0]["data"]["tool_results"][0]["ok"] is False
    assert "prompt_cache_breakpoint" not in results["content"][1] and "Dạ giá 100.000đ ạ." in text["content"]
    assert not any(m["role"] == "assistant" for m in policy.review_input(view))


def test_an_intent_reads_the_facts_then_the_conversation_by_role():
    messages = policy.intent_input({"recent_messages": [{"speaker": "assistant", "text": "Em chốt đơn nhé?"},
                                                         {"speaker": "customer", "text": "chốt"}], "order": "1 máy"})
    assert [m["role"] for m in messages] == ["developer", "user", "assistant", "user"]
    assert messages[1]["content"][0]["data"] == {"order": "1 máy"}
    assert messages[-1]["content"] == "chốt"  # the last message is the customer's
    assert len(policy.intent_input({"recent_messages": [{"speaker": "customer", "text": "có"}]})) == 2


@pytest.mark.asyncio
async def test_answers_come_by_name_and_a_refusal_has_no_probability(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    sent = {}

    async def create(**body):
        sent.update(body)
        usage = SimpleNamespace(input_tokens=1200, output_tokens=2,
                                input_tokens_details=SimpleNamespace(cached_tokens=1100, cache_write_tokens=0))
        return SimpleNamespace(model="gpt-6-luna", usage=usage, answers=[
            SimpleNamespace(type="predicate", name="a", probability=0.9), SimpleNamespace(type="refusal", name="b")])

    monkeypatch.setattr(decisions, "_api", lambda: SimpleNamespace(decisions=SimpleNamespace(create=create)))
    decision = await decisions.evaluate("policy", [{"role": "user", "content": "x"}], {"a": decisions.Predicate(instructions="A?"),
                                                              "b": decisions.Predicate(instructions="B?")}, wait=True)
    assert decision.answers["a"].probability == 0.9 and decision.answers["b"].probability is None
    assert decision.cached_tokens == 1100
    assert sent["model"] == "gpt-6-luna" and [q["type"] for q in sent["questions"]] == ["predicate", "predicate"]


@pytest.mark.asyncio
async def test_no_key_is_no_answer_not_a_failure(monkeypatch):
    monkeypatch.setattr(decisions, "has_api_key", lambda provider: False)
    with pytest.raises(decisions.DecisionUnavailable) as caught:
        await decisions.evaluate("policy", [], {"a": decisions.Predicate(instructions="A?")})
    assert caught.value.code == "NO_KEY"


# ── the whole run, against a fake OpenAI endpoint ────────────────────────


def sse(*chunks):
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks] + ["data: [DONE]\n\n"]
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(lines).encode())


def chunk(**delta):
    return {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "gpt-5.6-luna",
            "choices": [{"index": 0, "delta": {"role": "assistant", **delta}, "finish_reason": None}]}


@pytest.mark.asyncio
async def test_a_run_sends_the_boundary_strict_tools_and_chains_the_quote():
    requests = []

    def answer(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            call = {"index": 0, "id": "s1", "type": "function",
                    "function": {"name": "catalog_search", "arguments": json.dumps({"query": "AirPure", "category": None})}}
            return sse(chunk(tool_calls=[call]))
        return sse(chunk(content="Dạ AirPure X giá 4.890.000đ ạ."))

    ran = []

    def tool(name, data, properties):
        async def run(**kwargs):
            ran.append((name, kwargs))
            return json.dumps({"ok": True, "data": data})
        return StructuredTool.from_function(coroutine=run, name=name, description=name, args_schema={
            "type": "object", "properties": properties, "additionalProperties": False})

    sku, day = {"sku": {"type": "string"}}, {"on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}}
    tools = [tool("catalog_search", {"items": [{"sku": "SKU-AP-X", "name": "AirPure X"}]},
                  {"query": {"type": "string"}, "category": {"type": "string"}}),
             tool("pricing_get_quote", {"sku": "SKU-AP-X", "final_price_vnd": 4890000}, {**sku, "qty": {"type": "integer"}, **day}),
             tool("inventory_check", {"sku": "SKU-AP-X", "in_stock": True}, {**sku, **day})]
    model = ChatOpenAI(model="gpt-5.6-luna", api_key="x", reasoning_effort="none", use_responses_api=False, stream_usage=True,
                       http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)), max_retries=0)
    agent = AdvisorAgent(tools=tools, llm=model, retries=0)
    context = AgentContext(call_id="c", lane="NEW", tier="VERIFIED", now=NOW, on="2026-11-07", turn_id="t1")
    events = [event async for event in agent.stream([HumanMessage("máy AirPure giá bao nhiêu")], context)]

    # Two model calls: the search, then the answer, with the quote and the stock already in hand.
    assert len(requests) == 2
    first, second = requests
    assert first["messages"][0]["content"] == second["messages"][0]["content"] and "Hôm nay:" not in first["messages"][0]["content"]
    assert [m["role"] for m in first["messages"]][1] == "user" and first["messages"][2]["content"].startswith(TURN_CONTEXT)
    names = {t["function"]["name"]: t["function"] for t in first["tools"]}
    assert all(f["strict"] is True for f in names.values()) and "on" not in names["pricing_get_quote"]["parameters"]["properties"]
    called = [c["function"]["name"] for m in second["messages"] for c in m.get("tool_calls") or []]
    assert called == ["catalog_search", "pricing_get_quote", "inventory_check"]
    tool_turns = [m for m in second["messages"] if m["role"] == "tool"]
    assert len(tool_turns) == 3 and "4890000" in tool_turns[1]["content"]
    # What ran, with the null gone and the day filled in; the trace sees all three, and one chained round is no model call.
    assert ran[0] == ("catalog_search", {"query": "AirPure"})
    assert ("pricing_get_quote", {"sku": "SKU-AP-X", "qty": 1, "on": "2026-11-07"}) in ran
    done = events[-1].draft
    assert [r["name"] for r in done.tool_results] == ["catalog.search", "pricing.get_quote", "inventory.check"]
    assert done.model_calls == 2 and done.text.startswith("Dạ AirPure X")
