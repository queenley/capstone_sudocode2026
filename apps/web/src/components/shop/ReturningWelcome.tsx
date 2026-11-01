"use client";

import { useEffect, useRef, useState } from "react";
import { account as accountStore } from "@/lib/account";
import { customerToken } from "@/lib/session";
import { api, ReturningCustomerWelcome } from "@/services/api";

/** No personal data is persisted. A dismissed welcome stays dismissed for this tab/account. */
export default function ReturningWelcome({ customerId, chatOpen, onContinue, onDismiss }: {
  customerId: string;
  chatOpen: boolean;
  onContinue: () => void;
  onDismiss: () => void;
}) {
  const [welcome, setWelcome] = useState<ReturningCustomerWelcome | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  const panel = useRef<HTMLElement>(null);
  const stopped = useRef(false);
  const eligible = useRef<boolean | null>(null);
  const cancel = useRef<() => void>(() => undefined);
  const seenKey = `shop-welcome-seen:${customerId}`;

  function dismiss(restoreFocus = false) {
    const focused = panel.current?.contains(document.activeElement);
    stopped.current = true;
    cancel.current();
    setWelcome(null);
    setFailed(false);
    try { sessionStorage.setItem(seenKey, "1"); } catch { /* unavailable */ }
    if (restoreFocus && focused) onDismiss();
  }

  useEffect(() => {
    if (eligible.current === null) {
      try { eligible.current = sessionStorage.getItem(seenKey) !== "1"; } catch { eligible.current = true; }
    }
    if (!eligible.current) return;
    let request = 0;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const token = customerToken();
    const generation = accountStore.revision();
    const valid = () => !stopped.current && customerToken() === token && accountStore.revision() === generation;
    const clear = () => {
      request++;
      controller?.abort();
      clearTimeout(timer);
      setWelcome(null);
      setFailed(false);
      setLoading(false);
    };
    cancel.current = clear;
    async function load() {
      clear();
      if (!valid() || !token || document.visibilityState !== "visible") return;
      const version = request;
      controller = new AbortController();
      setLoading(true);
      try {
        const result = await api<ReturningCustomerWelcome>("/api/agent/welcome", token, undefined, "GET", { signal: controller.signal });
        if (version !== request || !valid()) return;
        const lifetime = Math.min(Date.parse(result.expires_at) - Date.now(), 30_000);
        if (!result.returning || !(lifetime > 0)) return;
        setWelcome(result);
        try { sessionStorage.setItem(seenKey, "1"); } catch { /* unavailable */ }
        timer = setTimeout(() => void load(), lifetime);
      } catch (error) {
        if (version !== request || !valid()) return;
        if ([401, 403].includes((error as { status?: number }).status || 0)) {
          stopped.current = true;
          void accountStore.load(true);
        } else {
          setFailed(true);
        }
      } finally {
        if (version === request) setLoading(false);
      }
    }
    const reset = () => { stopped.current = true; clear(); };
    const storage = (event: StorageEvent) => { if (event.key === "customer-token" || event.key === null) reset(); };
    const visibility = () => { if (document.visibilityState === "hidden") clear(); else void load(); };
    window.addEventListener("shop-conversation-reset", reset);
    window.addEventListener("shop-customer-token-changed", reset);
    window.addEventListener("storage", storage);
    document.addEventListener("visibilitychange", visibility);
    // Returning to a shared tab revalidates before revealing personal information again.
    window.addEventListener("blur", clear);
    window.addEventListener("focus", load);
    void load();
    return () => {
      clear();
      window.removeEventListener("shop-conversation-reset", reset);
      window.removeEventListener("shop-customer-token-changed", reset);
      window.removeEventListener("storage", storage);
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("blur", clear);
      window.removeEventListener("focus", load);
    };
  }, [customerId, retry, seenKey]);

  useEffect(() => {
    if (chatOpen) dismiss();
    // Opening chat consumes this welcome, including any pending response.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatOpen]);

  if (chatOpen || (!welcome && !failed)) return null;
  return (
    <aside ref={panel} className="s-returning" aria-labelledby="returning-title" aria-busy={loading}
      onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); dismiss(true); } }}>
      <header className="s-returning-head">
        <span className="s-returning-kicker">QUIVO · TIẾP NỐI TƯ VẤN</span>
        <button className="s-icon-btn s-returning-close" aria-label="Đóng lời chào" onClick={() => dismiss(true)}>✕</button>
      </header>
      <div className="s-returning-content">
        <h2 id="returning-title">{welcome ? <>Chào mừng {welcome.name || "bạn"} quay lại!</> : "Trợ lý luôn sẵn sàng"}</h2>
        <div aria-live="polite">
          {welcome?.blocker && Date.parse(welcome.blocker.valid_until) > Date.now() ? (
            <p>Lần trước bạn còn cân nhắc: <strong>{welcome.blocker.text}</strong>. Bạn muốn trao đổi tiếp chứ?</p>
          ) : <p>{failed ? "Chưa tải được phần tư vấn trước. Bạn có thể thử lại hoặc mở chat." : "Bạn muốn tiếp tục phần tư vấn trước hay cần hỗ trợ thêm?"}</p>}
        </div>
        <div className="s-returning-actions">
          <button className="s-btn" onClick={() => { dismiss(); onContinue(); }}>Tiếp tục tư vấn <span aria-hidden="true">↗</span></button>
          {failed && <button className="s-btn-ghost" disabled={loading} onClick={() => setRetry(value => value + 1)}>Thử lại</button>}
        </div>
        <small>Chỉ mở chat khi bạn chọn tiếp tục.</small>
      </div>
    </aside>
  );
}
