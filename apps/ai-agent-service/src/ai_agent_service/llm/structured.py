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
LENGTH_HINT = ("Câu trả lời trước bị cắt ở giới hạn token đầu ra. Hãy trả lời lại đầy đủ nhưng ngắn hơn: "
               "mỗi mục một lần, chuỗi ngắn, không giải thích thêm.")


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


class TruncatedOutput(InvalidOutput):
    """The provider marked the answer incomplete; repairing it cannot restore omitted items."""


def is_output_error(error: BaseException) -> bool:
    """Whether *error* means the answer was wrong (worth another attempt), not the call."""
    return (isinstance(error, (OutputParserException, InvalidOutput))
            or type(error).__name__ == "LengthFinishReasonError")


def parse(value: Any, schema: type[T]) -> T:
    """*value* (a schema instance, a dict, or JSON text, possibly broken) as *schema*.

    Raises :class:`InvalidOutput` when even the repaired JSON does not validate.
    """
    return _parse(value, schema)[0]


def _parse(value: Any, schema: type[T]) -> tuple[T, bool]:
    repaired = False
    if isinstance(value, schema):
        return value, repaired
    if isinstance(value, BaseModel):
        value = value.model_dump()
    try:
        if isinstance(value, (str, bytes)):
            text = value.decode("utf-8") if isinstance(value, bytes) else value
            try:
                return schema.model_validate_json(text), repaired
            except ValueError:
                value = json_repair.loads(text)
                repaired = True
        return schema.model_validate(value), repaired
    except (ValueError, TypeError, RecursionError) as error:
        raise InvalidOutput(str(error)) from error


class StructuredOutput(Generic[T]):
    """*llm* answering in *schema*: parsed, repaired when it can be, asked again when it cannot."""

    def __init__(self, llm: Any, schema: type[T], *, attempts: int = 3, length_hint: str = LENGTH_HINT) -> None:
        self.schema = schema
        self.attempts = max(1, attempts)
        self.length_hint = length_hint
        # SDK-side Pydantic validators can raise before raw output/usage reaches us.
        self._runnable = llm.with_structured_output(schema.model_json_schema(), include_raw=True)

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
                try:
                    result = await self._runnable.ainvoke(request)
                except OutputParserException as error:
                    result = {"raw": {"content": error.llm_output}, "parsed": None, "parsing_error": error}
                return self._answer(result, report), report
            except Exception as error:  # noqa: BLE001 - sorted into retry or give up just below
                request = self._next_request(request, error, report)

    def run(self, request: Request) -> tuple[T, Report]:
        """:meth:`arun`, synchronously."""
        report = Report()
        while True:
            report.attempts += 1
            try:
                try:
                    result = self._runnable.invoke(request)
                except OutputParserException as error:
                    result = {"raw": {"content": error.llm_output}, "parsed": None, "parsing_error": error}
                return self._answer(result, report), report
            except Exception as error:  # noqa: BLE001 - sorted into retry or give up just below
                request = self._next_request(request, error, report)

    def _answer(self, result: Any, report: Report) -> T:
        """The schema instance in what the runnable returned, repairing the raw answer if it did not parse."""
        if not (isinstance(result, dict) and "raw" in result):
            return parse(result, self.schema)  # a runnable without include_raw (a test's stand-in)
        error = result.get("parsing_error")
        if _truncated(result.get("raw"), error):
            raise TruncatedOutput(str(error) if error else "Đầu ra bị cắt ở giới hạn token.")
        errors = [str(error)] if error else []
        if result.get("parsed") is not None and result.get("parsing_error") is None:
            try:
                return parse(result["parsed"], self.schema)
            except InvalidOutput as invalid:
                errors.append(str(invalid))
        for candidate in _raw_answers(result.get("raw")):
            try:
                value, repaired = _parse(candidate, self.schema)
            except InvalidOutput as invalid:
                errors.append(str(invalid))
                continue
            report.repaired = repaired
            logger.info("%s: raw answer validated locally (json_repair=%s)", self.schema.__name__, repaired)
            return value
        raise InvalidOutput("\n\n".join(dict.fromkeys(errors)) or "Câu trả lời không chứa đối tượng JSON.")

    def _next_request(self, request: Request, error: Exception, report: Report) -> Request:
        """The request with the error appended, or raise when *error* is not worth another attempt."""
        report.errors.append(f"{type(error).__name__}: {error}")
        if not is_output_error(error) or report.attempts >= self.attempts:
            raise StructuredOutputError(f"{self.schema.__name__}: {report.errors[-1]}", cause=error,
                                        report=report) from error
        logger.warning("%s attempt %d invalid (%s); asking again", self.schema.__name__, report.attempts,
                       type(error).__name__)
        if isinstance(error, TruncatedOutput) or type(error).__name__ == "LengthFinishReasonError":
            note = f"{self.length_hint}\nLỗi nguyên văn: {error}"
        else:
            note = (f"Câu trả lời trước không khớp JSON schema. Lỗi validation nguyên văn:\n{error}\n"
                    f"Hãy trả lời lại một đối tượng JSON khớp chính xác schema {self.schema.__name__}.")
        if isinstance(request, str):
            return f"{request}\n\nRETRY: {note}"
        return [*request, HumanMessage(content=f"RETRY: {note}")]


def _raw_answers(raw: Any) -> list[Any]:
    """Every place an answer may sit in a raw message: tool-call arguments, then the text."""
    if raw is None:
        return []
    extra = _get(raw, "additional_kwargs", {}) or {}
    calls = [*(_get(raw, "tool_calls", []) or []), *(_get(raw, "invalid_tool_calls", []) or []),
             *(extra.get("tool_calls") or [])]
    if extra.get("function_call"):
        calls.append({"function": extra["function_call"]})
    found = [_get(call, "args", _get(_get(call, "function", {}), "arguments")) for call in calls]
    content = _get(raw, "content")
    if isinstance(content, list):  # Provider text parts, excluding private reasoning.
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and not part.get("thought"):
                if part.get("type") in ("tool_use", "tool_call"):
                    found.append(part.get("input", part.get("args")))
                elif part.get("type") in (None, "text", "output_text") and isinstance(part.get("text"), str):
                    parts.append(part["text"])
        content = "".join(parts)
    if isinstance(content, str) and content.strip():
        found.append(content)
    return [value for value in found if value is not None and value != ""]


def _get(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _truncated(raw: Any, error: Any) -> bool:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, TruncatedOutput) or type(error).__name__ == "LengthFinishReasonError":
            return True
        error = getattr(error, "__cause__", None) or getattr(error, "__context__", None)
    for meta in (raw, _get(raw, "response_metadata"), _get(raw, "additional_kwargs")):
        for key in ("finish_reason", "finishReason", "stop_reason"):
            reason = _get(meta, key)
            if isinstance(reason, str) and reason.lower() in ("length", "max_tokens", "max_output_tokens"):
                return True
    return False
