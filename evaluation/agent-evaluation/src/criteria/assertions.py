"""The assertions of a call's grading contract, each judged by its criterion module.

| ``kind`` | Criterion |
|---|---|
| ``tool_success`` | :func:`src.criteria.tool_accuracy.tool_success` |
| ``tool_accuracy`` | :func:`src.criteria.tool_accuracy.match_tool_calls` (only this configuration's labels) |
| ``fact_value`` | :func:`src.criteria.carryover.fact_value` |
| ``claim_grounding`` | :func:`src.criteria.claims.grounding` |
| ``guardrail`` | :func:`src.criteria.guardrail.check` |
| ``memory`` | :func:`src.criteria.memory.expectation` |
| ``schema`` | :func:`schema` here: the brief, tool arguments or trace pass the named contract |

An assertion whose evidence is missing, or whose ground truth is disputed, is reported as such and not judged.
"""
from referencing.exceptions import Unresolvable
import re

from src.criteria import carryover, claims, guardrail, memory
from src.criteria.tool_accuracy import match_tool_calls, tool_success


def schema(ev, params, checker, contracts_root):
    """The objects of ``params["artifact_role"]`` pass ``params["schema_ref"]`` (a local evaluator contract)."""
    findings = []
    roles = {"trace": ev.trace, "tool_args": [e["request"] for e in ev.tools],
             "call_brief": [ev.src.resolve(b["object_ref"]) for b in ev.briefs if b["kind"] == "call_brief"],
             "handoff_brief": [ev.src.resolve(b["object_ref"]) for b in ev.briefs if b["kind"] == "handoff_brief"]}
    objects = roles[params["artifact_role"]]
    schema_name = params["schema_ref"].split("#", 1)[0]
    if not schema_name or not (contracts_root / schema_name).resolve().is_relative_to(contracts_root) \
            or not (contracts_root / schema_name).is_file():
        raise ValueError("Schema must name a local evaluator contract")
    if not objects:
        findings.append(ev.issue("SCHEMA_OBJECT_MISSING", ev.call_id))
    for obj in objects:
        errors = checker.errors(params["schema_ref"], obj)
        if errors:
            findings.append(ev.issue("SCHEMA_ASSERTION", errors[0].message, "agent_violation"))
    return findings


def judge(ev, available_roles, checker, contracts_root):
    """``[(check_id, findings, tool_matching)]`` for every assertion of the call (``tool_matching`` for TCA only)."""
    results = []
    for assertion in ev.grader["checks"] if ev.grader else []:
        findings, matched = [], None
        params, kind = assertion["params"], assertion["kind"]
        try:
            for role in assertion["required_evidence"]:
                if not available_roles.get(role, False):
                    findings.append(ev.issue("ASSERTION_EVIDENCE_MISSING", ev.call_id + "/" + role))
            if not ev.complete:
                findings.append(ev.issue("ASSERTION_COVERAGE", ev.call_id))
            if ev.disputed:
                findings.append(ev.issue("ASSERTION_GT_DISPUTED", ev.call_id, "dispute"))
            elif kind == "tool_success":
                findings += tool_success(ev, params)
            elif kind == "fact_value":
                findings += carryover.fact_value(ev, params, ev.inputs.resolve(params["expected_source"]))
            elif kind == "claim_grounding":
                findings += claims.grounding(ev, params, ev.inputs.resolve(params["ground_truth"]))
            elif kind == "guardrail":
                findings += guardrail.check(ev, params["patterns"])
            elif kind == "memory":
                findings += memory.expectation(ev, ev.inputs.resolve(params["expectation"]))
            elif kind == "schema":
                findings += schema(ev, params, checker, contracts_root)
            elif kind == "tool_accuracy":
                if assertion["check_id"] != "tool_accuracy_" + ev.config:
                    continue   # the other configuration's labels
                labels = ev.inputs.resolve(params["expected_calls"])
                if any(labels["context"][k] != value for k, value in (("run_id", ev.manifest["run_id"]), ("config", ev.config),
                                                                       ("scenario_id", ev.scenario_id), ("call", ev.call))):
                    raise ValueError("Expected tool labels belong to another run/config/call; never relabel after execution")
                matched = match_tool_calls(labels, ev.tools, call_scope=True)
                if matched["fp"] or matched["fn"]:
                    findings.append(ev.issue("TOOL_ACCURACY", ev.call_id, "agent_violation" if ev.complete else "missing_evidence"))
                if matched["status"] == "UNDEFINED":
                    findings.append(ev.issue("TOOL_ACCURACY_UNDEFINED", ev.call_id))
            else:
                raise ValueError("Unsupported assertion kind")
        except (ValueError, KeyError, TypeError, OSError, IndexError, re.error, Unresolvable) as exc:
            findings.append(ev.issue("ASSERTION_CONFIG_OR_EVIDENCE", str(exc)))
        results.append((assertion, findings, matched))
    return results
