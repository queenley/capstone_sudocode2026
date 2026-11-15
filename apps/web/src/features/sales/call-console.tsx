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
// open call 3 s; the header's bell hears handoffs at once (handoff-alerts).
//
// The queue has one row per customer (call-groups): the sessions of one CRM
// customer, on any channel, open from that row and switch above the brief.
// The Call Brief, and the handoff brief when the assistant handed over, sit at
// the top of the conversation: what the consultant reads before answering.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Logo } from "@/components/brand/Logo";
import ThemeToggle from "@/components/theme/ThemeToggle";
import { api, AgentCall, AgentCallDetail, AgentTurn } from "@/services/api";
import CallEvidence, { ProductLinks, productsOf } from "@/features/sales/call-evidence";
import { reasonLabel } from "@/features/sales/handoff-reasons";
import Icon from "@/components/ui/Icon";
import { HandoffBell } from "@/features/sales/handoff-alerts";
import { groupCalls, groupOf } from "@/features/sales/call-groups";

const QUEUE_EVERY_MS = 5000;
const CALL_EVERY_MS = 3000;
const CHANNEL: Record<string, string> = {
  web: "Web chat",
  zalo: "Zalo",
  hotline: "Hotline",
  facebook: "Facebook",
};

type Warning = { content: string; action: string; reasons: string[] };
type Faq = { question: string; answer: string; saved: string | null };

/** ``embedded``: inside the sales workspace (/ban-hang), which has already signed the person in:
 * connect at once with that token and leave out this page's own header and token form.
 * ``focus``: a call to open, as the workspace's bell asks (``at`` makes the same call open again). */
export default function CallConsole({
  embedded = false,
  focus = null,
}: {
  embedded?: boolean;
  focus?: { id: number; at: number } | null;
}) {
  const [token, setToken] = useState("");
  const [tokenReady, setTokenReady] = useState(false);
  const [connected, setConnected] = useState(false);
  const [queueLoading, setQueueLoading] = useState(false);
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
  // The thumbs up/down the consultant gave the suggestion on screen, keyed by its text so a new suggestion starts unrated.
  const [rated, setRated] = useState<{
    text: string;
    thumb: "up" | "down";
  } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const currentToken = useRef(token);
  const currentCall = useRef(selectedId);
  const queueRequest = useRef(0);
  const detailRequest = useRef(0);
  const sendLock = useRef(false);
  currentToken.current = token;
  currentCall.current = selectedId;

  useEffect(
    () => () => {
      queueRequest.current++;
      detailRequest.current++;
    },
    [],
  );

  useEffect(() => {
    setToken(sessionStorage.getItem("staff-token") || "");
    setTokenReady(true);
  }, []);
  useEffect(() => {
    queueRequest.current++;
    detailRequest.current++;
    setConnected(false);
    setQueueLoading(false);
    setCalls([]);
    setSelectedId(null);
    setDetail(null);
    setError("");
  }, [token]);

  const refreshQueue = useCallback(async () => {
    const request = ++queueRequest.current;
    setQueueLoading(true);
    try {
      const list = await api<AgentCall[]>(
        `/api/agent/calls?open_only=${openOnly}&limit=50`,
        token,
      );
      if (token !== currentToken.current || request !== queueRequest.current)
        return;
      setCalls(list);
      setConnected(true);
      setSelectedId((current) => current ?? list[0]?.id ?? null);
    } catch (e) {
      if (token !== currentToken.current || request !== queueRequest.current)
        return;
      setError(e instanceof Error ? e.message : "Không tải được hàng chờ");
      if ([401, 403].includes((e as { status: number }).status)) setCalls([]);
      setConnected(false);
    } finally {
      if (token === currentToken.current && request === queueRequest.current)
        setQueueLoading(false);
    }
  }, [token, openOnly]);

  const refreshCall = useCallback(
    async (id: number | null) => {
      if (id == null) return;
      const request = ++detailRequest.current;
      try {
        const result = await api<AgentCallDetail>(
          `/api/agent/calls/${id}`,
          token,
        );
        if (
          id === currentCall.current &&
          token === currentToken.current &&
          request === detailRequest.current
        )
          setDetail(result);
      } catch (e) {
        if (
          id !== currentCall.current ||
          token !== currentToken.current ||
          request !== detailRequest.current
        )
          return;
        setError(e instanceof Error ? e.message : "Không tải được cuộc gọi");
      }
    },
    [token],
  );

  useEffect(() => {
    if (embedded && token && !connected) void refreshQueue();
  }, [embedded, token, connected, refreshQueue]);

  // The bell opened a call: show it, and read the queue now rather than at its next poll.
  const open = useCallback(
    (id: number) => {
      setSelectedId(id);
      void refreshQueue();
    },
    [refreshQueue],
  );
  useEffect(() => {
    // Only a new request from the bell opens a call, not every refresh of the queue.
    if (focus && connected) open(focus.id);
  }, [focus, connected]); // eslint-disable-line react-hooks/exhaustive-deps

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
    sendLock.current = false;
    setSending(false);
    if (!connected || selectedId == null) return;
    void refreshCall(selectedId);
    const timer = setInterval(() => refreshCall(selectedId), CALL_EVERY_MS);
    return () => clearInterval(timer);
  }, [connected, selectedId, refreshCall]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [detail?.turns.length]);

  async function run(task: (current: () => boolean) => Promise<void>) {
    const id = currentCall.current;
    const current = () =>
      token === currentToken.current && id === currentCall.current;
    setError("");
    try {
      await task(current);
    } catch (e) {
      if (current())
        setError(e instanceof Error ? e.message : "Yêu cầu thất bại");
    }
  }

  const accept = (id: number) =>
    run(async (current) => {
      await api(`/api/agent/calls/${id}/accept`, token, {});
      if (!current()) return;
      setSelectedId(id);
      await refreshQueue();
      await refreshCall(id);
    });

  const rate = (thumb: "up" | "down") =>
    run(async (current) => {
      if (!detail?.suggestion) return;
      await api(`/api/agent/calls/${detail.id}/suggestion-feedback`, token, {
        thumb,
      });
      if (current()) setRated({ text: detail.suggestion.text, thumb });
    });

  async function send(content: string, action: string, force = false) {
    if (!detail || !content.trim() || sendLock.current) return;
    sendLock.current = true;
    setSending(true);
    await run(async (current) => {
      const question = [...detail.turns]
        .reverse()
        .find((t) => t.speaker === "customer")?.content;
      const result = await api<{ sent: boolean; warnings: string[] }>(
        `/api/agent/calls/${detail.id}/reply`,
        token,
        {
          content: content.trim(),
          action,
          force,
        },
      );
      if (!current()) return;
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
    if (token === currentToken.current && detail.id === currentCall.current) {
      sendLock.current = false;
      setSending(false);
    }
  }

  const [search, setSearch] = useState("");
  const turns = detail?.turns ?? [];
  const spoken = turns.filter((t) => t.speaker !== "system");
  const last = spoken[spoken.length - 1];
  const live = Boolean(detail && !detail.ended_at);
  const copilot =
    live && detail?.handoff_status === "accepted" && detail.held_by_you;
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
  const waiting = calls.filter(
    (c) => c.handoff_status === "pending" && !c.ended_at,
  ).length;
  const groups = useMemo(() => groupCalls(calls), [calls]);
  // The queue in three parts, who needs a person first; the search narrows all three.
  const found = useMemo(() => {
    const words = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return groups.filter((g) => {
      const text = g.calls.map((c) => [caller(c), c.phone_last4, CHANNEL[c.channel] || c.channel].join(" ")).join(" ").toLowerCase();
      return words.every((w) => text.includes(w));
    });
  }, [groups, search]);
  const queueParts = [
    { id: "waiting", label: "Chờ nhân viên", list: found.filter((g) => g.waiting) },
    { id: "live", label: "Đang diễn ra", list: found.filter((g) => !g.waiting && g.live) },
    { id: "done", label: "Đã kết thúc", list: found.filter((g) => !g.waiting && !g.live) },
  ].filter((part) => part.list.length > 0);
  const sessions = groupOf(groups, selectedId)?.calls ?? [];

  const Container = embedded ? "section" : "main";
  const Heading = embedded ? "h2" : "h1";
  return (
    <Container
      id={embedded ? undefined : "calls-content"}
      tabIndex={-1}
      className={"shell workspace call-console" + (embedded ? " embedded" : "")}
    >
      {!embedded && (
        <>
        <a className="skip-link" href="#calls-content">Đến nội dung chính</a>
        <header className="topbar">
          <Link className="logo" href="/" aria-label="Quivo, về cửa hàng">
            <Logo height={30} title="" />
          </Link>
          <nav aria-label="Điều hướng nhân viên">
            <Link href="/ban-hang">Bán hàng</Link>
            <Link href="/agent">Hộp thư</Link>
            <Link href="/calls" aria-current="page">Cuộc gọi</Link>
            <Link href="/admin">Quản trị</Link>
            <Link href="/developer">Kỹ thuật</Link>
          </nav>
          <HandoffBell token={connected ? token : ""} onOpen={open} />
          <ThemeToggle />
        </header>
        </>
      )}
      {embedded ? (
        <div className="console-toolbar">
          <span className={"console-waiting" + (waiting ? " is-on" : "")} role="status">
            <span className={"status-dot" + (connected ? "" : " off")} />
            {waiting ? `${waiting} khách đang chờ nhân viên` : "Không ai đang chờ"}
          </span>
          <input
            type="search"
            className="console-search h-5 px-3 text-sm md:h-11 md:px-4 md:text-base rounded-lg border border-gray-300 focus:outline-none"
            aria-label="Tìm khách hoặc số điện thoại"
            placeholder="Tìm tên khách, 4 số cuối, kênh…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <label className="check inline">
            <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} /> Chỉ cuộc đang mở
          </label>
        </div>
      ) : (
      <div className="section-heading console-heading">
          <div>
            <p className="eyebrow">Quivo · Hỗ trợ khách hàng</p>
            <Heading>Cuộc gọi của trợ lý</Heading>
            <p className="console-subtitle">
              Theo dõi trợ lý đang tư vấn, nhận cuộc gọi khi trợ lý chuyển máy, và
              trả lời cùng gợi ý của trợ lý.
            </p>
          </div>
          <div className="console-status">
            <span className={"status-dot" + (connected ? "" : " off")} />{" "}
            {waiting} chờ nhận
          </div>
        </div>
      )}
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
              disabled={!tokenReady}
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Token của role agent hoặc admin"
              required
            />
          </label>
          <label className="check inline">
            <input
              type="checkbox"
              checked={openOnly}
              onChange={(e) => setOpenOnly(e.target.checked)}
            />{" "}
            Chỉ cuộc gọi đang mở
          </label>
          <button type="submit" disabled={!tokenReady || queueLoading} aria-busy={queueLoading}>{queueLoading ? "Đang tải…" : connected ? "Làm mới" : "Kết nối"}</button>
        </form>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
          <button onClick={() => setError("")}>Đóng</button>
        </div>
      )}

      <div className="call-grid">
        <aside className="panel call-queue" aria-busy={queueLoading}>
          <h2>Hàng chờ</h2>
          {calls.length === 0 && (
            <p className="empty">
              {queueLoading ? "Đang tải hàng chờ…" : connected ? "Chưa có cuộc gọi. Cuộc mới sẽ tự xuất hiện tại đây." : "Kết nối bằng token để tải."}
            </p>
          )}
          {queueParts.map((part) => (
            <div key={part.id} className={`queue-part queue-part--${part.id}`}>
              <h3>
                {part.label} <span>{part.list.length}</span>
              </h3>
              {part.list.map(({ key, calls: list, lead: c, waiting: waits }) => {
            const selected = list.some((s) => s.id === selectedId);
                const channels = [...new Set(list.map((s) => CHANNEL[s.channel] || s.channel))];
                return (
                  <div
                    key={key}
                    className={"queue-item" + (selected ? " selected" : "") + (waits ? " waiting" : "")}
                  >
                    <button className="queue-row" aria-pressed={selected} onClick={() => setSelectedId(c.id)}>
                      <span className={"live-dot" + (c.ended_at ? " ended" : "")} />
                      <span className="queue-text">
                        <strong>{caller(list.find((s) => s.customer_label) || c)}</strong>
                        <small>
                          {c.handoff_status === "pending"
                            ? <span className="badge-warn">{c.handoff_reason ? reasonLabel(c.handoff_reason) : "Khách cần gặp nhân viên"}</span>
                            : c.handoff_status === "accepted"
                              ? "Nhân viên đang phụ trách"
                              : `${c.tier === "VERIFIED" ? "Đã xác minh" : "Chưa xác minh"} · ${c.turn_count} lượt`}
                        </small>
                        <small className="queue-meta">
                          <span className={`channel-badge channel-${c.channel}`}>{channels.join(" · ")}</span>
                          {list.length > 1 ? `${list.length} phiên · ` : ""}
                          {ago(list[0].started_at)}
                        </small>
                      </span>
                    </button>
                    {c.handoff_status === "pending" && !c.ended_at && (
                      <button className="small" onClick={() => accept(c.id)}>
                        Nhận
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
          {calls.length > 0 && found.length === 0 && <p className="empty">Không có khách nào khớp “{search}”.</p>}
        </aside>

        <section className="panel call-transcript-pane">
          {detail ? (
            <>
              <div className="call-head">
                <div>
                  <h2>{caller(detail)}</h2>
                  <p>
                    <span className={`channel-badge channel-${detail.channel}`}>{CHANNEL[detail.channel] || detail.channel}</span>
                    <span className={"call-state" + (live && detail.handoff_status === "pending" ? " is-waiting" : live ? " is-live" : "")}>{modeLine}</span>
                  </p>
                </div>
                {live && detail.handoff_status === "pending" && (
                  <button onClick={() => accept(detail.id)}>Nhận cuộc gọi</button>
                )}
              </div>
              <section className="call-info" aria-label="Thông tin cuộc gọi">
                <h3>Thông tin cuộc gọi</h3>
                {sessions.length > 1 && (
                  <nav className="call-sessions" aria-label="Các phiên của khách này">
                    {sessions.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        className={"call-session" + (s.handoff_status === "pending" && !s.ended_at ? " waiting" : "")}
                        aria-current={s.id === detail.id ? "true" : undefined}
                        onClick={() => setSelectedId(s.id)}
                      >
                        <span className={"live-dot" + (s.ended_at ? " ended" : "")} />
                        <span>
                          <strong>{CHANNEL[s.channel] || s.channel}</strong>
                          <small>
                            {when(s.started_at)} · {s.ended_at ? "đã xong" : s.handoff_status === "pending" ? "chờ nhân viên" : "đang mở"} · {s.turn_count} lượt
                          </small>
                        </span>
                      </button>
                    ))}
                  </nav>
                )}
                <CallBrief detail={detail} part="info" />
              </section>
              <CallBrief detail={detail} part="now" />
              <div className="messages staff-messages call-turns">
                {spoken.length === 0 && (
                  <p className="empty">Chưa có lời nào.</p>
                )}
                {turns.map((t) => (
                  <TurnBubble key={t.id} turn={t} />
                ))}
                <div ref={bottom} />
              </div>

              {live && detail.handoff_status === "pending" && (
                <div className="call-action-bar">
                  <span>{detail.handoff_reason ? reasonLabel(detail.handoff_reason) : "Trợ lý đã chuyển máy"}: khách đang chờ người trả lời.</span>
                  <button onClick={() => accept(detail.id)}>Nhận cuộc gọi</button>
                </div>
              )}

              {copilot && (
                <div className="copilot">
                  {warning && (
                    <div className="alert column" role="alert">
                      <span><b>Câu trả lời có thể cam kết sai:</b> {warning.reasons.join(" ")}</span>
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
                        <button
                          className="danger"
                          disabled={sending}
                          onClick={() =>
                            send(warning.content, warning.action, true)
                          }
                        >
                          Vẫn gửi
                        </button>
                      </div>
                    </div>
                  )}
                  {faq && !awaitingReply && (
                    <div className="card">
                      {faq.saved ? (
                        <p>
                          Đã lưu thành FAQ {faq.saved}. Lần sau trợ lý tự trả
                          lời được câu này.
                        </p>
                      ) : (
                        <>
                          <small>
                            Lưu câu trả lời này để trợ lý dùng lần sau?
                          </small>
                          <p>Câu hỏi: {faq.question}</p>
                          <textarea
                            aria-label="Câu trả lời lưu vào FAQ"
                            rows={2}
                            value={faq.answer}
                            onChange={(e) =>
                              setFaq({ ...faq, answer: e.target.value })
                            }
                          />
                          <small>
                            Xóa mọi thông tin riêng của khách trước khi lưu.
                          </small>
                          <div className="buttonrow">
                            <button
                              onClick={() =>
                                run(async (current) => {
                                  const saved = await api<{
                                    chunk_id?: string;
                                  }>(
                                    `/api/agent/calls/${detail.id}/faq`,
                                    token,
                                    {
                                      question: faq.question,
                                      answer: faq.answer,
                                    },
                                  );
                                  if (!current()) return;
                                  setFaq({
                                    ...faq,
                                    saved: saved.chunk_id || "mới",
                                  });
                                })
                              }
                            >
                              Lưu FAQ
                            </button>
                            <button
                              className="secondary"
                              onClick={() => setFaq(null)}
                            >
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
                      {!!suggestion.used_lines?.length && (
                        <small>
                          Dựa trên {suggestion.used_lines.join(", ")}
                        </small>
                      )}
                      {!!suggestion.warnings?.length && (
                        <div className="alert">
                          <b>Kiểm tra trước khi gửi:</b> {suggestion.warnings.join(" ")}
                        </div>
                      )}
                      <div className="buttonrow">
                        <button
                          disabled={sending}
                          onClick={() => send(suggestion.text, "used")}
                        >
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
                        <span
                          className="thumbs"
                          role="group"
                          aria-label="Đánh giá gợi ý"
                        >
                          <button
                            className="secondary"
                            aria-label="Gợi ý tốt"
                            aria-pressed={
                              rated?.text === suggestion.text &&
                              rated.thumb === "up"
                            }
                            onClick={() => rate("up")}
                          >
                            <Icon name="thumb-up" />
                          </button>
                          <button
                            className="secondary"
                            aria-label="Gợi ý chưa tốt"
                            aria-pressed={
                              rated?.text === suggestion.text &&
                              rated.thumb === "down"
                            }
                            onClick={() => rate("down")}
                          >
                            <Icon name="thumb-down" />
                          </button>
                        </span>
                      </div>
                      {rated?.text === suggestion.text && (
                        <small>Đã ghi nhận đánh giá của bạn.</small>
                      )}
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
                        if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                          e.preventDefault();
                          void send(draft, draftFrom);
                        }
                      }}
                      placeholder={
                        awaitingReply ? "Trả lời khách" : "Nhắn cho khách"
                      }
                    />
                    <button type="submit" disabled={sending || !draft.trim()}>
                      Gửi
                    </button>
                  </form>
                  {draftFrom === "edited" && (
                    <small className="hint">
                      Đang sửa gợi ý; phần khác biệt được lưu làm phản hồi.
                    </small>
                  )}
                </div>
              )}

              {live && (
                <div className="buttonrow">
                  {!detail.handoff_status && (
                    <button
                      className="secondary"
                      onClick={() =>
                        run(async (current) => {
                          await api(
                            `/api/agent/calls/${detail.id}/handoff`,
                            token,
                            { reason: "Nhân viên chủ động nhận" },
                          );
                          if (!current()) return;
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
                      run(async (current) => {
                        if (
                          !window.confirm(
                            "Kết thúc cuộc gọi và chạy after-call (ghi nhớ, chấm QA)?",
                          )
                        )
                          return;
                        await api(
                          `/api/agent/calls/${detail.id}/end`,
                          token,
                          {},
                        );
                        if (!current()) return;
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
            <p className="empty" role="status">
              {selectedId == null ? "Chọn một cuộc gọi." : "Đang tải…"}
            </p>
          )}
        </section>

        <aside className="panel call-evidence" aria-label="Bằng chứng">
          <p className="evidence-eyebrow">Bằng chứng</p>
          {detail ? (
            <CallEvidence key={detail.id} detail={detail} token={token} />
          ) : (
            <p className="empty">Chọn một cuộc gọi để xem khách, sản phẩm và đơn hàng.</p>
          )}
        </aside>
      </div>
    </Container>
  );
}

/** How the web cart note under a customer's words starts (cart_note in the AI service). */
const CART_NOTE = "(Giỏ hàng trên website của khách";

/** What a tool looked up, in the consultant's words. */
const LOOKED_UP: Record<string, string> = {
  "catalog.search": "tìm sản phẩm",
  "catalog.get": "thông tin sản phẩm",
  "pricing.get_quote": "báo giá",
  "pricing.quote_order": "báo giá đơn",
  "inventory.check": "tồn kho",
  "delivery.estimate": "ngày giao",
  "order.create": "tạo đơn",
  "order.status": "tra đơn",
  "order.update": "sửa đơn",
  "schedule.callback": "hẹn gọi lại",
  "handoff.transfer": "chuyển máy",
  "knowledge.search": "tài liệu cửa hàng",
  "crm.get_customer": "hồ sơ khách",
};

function TurnBubble({ turn }: { turn: AgentTurn }) {
  if (turn.speaker === "system")
    return (
      <p className="call-note">
        {turn.meta?.joined
          ? `${String(turn.meta.joined)} đã tham gia`
          : turn.content}
      </p>
    );
  const label =
    turn.speaker === "customer"
      ? "Khách"
      : turn.speaker === "human_agent"
        ? "Nhân viên"
        : "Trợ lý AI";
  // What the reply rests on: the products it named, as links, and what it looked up, in plain words.
  const agent = turn.speaker === "agent";
  const looked = agent
    ? [...new Set(((turn.meta?.tool_calls as { name: string }[] | undefined) || [])
        .map((tool) => LOOKED_UP[tool.name.replace("_", ".")] || tool.name))]
    : [];
  const products = agent ? productsOf([turn]) : [];
  // The web cart the shop adds under a customer's words for the assistant (api/routes/conversations.py, cart_note):
  // a consultant reads the words alone, and the cart as links.
  const cartAt = turn.speaker === "customer" ? turn.content.indexOf(CART_NOTE) : -1;
  const words = cartAt >= 0 ? turn.content.slice(0, cartAt).trim() : turn.content;
  const cart = cartAt >= 0 ? [...turn.content.slice(cartAt).matchAll(/\[([A-Za-z0-9-]+)\]/g)].map((m) => ({ sku: m[1] })) : [];
  return (
    <div
      className={
        "message " +
        (turn.speaker === "customer"
          ? "incoming"
          : turn.speaker === "human_agent"
            ? "outgoing human"
            : "outgoing")
      }
    >
      <small>
        {label} ·{" "}
        {new Date(turn.created_at).toLocaleTimeString("vi-VN", {
          hour: "2-digit",
          minute: "2-digit",
        })}
      </small>
      <p>{words}</p>
      {cart.length > 0 && <small className="turn-tools">Giỏ hàng trên web:</small>}
      {cart.length > 0 && <ProductLinks products={cart} compact />}
      {products.length > 0 && <ProductLinks products={products} compact />}
      {looked.length > 0 && <small className="turn-tools">Đã tra: {looked.join(", ")}</small>}
    </div>
  );
}

/** What the consultant reads first. A handover: the assistant's brief, as a card of what to do. What was known of
 * the customer before the call (the Call Brief) is folded, in plain sentences: open it when the chat needs it. */
function CallBrief({ detail, part }: { detail: AgentCallDetail; part: "now" | "info" }) {
  const pendingHandoff = detail.handoff_status === "pending" && !detail.ended_at;
  const opening = detail.brief_object?.is_returning ? detail.brief_object.suggested_opening : undefined;
  // "now", above the chat: a handover still waiting and the warnings. "info", under it: the rest.
  const handover = !!detail.handoff_brief && (part === "now") === pendingHandoff;
  if (part === "now" && !handover && !detail.warnings.length) return null;
  return (
    <div className="call-brief-stack">
      {handover && detail.handoff_brief && (
        <section className={"handoff-card" + (pendingHandoff ? " waiting" : "")} aria-label="Bàn giao từ trợ lý">
          <header>
            <strong>Bàn giao từ trợ lý</strong>
            {detail.handoff_reason && <span className="badge-warn">{reasonLabel(detail.handoff_reason)}</span>}
          </header>
          <HandoffBriefView brief={detail.handoff_brief} turns={detail.turns} />
        </section>
      )}
      {part === "now" &&
        detail.warnings.map((w, i) => (
          <div className="notice" key={i}>
            {w}
          </div>
        ))}
      {part === "info" && (
      <details className="call-known">
        <summary>
          <strong>Đã biết về khách</strong>
          <small>
            {detail.brief.length
              ? `${detail.brief.length} điều từ các lần trước`
              : detail.tier === "UNKNOWN"
                ? "chưa xác định khách"
                : "chưa có gì từ trước"}
          </small>
        </summary>
        {detail.brief.length === 0 ? (
          <p className="empty">
            {detail.tier === "UNKNOWN"
              ? "Chưa xác định khách nên không có gì để mang sang."
              : detail.tier === "AMBIGUOUS"
                ? "Số dùng chung: chưa tải thông tin cho đến khi khách nói mình là ai."
                : "Đã biết khách, chưa có gì để mang sang."}
          </p>
        ) : (
          <ul className="call-known__lines">
            {detail.brief.map((line) => {
              const withheld = line.sensitive && detail.tier !== "VERIFIED";
              return (
                <li key={line.id} className={withheld ? "faded" : ""}>
                  {line.text}
                  {withheld && <small> (ẩn cho đến khi xác minh)</small>}
                </li>
              );
            })}
          </ul>
        )}
        {opening && (
          <p className="call-known__opening">
            <small>Mở đầu gợi ý</small>
            {opening}
          </p>
        )}
      </details>
      )}
    </div>
  );
}

// The brief the assistant hands over, field by field, so the person who takes the call
// does not ask the customer again. Fields it does not know stay readable as JSON.
/** Shown in the side panel ("Cuộc trò chuyện này"), not again in the handover. */
const SIDE_PANEL = new Set(["customer_name", "customer_phone", "channel", "product_advised"]);

const BRIEF_FIELDS: [string, string][] = [
  ["escalation_reason", "Lý do chuyển"],
  ["escalation_reason_detail", "Chi tiết"],
  ["conversation_summary", "Tóm tắt"],
  ["next_action", "Việc cần làm ngay"],
  ["open_questions", "Câu khách chưa được trả lời"],
  ["product_advised", "Sản phẩm đã tư vấn"],
  ["price_quoted_vnd", "Giá đã báo"],
  ["promo_code", "Mã khuyến mãi"],
  ["facts_confirmed", "Đã xác nhận với khách"],
  ["sentiment", "Thái độ"],
  ["customer_name", "Tên khách"],
  ["customer_phone", "Số điện thoại"],
  ["channel", "Kênh"],
];

function briefValue(key: string, value: unknown): React.ReactNode {
  if (key === "escalation_reason" && typeof value === "string") return reasonLabel(value);
  if (key === "price_quoted_vnd" && typeof value === "number") return `${value.toLocaleString("vi-VN")}₫`;
  if (Array.isArray(value)) return value.length ? <ul>{value.map((item, i) => <li key={i}>{String(item)}</li>)}</ul> : "—";
  if (value && typeof value === "object")
    return (
      <ul>
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <li key={k}>{k}: {String(v)}</li>
        ))}
      </ul>
    );
  return String(value);
}

function HandoffBriefView({ brief, turns }: { brief: Record<string, unknown>; turns: AgentTurn[] }) {
  const products = productsOf(turns, brief);
  // The fields a consultant acts on; who and where are in the side panel already.
  const shown = BRIEF_FIELDS.filter(([key]) => !SIDE_PANEL.has(key) && brief[key] !== undefined && brief[key] !== null && brief[key] !== "");
  const known = new Set([...BRIEF_FIELDS.map(([key]) => key), "generated_at"]);
  const rest = Object.fromEntries(Object.entries(brief).filter(([key]) => !known.has(key)));
  return (
    <section className="handoff-brief" aria-label="Bàn giao từ trợ lý">
      <dl className="facts">
        {shown.map(([key, label]) => (
          <React.Fragment key={key}>
            <dt>{label}</dt>
            <dd>{briefValue(key, brief[key])}</dd>
          </React.Fragment>
        ))}
      </dl>
      {products.length > 0 && (
        <>
          <h4>Sản phẩm khách quan tâm</h4>
          <ProductLinks products={products} />
        </>
      )}
      {Object.keys(rest).length > 0 && (
        <details>
          <summary>Các trường khác</summary>
          <pre>{JSON.stringify(rest, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}

function caller(c: AgentCall) {
  if (c.customer_label) return c.customer_label;
  if (c.phone_last4) return `Số đuôi ${c.phone_last4}`;
  if (c.channel_ref) return c.channel_ref;
  return `Cuộc gọi #${c.id}`;
}

/** How long ago, as a consultant reads a queue: "vừa xong", "5 phút trước", "2 giờ trước", then the date. */
function ago(iso: string) {
  const minutes = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (minutes < 1) return "vừa xong";
  if (minutes < 60) return `${minutes} phút trước`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)} giờ trước`;
  return when(iso);
}

function when(iso: string) {
  return new Date(iso).toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });
}
