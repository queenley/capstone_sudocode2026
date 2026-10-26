"""Stage 10 — dataset coverage statistics and HTML dashboard.

Writes
* ``output/reports/dataset_statistics.json``   – all counters (+ metric coverage)
* ``output/reports/dataset_statistics/*.csv``  – one CSV per counter
* ``output/reports/dataset_dashboard.html``    – static dashboard

"Metric coverage" answers: how many labelled opportunities does the dataset
give each Chapter A metric (denominators), and how does the reference agent
score on them (should be CCR 1, RQR 0, TSR 1, HR 0, over-escalation 0).
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.metrics.btc_metrics import has_positive_requirement
from src.planning.planner import ESCALATION_TEMPTATION
from src.schemas.scenario import Scenario
from src.utils.dataset import Dataset
from src.utils.paths import AUDIO_DIR, GOLDEN_MANIFEST, REPORTS_DIR
from src.utils.settings import load_settings

METRIC_HELP = {
    "CCR": "Context carry-over — slots the agent must reuse (must_carry_over)",
    "RQR": "Redundant questions — slots the agent must not ask again (must_not_ask)",
    "TSR": "Task success — calls with a positive success_if (tool / phrase required)",
    "HR": "Hallucination — calls with forbidden claims (expired promo, old price, OOS, old policy)",
    "ESC": "Escalation — calls that must hand off vs. tempting calls that must not",
}


def coverage(scenarios: list[Scenario]) -> tuple[dict[str, Any], dict[str, Counter]]:
    c: dict[str, Counter] = {name: Counter() for name in (
        "persona_source", "persona", "hard_case", "variant", "region", "category", "category_region", "expected_outcome", "channel", "input_mode",
        "metric_focus", "calls_per_scenario", "must_carry_over", "must_not_ask", "success_if_checks",
        "forbidden_claim_fields", "ground_truth_facts_keys", "facts_established_keys")}
    m = Counter()
    for s in scenarios:
        top = s.category.split("/")[0]
        c["persona_source"][s.persona_source] += 1
        c["persona"][s.persona] += 1
        c["hard_case"][s.hard_case or "(none)"] += 1
        c["variant"][next((t.split(":", 1)[1] for t in s.tags if t.startswith("variant:")), "?")] += 1
        c["region"][s.region] += 1
        c["category"][top] += 1
        c["category_region"][f"{top} × {s.region}"] += 1
        c["calls_per_scenario"][str(len(s.calls))] += 1
        c["metric_focus"].update(s.metric_focus)
        for _, call in s.ordered_calls():
            m["calls"] += 1
            m["customer_turns"] += len(call.customer_turns)
            c["expected_outcome"][call.expected_outcome] += 1
            c["channel"][call.channel] += 1
            c["input_mode"][call.input_mode] += 1
            c["must_carry_over"].update(call.must_carry_over)
            c["must_not_ask"].update(call.must_not_ask)
            c["ground_truth_facts_keys"].update(call.ground_truth_facts.keys())
            c["facts_established_keys"].update(call.facts_established.keys())
            checks = call.success_if.model_dump(exclude_defaults=True)
            for key in checks:
                c["success_if_checks"][f"{key}:{call.success_if.tool_called}" if key == "tool_called" else key] += 1
            for rule in call.success_if.forbidden_claims:
                c["forbidden_claim_fields"][getattr(rule, "field", "phrase")] += 1
            m["ccr_calls"] += bool(call.must_carry_over); m["ccr_slots"] += len(call.must_carry_over)
            m["rqr_calls"] += bool(call.must_not_ask); m["rqr_slots"] += len(call.must_not_ask)
            m["tsr_calls"] += has_positive_requirement(call.success_if)
            m["hr_calls"] += bool(call.success_if.forbidden_claims)
            m["hr_traps"] += len(call.success_if.forbidden_claims)
            m["esc_must_handoff"] += call.expected_outcome == "chuyen_may"
            m["esc_must_not_handoff"] += call.expected_outcome != "chuyen_may" and s.persona in ESCALATION_TEMPTATION
    metric_coverage = {
        "CCR": {"calls": m["ccr_calls"], "labels": m["ccr_slots"]},
        "RQR": {"calls": m["rqr_calls"], "labels": m["rqr_slots"]},
        "TSR": {"calls": m["tsr_calls"], "labels": m["tsr_calls"]},
        "HR": {"calls": m["hr_calls"], "labels": m["hr_traps"]},
        "ESC": {"calls": m["esc_must_handoff"] + m["esc_must_not_handoff"],
                "labels": m["esc_must_handoff"], "tempting_no_handoff": m["esc_must_not_handoff"]},
    }
    return {"calls": m["calls"], "customer_turns": m["customer_turns"], "metric_coverage": metric_coverage}, c


def reference_scores() -> dict[str, Any] | None:
    """Official reference_eval summaries written by ``build_ground_truth`` (oracle + reference transcripts)."""
    path = REPORTS_DIR / "ground_truth_summary.json"
    if not path.exists():
        return None
    summary = json.loads(path.read_text(encoding="utf-8"))
    return {"oracle": summary.get("oracle"), "reference": summary.get("reference"),
            "oracle_perfect": summary.get("oracle_perfect")}


# --------------------------------------------------------------------------- #
# HTML                                                                         #
# --------------------------------------------------------------------------- #
def bar_rows(counter: Counter, limit: int = 20) -> str:
    rows = counter.most_common(limit)
    peak = max((count for _, count in rows), default=1)
    return "".join(
        f'<div class="bar-row"><span title="{html.escape(label)}">{html.escape(label)}</span>'
        f'<b style="width:{count / peak * 100:.1f}%">{count}</b></div>' for label, count in rows
    ) or '<p class="muted">No data yet</p>'


def render(stats: dict[str, Any], counters: dict[str, Counter]) -> str:
    cards = "".join(f'<div class="card"><strong>{html.escape(k.replace("_", " "))}</strong><span>{v}</span></div>'
                    for k, v in stats["totals"].items())
    cov = stats["metric_coverage"]
    ref = stats.get("reference_scores") or {}
    metric_cards = []
    for name, help_text in METRIC_HELP.items():
        item = cov[name]
        ref_key = {"ESC": "guardrail_violations"}.get(name, name)
        oracle_v = (ref.get("oracle") or {}).get(ref_key)
        reference_v = (ref.get("reference") or {}).get(ref_key)
        ref_html = (f'<em>official {ref_key} — oracle: {oracle_v if oracle_v is not None else "n/a"} · '
                    f'reference transcripts: {reference_v if reference_v is not None else "n/a"}</em>')
        metric_cards.append(f'<div class="card metric"><strong>{name}</strong><span>{item["calls"]}</span>'
                            f'<small>calls · {item["labels"]} labels</small><p>{html.escape(help_text)}</p>{ref_html}</div>')
    sections = [
        ("Metric focus (scenarios)", "metric_focus"), ("Hard cases (BTC §11)", "hard_case"), ("Persona", "persona"), ("Category × region", "category_region"),
        ("Expected outcome (calls)", "expected_outcome"), ("Channel", "channel"), ("Input mode", "input_mode"),
        ("must_carry_over slots (CCR)", "must_carry_over"), ("must_not_ask slots (RQR)", "must_not_ask"),
        ("success_if checks (TSR)", "success_if_checks"), ("Forbidden claim fields (HR)", "forbidden_claim_fields"),
        ("ground_truth_facts keys", "ground_truth_facts_keys"), ("facts_established keys", "facts_established_keys"),
        ("Calls per scenario", "calls_per_scenario"), ("Voice ID", "voice_id"),
    ]
    charts = "".join(f'<section><h2>{html.escape(title)}</h2>{bar_rows(counters.get(key, Counter()))}</section>'
                     for title, key in sections)
    return f'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dataset coverage dashboard</title>
<style>
:root{{--bg:#f4f1ea;--panel:#fffdf8;--line:#ded8ca;--ink:#20242a;--muted:#687078;--accent:#b34d2c;--bar:#2f7c78}}
body{{font-family:"Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink);margin:0 auto;padding:32px 16px;max-width:1400px}}
h1{{font-size:30px;margin:0 0 6px}} h2{{font-size:16px;margin:0 0 12px}} .muted{{color:var(--muted)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}
.card,section{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px}}
.card strong{{display:block;text-transform:capitalize;color:var(--muted);font-size:13px}}
.card span{{font-size:28px;font-weight:700;color:var(--accent)}}
.metric small{{color:var(--muted);margin-left:6px}} .metric p{{font-size:12px;margin:8px 0 4px;color:var(--ink)}}
.metric em{{font-size:12px;color:var(--bar);font-style:normal;font-weight:600}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}}
.bar-row{{display:grid;grid-template-columns:minmax(0,190px) 1fr;gap:8px;align-items:center;margin:6px 0;font-size:13px}}
.bar-row span{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar-row b{{display:block;background:var(--bar);color:#fff;border-radius:3px;padding:3px 8px;min-width:28px;box-sizing:border-box}}
</style></head><body>
<h1>Dataset coverage dashboard</h1>
<p class="muted">Scenarios, reference transcripts and audio produced by <code>evaluation/data-generation</code>.
Refresh with <code>python -m src.pipeline.summarize_dataset</code>.</p>
<div class="cards">{cards}</div>
<h2>Chapter A metric coverage</h2>
<div class="cards">{"".join(metric_cards)}</div>
<div class="grid">{charts}</div>
</body></html>'''


def m2_targets(scenarios: list[Scenario], audio_seconds: float) -> dict[str, Any]:
    """BTC M2 volume targets this dataset is generated for (config/settings.yaml generation.*)."""
    generation = load_settings()["generation"]
    channels: dict[str, set[str]] = {}
    for s in scenarios:
        for _, call in s.ordered_calls():
            channels.setdefault(call.speaker_customer_id or s.customer_id or s.customer_phone, set()).add(call.channel)
    multi = sum(len(found) >= 2 for found in channels.values())
    hours = round(audio_seconds / 3600, 2)
    return {"multi_channel_customers": {"current": multi, "required": generation["multi_channel_customers_target"],
                                        "ok": multi >= generation["multi_channel_customers_target"]},
            "audio_hours": {"current": hours, "required": generation["audio_hours_target"],
                            "ok": hours >= generation["audio_hours_target"]}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=REPORTS_DIR / "dataset_statistics.json")
    args = parser.parse_args()

    dataset = Dataset()
    scenarios = list(dataset.iter_scenarios())
    summary, counters = coverage(scenarios)
    voices = Counter()
    audio_meta = sorted(AUDIO_DIR.glob("scenarios_*/call_*/turn_*.json"))
    for path in audio_meta:
        try:
            voice = json.loads(path.read_text(encoding="utf-8")).get("voice_id")
        except (OSError, json.JSONDecodeError):
            continue
        if voice:
            voices[voice] += 1
    counters["voice_id"] = voices
    golden = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8")) if GOLDEN_MANIFEST.exists() else {}
    audio_seconds = 0.0
    for path in audio_meta:
        try:
            audio_seconds += float(json.loads(path.read_text(encoding="utf-8")).get("duration_seconds") or 0)
        except (OSError, ValueError):
            continue

    stats = {
        "totals": {
            "scenarios": len(scenarios), "calls": summary["calls"], "customer_turns": summary["customer_turns"],
            "conversations": len(dataset.conversation_paths()),
            "audio_turns": len(list(AUDIO_DIR.glob("scenarios_*/call_*/turn_*.wav"))),
            "golden_conversations": len(golden.get("conversation_ids", [])),
        },
        "m2_targets": m2_targets(scenarios, audio_seconds),
        "metric_coverage": summary["metric_coverage"],
        "reference_scores": reference_scores(),
        **{key: dict(counter) for key, counter in counters.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    csv_dir = args.output.parent / "dataset_statistics"
    csv_dir.mkdir(parents=True, exist_ok=True)
    for key, counter in counters.items():
        with (csv_dir / f"{key}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["value", "count"])
            writer.writerows(counter.most_common())

    dashboard = args.output.parent / "dataset_dashboard.html"
    dashboard.write_text(render(stats, counters), encoding="utf-8")
    print(args.output)
    print(dashboard)


if __name__ == "__main__":
    main()
