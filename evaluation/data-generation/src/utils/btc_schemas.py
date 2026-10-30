"""BTC's schemas (``data/schemas``): what every generated trace row, brief and tool call must look like.

* ``trace_log.schema.json``, ``call_brief.schema.json``, ``handoff_brief.schema.json``: JSON Schema
  (draft 2020-12), checked with ``jsonschema``.
* ``tools.schema.json``: a list of tools with their inputs, ``"string"`` for a required parameter,
  ``"string?"`` for an optional one, ``"a|b|c"`` for the values allowed. :func:`tool_call_errors`
  reads it that way.

``build_ground_truth`` checks every file of the dataset with :func:`dataset_errors`;
``validate_rules`` checks each reference transcript's trace rows.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from src.utils.paths import DATA_DIR

SCHEMA_DIR = DATA_DIR / "schemas"
JSON_SCHEMAS = ("trace_log", "call_brief", "handoff_brief")
#: Trace configurations reference_eval tells apart (trace_log.schema.json → config).
CONFIGS = ("full", "baseline_no_memory")
#: Our input modes as trace_log's ``customer_input_mode`` names them: every typed-chat mode is chat_teencode.
INPUT_MODES = {"text": "clean", "asr_transcript": "asr_transcript", "chat_teencode": "chat_teencode",
               "chat_khong_dau": "chat_teencode", "chat_sai_chinh_ta": "chat_teencode"}


@lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def errors(name: str, value: Any) -> list[str]:
    """``"<path>: <message>"`` for each way *value* breaks the schema *name* (trace_log, call_brief, handoff_brief)."""
    found = sorted(validator(name).iter_errors(value), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in found]


@lru_cache(maxsize=1)
def tools() -> dict[str, dict[str, str]]:
    """Tool name -> ``{parameter: type}`` from tools.schema.json (memory.* has no fixed schema and is left out)."""
    listed = json.loads((SCHEMA_DIR / "tools.schema.json").read_text(encoding="utf-8"))["tools"]
    return {t["name"]: t["input"] for t in listed if "input" in t}


def tool_call_errors(name: str, args: dict[str, Any]) -> list[str]:
    """How a tool call breaks tools.schema.json: an unknown tool, a missing required parameter, a value not allowed.

    A team tool registered in contracts/scenario/scenario-keys.yaml (``team_tools``) is checked by its arguments there.
    """
    from src.schemas import keys   # the registry imports this package's paths; import late

    team = keys.registry().get("team_tools") or {}
    if name in team:
        unknown = sorted(set(args) - set(team[name]))
        return [f"{name}: argument '{a}' not in team_tools" for a in unknown]
    if name not in tools():
        return [f"{name}: not a BTC tool"]
    found = []
    for parameter, kind in tools()[name].items():
        optional = kind.split(" ")[0].endswith("?")
        if parameter not in args:
            if not optional:
                found.append(f"{name}: missing required '{parameter}'")
            continue
        allowed = kind.split(" ")[0].rstrip("?")
        if "|" in allowed and str(args[parameter]) not in allowed.split("|"):
            found.append(f"{name}: {parameter}={args[parameter]!r} not in {allowed}")
    return found


def dataset_errors(dataset) -> dict[str, list[str]]:
    """Every schema error of a dataset (``src.utils.dataset.Dataset``), by file, relative to its root."""
    found: dict[str, list[str]] = {}

    def check(path, problems: list[str]) -> None:
        if problems:
            found[path.relative_to(dataset.root).as_posix()] = problems

    for name in ("call_brief", "handoff_brief"):
        for path in sorted((dataset.root / name).glob("scenarios_*/call_*.json")):
            check(path, errors(name, json.loads(path.read_text(encoding="utf-8"))))
    for path in sorted((dataset.root / "tools").glob("scenarios_*/call_*.json")):
        check(path, [e for call in json.loads(path.read_text(encoding="utf-8"))
                     for e in tool_call_errors(call["name"], call["args"])])
    for path in sorted((dataset.root / "trace_log").glob("scenarios_*/call_*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        check(path, [f"turn {row.get('turn')}: {e}" for row in rows for e in errors("trace_log", row)])
    return found
