"""Stage 7b — export the dataset in BTC format and prove every label with the official script.

Writes
* ``output/test_set/SCN-GEN-xxxx.json``          scenarios in ``test_set/public_sample`` format
  (+ ``_manifest.json``; files starting with ``_`` are skipped by reference_eval)
* ``output/ground_truth/oracle_trace.jsonl``     ideal-agent trace (``trace_log`` rows) built from labels
* ``output/ground_truth/reference_trace.jsonl``  reference transcripts as trace rows (if generated)
* ``output/ground_truth/*_report.json``          ``reference_eval.evaluate`` on each trace
* ``output/ground_truth/a6_oracle.txt``          A.6 table printed by the official CLI
* ``output/ground_truth/call_briefs.jsonl``, ``handoff_briefs.jsonl``   expected CallBrief / HandoffBrief
* ``output/reports/tools_audit.{json,md}``       tools/params we use that are not in the BTC tool set

The oracle must score CCR 100 · RQR 0 · TSR 100 · HR 0 · 0 guardrail violations; anything
else means a label (not the agent) is wrong, and the stage exits non-zero.
"""
from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.ground_truth.traces import conversation_rows, oracle_rows
from src.metrics.btc_metrics import evaluate
from src.schemas.conversation import Conversation, split_conversation_id
from src.schemas.scenario import Scenario
from src.utils.btc_tools import EVAL_DIR, M2_TOOLS, OFFICIAL_TOOLS, fresh_mock_tools, mock_tools
from src.utils.io import iter_models, write_json
from src.utils.paths import CONVERSATIONS_DIR, OUTPUT_DIR, REPORTS_DIR, ROOT, SCENARIOS_INTERNAL_DIR

# Tools the old BTC notebook schema listed under "M1 (qua mcp-memory)"; not in the revised official list (§3).
LEGACY_TOOLS = {"memory.read": "listed in the old tools_schema (mcp-memory); memory is now traced via memory_writes",
                "memory.write": "listed in the old tools_schema (mcp-memory); memory is now traced via memory_writes"}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


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
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS_INTERNAL_DIR,
                        help="internal scenarios (output/scenarios_internal or output/plans_internal)")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR, help="root for test_set/ and ground_truth/")
    parser.add_argument("--allow-imperfect", action="store_true", help="do not fail when the oracle is not perfect")
    args = parser.parse_args()
    test_set_dir, gt_dir = args.out / "test_set", args.out / "ground_truth"
    reports_dir = REPORTS_DIR if args.out == OUTPUT_DIR else gt_dir

    scenarios = [s for _, s in iter_models(sorted(args.scenarios.glob("SCN-GEN-*.json")), Scenario)]
    if not scenarios:
        sys.exit(f"No valid scenarios in {args.scenarios}")
    exported = {s.scenario_id: s.btc_export() for s in scenarios}

    # 1. test_set in public_sample format
    test_set_dir.mkdir(parents=True, exist_ok=True)
    for old in test_set_dir.glob("SCN-GEN-*.json"):
        old.unlink()
    for sid, payload in exported.items():
        write_json(test_set_dir / f"{sid}.json", payload)
    hard = sorted(sid for sid, s in exported.items() if s.get("hard_case"))
    write_json(test_set_dir / "_manifest.json", {
        "n_scenarios": len(exported), "n_hard_cases": len(hard), "hard_cases": {sid: exported[sid]["hard_case"] for sid in hard},
        "n_calls": sum(len(s["calls"]) for s in exported.values()), "format": "BTC test_set/public_sample (Phụ lục B)"})

    # 2. oracle trace + official evaluation
    oracle = [row for s in scenarios for row in oracle_rows(s)]
    write_jsonl(gt_dir / "oracle_trace.jsonl", oracle)
    oracle_report = evaluate(exported, oracle)
    write_json(gt_dir / "oracle_report.json", oracle_report)
    oracle_summary = summarize(oracle_report)

    # 3. reference transcripts as a trace
    conversations = [c for _, c in iter_models(sorted(CONVERSATIONS_DIR.glob("*__call_*.json")), Conversation)]
    reference_summary = None
    if conversations and args.out == OUTPUT_DIR:
        mocks: dict[str, Any] = {}
        ref_rows = []
        for conv in conversations:
            sid, _ = split_conversation_id(conv.conversation_id)
            if sid in exported:
                ref_rows += conversation_rows(conv, mocks.setdefault(sid, fresh_mock_tools()))
        write_jsonl(gt_dir / "reference_trace.jsonl", ref_rows)
        ref_report = evaluate({sid: s for sid, s in exported.items()
                               if any(r["scenario_id"] == sid for r in ref_rows)}, ref_rows)
        write_json(gt_dir / "reference_report.json", ref_report)
        reference_summary = summarize(ref_report)

    # 4. expected briefs
    write_jsonl(gt_dir / "call_briefs.jsonl", [{"scenario_id": s.scenario_id, "call": n, **c.expected_call_brief}
                                               for s in scenarios for n, c in s.ordered_calls() if c.expected_call_brief])
    write_jsonl(gt_dir / "handoff_briefs.jsonl", [{"scenario_id": s.scenario_id, "call": n, **c.expected_handoff_brief}
                                                  for s in scenarios for n, c in s.ordered_calls() if c.expected_handoff_brief])

    # 5. official CLI on the oracle (A.6 table, proves the numbers are reproducible with BTC's script)
    cli = subprocess.run([sys.executable, str(EVAL_DIR / "reference_eval.py"), "--scenarios", str(test_set_dir),
                          "--trace", str(gt_dir / "oracle_trace.jsonl"), "--out", str(gt_dir / "oracle_report_cli.json")],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ,
                                                                                           "PYTHONIOENCODING": "utf-8"})
    (gt_dir / "a6_oracle.txt").write_text(cli.stdout + cli.stderr, encoding="utf-8")

    # 6. tool audit
    audit = tools_audit(scenarios, conversations, oracle)
    write_json(reports_dir / "tools_audit.json", audit)
    (reports_dir / "tools_audit.md").write_text(tools_audit_markdown(audit), encoding="utf-8")

    summary = {"scenarios": len(scenarios), "hard_cases": len(hard), "oracle": oracle_summary,
               "oracle_perfect": is_perfect(oracle_summary), "reference": reference_summary,
               "tools_not_in_btc": audit["not_in_btc"], "extra_params": audit["extra_params"]}
    write_json(gt_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["oracle_perfect"] and not args.allow_imperfect:
        failures = oracle_report["task_success_rate"]["failures"][:10]
        sys.exit(f"Oracle trace is not perfect -> a label is unsatisfiable. First failures: {failures}")


if __name__ == "__main__":
    main()
