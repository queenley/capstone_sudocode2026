"use client";
// The weekly round's pipeline (Airflow locally, two CronJobs on EKS), block by block (admin.css, "the round's pipeline"): what ran, what runs,
// what failed, for the latest runs; an admin starts a round by hand or runs one block again (with the blocks after
// it). The API (runtime/airflow_pipeline.py, runtime/k8s_pipeline.py) checks the role and talks to the scheduler; nothing here approves a proposal
// or switches a version on, as the DAG never does.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/services/api";

type BlockState = { state: string | null; started_at: string | null; ended_at: string | null; tries: number | null };
type Run = {
  run_id: string;
  state: string | null;
  kind: string | null;
  week: string | null;
  started_at: string | null;
  ended_at: string | null;
  blocks: Record<string, BlockState>;
};
type Pipeline = {
  available: boolean;
  runner?: "airflow" | "kubernetes" | null;
  airflow_ui: string | null;
  dag_id: string;
  blocks: { id: string; label: string; detail: string }[];
  runs: Run[];
  paused: boolean | null;
  error: string | null;
  current_week: string;
};

/** Airflow's task states, as the admin reads them. */
const STATE: Record<string, string> = {
  success: "Xong",
  running: "Đang chạy",
  queued: "Đang xếp hàng",
  scheduled: "Đã lên lịch",
  up_for_reschedule: "Đang chờ, kiểm tra lại sau",
  up_for_retry: "Chờ thử lại",
  failed: "Lỗi",
  upstream_failed: "Không chạy (bước trước lỗi)",
  skipped: "Bỏ qua",
  removed: "Đã gỡ",
  deferred: "Tạm hoãn",
  restarting: "Đang chạy lại",
};
const ACTIVE = new Set(["running", "queued", "scheduled", "up_for_reschedule", "up_for_retry", "restarting", "deferred"]);

const time = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) : "";

function duration(block: BlockState): string {
  if (!block.started_at) return "";
  const end = block.ended_at ? new Date(block.ended_at).getTime() : Date.now();
  const minutes = Math.max(0, Math.round((end - new Date(block.started_at).getTime()) / 60000));
  return minutes < 60 ? `${minutes} phút` : `${Math.floor(minutes / 60)} giờ ${minutes % 60} phút`;
}

export default function ImprovementPipeline({ token, onNotice }: { token: string; onNotice: (text: string) => void }) {
  const [data, setData] = useState<Pipeline | null>(null);
  const [runId, setRunId] = useState("");
  const [week, setWeek] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const found = await api<Pipeline>("/api/developer/improvement/pipeline", token);
      setData(found);
      setWeek((current) => current || found.current_week);
    } catch (e) {
      onNotice(e instanceof Error ? e.message : "Không tải được pipeline");
    }
  }, [token, onNotice]);

  useEffect(() => {
    load();
  }, [load]);

  const run = data?.runs.find((r) => r.run_id === runId) || data?.runs[0] || null;
  const live = !!run && (ACTIVE.has(run.state || "") || Object.values(run.blocks).some((b) => ACTIVE.has(b.state || "")));

  // A run in progress is followed every 15 seconds; a finished one is not polled.
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(load, 15000);
    return () => window.clearInterval(timer);
  }, [live, load]);

  async function act(path: string, body: unknown, done: string) {
    setBusy(true);
    try {
      await api(path, token, body);
      onNotice(done);
      await load();
    } catch (e) {
      onNotice(e instanceof Error ? e.message : "Bộ lập lịch không nhận lệnh");
    } finally {
      setBusy(false);
    }
  }

  if (data === null) return <p className="sl-muted" role="status">Đang tải pipeline…</p>;
  const k8s = data.runner === "kubernetes";
  return (
    <section className="sl-panel ad-pipeline" aria-labelledby="ad-pipeline-title">
      <header className="ad-pipeline__head">
        <div>
          <h2 id="ad-pipeline-title">Pipeline cải tiến ({k8s ? "Kubernetes" : "Airflow"})</h2>
          {k8s ? (
            <p className="ad-lead">
              CronJob <code>improve-learn</code> chạy mỗi thứ Hai 02:00; <code>improve-tick</code> chạy 10:00, 16:00, 22:00
              và đo version ứng viên khi mọi đề xuất đã được duyệt. Bấm tay để chạy vòng mới ngay; mọi đề xuất vẫn chờ admin
              duyệt, không có gì tự bật.
            </p>
          ) : (
            <p className="ad-lead">
              DAG <code>{data.dag_id}</code> chạy mỗi thứ Hai 02:00. Bấm tay để chạy vòng mới hoặc chạy lại một bước; mọi đề
              xuất vẫn chờ admin duyệt, không có gì tự bật.
            </p>
          )}
        </div>
        {data.airflow_ui && (
          <a className="ad-pipeline__ui" href={data.airflow_ui} target="_blank" rel="noreferrer">Mở Airflow ↗</a>
        )}
      </header>

      {!data.available ? (
        <p className="ad-pipeline__off">
          Chưa có bộ lập lịch. Local: chạy{" "}
          <code>docker compose -f docker-compose.yml -f infra/airflow/docker-compose.airflow.yml up -d --build airflow ai-agent-service</code>{" "}
          rồi tải lại trang. EKS: CronJob trong <code>infra/kubernetes/overlays/aws-production/improve.yaml</code> và{" "}
          <code>IMPROVE_RUNNER=kubernetes</code>.
        </p>
      ) : (
        <div className="ad-pipeline__controls">
          <label>
            Tuần
            <input value={week} onChange={(e) => setWeek(e.target.value.trim())} placeholder="2026-W46" pattern="\d{4}-W\d{2}" />
          </label>
          <button
            className="sl-btn"
            disabled={busy || live}
            onClick={() => {
              if (window.confirm(`Chạy vòng cải tiến cho tuần ${week}? Bước "Đo R0 và học" gọi model và tốn phí.`))
                act("/api/developer/improvement/pipeline/runs", { week }, `Đã gửi lệnh chạy vòng ${week}.`);
            }}
          >
            {live ? "Đang có vòng chạy" : "Chạy vòng mới"}
          </button>
          {data.runs.length > 1 && (
            <label>
              Lần chạy
              <select value={run?.run_id || ""} onChange={(e) => setRunId(e.target.value)}>
                {data.runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {(r.week || r.run_id)} · {STATE[r.state || ""] || r.state} · {time(r.started_at)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button className="ad-btn-quiet" disabled={busy} onClick={load}>Làm mới</button>
        </div>
      )}
      {data.error && <p className="sl-alert" role="alert">{data.error}</p>}
      {data.paused && !run && (
        <p className="sl-muted">
          {k8s ? "CronJob improve-learn đang tạm dừng (suspend): bấm tay vẫn chạy được, lịch hằng tuần thì không."
            : "DAG đang tạm dừng: chạy tay sẽ bật lại lịch hằng tuần."}
        </p>
      )}

      <ol className="ad-flow" aria-label="Các bước của vòng cải tiến">
        {data.blocks.map((block, index) => {
          const state = run?.blocks[block.id] || null;
          const name = state?.state || "none";
          const canRerun = !!run && !live && !!state?.state && block.id !== "wait_for_review";
          return (
            <li key={block.id} className={`ad-flow__block is-${name}`}>
              <span className="ad-flow__step" aria-hidden="true">{index + 1}</span>
              <div className="ad-flow__body">
                <strong>{block.label}</strong>
                <code>{block.id}</code>
                <p>{block.detail}</p>
                <span className="ad-flow__state">
                  {state?.state ? STATE[state.state] || state.state : run ? "Chưa tới" : "Chưa chạy"}
                  {state?.started_at ? ` · ${duration(state)}` : ""}
                  {state?.tries && state.tries > 1 ? ` · lần ${state.tries}` : ""}
                </span>
                {canRerun && (
                  <button
                    className="ad-btn-quiet ad-flow__rerun"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm(`Chạy lại "${block.label}" và các bước sau nó?`))
                        act(`/api/developer/improvement/pipeline/runs/${encodeURIComponent(run!.run_id)}/blocks/${block.id}/rerun`, {},
                          `Đã gửi lệnh chạy lại ${block.label}.`);
                    }}
                  >
                    Chạy lại từ đây
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {run && (
        <p className="sl-muted ad-pipeline__meta">
          Lần chạy <code>{run.run_id}</code>
          {run.kind === "manual" ? " (chạy tay)" : run.kind === "scheduled" ? " (theo lịch)" : ""}
          {run.started_at ? ` · bắt đầu ${time(run.started_at)}` : ""}
          {live ? " · tự cập nhật mỗi 15 giây" : ""}
        </p>
      )}
    </section>
  );
}
