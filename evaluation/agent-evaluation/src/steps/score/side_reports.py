"""Diagnostic interpretation beside, never in place of, the BTC score."""

import re

#: How a customer-facing sentence says each order status the BTC mock holds.
STATUS_PHRASES = {
    "created": re.compile(r"\bđã (?:được )?(?:tạo|ghi nhận)\b|\bmới (?:được )?tạo\b"),
    "processing": re.compile(r"\bđang (?:được )?(?:trong trạng thái )?(?:xử lý|chuẩn bị)\b"),
    "shipping": re.compile(r"\bđang (?:ở )?(?:trong )?(?:trạng thái )?giao(?: hàng)?\b"),
    "delivered": re.compile(r"\b(?:đã giao|giao thành công|đã nhận)\b"),
    "cancelled": re.compile(r"\b(?:đã hủy|bị hủy|đã huỷ)\b"),
}
#: Claims whose value a tool can legitimately return for a different subject than the label's.
TOOL_BACKED_FIELDS = ("price_vnd", "order_id", "sku", "list_price_vnd", "total_vnd")


def values_of(result):
    """Every scalar inside a tool result."""
    if isinstance(result, dict):
        return [v for item in result.values() for v in values_of(item)]
    if isinstance(result, list):
        return [v for item in result for v in values_of(item)]
    return [result]


def interpret_claim(field, claimed, expected, call_rows):
    if field == "product_name" and isinstance(claimed, str) and isinstance(expected, str):
        products = {item["sku"]: item["name"] for row in call_rows for tool in row["tool_calls"]
                    if tool["name"] == "catalog.search" for item in tool.get("result", {}).get("items", [])
                    if isinstance(item, dict) and isinstance(item.get("sku"), str) and isinstance(item.get("name"), str)}
        short = " ".join(claimed.casefold().split())
        matches = [(sku, name) for sku, name in products.items()
                   if len(short.split()) >= 2 and (name.casefold() == short or name.casefold().endswith(" " + short))]
        if len(matches) == 1 and matches[0][1] == expected:
            return "EQUIVALENT", "unique_catalog_name_suffix", [{"sku": matches[0][0], "name": matches[0][1]}]
    if field == "order_status" and isinstance(claimed, str) and expected in STATUS_PHRASES:
        phrase = claimed.casefold()
        said = {status for status, pattern in STATUS_PHRASES.items() if pattern.search(phrase)}
        confirmed = [order.get("status") for row in call_rows for tool in row["tool_calls"]
                     if tool["name"] == "order.status" for order in tool.get("result", {}).get("orders", [])]
        # The words say exactly the status the order has, and an order.status result of the call confirms it.
        if said == {expected} and expected in confirmed:
            return "EQUIVALENT", f"{expected}_phrase_and_order_tool", [{"tool": "order.status", "status": expected}]
    if field in TOOL_BACKED_FIELDS and claimed not in (None, "") and any(
            claimed in values_of(tool.get("result")) for row in call_rows for tool in row["tool_calls"]):
        # Not invented: a tool of this call returned this very value, about something other than the label expects.
        return "TOOL_BACKED", "value_returned_by_a_tool_of_this_call", []
    return "NEEDS_REVIEW", "no_verified_equivalence", []


def review_claims(traces, scenarios):
    rows = []
    for config, trace in traces.items():
        for row in trace:
            sid, call = row["scenario_id"], row["call"]
            gt = scenarios[sid]["calls"][call].get("ground_truth_facts", {})
            cohort = [item for item in trace if item["scenario_id"] == sid and item["call"] == call]
            for claim in row["claims"]:
                field = claim["field"]
                if field not in gt or claim["value"] == gt[field]:
                    continue
                decision, rule, evidence = interpret_claim(field, claim["value"], gt[field], cohort)
                rows.append({"config": config, "trace_source": "evidence/" + ("full" if config == "full" else "baseline") + ".jsonl",
                             "scenario_id": sid, "call": call, "turn": row["turn"],
                             "field": field, "claimed": claim["value"], "ground_truth": gt[field],
                             "decision": decision, "rule": rule, "evidence": evidence})
    return {"report_kind": "claim-adjudication-v1", "official_score_changed": False,
            "counts": {key: sum(row["decision"] == key for row in rows) for key in ("EQUIVALENT", "TOOL_BACKED", "NEEDS_REVIEW")},
            "rows": rows}


def review_tool_errors(tools):
    rows = []
    for config, events in tools.items():
        for index, event in enumerate(events):
            if event["outcome"] != "business_error":
                continue
            context = event["context"]
            recovered = next((later["event_id"] for later in events[index + 1:]
                              if later["outcome"] == "success" and later["request"]["name"] == event["request"]["name"]
                              and all(later["context"][key] == context[key] for key in ("scenario_id", "call"))), None)
            rows.append({"config": config, "scenario_id": context["scenario_id"], "call": context["call"],
                         "event_id": event["event_id"], "tool": event["request"]["name"],
                         "sku_arg": event["request"].get("args", {}).get("sku"),
                         "error": event["result"].get("error") if isinstance(event["result"], dict) else None,
                         "recovered_by": recovered})
    return {"report_kind": "tool-business-error-review-v1", "official_score_changed": False,
            "rows": rows}
