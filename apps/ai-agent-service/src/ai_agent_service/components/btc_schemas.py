"""The organisers' JSON schemas (``data/btc/schemas``), as validators.

``call_brief``, ``handoff_brief`` and ``trace_log`` are the grading contract
(Phụ lục A). What the agent builds is checked against the files themselves,
not a hand-copied list of their fields, so a newer pack is picked up as is.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

from ..config.config_manager import btc_data_dir

Name = Literal["call_brief", "handoff_brief", "trace_log", "tools"]


@lru_cache(maxsize=None)
def validator(name: Name) -> Draft202012Validator:
    path = btc_data_dir() / "schemas" / f"{name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def errors(name: Name, document: Any) -> list[str]:
    """Every violation, as "field: message", in document order; empty when valid."""
    found = sorted(validator(name).iter_errors(document), key=lambda e: list(e.absolute_path))
    return [f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in found]
