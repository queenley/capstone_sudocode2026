"use client";
// Tells the staff on duty that a conversation waits for a person (handoff
// pending): a red bell with the count in the header, a red toast, a short
// tone, the count in the tab title and, once the consultant allows it, a
// browser notification that reaches them in another tab. Each call alerts
// once, the first time it is seen waiting, including the ones already waiting
// when the page opens.
//
// Who waits comes pushed from `/api/agent/handoffs/stream` (server-sent
// events; the service hears handoffs on Kafka or in-process). The stream is
// read with fetch, since EventSource cannot send the staff token. When the
// stream cannot be opened the bell polls the queue every few seconds instead,
// and tries the stream again.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, AgentCall } from "@/services/api";
import { reasonLabel } from "@/features/handoff-reasons";
import Icon from "@/components/ui/Icon";

const CHANNEL: Record<string, string> = { web: "Web chat", zalo: "Zalo", hotline: "Hotline", facebook: "Facebook" };
const POLL_MS = 5000;
type Permission = NotificationPermission | "unsupported";
/** Where the bell hears from: pushed through Kafka, pushed by the service's own poll, or polled by this page. */
export type AlertSource = "kafka" | "polling" | "fallback" | "off";
const SOURCE: Record<AlertSource, string> = {
  kafka: "Trực tiếp qua Kafka",
  polling: "Trực tiếp, máy chủ đọc lại mỗi 5 giây",
  fallback: "Mất kết nối trực tiếp, trang tự tải lại mỗi 5 giây",
  off: "Chưa kết nối",
};

/** Why the call waits, as the consultant reads it. */
export function handoffReason(c: AgentCall): string {
  const reason = (c.handoff_reason || "").replace(/^The assistant handed over:\s*/i, "");
  return reason ? reasonLabel(reason) : "Cần nhân viên hỗ trợ";
}

function who(c: AgentCall): string {
  return c.customer_label || (c.phone_last4 ? `Khách ···${c.phone_last4}` : `Cuộc gọi #${c.id}`);
}

function waited(c: AgentCall, now: number): string {
  const since = Date.parse(c.handoff_requested_at || c.started_at);
  const minutes = Math.max(0, Math.floor((now - since) / 60000));
  return minutes < 1 ? "vừa xong" : minutes < 60 ? `chờ ${minutes} phút` : `chờ ${Math.floor(minutes / 60)} giờ`;
}

/** Two short beeps; silent until the page has had a click (the browser's autoplay rule). */
function chime() {
  try {
    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioCtx();
    [0, 0.22].forEach((at) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.15, ctx.currentTime + at);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + at + 0.18);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + at);
      osc.stop(ctx.currentTime + at + 0.2);
    });
    setTimeout(() => void ctx.close(), 800);
  } catch {
    // no audio: the bell, the toast and the title still tell
  }
}

/** One server-sent event block: its name and its data lines; comments (": keepalive") give null. */
export function readEvent(block: string): { event: string; data: string } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

/** Who waits for a consultant, kept current from the stream, or by polling when it is down. */
export function useHandoffStream(token: string) {
  const [waiting, setWaiting] = useState<AgentCall[] | null>(null);
  const [source, setSource] = useState<AlertSource>("off");

  useEffect(() => {
    setWaiting(null);
    setSource("off");
    if (!token) return;
    let stopped = false;
    let failures = 0;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const list = await api<AgentCall[]>("/api/agent/calls?open_only=true&limit=50", token);
        if (!stopped) setWaiting(list.filter((c) => c.handoff_status === "pending" && !c.ended_at));
      } catch {
        // the next try tells
      }
    };

    const listen = async () => {
      controller = new AbortController();
      let heard = false;
      let refused = false;
      try {
        const response = await fetch("/backend/api/agent/handoffs/stream", {
          headers: { Authorization: "Bearer " + token, Accept: "text/event-stream" },
          cache: "no-store",
          signal: controller.signal,
        });
        refused = response.status === 401 || response.status === 403;
        if (!response.ok || !response.body) throw new Error(String(response.status));
        const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = "";
        while (!stopped) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += value;
          let at;
          while ((at = buffer.search(/\r?\n\r?\n/)) >= 0) {
            const event = readEvent(buffer.slice(0, at));
            buffer = buffer.slice(at).replace(/^\r?\n\r?\n/, "");
            if (event?.event !== "handoffs") continue;
            const data = JSON.parse(event.data) as { source?: string; waiting: AgentCall[] };
            heard = true;
            failures = 0;
            setWaiting(data.waiting);
            setSource(data.source === "kafka" ? "kafka" : "polling");
          }
        }
      } catch {
        // closed, refused or never opened: below decides what next
      }
      if (stopped || refused) return;
      if (!heard) failures++;
      if (failures >= 2) {
        setSource("fallback");
        await poll();
      }
      // The proxy ends a stream after two minutes: open the next at once; after failures, poll at the poll's pace.
      if (!stopped) timer = setTimeout(listen, heard ? 200 : failures >= 2 ? POLL_MS : 1000);
    };

    void listen();
    return () => {
      stopped = true;
      controller?.abort();
      clearTimeout(timer);
    };
  }, [token]);

  return { waiting, source };
}

export function useHandoffAlerts(calls: AgentCall[] | null) {
  const seen = useRef<Set<number>>(new Set());
  const title = useRef("");
  const [toasts, setToasts] = useState<AgentCall[]>([]);
  const [permission, setPermission] = useState<Permission>("unsupported");

  const waiting = useMemo(() => (calls || []).filter((c) => c.handoff_status === "pending" && !c.ended_at), [calls]);

  useEffect(() => {
    setPermission(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
    title.current = document.title;
    return () => {
      document.title = title.current;
    };
  }, []);

  useEffect(() => {
    if (!calls) return;
    const added = waiting.filter((c) => !seen.current.has(c.id));
    added.forEach((c) => seen.current.add(c.id));
    // A toast leaves when its call no longer waits (someone took it, or it ended).
    setToasts((current) => [...added, ...current.filter((t) => waiting.some((w) => w.id === t.id))].slice(0, 4));
    if (!added.length) return;
    chime();
    if (typeof Notification !== "undefined" && Notification.permission === "granted")
      for (const c of added)
        new Notification("Khách cần nhân viên", {
          body: `${who(c)} · ${CHANNEL[c.channel] || c.channel} · ${handoffReason(c)}`,
          tag: `handoff-${c.id}`,
        });
  }, [calls, waiting]);

  useEffect(() => {
    if (!title.current) return;
    document.title = waiting.length ? `(${waiting.length}) Khách chờ · ${title.current}` : title.current;
  }, [waiting.length]);

  const dismiss = useCallback((id: number) => setToasts((current) => current.filter((t) => t.id !== id)), []);
  const enable = useCallback(async () => {
    if (typeof Notification === "undefined") return;
    setPermission(await Notification.requestPermission());
  }, []);

  return { waiting, toasts, dismiss, permission, enable };
}

export function HandoffToasts({
  alerts,
  onOpen,
}: {
  alerts: ReturnType<typeof useHandoffAlerts>;
  onOpen: (id: number) => void;
}) {
  const { toasts, dismiss } = alerts;
  if (!toasts.length || typeof document === "undefined") return null;
  // On the body: a header with a backdrop filter would otherwise hold the "fixed" toasts at its own top.
  return createPortal(
    <div className="handoff-toasts" role="status" aria-live="assertive">
      {toasts.map((c) => (
        <div key={c.id} className="handoff-toast">
          <strong>Khách cần nhân viên</strong>
          <span>
            {who(c)} · {CHANNEL[c.channel] || c.channel}
          </span>
          <small>{handoffReason(c)}</small>
          <div className="handoff-toast-actions">
            <button
              onClick={() => {
                dismiss(c.id);
                onOpen(c.id);
              }}
            >
              Mở hội thoại
            </button>
            <button className="secondary" onClick={() => dismiss(c.id)}>
              Để sau
            </button>
          </div>
        </div>
      ))}
    </div>,
    document.body,
  );
}

/** The header's bell: red with the count while someone waits; opens the list of who waits. */
export function HandoffBell({ token, onOpen }: { token: string; onOpen: (id: number) => void }) {
  const { waiting: pushed, source } = useHandoffStream(token);
  const alerts = useHandoffAlerts(pushed);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const box = useRef<HTMLDivElement>(null);
  const count = alerts.waiting.length;

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!open) return;
    setNow(Date.now());
    const outside = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const go = (id: number) => {
    setOpen(false);
    onOpen(id);
  };

  return (
    <div className="handoff-bell" ref={box}>
      <button
        type="button"
        className={"handoff-bell-button" + (count ? " ringing" : "")}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={count ? `${count} khách đang chờ nhân viên` : "Không có khách chờ nhân viên"}
        title={SOURCE[source]}
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="bell" size={20} />
        {count > 0 && <span className="handoff-bell-count" aria-hidden="true">{count > 99 ? "99+" : count}</span>}
        <span className={"handoff-bell-source " + source} aria-hidden="true" />
      </button>
      {open && (
        <div className="handoff-bell-panel" role="dialog" aria-label="Khách chờ nhân viên">
          <div className="handoff-bell-head">
            <strong>Khách chờ nhân viên</strong>
            <small>{SOURCE[source]}</small>
          </div>
          {count === 0 ? (
            <p className="handoff-bell-empty">Không ai chờ. Khi trợ lý chuyển máy, chuông sẽ đỏ và kêu.</p>
          ) : (
            <ul>
              {alerts.waiting.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => go(c.id)}>
                    <strong>{who(c)}</strong>
                    <span>
                      {CHANNEL[c.channel] || c.channel} · {waited(c, now)}
                    </span>
                    <small>{handoffReason(c)}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {alerts.permission === "default" && (
            <button type="button" className="secondary handoff-enable" onClick={() => void alerts.enable()}>
              Bật thông báo trình duyệt
            </button>
          )}
        </div>
      )}
      <HandoffToasts alerts={alerts} onOpen={go} />
    </div>
  );
}
