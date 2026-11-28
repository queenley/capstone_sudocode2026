"use client";
// The evaluation history of the scored runs `run_eval.py --ingest` kept, in five tabs:
// the organisers' four rates week by week, performance (latency, tokens, cost), quality (errors, guardrails),
// a comparison of two runs, and each scenario of one run. The pieces are in ./evaluation.
//
// Only runs of one cohort (same scenario files) and one extractor are shown together: numbers of different cohorts
// or extractors are not comparable, so the cohort is a filter, never a mixed line.
import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";
import { cohortKey, PURPOSE, Round, Run } from "./evaluation/model";
import Scenarios from "./evaluation/scenarios";
import { Compare, Overview, Performance, Quality } from "./evaluation/views";

const TABS = [
  { id: "overview", label: "Bốn chỉ số" },
  { id: "performance", label: "Hiệu năng" },
  { id: "quality", label: "Chất lượng" },
  { id: "compare", label: "So sánh hai run" },
  { id: "scenarios", label: "Theo kịch bản" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export default function EvaluationDashboard({ token, onNotice }: { token: string; onNotice: (text: string) => void }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [purpose, setPurpose] = useState("");
  const [cohort, setCohort] = useState("");
  const [asTable, setAsTable] = useState(false);
  const [tab, setTab] = useState<Tab>("overview");

  useEffect(() => {
    (async () => {
      try {
        const found = await api<{ runs: Run[] }>("/api/developer/evaluations", token);
        setRuns(found?.runs ?? []);
        try {
          setRounds((await api<{ rounds: Round[] }>("/api/developer/improvement/rounds", token))?.rounds ?? []);
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
  const ofCohort = useMemo(() => ofPurpose.filter((r) => cohortKey(r) === chosenCohort), [ofPurpose, chosenCohort]);
  // One point a week: the latest run of that week in the chosen cohort.
  const points = useMemo(() => {
    const byWeek = new Map<string, Run>();
    for (const r of ofCohort) byWeek.set(r.week, r);
    return [...byWeek.values()].sort((a, b) => a.week.localeCompare(b.week));
  }, [ofCohort]);
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
        {tab === "overview" && (
          <button className="sl-btn sl-btn-small ad-btn-quiet" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
            {asTable ? "Xem biểu đồ" : "Xem bảng"}
          </button>
        )}
      </div>
      {cohorts.length > 1 && (
        <p className="sl-muted">
          Có {cohorts.length} bộ kịch bản/extractor khác nhau: mỗi lần chỉ vẽ một bộ, vì số của hai bộ không so được.
        </p>
      )}
      <div className="ad-tabs" role="tablist" aria-label="Phần của trang đánh giá">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`eval-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`eval-panel-${t.id}`}
            className={tab === t.id ? "is-active" : undefined}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`eval-panel-${tab}`} aria-labelledby={`eval-tab-${tab}`}>
        {tab === "overview" && <Overview points={points} switches={switches} asTable={asTable} />}
        {tab === "performance" && <Performance points={points} switches={switches} />}
        {tab === "quality" && <Quality points={points} />}
        {tab === "compare" && <Compare key={chosenCohort} points={ofCohort} />}
        {tab === "scenarios" && <Scenarios key={chosenCohort} points={ofCohort} token={token} />}
      </div>
    </div>
  );
}
