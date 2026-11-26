"use client";
// The dashboard's tabs over one cohort's runs: the four rates, performance, quality and a comparison of two runs.
import { useState } from "react";
import TrendChart from "./trend-chart";
import { delta, format, Metric, PERFORMANCE, QUALITY, RATES, Round, Run, SERIES, value, verdict } from "./model";

const latest = (points: Run[]) => points[points.length - 1];

/** The latest run's headline numbers as tiles: what a person reads first. */
function Tiles({ run, metrics }: { run: Run | undefined; metrics: Metric[] }) {
  return (
    <div className="sl-kpis ad-tiles">
      {metrics.map((m) => (
        <div className="sl-kpi" key={m.id}>
          <span className="sl-muted">{m.title}</span>
          <strong>{format(value(run, m), m.unit)}</strong>
          <small className="sl-muted">càng {m.better} càng tốt</small>
        </div>
      ))}
    </div>
  );
}

export function Overview({ points, switches, asTable }: { points: Run[]; switches: Round[]; asTable: boolean }) {
  if (asTable) return <RunTable points={points} />;
  return (
    <div className="ad-charts">
      {RATES.map((rate) => (
        <TrendChart
          key={rate.id}
          title={rate.title}
          better={rate.better}
          unit="pct"
          points={points}
          switches={switches}
          series={SERIES.map((s) => ({ key: s.config, label: s.label, color: s.color, values: points.map((p) => value(p, rate, s.config)) }))}
        />
      ))}
    </div>
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
                {format(value(p, r, "full"), "pct")} / {format(value(p, r, "baseline_no_memory"), "pct")}
              </td>
            ))}
            <td>{format(p.metrics?.full?.ttft_p95_ms, "ms")}</td>
            <td>{format(p.metrics?.full?.cost_per_turn_usd, "usd")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Latency, tokens and cost of the full configuration, two figures per chart (p50 and p95, or without and with
    the after-call work). */
const PAIRS: { title: string; better: "thấp" | "cao"; unit: Metric["unit"]; a: [string, string]; b: [string, string] }[] = [
  { title: "Thời gian tới chữ đầu tiên (TTFT)", better: "thấp", unit: "ms", a: ["ttft_p50_ms", "p50"], b: ["ttft_p95_ms", "p95"] },
  { title: "Thời gian trả lời trọn lượt", better: "thấp", unit: "ms", a: ["total_p50_ms", "p50"], b: ["total_p95_ms", "p95"] },
  { title: "Token mỗi lượt", better: "thấp", unit: "tokens", a: ["tokens_per_turn", "chỉ lượt"], b: ["tokens_per_turn_with_after_call", "kể cả after_call"] },
  { title: "Chi phí mỗi lượt", better: "thấp", unit: "usd", a: ["cost_per_turn_usd", "chỉ lượt"], b: ["cost_per_turn_with_after_call_usd", "kể cả after_call"] },
];

export function Performance({ points, switches }: { points: Run[]; switches: Round[] }) {
  const run = latest(points);
  return (
    <div className="ad-stack">
      <p className="sl-muted">
        Số của run gần nhất ({run?.run_id || "chưa có"}), cấu hình có bộ nhớ. Chi phí chỉ hiện khi model advisor có trong
        bảng giá.
      </p>
      <Tiles run={run} metrics={PERFORMANCE.filter((m) => ["ttft_p95_ms", "total_p95_ms", "tokens_per_turn_with_after_call", "cost_per_turn_with_after_call_usd", "cached_share"].includes(m.id))} />
      <div className="ad-charts">
        {PAIRS.map((pair) => (
          <TrendChart
            key={pair.title}
            title={pair.title}
            better={pair.better}
            unit={pair.unit}
            points={points}
            switches={switches}
            series={[pair.a, pair.b].map(([id, label], k) => ({
              key: id,
              label,
              color: SERIES[k].color,
              values: points.map((p) => p.metrics?.full?.[id]),
            }))}
          />
        ))}
      </div>
    </div>
  );
}

export function Quality({ points }: { points: Run[] }) {
  const run = latest(points);
  const shown = QUALITY.filter((m) => points.some((p) => value(p, m) != null));
  return (
    <div className="ad-stack">
      <Tiles run={run} metrics={QUALITY.filter((m) => ["TSR_hard_cases", "guardrail_violations", "failed_turns", "after_call_failed"].includes(m.id))} />
      {shown.length === 0 ? (
        <p className="sl-muted">Các run này được ingest trước khi có số chất lượng: ingest lại để xem.</p>
      ) : (
        <div className="ad-scroll">
          <table className="sl-table ad-quality" aria-label="Chất lượng theo run">
            <thead>
              <tr>
                <th scope="col">Chỉ số (full)</th>
                {points.map((p) => (
                  <th scope="col" key={p.run_id}>
                    {p.week}
                    <br />
                    <small className="sl-muted">{p.run_id.slice(0, 15)}</small>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((m) => (
                <tr key={m.id}>
                  <th scope="row">{m.title}</th>
                  {points.map((p) => {
                    const v = value(p, m);
                    const bad = m.unit === "count" && v != null && v > 0;
                    return (
                      <td key={p.run_id} className={bad ? "ad-bad" : v === 0 ? "sl-muted" : undefined}>
                        {format(v, m.unit)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function Compare({ points }: { points: Run[] }) {
  const [a, setA] = useState(points.length > 1 ? points[points.length - 2].run_id : points[0]?.run_id || "");
  const [b, setB] = useState(points[points.length - 1]?.run_id || "");
  const runA = points.find((p) => p.run_id === a);
  const runB = points.find((p) => p.run_id === b);
  if (points.length < 2) return <p className="sl-muted">Cần ít nhất hai run cùng bộ kịch bản và extractor để so sánh.</p>;
  const pick = (label: string, chosen: string, set: (v: string) => void) => (
    <label>
      {label}
      <select value={chosen} onChange={(e) => set(e.target.value)}>
        {points.map((p) => (
          <option key={p.run_id} value={p.run_id}>
            {p.week} · {p.run_id} · skills v{p.skills_version ?? "đang chạy"}
          </option>
        ))}
      </select>
    </label>
  );
  const groups: [string, Metric[]][] = [
    ["Bốn chỉ số", RATES],
    ["Hiệu năng", PERFORMANCE],
    ["Chất lượng", QUALITY],
  ];
  return (
    <div className="ad-stack">
      <div className="ad-filters" role="group" aria-label="Chọn hai run">
        {pick("Run A (trước)", a, setA)}
        {pick("Run B (sau)", b, setB)}
      </div>
      <table className="sl-table ad-compare" aria-label="So sánh hai run">
        <thead>
          <tr>
            <th scope="col">Chỉ số (full)</th>
            <th scope="col">A</th>
            <th scope="col">B</th>
            <th scope="col">B so với A</th>
          </tr>
        </thead>
        {groups.map(([name, metrics]) => (
          <tbody key={name}>
            <tr className="ad-group">
              <th colSpan={4} scope="colgroup">{name}</th>
            </tr>
            {metrics
              .filter((m) => value(runA, m) != null || value(runB, m) != null)
              .map((m) => {
                const va = value(runA, m);
                const vb = value(runB, m);
                const v = verdict(m, va, vb);
                return (
                  <tr key={m.id}>
                    <th scope="row">{m.title}</th>
                    <td>{format(va, m.unit)}</td>
                    <td>{format(vb, m.unit)}</td>
                    <td className={v === "better" ? "ad-good" : v === "worse" ? "ad-bad" : "sl-muted"}>
                      {delta(m, va, vb)}
                      {v === "better" ? " · tốt hơn" : v === "worse" ? " · kém hơn" : ""}
                    </td>
                  </tr>
                );
              })}
          </tbody>
        ))}
      </table>
    </div>
  );
}
