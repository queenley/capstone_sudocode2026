"""Chapter A metrics via the OFFICIAL BTC script (``data/eval/reference_eval.py``).

This module does not re-implement any metric: it builds the inputs that
``reference_eval.evaluate`` expects (scenario dicts in ``public_sample`` shape and
trace rows in ``trace_log`` shape) and reads its numbers back. What the official
script measures (summary; see the script for the exact code):

=====================  ======================================================================
RQR  Repeat-Question    redundant / all questions, on calls with must_not_ask. Redundant = open
                        question on a must_not_ask slot, or a 2nd+ confirm of the same slot.
CCR  Context carryover  |must_carry_over ∩ (facts_used ∪ tool-arg keys)| / |must_carry_over|
TSR  Task success       scenarios whose every call with success_if passes / scenarios (+ hard cases)
HR   Hallucination      claims ≠ ground_truth_facts[field] / claims whose field is in ground truth
                        (+ price & promo only: fields starting price/promo/list_price)
Guardrails              PII in text/memory, over-escalation, claims is_human, trace_must_not_match
=====================  ======================================================================
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from src.schemas.scenario import SuccessIf
from src.utils.btc_tools import reference_eval

ABSTAIN_PHRASES: tuple[str, ...] = tuple(reference_eval().ABSTAIN_KW)
TraceRow = dict[str, Any]


def group_rows(rows: Iterable[TraceRow]) -> dict[tuple[str, str], list[TraceRow]]:
    """Same grouping as ``reference_eval.load_trace``."""
    grouped: dict[tuple[str, str], list[TraceRow]] = defaultdict(list)
    for row in rows:
        grouped[(row["scenario_id"], row["call"])].append(row)
    for key in grouped:
        grouped[key].sort(key=lambda r: r["turn"])
    return grouped


def evaluate(scenarios: dict[str, dict], rows: Iterable[TraceRow]) -> dict[str, Any]:
    """Full official report for a set of exported scenarios and one trace."""
    return reference_eval().evaluate(scenarios, group_rows(rows))


def check_call(spec: dict[str, Any], rows: list[TraceRow]) -> tuple[bool | None, list[str]]:
    """Official ``success_if`` check of one call (``None`` when the call has no success_if)."""
    return reference_eval().check_call(spec, rows)


@dataclass
class CallScore:
    tsr: bool | None
    rqr: tuple[int, int]          # redundant, total questions
    ccr: tuple[int, int]          # used, required
    hr: tuple[int, int]           # wrong, checkable claims
    guardrails: dict[str, int]
    failures: list[str] = field(default_factory=list)


def score_call(scenario_id: str, call_name: str, spec: dict[str, Any], rows: list[TraceRow],
               hard_case: str | None = None) -> CallScore:
    """Run the official evaluation on a single call and turn it into readable failures."""
    report = reference_eval().evaluate({scenario_id: {"calls": {call_name: spec}, "hard_case": hard_case}},
                                       {(scenario_id, call_name): sorted(rows, key=lambda r: r["turn"])})
    rqr, ccr, hr = report["repeat_question_rate"], report["context_carryover_rate"], report["hallucination_rate"]
    guard = report["guardrail_violations"]["by_type"]
    tsr_ok, reasons = check_call(spec, rows)
    failures = [f"tsr:{r}" for r in reasons]
    failures += [f"redundant_question:{e['slot']}:{e['type']}" for e in rqr["examples"]]
    seen = {slot for r in rows for slot in r.get("facts_used", [])}
    seen |= {key for r in rows for tc in r.get("tool_calls", []) for key in tc.get("args", {})}
    failures += [f"ccr_missing:{slot}" for slot in spec.get("must_carry_over", []) if slot not in seen]
    failures += [f"hallucination:{e['field']}={e['claimed']}!={e['truth']}" for e in hr["examples"]]
    failures += [f"guardrail:{kind}" for kind, count in guard.items() if count]
    return CallScore(tsr_ok, (rqr["redundant"], rqr["total_questions"]), (ccr["used"], ccr["required"]),
                     (hr["wrong"], hr["total_claims"]), dict(guard), failures)


def has_positive_requirement(success_if: SuccessIf) -> bool:
    """True when success needs the agent to *do* something (not only avoid things)."""
    return bool(success_if.tool_called or success_if.must_say_any or success_if.agent_must_say
                or success_if.also_ordered or success_if.total_match_vnd is not None)


# --------------------------------------------------------------------------- #
# Text helpers used by deterministic consistency checks                        #
# --------------------------------------------------------------------------- #
#: "5 triệu", "5,2 triệu", "5tr2", "4 triệu rưỡi", "4 triệu 290 ngàn", "4 triệu 290", "5 triệu 2 trăm": the part after
#: the millions belongs to the same amount ("tr" is not "trăm": no letter may follow it).
_MILLION = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:triệu|tr(?![^\W\d_]))"
                      r"(?:\s*(rưỡi)|\s*(\d{1,3})(?:\s*(trăm|nghìn|ngàn|k)(?![^\W\d_]))?)?", re.IGNORECASE)
_THOUSAND = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:nghìn|ngàn|k)(?![^\W\d_])", re.IGNORECASE)
_GROUPED = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+)(?![\d.,])")
#: A bare number after the millions, by its digits: "5 triệu 2" is 5.200.000, "5 triệu 25" 5.250.000, "4 triệu 290" 4.290.000.
_REST_SCALE = {1: 100_000, 2: 10_000, 3: 1_000}
_REST_UNIT = {"trăm": 100_000, "nghìn": 1_000, "ngàn": 1_000, "k": 1_000}


def money_mentions(text: str) -> set[int]:
    """VND amounts written as ``5.200.000đ``, ``5,2 triệu``, ``5tr2``, ``4 triệu rưỡi``, ``4 triệu 290 ngàn``, ``500k``."""
    amounts: set[int] = set()
    taken: list[tuple[int, int]] = []
    for match in _MILLION.finditer(text):
        value = float(match.group(1).replace(",", ".")) * 1_000_000
        if match.group(2):
            value += 500_000
        elif match.group(3):
            unit = (match.group(4) or "").lower()
            value += int(match.group(3)) * (_REST_UNIT[unit] if unit else _REST_SCALE[len(match.group(3))])
        amounts.add(round(value))
        taken.append(match.span())
    for match in _THOUSAND.finditer(text):
        if not any(start <= match.start() < end for start, end in taken):   # "290 ngàn" of "4 triệu 290 ngàn"
            amounts.add(round(float(match.group(1).replace(",", ".")) * 1_000))
    for match in _GROUPED.finditer(text):
        amounts.add(int(re.sub(r"\D", "", match.group(1))))
    return amounts
