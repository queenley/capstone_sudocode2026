"""Criteria on what the agent asserted (HR's evidence): ``claim_gt_coverage`` and the ``claim_grounding`` assertion.

BTC's HR skips a claim whose field is not in ``ground_truth_facts``. Here such a claim is an issue (unknown, never
silently correct), and a claim whose value differs from the ground truth is an agent violation.
"""


def gt_coverage(ev):
    findings = []
    for row in ev.trace:
        for claim in row["claims"]:
            gt = ev.ground_truth
            if ev.disputed or claim["field"] not in gt:
                findings.append(ev.issue("CLAIM_GT_MISSING", ev.call_id + "/" + claim["field"], "dispute" if ev.disputed else "missing_evidence"))
            elif claim["value"] != gt[claim["field"]]:
                findings.append(ev.issue("CLAIM_VALUE_WRONG", ev.call_id + "/" + claim["field"], "agent_violation"))
    return findings


def grounding(ev, params, gt):
    """The ``claim_grounding`` assertion: each claim on ``params["fields"]`` equals *gt*."""
    findings = []
    for row in ev.trace:
        for item in row["claims"]:
            if item["field"] not in params["fields"]:
                continue
            if item["field"] not in gt:
                findings.append(ev.issue("CLAIM_ASSERTION_GT_MISSING", ev.call_id))
            elif item["value"] != gt[item["field"]]:
                findings.append(ev.issue("CLAIM_ASSERTION_WRONG", ev.call_id, "agent_violation"))
    return findings
