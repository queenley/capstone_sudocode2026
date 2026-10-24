"use client";
// The shop's assistant, on every storefront page: chat with the AI agent
// (`/api/conversations/{id}/stream`), a voice call to the hotline in the
// browser (the agent's voice channel), the Zalo link, and the hand-over to a
// person (the agent hands off; staff reply from /calls or /ban-hang).
import { useEffect, useRef, useState } from "react";
import { streamTurn } from "@/services/api";
import { VoiceCall } from "@/services/voice";
import VoiceCallPanel from "@/features/voice-call";
import ChatProducts from "@/components/shop/ChatProducts";
import { loadConversation, newSession, openSession, ShopSession } from "@/lib/session";
import { shopContext, useShopContext } from "@/lib/shop-context";
import { HOTLINE, ZALO_URL } from "@/lib/contact";

type Line = { speaker: string; text: string };

const SUGGESTIONS = [
  "Tư vấn máy lọc không khí cho phòng 25m²",
  "Giày chạy bộ nào đang giảm giá?",
  "Chính sách đổi trả thế nào?",
  "Kiểm tra đơn hàng của tôi",
];

const SPEAKER: Record<string, string> = { customer: "Bạn", assistant: "Trợ lý AI", agent: "Nhân viên", system: "Hệ thống" };

export default function ChatWidget() {
  const { chatOpen, sku, productName } = useShopContext();
  const [session, setSession] = useState<ShopSession | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [call, setCall] = useState<VoiceCall | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  async function ensure(): Promise<ShopSession> {
    if (session && (status === "open" || status === "handed_off")) return session;
    const opened = await openSession();
    setSession(opened);
    const state = await loadConversation(opened);
    setLines(state.messages);
    setStatus(state.status);
    return opened;
  }

  async function refresh(s: ShopSession) {
    const state = await loadConversation(s);
    setLines(state.messages);
    setStatus(state.status);
  }

  // Open: resume this tab's conversation and take any question a page handed over.
  useEffect(() => {
    if (!chatOpen) return;
    const draft = shopContext.takeDraft();
    if (draft) setText(draft);
    ensure().catch((e) => setError(e.message));
    setTimeout(() => input.current?.focus(), 50);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatOpen]);

  // Braces matter: newer Chromium returns a Promise from scrollIntoView, and an
  // effect may only return a cleanup function.
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, busy]);

  // While a person has the conversation, their replies arrive by polling.
  useEffect(() => {
    if (!session || status !== "handed_off" || !chatOpen) return;
    const timer = setInterval(() => refresh(session).catch(() => undefined), 3000);
    return () => clearInterval(timer);
  }, [session, status, chatOpen]);

  async function send(message: string) {
    const content = message.trim();
    if (!content || busy) return;
    setText("");
    setError("");
    setBusy(true);
    try {
      const s = await ensure();
      const human = status === "handed_off";
      setLines((old) => [...old, { speaker: "customer", text: content }, ...(human ? [] : [{ speaker: "assistant", text: "" }])]);
      await streamTurn(s, content, sku, (reply) =>
        setLines((old) => (human ? old : [...old.slice(0, -1), { speaker: "assistant", text: reply }])),
      );
      await refresh(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không gửi được tin nhắn");
      setLines((old) => (old.length && old[old.length - 1].speaker === "assistant" && !old[old.length - 1].text ? old.slice(0, -1) : old));
    } finally {
      setBusy(false);
    }
  }

  async function restart() {
    setError("");
    const s = await newSession();
    setSession(s);
    setLines([]);
    setStatus("open");
  }

  return (
    <>
      {!chatOpen && (
        <button className="s-chat-fab" onClick={() => shopContext.openChat()} aria-label="Chat với trợ lý">
          <span className="s-chat-fab-dot" />
          Tư vấn ngay
        </button>
      )}
      {chatOpen && (
        <section className="s-chat" aria-label="Trò chuyện với cửa hàng">
          <header className="s-chat-head">
            <div>
              <strong>Trợ lý Tiếp Nối</strong>
              <span>
                {status === "handed_off"
                  ? "Nhân viên đang hỗ trợ bạn"
                  : status === "closed"
                    ? "Cuộc trò chuyện đã kết thúc"
                    : "AI trả lời ngay · có nhân viên khi cần"}
              </span>
            </div>
            <div className="s-chat-head-actions">
              <button
                className="s-icon-btn"
                title="Gọi thoại với cửa hàng ngay trên trình duyệt"
                aria-label="Gọi thoại"
                disabled={busy || call !== null || status === "closed"}
                onClick={() => {
                  // The audio context must be created inside the click (Safari).
                  const line = new VoiceCall().prepare();
                  ensure()
                    .then(() => setCall(line))
                    .catch((e) => {
                      line.stop();
                      setError(e.message);
                    });
                }}
              >
                ☏
              </button>
              <button className="s-icon-btn" aria-label="Đóng" onClick={() => shopContext.closeChat()}>
                ✕
              </button>
            </div>
          </header>
          {sku && (
            <div className="s-chat-context">
              Đang xem: <b>{productName || sku}</b>
            </div>
          )}
          <div className="s-chat-body" aria-live="polite">
            {lines.length === 0 && (
              <div className="s-chat-welcome">
                <p>Xin chào! Em là trợ lý tự động của Tiếp Nối. Anh/chị cần tư vấn sản phẩm, giá hay kiểm tra đơn hàng ạ?</p>
                <div className="s-chips">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} className="s-chip" onClick={() => send(s)} disabled={busy}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {lines.map((line, i) => (
              <div key={i} className={`s-msg s-msg-${line.speaker === "customer" ? "me" : line.speaker}`}>
                {line.speaker !== "customer" && <span className="s-msg-who">{SPEAKER[line.speaker] || line.speaker}</span>}
                <p>{line.text || (busy && i === lines.length - 1 ? <span className="s-typing">Đang soạn câu trả lời…</span> : "")}</p>
                {/* Once the reply is complete, the products it names: picture, price, link. */}
                {line.speaker !== "customer" && line.speaker !== "system" && !(busy && i === lines.length - 1) && (
                  <ChatProducts
                    text={line.text}
                    onShow={i === lines.length - 1 ? () => bottom.current?.scrollIntoView({ behavior: "smooth" }) : undefined}
                  />
                )}
              </div>
            ))}
            <div ref={bottom} />
          </div>
          {error && (
            <div className="s-chat-error" role="alert">
              {error}
            </div>
          )}
          {status === "closed" ? (
            <div className="s-chat-closed">
              <button className="s-btn" onClick={() => restart().catch((e) => setError(e.message))}>
                Bắt đầu cuộc trò chuyện mới
              </button>
            </div>
          ) : (
            <form
              className="s-chat-input"
              onSubmit={(e) => {
                e.preventDefault();
                send(text);
              }}
            >
              <textarea
                ref={input}
                aria-label="Tin nhắn"
                rows={1}
                placeholder="Nhập câu hỏi của bạn…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(text);
                  }
                }}
              />
              <button type="submit" disabled={busy || !text.trim()} aria-label="Gửi">
                Gửi
              </button>
            </form>
          )}
          <footer className="s-chat-foot">
            <a href={`tel:${HOTLINE.replace(/\s/g, "")}`}>☏ {HOTLINE}</a>
            {ZALO_URL && (
              <a href={ZALO_URL} target="_blank" rel="noreferrer">
                Chat qua Zalo
              </a>
            )}
          </footer>
        </section>
      )}
      {call && session && (
        <VoiceCallPanel
          call={call}
          conversationId={session.conversation_id}
          token={session.conversation_token}
          onClose={() => {
            setCall(null);
            refresh(session).catch(() => undefined);
          }}
        />
      )}
    </>
  );
}
