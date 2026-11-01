"""Structured output: broken JSON repaired, invalid answers asked again with the error, call errors not retried."""
import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from ai_agent_service.llm.structured import StructuredOutput, StructuredOutputError, parse


class Answer(BaseModel):
    """A fixture schema."""

    items: list[int] = Field(description="Some numbers.")
    note: str = Field(description="A note.")


class Model:
    """Stands in for a chat model: ``with_structured_output(..., include_raw=True)`` answers from *results*."""

    def __init__(self, *results):
        self.results, self.requests = list(results), []

    def with_structured_output(self, schema, include_raw=False):
        assert include_raw
        self.schema = schema
        return self

    async def ainvoke(self, request):
        return self.invoke(request)

    def invoke(self, request):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def unparsed(content="", **message):
    return {"raw": AIMessage(content=content, **message), "parsed": None, "parsing_error": ValueError("bad JSON")}


@pytest.mark.asyncio
async def test_broken_json_is_repaired_without_another_call():
    model = Model(unparsed('{"items": [1, 2,], "note": "ok'))
    value, report = await StructuredOutput(model, Answer).arun("prompt")
    assert value == Answer(items=[1, 2], note="ok")
    assert (report.attempts, report.repaired, report.errors) == (1, True, [])


def test_broken_tool_call_arguments_are_repaired():
    model = Model(unparsed(invalid_tool_calls=[{"name": "Answer", "args": "{'items': [3], 'note': 'x',}", "id": "1"}]))
    value, report = StructuredOutput(model, Answer).run("prompt")
    assert value == Answer(items=[3], note="x") and report.repaired


@pytest.mark.asyncio
async def test_invalid_answer_is_asked_again_with_the_error():
    model = Model(unparsed('{"items": "many"}'), unparsed("no json here"),
                  {"raw": AIMessage(content=""), "parsed": Answer(items=[1], note="n"), "parsing_error": None})
    value, report = await StructuredOutput(model, Answer, attempts=3).arun("prompt")
    assert value.items == [1]
    assert report.attempts == 3 and len(report.errors) == 2
    assert model.requests[0] == "prompt"
    assert "RETRY:" in model.requests[1] and "Answer" in model.requests[1]


@pytest.mark.asyncio
async def test_gives_up_after_the_attempts():
    model = Model(unparsed("{}"), unparsed("{}"))
    with pytest.raises(StructuredOutputError) as failed:
        await StructuredOutput(model, Answer, attempts=2).arun("prompt")
    assert failed.value.report.attempts == 2 and len(model.requests) == 2


@pytest.mark.asyncio
async def test_a_failed_call_is_not_retried():
    model = Model(RuntimeError("budget exhausted"), unparsed("{}"))
    with pytest.raises(StructuredOutputError) as failed:
        await StructuredOutput(model, Answer).arun("prompt")
    assert isinstance(failed.value.cause, RuntimeError) and len(model.requests) == 1


def test_message_requests_get_the_retry_as_a_new_message():
    from langchain_core.messages import HumanMessage

    model = Model(unparsed("[]"), {"raw": None, "parsed": Answer(items=[], note=""), "parsing_error": None})
    StructuredOutput(model, Answer).run([HumanMessage(content="prompt")])
    assert [m.content for m in model.requests[1]][0] == "prompt"
    assert model.requests[1][-1].content.startswith("RETRY:")


def test_parse_accepts_instances_dicts_and_text():
    assert parse({"items": [1], "note": "a"}, Answer) == parse('{"items": [1], "note": "a"}', Answer)
    assert parse(Answer(items=[], note=""), Answer).items == []


@pytest.mark.parametrize("async_call", [False, True])
@pytest.mark.asyncio
async def test_invocation_configuration_errors_are_not_output_retries(async_call):
    from pydantic import ValidationError

    try:
        Answer.model_validate({"items": "bad"})
    except ValidationError as invalid:
        errors = [ValueError("invalid model input configuration"), invalid]
    for error in errors:
        model = Model(error, unparsed("{}"))
        with pytest.raises(StructuredOutputError) as failed:
            if async_call:
                await StructuredOutput(model, Answer).arun("prompt")
            else:
                StructuredOutput(model, Answer).run("prompt")
        assert failed.value.cause is error
        assert len(model.requests) == failed.value.report.attempts == 1


def test_retry_and_report_keep_the_entire_validation_error():
    error = ValueError("validation detail " + "x" * 2000 + " END OF ERROR")
    model = Model({"raw": AIMessage(content="{}"), "parsed": None, "parsing_error": error},
                  {"raw": None, "parsed": Answer(items=[], note=""), "parsing_error": None})
    _, report = StructuredOutput(model, Answer).run("prompt")
    assert str(error) in model.requests[1] and str(error) in report.errors[0]
    # Repair validation errors are preserved too, rather than only the native parser's generic error.
    assert "items" in model.requests[1] and "note" in model.requests[1]


@pytest.mark.parametrize("raw", [
    {"tool_calls": [{"args": "{'items': [2], 'note': 'ok',}"}]},
    {"invalid_tool_calls": [{"args": "{'items': [2], 'note': 'ok',}"}]},
    {"additional_kwargs": {"tool_calls": [{"function": {"arguments": "{'items': [2], 'note': 'ok',}"}}]}},
    {"additional_kwargs": {"function_call": {"arguments": "{'items': [2], 'note': 'ok',}"}}},
    {"content": [{"type": "tool_use", "input": {"items": [2], "note": "ok"}}]},
    {"content": [{"type": "thinking", "text": "ignore me"},
                 {"type": "text", "text": "{'items': [2], 'note': 'ok',}"}]},
])
def test_raw_provider_carriers_are_repaired_without_another_call(raw):
    model = Model({"raw": raw, "parsed": None, "parsing_error": ValueError("bad JSON")})
    value, report = StructuredOutput(model, Answer).run("prompt")
    assert value == Answer(items=[2], note="ok")
    assert report.repaired == ("tool_use" not in str(raw))
    assert report.attempts == len(model.requests) == 1
    assert model.schema == Answer.model_json_schema()


@pytest.mark.parametrize("metadata", [
    {"finish_reason": "length"}, {"stop_reason": "max_tokens"}, {"finishReason": "MAX_TOKENS"},
])
@pytest.mark.parametrize("parsed", [None, Answer(items=[1], note="partial")])
def test_truncated_json_is_never_accepted_as_a_complete_answer(metadata, parsed):
    raw = AIMessage(content='{"items": [1], "note": "partial', response_metadata=metadata)
    model = Model({"raw": raw, "parsed": parsed, "parsing_error": None},
                  {"raw": None, "parsed": Answer(items=[1, 2], note="complete"), "parsing_error": None})
    value, report = StructuredOutput(model, Answer).run("prompt")
    assert value.items == [1, 2] and value.note == "complete"
    assert report.attempts == 2 and not report.repaired
    assert "ngắn hơn" in model.requests[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_call", [False, True])
@pytest.mark.parametrize("first_content,expected_calls,repaired", [
    ("{'items':[2], 'note':'ok',}", 1, True), ("{}", 2, False),
])
async def test_callbacks_count_only_actual_model_calls(async_call, first_content, expected_calls, repaired):
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.language_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.runnables import RunnableLambda

    class Counter(BaseCallbackHandler):
        starts = ends = 0

        def on_chat_model_start(self, *args, **kwargs):
            self.starts += 1

        def on_llm_end(self, *args, **kwargs):
            self.ends += 1

    class LocalModel(BaseChatModel):
        replies: list[str]

        @property
        def _llm_type(self):
            return "offline-structured-fixture"

        def _generate(self, *args, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.replies.pop(0)))])

        def with_structured_output(self, schema, include_raw=False):
            assert schema == Answer.model_json_schema() and include_raw
            return self | RunnableLambda(lambda raw: {"raw": raw, "parsed": None,
                                                      "parsing_error": ValueError("bad JSON")})

    counter = Counter()
    helper = StructuredOutput(LocalModel(callbacks=[counter], replies=[first_content, '{"items":[2], "note":"ok"}']), Answer)
    value, report = await helper.arun("prompt") if async_call else helper.run("prompt")
    assert value.items == [2] and report.repaired == repaired
    assert counter.starts == counter.ends == report.attempts == expected_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("async_call", [False, True])
async def test_a_native_parser_exception_can_be_repaired_without_another_call(async_call):
    from langchain_core.exceptions import OutputParserException

    model = Model(OutputParserException("parser failed", llm_output="{'items': [4], 'note':'ok',}"))
    helper = StructuredOutput(model, Answer)
    value, report = await helper.arun("prompt") if async_call else helper.run("prompt")
    assert value.items == [4] and report.repaired and len(model.requests) == 1


def test_empty_tool_arguments_can_validate_a_schema_with_defaults():
    class Defaults(BaseModel):
        note: str = ""

    model = Model({"raw": {"tool_calls": [{"args": {}}]}, "parsed": None, "parsing_error": ValueError("bad")})
    value, report = StructuredOutput(model, Defaults).run("prompt")
    assert value.note == "" and not report.repaired and report.attempts == 1


def test_native_parser_cannot_hide_a_truncation_cause():
    from langchain_core.exceptions import OutputParserException
    from openai import LengthFinishReasonError
    from openai.types.chat import ChatCompletion

    error = OutputParserException("parser failed", llm_output='{"items":[1],"note":"partial')
    error.__cause__ = LengthFinishReasonError(completion=ChatCompletion(
        id="fixture", model="fixture", created=0, object="chat.completion", choices=[]))
    model = Model(error, {"raw": None, "parsed": Answer(items=[1, 2], note="complete"), "parsing_error": None})
    value, report = StructuredOutput(model, Answer).run("prompt")
    assert value.items == [1, 2] and report.attempts == 2 and not report.repaired
    assert "ngắn hơn" in model.requests[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_call", [False, True])
async def test_provider_returns_raw_before_local_pydantic_validation(async_call):
    """Reproduce the real cohort's native validation failure without a provider call."""
    import json

    import httpx
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_openai import ChatOpenAI
    from pydantic import model_validator

    class Span(BaseModel):
        """Bằng chứng nguyên văn trong một lượt."""

        start: int = Field(description="Vị trí bắt đầu.")
        end: int = Field(description="Vị trí kết thúc, lớn hơn start.")

        @model_validator(mode="after")
        def valid_span(self):
            if self.end <= self.start:
                raise ValueError("end phải lớn hơn start cho quote không rỗng")
            return self

    class Counter(BaseCallbackHandler):
        ends = 0

        def on_llm_end(self, *args, **kwargs):
            self.ends += 1

    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        supplied = body["response_format"]["json_schema"]["schema"]
        assert body["response_format"]["json_schema"]["description"] == Span.__doc__
        assert supplied["properties"]["end"]["description"] == Span.model_fields["end"].description
        return httpx.Response(200, json={
            "id": "offline-fixture", "model": "gpt-4.1-mini", "created": 0,
            "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"start": 2, "end": 1 if len(requests) == 1 else 3})}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    counter = Counter()
    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        async with httpx.AsyncClient(transport=transport) as async_client:
            llm = ChatOpenAI(model="gpt-4.1-mini", api_key="offline-fixture", max_retries=0,
                             http_client=client, http_async_client=async_client, callbacks=[counter])
            helper = StructuredOutput(llm, Span, attempts=2)
            value, report = await helper.arun("prompt") if async_call else helper.run("prompt")
    assert value == Span(start=2, end=3)
    assert len(requests) == counter.ends == report.attempts == 2
    assert "end phải lớn hơn start cho quote không rỗng" in requests[1]["messages"][-1]["content"]
    assert report.errors[0].removeprefix("InvalidOutput: ") in requests[1]["messages"][-1]["content"]
