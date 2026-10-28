"""Criterion on the briefs: the Call Brief and the Handoff Brief are valid, about this customer, and true.

- each brief must pass BTC's ``call_brief.schema.json`` / ``handoff_brief.schema.json`` and the collector's check;
- it must name this customer (the Call Brief may mask the phone to ``******1234``; the handoff keeps it whole);
- every fact it states that the ground truth knows must equal it;
- a call that expects a transfer (``handoff.transfer`` or outcome ``chuyen_may``) must leave a Handoff Brief.

A Handoff Brief's free text still needs a human: it is reported as ``HANDOFF_CONTENT_REVIEW_PENDING``.
"""


def brief_matches_profile(brief, kind, scenario, spec):
    """Call Brief may mask the phone; handoff must keep the BTC wire phone."""
    phone = scenario["customer_phone"]
    actual = brief.get("customer_phone")
    if kind == "call_brief":
        if actual not in (phone, "******" + phone[-4:]):
            return False
    elif actual != phone:
        return False
    expected_id = spec.get("ground_truth_facts", {}).get("customer_id")
    actual_id = brief.get("customer_id")
    if kind == "call_brief" and expected_id and actual_id != expected_id:
        return False
    return not (expected_id and actual_id and actual_id != expected_id)


def check(ev, checker):
    findings = []
    for brief in ev.briefs:
        brief_object = ev.src.resolve(brief["object_ref"])
        schema = "sources/btc/schemas/" + ("call_brief" if brief["kind"] == "call_brief" else "handoff_brief") + ".schema.json"
        if brief["validation"]["verdict"] == "FAIL" or checker.errors(schema, brief_object):
            findings.append(ev.issue("BRIEF_INVALID", ev.call_id, "agent_violation", ev.ref(brief["object_ref"])))
        if not isinstance(brief_object, dict):
            continue
        if not brief_matches_profile(brief_object, brief["kind"], ev.scenario, ev.spec):
            findings.append(ev.issue("BRIEF_WRONG_PROFILE", ev.call_id, "agent_violation", ev.ref(brief["object_ref"])))
        content = brief_object.get("profile_facts", {}) if brief["kind"] == "call_brief" else brief_object.get("facts_confirmed", {})
        for field, value in content.items():
            gt = ev.ground_truth
            if field in gt and not ev.disputed and value != gt[field]:
                findings.append(ev.issue("BRIEF_FACT_WRONG", ev.call_id + "/" + field, "agent_violation", ev.ref(brief["object_ref"])))
        if brief["kind"] == "handoff_brief":
            findings.append(ev.issue("HANDOFF_CONTENT_REVIEW_PENDING", ev.call_id, origin=ev.ref(brief["object_ref"])))
    if (ev.spec.get("success_if") or {}).get("tool_called") == "handoff.transfer" or ev.spec.get("expected_outcome") == "chuyen_may":
        if not any(b["kind"] == "handoff_brief" for b in ev.briefs):
            findings.append(ev.issue("HANDOFF_EVIDENCE_MISSING", ev.call_id))
    return findings
