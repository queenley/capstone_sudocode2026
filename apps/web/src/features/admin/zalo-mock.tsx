"use client";
// /admin/zalo: the Zalo mock (scripts/dev/zalo_mock.py), to chat with the shop as Zalo users without an Official
// Account. The page asks this server for the mock's cookie with the admin's token (lib/zalo-mock-session.ts), then
// shows the mock in a frame; whoever has no admin token never reaches it.
import { useEffect, useState } from "react";
import { useAdmin } from "./admin-context";

type State = { kind: "checking" } | { kind: "ready" } | { kind: "refused"; message: string };

export default function ZaloMock() {
  const { token } = useAdmin();
  const [state, setState] = useState<State>({ kind: "checking" });

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const response = await fetch("/zalo-mock-session", {
          method: "POST",
          headers: { Authorization: "Bearer " + token },
          cache: "no-store",
        });
        if (!alive) return;
        if (response.ok) setState({ kind: "ready" });
        else {
          const body = await response.json().catch(() => ({}));
          setState({ kind: "refused", message: body.detail || `Không mở được Zalo mock (HTTP ${response.status}).` });
        }
      } catch {
        if (alive) setState({ kind: "refused", message: "Không kết nối được máy chủ." });
      }
    })();
    return () => {
      alive = false;
    };
  }, [token]);

  return (
    <section className="sl-panel zalo-mock-panel" aria-label="Zalo mock">
      <header>
        <h2>Zalo mock</h2>
        <p>
          Chat với cửa hàng như một người dùng Zalo: các khách CRM có Zalo, hoặc một khách mới. Tin nhắn đi vào webhook
          Zalo của trợ lý, câu trả lời hiện lại ở đây. Mỗi tin là một lượt trợ lý thật, có tính phí model.
        </p>
      </header>
      {state.kind === "checking" && <p className="empty">Đang kiểm quyền quản trị…</p>}
      {state.kind === "refused" && (
        <div className="sl-alert" role="alert">
          {state.message}
        </div>
      )}
      {state.kind === "ready" && (
        <>
          <iframe className="zalo-mock-frame" src="/zalo-mock" title="Zalo mock" />
          <p className="zalo-mock-open">
            <a href="/zalo-mock" target="_blank" rel="noopener">
              Mở trong tab mới
            </a>
          </p>
        </>
      )}
    </section>
  );
}
