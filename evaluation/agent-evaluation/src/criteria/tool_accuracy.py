"""Criteria on tool calls: ``tool_accuracy`` (TCA) against the labelled calls, and the ``tool_success`` assertion.

- :func:`match_tool_calls`: the calls of ``tool-labels.json`` (required, or allowed) matched in time order to the
  agent's real calls; TP/FP/FN, precision, recall. Read-only lookups outside the labels may be allowed.
- :func:`tool_success`: a required tool was called and the mock answered with the expected status.

BTC's TSR (``check_call``: right tool, ``args_match``, forbidden tools, phrases) is in the official report.
"""
from datetime import datetime

from src.common.contracts import checker, validate

READ_ONLY_TOOLS = frozenset({
    "crm.get_customer", "catalog.search", "inventory.check",
    "pricing.get_quote", "order.status",
})


def match_tool_calls(expectations, events, *, call_scope=False):
    """Match one labelled context; inputs must be complete, not partial logs.

    Chronological events consume the earliest unmatched compatible label.
    Required matches are TP; optional/read-only allowances are reported separately.
    Args are exact expected-key subsets (including nested values), never null wildcards.
    This does not infer tool success from results or evaluate unresolved conditions.
    """
    validate("ExpectedToolCalls", expectations)
    if expectations["context"]["run_id"] != expectations["run_id"]:
        raise ValueError("Labels have inconsistent run_id/context")
    for label in expectations["calls"]:
        if any(value is None for value in checker.walk(label["args_match"])):
            raise ValueError("Unresolved null expected args; labels must be settled before scoring")
    seen = set()
    for event in events:
        validate("ToolEvent", event)
        same_context = all(event["context"][key] == expectations["context"][key]
                           for key in ("run_id", "config", "scenario_id", "call")) if call_scope else event["context"] == expectations["context"]
        if not same_context or event["run_id"] != expectations["run_id"]:
            raise ValueError("Tool event does not belong to the labelled context")
        if event["event_id"] in seen:
            raise ValueError("Duplicate tool event_id")
        seen.add(event["event_id"])
        if datetime.fromisoformat(event["finished_at"]) < datetime.fromisoformat(event["started_at"]):
            raise ValueError("Tool event finished before it started")
    remaining = list(enumerate(expectations["calls"]))
    matches, allowed, false_positives = [], [], []
    execution_failures, execution_incomplete = [], []
    for event in sorted(events, key=lambda item: datetime.fromisoformat(item["started_at"])):
        request = event["request"]
        match = next(((index, label) for index, label in remaining
                      if label["name"] == request["name"]
                      and all(key in request["args"] and request["args"][key] == value
                              for key, value in label["args_match"].items())), None)
        if match is not None:
            remaining.remove(match)
            record = {"expected_index": match[0], "event_id": event["event_id"]}
            (matches if match[1]["required"] else allowed).append(record)
        elif expectations["allow_extra_read_only"] and request["name"] in READ_ONLY_TOOLS:
            allowed.append({"expected_index": None, "event_id": event["event_id"]})
        else:
            false_positives.append(event["event_id"])
        # Outcomes are collector evidence, not inferred from HTTP status or args.
        if event["outcome"] == "business_error":
            execution_failures.append(event["event_id"])
        elif event["outcome"] != "success":
            execution_incomplete.append(event["event_id"])
    false_negatives = [index for index, label in remaining if label["required"]]
    tp, fp, fn = len(matches), len(false_positives), len(false_negatives)
    denominator = tp + fp + fn
    return {
        "formula_id": "tool-accuracy.v2", "tp": tp, "fp": fp, "fn": fn,
        "value": 100 * tp / denominator if denominator else None,
        "status": "MEASURED" if denominator else "UNDEFINED",
        "precision": 100 * tp / (tp + fp) if tp + fp else None,
        "recall": 100 * tp / (tp + fn) if tp + fn else None,
        "matches": matches, "allowed": allowed,
        "false_positives": false_positives, "false_negatives": false_negatives,
        "execution_failures": execution_failures,
        "execution_incomplete": execution_incomplete,
    }


def tool_success(ev, params):
    """The ``tool_success`` assertion: ``params["tool_name"]`` was called and returned ``params["expected_status"]``."""
    findings = []
    matching = [e for e in ev.tools if e["request"]["name"] == params["tool_name"]]
    if not matching:
        findings.append(ev.issue("REQUIRED_TOOL_MISSING", ev.call_id, "agent_violation" if ev.complete and ev.tool_complete else "missing_evidence"))
    for event in matching:
        actual = event["outcome"] if params["expected_status"] == "success" else (event["result"].get("status") if isinstance(event["result"], dict) else None)
        if event["outcome"] == "business_error" or actual != params["expected_status"]:
            findings.append(ev.issue("REQUIRED_TOOL_FAILED", event["event_id"], "agent_violation" if event["outcome"] in ("success", "business_error") else "infra_error"))
    return findings
