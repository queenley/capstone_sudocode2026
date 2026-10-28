"""Criteria on memory: ``memory_integrity`` for every call, and the ``memory`` assertion of ``memory_expectation``.

BTC's ``memory_checks`` only looks for the expected values in the trace's ``memory_writes`` and leaves the rest to a
human. Here the snapshots the agent's memory server returned before and after the call are checked:

- **integrity**: one snapshot per phase; the right namespace and customer; one active value per key; no fact written
  to another profile; every fact's source resolves; no value active outside its validity on the call's date; each
  write visible in the active state;
- **expectation**: each value of ``memory_expectation`` active after the call; a ``superseded`` value no longer active
  and kept as history; nothing written to a ``must_not_write_to`` profile.
"""
from datetime import datetime

from src.steps.prepare.preflight import call_plan


def integrity(ev):
    findings = []
    before = [m for m in ev.memories if m["phase"] == "before_call"]
    if len(before) != 1 or len(ev.after_call_memory) != 1:
        findings.append(ev.issue("MEMORY_PHASE_COVERAGE", ev.call_id))
    on = next(p["on"] for p in call_plan(ev.scenario, ev.manifest["reference_date"]) if p["call"] == ev.call)
    at = datetime.fromisoformat(on + "T00:00:00+07:00")
    namespace = f"{ev.manifest['state_namespaces'][ev.config]}/{ev.manifest['run_id']}/{ev.scenario_id}"
    for snapshot in ev.memories:
        if snapshot["namespace"] != namespace or before and snapshot["customer_id"] != before[0]["customer_id"]:
            findings.append(ev.issue("MEMORY_SCOPE_PROFILE", ev.call_id, "agent_violation"))
        active = [f for f in snapshot["facts"] if f["state"] == "active"]
        if len({f["key"] for f in active}) != len(active):
            findings.append(ev.issue("MEMORY_MULTIPLE_ACTIVE", ev.call_id, "agent_violation"))
        for item in snapshot["facts"] + snapshot["writes"]:
            if item["customer_id"] != snapshot["customer_id"]:
                findings.append(ev.issue("MEMORY_WRONG_PROFILE", ev.call_id, "agent_violation"))
            try:
                ev.src.resolve(item["source"])
            except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
                findings.append(ev.issue("MEMORY_SOURCE_MISSING", str(exc)))
        for fact in active:
            start = datetime.fromisoformat(fact["valid_from"])
            end = datetime.fromisoformat(fact["valid_until"]) if fact["valid_until"] else None
            if start > at or end is not None and end <= at:
                findings.append(ev.issue("MEMORY_INACTIVE_VALUE_EXPOSED", ev.call_id, "agent_violation"))
        for write_item in snapshot["writes"]:
            same = [f for f in active if f["key"] == write_item["key"]]
            if write_item["op"] == "delete" and same or write_item["op"] in ("set", "supersede") and not any(f["value"] == write_item["value"] for f in same):
                findings.append(ev.issue("MEMORY_WRITE_STATE", ev.call_id, "agent_violation"))
    return findings


def expectation(ev, expected):
    """The ``memory`` assertion: *expected* is the call's ``memory_expectation``."""
    findings = []
    after = ev.after_call_memory
    latest = {f["key"]: f["value"] for m in after for f in m["facts"] if f["state"] == "active"}
    for key, value in expected.items():
        if key == "superseded" and isinstance(value, dict):
            for slot, old_value in value.items():
                if latest.get(slot) == old_value:
                    findings.append(ev.issue("MEMORY_SUPERSEDED_ACTIVE", ev.call_id + "/" + slot, "agent_violation"))
                elif not any(f["key"] == slot and f["value"] == old_value and f["state"] == "superseded" for m in after for f in m["facts"]):
                    findings.append(ev.issue("MEMORY_SUPERSEDE_HISTORY_MISSING", ev.call_id + "/" + slot))
        elif key == "must_not_write_to" and isinstance(value, (str, list)):
            forbidden = [value] if isinstance(value, str) else value
            for m in ev.memories:
                if any(w["customer_id"] in forbidden for w in m["writes"]):
                    findings.append(ev.issue("MEMORY_FORBIDDEN_PROFILE_WRITE", ev.call_id, "agent_violation"))
        elif key in ("superseded", "must_not_write_to", "address_ttl_check", "profile_state"):
            findings.append(ev.issue("MEMORY_EXPECTATION_SEMANTICS_PENDING", ev.call_id + "/" + key))
        elif key not in latest or latest[key] != value:
            findings.append(ev.issue("MEMORY_EXPECTATION_WRONG", ev.call_id + "/" + key, "agent_violation" if after else "missing_evidence"))
    return findings
