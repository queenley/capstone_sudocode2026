"""The organisers' tables per method, from runs already finished: the four metrics (TSR, CCR, RQR, HR), the operating
mode and performance, and the LLM-judge rubric (J01-J12), overall and per conversation, as CSV. No model call.

    apps/ai-agent-service/.venv/Scripts/python.exe scripts/evaluation/method_metrics.py
    ... --method router=eval_3/full.jsonl --column Router=router --out evaluation/runs/x

Every metric number comes from the organisers' own code, never rewritten here: ``eval/reference_eval.py`` (imported)
for the four metrics, ``pipeline/eval/performance.measure`` for latency, tokens and cost, and the rubric judge's
verdicts as ``run_eval.py --judge-run`` wrote them. A method's trace is graded on the whole of its scenarios, and on
each *cohort* (the scenario set of a before/after round) that every compared method ran in full, so methods are
compared on the same scenarios and labels only.

The default methods are the runs in evaluation/runs that can be compared (same advisor model, extractor
product-extractor-v13, ADVISOR_CONTEXT=full, scenario labels byte-identical to eval_3's):

  baseline          eval_3/baseline.jsonl          409 data/dev, baseline_no_memory
  router            eval_3/full.jsonl              409 data/dev, full (knowledge v0, skills v0)
  router_rerun_*    r0-* of each round             the same router, run again before the change: run-to-run noise
  reflection        dev-1/r1-dev-1                 skills v1 (Reflection), 10 dev scenarios
  combined          gapmix-1/r1-gapmix-1           knowledge v6 + skills v2 (GapLoop + Reflection), 20 dev scenarios
  combined_proof    gapmix-1/r1-gap-loop           the same, on the 13 gap-loop proof cases (TSR only: no other labels)
  gaploop_proof     gap-1/r1-gap-loop              knowledge v5 (GapLoop), 13 gap-loop proof cases (TSR only)
  reflection1, gaploop5, combined1 (and -2)        the 15/11 rounds on the same 20 frozen scenarios as gapmix-1, two
                                                   runs each side; the organisers' columns read these
  *_proof, *_budget                                their proof sets: gap-loop (13) and budget (6), TSR only

The rubric of a method is read from ``<run>-judge/`` beside its run (``full.judge.jsonl``, or
``baseline_no_memory.judge.jsonl`` for a baseline trace); make it with
``run_eval.py --judge-run evaluation/runs/<run> --out evaluation/runs/<run>-judge`` (judge model cost). A method with
no judged run has empty rubric cells, never a guessed verdict.

Writes into --out (default evaluation/runs/method-metrics, not in git: it holds the conversations):
  summary.csv        method x cohort: TSR, CCR, RQR, HR with their counts
  performance.csv    method: mode, call brief, TTFT/TTFA/total p50 and p95, sessions, tokens and cost per turn
  rubric.csv         method x criterion: PASS, FAIL, % PASS over the calls the judge graded completely
  conversations.csv  one row per method x scenario x call: transcript, that call's four metrics and J01-J12 verdicts
  turns.csv          one row per turn: customer text, agent reply, questions/redundant, claims/wrong
  summary.md         the tables, the organisers' layout first
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "evaluation" / "runs"
BTC_EVAL = ROOT / "apps" / "ai-agent-service" / "data" / "btc" / "eval"
REFERENCE = BTC_EVAL / "reference_eval.py"
CRITERIA = [c["id"] for c in json.loads((BTC_EVAL / "llm_judge_rubric.json").read_text(encoding="utf-8"))["criteria"]]

#: name -> trace (the scenario folder is the run's own frozen copy beside it).
DEFAULT_METHODS = {
    "baseline": "eval_3/baseline.jsonl",
    "router": "eval_3/full.jsonl",
    "router_rerun_dev1": "dev-1/r0-dev-1-1/full.jsonl",
    "reflection": "dev-1/r1-dev-1/full.jsonl",
    "router_rerun_gapmix1": "gapmix-1/r0-gapmix-1-1/full.jsonl",
    "combined": "gapmix-1/r1-gapmix-1/full.jsonl",
    "router_rerun_proof": "gap-1/r0-gap-loop-1/full.jsonl",
    "gaploop_proof": "gap-1/r1-gap-loop/full.jsonl",
    "combined_proof": "gapmix-1/r1-gap-loop/full.jsonl",
    # The 15/11 rounds: the same 20 frozen dev scenarios as gapmix-1, each side run twice (-2 = the second run).
    "router_rerun_r1": "reflection-1/r0-reflection-1-1/full.jsonl",
    "router_rerun_r1-2": "reflection-1/r0-reflection-1-2/full.jsonl",
    "reflection1": "reflection-1/r1-reflection-1/full.jsonl",
    "reflection1-2": "reflection-1/r1-reflection-1-2/full.jsonl",
    "router_rerun_g5": "gaploop-5/r0-gaploop-5-1/full.jsonl",
    "router_rerun_g5-2": "gaploop-5/r0-gaploop-5-2/full.jsonl",
    "gaploop5": "gaploop-5/r1-gaploop-5/full.jsonl",
    "gaploop5-2": "gaploop-5/r1-gaploop-5-2/full.jsonl",
    "router_rerun_c1": "combined_1/r0-combined_1-1/full.jsonl",
    "router_rerun_c1-2": "combined_1/r0-combined_1-2/full.jsonl",
    "combined1": "combined_1/r1-combined_1/full.jsonl",
    "combined1-2": "combined_1/r1-combined_1-2/full.jsonl",
    # Their proof sets: gap-loop (13, TSR only) and budget (6, TSR only).
    "gaploop5_proof": "gaploop-5/r1-gap-loop/full.jsonl",
    "combined1_proof": "combined_1/r1-gap-loop/full.jsonl",
    "router_rerun_budget": "reflection-1/r0-budget-1/full.jsonl",
    "reflection1_budget": "reflection-1/r1-budget/full.jsonl",
    "combined1_budget": "combined_1/r1-budget/full.jsonl",
}
#: Cohorts named after the round whose frozen set they are; "dev409" is all of eval_3.
DEFAULT_COHORTS = {
    "dev409": "eval_3/scenarios",
    "dev-1 (10)": "dev-1/r1-dev-1/full.scenarios",
    "gapmix-1 (20)": "gapmix-1/r1-gapmix-1/full.scenarios",
    "gap-loop proof (13)": "gap-1/r1-gap-loop/full.scenarios",
    "budget proof (6)": "reflection-1/r1-budget/full.scenarios",
}
#: The organisers' columns -> the method that fills each; None: the agent has no such mode, the column says so.
DEFAULT_COLUMNS = {
    "Baseline": "baseline", "Router": "router", "Subagent": None, "GapLoop": "gaploop5",
    # combined1 was its own learning round (kb v5 + skills v1) and proved neither column: dropped 2026-11-16. The
    # column is filled from a 2x2 measurement (scripts/evaluation/ablation.py), given with --ablation.
    "Reflection": "reflection1", "GapLoop + Reflection": None, "A/B Testing": None,
}


ABLATION_COLUMNS = (("Router", "router"), ("GapLoop", "gaploop"), ("Reflection", "reflection"),
                    ("GapLoop + Reflection", "combined"))


def ablation_table(folder: Path) -> list[str]:
    """The organisers' four metrics from ablation.json (run ablation_verdict.py first): per set, each column the mean
    of its k runs with the [min-max] of those runs, so a difference smaller than the Router's own spread reads as one."""
    path = folder / "ablation.json"
    if not path.is_file():
        return ["", f"## Ablation: chưa có {path} (chạy ablation_verdict.py)", ""]
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = ["", f"## Bốn chỉ số theo phương pháp: đo 2x2 `{folder.name}` ({data['verdict']})", "",
             "Mỗi ô: trung bình của k lần chạy [thấp nhất-cao nhất]. Cùng bộ kịch bản, cùng số lần chạy cho mọi cột; "
             "chênh nhỏ hơn khoảng của Router là dao động.", ""]
    for label, metrics in data["metrics"].items():
        lines += [f"### {label}", "", "| Metrics | " + " | ".join(c for c, _ in ABLATION_COLUMNS) + " |",
                  "|---|" + "---|" * len(ABLATION_COLUMNS)]
        for name, key in (("Repeat-Question Rate (RQR)", "RQR"), ("Context Carryover Rate (CCR)", "CCR"),
                          ("Task Success Rate (TSR)", "TSR"), ("Hallucination Rate (HR)", "HR")):
            cells = []
            for _, config in ABLATION_COLUMNS:
                m = (metrics.get(config) or {}).get(key) or {}
                cells.append("chưa đo" if m.get("mean") is None else f"{m['mean']} [{m['min']}-{m['max']}]")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def reference():
    spec = importlib.util.spec_from_file_location("reference_eval", REFERENCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def performance_module():
    """``pipeline/eval/performance`` of the agent; None when this Python cannot import the agent (use its .venv)."""
    for path in (ROOT / "apps" / "ai-agent-service" / "src", ROOT / "packages" / "backend-common"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    try:
        from ai_agent_service.pipeline.eval import performance
    except ImportError as error:
        print(f"performance skipped ({error}): run with apps/ai-agent-service/.venv/Scripts/python.exe", file=sys.stderr)
        return None
    return performance


def scenario_dir(trace: Path) -> Path:
    for name in ("full.scenarios", "scenarios"):
        if (trace.parent / name).is_dir():
            return trace.parent / name
    raise SystemExit(f"{trace}: no scenarios folder beside it")


def judge_file(trace: Path, override: Path | None) -> Path | None:
    folder = override or trace.parent.with_name(trace.parent.name + "-judge")
    path = folder / ("baseline_no_memory.judge.jsonl" if trace.name.startswith("baseline") else "full.judge.jsonl")
    return path if path.is_file() else None


def load_judgments(path: Path | None) -> dict[tuple[str, str], dict]:
    if path is None:
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {(r["scenario_id"], r["call"]): r for r in rows}


def grade(ref, scenarios: dict, trace: dict) -> dict:
    """reference_eval's four numbers on these scenarios; None where no scenario carries the label."""
    rqr = ref.repeat_question_rate(scenarios, trace)
    ccr = ref.context_carryover_rate(scenarios, trace)
    tsr = ref.task_success_rate(scenarios, trace)
    hr = ref.hallucination_rate(scenarios, trace)
    return {
        "n_scenarios": len(scenarios),
        "TSR": tsr["value"], "tsr_passed": tsr["passed"], "tsr_total": tsr["total"],
        "TSR_hard": (tsr["hard_cases"] or {}).get("value"),
        "CCR": ccr["value"], "ccr_used": ccr["used"], "ccr_required": ccr["required"],
        "RQR": rqr["value"], "rqr_redundant": rqr["redundant"], "rqr_questions": rqr["total_questions"],
        "HR": hr["value"], "hr_wrong": hr["wrong"], "hr_claims": hr["total_claims"],
        "HR_price": hr["price_promo_only"]["value"],
    }


def per_call(ref, sid: str, s: dict, call: str, trace: dict) -> dict:
    """The four metrics of one call, by reference_eval's own functions on a scenario cut down to that call."""
    one = {sid: {**s, "calls": {call: s["calls"][call]}}}
    rqr = ref.repeat_question_rate(one, trace)
    ccr = ref.context_carryover_rate(one, trace)
    hr = ref.hallucination_rate(one, trace)
    earlier = [r for c in sorted(s["calls"]) if c < call for r in trace.get((sid, c), [])]
    passed, reasons = ref.check_call(s["calls"][call], trace.get((sid, call), []), ref.created_order_ids(earlier))
    return {
        "tsr_call": "" if passed is None else int(passed), "tsr_reasons": "; ".join(reasons),
        "rqr_redundant": rqr["redundant"], "rqr_questions": rqr["total_questions"], "RQR": rqr["value"],
        "ccr_used": ccr["used"], "ccr_required": ccr["required"], "CCR": ccr["value"],
        "hr_wrong": hr["wrong"], "hr_claims": hr["total_claims"], "HR": hr["value"],
    }


def rubric_cells(judgment: dict | None, rows: list[dict]) -> dict:
    """J01-J12 of one call: PASS/FAIL, blank when the criterion does not apply or the call was not judged.

    The verdicts are shown even for an INCOMPLETE call; ``rubric_incomplete_reason`` says why the judge's own check
    refused it: a criterion left out, or evidence that is not a word-for-word quote of the call (judge.BtcJudge)."""
    if judgment is None:
        return {"rubric_status": "", **{c: "" for c in CRITERIA}, "rubric_incomplete_reason": "", "rubric_fail_evidence": ""}
    verdicts = {v["criterion_id"]: v for v in judgment.get("verdicts", [])}
    reason = ""
    if judgment.get("status") != "COMPLETE":
        words = "\n".join(f"{r.get('customer_text') or ''}\n{r.get('agent_text') or ''}" for r in rows)
        missing = [c for c in judgment.get("criteria", []) if c not in verdicts]
        unquoted = [c for c, v in verdicts.items() if v.get("evidence", "").strip() not in words]
        reason = "; ".join(filter(None, [
            judgment.get("error") and f"lỗi judge: {judgment['error']}",
            missing and "thiếu tiêu chí: " + ", ".join(missing),
            unquoted and "evidence không trích nguyên văn: " + ", ".join(unquoted)])) or "evidence chứa dữ liệu đã che PII"
    return {
        "rubric_status": judgment.get("status", ""),
        **{c: verdicts[c]["verdict"] if c in verdicts else "" for c in CRITERIA},
        "rubric_incomplete_reason": reason,
        "rubric_fail_evidence": " | ".join(f"{c}: {v.get('evidence', '')}" for c, v in verdicts.items()
                                           if v.get("verdict") == "FAIL"),
    }


def rubric_summary(judgments: dict[tuple[str, str], dict]) -> dict[str, dict]:
    """Per criterion: % PASS over the calls the judge graded completely (``judge.summarise``'s rule), and over every
    verdict it gave (an INCOMPLETE call usually has all its verdicts, only an evidence that is not a quote)."""
    complete = [j for j in judgments.values() if j.get("status") == "COMPLETE"]
    out = {"_calls": {"calls": len(judgments), "complete": len(complete)}}
    rate = lambda p, n: round(100 * p / n, 1) if n else None
    for c in CRITERIA:
        strict = [v["verdict"] for j in complete for v in j.get("verdicts", []) if v["criterion_id"] == c]
        every = [v["verdict"] for j in judgments.values() for v in j.get("verdicts", []) if v["criterion_id"] == c]
        out[c] = {"PASS": strict.count("PASS"), "FAIL": len(strict) - strict.count("PASS"),
                  "pass_rate": rate(strict.count("PASS"), len(strict)),
                  "PASS_all": every.count("PASS"), "FAIL_all": len(every) - every.count("PASS"),
                  "pass_rate_all": rate(every.count("PASS"), len(every))}
    return out


def redundant_turns(s: dict, call: str, rows: list[dict]) -> dict[int, int]:
    """Redundant questions per turn, by reference_eval's RQR rule (open question on must_not_ask, or a second confirm)."""
    mna, confirmed, out = set(s["calls"][call].get("must_not_ask", [])), set(), {}
    if not mna:
        return out
    for r in rows:
        bad = 0
        for q in r.get("questions", []):
            if q["type"] == "open" and q["slot"] in mna:
                bad += 1
            elif q["type"] == "confirm":
                bad += q["slot"] in confirmed
                confirmed.add(q["slot"])
        out[r["turn"]] = bad
    return out


def ms(stat: dict | None, key: str) -> str:
    return "chưa đo" if not stat else f"{stat[key]} ms"


def performance_row(perf, run: Path) -> dict:
    """The organisers' "Chế độ vận hành & hiệu năng" of one run, from its files."""
    figures = perf.measure(run)
    lat, tokens = figures["latency"], figures["tokens_per_turn"]
    saved = run / "performance.json"
    sessions = json.loads(saved.read_text(encoding="utf-8")).get("sessions") if saved.is_file() else None
    cost = (tokens or {}).get("cost_usd") or {}
    modes = figures["modes"]
    return {
        "turns": figures["turns"], "calls": figures["calls"],
        "mode": ", ".join(f"{'chat (text)' if k == 'text' else k}: {v} lượt" for k, v in modes.items()),
        "call_brief_p50": ms(lat["call_brief"], "p50_ms"), "call_brief_p95": ms(lat["call_brief"], "p95_ms"),
        "ttft_p50": ms(lat["ttft"], "p50_ms"), "ttfa_p50": ms(lat["ttfa"], "p50_ms"), "total_p50": ms(lat["total"], "p50_ms"),
        "ttft_p95": ms(lat["ttft"], "p95_ms"), "ttfa_p95": ms(lat["ttfa"], "p95_ms"), "total_p95": ms(lat["total"], "p95_ms"),
        "sessions": perf.sessions_line(sessions or []),
        "tokens_per_turn": f"{tokens['total']:.0f} (vào {tokens['input']:.0f}, ra {tokens['output']:.0f})" if tokens else "chưa đo",
        "usd_per_turn_gemini_3_flash": cost.get("gemini-3-flash", "chưa đo"),
        "usd_per_turn_gpt_4_1_mini": cost.get("gpt-4.1-mini", "chưa đo"),
        "advisor_model": (figures.get("advisor") or {}).get("model", ""),
    }


PERFORMANCE_ROWS = [
    ("Chế độ vận hành", "mode"), ("Thời gian nạp Call Brief (p50)", "call_brief_p50"),
    ("Thời gian nạp Call Brief (p95)", "call_brief_p95"),
    ("p50 · TTFT (chat)", "ttft_p50"), ("p50 · TTFA (voice)", "ttfa_p50"), ("p50 · Total Latency", "total_p50"),
    ("p95 · TTFT (chat)", "ttft_p95"), ("p95 · TTFA (voice)", "ttfa_p95"), ("p95 · Total Latency", "total_p95"),
    ("Số phiên đồng thời (demo)", "sessions"), ("Số token mỗi lượt (trung bình)", "tokens_per_turn"),
    ("USD mỗi lượt · Gemini 3 Flash", "usd_per_turn_gemini_3_flash"), ("USD mỗi lượt · GPT-4.1-mini", "usd_per_turn_gpt_4_1_mini"),
    ("Số lượt đo", "turns"), ("Model advisor", "advisor_model"),
]


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8-sig") as fh:   # utf-8-sig: Excel reads Vietnamese correctly
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fmt(v) -> str:
    return "-" if v is None else str(v)


def table(head: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *["| " + " | ".join(r) + " |" for r in rows], ""]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--method", action="append", default=[], metavar="NAME=TRACE",
                   help="a trace (.jsonl, relative to evaluation/runs or absolute); replaces the default methods")
    p.add_argument("--cohort", action="append", default=[], metavar="NAME=SCENARIOS",
                   help="a scenario folder to compare every method on; replaces the default cohorts")
    p.add_argument("--column", action="append", default=[], metavar="COLUMN=METHOD",
                   help="which method fills an organisers' column (Router, GapLoop, ...); overrides that column only")
    p.add_argument("--judge", action="append", default=[], metavar="METHOD=JUDGE_DIR",
                   help="the --judge-run output of a method, when it is not <run>-judge beside the run")
    p.add_argument("--out", default=str(RUNS / "method-metrics"))
    p.add_argument("--ablation", help="evaluation/runs/<name> of ablation.py: the Router, GapLoop, Reflection and "
                                      "GapLoop + Reflection columns of the four metrics, k runs each on one suite")
    args = p.parse_args()

    pairs = lambda items, default: dict(i.split("=", 1) for i in items) if items else dict(default)
    resolve = lambda v: Path(v) if Path(v).is_absolute() else (RUNS / v if (RUNS / v).exists() else ROOT / v)
    methods = {n: resolve(v) for n, v in pairs(args.method, DEFAULT_METHODS).items()}
    cohorts = {n: resolve(v) for n, v in pairs(args.cohort, DEFAULT_COHORTS).items()}
    columns = {**DEFAULT_COLUMNS, **dict(i.split("=", 1) for i in args.column)}
    judge_dirs = {n: resolve(v) for n, v in pairs(args.judge, {}).items()}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ref, perf = reference(), performance_module()

    traces, labels, judgments, notes = {}, {}, {}, []
    for name, path in methods.items():
        if not path.exists():
            print(f"skip {name}: {path} not found", file=sys.stderr)
            continue
        traces[name] = ref.load_trace(str(path))
        labels[name] = ref.load_scenarios(str(scenario_dir(path)))
        judgments[name] = load_judgments(judge_file(path, judge_dirs.get(name)))

    # ---- the four metrics, on each run's own scenarios and on every shared cohort
    summary = []
    for name, trace in traces.items():
        ran = {sid for sid, _ in trace}
        own = {sid: s for sid, s in labels[name].items() if sid in ran}
        summary.append({"method": name, "cohort": "own", **grade(ref, own, trace)})
        report = methods[name].parent / "report.json"
        if report.exists():
            r = json.loads(report.read_text(encoding="utf-8"))
            side = r["baseline"] if methods[name].name == "baseline.jsonl" else r["system"]
            theirs = side["task_success_rate"]["value"], side["hallucination_rate"]["value"]
            if theirs != (summary[-1]["TSR"], summary[-1]["HR"]):
                notes.append(f"{name}: TSR/HR {summary[-1]['TSR']}/{summary[-1]['HR']} differ from report.json {theirs}")
    for cname, folder in cohorts.items():
        cohort = ref.load_scenarios(str(folder))
        for name, trace in traces.items():
            if not set(cohort) <= {sid for sid, _ in trace}:
                continue
            if any(labels[name].get(sid) != cohort[sid] for sid in cohort):
                notes.append(f"{name} on {cname}: labels differ from the cohort's; graded with the cohort's")
            summary.append({"method": name, "cohort": cname, **grade(ref, cohort, trace)})

    # ---- performance: the full trace of each run (a baseline trace has no performance of its own)
    performance = {}
    if perf is not None:
        for name, path in methods.items():
            if name in traces and path.name == "full.jsonl":
                try:
                    performance[name] = performance_row(perf, path.parent)
                except (OSError, ValueError) as error:
                    notes.append(f"{name}: performance not measured ({error})")

    # ---- rubric
    rubric = {name: rubric_summary(j) for name, j in judgments.items() if j}
    for name in traces:
        if name not in rubric:
            notes.append(f"{name}: no rubric (run_eval.py --judge-run {methods[name].parent.relative_to(RUNS.parent.parent)}"
                         f" --out {methods[name].parent.relative_to(RUNS.parent.parent)}-judge)")

    # ---- per conversation and per turn
    conversations, turns = [], []
    for name, trace in traces.items():
        for (sid, call), rows in sorted(trace.items()):
            s = labels[name].get(sid)
            if not s or call not in s["calls"]:
                continue
            spec = s["calls"][call]
            transcript = "\n".join(f"Khách: {r.get('customer_text', '')}\nAgent: {r.get('agent_text', '')}" for r in rows)
            conversations.append({
                "method": name, "scenario_id": sid, "call": call, "hard_case": int(bool(s.get("hard_case"))),
                "expected_outcome": spec.get("expected_outcome", ""), "n_turns": len(rows),
                **per_call(ref, sid, s, call, trace), **rubric_cells(judgments[name].get((sid, call)), rows),
                "transcript": transcript,
            })
            gt, bad = spec.get("ground_truth_facts", {}), redundant_turns(s, call, rows)
            for r in rows:
                checked = [c for c in r.get("claims", []) if c["field"] in gt]
                turns.append({
                    "method": name, "scenario_id": sid, "call": call, "turn": r["turn"],
                    "customer_text": r.get("customer_text", ""), "agent_text": r.get("agent_text", ""),
                    "questions": len(r.get("questions", [])), "redundant_questions": bad.get(r["turn"], 0),
                    "facts_used": ", ".join(r.get("facts_used", [])),
                    "claims_checked": len(checked), "claims_wrong": sum(c["value"] != gt[c["field"]] for c in checked),
                    "tools": ", ".join(tc["name"] for tc in r.get("tool_calls", [])),
                    "ttft_ms": (r.get("latency") or {}).get("ttft_ms"), "total_ms": (r.get("latency") or {}).get("total_ms"),
                })

    write_csv(out / "summary.csv", summary)
    write_csv(out / "conversations.csv", conversations)
    write_csv(out / "turns.csv", turns)
    write_csv(out / "performance.csv", [{"method": n, **row} for n, row in performance.items()])
    write_csv(out / "rubric.csv", [{"method": n, "criterion": c, **v, **r["_calls"]}
                                   for n, r in rubric.items() for c, v in r.items() if c != "_calls"])

    # ---- the text: the organisers' layout first
    def cell(column: str, value) -> str:
        return "chưa có" if columns.get(column) is None else value

    perf_cols = [c for c in columns if c != "Baseline"]
    lines = ["# Bảng của BTC theo phương pháp", "",
             "Cột nào chưa có chế độ đó trong agent ghi `chưa có`; cột có nhưng chưa đo ghi `chưa đo`.", "",
             "## Chế độ hoạt động & hiệu năng", ""]
    lines += table(["Metrics", *[f"{c} ({columns[c]})" if columns[c] else c for c in perf_cols]],
                   [[label, *[cell(c, str((performance.get(columns[c]) or {}).get(key, "chưa đo"))) for c in perf_cols]]
                    for label, key in PERFORMANCE_ROWS])
    def rubric_cell(column: str, crit: str) -> str:
        v = rubric.get(columns[column] or "")
        if columns.get(column) is None:
            return "chưa có"
        if v is None:
            return "chưa đo"
        r = v[crit]
        if r["pass_rate_all"] is None:
            return "-"
        strict = "-" if r["pass_rate"] is None else f"{r['pass_rate']}"
        return f"{r['pass_rate_all']} ({r['PASS_all']}/{r['PASS_all'] + r['FAIL_all']}) · đủ {strict}"

    lines += ["## LLM Judge Rubric", "",
              "% PASS trên mọi verdict của judge (PASS/tổng), rồi `đủ`: % PASS chỉ trên cuộc gọi judge chấm đủ "
              "(evidence trích nguyên văn, quy tắc của judge.summarise). `-`: tiêu chí không áp dụng cho cuộc gọi nào.", ""]
    lines += table(["Metrics", *columns], [[crit, *[rubric_cell(c, crit) for c in columns]] for crit in CRITERIA]
                   + [["Cuộc gọi chấm đủ", *[cell(c, (lambda v: "chưa đo" if v is None else
                       f"{v['_calls']['complete']}/{v['_calls']['calls']}")(rubric.get(columns[c] or ""))) for c in columns]]])
    lines += ["## Bốn chỉ số (reference_eval.py của BTC)", ""]
    for cname in ["own", *cohorts]:
        rows = [r for r in summary if r["cohort"] == cname]
        if not rows:
            continue
        lines += [f"### {'Toàn bộ kịch bản mỗi run' if cname == 'own' else cname}", ""]
        lines += table(["Phương pháp", "n", "TSR %", "CCR %", "RQR %", "HR %"],
                       [[r["method"], str(r["n_scenarios"]), f"{fmt(r['TSR'])} ({r['tsr_passed']}/{r['tsr_total']})",
                         fmt(r["CCR"]), f"{fmt(r['RQR'])} ({r['rqr_redundant']}/{r['rqr_questions']})",
                         f"{fmt(r['HR'])} ({r['hr_wrong']}/{r['hr_claims']})"] for r in rows])
    if notes:
        lines += ["## Ghi chú", "", *[f"- {n}" for n in notes], ""]
    if args.ablation:
        lines += ablation_table(RUNS / args.ablation)
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(lines))
    print(f"Wrote {out}: summary.csv, performance.csv, rubric.csv, conversations.csv ({len(conversations)} rows), "
          f"turns.csv ({len(turns)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
