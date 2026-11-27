"use client";
// The shop's assistant, on every storefront page: chat with the AI agent
// (`/api/conversations/{id}/stream`), a voice call to the hotline in the
// browser (the agent's voice channel), the Zalo link, and the hand-over to a
// person (the agent hands off; staff reply from /calls or /ban-hang).
import { useEffect, useRef, useState } from "react";
import { ChatCartLine, streamTurn, transcribeVoice } from "@/services/api";
import { useSentAt } from "@/lib/sent-at";
import { VoiceCall } from "@/services/voice";
import VoiceCallPanel from "@/features/voice/voice-call";
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
import Icon from "@/components/ui/Icon";
import StepTrail, { mergeStep, type TurnStep } from "@/components/ui/StepTrail";
import { clock, MAX_SECONDS, VoiceRecorder, voiceSupported } from "@/lib/voice-note";

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

type Line = {
  speaker: string;
  text: string;
  /** A voice message recorded here: its recording, and where its words are. */
  voice?: { url: string; seconds: number; state: "listening" | "done" | "failed" };
  /** Not sent to the assistant yet: kept when the conversation is read again from the server. */
  local?: boolean;
};

/** Marks a line the customer spoke (api/routes/conversations.py VOICE_MARK): shown as a voice message. */
const VOICE_MARK = "\u{1F3A4} ";
/** After the last voice message, how long the chat waits for another before the assistant answers all of them. */
const QUIET_MS = 2500;

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
  /** The tool steps of the turn being answered, as they happen; then kept, folded, under the reply they led to. */
  const [liveSteps, setLiveSteps] = useState<TurnStep[]>([]);
  const [doneSteps, setDoneSteps] = useState<Map<string, { steps: TurnStep[]; ms: number }>>(() => new Map());
  const [error, setError] = useState("");
  const [call, setCall] = useState<VoiceCall | null>(null);
  // Testing aid: when messages and calls say they were sent (lib/sent-at.ts).
  const [sentAt, setSentAt] = useSentAt();
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
  // Voice messages, as on Zalo: hold to record, let go to send; the assistant answers when the customer stops.
  const [voiceOk, setVoiceOk] = useState(false);
  const [recording, setRecording] = useState<{ seconds: number; cancel: boolean } | null>(null);
  const [gathering, setGathering] = useState(0);
  const recorder = useRef<VoiceRecorder | null>(null);
  /** The words of voice messages the assistant has not answered yet, in the order said. */
  const notes = useRef<string[]>([]);
  /** Voice messages still being recognised. */
  const listening = useRef(0);
  const flushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** A voice message's words -> its recording, to play it back once the conversation is read again. */
  const audio = useRef(new Map<string, string>());

  useEffect(() => setVoiceOk(voiceSupported()), []);
  useEffect(() => {
    const recordings = audio.current;
    return () => {
      recorder.current?.cancel();
      if (flushTimer.current) clearTimeout(flushTimer.current);
      recordings.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

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
    setLines((old) => [...state.messages, ...old.filter((line) => line.local)]);
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
      forgetVoice();
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
    const typed = message.trim();
    // Retrying the turn whose outcome is unknown sends it as it was; otherwise the voice messages not answered yet
    // go first, in the order said, then what was typed: one turn, one answer.
    const retrying = !!pending.current && pending.current.text === typed;
    const spoken = retrying ? [] : [...notes.current];
    const content = retrying ? typed : [...spoken.map((words) => VOICE_MARK + words), typed].filter(Boolean).join("\n");
    if (!content || sending.current) return;
    if (pending.current && pending.current.text !== content) {
      setError(
        "Lượt trước chưa rõ kết quả. Hãy kiểm tra lại lượt đó trước khi gửi tin mới.",
      );
      return;
    }
    sending.current = true;
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = null;
    notes.current = notes.current.slice(spoken.length);
    setGathering(notes.current.length);
    const sent = new Set(spoken.map((words) => VOICE_MARK + words));
    const shown = retrying ? content : typed;
    const version = revision.current;
    const controller = new AbortController();
    abort.current = controller;
    pending.current ||= { id: newKey(), text: content };
    setText("");
    setError("");
    setBusy(true);
    setLiveSteps([]);
    const startedAt = performance.now();
    let turnSteps: TurnStep[] = [];
    try {
      const s = await ensure();
      if (version !== revision.current) return;
      const human = status === "handed_off";
      setLines((old) => [
        // The voice messages sent now are the server's from here on.
        ...old.map((line) => (line.local && sent.has(line.text) ? { ...line, local: false } : line)),
        ...(shown ? [{ speaker: "customer", text: shown }] : []),
        ...(human ? [] : [{ speaker: "assistant", text: "" }]),
      ]);
      const result = await streamTurn(
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
        {
          signal: controller.signal,
          turnId: pending.current!.id,
          onStep: (step) => {
            if (version !== revision.current) return;
            turnSteps = mergeStep(turnSteps, step);
            setLiveSteps(turnSteps);
          },
        },
      );
      if (version !== revision.current) return;
      const reply = typeof result?.reply === "string" ? result.reply : "";
      if (reply && turnSteps.length) {
        const kept = { steps: turnSteps, ms: Math.round(performance.now() - startedAt) };
        setDoneSteps((old) => new Map(old).set(reply, kept));
      }
      setLiveSteps([]);
      pending.current = null;
      await refresh(s);
    } catch (e) {
      if (version !== revision.current || controller.signal.aborted) return;
      if ([401, 403, 404, 422].includes((e as { status?: number }).status || 0))
        pending.current = null;
      setError(e instanceof Error ? e.message : "Không gửi được tin nhắn");
      setLiveSteps([]);
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

  function forgetVoice() {
    recorder.current?.cancel();
    recorder.current = null;
    setRecording(null);
    notes.current = [];
    setGathering(0);
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = null;
  }

  /** The assistant answers once the customer stops: no recording, nothing being recognised, QUIET_MS of quiet. */
  function scheduleFlush() {
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = null;
    if (!notes.current.length || recorder.current || listening.current) return;
    flushTimer.current = setTimeout(() => {
      flushTimer.current = null;
      // Still answering the turn before: the end of that turn schedules this again.
      if (sending.current || recorder.current || listening.current) return;
      void send("");
    }, QUIET_MS);
  }

  async function startVoice() {
    if (recorder.current || status === "closed") return;
    setError("");
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = null;
    const voice = new VoiceRecorder();
    recorder.current = voice;
    setRecording({ seconds: 0, cancel: false });
    try {
      await voice.start();
    } catch (e) {
      if (recorder.current === voice) recorder.current = null;
      setRecording(null);
      const name = (e as { name?: string })?.name;
      if (name !== "AbortError")
        setError(
          name === "NotAllowedError"
            ? "Trình duyệt chưa cho phép dùng micro. Hãy bật quyền micro cho trang này để gửi tin nhắn thoại."
            : "Không mở được micro trên thiết bị này.",
        );
      scheduleFlush();
    }
  }

  async function stopVoice(cancel: boolean) {
    const voice = recorder.current;
    if (!voice) return;
    recorder.current = null;
    setRecording(null);
    if (cancel) {
      voice.cancel();
      scheduleFlush();
      return;
    }
    const note = await voice.stop().catch(() => null);
    if (!note) {
      setError("Tin nhắn thoại quá ngắn hoặc chưa nghe rõ. Nhấn giữ nút micro trong lúc nói.");
      scheduleFlush();
      return;
    }
    const url = URL.createObjectURL(note.blob);
    const version = revision.current;
    listening.current++;
    setLines((old) => [
      ...old,
      { speaker: "customer", text: "", voice: { url, seconds: note.seconds, state: "listening" }, local: true },
    ]);
    try {
      const s = await ensure();
      const heard = await transcribeVoice(s, note.pcm);
      if (version !== revision.current) return;
      const words = heard.text.trim();
      if (!words) throw new Error("Chưa nghe rõ tin nhắn thoại. Bạn nói lại giúp nhé.");
      audio.current.set(words, url);
      notes.current.push(words);
      setGathering(notes.current.length);
      setLines((old) =>
        old.map((line) =>
          line.voice?.url === url ? { ...line, text: VOICE_MARK + words, voice: { ...line.voice, state: "done" } } : line,
        ),
      );
    } catch (e) {
      if (version !== revision.current) return;
      setLines((old) =>
        old.map((line) => (line.voice?.url === url ? { ...line, local: false, voice: { ...line.voice, state: "failed" } } : line)),
      );
      setError(e instanceof Error ? e.message : "Không nhận dạng được tin nhắn thoại.");
    } finally {
      listening.current--;
      if (version === revision.current) scheduleFlush();
    }
  }

  // The turn before is answered: the voice messages said meanwhile go now (after the same quiet).
  useEffect(() => {
    if (!busy) scheduleFlush();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy]);

  // The recording's clock; a minute is the most a voice message holds, then it is sent.
  const isRecording = recording !== null;
  useEffect(() => {
    if (!isRecording) return;
    const timer = setInterval(() => {
      const voice = recorder.current;
      if (!voice) return;
      const seconds = voice.elapsed();
      if (seconds >= MAX_SECONDS) void stopVoice(false);
      else setRecording((old) => old && { ...old, seconds });
    }, 200);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRecording]);

  /** Let go away from the button (up, or far to the left) cancels, as on Zalo. */
  function away(event: React.PointerEvent<HTMLButtonElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    return event.clientY < box.top - 60 || event.clientX < box.left - 140;
  }

  async function restart() {
    revision.current++;
    abort.current?.abort();
    pending.current = null;
    forgetVoice();
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
          <header className={`s-chat-head${status === "handed_off" ? " s-chat-head-human" : ""}`}>
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
                <Icon name="phone" />
              </button>
              <button
                className="s-icon-btn"
                aria-label="Đóng"
                onClick={() => shopContext.closeChat()}
              >
                <Icon name="close" />
              </button>
            </div>
          </header>
          <div className="s-chat-clock">
            <label>
              <span>Thời điểm gửi</span>
              <input
                type="datetime-local"
                value={sentAt}
                min="2026-01-01T00:00"
                max="2027-12-31T23:59"
                title="Thử agent ở một ngày giờ khác (tồn kho, khuyến mãi, giờ làm việc). Để trống: giờ của cửa hàng."
                disabled={call !== null}
                onChange={(event) => setSentAt(event.target.value)}
              />
            </label>
            {sentAt ? (
              <button type="button" className="s-chat-clock-reset" disabled={call !== null} onClick={() => setSentAt("")}>
                Dùng giờ cửa hàng
              </button>
            ) : (
              <small>Giờ cửa hàng</small>
            )}
          </div>
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
                {line.speaker === "assistant" &&
                  (busy && i === lines.length - 1 ? (
                    <StepTrail steps={liveSteps} done={false} />
                  ) : (
                    doneSteps.has(line.text) && (
                      <StepTrail
                        steps={doneSteps.get(line.text)!.steps}
                        done
                        elapsedMs={doneSteps.get(line.text)!.ms}
                      />
                    )
                  ))}
                {line.speaker === "customer" && (line.voice || line.text.includes(VOICE_MARK)) ? (
                  <CustomerWords line={line} audio={audio.current} />
                ) : (
                  <p>
                    {line.text ||
                      (busy && i === lines.length - 1 ? (
                        <span className="s-typing">Đang soạn câu trả lời…</span>
                      ) : (
                        ""
                      ))}
                  </p>
                )}
                {/* Once the reply is complete, the products it names: picture, price, link. */}
                {line.speaker !== "customer" &&
                  line.speaker !== "system" &&
                  !(busy && i === lines.length - 1) && (
                    <ChatProducts
                      text={line.text}
                      earlier={lines
                        .slice(0, i)
                        .filter((before) => before.speaker !== "customer" && before.speaker !== "system")
                        .map((before) => before.text)}
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
            {/* Who answers now: a person has the conversation and has read it, so nothing needs repeating. */}
            {status === "handed_off" && (
              <p className="s-chat-handoff">
                Đã chuyển cho nhân viên. Nhân viên đã xem cuộc trò chuyện này, bạn không cần nhắc lại.
              </p>
            )}
            {gathering > 0 && !busy && !recording && (
              <p className="s-voice-hint" role="status">
                Đã nhận {gathering} tin nhắn thoại. Trợ lý sẽ trả lời khi bạn gửi xong.
              </p>
            )}
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
              {recording ? (
                <div className={"s-recording" + (recording.cancel ? " is-cancel" : "")} role="status" aria-live="polite">
                  <span className="s-rec-dot" aria-hidden="true" />
                  <b>{clock(recording.seconds)}</b>
                  <span>{recording.cancel ? "Thả ra để hủy" : "Thả ra để gửi · kéo lên để hủy"}</span>
                </div>
              ) : (
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
              )}
              {voiceOk && !text.trim() ? (
                <button
                  type="button"
                  className={"s-mic" + (recording ? " is-on" : "") + (recording?.cancel ? " is-cancel" : "")}
                  aria-label="Nhấn giữ để ghi âm tin nhắn thoại"
                  title="Nhấn giữ để ghi âm, thả ra để gửi"
                  onPointerDown={(event) => {
                    if (event.button !== 0) return;
                    event.preventDefault();
                    event.currentTarget.setPointerCapture(event.pointerId);
                    void startVoice();
                  }}
                  onPointerMove={(event) => {
                    if (!recorder.current) return;
                    const cancel = away(event);
                    setRecording((old) => (old && old.cancel !== cancel ? { ...old, cancel } : old));
                  }}
                  onPointerUp={(event) => void stopVoice(away(event))}
                  onPointerCancel={() => void stopVoice(true)}
                  onKeyDown={(event) => {
                    if ((event.key === " " || event.key === "Enter") && !event.repeat) {
                      event.preventDefault();
                      void startVoice();
                    } else if (event.key === "Escape" && recorder.current) {
                      event.preventDefault();
                      event.stopPropagation();
                      void stopVoice(true);
                    }
                  }}
                  onKeyUp={(event) => {
                    if (event.key === " " || event.key === "Enter") {
                      event.preventDefault();
                      void stopVoice(false);
                    }
                  }}
                  onContextMenu={(event) => event.preventDefault()}
                >
                  <Icon name="mic" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={busy || !text.trim()}
                  aria-label="Gửi"
                >
                  Gửi
                </button>
              )}
            </form>
          )}
          <footer className="s-chat-foot">
            <a href={`tel:${HOTLINE.replace(/\s/g, "")}`}><Icon name="phone" size={16} /> {HOTLINE}</a>
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

/** What the customer said: typed lines as text, voice messages with their recording (when this browser made it)
 *  and the words the recogniser heard. */
function CustomerWords({ line, audio }: { line: Line; audio: Map<string, string> }) {
  if (line.voice && line.voice.state !== "done")
    return (
      <div className="s-voice">
        <span className="s-voice-head">
          <Icon name="mic" size={14} /> Tin nhắn thoại · {clock(line.voice.seconds)}
        </span>
        <audio controls preload="metadata" src={line.voice.url} />
        <span className={"s-voice-text" + (line.voice.state === "failed" ? " is-failed" : "")}>
          {line.voice.state === "listening" ? "Đang nghe…" : "Chưa nhận dạng được, bạn gửi lại giúp nhé"}
        </span>
      </div>
    );
  return (
    <>
      {line.text.split("\n").map((part, i) => {
        if (!part.startsWith(VOICE_MARK)) return part ? <p key={i}>{part}</p> : null;
        const words = part.slice(VOICE_MARK.length);
        const url = line.voice?.url || audio.get(words);
        return (
          <div key={i} className="s-voice">
            <span className="s-voice-head">
              <Icon name="mic" size={14} /> Tin nhắn thoại{line.voice ? ` · ${clock(line.voice.seconds)}` : ""}
            </span>
            {url && <audio controls preload="metadata" src={url} />}
            <span className="s-voice-text">{words}</span>
          </div>
        );
      })}
    </>
  );
}
