"""One line of the organisers' trace per agent turn. ``docs/design.md`` section 9.3.

The grader reads the trace and nothing else (section 0.4), so a line holds
exactly what ``schemas/trace_log.schema.json`` names; what helps a person
read a run but is not graded (the lane, the guard's verdicts, an error) goes
to the run's diagnostics file instead. Every line is checked against the
schema before it is written.

How each field is filled, matching ``eval/reference_eval.py`` and the
harness's collector (``scripts/evaluation/eval_harness/collector.py``):

- ``tool_calls``: the calls that ran, with the arguments they ran with (the
  day and the phone the harness filled in, the defaults it completed), and
  their result envelope. A call the guardrail before act refused never ran,
  so it is not here. The idempotency key is transport, not business: dropped.
- ``facts_used``: section 5.5's chain, the ``[Bn]`` the reply cited, the
  ``fact_ids`` of those brief lines, the slots of those facts. Only facts in
  force are resolved; a line with no ledger fact behind it names no slot.
- ``memory_writes``: on the last line of each call, what ``after_call``
  wrote, as ``{key, value, op, source, customer_id}``. Never ``fact_id``: a
  twelve-character hex id can be all digits, and any run of 10 to 14 digits in
  ``memory_writes`` counts as leaked personal data (section 0.5, trap 4).
- ``call_brief_latency_ms``: on turn 1 of ``call_2`` and ``call_3``.
- ``customer_input_mode``: the scenario's ``input_mode`` when the call gives
  ``customer_turns_asr``, else ``clean``.
- ``latency``: integer milliseconds around the turn; ``ttft_ms`` is the first
  token of the answer once replies stream, and equals ``total_ms`` until then
  (``eval/huong-dan-do-latency.md``, rule 7).

``questions`` and ``claims`` are left empty here and filled by the extractor
after every turn of a configuration has run (:mod:`.runner`).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

from ...components.intake import pii
from ...config.config_manager import btc_data_dir

#: Arguments that steer how a call is made rather than what it does.
TRANSPORT_ARGS = frozenset({"idempotency_key"})

#: Fields of a write the grader reads; anything else in our ledger's answer stays out.
MEMORY_WRITE_FIELDS = ("key", "value", "op", "source", "customer_id")


def tool_calls(results: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The calls that ran, as the trace names them."""
    return [
        {"name": r["name"], "args": {k: v for k, v in (r.get("args") or {}).items() if k not in TRANSPORT_ARGS},
         "result": r.get("result")}
        for r in results if not r.get("blocked_by")
    ]


def facts_used(state: Mapping[str, Any]) -> list[str]:
    """Slots of the facts behind the brief lines the reply cited (section 5.5)."""
    brief = state.get("brief") or {}
    slot_of = {fact["fact_id"]: slot for slot, fact in (brief.get("profile_facts") or {}).items()
               if isinstance(fact, Mapping) and fact.get("fact_id")}
    lines = {line["id"]: line for line in state.get("brief_lines") or []}
    cited = (state.get("reply") or {}).get("used_lines") or []
    return sorted({slot_of[fact_id] for line_id in cited
                   for fact_id in (lines.get(line_id) or {}).get("fact_ids") or [] if fact_id in slot_of})


def memory_writes(writes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """What ``after_call`` wrote, in the trace's shape."""
    return [{field: write.get(field) for field in MEMORY_WRITE_FIELDS} for write in writes]


def turn_row(
    *,
    run_id: str,
    config: str,
    scenario_id: str,
    call: str,
    turn: int,
    customer_text: str,
    state: Mapping[str, Any],
    vault: pii.Vault,
    total_ms: int,
    first_token_ms: int | None,
    input_mode: str,
    call_brief_latency_ms: int | None = None,
) -> dict[str, Any]:
    """One trace line for one agent turn. ``questions``, ``claims`` and ``memory_writes`` start empty."""
    reply = (state.get("reply") or {}).get("text") or ""
    row: dict[str, Any] = {
        "run_id": run_id,
        "config": config,
        "scenario_id": scenario_id,
        "call": call,
        "turn": turn,
        "customer_text": customer_text,
        # What the customer heard: their own phone number restored, an ID or
        # account number never more than its last four digits.
        "agent_text": pii.detokenize(reply, vault),
        "questions": [],
        "claims": [],
        "facts_used": facts_used(state),
        "tool_calls": tool_calls(state.get("tool_results") or []),
        "latency": {"ttft_ms": first_token_ms if first_token_ms is not None else total_ms,
                    "total_ms": total_ms, "ttfa_ms": None},
        "memory_writes": [],
        "customer_input_mode": input_mode,
    }
    if turn == 1 and call != "call_1":
        row["call_brief_latency_ms"] = call_brief_latency_ms
    return row


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads((btc_data_dir() / "schemas" / "trace_log.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def schema_errors(row: Mapping[str, Any]) -> list[str]:
    """Where *row* breaks ``trace_log.schema.json``, one message per problem."""
    return [f"{'/'.join(str(p) for p in error.absolute_path) or '(row)'}: {error.message}"
            for error in _validator().iter_errors(row)]


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """One JSON object per line, UTF-8, written whole and then swapped in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows),
                       encoding="utf-8")
    partial.replace(path)
