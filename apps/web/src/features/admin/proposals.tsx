"use client";
// /admin/de-xuat: proposals the conversations raised; one becomes knowledge only with the text a person checked.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/services/api";
import { useAdmin } from "./admin-context";

type Proposal = { id: string; kind: string; candidate: unknown; status: string };

const STATUS: Record<string, string> = { pending: "Chờ duyệt", approved: "Đã duyệt", rejected: "Đã từ chối" };

export default function Proposals() {
  const { token, setNotice } = useAdmin();
  const [rows, setRows] = useState<Proposal[] | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await api<Proposal[]>("/api/admin/proposals", token));
    } catch (e) {
      setRows([]);
      setNotice(e instanceof Error ? e.message : "Không tải được đề xuất");
    }
  }, [token, setNotice]);

  useEffect(() => {
    load();
  }, [load]);

  async function decide(id: string, decision: "approved" | "rejected") {
    setBusy(true);
    try {
      await api(
        `/api/admin/proposals/${id}/review`,
        token,
        decision === "approved" ? { decision, knowledge_text: texts[id] || "" } : { decision },
      );
      setNotice(decision === "approved" ? "Đã duyệt đề xuất." : "Đã từ chối đề xuất.");
      await load();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Không lưu được quyết định");
    } finally {
      setBusy(false);
    }
  }

  if (rows === null)
    return (
      <p className="sl-muted" role="status">
        Đang tải…
      </p>
    );
  if (rows.length === 0) return <p className="sl-muted">Chưa có đề xuất nào.</p>;
  return (
    <div className="sl-columns">
      {rows.map((row) => (
        <article className="sl-panel" key={row.id} aria-label={`Đề xuất ${row.id}`}>
          <header>
            <strong>{row.kind}</strong>
            <span className="sl-badge">{STATUS[row.status] || row.status}</span>
          </header>
          <pre className="sl-code">{JSON.stringify(row.candidate, null, 2)}</pre>
          {row.status === "pending" && (
            <>
              <label>
                Nội dung kiến thức đã kiểm tra
                <textarea
                  rows={4}
                  value={texts[row.id] || ""}
                  onChange={(e) => setTexts((old) => ({ ...old, [row.id]: e.target.value }))}
                />
              </label>
              <div className="sl-actions">
                <button
                  className="sl-btn sl-btn-small"
                  disabled={busy || !(texts[row.id] || "").trim()}
                  onClick={() => decide(row.id, "approved")}
                >
                  Duyệt nội dung đã kiểm tra
                </button>
                <button className="sl-btn sl-btn-small ad-btn-danger" disabled={busy} onClick={() => decide(row.id, "rejected")}>
                  Từ chối
                </button>
              </div>
            </>
          )}
        </article>
      ))}
    </div>
  );
}
