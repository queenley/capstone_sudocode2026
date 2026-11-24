"use client";
// Router, GapLoop, Reflection and Kết hợp side by side: one column per run of the chosen kind (run_eval.py --profile,
// docs/evaluation/scoring-flow.md), as `run_eval.py --report --run router=... --run gaploop=...` prints them.
//
// Runs on different scenario files (labels changed between them) are shown together on purpose, but never compared:
// each column carries the letter of its cohort, and the best value of a row is marked only among columns of the same
// letter (evaluation/README.md: numbers compare only on the same cohort and extractor).
import { useMemo, useState } from "react";
import {
  cohortKey,
  format,
  Metric,
  PERFORMANCE,
  RATES,
  Run,
  value,
} from "./model";

const METHOD: Record<string, string> = {
  router: "Router",
  gaploop: "GapLoop",
  reflection: "Reflection",
  combined: "Kết hợp",
};
const ORDER = ["router", "gaploop", "reflection", "combined"];
const SHOWN: Metric[] = [
  ...RATES,
  ...PERFORMANCE.filter((m) =>
    [
      "ttft_p95_ms",
      "total_p95_ms",
      "tokens_per_turn",
      "cost_per_turn_usd",
    ].includes(m.id),
  ),
];

type Column = {
  key: string;
  run: Run;
  config: string;
  title: string;
  cohort: string;
};

const day = (iso: string) =>
  iso
    ? new Date(iso).toLocaleString("vi-VN", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

export default function Methods({ runs }: { runs: Run[] }) {
  const most = Math.max(0, ...runs.map((r) => r.n_scenarios || 0));
  const [onlyFull, setOnlyFull] = useState(true);
  const [withBaseline, setWithBaseline] = useState(true);

  const { columns, letters } = useMemo(() => {
    const chosen = runs
      .filter((r) => !onlyFull || (r.n_scenarios || 0) === most)
      .sort((a, b) => {
        const ia = ORDER.indexOf(a.profile),
          ib = ORDER.indexOf(b.profile);
        return (
          (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) ||
          a.started_at.localeCompare(b.started_at)
        );
      });
    // Cohorts lettered A, B, … oldest first: the same letter means the same scenario files and extractor.
    const letters = new Map<string, string>();
    for (const r of [...chosen].sort((a, b) =>
      a.started_at.localeCompare(b.started_at),
    ))
      if (!letters.has(cohortKey(r)))
        letters.set(cohortKey(r), String.fromCharCode(65 + letters.size));
    const columns: Column[] = [];
    for (const r of chosen) {
      const cohort = letters.get(cohortKey(r)) || "?";
      const title = METHOD[r.profile] || r.profile;
      if (withBaseline && r.metrics?.baseline_no_memory)
        columns.push({
          key: `${r.run_id}|b`,
          run: r,
          config: "baseline_no_memory",
          title: `${title} · không bộ nhớ`,
          cohort,
        });
      columns.push({
        key: `${r.run_id}|f`,
        run: r,
        config: "full",
        title,
        cohort,
      });
    }
    return { columns, letters };
  }, [runs, onlyFull, withBaseline, most]);

  if (runs.length === 0)
    return <p className="sl-muted">Chưa có run nào của loại này.</p>;

  /** The column(s) holding the best value of *m* among the columns of *cohort*. */
  function best(m: Metric, cohort: string): Set<string> {
    const found = columns
      .filter((c) => c.cohort === cohort)
      .map((c) => [c.key, value(c.run, m, c.config)] as const)
      .filter((pair): pair is readonly [string, number] => pair[1] != null);
    if (found.length < 2) return new Set();
    const target =
      m.better === "cao"
        ? Math.max(...found.map(([, v]) => v))
        : Math.min(...found.map(([, v]) => v));
    return new Set(
      found.filter(([, v]) => Math.abs(v - target) < 1e-9).map(([k]) => k),
    );
  }

  return (
    <div className="ad-stack">
      <div
        className="ad-filters"
        role="group"
        aria-label="Chọn run để so sánh phương pháp"
      >
        <label className="ad-check">
          <input
            type="checkbox"
            checked={onlyFull}
            onChange={(e) => setOnlyFull(e.target.checked)}
          />
          Chỉ run đủ kịch bản ({most})
        </label>
        <label className="ad-check">
          <input
            type="checkbox"
            checked={withBaseline}
            onChange={(e) => setWithBaseline(e.target.checked)}
          />
          Thêm cột không bộ nhớ (baseline)
        </label>
      </div>
      {letters.size > 1 && (
        <p className="sl-muted">
          Có {letters.size} bộ kịch bản/nhãn khác nhau (
          {[...letters.entries()]
            .map(([k, l]) => `${l}: ${k.split("|")[0].slice(0, 8)}`)
            .join(", ")}
          ). Chỉ so các cột cùng chữ; giá trị tốt nhất được tô trong từng nhóm
          chữ. Muốn so mọi cột, chấm lại các run trên cùng nhãn bằng{" "}
          <code>run_eval.py --relabel</code>.
        </p>
      )}
      <div className="ad-table-scroll">
        <table
          className="sl-table ad-compare ad-methods"
          aria-label="So sánh các phương pháp"
        >
          <thead>
            <tr>
              <th scope="col">Chỉ số</th>
              {columns.map((c) => (
                <th scope="col" key={c.key}>
                  <span className="ad-methods__name">{c.title}</span>
                  <span
                    className="ad-methods__cohort"
                    title={`Bộ kịch bản ${c.run.cohort_sha256 || "?"}`}
                  >
                    Nhãn {c.cohort}
                  </span>
                  <span className="sl-muted ad-methods__meta">
                    {day(c.run.started_at)} · {c.run.n_scenarios ?? "?"} kịch
                    bản
                    {c.run.skills_version != null
                      ? ` · skills v${c.run.skills_version}`
                      : ""}
                    {c.run.kb_version != null
                      ? ` · kb v${c.run.kb_version}`
                      : ""}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SHOWN.map((m) => {
              const winners = new Set(
                [...letters.values()].flatMap((l) => [...best(m, l)]),
              );
              return (
                <tr key={m.id}>
                  <th scope="row">
                    {m.title}{" "}
                    <span className="sl-muted">({m.better} hơn là tốt)</span>
                  </th>
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={winners.has(c.key) ? "ad-good" : undefined}
                    >
                      {format(value(c.run, m, c.config), m.unit)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
