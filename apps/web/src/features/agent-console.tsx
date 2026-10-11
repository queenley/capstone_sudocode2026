"use client";
// Developer console for the AI agent (`/api/developer/*`, role developer/admin):
// the advisor's model, live sessions, latency against the organisers'
// thresholds, the 7-node pipeline, recent turns, voice options and the
// business day. Runtime changes live in the agent process only.
import { useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/services/api";

type Trace = {
  trace_id: string;
  pipeline: string;
  route: string | null;
  confidence: number;
  latency_ms: number | null;
  usage: { model_calls?: number; regenerations?: number } | null;
  errors: { stage: string; type: string }[];
  tools: { name: string; status: string; latency_ms: number | null }[];
  tier?: string | null;
  model?: string | null;
};
type ModelChoice = { provider: string; model: string; label?: string };
type ModelSelection = {
  provider: string;
  model: string;
  configured: boolean;
  overridden: boolean;
  choices: ModelChoice[];
};
type Stat = { n: number; p50_ms: number; p95_ms: number } | null;
type Latency = {
  turns: number;
  warmup_excluded: number;
  warning: string | null;
  thresholds_ms: Record<string, number>;
  ttft: Stat;
  total: Stat;
  ttfa: Stat;
  call_brief: Stat;
  ttfa_client: Stat;
};
type Sessions = { open: number; today: number; handoffs_waiting: number };
type Choice = { name: string; label?: string };
type Voice = {
  asr: string;
  endpointing: string;
  barge_in_ms: number;
  min_interruption_words: number;
  tts: string;
  overridden: boolean;
  available: { status: string; missing_packages: string[]; hint: string | null };
  asr_choices: Choice[];
  endpointing_choices: Choice[];
  tts_choices: Choice[];
};

const STAGES = [
  ["perceive", "Làm sạch, ITN, token PII"],
  ["load_context", "Định danh, CallBrief"],
  ["route", "Chọn lane bằng luật"],
  ["advisor", "Model gọi tool của lane"],
  ["guard", "Hard guard → Jev, regen ≤ 2"],
  ["respond", "Giải token, trả lời"],
  ["persist", "Lưu lượt, checkpoint"],
];
const FIGURES: [keyof Latency, string, string][] = [
  ["ttft", "TTFT", "ttft"],
  ["total", "Total", "total"],
  ["ttfa", "TTFA (voice)", "ttfa"],
  ["call_brief", "CallBrief", "call_brief"],
];

export default function AgentConsole({ token, onToken }: { token: string; onToken: (value: string) => void }) {
  const [traces, setTraces] = useState<Trace[]>([]);
  const [selected, setSelected] = useState<Trace | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState<ModelSelection | null>(null);
  const [modelChoice, setModelChoice] = useState("");
  const [latency, setLatency] = useState<Latency | null>(null);
  const [channel, setChannel] = useState("all");
  const [sessions, setSessions] = useState<Sessions | null>(null);
  const [voice, setVoice] = useState<Voice | null>(null);
  const [day, setDay] = useState("");
  const [dayInput, setDayInput] = useState("");

  const lanes = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const t of traces) counts[t.route || "—"] = (counts[t.route || "—"] || 0) + 1;
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [traces]);

  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Yêu cầu thất bại");
    } finally {
      setBusy(false);
    }
  }

  const refresh = () =>
    run(async () => {
      const [t, m, l, s, v, c] = await Promise.all([
        api<Trace[]>("/api/developer/traces", token),
        api<ModelSelection>("/api/developer/model", token),
        api<Latency>(`/api/developer/latency?channel=${channel}`, token),
        api<Sessions>("/api/developer/sessions", token),
        api<Voice>("/api/developer/voice", token),
        api<{ day: string }>("/api/developer/clock", token),
      ]);
      setTraces(t);
      setModel(m);
      setModelChoice(`${m.provider}::${m.model}`);
      setLatency(l);
      setSessions(s);
      setVoice(v);
      setDay(c.day);
      setDayInput(c.day);
    });

  const applyModel = (reset = false) =>
    run(async () => {
      const [provider, ...rest] = modelChoice.split("::");
      const next = reset
        ? await api<ModelSelection>("/api/developer/model", token, undefined, "DELETE")
        : await api<ModelSelection>("/api/developer/model", token, { provider, model: rest.join("::") }, "PUT");
      setModel(next);
      setModelChoice(`${next.provider}::${next.model}`);
    });

  const setVoiceOption = (change: Record<string, unknown>) =>
    run(async () => setVoice(await api<Voice>("/api/developer/voice", token, change)));

  return (
    <main className="shell workspace agent-console">
      <header className="topbar">
        <Link className="logo" href="/">
          tiếp nối
        </Link>
        <nav>
          <Link href="/login">Sign in</Link>
          <Link href="/agent">Inbox</Link>
          <Link href="/calls">Calls</Link>
          <Link href="/admin">Admin</Link>
          <Link href="/developer">Developer</Link>
        </nav>
      </header>
      <div className="section-heading console-heading">
        <div>
          <p className="eyebrow">AI AGENT · OBSERVABILITY</p>
          <h1>Agent Console</h1>
          <p className="console-subtitle">Model, độ trễ, lane và tool của từng lượt; cấu hình voice và ngày nghiệp vụ.</p>
        </div>
        <div className="console-status">
          <span className="status-dot" /> {day ? `Ngày nghiệp vụ ${day}` : "Chưa kết nối"}
        </div>
      </div>
      <form
        className="authbar"
        onSubmit={(e) => {
          e.preventDefault();
          void refresh();
        }}
      >
        <label>
          Developer access token
          <input
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => onToken(e.target.value)}
            placeholder="Token developer hoặc admin"
            required
          />
        </label>
        <button disabled={busy} type="submit">
          {busy ? "Đang tải…" : "Kết nối / Làm mới"}
        </button>
      </form>
      {error && (
        <div role="alert" className="alert">
          {error}
          <button onClick={() => setError("")}>Đóng</button>
        </div>
      )}

      <section className="console-stats four">
        <article>
          <span>Cuộc gọi đang mở</span>
          <strong>{sessions?.open ?? "—"}</strong>
          <small>{sessions ? `${sessions.today} cuộc gọi hôm nay` : "Theo bảng agent.calls"}</small>
        </article>
        <article>
          <span>Chờ nhân viên</span>
          <strong>{sessions?.handoffs_waiting ?? "—"}</strong>
          <small>
            <Link href="/calls">Mở console cuộc gọi ↗</Link>
          </small>
        </article>
        <article>
          <span>Lượt gần đây</span>
          <strong>{traces.length}</strong>
          <small>{lanes.slice(0, 3).map(([lane, n]) => `${lane} ${n}`).join(" · ") || "Tối đa 100 lượt"}</small>
        </article>
        <article>
          <span>Total p95</span>
          <strong>{latency?.total ? `${(latency.total.p95_ms / 1000).toFixed(1)} s` : "—"}</strong>
          <small>Ngưỡng BTC {latency ? `${latency.thresholds_ms.total / 1000} s` : "8 s"}</small>
        </article>
      </section>

      <section className="panel model-panel">
        <div className="panel-title">
          <div>
            <p className="eyebrow">ADVISOR MODEL</p>
            <h2>Model đang chạy</h2>
          </div>
          <span>{model?.overridden ? "Runtime override" : "Theo config/models.yaml"}</span>
        </div>
        <p className="console-subtitle">
          {!model
            ? "Kết nối để xem."
            : model.configured
              ? `${model.provider} · ${model.model}`
              : `${model.provider} · ${model.model}: thiếu API key, trợ lý sẽ nói câu an toàn rồi chuyển nhân viên.`}
        </p>
        <div className="model-controls">
          <label>
            Provider / model
            <select value={modelChoice} onChange={(e) => setModelChoice(e.target.value)} disabled={!model?.choices.length || busy}>
              {(model?.choices || []).map((c) => (
                <option key={`${c.provider}::${c.model}`} value={`${c.provider}::${c.model}`}>
                  {c.label || `${c.provider} · ${c.model}`}
                </option>
              ))}
            </select>
          </label>
          <button
            disabled={busy || !model?.choices.length || modelChoice === `${model?.provider}::${model?.model}`}
            onClick={() => void applyModel()}
          >
            Áp dụng
          </button>
          <button className="secondary" disabled={busy || !model?.overridden} onClick={() => void applyModel(true)}>
            Khôi phục mặc định
          </button>
        </div>
        <small>Chỉ hiện model có API key. Thay đổi mất khi service khởi động lại.</small>
      </section>

      <section className="panel latency-panel">
        <div className="panel-title">
          <div>
            <p className="eyebrow">LATENCY · HUONG-DAN-DO-LATENCY</p>
            <h2>p50 / p95 so với ngưỡng BTC</h2>
          </div>
          <select
            aria-label="Kênh"
            value={channel}
            onChange={(e) => {
              setChannel(e.target.value);
              if (token)
                void run(async () => setLatency(await api<Latency>(`/api/developer/latency?channel=${e.target.value}`, token)));
            }}
          >
            {["all", "web", "hotline", "zalo", "facebook"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        {latency ? (
          <>
            <div className="latency-grid">
              {FIGURES.map(([key, label, threshold]) => {
                const stat = latency[key] as Stat;
                const limit = latency.thresholds_ms[threshold];
                const over = stat != null && stat.p95_ms > limit;
                return (
                  <article key={key} className={over ? "over" : ""}>
                    <span>{label}</span>
                    <strong>{stat ? `${stat.p95_ms} ms` : "—"}</strong>
                    <small>
                      {stat ? `p50 ${stat.p50_ms} ms · n=${stat.n}` : "chưa có số liệu"} · ngưỡng {limit} ms
                    </small>
                    <div className="meter">
                      <i style={{ width: `${stat ? Math.min(100, (stat.p95_ms / limit) * 100) : 0}%` }} />
                    </div>
                  </article>
                );
              })}
            </div>
            <small className="hint">
              {latency.turns} lượt, bỏ {latency.warmup_excluded} lượt khởi động. {latency.warning || ""}
            </small>
          </>
        ) : (
          <p className="empty">Kết nối để tải số liệu.</p>
        )}
      </section>

      <section className="panel flow-panel">
        <div className="panel-title">
          <div>
            <p className="eyebrow">HOT GRAPH · PIPELINE/HOT</p>
            <h2>Một lượt đi qua 7 bước</h2>
          </div>
        </div>
        <div className="flow-nodes">
          {STAGES.map(([key, label], index) => (
            <div className="flow-node-wrap" key={key}>
              <article className="flow-node">
                <small>{String(index + 1).padStart(2, "0")}</small>
                <strong>{label}</strong>
                <code>{key}</code>
              </article>
              {index < STAGES.length - 1 && <span className="flow-arrow">→</span>}
            </div>
          ))}
        </div>
        <p className="flow-note">
          Lane do luật chọn (HANDOFF, CLARIFY, CONFIRM_IDENTITY, ORDER_SERVICE, OUT_OF_SCOPE, CONTINUITY, NEW) và giới hạn tool
          mà advisor thấy. Mọi số tiền trong câu trả lời phải có trong kết quả tool của lượt đó.
        </p>
      </section>

      <div className="console-grid">
        <section className="panel trace-panel">
          <div className="panel-title">
            <div>
              <p className="eyebrow">AGENT TURNS</p>
              <h2>Lượt gần đây</h2>
            </div>
            <button className="secondary" disabled={busy || !token} onClick={() => void refresh()}>
              Làm mới
            </button>
          </div>
          {traces.length === 0 ? (
            <p className="empty">Kết nối bằng token để tải các lượt từ AI Agent service.</p>
          ) : (
            traces.map((t) => (
              <button
                className={`trace-row ${selected?.trace_id === t.trace_id ? "selected" : ""}`}
                key={t.trace_id}
                onClick={() => setSelected(t)}
              >
                <span className="trace-route">{t.route || "—"}</span>
                <span>{t.tools.map((tool) => tool.name).join(", ") || "không gọi tool"}</span>
                <span>{t.latency_ms != null ? `${t.latency_ms} ms` : "—"}</span>
                <code className={t.errors.length ? "bad-text" : ""}>{t.errors.length ? `${t.errors.length} lỗi` : t.trace_id}</code>
              </button>
            ))
          )}
        </section>
        <aside className="panel trace-detail">
          <p className="eyebrow">CHI TIẾT LƯỢT</p>
          <h2>{selected?.route || "Chọn một lượt"}</h2>
          {selected ? (
            <>
              <Metric label="Trace ID" value={selected.trace_id} code />
              <Metric label="Tier" value={selected.tier || "—"} />
              <Metric label="Model" value={selected.model || "—"} code />
              <Metric label="Latency" value={selected.latency_ms != null ? `${selected.latency_ms} ms` : "—"} />
              <Metric
                label="Model calls · regen"
                value={`${selected.usage?.model_calls ?? 0} · ${selected.usage?.regenerations ?? 0}`}
              />
              <Metric
                label="Tools"
                value={selected.tools.length ? selected.tools.map((t) => `${t.name} · ${t.status}`).join("\n") : "Không gọi tool"}
                code
              />
              <Metric
                label="Lỗi / guard"
                value={selected.errors.length ? selected.errors.map((e) => `${e.stage}: ${e.type}`).join("\n") : "Không có"}
                code
              />
            </>
          ) : (
            <p className="empty">Chọn một lượt để xem lane, tool và kết quả guard.</p>
          )}
        </aside>
      </div>

      <div className="console-grid">
        <section className="panel">
          <div className="panel-title">
            <div>
              <p className="eyebrow">VOICE CHANNEL</p>
              <h2>Kênh gọi thoại</h2>
            </div>
            <span>{voice ? (voice.available.status === "ok" ? "Sẵn sàng" : "Chưa sẵn sàng") : ""}</span>
          </div>
          {!voice ? (
            <p className="empty">Kết nối để xem.</p>
          ) : voice.available.status !== "ok" ? (
            <p className="empty">
              {voice.available.missing_packages.length
                ? `Thiếu gói: ${voice.available.missing_packages.join(", ")}. `
                : ""}
              {voice.available.hint}
            </p>
          ) : (
            <div className="voice-form">
              <label>
                ASR
                <select value={voice.asr} onChange={(e) => setVoiceOption({ asr: e.target.value })} disabled={busy}>
                  {voice.asr_choices.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.label || c.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Endpointing
                <select value={voice.endpointing} onChange={(e) => setVoiceOption({ endpointing: e.target.value })} disabled={busy}>
                  {voice.endpointing_choices.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.label || c.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Giọng đọc
                <select value={voice.tts} onChange={(e) => setVoiceOption({ tts: e.target.value })} disabled={busy}>
                  {voice.tts_choices.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.label || c.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Barge-in (ms)
                <input
                  type="number"
                  min={100}
                  max={2000}
                  step={50}
                  defaultValue={voice.barge_in_ms}
                  onBlur={(e) => setVoiceOption({ barge_in_ms: Number(e.target.value) })}
                />
              </label>
              <div className="buttonrow">
                <button disabled={busy} onClick={() => run(async () => void (await api("/api/developer/voice/warm", token, {})))}>
                  Nạp model
                </button>
                <button className="secondary" disabled={busy || !voice.overridden} onClick={() => setVoiceOption({ reset: true })}>
                  Khôi phục mặc định
                </button>
              </div>
            </div>
          )}
        </section>
        <aside className="panel">
          <p className="eyebrow">BUSINESS DAY</p>
          <h2>Ngày nghiệp vụ</h2>
          <p className="empty">
            Dữ liệu BTC viết cho 2026-10-15. Đổi ngày để thử cuộc gọi thứ hai (khách quay lại, giá/khuyến mãi theo ngày).
          </p>
          <form
            className="model-controls"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => setDay((await api<{ day: string }>("/api/developer/clock", token, { day: dayInput || null })).day));
            }}
          >
            <label>
              Ngày (YYYY-MM-DD)
              <input value={dayInput} onChange={(e) => setDayInput(e.target.value)} placeholder="2026-10-15" />
            </label>
            <button disabled={busy || !token} type="submit">
              Đặt ngày
            </button>
          </form>
          <small className="hint">Hiện tại: {day || "—"}. Để trống rồi bấm Đặt ngày để quay về ngày tham chiếu.</small>
        </aside>
      </div>
    </main>
  );
}

function Metric({ label, value, code }: { label: string; value: string; code?: boolean }) {
  return (
    <div className="detail-metric">
      <span>{label}</span>
      {code ? <code>{value}</code> : <strong>{value}</strong>}
    </div>
  );
}
