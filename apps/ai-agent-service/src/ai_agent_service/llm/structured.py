"""Structured output: a Pydantic schema, repaired JSON, and retries that say what was wrong.

``with_structured_output`` gives the provider the schema (a JSON schema or a
tool, as each integration does it), field descriptions included, and parses
the answer. A model still writes JSON a parser rejects now and then: a
trailing comma, an unescaped quote, a value of the wrong type, an answer cut
off at the token limit. :class:`StructuredOutput` then

1. repairs the raw answer with ``json_repair`` and validates it against the
   schema; an answer that validates once repaired is a success, and the
   report says it was repaired;
2. otherwise asks again, up to ``attempts`` calls in all, with the error
   appended to the request so the model can correct it.

An error of the call itself (network, authentication, budget, a provider
outage) is not retried here: the client's ``max_retries`` handles transport,
and the caller decides what a failed call means.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Generic, Sequence, TypeVar

import json_repair
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

Request = str | Sequence[BaseMessage]

#: Said after an answer cut off at the token limit, unless the caller has its own words for it.
LENGTH_HINT = ("The previous answer was cut off at the output token limit. Answer again, shorter: "
               "each item once, short strings, no explanations.")


@dataclass
class Report:
    """What it took to get one valid answer."""

    attempts: int = 0
    #: ``"<ErrorType>: <message>"`` of each attempt that failed, in order.
    errors: list[str] = field(default_factory=list)
    #: The answer validated only after ``json_repair`` fixed its JSON.
    repaired: bool = False


class StructuredOutputError(RuntimeError):
    """No attempt gave a valid answer, or the call itself failed; ``cause`` is the last error."""

    def __init__(self, message: str, *, cause: BaseException, report: Report) -> None:
        super().__init__(message)
        self.cause = cause
        self.report = report


class InvalidOutput(ValueError):
    """The model answered, but not with JSON the schema accepts."""


def is_output_error(error: BaseException) -> bool:
    """Whether *error* means the answer was wrong (worth another attempt), not the call."""
    return (isinstance(error, (OutputParserException, ValueError))
            or type(error).__name__ == "LengthFinishReasonError")


def parse(value: Any, schema: type[T]) -> T:
    """*value* (a schema instance, a dict, or JSON text, possibly broken) as *schema*.

    Raises :class:`InvalidOutput` when even the repaired JSON does not validate.
    """
    if isinstance(value, schema):
        return value
    if isinstance(value, BaseModel):
        value = value.model_dump()
    if isinstance(value, (str, bytes)):
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        try:
            return schema.model_validate_json(text)
        except ValueError:
            value = json_repair.loads(text)
    try:
        return schema.model_validate(value)
    except ValueError as error:
        raise InvalidOutput(str(error)) from error


class StructuredOutput(Generic[T]):
    """*llm* answering in *schema*: parsed, repaired when it can be, asked again when it cannot."""

    def __init__(self, llm: Any, schema: type[T], *, attempts: int = 3, length_hint: str = LENGTH_HINT) -> None:
        self.schema = schema
        self.attempts = max(1, attempts)
        self.length_hint = length_hint
        self._runnable = llm.with_structured_output(schema, include_raw=True)

    async def ainvoke(self, request: Request) -> T:
        return (await self.arun(request))[0]

    def invoke(self, request: Request) -> T:
        return self.run(request)[0]

    async def arun(self, request: Request) -> tuple[T, Report]:
        """The valid answer and its :class:`Report`; :class:`StructuredOutputError` when there is none."""
        report = Report()
        while True:
            report.attempts += 1
            try:
                return self._answer(await self._runnable.ainvoke(request), report), report
            except Exception as error:  # noqa: BLE001 - sorted into retry or give up just below
                request = self._next_request(request, error, report)

    def run(self, request: Request) -> tuple[T, Report]:
        """:meth:`arun`, synchronously."""
        report = Report()
        while True:
            report.attempts += 1
            try:
                return self._answer(self._runnable.invoke(request), report), report
            except Exception as error:  # noqa: BLE001 - sorted into retry or give up just below
                request = self._next_request(request, error, report)

    def _answer(self, result: Any, report: Report) -> T:
        """The schema instance in what the runnable returned, repairing the raw answer if it did not parse."""
        if not (isinstance(result, dict) and "raw" in result):
            return parse(result, self.schema)  # a runnable without include_raw (a test's stand-in)
        if result.get("parsed") is not None and result.get("parsing_error") is None:
            return parse(result["parsed"], self.schema)
        for candidate in _raw_answers(result.get("raw")):
            try:
                value = parse(candidate, self.schema)
            except InvalidOutput:
                continue
            report.repaired = True
            logger.info("%s: answer repaired with json_repair", self.schema.__name__)
            return value
        error = result.get("parsing_error")
        raise InvalidOutput(str(error) if error else "the answer held no JSON object")

    def _next_request(self, request: Request, error: Exception, report: Report) -> Request:
        """The request with the error appended, or raise when *error* is not worth another attempt."""
        report.errors.append(f"{type(error).__name__}: {error}"[:300])
        if not is_output_error(error) or report.attempts >= self.attempts:
            raise StructuredOutputError(f"{self.schema.__name__}: {report.errors[-1]}", cause=error,
                                        report=report) from error
        logger.warning("%s attempt %d invalid (%s); asking again", self.schema.__name__, report.attempts,
                       type(error).__name__)
        if type(error).__name__ == "LengthFinishReasonError":
            note = self.length_hint
        else:
            note = (f"The previous answer did not match the required JSON schema: {str(error)[:500]}\n"
                    f"Answer again with one JSON object that matches the {self.schema.__name__} schema exactly.")
        if isinstance(request, str):
            return f"{request}\n\nRETRY: {note}"
        return [*request, HumanMessage(content=f"RETRY: {note}")]


def _raw_answers(raw: Any) -> list[Any]:
    """Every place an answer may sit in a raw message: tool-call arguments, then the text."""
    if raw is None:
        return []
    found: list[Any] = [call.get("args") for call in getattr(raw, "tool_calls", None) or []]
    found += [call.get("args") for call in getattr(raw, "invalid_tool_calls", None) or []]
    content = getattr(raw, "content", None)
    if isinstance(content, list):  # Gemini and Anthropic return parts
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    if isinstance(content, str) and content.strip():
        found.append(content)
    return [value for value in found if value not in (None, "", {})]
