"""A model's JSON answer as a Pydantic schema, repaired when the JSON itself is broken.

Both model clients (``src/providers/gemini_client.py``, ``src/providers/openai_client.py``)
read answers through :func:`parse_output`: the strict parse first, then, if
the text is not valid JSON (a trailing comma, an unescaped quote, a cut-off
answer), ``json_repair`` and the schema again. A key the schema does not have
(``tags`` written inside a call instead of beside the calls) is dropped, since
nothing reads it. A value the schema rejects still raises ``ValidationError``,
and the client asks again with that error.
"""
from __future__ import annotations

import json
from typing import Any, TypeVar

import json_repair
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def parse_output(text: str, schema: type[T]) -> tuple[T, bool]:
    """``(value, repaired)``: *text* validated as *schema*; ``repaired`` when only the repaired JSON validated."""
    try:
        return schema.model_validate_json(text), False
    except ValidationError as error:
        if any(e["type"] == "json_invalid" for e in error.errors()):
            data = json_repair.loads(text)
        elif all(e["type"] == "extra_forbidden" for e in error.errors()):
            data = json.loads(text)
        else:
            raise  # valid JSON, wrong values: repairing the syntax cannot help
    try:
        return schema.model_validate(data), True
    except ValidationError as error:
        if not all(e["type"] == "extra_forbidden" for e in error.errors()):
            raise
        for e in error.errors():
            _drop(data, e["loc"])
        return schema.model_validate(data), True


def _drop(data: Any, loc: tuple[Any, ...]) -> None:
    """Remove the key at *loc* (a ValidationError location) from *data*."""
    *parents, key = loc
    for part in parents:
        data = data[part]
    if isinstance(data, dict):
        data.pop(key, None)
