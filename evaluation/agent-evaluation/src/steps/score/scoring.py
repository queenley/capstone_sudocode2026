"""Step 4 — Score: BTC's official grader on the trace, then each criterion of ``src/criteria`` on every call.

:func:`score` reads only the locked evidence of the Collect step (it never runs the agent, a tool or a model):

1. snapshot the evidence into ``scored/evidence/`` and check every row against its contract;
2. planned trace coverage: one row per (config, scenario, call, turn);
3. BTC's ``reference_eval.py`` on ``scorer-input/`` → ``official-report.json``, ``scorer.stdout.txt``
   (:mod:`src.steps.score.official`);
4. per call and configuration, the criteria: evidence coverage, ``tool_execution_state``, ``memory_integrity``,
   ``fact_carryover``, ``claim_gt_coverage``, briefs, and the grading contract's assertions;
5. beside BTC's table: latency without warm-up and verified Calls-to-Close (``run-summary``), and two side reports
   that never change a score (``claim-adjudication.json``, ``tool-business-error-review.json``).

Every finding is an issue with a classification: ``agent_violation`` (the agent did wrong: verdict FAIL),
``missing_evidence`` / ``dispute`` / ``infra_error`` / ``schema_error`` (cannot judge: UNDETERMINED).
"""
from collections import Counter
import hashlib
import json

from src.baseline.configs import TRACE_FILE
from src.common.assets import Assets, new_output, parse_json, read_json, write_new
from src.common.contracts import ROOT, checker, validate
from src.criteria import assertions, briefs, carryover, claims, coverage, memory, tool_state
from src.criteria.evidence import CallEvidence
from src.steps.collect.collector import context_key, locked_run, status
from src.steps.collect.extraction import digest
from src.steps.score import official as btc
from src.steps.score.side_reports import review_claims, review_tool_errors
from src.steps.score.supplement import build as build_supplement


def score(run_dir, out):
    """Never invoke Agent/tools/model, alter source runs, or repair official scores."""
    source, lock = locked_run(run_dir)
    checker.verify_sources()
    manifest = read_json(source.path("manifest.json"))
    validate("Manifest", manifest)
    plan = read_json(source.path("raw/execution-plan.json"))
    if "full" not in plan["configs"]:
        raise ValueError("BTC scoring requires the full config; baseline alone is not a system run")
    target = new_output(out, source)
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    evidence = target / "evidence"
    evidence.mkdir()
    for name in list(lock["files"]) + ["artifacts.lock.json"]:
        payload = source.path(name).read_bytes()
        if name in lock["files"] and hashlib.sha256(payload).hexdigest() != lock["files"][name]:
            raise ValueError("Source changed while snapshotting")
        path = evidence / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
    src, _ = locked_run(evidence)
    assets, inputs = Assets(target), Assets(evidence / "raw/inputs")
    write_new(target / "manifest.json", manifest)
    manifest_ref = assets.ref("manifest.json")
    issues, checks, metrics, details = [], [], [], []

    def ref(value):
        return {**value, "path": "evidence/" + value["path"]}

    def issue(code, message, classification="missing_evidence", origin=None):
        item = {"code": code, "message": message, "classification": classification,
                "artifact": origin or manifest_ref, "json_pointer": ""}
        validate("Issue", item)
        issues.append(item)
        return item

    def check(name, findings, refs):
        checks.append({"check_id": name, "status": status(findings), "evidence_refs": refs})

    def write(name, value):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_new(path, value)
        return assets.ref(name)

    def rows(name, definition):
        result = []
        try:
            path = src.path(name)
            origin = ref(src.ref(name))
        except ValueError:
            issue("EVIDENCE_FILE_MISSING", name)
            return result
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                obj = parse_json(line)
                if definition == "Trace":
                    errors = checker.errors("sources/btc/schemas/trace_log.schema.json", obj)
                    if errors:
                        raise ValueError(errors[0].message)
                else:
                    validate(definition, obj)
                    for ev in obj.get("evidence_refs", []):
                        src.resolve(ev, json_content=False)
                    if definition == "Extraction":
                        for item in obj["items"]:
                            text = src.resolve(item["source"])
                            if (not isinstance(text, str) or item["start"] < 0 or item["end"] > len(text)
                                    or item["end"] <= item["start"] or text[item["start"]:item["end"]] != item["quote"]):
                                raise ValueError("Extraction quote/span invalid")
                            pointer = item["source"]["pointer"]
                            role = item["speaker"]
                            if (role == "agent" and pointer != "/agent_text"
                                    or role == "tool" and not pointer.startswith("/tool_texts/")
                                    or role == "consultant" and not pointer.startswith("/consultant_texts/")):
                                raise ValueError("Extraction source/speaker mismatch")
                            document = read_json(src.path(item["source"]["path"]))
                            if document["context"] != obj["context"]:
                                raise ValueError("Extraction source context mismatch")
                context = obj if definition == "Trace" else obj["context"]
                file_config = next((c for c, f in TRACE_FILE.items() if f == name), name.split("/")[0])
                if context_key(context) not in expected or context["config"] != file_config or obj["run_id"] != manifest["run_id"]:
                    raise ValueError("Unknown run/config/scenario/call/turn")
                result.append(obj)
            except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
                issue("EVIDENCE_SCHEMA", f"{name}:{index}: {exc}", "schema_error", origin)
        return result

    # -- 1. The pinned inputs and the planned coverage ----------------------------------------------------------
    expected = [f"{manifest['run_id']}/{p['config']}/{p['scenario_id']}/{p['call']}/{turn}"
                for p in manifest["planned_calls"] if p["config"] in plan["configs"]
                for turn in range(1, p["expected_turns"] + 1)]
    if Counter(expected) != Counter(plan["expected_ids"]) or len(set(expected)) != len(expected):
        raise ValueError("Manifest/plan coverage mismatch or duplicate planned IDs")
    prior = read_json(src.path("validation.json"))
    validate("ValidationReport", prior)
    for item in prior["issues"]:
        src.resolve(item["artifact"], json_content=False)
        issues.append({**item, "artifact": ref(item["artifact"])})
    scenarios, graders = {}, {}
    for pinned in manifest["scenarios"]:
        obj = inputs.resolve(pinned)
        validate("Scenario", obj)
        if obj["scenario_id"] in scenarios:
            raise ValueError("Duplicate planned scenario")
        scenarios[obj["scenario_id"]] = obj
    for pinned in manifest["grading_contracts"]:
        obj = inputs.resolve(pinned)
        errors = checker.errors("grading-contract.schema.json", obj)
        if errors:
            raise ValueError(errors[0].message)
        if obj["scenario_id"] in graders or inputs.resolve(obj["scenario"]) != scenarios[obj["scenario_id"]]:
            raise ValueError("Grading contract scenario mismatch/duplicate")
        graders[obj["scenario_id"]] = obj

    configs = plan["configs"]
    traces, tools, memories, extractions, brief_rows = {}, {}, {}, {}, {}
    for config in configs:
        traces[config] = rows(TRACE_FILE[config], "Trace")
        tools[config] = rows(config + "/tools.jsonl", "ToolEvent")
        memories[config] = rows(config + "/memory.jsonl", "MemoryEvidence")
        extractions[config] = rows(config + "/extraction.jsonl", "Extraction")
        brief_rows[config] = rows(config + "/brief-evidence.jsonl", "BriefEvidence")
    observed = [context_key(r) for values in traces.values() for r in values]
    counts = Counter(observed)
    gaps = {"missing_ids": sorted(set(expected) - set(observed)),
            "duplicate_ids": sorted(k for k, n in counts.items() if n > 1),
            "unknown_ids": sorted(set(observed) - set(expected))}
    coverage_findings = []
    if Counter(observed) != Counter(expected):
        coverage_findings.append(issue("TRACE_COVERAGE", "Missing/duplicate/unknown planned turns"))
    check("planned_trace_coverage", coverage_findings, [manifest_ref])
    coverage_report = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/score-coverage",
                       "run_id": manifest["run_id"], "scope": "btc_trace", "expected_ids": expected,
                       "observed_ids": observed, **gaps, "status": status(coverage_findings)}
    validate("Coverage", coverage_report)
    coverage_ref = write("coverage.json", coverage_report)

    # -- 2. BTC's official scores (valid trace rows only, never placeholders) ----------------------------------
    for config, values in traces.items():
        path = target / "scorer-input" / TRACE_FILE[config]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            for value in values:
                stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    for sid, obj in scenarios.items():
        write("scorer-input/scenarios/" + digest(sid) + ".json", obj)
    code, invocation = btc.run(target, inputs.path("sources/btc/eval/reference_eval.py"), configs)
    invocation.update(scorer=ref(src.ref("raw/inputs/sources/btc/eval/reference_eval.py")),
                      stdout=assets.ref("scorer.stdout.txt"), stderr=assets.ref("scorer.stderr.txt"),
                      quality_accepted=False)
    official_ref = None
    try:
        if code != 0:
            raise ValueError(f"BTC CLI exit {code}")
        official_report = read_json(target / "official-report.json")
        validate("OfficialReport", official_report)
        official_ref = assets.ref("official-report.json")
    except (OSError, ValueError) as exc:
        issue("SCORER_INFRA", str(exc), "infra_error")

    # -- 3. The criteria, per call and configuration -------------------------------------------------------------
    def selected(values, config, sid, call):
        return [v for v in values[config] if (v.get("context", v)["scenario_id"], v.get("context", v)["call"]) == (sid, call)]

    def input_ref(pinned):
        inputs.resolve(pinned)
        return {**pinned, "path": "evidence/raw/inputs/" + pinned["path"]}

    def metric(mid, formula, cohort, n, d, refs, missing=False, unit="percent"):
        value = None if missing or not d else n / d * (100 if unit == "percent" else 1)
        obj = {"metric_id": mid, "formula_id": formula, "unit": unit, "value": value,
               "numerator": n, "denominator": d, "cohort_ids": cohort, "evidence_refs": refs,
               "status": "INCOMPLETE" if missing else "UNDEFINED" if not d else "MEASURED",
               "reason": "MISSING_OR_DISPUTED_EVIDENCE" if missing else "ZERO_DENOMINATOR" if not d else None,
               "currency": None}
        validate("Metric", obj)
        metrics.append(obj)

    for config in configs:
        fact_n, fact_d, fact_missing, fact_cohort, verified_orders, closed = 0, 0, False, [], [], {}
        for planned in (p for p in manifest["planned_calls"] if p["config"] == config):
            sid, call = planned["scenario_id"], planned["call"]
            call_id = f"{manifest['run_id']}/{config}/{sid}/{call}"
            trace = selected(traces, config, sid, call)
            ts, ms, es, bs = [selected(v, config, sid, call) for v in (tools, memories, extractions, brief_rows)]
            turn_ids = Counter(call_id + "/" + str(t) for t in range(1, planned["expected_turns"] + 1))
            grader = next((g for g in graders.get(sid, {}).get("calls", []) if g["call"] == call), None)
            ev = CallEvidence(
                call_id=call_id, config=config, scenario_id=sid, call=call, scenario=scenarios[sid],
                spec=scenarios[sid]["calls"][call], trace=trace, tools=ts, memories=ms, extractions=es, briefs=bs,
                grader=grader, complete=Counter(context_key(r) for r in trace) == turn_ids,
                tool_complete=Counter(digest(t) for r in trace for t in r["tool_calls"]) == Counter(
                    digest({**e["request"], "result": e["result"]}) for e in ts),
                extraction_complete=Counter(context_key(e["context"]) for e in es) == turn_ids,
                disputed=bool(grader and grader["dispute_ids"]),
                issue=issue, ref=ref, src=src, inputs=inputs, manifest=manifest)
            call_refs = [ref(src.ref(config + "/" + f)) for f in ("tools.jsonl", "memory.jsonl", "extraction.jsonl")]

            call_findings, available_roles = coverage.call_bookkeeping(ev, graders.get(sid, {}).get("required_evidence", []))
            # A complete empty log proves no invocation; it is not missing evidence.
            log_present = (src.root / config / "tools.jsonl").is_file()
            available_roles["tools"] = available_roles["tool_events"] = ev.complete and ev.tool_complete and log_present
            tool_findings = tool_state.coverage(ev)
            call_findings += coverage.trace_matches_extraction(ev)
            found, orders = tool_state.check(ev, ref(src.ref(config + "/tools.jsonl")))
            tool_findings += found
            verified_orders += orders
            if orders:
                closed[sid] = min(closed.get(sid, 4), int(call.split("_")[1]))
            check(call_id + "/tool_execution_state", tool_findings, call_refs[:1])

            memory_findings = memory.integrity(ev)
            check(call_id + "/memory_integrity", memory_findings, call_refs[1:2])

            fact_findings, passed, total, missing, cohort = carryover.check(ev, memory_findings)
            fact_n, fact_d, fact_missing, fact_cohort = fact_n + passed, fact_d + total, fact_missing or missing, fact_cohort + cohort
            check(call_id + "/fact_carryover", fact_findings, call_refs)

            check(call_id + "/claim_gt_coverage", claims.gt_coverage(ev), call_refs[2:])
            call_findings += briefs.check(ev, checker)
            call_findings += coverage.guardrail_labelled(ev)
            for assertion, findings, matched in assertions.judge(ev, available_roles, checker, ROOT):
                if matched is not None:
                    details.append({"check_id": call_id + "/" + assertion["check_id"], "matching": matched,
                                    "labels": input_ref(assertion["params"]["expected_calls"])})
                    metric(call_id + "/tool_accuracy", "tool-accuracy.v2", [call_id], matched["tp"],
                           matched["tp"] + matched["fp"] + matched["fn"], call_refs, not ev.complete)
                check(call_id + "/" + assertion["check_id"], findings, call_refs)
                call_findings.extend(findings)
            check(call_id + "/grading", call_findings, call_refs)
        metric(config + "/fact_value", "fact-value.v1", fact_cohort, fact_n, fact_d,
               [ref(src.ref(config + "/extraction.jsonl"))], fact_missing)
        write(config + "/verified-orders.json", {"event_ids": verified_orders,
            "first_close_call_by_scenario": closed,
            "notice": "Only new orders proven in audit state; never seed orders or invocation-only close"})
        metric(config + "/verified_calls_to_close", "ratio.v1", [manifest["run_id"] + "/" + config + "/" + sid for sid in scenarios],
               sum(closed.values()), len(closed), [assets.ref(config + "/verified-orders.json")],
               Counter(context_key(r) for r in traces[config]) != Counter(k for k in expected if k.startswith(manifest["run_id"] + "/" + config + "/")), unit="count")

    # -- 4. Reports beside BTC's ---------------------------------------------------------------------------------
    if official_ref is not None:
        report = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/supplemental",
                  "run_id": manifest["run_id"], "status": status(issues), "checks": checks,
                  "metrics": metrics, "coverage_refs": [coverage_ref], "official_report": official_ref}
        validate("SupplementalReport", report)
        write("supplemental-report.json", report)
        timings = {config: rows(config + "/timing.jsonl", "TimingEvidence") for config in configs}
        extra, text = build_supplement(official_report, traces, timings, metrics)
        write("run-summary.json", extra)
        (target / "run-summary.txt").write_text(text, encoding="utf-8")
    write("claim-adjudication.json", review_claims(traces, scenarios))
    write("tool-business-error-review.json", review_tool_errors(tools))
    validation = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/score-validation",
                  "run_id": manifest["run_id"], "status": status(issues), "issues": issues, "coverage_refs": [coverage_ref]}
    validate("ValidationReport", validation)
    write("validation.json", validation)
    write("assertion-details.json", details)
    write("scorer-invocation.json", {**invocation, "diagnostic_only": bool(issues)})
    summary = {"run_id": manifest["run_id"], "fixture": manifest["fixture"], "status": status(issues),
               "official_report_available": official_ref is not None, "diagnostic_only": bool(issues),
               "quality_accepted": False, "deferred": read_json(src.path("collector-report.json"))["deferred"],
               "btc_full_readiness": "INCOMPLETE", "notice": "Offline scoring, not runtime/DB or acceptance certification"}
    write("score-report.json", summary)
    write("artifacts.lock.json", {"files": {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in sorted(target.rglob("*")) if p.is_file()}})
    locked_run(run_dir)
    checker.verify_sources()
    return summary
