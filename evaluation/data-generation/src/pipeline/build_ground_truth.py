"""Stage 7b — the ideal agent's trace for every call, proven perfect with BTC's official script.

Writes (layout: ``src/utils/dataset.py``)
* ``<seed>/trace_log/scenarios_<id>/call_<n>.jsonl``  the ideal agent (``trace_log`` rows) built from the labels
* ``<seed>/reports/oracle_report.json``               ``reference_eval.evaluate`` on that trace
* ``<seed>/reports/reference_report.json``            the same on the reference transcripts (if generated)
* ``<seed>/reports/a6_oracle.txt``                    A.6 table printed by the official CLI on the oracle
* ``<seed>/reports/tools_audit.{json,md}``            tools/params we use that are not in the BTC tool set
* ``<seed>/reports/schema_check.json``                every brief, tool call and trace row checked against
                                                      ``data/schemas`` (call_brief, handoff_brief, tools, trace_log)
* ``<seed>/reports/ground_truth_summary.json``        the scores, the hard cases, the audit's and schemas' verdicts

The oracle must score CCR 100 · RQR 0 · TSR 100 · HR 0 · 0 guardrail violations, and every file must
match BTC's schemas; anything else means a label (not the agent) is wrong, and the stage exits non-zero.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.ground_truth.traces import conversation_rows, oracle_rows
from src.metrics.btc_metrics import evaluate
from src.schemas.conversation import Conversation
from src.schemas.scenario import Scenario
from src.utils.btc_schemas import dataset_errors
from src.utils.btc_tools import EVAL_DIR, M2_TOOLS, OFFICIAL_TOOLS, fresh_mock_tools, mock_tools
from src.utils.dataset import Dataset
from src.utils.io import write_json
from src.utils.paths import OUTPUT_DIR, ROOT

# Tools the old BTC notebook schema listed under "M1 (qua mcp-memory)"; not in the revised official list (§3).
LEGACY_TOOLS = {"memory.read": "listed in the old tools_schema (mcp-memory); memory is now traced via memory_writes",
                "memory.write": "listed in the old tools_schema (mcp-memory); memory is now traced via memory_writes"}


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    tsr = report["task_success_rate"]
    return {"RQR": report["repeat_question_rate"]["value"], "CCR": report["context_carryover_rate"]["value"],
            "TSR": tsr["value"], "TSR_hard_cases": (tsr.get("hard_cases") or {}).get("value"),
            "HR": report["hallucination_rate"]["value"],
            "HR_price_promo": report["hallucination_rate"]["price_promo_only"]["value"],
            "guardrail_violations": report["guardrail_violations"]["total"],
            "memory_checks_review": sum(m["verdict"] == "review" for m in report["memory_checks"])}


def is_perfect(s: dict[str, Any]) -> bool:
    return (s["RQR"] in (0.0, None) and s["CCR"] in (100.0, None) and s["TSR"] == 100.0 and s["HR"] in (0.0, None)
            and s["guardrail_violations"] == 0)


# --------------------------------------------------------------------------- #
# Tool audit                                                                   #
# --------------------------------------------------------------------------- #
def tools_audit(scenarios: list[Scenario], conversations: list[Conversation],
                oracle_trace: list[dict[str, Any]]) -> dict[str, Any]:
    signatures = {name: inspect.signature(fn).parameters for name, fn in mock_tools().TOOLS.items()}
    usage: dict[str, Counter] = defaultdict(Counter)
    args_seen: dict[str, set[str]] = defaultdict(set)
    for s in scenarios:
        for call in s.calls.values():
            if call.success_if.tool_called:
                usage[call.success_if.tool_called]["success_if.tool_called"] += 1
                args_seen[call.success_if.tool_called] |= set(call.success_if.args_match)
            for tool in call.success_if.must_not_call_tools:
                usage[tool]["success_if.must_not_call_tools"] += 1
            if call.fault_injection:
                usage[call.fault_injection.tool]["fault_injection"] += 1
    for row in oracle_trace:
        for tc in row["tool_calls"]:
            usage[tc["name"]]["oracle_trace"] += 1
            args_seen[tc["name"]] |= set(tc["args"])
    for conv in conversations:
        for turn in conv.agent_turns():
            for tc in turn.tool_calls:
                usage[tc.name]["reference_transcripts"] += 1
                args_seen[tc.name] |= set(tc.args)
    rows = []
    for name in sorted(set(OFFICIAL_TOOLS) | set(usage)):
        params = signatures.get(name)
        official = name in OFFICIAL_TOOLS
        required = [p for p, v in params.items() if v.default is inspect.Parameter.empty] if params else []
        extra_args = sorted(args_seen[name] - set(params)) if params else sorted(args_seen[name])
        rows.append({"tool": name, "official": official, "level": "M2" if name in M2_TOOLS else "M1" if official else "team",
                     "mock_params": list(params) if params else [], "required_params": required,
                     "used": dict(usage[name]), "args_used": sorted(args_seen[name]),
                     "extra_args_not_in_btc": extra_args, "note": LEGACY_TOOLS.get(name, "")})
    return {"official_tools": list(OFFICIAL_TOOLS), "tools": rows,
            "not_in_btc": [r["tool"] for r in rows if not r["official"]],
            "extra_params": {r["tool"]: r["extra_args_not_in_btc"] for r in rows if r["official"] and r["extra_args_not_in_btc"]},
            "unused_official": [r["tool"] for r in rows if r["official"] and not r["used"]]}


def tools_audit_markdown(audit: dict[str, Any]) -> str:
    lines = ["# Tool audit vs BTC tool set", "",
             "Official tools (Điều chỉnh đề §3, `data/eval/mock_tools.py`): " + ", ".join(f"`{t}`" for t in audit["official_tools"]),
             "", "BTC allows extra tools/params (\"Được thêm tool/tham số riêng\"); they must be reported.", "",
             "## Tools used by our data that are NOT in the BTC set", ""]
    extra = [r for r in audit["tools"] if not r["official"]]
    lines += [f"- `{r['tool']}` — used {sum(r['used'].values())}× ({', '.join(f'{k} {v}' for k, v in r['used'].items())})"
              + (f"; {r['note']}" if r["note"] else "") for r in extra] or ["- none"]
    lines += ["", "## Extra parameters passed to official tools", ""]
    lines += [f"- `{tool}`: " + ", ".join(f"`{p}`" for p in params) for tool, params in audit["extra_params"].items()] or ["- none"]
    lines += ["", "## All tools", "", "| Tool | Official | Level | Required params (mock) | Args we use | Used |",
              "|---|---|---|---|---|---|"]
    for r in audit["tools"]:
        used = ", ".join(f"{k}: {v}" for k, v in r["used"].items()) or "—"
        lines.append(f"| `{r['tool']}` | {'yes' if r['official'] else '**no**'} | {r['level']} | "
                     f"{', '.join(r['required_params']) or '—'} | {', '.join(r['args_used']) or '—'} | {used} |")
    if audit["unused_official"]:
        lines += ["", "Official tools not exercised by any scenario yet: " + ", ".join(f"`{t}`" for t in audit["unused_official"])]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=OUTPUT_DIR,
                        help="dataset root: output (default) or <seed>/plan_preview")
    parser.add_argument("--allow-imperfect", action="store_true", help="do not fail when the oracle is not perfect")
    args = parser.parse_args()
    dataset = Dataset(args.root)
    reports = args.root / "reports"

    scenarios = list(dataset.iter_scenarios())
    if not scenarios:
        sys.exit(f"No valid scenarios in {dataset.scenarios_dir}")
    exported = {s.scenario_id: s.btc_export() for s in scenarios}

    # 1. the oracle's trace, one file per call, and the official evaluation of it
    oracle: list[dict[str, Any]] = []
    for scenario in scenarios:
        rows = oracle_rows(scenario)
        oracle += rows
        by_call: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_call[row["call"]].append(row)
        for call, call_rows in by_call.items():
            dataset.write_trace(scenario.scenario_id, call, call_rows)
    oracle_report = evaluate(exported, oracle)
    write_json(reports / "oracle_report.json", oracle_report)
    oracle_summary = summarize(oracle_report)

    # 2. the reference transcripts as a trace (not kept: validate_rules judges them call by call)
    conversations: list[Conversation] = list(dataset.iter_conversations()) if args.root == OUTPUT_DIR else []
    reference_summary = None
    if conversations:
        mocks: dict[str, Any] = {}
        ref_rows = [row for conv in conversations if conv.scenario_id in exported
                    for row in conversation_rows(conv, mocks.setdefault(conv.scenario_id, fresh_mock_tools()))]
        scored = {r["scenario_id"] for r in ref_rows}
        ref_report = evaluate({sid: s for sid, s in exported.items() if sid in scored}, ref_rows)
        write_json(reports / "reference_report.json", ref_report)
        reference_summary = summarize(ref_report)

    # 3. BTC's own CLI on the oracle: the A.6 table, reproducible with their script
    with tempfile.TemporaryDirectory() as folder:
        trace = Path(folder) / "oracle_trace.jsonl"
        trace.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in oracle), encoding="utf-8")
        cli = subprocess.run([sys.executable, str(EVAL_DIR / "reference_eval.py"), "--scenarios", str(dataset.scenarios_dir),
                              "--trace", str(trace), "--out", str(reports / "oracle_report_cli.json")],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    (reports / "a6_oracle.txt").write_text(cli.stdout + cli.stderr, encoding="utf-8")

    # 4. tool audit
    audit = tools_audit(scenarios, conversations, oracle)
    write_json(reports / "tools_audit.json", audit)
    (reports / "tools_audit.md").write_text(tools_audit_markdown(audit), encoding="utf-8")

    # 5. BTC's schemas, file by file
    schema_problems = dataset_errors(dataset)
    write_json(reports / "schema_check.json", {"files_with_errors": len(schema_problems), "errors": schema_problems})

    hard = {sid: s["hard_case"] for sid, s in exported.items() if s.get("hard_case")}
    summary = {"scenarios": len(scenarios), "calls": sum(len(s.calls) for s in scenarios),
               "by_persona_source": dict(Counter(s.persona_source for s in scenarios)),
               "hard_cases": len(hard), "hard_case_ids": hard, "oracle": oracle_summary,
               "oracle_perfect": is_perfect(oracle_summary), "reference": reference_summary,
               "tools_not_in_btc": audit["not_in_btc"], "extra_params": audit["extra_params"],
               "schema_files_with_errors": len(schema_problems)}
    write_json(reports / "ground_truth_summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "hard_case_ids"}, ensure_ascii=False, indent=2))
    if not summary["oracle_perfect"] and not args.allow_imperfect:
        failures = oracle_report["task_success_rate"]["failures"][:10]
        sys.exit(f"Oracle trace is not perfect -> a label is unsatisfiable. First failures: {failures}")
    if schema_problems and not args.allow_imperfect:
        first = next(iter(schema_problems.items()))
        sys.exit(f"{len(schema_problems)} files break BTC's schemas (reports/schema_check.json). First: {first}")


if __name__ == "__main__":
    main()
