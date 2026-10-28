"""Criterion ``tool_execution_state``: what a tool says it did must be in the mock's state.

Every business tool call is checked against the BTC mock's state before and after it (the audit the Run step
records). A created order must exist with the phone, SKU, payment, address, price and quantity asked for; a callback,
handoff or return must have added the record its result names; a writing tool that changed nothing is missing state.
Only orders proven this way count for Calls-to-Close (:mod:`.calls_to_close`).
"""
from src.criteria.tool_accuracy import READ_ONLY_TOOLS


def new_order_verified(event, before, after):
    """BTC mock state proof, not a general production-order verifier."""
    result, args = event["result"], event["request"]["args"]
    oid = result.get("order_id") if isinstance(result, dict) else None
    order = after["_ORDERS"].get(oid)
    return (isinstance(result, dict) and result.get("status") == "created" and oid not in before["_ORDERS"]
            and isinstance(order, dict) and order.get("order_id") == oid
            and all(order.get(k) == args[k] for k in ("customer_phone", "sku", "payment", "address", "price_vnd") if k in args)
            and order.get("qty") == args.get("qty", 1) and order.get("total_vnd") == result.get("total_vnd"))


def coverage(ev):
    """The logged tool events must be exactly the trace's tool calls."""
    return [] if ev.tool_complete else [ev.issue("TOOL_EVIDENCE_COVERAGE", ev.call_id)]


def check(ev, evref):
    """``(findings, verified_order_event_ids)`` over every tool event of the call."""
    findings, verified = [], []
    for event in ev.tools:
        if event["outcome"] == "business_error":
            findings.append(ev.issue("TOOL_BUSINESS_ERROR", event["event_id"], "agent_violation", evref))
            continue
        if event["outcome"] != "success":
            findings.append(ev.issue("TOOL_EXECUTION_UNKNOWN", event["event_id"], "infra_error", evref))
            continue
        result = event["result"]
        if isinstance(result, dict) and result.get("error"):
            findings.append(ev.issue("TOOL_OUTCOME_CONTRADICTION", event["event_id"], "schema_error", evref))
            continue
        try:
            if len(event["evidence_refs"]) != 1:
                raise ValueError("Unique audit required")
            audit = ev.src.resolve(event["evidence_refs"][0])["data"]
            raw_event = audit["event"]
            if any(raw_event[k] != event[k] for k in event if k != "evidence_refs"):
                raise ValueError("Audit/event mismatch")
            before, after = audit["state_before"], audit["state_after"]
            if (before != after) != event["side_effect"]:
                raise ValueError("State delta/side_effect mismatch")
            name = event["request"]["name"]
            if name == "order.create":
                if not new_order_verified(event, before, after):
                    findings.append(ev.issue("ORDER_STATE_UNVERIFIED", event["event_id"], "agent_violation", evref))
                else:
                    verified.append(event["event_id"])
            elif name in ("schedule.callback", "handoff.transfer", "order.cancel_or_return"):
                state_name = "_CALLBACKS" if name == "schedule.callback" else "_TICKETS"
                added = [v for v in after[state_name] if v not in before[state_name]]
                if not isinstance(result, dict) or not any(all(v.get(k) == val for k, val in result.items()) for v in added):
                    findings.append(ev.issue("TOOL_RESULT_STATE_MISMATCH", event["event_id"], "agent_violation", evref))
            elif name not in READ_ONLY_TOOLS and before == after:
                findings.append(ev.issue("TOOL_STATE_MISSING", event["event_id"], origin=evref))
        except (ValueError, KeyError, TypeError, OSError, IndexError, AttributeError) as exc:
            findings.append(ev.issue("TOOL_STATE_EVIDENCE", str(exc), origin=evref))
    return findings, verified
