"""Criterion ``fact_carryover`` (value-level CCR): each ``must_carry_over`` slot used, with the right value.

BTC's CCR counts a slot as carried over when its name appears in ``facts_used`` or a tool call's arguments. Here the
extracted fact usage must also hold the ground-truth value, and the memory it came from must be the customer's own
(no ``memory_integrity`` finding). The per-config metric ``fact_value`` is the share of slots that pass.
"""


def check(ev, memory_findings):
    """``(findings, passed, total, missing_evidence, cohort_ids)`` for the call's ``must_carry_over`` slots."""
    findings, passed, total, missing, cohort = [], 0, 0, False, []
    for slot in ev.spec.get("must_carry_over", []):
        total += 1
        cohort.append(ev.call_id + "/" + slot)
        used = [i for i in ev.fact_usage if i["slot_or_field"] == slot]
        gt = ev.ground_truth
        if ev.disputed or slot not in gt or not ev.complete or not ev.extraction_complete:
            missing = True
            findings.append(ev.issue("FACT_GT_OR_USAGE_MISSING", ev.call_id + "/" + slot, "dispute" if ev.disputed else "missing_evidence"))
        elif not used or any(i["value"] != gt[slot] for i in used):
            findings.append(ev.issue("FACT_VALUE_WRONG_OR_UNUSED", ev.call_id + "/" + slot, "agent_violation"))
        elif memory_findings:
            missing = True
            findings.append(ev.issue("FACT_PROFILE_UNVERIFIED", ev.call_id + "/" + slot))
        else:
            passed += 1
    return findings, passed, total, missing, cohort


def fact_value(ev, params, expected_value):
    """The ``fact_value`` assertion: every use of ``params["slot"]`` has *expected_value*."""
    required = [i for i in ev.fact_usage if i["slot_or_field"] == params["slot"]]
    if not required or any(i["value"] != expected_value for i in required):
        return [ev.issue("FACT_ASSERTION", ev.call_id, "agent_violation" if ev.complete and ev.extractions else "missing_evidence")]
    return []
