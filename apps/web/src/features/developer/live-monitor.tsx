"use client";
// The developer console's live view: each agent turn the moment it is stored (services/live.ts), with what it cost
// and what it did. The tiles add up the last 15 minutes (GET /api/developer/live/summary, every 15 s). A turn's
// prompt and the model's tree of calls stay in Langfuse: each row links to its session there when it is set up.
import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";
import { followTurns, LiveSummary, LiveTurn } from "@/services/live";

const KEEP = 200;
const ms = (v: number | null | undefined) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);
const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(v < 0.01 ? 5 : 3)}`);
const n = (v: number | null | undefined) => (v == null ? "—" : Math.round(v).toLocaleString("vi-VN"));
const time = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("vi-VN", { hour12: false }) : "—");
const problem = (t: LiveTurn) => !!t.error || t.fallback || !t.guard.passed || t.tools.some((x) => !x.ok);

export default function LiveMonitor({ token }: { token: string }) {
  const [turns, setTurns] = useState<LiveTurn[]>([]);
  const [summary, setSummary] = useState<LiveSummary | null>(null);
  const [state, setState] = useState<{ kind: "idle" | "connected" | "reconnecting" | "error"; detail?: string }>({ kind: "idle" });
  const [paused, setPaused] = useState(false);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  // The latest turns, then the feed from the newest one.
  useEffect(() => {
    if (!token || paused) return;
    const stop = new AbortController();
    (async () => {
      try {
        const found = await api<{ turns: LiveTurn[] }>("/api/developer/live/turns?limit=50", token, undefined, undefined, { signal: stop.signal });
        const latest = found?.turns ?? [];
        setTurns((now) => merge(now, latest));
        const after = latest.length ? Math.max(...latest.map((t) => t.id)) : null;
        await followTurns(token, after, (turn) => setTurns((now) => merge(now, [turn])),
          (kind, detail) => setState({ kind, detail }), stop.signal);
      } catch (e) {
        if (!stop.signal.aborted) setState({ kind: "error", detail: e instanceof Error ? e.message : undefined });
      }
    })();
    return () => stop.abort();
  }, [token, paused]);

  useEffect(() => {
    if (!token) return;
    let gone = false;
    const load = () =>
      api<LiveSummary>("/api/developer/live/summary?minutes=15", token)
        .then((s) => !gone && setSummary(s))
        .catch(() => undefined);
    load();
    const timer = setInterval(load, 15_000);
    return () => {
      gone = true;
      clearInterval(timer);
    };
  }, [token]);

  const shown = useMemo(() => (onlyProblems ? turns.filter(problem) : turns), [turns, onlyProblems]);
  const current = turns.find((t) => t.id === selected) || null;

  if (!token) return <p className="empty">Nhập token developer hoặc admin rồi bấm Kết nối để xem các lượt trực tiếp.</p>;
  return (
    <div className="live">
      <div className="live-bar">
        <span className={`live-state live-state--${paused ? "paused" : state.kind}`} role="status">
          <span className="status-dot" aria-hidden />
          {paused ? "Tạm dừng" : state.kind === "connected" ? "Đang nhận trực tiếp" : state.kind === "reconnecting" ? "Đang nối lại…" : state.kind === "error" ? state.detail || "Mất kết nối" : "Đang kết nối…"}
        </span>
        <button type="button" className="live-btn" onClick={() => setPaused((p) => !p)} aria-pressed={paused}>
          {paused ? "Tiếp tục" : "Tạm dừng"}
        </button>
        <label className="live-check">
          <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} /> Chỉ lượt có vấn đề
        </label>
        {summary && !summary.langfuse && (
          <span className="hint">Đặt LANGFUSE_HOST và LANGFUSE_PROJECT_ID để mở trace chi tiết của từng lượt trong Langfuse.</span>
        )}
      </div>

      <section className="console-stats live-tiles" aria-label="15 phút gần nhất">
        <Tile label="Lượt (15 phút)" value={n(summary?.turns)} hint={summary?.handoffs ? `${summary.handoffs} chuyển nhân viên` : undefined} />
        <Tile label="TTFT p50 / p95" value={`${ms(summary?.ttft_p50_ms)} / ${ms(summary?.ttft_p95_ms)}`} warn={(summary?.ttft_p95_ms ?? 0) > 3000} hint="Ngưỡng BTC 3 s" />
        <Tile label="Token mỗi lượt" value={n(summary?.tokens_per_turn)} hint={`${n(summary?.tokens_input)} vào · ${n(summary?.tokens_output)} ra`} />
        <Tile label="Chi phí 15 phút" value={usd(summary?.cost_usd)}
          hint={summary?.spend_today_usd != null ? `Hôm nay ${usd(summary.spend_today_usd)}` : "Theo giá trong config/models.yaml"} />
        <Tile label="Đang chạy" value={`${n(summary?.load?.turns)} lượt · ${n(summary?.load?.calls)} gọi thoại`}
          hint={summary?.load ? (summary.load.shared ? `${summary.load.pods} pod` : "Pod này") : undefined} />
        <Tile label="Tool lỗi" value={`${n(summary?.tool_failures)} / ${n(summary?.tool_calls)}`} warn={(summary?.tool_failures ?? 0) > 0} />
        <Tile label="Guard chặn · lỗi · dự phòng" value={`${n(summary?.guard_blocks)} · ${n(summary?.errors)} · ${n(summary?.fallbacks)}`} warn={(summary?.errors ?? 0) > 0} />
      </section>

      <div className="live-grid">
        <section className="panel live-feed" aria-label="Các lượt gần nhất">
          <div className="live-feed-head">
            <h2>Lượt của trợ lý</h2>
            <span className="hint">{shown.length} lượt, mới nhất trên cùng</span>
          </div>
          {shown.length === 0 ? (
            <p className="empty">{onlyProblems ? "Không có lượt nào có vấn đề." : "Chưa có lượt nào. Lượt mới hiện ở đây ngay khi được lưu."}</p>
          ) : (
            <div className="live-scroll">
              <table className="live-table">
                <thead>
                  <tr>
                    <th scope="col">Lúc</th>
                    <th scope="col">Cuộc gọi</th>
                    <th scope="col">Lane · model</th>
                    <th scope="col">TTFT</th>
                    <th scope="col">Token</th>
                    <th scope="col">Chi phí</th>
                    <th scope="col">Tool</th>
                    <th scope="col">Guard</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((t) => (
                    <tr key={t.id} className={`${t.id === selected ? "is-selected" : ""} ${problem(t) ? "is-problem" : ""}`}
                      tabIndex={0} onClick={() => setSelected(t.id)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setSelected(t.id)}
                      aria-label={`Lượt ${t.turn_id} của cuộc gọi ${t.call_id}`}>
                      <td>{time(t.at)}</td>
                      <td><code>#{t.call_id}</code> <span className="hint">{t.channel}</span></td>
                      <td>{t.lane || "—"}<br /><span className="hint">{t.model || "—"}</span></td>
                      <td className={(t.ttft_ms ?? 0) > 3000 ? "live-warn" : undefined}>{ms(t.ttft_ms)}</td>
                      <td>{n((t.tokens.input ?? 0) + (t.tokens.output ?? 0) || null)}<br /><span className="hint">{t.model_calls} lần gọi</span></td>
                      <td>{usd(t.cost_usd)}</td>
                      <td>
                        {t.tools.length === 0 ? <span className="hint">—</span> : t.tools.map((x, k) => (
                          <span key={k} className={`live-tool ${x.ok ? "" : "is-failed"}`}>{x.name}</span>
                        ))}
                      </td>
                      <td>{t.error ? <span className="live-bad">lỗi</span> : t.guard.passed ? <span className="live-ok">qua</span> : <span className="live-bad">chặn</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <aside className="panel live-detail" aria-label="Chi tiết lượt">
          {!current ? (
            <p className="empty">Chọn một lượt để xem token theo agent, thời gian từng bước, tool và guard.</p>
          ) : (
            <TurnDetail turn={current} />
          )}
          {summary && Object.keys(summary.by_tool).length > 0 && (
            <div className="live-tools-summary">
              <h3>Tool trong 15 phút</h3>
              <ul>
                {Object.entries(summary.by_tool).map(([name, v]) => (
                  <li key={name}><code>{name}</code> <span>{v.calls} lần{v.failed ? `, ${v.failed} lỗi` : ""}</span></li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function merge(now: LiveTurn[], incoming: LiveTurn[]): LiveTurn[] {
  const seen = new Map(now.map((t) => [t.id, t]));
  for (const t of incoming) seen.set(t.id, t);
  return [...seen.values()].sort((a, b) => b.id - a.id).slice(0, KEEP);
}

function Tile({ label, value, hint, warn }: { label: string; value: string; hint?: string; warn?: boolean }) {
  return (
    <article className={warn ? "is-warn" : undefined}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </article>
  );
}

function TurnDetail({ turn }: { turn: LiveTurn }) {
  const stages = Object.entries(turn.stages).sort((a, b) => b[1] - a[1]);
  const longest = Math.max(1, ...stages.map(([, v]) => v));
  return (
    <div className="live-turn">
      <p className="eyebrow">Cuộc gọi #{turn.call_id} · {turn.turn_id}</p>
      <h2>{turn.lane || "Lượt"} · {turn.model || "model ?"}</h2>
      {turn.langfuse_url && (
        <a className="live-link" href={turn.langfuse_url} target="_blank" rel="noreferrer">Mở trace trong Langfuse ↗</a>
      )}
      <dl className="live-facts">
        <dt>TTFT · trọn lượt</dt><dd>{ms(turn.ttft_ms)} · {ms(turn.total_ms)}{turn.warmup ? " (khởi động)" : ""}</dd>
        <dt>Token vào · ra · cache</dt><dd>{n(turn.tokens.input)} · {n(turn.tokens.output)} · {n(turn.tokens.cached)}</dd>
        <dt>Chi phí</dt><dd>{usd(turn.cost_usd)}</dd>
        <dt>Viết lại · dự phòng</dt><dd>{turn.regenerations} · {turn.fallback ? "có" : "không"}</dd>
        {turn.route_reason && (<><dt>Vì sao lane này</dt><dd>{turn.route_reason}</dd></>)}
        {turn.error && (<><dt>Lỗi</dt><dd className="live-bad">{turn.error}</dd></>)}
      </dl>
      {Object.keys(turn.by_agent).length > 0 && (
        <>
          <h3>Token theo agent</h3>
          <table className="live-table live-mini">
            <thead><tr><th scope="col">Agent</th><th scope="col">Lần gọi</th><th scope="col">Vào / ra</th><th scope="col">Chi phí</th></tr></thead>
            <tbody>
              {Object.entries(turn.by_agent).map(([agent, v]) => (
                <tr key={agent}><td>{agent}</td><td>{v.calls}</td><td>{n(v.input)} / {n(v.output)}</td><td>{usd(v.cost_usd)}</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {stages.length > 0 && (
        <>
          <h3>Thời gian từng bước</h3>
          <ul className="live-stages">
            {stages.map(([name, v]) => (
              <li key={name}>
                <span>{name.replace(/_ms$/, "")}</span>
                <span className="live-bar-track" aria-hidden><i style={{ width: `${(v / longest) * 100}%` }} /></span>
                <span>{ms(v)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <h3>Tool đã gọi</h3>
      {turn.tools.length === 0 ? <p className="hint">Không gọi tool.</p> : (
        <ul className="live-tool-list">
          {turn.tools.map((t, k) => (
            <li key={k} className={t.ok ? undefined : "is-failed"}>
              <code>{t.name}</code> {t.ok ? <span className="live-ok">ok</span> : <span className="live-bad">{t.blocked_by ? `bị chặn: ${t.blocked_by}` : t.error || "lỗi"}</span>}
              {t.args.length > 0 && <small> ({t.args.join(", ")})</small>}
            </li>
          ))}
        </ul>
      )}
      <h3>Guard</h3>
      {turn.guard.passed ? <p className="live-ok">Qua, không có lý do chặn.</p> : (
        <ul>{turn.guard.reasons.map((r) => <li key={r} className="live-bad">{r}</li>)}</ul>
      )}
    </div>
  );
}
