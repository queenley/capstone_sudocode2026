"""Stage 11 — data-generation report with visualizations.

Outputs (``<seed>/reports/``)
* ``validation_report.md``   – tables + Mermaid charts (renders on GitHub / Mermaid-enabled previews)
* ``validation_report.html`` – self-contained visual report (meters, bars, tooltips, dark mode)
* ``audio_statistics.json``, ``audio_by_customer.csv`` – audio analysis data

Sections: M2 volume targets, Chapter A metric coverage, simulator repeatability,
audio (calls per customer, channel, noise), review funnel. Generated ≠ golden:
the funnel separates generated, rule-passed, judge-passed and human-approved records.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.schemas.catalog import ProductCatalog
from src.utils.audio_stats import collect as collect_audio, summarize as summarize_audio, to_markdown as audio_markdown
from src.utils.crm import load_customers
from src.utils.dataset import Dataset
from src.utils.io import load_model
from src.utils.paths import (
    ASR_TEST_DIR, CATALOG_DIR, GOLDEN_MANIFEST, MODEL_CALLS_LOG, PLAN_PREVIEW_DIR, RAG_DIR, REPORTS_DIR, REVIEW_DIR,
    SIMULATION_REPLAYS, VALIDATION_JSON,
)
from src.utils.report_html import render as render_html
from src.utils.settings import load_settings

# M2 volume requirements (competition brief).
TARGETS = {"conversations": 250, "audio_conversations": 100, "audio_hours": 3, "multi_session_customers": 60,
           "multi_channel_customers": 30, "categories": 3, "category_region_pairs": 9, "skus": 100,
           "noisy_ratio": 0.20, "scenarios": 40}
MAX_TSR_STD_POINTS = 10  # BTC simulator spec §5(b)
METRICS = (("CCR", "CCR"), ("RQR", "RQR"), ("TSR", "TSR"), ("HR", "HR"), ("Over-escalation", "over_escalation"))


def _json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def estimated_usd(calls_log: list[dict[str, Any]], prices: dict[str, dict[str, float]]) -> float | None:
    """The model requests' cost by settings.yaml pricing_usd_per_mtok, cached prompt tokens at the cached rate.
    None when a model that was paid for has no price: a partial sum would read as the whole."""
    total = 0.0
    for row in calls_log:
        if row.get("cache_hit") or row.get("prompt_tokens") is None:
            continue
        price = prices.get(row.get("model", ""))
        if price is None:
            return None
        cached = row.get("cached_tokens") or 0
        total += ((row["prompt_tokens"] - cached) * price["input"] + cached * price["cached"]
                  + (row.get("output_tokens") or 0) * price["output"]) / 1_000_000
    return round(total, 4)


# --------------------------------------------------------------------------- #
# Data collection                                                              #
# --------------------------------------------------------------------------- #
def simulator_stats() -> dict[str, Any]:
    path = SIMULATION_REPLAYS
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    records = [r for r in records if "tsr_pass" in r]  # ignore pre-v2 replays
    by_seed: dict[int, list[bool]] = defaultdict(list)
    for record in records:
        by_seed[record["seed"]].append(bool(record["tsr_pass"]))
    per_seed = {seed: 100 * sum(v) / len(v) for seed, v in sorted(by_seed.items()) if v}
    values = list(per_seed.values())
    return {"replays": len(records), "seeds": len(per_seed), "per_seed": per_seed, "max_std": MAX_TSR_STD_POINTS,
            "tsr_mean": statistics.mean(values) if values else None,
            "tsr_std": statistics.pstdev(values) if values else None}


def write_audio_outputs(summary: dict[str, Any]) -> None:
    (REPORTS_DIR / "audio_statistics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (REPORTS_DIR / "audio_by_customer.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["customer_id", "customer_name", "region", "scenarios", "audio_calls", "turns", "minutes",
                         "channels", "noisy_turns", "noise_known_turns"])
        for c in summary["by_customer"]:
            writer.writerow([c["customer_id"], c["customer_name"] or "", c["region"], c["scenarios"], c["calls"],
                             c["turns"], round(c["seconds"] / 60, 2),
                             "; ".join(f"{k}={v}" for k, v in c["channels"].items()),
                             c["noisy_turns"], c["noise_known_turns"]])


def build_context() -> dict[str, Any]:
    """Every number shown in the Markdown and HTML reports."""
    catalog = load_model(CATALOG_DIR / "products.json", ProductCatalog)
    dataset = Dataset()
    scenarios = list(dataset.iter_scenarios())
    conversations = [_json(p, {}) for p in dataset.conversation_paths()]
    validations = [r for r in _json(VALIDATION_JSON, []) if "call" in r]  # ignore pre-v2 rows
    verdicts = {v.get("conversation_id"): v for v in (_json(p, {}) for p in dataset.judgment_paths())}
    stats = _json(REPORTS_DIR / "dataset_statistics.json", {})
    audio = summarize_audio(collect_audio())
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    write_audio_outputs(audio)
    ov = audio["overview"]
    noisy_ratio = audio["noise_summary"]["noisy_ratio"] or 0.0

    # Sessions and channels per customer, over every planned call (BTC M2: ≥ 60 and ≥ 30 customers).
    sessions, channels = defaultdict(int), defaultdict(set)
    for scenario in scenarios:
        for _, call in scenario.ordered_calls():
            who = call.speaker_customer_id or scenario.customer_id
            sessions[who] += 1
            channels[who].add(call.channel)
    multi_session = sum(n >= 2 for n in sessions.values())
    multi_channel = sum(len(c) >= 2 for c in channels.values())
    domains = {p.category.split("/")[0] for p in catalog.products}
    pairs = {(s.category.split("/")[0], s.region) for s in scenarios}
    skus = sum(1 + len(p.variants) for p in catalog.products)

    def target(name: str, key: str, current: float, shown: Any = None, fmt=None) -> dict[str, Any]:
        required = TARGETS[key]
        return {"name": name, "required": fmt(required) if fmt else required,
                "current": shown if shown is not None else current,
                "ratio": current / required if required else 0, "ok": current >= required}

    pct = lambda x: f"{x:.0%}"  # noqa: E731
    targets = [
        target("Transcript conversations (one per call)", "conversations", len(conversations)),
        target("Audio calls", "audio_conversations", ov["calls"]),
        target("Audio duration (hours)", "audio_hours", ov["hours"], round(ov["hours"], 2)),
        target("Customers with ≥2 sessions", "multi_session_customers", multi_session),
        target("Customers with ≥2 channels", "multi_channel_customers", multi_channel),
        target("Product categories", "categories", len(domains)),
        target("Category × region pairs", "category_region_pairs", len(pairs)),
        target("SKUs incl. variants", "skus", skus),
        target("Noisy audio ratio (known status)", "noisy_ratio", noisy_ratio, pct(noisy_ratio), pct),
        target("Scenarios", "scenarios", len(scenarios)),
    ]
    if not ov["turns"]:
        targets[8]["ok"] = False

    coverage_raw = stats.get("metric_coverage", {})
    # Real run first; fall back to the offline plan preview (run_all --plan-only) when nothing was generated yet.
    summary_path = REPORTS_DIR / "ground_truth_summary.json"
    preview = not summary_path.exists()
    gt_summary = _json(PLAN_PREVIEW_DIR / "reports" / "ground_truth_summary.json" if preview else summary_path, {})
    official = {"oracle": gt_summary.get("oracle"), "reference": gt_summary.get("reference"),
                "oracle_perfect": gt_summary.get("oracle_perfect"), "preview": preview}
    coverage = {}
    for name, _ in METRICS:
        item = coverage_raw.get("ESC" if name == "Over-escalation" else name, {})
        key = "guardrail_violations" if name == "Over-escalation" else name
        ref = (official["reference"] or {}).get(key)
        coverage[name] = {"calls": item.get("calls", 0), "labels": item.get("labels", 0),
                          "reference": "n/a" if ref is None else ref}
    hard_cases: dict[str, int] = defaultdict(int)
    for case in gt_summary.get("hard_case_ids", {}).values():
        hard_cases[case] += 1

    rule_pass = sum(r["validator_pass"] for r in validations)
    judge_pass = sum(r["validator_pass"] and verdicts.get(r["conversation_id"], {}).get("overall_pass", False)
                     for r in validations)
    approved_csv = REVIEW_DIR / "approved.csv"
    human = sum(1 for _ in csv.DictReader(approved_csv.open(encoding="utf-8-sig"))) if approved_csv.exists() else 0
    golden = len(_json(GOLDEN_MANIFEST, {}).get("conversation_ids", []))
    calls_log = [json.loads(x) for x in MODEL_CALLS_LOG.read_text(encoding="utf-8").splitlines()] if MODEL_CALLS_LOG.exists() else []

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kpis": {"scenarios": len(scenarios), "calls": stats.get("totals", {}).get("calls", 0),
                 "reference transcripts": len(conversations), "golden conversations": golden,
                 "audio calls": ov["calls"], "audio hours": round(ov["hours"], 2)},
        "targets": targets,
        "coverage": coverage,
        "official": official,
        "test_set": {"n_scenarios": gt_summary.get("scenarios", 0), "n_hard_cases": gt_summary.get("hard_cases", 0),
                     "n_calls": gt_summary.get("calls", 0), "hard_cases": dict(sorted(hard_cases.items()))},
        "rag": _json(RAG_DIR / "rag_report.json", None),
        "asr_team_dialogues": len(_json(ASR_TEST_DIR / "ground_truth.json", {}).get("dialogues", [])),
        "tools": _json(REPORTS_DIR / "tools_audit.json", None) or _json(PLAN_PREVIEW_DIR / "reports" / "tools_audit.json", None),
        "judge_agreement": _json(REPORTS_DIR / "judge_agreement.json", None),
        "simulator": simulator_stats(),
        "audio": audio,
        "funnel": [("Generated", len(conversations)), ("Rule pass", rule_pass), ("Judge pass", judge_pass),
                   ("Human approved", human), ("Golden", golden)],
        "api": {"requests": sum(not x.get("cache_hit", False) for x in calls_log),
                "cache_hits": sum(bool(x.get("cache_hit")) for x in calls_log),
                "prompt_tokens": sum(x.get("prompt_tokens") or 0 for x in calls_log),
                "output_tokens": sum(x.get("output_tokens") or 0 for x in calls_log),
                "cached_tokens": sum(x.get("cached_tokens") or 0 for x in calls_log),
                "estimated_usd": estimated_usd(calls_log, load_settings().get("pricing_usd_per_mtok") or {}),
                "tts_chars": _json(REPORTS_DIR / "elevenlabs_usage.json", {}).get("characters_sent", 0)},
        "crm_profiles": len(load_customers()),
    }


# --------------------------------------------------------------------------- #
# Markdown (+ Mermaid)                                                         #
# --------------------------------------------------------------------------- #
def _mermaid_bar(title: str, labels: list[str], values: list[float], y_label: str, y_max: float | None = None) -> list[str]:
    if not labels:
        return []
    top = y_max if y_max is not None else max(max(values), 1) * 1.1
    quoted = ", ".join(f'"{label}"' for label in labels)
    return ["```mermaid", "xychart-beta horizontal", f'    title "{title}"', f"    x-axis [{quoted}]",
            f'    y-axis "{y_label}" 0 --> {top:g}', f"    bar [{', '.join(f'{v:g}' for v in values)}]", "```", ""]


def official_markdown(ctx: dict[str, Any]) -> list[str]:
    """Official reference_eval numbers, hard cases, RAG, ASR, tool audit, judge agreement."""
    off = ctx["official"]
    lines = ["", "## Official scores (BTC reference_eval.py)" + (" — plan preview, no generated data yet" if off.get("preview") else ""), ""]
    keys = ("RQR", "CCR", "TSR", "TSR_hard_cases", "HR", "HR_price_promo", "guardrail_violations")
    if off["oracle"]:
        lines += ["| Trace | " + " | ".join(keys) + " |", "|---|" + "---:|" * len(keys)]
        for name in ("oracle", "reference"):
            if off[name]:
                lines.append(f"| {name} | " + " | ".join(str(off[name].get(k)) for k in keys) + " |")
        lines += ["", f"Oracle perfect (every label satisfiable with BTC mock_tools): **{off['oracle_perfect']}**. "
                      "Score the agent with `data/eval/reference_eval.py --scenarios <seed>/scenarios --trace <agent trace>`."]
    else:
        lines.append("Not built yet: `python -m src.pipeline.build_ground_truth`.")
    ts = ctx["test_set"]
    lines += ["", f"### Test set: {ts['n_scenarios']} scenarios, {ts['n_calls']} calls, {ts['n_hard_cases']} hard cases", ""]
    lines += _mermaid_bar("Scenarios per hard case", list(ts["hard_cases"]), list(ts["hard_cases"].values()), "scenarios")
    rag = ctx["rag"]
    lines += ["", "## RAG (Recall@k on rag/qa_labeled.json)", ""]
    if rag:
        lines += [f"Method: {rag['method']}", "",
                  "| recall@3 | recall@5 | multi-hop full@3 | multi-hop full@5 | abstain unanswerable | abstain restricted | false abstain |",
                  "|---:|---:|---:|---:|---:|---:|---:|",
                  f"| {rag['recall@3']} | {rag['recall@5']} | {rag['multi_hop_full_recall@3']} | {rag['multi_hop_full_recall@5']} "
                  f"| {rag['abstain_rate_unanswerable']} | {rag['abstain_rate_restricted']} | {rag['false_abstain_rate']} |", ""]
        lines += _mermaid_bar("Recall@5 by question type (%)", list(rag["by_type_recall@5"]),
                              [v or 0 for v in rag["by_type_recall@5"].values()], "%", 100)
    else:
        lines.append("Not run yet: `python -m src.pipeline.eval_rag`.")
    lines += ["", "## ASR (WER / CER / entity accuracy)", "",
              f"Team ASR set: {ctx['asr_team_dialogues']} dialogues (BTC requires >= 20 plus the 12 BTC dialogues)."]
    lines.append("Scoring: BTC's `reference_eval.py` grades an ASR hypotheses file against this ground truth (`--asr`).")
    tools = ctx["tools"]
    lines += ["", "## Tools vs BTC tool set", ""]
    if tools:
        lines.append("Tools not in BTC set: " + (", ".join(f"`{t}`" for t in tools["not_in_btc"]) or "none")
                     + " · extra params: " + (", ".join(f"`{t}`: {p}" for t, p in tools["extra_params"].items()) or "none")
                     + " · details: `<seed>/reports/tools_audit.md`.")
    else:
        lines.append("Not audited yet: `python -m src.pipeline.build_ground_truth`.")
    agreement = ctx["judge_agreement"]
    lines += ["", "## LLM-judge vs human agreement", ""]
    lines.append(f"n={agreement['n_samples']} · agreement {agreement['agreement_pct']}% · Cohen's kappa {agreement['cohen_kappa']} "
                 f"({'reliable' if agreement['reliable'] else 'below 0.6: analyse errors'})" if agreement
                 else "Not measured yet: `python -m src.pipeline.judge_agreement --export` then `--ingest`.")
    return lines


def to_markdown(ctx: dict[str, Any]) -> str:
    lines = ["# Data generation report", "",
             f"_Generated {ctx['generated_at']}. Visual version: [validation_report.html](validation_report.html)._", "",
             "Generated records are not golden until they pass rules and the judge (or a human approves them).", "",
             "## M2 volume targets", ""]
    lines += _mermaid_bar("Progress toward M2 targets (%, capped at 100)",
                          [t["name"] for t in ctx["targets"]], [round(min(t["ratio"], 1) * 100) for t in ctx["targets"]],
                          "% of requirement", 100)
    lines += ["| Metric | Required | Current | Status |", "|---|---:|---:|---|"]
    lines += [f"| {t['name']} | {t['required']} | {t['current']} | {'✓ PASS' if t['ok'] else '○ PENDING'} |"
              for t in ctx["targets"]]

    lines += ["", "## Chapter A metric coverage", ""]
    lines += _mermaid_bar("Calls with labels per metric", list(ctx["coverage"]),
                          [c["calls"] for c in ctx["coverage"].values()], "calls")
    lines += ["| Metric | Calls with labels | Labels | Reference transcript score |", "|---|---:|---:|---|"]
    lines += [f"| {name} | {c['calls']} | {c['labels']} | {c['reference']} |" for name, c in ctx["coverage"].items()]

    lines += official_markdown(ctx)
    sim = ctx["simulator"]
    lines += ["", "## Simulator repeatability", "", f"- Replays: {sim['replays']} across {sim['seeds']} seeds."]
    if sim["tsr_mean"] is not None:
        ok = sim["tsr_std"] <= MAX_TSR_STD_POINTS
        lines.append(f"- TSR across seeds: {sim['tsr_mean']:.1f} ± {sim['tsr_std']:.1f} points "
                     f"({'within' if ok else 'OUTSIDE'} the ≤ {MAX_TSR_STD_POINTS}-point BTC tolerance).")
    else:
        lines.append("- No simulator replays yet.")

    audio = ctx["audio"]
    lines += [""] + audio_markdown(audio)[:1] + [""]
    noise = audio["noise_summary"]["by_type"]
    lines += _mermaid_bar("Audio turns by noise type", list(noise), [v["turns"] for v in noise.values()], "turns")
    dist = audio["calls_per_customer_distribution"]
    lines += _mermaid_bar("Customers by number of audio calls", [f"{k} calls" for k in dist], list(dist.values()),
                          "customers")
    lines += audio_markdown(audio)[1:]

    api = ctx["api"]
    lines += ["## Review funnel", ""]
    lines += _mermaid_bar("Reference transcripts through the gates", [s for s, _ in ctx["funnel"]],
                          [n for _, n in ctx["funnel"]], "conversations")
    lines += [" → ".join(f"{stage} **{n}**" for stage, n in ctx["funnel"]), "",
              f"- CRM profiles: {ctx['crm_profiles']} (incl. synthetic when generated)",
              f"- Model API requests: {api['requests']} · cache hits: {api['cache_hits']} · prompt tokens: "
              f"{api['prompt_tokens']} (cached {api['cached_tokens']}) · output tokens: {api['output_tokens']}"
              + (f" · estimated cost: ${api['estimated_usd']:.2f}" if api["estimated_usd"] is not None else ""),
              f"- ElevenLabs characters: {api['tts_chars']}", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=REPORTS_DIR / "validation_report.md",
                        help="Markdown path; the HTML report is written next to it")
    args = parser.parse_args()
    ctx = build_context()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(to_markdown(ctx), encoding="utf-8")
    html_path = args.output.with_suffix(".html")
    html_path.write_text(render_html(ctx), encoding="utf-8")
    print(args.output)
    print(html_path)


if __name__ == "__main__":
    main()
