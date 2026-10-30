"use client";
// Tells the staff on duty that a conversation waits for a person (handoff
// pending): a red toast on the page, a short tone, the count in the tab title
// and, once the consultant allows it, a browser notification that reaches them
// in another tab. Each call alerts once, the first time it is seen waiting,
// including the ones already waiting when the page opens.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgentCall } from "@/services/api";

const CHANNEL: Record<string, string> = { web: "Web chat", zalo: "Zalo", hotline: "Hotline", facebook: "Facebook" };
type Permission = NotificationPermission | "unsupported";

/** Why the call waits, as the consultant reads it (the agent writes an English prefix). */
export function handoffReason(c: AgentCall): string {
  return (c.handoff_reason || "").replace(/^The assistant handed over:\s*/i, "") || "Cần nhân viên hỗ trợ";
}

function who(c: AgentCall): string {
  return c.customer_label || (c.phone_last4 ? `Khách ···${c.phone_last4}` : `Cuộc gọi #${c.id}`);
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
    // no audio: the toast and the title still tell
  }
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
  const { toasts, dismiss, permission, enable } = alerts;
  if (!toasts.length && permission !== "default") return null;
  return (
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
      {permission === "default" && (
        <button className="handoff-enable" onClick={() => void enable()}>
          Bật thông báo trình duyệt khi khách cần nhân viên
        </button>
      )}
    </div>
  );
}
