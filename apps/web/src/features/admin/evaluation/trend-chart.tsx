"use client";
// One metric week by week, one line per series, the weeks a skills version went live marked. Shared by the
// four rates and the performance figures; a percentage axis stops at 100, other units grow with their values.
import { useState } from "react";
import { format, Round, Run, Unit } from "./model";

const W = 520;
const H = 240;
const PAD = { top: 16, right: 72, bottom: 28, left: 48 };

/** A round top for the y axis and its step: a rate near 3% must not lie flat on a 0–100% axis. */
export function niceScale(max: number, capAt100 = true): { top: number; step: number } {
  const target = Math.max(max * 1.15, capAt100 ? 1 : 1e-6) / 4;
  const power = 10 ** Math.floor(Math.log10(target));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= target) || 10 * power;
  const top = Math.ceil((max * 1.15) / step) * step || step * 4;
  return { top: capAt100 ? Math.min(100, top) : top, step };
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

export type Series = { key: string; label: string; color: string; values: (number | undefined)[] };

export default function TrendChart({
  title,
  better,
  unit,
  points,
  series: all,
  switches,
}: {
  title: string;
  better: "cao" | "thấp";
  unit: Unit;
  points: Run[];
  series: Series[];
  switches: Round[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const series = all.filter((s) => s.values.some((v) => v != null));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (points.length <= 1 ? innerW / 2 : (i * innerW) / (points.length - 1));
  const highest = Math.max(0, ...series.flatMap((s) => s.values.filter((v): v is number => v != null)));
  const { top, step } = niceScale(highest, unit === "pct");
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, k) => +(k * step).toFixed(8));
  const y = (v: number) => PAD.top + innerH - (Math.max(0, Math.min(top, v)) / top) * innerH;
  const weeks = points.map((p) => p.week);
  const ends = series.map((s) => {
    const i = s.values.map((v, k) => (v == null ? -1 : k)).filter((k) => k >= 0).pop() ?? 0;
    return { i, value: s.values[i] as number };
  });
  const labelY = spread(ends.map((e) => y(e.value) + 4));

  return (
    <figure className="sl-panel ad-chart" aria-label={title}>
      <figcaption>
        <strong>{title}</strong>
        <span className="sl-muted">càng {better} càng tốt</span>
      </figcaption>
      {series.length > 1 && (
        <ul className="ad-legend" aria-label="Chú giải">
          {series.map((s) => (
            <li key={s.key}>
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
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title} theo tuần`}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="ad-grid" />
                <text x={PAD.left - 6} y={y(t) + 4} className="ad-tick" textAnchor="end">
                  {unit === "pct" ? `${t}%` : format(t, unit)}
                </text>
              </g>
            ))}
            {weeks.map((w, i) =>
              points.length <= 6 || i % Math.ceil(points.length / 6) === 0 || i === points.length - 1 ? (
                <text key={`${w}-${i}`} x={x(i)} y={H - 8} className="ad-tick" textAnchor="middle">
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
                <g key={s.key}>
                  <path d={path} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" />
                  {coords.map((c, i) =>
                    c ? <circle key={i} cx={c[0]} cy={c[1]} r={4} fill={s.color} className="ad-dot" /> : null,
                  )}
                  <text x={x(ends[n].i) + 8} y={labelY[n]} className="ad-label">
                    {format(ends[n].value, unit)}
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
                aria-label={`Tuần ${p.week}: ${series.map((s) => `${s.label} ${format(s.values[i], unit)}`).join(", ")}`}
              />
            ))}
          </svg>
          {hover != null && (
            <div className="ad-tooltip" role="status" style={{ left: `${(x(hover) / W) * 100}%` }}>
              <strong>Tuần {points[hover].week}</strong>
              {series.map((s) => (
                <span key={s.key}>
                  <i className="ad-swatch" style={{ background: s.color }} aria-hidden /> {s.label}: {format(s.values[hover], unit)}
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
