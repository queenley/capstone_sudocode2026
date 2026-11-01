"use client";
// The shop's assistant, on every storefront page: chat with the AI agent
// (`/api/conversations/{id}/stream`), a voice call to the hotline in the
// browser (the agent's voice channel), the Zalo link, and the hand-over to a
// person (the agent hands off; staff reply from /calls or /ban-hang).
import { useEffect, useRef, useState } from "react";
import { ChatCartLine, streamTurn } from "@/services/api";
import { VoiceCall } from "@/services/voice";
import VoiceCallPanel from "@/features/voice-call";
import ChatProducts from "@/components/shop/ChatProducts";
import {
  loadConversation,
  newSession,
  openSession,
  ShopSession,
} from "@/lib/session";
import { shopContext, useShopContext } from "@/lib/shop-context";
import { HOTLINE, ZALO_URL } from "@/lib/contact";
import { cart } from "@/lib/cart";
import { variantLabel } from "@/lib/catalog";
import { catalogOnce } from "@/lib/mentions";
import { account as accountStore, useAccount } from "@/lib/account";
import { newKey } from "@/lib/cart-items";
import ReturningWelcome from "@/components/shop/ReturningWelcome";

/** The cart in this browser with the names the shop shows, for the assistant ("giỏ hàng tôi có gì").
 *  Signed in, the assistant reads the account's cart itself (its account_cart tool): nothing is sent. */
async function cartForChat(): Promise<ChatCartLine[] | null> {
  if (cart.signedIn()) return null;
  const lines = cart.lines();
  if (!lines.length) return [];
  const products = await catalogOnce().catch(() => []);
  const rows = new Map(
    products.flatMap((p) =>
      p.variants.map((row) => [row.sku_code, row] as const),
    ),
  );
  return lines.map(({ sku, qty }) => {
    const row = rows.get(sku);
    const variant = row ? variantLabel(row) : "";
    return {
      sku,
      qty,
      ...(row ? { name: variant ? `${row.name} (${variant})` : row.name } : {}),
    };
  });
}

type Line = { speaker: string; text: string };

const SUGGESTIONS = [
  "Tư vấn máy lọc không khí cho phòng 25m²",
  "Giày chạy bộ nào đang giảm giá?",
  "Chính sách đổi trả thế nào?",
  "Kiểm tra đơn hàng của tôi",
];

const SPEAKER: Record<string, string> = {
  customer: "Bạn",
  assistant: "Trợ lý AI",
  agent: "Nhân viên",
  system: "Hệ thống",
};

export default function ChatWidget() {
  const { account, status } = useAccount();
  return <ConversationWidget key={`${account?.customer_id || "guest"}:${accountStore.revision()}`} customerId={status === "signed-in" ? account?.customer_id : undefined} />;
}

function ConversationWidget({ customerId }: { customerId?: string }) {
  const { chatOpen, sku, productName } = useShopContext();
  const [session, setSession] = useState<ShopSession | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [call, setCall] = useState<VoiceCall | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const fab = useRef<HTMLButtonElement>(null);
  const callButton = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const revision = useRef(0);
  const sending = useRef(false);
  const abort = useRef<AbortController | null>(null);
  const pending = useRef<{ id: string; text: string } | null>(null);
  const currentSession = useRef<ShopSession | null>(null);

  useEffect(
    () => () => {
      revision.current++;
      abort.current?.abort();
    },
    [],
  );
  useEffect(
    () => () => {
      call?.stop();
    },
    [call],
  );

  async function ensure(): Promise<ShopSession> {
    const version = revision.current;
    if (session && (status === "open" || status === "handed_off"))
      return session;
    const opened = await openSession();
    const state = await loadConversation(opened);
    if (version !== revision.current)
      throw new DOMException("Conversation changed", "AbortError");
    currentSession.current = opened;
    setSession(opened);
    setLines(state.messages);
    setStatus(state.status);
    return opened;
  }

  async function refresh(s: ShopSession) {
    const version = revision.current;
    const state = await loadConversation(s);
    if (
      version !== revision.current ||
      currentSession.current?.conversation_id !== s.conversation_id
    )
      return;
    setLines(state.messages);
    setStatus(state.status);
  }

  // Open: resume this tab's conversation and take any question a page handed over.
  useEffect(() => {
    if (!chatOpen) return;
    const draft = shopContext.takeDraft();
    if (draft) setText(draft);
    const version = revision.current;
    ensure().catch((e) => {
      if (version === revision.current && e?.name !== "AbortError")
        setError(e.message);
    });
    const timer = setTimeout(() => input.current?.focus(), 50);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatOpen]);

  // On a phone the open chat covers the page: the page behind it must not scroll.
  useEffect(() => {
    document.documentElement.classList.toggle("s-chat-open", chatOpen);
    return () => document.documentElement.classList.remove("s-chat-open");
  }, [chatOpen]);

  useEffect(() => {
    if (!chatOpen) return;
    const panel = dialog.current!;
    panel.showModal();
    return () => panel.close();
  }, [chatOpen]);

  // Signing in or out starts a new conversation, as the new person (lib/account.ts).
  useEffect(() => {
    const reset = () => {
      revision.current++;
      abort.current?.abort();
      sending.current = false;
      pending.current = null;
      currentSession.current = null;
      setBusy(false);
      setCall((old) => {
        old?.stop();
        return null;
      });
      setSession(null);
      setLines([]);
      setStatus("");
    };
    window.addEventListener("shop-conversation-reset", reset);
    return () => window.removeEventListener("shop-conversation-reset", reset);
  }, []);

  // Braces matter: newer Chromium returns a Promise from scrollIntoView, and an
  // effect may only return a cleanup function.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [lines, busy]);

  // While a person has the conversation, their replies arrive by polling.
  useEffect(() => {
    if (!session || status !== "handed_off" || !chatOpen) return;
    const timer = setInterval(
      () => refresh(session).catch(() => undefined),
      3000,
    );
    return () => clearInterval(timer);
  }, [session, status, chatOpen]);

  async function send(message: string) {
    const content = message.trim();
    if (!content || sending.current) return;
    if (pending.current && pending.current.text !== content) {
      setError(
        "Lượt trước chưa rõ kết quả. Hãy kiểm tra lại lượt đó trước khi gửi tin mới.",
      );
      return;
    }
    sending.current = true;
    const version = revision.current;
    const controller = new AbortController();
    abort.current = controller;
    pending.current ||= { id: newKey(), text: content };
    setText("");
    setError("");
    setBusy(true);
    try {
      const s = await ensure();
      if (version !== revision.current) return;
      const human = status === "handed_off";
      setLines((old) => [
        ...old,
        { speaker: "customer", text: content },
        ...(human ? [] : [{ speaker: "assistant", text: "" }]),
      ]);
      await streamTurn(
        s,
        content,
        sku,
        (reply) => {
          if (version === revision.current)
            setLines((old) =>
              human
                ? old
                : [...old.slice(0, -1), { speaker: "assistant", text: reply }],
            );
        },
        await cartForChat(),
        { signal: controller.signal, turnId: pending.current!.id },
      );
      if (version !== revision.current) return;
      pending.current = null;
      await refresh(s);
    } catch (e) {
      if (version !== revision.current || controller.signal.aborted) return;
      if ([401, 403, 404, 422].includes((e as { status?: number }).status || 0))
        pending.current = null;
      setError(e instanceof Error ? e.message : "Không gửi được tin nhắn");
      setLines((old) =>
        old.length &&
        old[old.length - 1].speaker === "assistant" &&
        !old[old.length - 1].text
          ? old.slice(0, -1)
          : old,
      );
    } finally {
      if (version !== revision.current) return;
      sending.current = false;
      setBusy(false);
    }
  }

  async function restart() {
    revision.current++;
    abort.current?.abort();
    pending.current = null;
    setError("");
    const s = await newSession();
    currentSession.current = s;
    setSession(s);
    setLines([]);
    setStatus("open");
  }

  return (
    <>
      {customerId && <ReturningWelcome customerId={customerId} chatOpen={chatOpen}
        onDismiss={() => fab.current?.focus()}
        onContinue={() => { fab.current?.focus(); shopContext.openChat(); }} />}
        <button
          ref={fab}
          className="s-chat-fab"
          hidden={chatOpen}
          onClick={() => shopContext.openChat()}
          aria-label="Chat với trợ lý"
          aria-haspopup="dialog"
        >
          <span className="s-chat-fab-dot" />
          <svg
            className="s-chat-fab-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
            <path d="M8.5 11h.01M12 11h.01M15.5 11h.01" />
          </svg>
          <span className="s-chat-fab-label">Tư vấn ngay</span>
        </button>
      {chatOpen && (
        <dialog ref={dialog} className="s-chat" aria-label="Trò chuyện với cửa hàng" onCancel={(event) => {
          event.preventDefault();
          shopContext.closeChat();
        }}>
          <header className="s-chat-head">
            <div>
              <strong>Trợ lý Quivo</strong>
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
                ref={callButton}
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
              <button
                className="s-icon-btn"
                aria-label="Đóng"
                onClick={() => shopContext.closeChat()}
              >
                ✕
              </button>
            </div>
          </header>
          {sku && (
            <div className="s-chat-context">
              Đang xem: <b>{productName || sku}</b>
            </div>
          )}
          <div className="s-chat-body" role="log" aria-label="Tin nhắn trong cuộc trò chuyện" aria-live="polite" aria-relevant="additions text" aria-busy={busy}>
            {lines.length === 0 && (
              <div className="s-chat-welcome">
                <p>
                  Xin chào! Em là trợ lý tự động của Quivo. Anh/chị cần tư vấn
                  sản phẩm, giá hay kiểm tra đơn hàng ạ?
                </p>
                <div className="s-chips">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      className="s-chip"
                      onClick={() => send(s)}
                      disabled={busy}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {lines.map((line, i) => (
              <div
                key={i}
                className={`s-msg s-msg-${line.speaker === "customer" ? "me" : line.speaker}`}
              >
                {line.speaker !== "customer" && (
                  <span className="s-msg-who">
                    {SPEAKER[line.speaker] || line.speaker}
                  </span>
                )}
                <p>
                  {line.text ||
                    (busy && i === lines.length - 1 ? (
                      <span className="s-typing">Đang soạn câu trả lời…</span>
                    ) : (
                      ""
                    ))}
                </p>
                {/* Once the reply is complete, the products it names: picture, price, link. */}
                {line.speaker !== "customer" &&
                  line.speaker !== "system" &&
                  !(busy && i === lines.length - 1) && (
                    <ChatProducts
                      text={line.text}
                      onShow={
                        i === lines.length - 1
                          ? () =>
                              bottom.current?.scrollIntoView({
                                block: "nearest",
                              })
                          : undefined
                      }
                    />
                  )}
              </div>
            ))}
            <div ref={bottom} />
          </div>
          {error && (
            <div className="s-chat-error" role="alert">
              {error}
              {pending.current && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void send(pending.current!.text)}
                >
                  Kiểm tra lại lượt trước
                </button>
              )}
            </div>
          )}
          {status === "closed" ? (
            <div className="s-chat-closed">
              <button
                className="s-btn"
                onClick={() => restart().catch((e) => setError(e.message))}
              >
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
                autoFocus
                aria-label="Tin nhắn"
                rows={1}
                placeholder="Nhập câu hỏi của bạn…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    send(text);
                  }
                }}
              />
              <button
                type="submit"
                disabled={busy || !text.trim()}
                aria-label="Gửi"
              >
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
        </dialog>
      )}
      {call && session && (
        <VoiceCallPanel
          call={call}
          conversationId={session.conversation_id}
          token={session.conversation_token}
          onClose={() => {
            setCall(null);
            requestAnimationFrame(() => callButton.current?.focus());
            refresh(session).catch(() => undefined);
          }}
        />
      )}
    </>
  );
}
