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
