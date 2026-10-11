"""Render the data-generation report as a self-contained HTML page with charts.

No external assets: plain HTML/CSS bars, a tiny hover-tooltip script, light and
dark palettes, and a data table behind every chart (``<details>``), so values are
never conveyed by color or bar length alone.

Chart choices: progress toward a target → meter; magnitude per category →
single-hue horizontal bars; part-to-whole (noise per channel) → stacked bar with
legend; ordered stages (review funnel) → bars in pipeline order.
"""
from __future__ import annotations

import html
from typing import Any, Iterable

CSS = """
.viz-root{color-scheme:light;--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
 --grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--gray:#b5b3ab;
 --good:#0ca30c;--good-text:#006300;--warn:#fab219}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;--surface:#1a1a19;
 --page:#0d0d0d;--ink:#f0efec;--ink-2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--gray:#5c5b57;--good-text:#0ca30c}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink-2:#c3c2b7;
 --grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--gray:#5c5b57;--good-text:#0ca30c}
body.viz-root{margin:0;min-height:100vh;font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;
 color:var(--ink);background:var(--page)}
.wrap{max-width:1200px;margin:0 auto;padding:28px 16px 48px}
h1{font-size:26px;margin:0 0 4px} h2{font-size:18px;margin:32px 0 12px} h3{font-size:14px;margin:0 0 10px}
.sub{color:var(--ink-2);margin:0 0 18px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi,.panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.kpi b{display:block;font-size:28px;font-weight:650}.kpi span{color:var(--ink-2);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:16px}
.row{display:grid;grid-template-columns:minmax(0,190px) 1fr minmax(64px,auto);gap:10px;align-items:center;margin:7px 0}
.row .lbl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-2)}
.row .val{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.track{position:relative;height:14px;border-left:1px solid var(--axis)}
.bar{height:100%;border-radius:0 4px 4px 0;background:var(--s1);min-width:2px}
.bar.gray{background:var(--gray)}
.row.meter{grid-template-columns:minmax(0,220px) 1fr 170px}
.meter .track{background:var(--grid);border-radius:0 4px 4px 0;border-left:none}
.meter .bar{border-radius:4px}
.stack{display:flex;height:14px;gap:2px}.stack>i{display:block;height:100%}
.stack>i:last-child{border-radius:0 4px 4px 0}
.status{font-size:12px;font-weight:600;margin-left:8px}.status.ok{color:var(--good-text)}.status.pending{color:var(--ink-2)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink-2);margin:0 0 8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.note{color:var(--ink-2);font-size:12px;margin:8px 0 0}
details{margin-top:10px;font-size:12px}summary{cursor:pointer;color:var(--ink-2)}
table{border-collapse:collapse;width:100%;margin-top:6px}td,th{text-align:left;padding:4px 6px;border-bottom:1px solid var(--grid)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);padding:6px 9px;border-radius:6px;
 font-size:12px;white-space:pre;opacity:0;transition:opacity .08s;z-index:9}
[data-tip]{cursor:default}
"""

JS = """
const tip=document.getElementById('tip');
document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');
 if(!t){tip.style.opacity=0;return}
 tip.textContent=t.dataset.tip;tip.style.opacity=1;
 const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8),y=Math.min(e.clientY+14,innerHeight-tip.offsetHeight-8);
 tip.style.left=x+'px';tip.style.top=y+'px'});
"""


# Color follows the channel, never its rank: fixed slot per channel.
CHANNEL_COLORS = [("hotline", "--s1"), ("zalo_oa", "--s2"), ("chat_fanpage", "--s3"), ("unknown", "--gray")]
GENDER_COLORS = [("female", "--s3"), ("male", "--s2"), ("unknown", "--gray")]


def _e(value: Any) -> str:
    return html.escape(str(value))


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:,}" if isinstance(value, int) else str(value)


def _table(headers: list[str], rows: Iterable[list[Any]], numeric_from: int = 1) -> str:
    head = "".join(f'<th class="{"n" if i >= numeric_from else ""}">{_e(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td class="{"n" if i >= numeric_from else ""}">{_e(_fmt(c))}</td>'
                                    for i, c in enumerate(row)) + "</tr>" for row in rows)
    return f'<details><summary>Show data</summary><div class="scroll"><table><tr>{head}</tr>{body}</table></div></details>'


def bars(title: str, items: list[tuple[str, float, str]], *, gray: set[str] = frozenset(), note: str = "",
         headers: tuple[str, str] = ("Category", "Value")) -> str:
    """Single-hue horizontal bars. ``items`` = (label, value, display text)."""
    if not items:
        return f'<div class="panel"><h3>{_e(title)}</h3><p class="note">No data yet.</p></div>'
    peak = max(value for _, value, _ in items) or 1
    rows = "".join(
        f'<div class="row"><span class="lbl" title="{_e(label)}">{_e(label)}</span>'
        f'<div class="track"><div class="bar{" gray" if label in gray else ""}" style="width:{value / peak * 100:.1f}%"'
        f' data-tip="{_e(label)}: {_e(text)}"></div></div><span class="val">{_e(text)}</span></div>'
        for label, value, text in items)
    note_html = f'<p class="note">{_e(note)}</p>' if note else ""
    return (f'<div class="panel"><h3>{_e(title)}</h3>{rows}{note_html}'
            f'{_table(list(headers), [[label, text] for label, _, text in items])}</div>')


def meters(title: str, targets: list[dict[str, Any]]) -> str:
    """Progress toward each M2 target; the track end is the requirement."""
    rows = []
    for t in targets:
        ratio = min(t["ratio"], 1.0)
        status = ('<span class="status ok">✓ PASS</span>' if t["ok"] else '<span class="status pending">○ PENDING</span>')
        rows.append(
            f'<div class="row meter"><span class="lbl" title="{_e(t["name"])}">{_e(t["name"])}</span>'
            f'<div class="track"><div class="bar" style="width:{ratio * 100:.1f}%" '
            f'data-tip="{_e(t["name"])}\n{_e(t["current"])} of {_e(t["required"])} ({t["ratio"]:.0%})"></div></div>'
            f'<span class="val">{_e(t["current"])} / {_e(t["required"])}{status}</span></div>')
    table = _table(["Target", "Required", "Current", "Progress", "Status"],
                   [[t["name"], t["required"], t["current"], f'{t["ratio"]:.0%}', "PASS" if t["ok"] else "PENDING"]
                    for t in targets])
    return f'<div class="panel"><h3>{_e(title)}</h3>{"".join(rows)}{table}</div>'


def stacked(title: str, rows: list[tuple[str, list[tuple[str, int]]]], series: list[tuple[str, str]],
            note: str = "") -> str:
    """Part-to-whole per row. ``series`` = (name, css color var) in fixed order."""
    if not rows:
        return f'<div class="panel"><h3>{_e(title)}</h3><p class="note">No data yet.</p></div>'
    legend = "".join(f'<span><i style="background:var({color})"></i>{_e(name)}</span>' for name, color in series)
    peak = max(sum(v for _, v in parts) for _, parts in rows) or 1
    colors = dict(series)
    body = []
    for label, parts in rows:
        total = sum(v for _, v in parts)
        segs = "".join(f'<i style="width:{v / peak * 100:.1f}%;background:var({colors[name]})" '
                       f'data-tip="{_e(label)} · {_e(name)}: {v} of {total}"></i>' for name, v in parts if v)
        body.append(f'<div class="row"><span class="lbl">{_e(label)}</span><div class="track"><div class="stack">{segs}</div>'
                    f'</div><span class="val">{total}</span></div>')
    table = _table(["Row", *[name for name, _ in series], "Total"],
                   [[label, *[dict(parts).get(name, 0) for name, _ in series], sum(v for _, v in parts)]
                    for label, parts in rows])
    note_html = f'<p class="note">{_e(note)}</p>' if note else ""
    return f'<div class="panel"><h3>{_e(title)}</h3><div class="legend">{legend}</div>{"".join(body)}{note_html}{table}</div>'


def render(ctx: dict[str, Any]) -> str:
    audio = ctx["audio"]
    ov, noise = audio["overview"], audio["noise_summary"]
    kpis = "".join(f'<div class="kpi"><b>{_e(_fmt(v))}</b><span>{_e(k)}</span></div>' for k, v in ctx["kpis"].items())

    cov = ctx["coverage"]
    coverage = bars("Labelled calls per Chapter A metric",
                    [(name, item["calls"], f'{item["calls"]} calls · {item["labels"]} labels') for name, item in cov.items()],
                    note="Reference transcript scores (target CCR 1 · RQR 0 · TSR 1 · HR 0 · over-escalation 0): "
                         + " · ".join(f'{n} {item["reference"]}' for n, item in cov.items()),
                    headers=("Metric", "Calls · labels"))
    off = ctx["official"]
    metric_keys = ("RQR", "CCR", "TSR", "TSR_hard_cases", "HR", "HR_price_promo", "guardrail_violations")
    official_rows = [[name, *[off[name].get(k) for k in metric_keys]] for name in ("oracle", "reference") if off.get(name)]
    official = (f'<div class="panel"><h3>Official reference_eval scores{" — plan preview" if off.get("preview") else ""}</h3>'
                f'<p class="note">Oracle = ideal agent built from the labels; it must be perfect '
                f'(RQR 0 · CCR 100 · TSR 100 · HR 0 · 0 violations). Oracle perfect: <b>{_e(off.get("oracle_perfect"))}</b></p>'
                + (_table(["Trace", *metric_keys], official_rows).replace("<details>", "<details open>") if official_rows
                   else '<p class="note">Run build_ground_truth.</p>') + '</div>')
    ts = ctx["test_set"]
    hard = bars(f'Hard cases in test set ({ts["n_hard_cases"]}/{ts["n_scenarios"]} scenarios)',
                [(k, v, str(v)) for k, v in ts["hard_cases"].items()], headers=("Hard case", "Scenarios"))
    rag = ctx.get("rag")
    rag_keys = ("recall@3", "recall@5", "multi_hop_full_recall@5", "abstain_rate_unanswerable",
                "abstain_rate_restricted", "false_abstain_rate")
    rag_panel = (bars("RAG recall & abstain (%)", [(k, rag[k] or 0, f"{rag[k]}%") for k in rag_keys],
                      note=rag["method"], headers=("Metric", "%")) if rag else bars("RAG recall & abstain (%)", []))
    tools = ctx.get("tools") or {}
    tool_rows = [(t["tool"] + ("" if t["official"] else " (not BTC)"), t["used"].get("oracle_trace", 0),
                  str(t["used"].get("oracle_trace", 0))) for t in tools.get("tools", [])]
    tool_panel = bars("Tool calls in oracle trace", tool_rows,
                      note="Not in BTC set: " + (", ".join(tools.get("not_in_btc", [])) or "none"),
                      headers=("Tool", "Calls"))
    funnel = bars("Review funnel (reference transcripts)", [(s, n, _fmt(n)) for s, n in ctx["funnel"]],
                  headers=("Stage", "Conversations"))
    sim = ctx["simulator"]
    sim_note = (f'TSR across seeds {sim["tsr_mean"]:.1f} ± {sim["tsr_std"]:.1f} points '
                f'(BTC tolerance ≤ {sim["max_std"]})' if sim["tsr_mean"] is not None else "No v2 replays yet.")
    simulator = bars("Simulator TSR per seed (%)", [(f"seed {s}", v, f"{v:.1f}%") for s, v in sim["per_seed"].items()],
                     note=sim_note, headers=("Seed", "TSR"))

    noise_types = bars("Audio turns by noise type",
                       [(k, v["turns"], f'{v["turns"]} turns · {v["minutes"]} min') for k, v in noise["by_type"].items()],
                       gray={"unknown"}, headers=("Noise", "Turns · minutes"),
                       note=f'Noisy turns {noise["noisy_turns"]}/{noise["noise_known_turns"]} with known status; '
                            f'calls with ≥1 noisy turn {noise["noisy_calls"]}/{ov["calls"]}. Gray = no TTS metadata.')

    def mix(group: dict[str, dict]) -> list[tuple[str, list[tuple[str, int]]]]:
        rows = []
        for key, v in group.items():
            types = v["noise_types"]
            rows.append((key, [("noisy", v["noisy_turns"]), ("clean", types.get("clean", 0)),
                               ("unknown", types.get("unknown", 0))]))
        return rows

    series = [("noisy", "--s2"), ("clean", "--s1"), ("unknown", "--gray")]
    by_channel = stacked("Audio turns by channel and noise", mix(audio["by_channel"]), series)
    by_mode = stacked("Audio turns by input mode and noise", mix(audio["by_input_mode"]), series)
    voice_rows = [(region, [(gender, values["voices"])
                            for gender, values in sorted(genders.items())])
                  for region, genders in sorted(audio["by_region_gender"].items())]
    voices = stacked("Distinct voices by region and gender", voice_rows,
                     GENDER_COLORS,
                     note="Counts are distinct customer voice IDs; gender is inferred from CRM honorific.")
    dist = bars("Customers by number of audio calls",
                [(f"{k} call{'s' if k != '1' else ''}", v, f"{v} customers")
                 for k, v in audio["calls_per_customer_distribution"].items()], headers=("Audio calls", "Customers"))
    top = audio["by_customer"][:20]
    customers = stacked(
        "Audio calls per customer (top 20, by channel)",
        [(f'{c["customer_id"]} {c["customer_name"] or ""}'.strip(), sorted(c["channels"].items())) for c in top],
        [(name, var) for name, var in CHANNEL_COLORS if any(name in c["channels"] for c in top)],
        note=f'{ov["customers"]} customers in total; full list in audio_by_customer.csv.')

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Data generation report</title>
<style>{CSS}</style></head><body class="viz-root"><main class="wrap">
<h1>Data generation report</h1>
<p class="sub">Generated {_e(ctx["generated_at"])} · generated records are not golden until they pass rules and the judge
(or a human approves them). Companion of <code>validation_report.md</code>.</p>
<div class="kpis">{kpis}</div>
<h2>M2 volume targets</h2>{meters("Progress toward each requirement", ctx["targets"])}
<h2>Chapter A metrics &amp; quality</h2>{official}<div class="grid" style="margin-top:16px">{coverage}{hard}{funnel}{simulator}{rag_panel}{tool_panel}</div>
<h2>Audio</h2>
<p class="sub">{ov["turns"]} customer turns · {ov["calls"]} calls · {ov["customers"]} customers · {ov["hours"]:.2f} h ·
mean {ov["mean_turn_seconds"]} s/turn, {ov["mean_call_seconds"]} s/call · {ov["voices"]} voices</p>
<div class="grid">{noise_types}{by_channel}{by_mode}{voices}{dist}</div>
<div style="margin-top:16px">{customers}</div>
</main><div id="tip" role="tooltip"></div><script>{JS}</script></body></html>"""
