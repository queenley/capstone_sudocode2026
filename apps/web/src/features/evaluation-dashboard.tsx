"use client";
// The evaluation history, week by week: the organisers' four rates of each scored run that `run_eval.py --ingest`
// kept, with the weeks a skills version went live marked. docs/plan/001, part D.
//
// Only runs of one cohort (same scenario files) and one extractor are drawn together: numbers of different cohorts
// or extractors are not comparable (evaluation/README.md), so the cohort is a filter, never a mixed line.
// One small chart per rate: TSR and CCR are better high, RQR and HR better low, so they never share an axis.
import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";

type Run = {
  run_id: string;
  purpose: string;
  week: string;
  started_at: string;
  cohort_sha256: string | null;
  n_scenarios: number | null;
  extractor_version: string | null;
  advisor_model: string | null;
  profile: string;
  skills_version: number | null;
  kb_version: number | null;
  metrics: Record<string, Record<string, number>>;
};
type Round = { name: string; week: string; status: string; candidate_skills_version: number | null };

const PURPOSE: Record<string, string> = {
  weekly_frozen: "Hằng tuần, version đang chạy (R0)",
  weekly_candidate: "Hằng tuần, version ứng viên (R1)",
  dev_full: "Toàn bộ data/dev",
  adhoc: "Chạy tay",
};
const RATES: { id: string; title: string; better: "cao" | "thấp" }[] = [
  { id: "TSR", title: "Task Success Rate (TSR)", better: "cao" },
  { id: "CCR", title: "Context Carryover Rate (CCR)", better: "cao" },
  { id: "RQR", title: "Repeat-Question Rate (RQR)", better: "thấp" },
  { id: "HR", title: "Hallucination Rate (HR, giá & KM)", better: "thấp" },
];
const SERIES = [
  { config: "full", label: "Có bộ nhớ (full)", color: "var(--ad-series-1)" },
  { config: "baseline_no_memory", label: "Không bộ nhớ (baseline)", color: "var(--ad-series-2)" },
];

const cohortKey = (r: Run) => `${r.cohort_sha256 || "?"}|${r.extractor_version || "?"}`;
const pct = (v: number | undefined) => (v == null ? "chưa đo" : `${v.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}%`);

export default function EvaluationDashboard({ token, onNotice }: { token: string; onNotice: (text: string) => void }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [purpose, setPurpose] = useState("");
  const [cohort, setCohort] = useState("");
  const [asTable, setAsTable] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const found = await api<{ runs: Run[] }>("/api/developer/evaluations", token);
        setRuns(found.runs);
        try {
          setRounds((await api<{ rounds: Round[] }>("/api/developer/improvement/rounds", token)).rounds);
        } catch {
          setRounds([]);
        }
      } catch (e) {
        setRuns([]);
        onNotice(e instanceof Error ? e.message : "Không tải được lịch sử đánh giá");
      }
    })();
  }, [token, onNotice]);

  const purposes = useMemo(() => [...new Set((runs || []).map((r) => r.purpose))], [runs]);
  const chosenPurpose = purpose || (purposes.includes("weekly_frozen") ? "weekly_frozen" : purposes[0] || "");
  const ofPurpose = useMemo(() => (runs || []).filter((r) => r.purpose === chosenPurpose), [runs, chosenPurpose]);
  const cohorts = useMemo(() => {
    const seen = new Map<string, Run>();
    for (const r of ofPurpose) seen.set(cohortKey(r), r); // the latest run of each cohort describes it
    return [...seen.entries()];
  }, [ofPurpose]);
  const chosenCohort = cohort && cohorts.some(([k]) => k === cohort) ? cohort : cohorts[cohorts.length - 1]?.[0] || "";
  // One point a week: the latest run of that week in the chosen cohort.
  const points = useMemo(() => {
    const byWeek = new Map<string, Run>();
    for (const r of ofPurpose.filter((r) => cohortKey(r) === chosenCohort)) byWeek.set(r.week, r);
    return [...byWeek.values()].sort((a, b) => a.week.localeCompare(b.week));
  }, [ofPurpose, chosenCohort]);
  const switches = rounds.filter((r) => r.status === "active" && r.candidate_skills_version != null);

  if (runs === null) return <p className="sl-muted" role="status">Đang tải…</p>;
  if (runs.length === 0)
    return (
      <p className="sl-muted">
        Chưa có run nào trong lịch sử. Sau mỗi run đã chấm, chạy{" "}
        <code>python run_eval.py --ingest evaluation/runs/&lt;tên&gt; --purpose dev_full</code>; vòng hằng tuần tự
        ingest.
      </p>
    );
  return (
    <div className="ad-stack">
      <div className="ad-filters" role="group" aria-label="Lọc lịch sử đánh giá">
        <label>
          Loại run
          <select value={chosenPurpose} onChange={(e) => setPurpose(e.target.value)}>
            {purposes.map((p) => (
              <option key={p} value={p}>
                {PURPOSE[p] || p}
              </option>
            ))}
          </select>
        </label>
        <label>
          Bộ kịch bản và extractor
          <select value={chosenCohort} onChange={(e) => setCohort(e.target.value)}>
            {cohorts.map(([key, r]) => (
              <option key={key} value={key}>
                {r.n_scenarios ?? "?"} kịch bản · {r.extractor_version || "extractor ?"} · {(r.cohort_sha256 || "?").slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <button className="sl-btn sl-btn-small" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          {asTable ? "Xem biểu đồ" : "Xem bảng"}
        </button>
      </div>
      {cohorts.length > 1 && (
        <p className="sl-muted">
          Có {cohorts.length} bộ kịch bản/extractor khác nhau: mỗi lần chỉ vẽ một bộ, vì số của hai bộ không so được.
        </p>
      )}
      {asTable ? (
        <RunTable points={points} />
      ) : (
        <div className="ad-charts">
          {RATES.map((rate) => (
            <RateChart key={rate.id} rate={rate} points={points} switches={switches} />
          ))}
        </div>
      )}
    </div>
  );
}

// The viewBox is near a chart card's width on a desktop, so ticks print close to their CSS size.
const W = 520;
const H = 240;
const PAD = { top: 16, right: 64, bottom: 28, left: 40 };

/** A round top for the y axis and its step: a rate near 3% must not lie flat on a 0–100% axis. */
export function niceScale(max: number): { top: number; step: number } {
  const target = Math.max(max * 1.15, 1) / 4;
  const power = 10 ** Math.floor(Math.log10(target));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= target) || 10 * power;
  return { top: Math.min(100, Math.ceil((max * 1.15) / step) * step || step * 4), step };
}

/** End labels nudged apart so two close values never print on top of each other (at least *gap* px apart). */
export function spread(ys: number[], gap = 13): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  for (let k = 1; k < order.length; k++) {
    if (order[k].y - order[k - 1].y < gap) order[k].y = order[k - 1].y + gap;
  }
  const out = [...ys];
  for (const { y, i } of order) out[i] = y;
  return out;
}

function RateChart({
  rate,
  points,
  switches,
}: {
  rate: (typeof RATES)[number];
  points: Run[];
  switches: Round[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const series = SERIES.map((s) => ({
    ...s,
    values: points.map((p) => p.metrics?.[s.config]?.[rate.id]),
  })).filter((s) => s.values.some((v) => v != null));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (points.length <= 1 ? innerW / 2 : (i * innerW) / (points.length - 1));
  const highest = Math.max(0, ...series.flatMap((s) => s.values.filter((v): v is number => v != null)));
  const { top, step } = niceScale(highest);
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, k) => +(k * step).toFixed(4));
  const y = (v: number) => PAD.top + innerH - (Math.max(0, Math.min(top, v)) / top) * innerH;
  const weeks = points.map((p) => p.week);
  // Where each series' last value is labelled, apart from the others'.
  const ends = series.map((s) => {
    const i = s.values.map((v, k) => (v == null ? -1 : k)).filter((k) => k >= 0).pop() ?? 0;
    return { i, value: s.values[i] as number };
  });
  const labelY = spread(ends.map((e) => y(e.value) + 4));

  return (
    <figure className="sl-panel ad-chart" aria-label={rate.title}>
      <figcaption>
        <strong>{rate.title}</strong>
        <span className="sl-muted">càng {rate.better} càng tốt</span>
      </figcaption>
      {series.length > 1 && (
        <ul className="ad-legend" aria-label="Chú giải">
          {series.map((s) => (
            <li key={s.config}>
              <span className="ad-swatch" style={{ background: s.color }} aria-hidden />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      {points.length === 0 || series.length === 0 ? (
        <p className="sl-muted">Chưa đo.</p>
      ) : (
        <div className="ad-plot">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${rate.title} theo tuần`}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="ad-grid" />
                <text x={PAD.left - 6} y={y(t) + 4} className="ad-tick" textAnchor="end">
                  {t}%
                </text>
              </g>
            ))}
            {weeks.map((w, i) =>
              points.length <= 6 || i % Math.ceil(points.length / 6) === 0 || i === points.length - 1 ? (
                <text key={w} x={x(i)} y={H - 8} className="ad-tick" textAnchor="middle">
                  {w.slice(5)}
                </text>
              ) : null,
            )}
            {switches.map((s) => {
              const i = weeks.indexOf(s.week);
              if (i < 0) return null;
              return (
                <g key={s.name}>
                  <line x1={x(i)} x2={x(i)} y1={PAD.top} y2={PAD.top + innerH} className="ad-marker" />
                  <text x={x(i) + 3} y={PAD.top + 10} className="ad-tick">
                    skills v{s.candidate_skills_version}
                  </text>
                </g>
              );
            })}
            {series.map((s, n) => {
              const coords = s.values.map((v, i) => (v == null ? null : ([x(i), y(v)] as const)));
              const path = coords
                .map((c, i) => (c ? `${i === 0 || !coords[i - 1] ? "M" : "L"}${c[0]},${c[1]}` : ""))
                .join(" ");
              return (
                <g key={s.config}>
                  <path d={path} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" />
                  {coords.map((c, i) =>
                    c ? (
                      <circle key={i} cx={c[0]} cy={c[1]} r={4} fill={s.color} className="ad-dot" />
                    ) : null,
                  )}
                  <text x={x(ends[n].i) + 8} y={labelY[n]} className="ad-label">
                    {pct(ends[n].value)}
                  </text>
                </g>
              );
            })}
            {hover != null && (
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} className="ad-crosshair" />
            )}
            {points.map((p, i) => (
              <rect
                key={p.run_id}
                x={x(i) - (points.length <= 1 ? innerW / 2 : innerW / (points.length - 1) / 2)}
                y={PAD.top}
                width={points.length <= 1 ? innerW : innerW / (points.length - 1)}
                height={innerH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                aria-label={`Tuần ${p.week}: ${series.map((s) => `${s.label} ${pct(s.values[i])}`).join(", ")}`}
              />
            ))}
          </svg>
          {hover != null && (
            <div
              className="ad-tooltip"
              role="status"
              style={{ left: `${(x(hover) / W) * 100}%` }}
            >
              <strong>Tuần {points[hover].week}</strong>
              {series.map((s) => (
                <span key={s.config}>
                  <i className="ad-swatch" style={{ background: s.color }} aria-hidden /> {s.label}: {pct(s.values[hover])}
                </span>
              ))}
              <small>
                skills v{points[hover].skills_version ?? "đang chạy"} · {points[hover].advisor_model || "model ?"}
              </small>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}

function RunTable({ points }: { points: Run[] }) {
  return (
    <table className="sl-table" aria-label="Lịch sử đánh giá">
      <thead>
        <tr>
          <th>Tuần</th>
          <th>Run</th>
          <th>Skills</th>
          {RATES.map((r) => (
            <th key={r.id}>{r.id} full / baseline</th>
          ))}
          <th>TTFT p95</th>
          <th>Chi phí mỗi lượt</th>
        </tr>
      </thead>
      <tbody>
        {points.map((p) => (
          <tr key={p.run_id}>
            <td>{p.week}</td>
            <td>
              <code>{p.run_id}</code>
            </td>
            <td>{p.skills_version ?? "đang chạy"}</td>
            {RATES.map((r) => (
              <td key={r.id}>
                {pct(p.metrics?.full?.[r.id])} / {pct(p.metrics?.baseline_no_memory?.[r.id])}
              </td>
            ))}
            <td>
              {p.metrics?.full?.ttft_p95_ms != null ? `${(p.metrics.full.ttft_p95_ms / 1000).toFixed(2)} s` : "chưa đo"}
            </td>
            <td>
              {p.metrics?.full?.cost_per_turn_usd != null ? `$${p.metrics.full.cost_per_turn_usd.toFixed(5)}` : "chưa đo"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
