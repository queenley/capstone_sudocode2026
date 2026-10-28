"""Evidence completeness: can the call be judged at all?

Before any criterion, the Score step checks that the call has what judging needs, and reports what is missing as
``missing_evidence`` (the verdict becomes UNDETERMINED, not FAIL):

- every planned turn has one trace row (``CALL_COVERAGE``) and one extraction (``EXTRACTION_COVERAGE``);
- the grading contract exists, is assertion-only, labels tool accuracy for this configuration and a PII guardrail;
- the evidence roles it requires (trace, memory, tools, extraction, briefs) are present;
- each trace row's questions, claims and ``facts_used`` are exactly what was extracted from that turn.
"""
from src.common.assets import read_json
from src.steps.collect.collector import context_key, merged_facts_used
from src.steps.collect.extraction import digest

CONTEXT_KEYS = ("run_id", "config", "scenario_id", "call", "turn")


def reported_document(src, row):
    """The transcript document of a trace row: it holds the slots the agent reported using (``agent_facts_used``)."""
    context = {k: row[k] for k in CONTEXT_KEYS}
    try:
        return read_json(src.path(f"{row['config']}/transcripts/{digest(context_key(context))}.json"))
    except (OSError, ValueError, KeyError):
        return {}


def call_bookkeeping(ev, required_evidence):
    """``(findings, available_roles)``: coverage, dispute and grading-contract issues of the call."""
    findings = []
    if not ev.complete:
        findings.append(ev.issue("CALL_COVERAGE", ev.call_id))
    if ev.disputed:
        findings.append(ev.issue("GT_DISPUTED", ev.call_id, "dispute"))
    available = {"trace": bool(ev.trace), "memory": bool(ev.memories), "tools": bool(ev.tools),
                 "tool_events": bool(ev.tools), "extraction": bool(ev.extractions),
                 "call_brief": any(b["kind"] == "call_brief" for b in ev.briefs),
                 "handoff_brief": any(b["kind"] == "handoff_brief" for b in ev.briefs)}
    if ev.grader is None:
        findings.append(ev.issue("GRADING_MISSING", ev.call_id))
    elif ev.grader["mode"] != "assertion_only":
        findings.append(ev.issue("JUDGE_PENDING", ev.call_id + "/" + ev.grader["mode"]))
    if ev.grader and not any(c["kind"] == "tool_accuracy" and c["check_id"] == "tool_accuracy_" + ev.config
                             for c in ev.grader["checks"]):
        findings.append(ev.issue("TOOL_EXPECTATIONS_NOT_LABELLED", ev.call_id))
    for role in required_evidence:
        if not available.get(role, False):
            findings.append(ev.issue("REQUIRED_EVIDENCE_MISSING", ev.call_id + "/" + role))
    return findings, available


def trace_matches_extraction(ev):
    """Each trace row says what was extracted from its turn, nothing added or dropped."""
    findings = []
    if not ev.extraction_complete:
        findings.append(ev.issue("EXTRACTION_COVERAGE", ev.call_id))
    for row in ev.trace:
        extracted = [e for e in ev.extractions if e["context"] == {k: row[k] for k in CONTEXT_KEYS}]
        if len(extracted) != 1:
            continue
        atomics = extracted[0]["items"]
        claims = [{"field": i["slot_or_field"], "value": i["value"], "text": i["quote"]}
                  for i in atomics if i["kind"] == "claim" and i["speaker"] == "agent"]
        questions = [{"slot": i["slot_or_field"], "type": i["question_type"], "text": i["quote"]}
                     for i in atomics if i["kind"] == "question" and i["speaker"] == "agent"]
        if (row["claims"] != claims or row["questions"] != questions
                or row.get("facts_used", []) != merged_facts_used(atomics, reported_document(ev.src, row))):
            findings.append(ev.issue("TRACE_EXTRACTION_MISMATCH", ev.call_id, "schema_error"))
    return findings


def guardrail_labelled(ev):
    if not ev.grader or not any(c["kind"] == "guardrail" for c in ev.grader["checks"]):
        return [ev.issue("PII_POLICY_NOT_LABELLED", ev.call_id)]
    return []
