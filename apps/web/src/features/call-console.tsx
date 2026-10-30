"use client";
// The consultant's console for the AI agent's calls (`/api/agent/calls`).
//
// Three panes: the queue, the transcript of the selected call seen from the
// staff side, and the evidence behind it (Call Brief, context, each assistant
// turn's lane, tools and guard). While the assistant handles a call the
// consultant observes. Copilot begins with a handoff the consultant accepts:
// the assistant then drafts a reply to each customer message and the
// consultant sends it as written, edited, or in their own words. What they
// send passes the same hard guard as a draft; a warning can be fixed or
// overridden. The reply reaches the customer's chat. Polling: queue 5 s,
// open call 3 s.
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, AgentCall, AgentCallDetail, AgentTurn } from "@/services/api";
import { handoffReason, HandoffToasts, useHandoffAlerts } from "@/features/handoff-alerts";

const QUEUE_EVERY_MS = 5000;
const CALL_EVERY_MS = 3000;
const CHANNEL: Record<string, string> = { web: "Web chat", zalo: "Zalo", hotline: "Hotline", facebook: "Facebook" };

type Warning = { content: string; action: string; reasons: string[] };
type Faq = { question: string; answer: string; saved: string | null };

/** ``embedded``: inside the sales workspace (/ban-hang), which has already signed the person in:
 * connect at once with that token and leave out this page's own header and token form; the
 * workspace raises the handoff alerts. ``focus``: a call to open (a clicked alert). */
export default function CallConsole({ embedded = false, focus = null }: { embedded?: boolean; focus?: number | null }) {
  const [token, setToken] = useState("");
  const [connected, setConnected] = useState(false);
  const [openOnly, setOpenOnly] = useState(false);
  const [calls, setCalls] = useState<AgentCall[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AgentCallDetail | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [draftFrom, setDraftFrom] = useState<"own" | "edited">("own");
  const [sending, setSending] = useState(false);
  const [warning, setWarning] = useState<Warning | null>(null);
  const [faq, setFaq] = useState<Faq | null>(null);
  // The 👍/👎 the consultant gave the suggestion on screen, keyed by its text so a new suggestion starts unrated.
  const [rated, setRated] = useState<{ text: string; thumb: "up" | "down" } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setToken(sessionStorage.getItem("staff-token") || "");
  }, []);

  useEffect(() => {
    if (focus != null) setSelectedId(focus);
  }, [focus]);

  const alerts = useHandoffAlerts(connected && !embedded ? calls : null);

  const refreshQueue = useCallback(async () => {
    try {
      const list = await api<AgentCall[]>(`/api/agent/calls?open_only=${openOnly}&limit=50`, token);
      setCalls(list);
      setConnected(true);
      setSelectedId((current) => current ?? list[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được hàng chờ");
      setConnected(false);
    }
  }, [token, openOnly]);

  const refreshCall = useCallback(
    async (id: number | null) => {
      if (id == null) return;
      try {
        setDetail(await api<AgentCallDetail>(`/api/agent/calls/${id}`, token));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Không tải được cuộc gọi");
      }
    },
    [token],
  );

  useEffect(() => {
    if (embedded && token && !connected) void refreshQueue();
  }, [embedded, token, connected, refreshQueue]);

  useEffect(() => {
    if (!connected) return;
    const timer = setInterval(refreshQueue, QUEUE_EVERY_MS);
    return () => clearInterval(timer);
  }, [connected, refreshQueue]);

  useEffect(() => {
    setDetail(null);
    setDraft("");
    setDraftFrom("own");
    setWarning(null);
    setFaq(null);
    if (!connected || selectedId == null) return;
    void refreshCall(selectedId);
    const timer = setInterval(() => refreshCall(selectedId), CALL_EVERY_MS);
    return () => clearInterval(timer);
  }, [connected, selectedId, refreshCall]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail?.turns.length]);

  async function run(task: () => Promise<void>) {
    setError("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Yêu cầu thất bại");
    }
  }

  const accept = (id: number) =>
    run(async () => {
      await api(`/api/agent/calls/${id}/accept`, token, {});
      setSelectedId(id);
      await refreshQueue();
      await refreshCall(id);
    });

  const rate = (thumb: "up" | "down") =>
    run(async () => {
      if (!detail?.suggestion) return;
      await api(`/api/agent/calls/${detail.id}/suggestion-feedback`, token, { thumb });
      setRated({ text: detail.suggestion.text, thumb });
    });

  async function send(content: string, action: string, force = false) {
    if (!detail || !content.trim() || sending) return;
    setSending(true);
    await run(async () => {
      const question = [...detail.turns].reverse().find((t) => t.speaker === "customer")?.content;
      const result = await api<{ sent: boolean; warnings: string[] }>(`/api/agent/calls/${detail.id}/reply`, token, {
        content: content.trim(),
        action,
        force,
      });
      if (!result.sent) {
        setWarning({ content, action, reasons: result.warnings });
        return;
      }
      setWarning(null);
      setDraft("");
      setDraftFrom("own");
      if (question) setFaq({ question, answer: content.trim(), saved: null });
      await refreshCall(detail.id);
    });
    setSending(false);
  }

  const turns = detail?.turns ?? [];
  const spoken = turns.filter((t) => t.speaker !== "system");
  const last = spoken[spoken.length - 1];
  const live = Boolean(detail && !detail.ended_at);
  const copilot = live && detail?.handoff_status === "accepted" && detail.held_by_you;
  const awaitingReply = copilot && last?.speaker === "customer";
  const suggestion = awaitingReply ? detail?.suggestion : null;
  const modeLine = !detail
    ? ""
    : detail.ended_at
      ? "Đã kết thúc"
      : detail.handoff_status === "pending"
        ? "Đang chờ nhân viên nhận"
        : detail.handoff_status === "accepted"
          ? detail.held_by_you
            ? "Bạn đang phụ trách cuộc gọi này (copilot)"
            : "Một nhân viên khác đang phụ trách"
          : "Trợ lý AI đang xử lý; bạn đang quan sát";
  const waiting = calls.filter((c) => c.handoff_status === "pending" && !c.ended_at).length;
  const flagged = turns.filter((t) => t.speaker === "customer" && t.meta?.handoff).length;

  return (
    <main className={"shell workspace call-console" + (embedded ? " embedded" : "")}>
      {!embedded && (
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
      )}
      <div className="section-heading console-heading">
        <div>
          <p className="eyebrow">AI AGENT · CONSULTANT CONSOLE</p>
          <h1>Cuộc gọi của trợ lý</h1>
          <p className="console-subtitle">
            Theo dõi trợ lý đang tư vấn, nhận cuộc gọi khi trợ lý chuyển máy, và trả lời cùng gợi ý của trợ lý.
          </p>
        </div>
        <div className="console-status">
          <span className={"status-dot" + (connected ? "" : " off")} /> {waiting} chờ nhận
        </div>
      </div>
      {!embedded && (
      <form
        className="authbar"
        onSubmit={(e) => {
          e.preventDefault();
          void run(refreshQueue);
        }}
      >
        <label>
          Staff access token
          <input
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Token của role agent hoặc admin"
            required
          />
        </label>
        <label className="check inline">
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} /> Chỉ cuộc gọi đang mở
        </label>
        <button type="submit">{connected ? "Làm mới" : "Kết nối"}</button>
      </form>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
          <button onClick={() => setError("")}>Đóng</button>
        </div>
      )}

      <div className="call-grid">
        <aside className="panel call-queue">
          <h2>Hàng chờ</h2>
          {calls.length === 0 && <p className="empty">{connected ? "Chưa có cuộc gọi." : "Kết nối bằng token để tải."}</p>}
          {calls.map((c) => (
            <div
              key={c.id}
              className={
                "queue-item" +
                (c.id === selectedId ? " selected" : "") +
                (c.handoff_status === "pending" && !c.ended_at ? " waiting" : "")
              }
            >
              <button className="queue-row" onClick={() => setSelectedId(c.id)}>
                <span className={"live-dot" + (c.ended_at ? " ended" : "")} />
                <span className="queue-text">
                  <strong>{caller(c)}</strong>
                  <small>
                    {c.handoff_status === "pending"
                      ? `Cần nhân viên · ${handoffReason(c)}`
                      : c.handoff_status === "accepted"
                        ? "Nhân viên đang phụ trách"
                        : `${c.lane} · ${c.tier.toLowerCase()} · ${c.turn_count} lượt`}
                  </small>
                  <small>
                    {CHANNEL[c.channel] || c.channel} · {when(c.started_at)}
                  </small>
                </span>
              </button>
              {c.handoff_status === "pending" && !c.ended_at && (
                <button className="small" onClick={() => accept(c.id)}>
                  Nhận
                </button>
              )}
            </div>
          ))}
        </aside>

        <section className="panel call-transcript-pane">
          {detail ? (
            <>
              <div className="panel-title">
                <div>
                  <h2>
                    {caller(detail)} · {CHANNEL[detail.channel] || detail.channel}
                  </h2>
                  <p className="console-subtitle">{modeLine}</p>
                </div>
                <span className={"tag" + (detail.ended_at ? "" : " accent")}>
                  {detail.ended_at ? "Ended" : detail.mode === "copilot" ? "Copilot" : "Assistant"}
                </span>
              </div>
              <div className="messages staff-messages call-turns">
                {spoken.length === 0 && <p className="empty">Chưa có lời nào.</p>}
                {turns.map((t) => (
                  <TurnBubble key={t.id} turn={t} />
                ))}
                <div ref={bottom} />
              </div>

              {flagged > 0 && (
                <p className="handoff-legend">
                  {flagged} tin nhắn của khách được tô đỏ: tin khiến cuộc trò chuyện chuyển sang nhân viên, và tin khách
                  gửi trong lúc chờ.
                </p>
              )}

              {live && detail.handoff_status === "pending" && (
                <div className="call-action-bar handoff-pending">
                  <span>{handoffReason(detail)}</span>
                  <button onClick={() => accept(detail.id)}>Nhận cuộc gọi này</button>
                </div>
              )}

              {copilot && (
                <div className="copilot">
                  {warning && (
                    <div className="alert column" role="alert">
                      <span>Guard cảnh báo: {warning.reasons.join(" ")}</span>
                      <div className="buttonrow">
                        <button
                          className="secondary"
                          onClick={() => {
                            setDraft(warning.content);
                            setDraftFrom("edited");
                            setWarning(null);
                          }}
                        >
                          Sửa lại
                        </button>
                        <button className="danger" disabled={sending} onClick={() => send(warning.content, warning.action, true)}>
                          Vẫn gửi
                        </button>
                      </div>
                    </div>
                  )}
                  {faq && !awaitingReply && (
                    <div className="card">
                      {faq.saved ? (
                        <p>Đã lưu thành FAQ {faq.saved}. Lần sau trợ lý tự trả lời được câu này.</p>
                      ) : (
                        <>
                          <small>Lưu câu trả lời này để trợ lý dùng lần sau?</small>
                          <p>Câu hỏi: {faq.question}</p>
                          <textarea rows={2} value={faq.answer} onChange={(e) => setFaq({ ...faq, answer: e.target.value })} />
                          <small>Xóa mọi thông tin riêng của khách trước khi lưu.</small>
                          <div className="buttonrow">
                            <button
                              onClick={() =>
                                run(async () => {
                                  const saved = await api<{ chunk_id?: string }>(`/api/agent/calls/${detail.id}/faq`, token, {
                                    question: faq.question,
                                    answer: faq.answer,
                                  });
                                  setFaq({ ...faq, saved: saved.chunk_id || "mới" });
                                })
                              }
                            >
                              Lưu FAQ
                            </button>
                            <button className="secondary" onClick={() => setFaq(null)}>
                              Để sau
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                  {suggestion && draftFrom === "own" && !draft && (
                    <div className="card suggestion">
                      <small>Trợ lý gợi ý</small>
                      <p>{suggestion.text}</p>
                      {!!suggestion.used_lines?.length && <small>Dựa trên {suggestion.used_lines.join(", ")}</small>}
                      {!!suggestion.warnings?.length && <div className="alert">{suggestion.warnings.join(" ")}</div>}
                      <div className="buttonrow">
                        <button disabled={sending} onClick={() => send(suggestion.text, "used")}>
                          Gửi nguyên văn
                        </button>
                        <button
                          className="secondary"
                          onClick={() => {
                            setDraft(suggestion.text);
                            setDraftFrom("edited");
                          }}
                        >
                          Sửa trước khi gửi
                        </button>
                        <span className="thumbs" role="group" aria-label="Đánh giá gợi ý">
                          <button
                            className="secondary"
                            aria-label="Gợi ý tốt"
                            aria-pressed={rated?.text === suggestion.text && rated.thumb === "up"}
                            onClick={() => rate("up")}
                          >
                            👍
                          </button>
                          <button
                            className="secondary"
                            aria-label="Gợi ý chưa tốt"
                            aria-pressed={rated?.text === suggestion.text && rated.thumb === "down"}
                            onClick={() => rate("down")}
                          >
                            👎
                          </button>
                        </span>
                      </div>
                      {rated?.text === suggestion.text && <small>Đã ghi nhận đánh giá của bạn.</small>}
                    </div>
                  )}
                  <form
                    className="composer"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void send(draft, draftFrom);
                    }}
                  >
                    <textarea
                      aria-label="Trả lời khách"
                      rows={2}
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          void send(draft, draftFrom);
                        }
                      }}
                      placeholder={awaitingReply ? "Trả lời khách" : "Nhắn cho khách"}
                    />
                    <button type="submit" disabled={sending || !draft.trim()}>
                      Gửi
                    </button>
                  </form>
                  {draftFrom === "edited" && <small className="hint">Đang sửa gợi ý; phần khác biệt được lưu làm phản hồi.</small>}
                </div>
              )}

              {live && (
                <div className="buttonrow">
                  {!detail.handoff_status && (
                    <button
                      className="secondary"
                      onClick={() =>
                        run(async () => {
                          await api(`/api/agent/calls/${detail.id}/handoff`, token, { reason: "Nhân viên chủ động nhận" });
                          await refreshCall(detail.id);
                        })
                      }
                    >
                      Yêu cầu chuyển cho nhân viên
                    </button>
                  )}
                  <button
                    className="secondary"
                    onClick={() =>
                      run(async () => {
                        if (!window.confirm("Kết thúc cuộc gọi và chạy after-call (ghi nhớ, chấm QA)?")) return;
                        await api(`/api/agent/calls/${detail.id}/end`, token, {});
                        await refreshCall(detail.id);
                        await refreshQueue();
                      })
                    }
                  >
                    Kết thúc cuộc gọi
                  </button>
                </div>
              )}
            </>
          ) : (
            <p className="empty">{selectedId == null ? "Chọn một cuộc gọi." : "Đang tải…"}</p>
          )}
        </section>

        <aside className="panel call-evidence">
          <h2>Bằng chứng</h2>
          {detail ? <Evidence detail={detail} /> : <p className="empty">Chọn cuộc gọi để xem brief và các lượt của trợ lý.</p>}
        </aside>
      </div>
      {!embedded && <HandoffToasts alerts={alerts} onOpen={setSelectedId} />}
    </main>
  );
}

function TurnBubble({ turn }: { turn: AgentTurn }) {
  if (turn.speaker === "system")
    return <p className="call-note">{turn.meta?.joined ? `${String(turn.meta.joined)} đã tham gia` : turn.content}</p>;
  const label =
    turn.speaker === "customer" ? "KHÁCH" : turn.speaker === "human_agent" ? "NHÂN VIÊN" : "TRỢ LÝ AI";
  const lane = turn.speaker === "agent" ? (turn.meta?.lane as string | undefined) : undefined;
  // Set by the agent (runtime/harness.py handoff_mark): the message the call was handed over after
  // ("trigger"), or one written while the handoff waited ("waiting").
  const mark = turn.speaker === "customer" ? (turn.meta?.handoff as { role?: string; label?: string } | undefined) : undefined;
  return (
    <div
      className={
        "message " +
        (turn.speaker === "customer" ? "incoming" : turn.speaker === "human_agent" ? "outgoing human" : "outgoing") +
        (mark?.role ? ` handoff-${mark.role}` : "")
      }
    >
      {mark?.role && (
        <span className="handoff-flag">
          {mark.role === "trigger" ? `⚠ Cần nhân viên · ${mark.label || "chuyển máy"}` : mark.label || "Khách nhắn khi đang chờ"}
        </span>
      )}
      <small>
        {label}
        {lane ? ` · ${lane}` : ""} · {new Date(turn.created_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}
      </small>
      <p>{turn.content}</p>
    </div>
  );
}

function Evidence({ detail }: { detail: AgentCallDetail }) {
  const agentTurns = detail.turns.filter((t) => t.speaker === "agent");
  return (
    <>
      <h3>Call brief</h3>
      {detail.warnings.map((w, i) => (
        <div className="notice" key={i}>
          {w}
        </div>
      ))}
      {detail.brief.length === 0 ? (
        <p className="empty">
          {detail.tier === "UNKNOWN"
            ? "Chưa xác định khách nên không có gì để mang sang."
            : detail.tier === "AMBIGUOUS"
              ? "Số dùng chung: chưa tải brief cho đến khi khách nói mình là ai."
              : "Đã biết khách, chưa có gì để mang sang."}
        </p>
      ) : (
        <ol className="brief">
          {detail.brief.map((line) => {
            const withheld = line.sensitive && detail.tier !== "VERIFIED";
            return (
              <li key={line.id} className={withheld ? "faded" : ""}>
                <code>{line.id}</code> {line.text}
                {withheld && <small> (ẩn cho đến khi xác minh)</small>}
              </li>
            );
          })}
        </ol>
      )}
      {detail.brief_object?.is_returning && (
        <dl className="facts">
          <dt>Không hỏi lại</dt>
          <dd>{detail.brief_object.must_not_ask?.join(", ") || "—"}</dd>
          <dt>Mở đầu gợi ý</dt>
          <dd>{detail.brief_object.suggested_opening}</dd>
          <dt>Dựng trong</dt>
          <dd>{detail.brief_object.latency_ms} ms</dd>
        </dl>
      )}
      <h3>Ngữ cảnh</h3>
      <dl className="facts">
        <dt>Khách</dt>
        <dd>{detail.customer_id ? `${detail.customer_label || ""} (${detail.customer_id})` : "chưa biết"}</dd>
        <dt>Tier</dt>
        <dd>{detail.tier}</dd>
        <dt>Lane</dt>
        <dd>
          {detail.lane}
          {detail.route_reason ? ` — ${detail.route_reason}` : ""}
        </dd>
        <dt>Ngày nghiệp vụ</dt>
        <dd>{detail.business_day || "—"}</dd>
        {detail.handoff_status && (
          <>
            <dt>Handoff</dt>
            <dd>
              {detail.handoff_status}
              {detail.handoff_reason ? ` — ${detail.handoff_reason}` : ""}
            </dd>
          </>
        )}
      </dl>
      {detail.handoff_brief && (
        <>
          <h3>Handoff brief</h3>
          <pre>{JSON.stringify(detail.handoff_brief, null, 2)}</pre>
        </>
      )}
      <h3>Các lượt của trợ lý</h3>
      {agentTurns.length === 0 && <p className="empty">Chưa có lượt nào.</p>}
      {agentTurns.map((t, i) => {
        const tools = (t.meta?.tool_calls as { name: string; result?: { ok?: boolean } }[] | undefined) || [];
        const guard = (t.meta?.guard as { passed?: boolean; hard?: { reasons?: string[] }; soft?: { reasons?: string[] } }) || {};
        const reasons = [...(guard.hard?.reasons || []), ...(guard.soft?.reasons || [])];
        return (
          <div className="turn-evidence" key={t.id}>
            <strong>
              #{i + 1} · {String(t.meta?.lane || "—")}
            </strong>
            {tools.length > 0 && (
              <div className="chips">
                {tools.map((tool, j) => (
                  <span key={j} className={"chip" + (tool.result?.ok ? "" : " bad")}>
                    {tool.name}
                  </span>
                ))}
              </div>
            )}
            <small>
              Guard {guard.passed === false ? "trượt" : "đạt"}
              {Number(t.meta?.regenerations) > 0 ? ` · viết lại ${String(t.meta.regenerations)} lần` : ""}
              {t.meta?.fallback ? " · câu an toàn" : ""}
              {t.meta?.model ? ` · ${String(t.meta.model)}` : ""}
            </small>
            {reasons.length > 0 && <small className="bad-text">{reasons.join(" ")}</small>}
          </div>
        );
      })}
      {detail.ended_at && (
        <>
          <h3>Sau cuộc gọi</h3>
          <p className="empty">Ghi nhớ: {detail.memory_status || "—"}</p>
          {detail.after_call && <pre>{JSON.stringify(detail.after_call, null, 2)}</pre>}
        </>
      )}
    </>
  );
}

function caller(c: AgentCall) {
  if (c.customer_label) return c.customer_label;
  if (c.phone_last4) return `Số đuôi ${c.phone_last4}`;
  if (c.channel_ref) return c.channel_ref;
  return `Cuộc gọi #${c.id}`;
}

function when(iso: string) {
  return new Date(iso).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
}
