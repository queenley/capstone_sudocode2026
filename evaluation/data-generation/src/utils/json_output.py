"""A model's JSON answer as a Pydantic schema, repaired when the JSON itself is broken.

Both model clients (``src/gemini_client.py``, ``src/providers/openai_client.py``)
read answers through :func:`parse_output`: the strict parse first, then, if
the text is not valid JSON (a trailing comma, an unescaped quote, a cut-off
answer), ``json_repair`` and the schema again. A value the schema rejects
still raises ``ValidationError``, and the client asks again with that error.
"""
from __future__ import annotations

from typing import TypeVar

import json_repair
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def parse_output(text: str, schema: type[T]) -> tuple[T, bool]:
    """``(value, repaired)``: *text* validated as *schema*; ``repaired`` when only the repaired JSON validated."""
    try:
        return schema.model_validate_json(text), False
    except ValidationError as error:
        if not any(e["type"] == "json_invalid" for e in error.errors()):
            raise  # valid JSON, wrong values: repairing the syntax cannot help
    return schema.model_validate(json_repair.loads(text)), True
