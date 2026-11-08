"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/services/api";

type Gap = {
  id: string;
  question: string;
  status: string;
  knowledge_version?: number;
  faq_id?: string;
  occurrences: { call_id: string; turn_id: string }[];
};

export default function KnowledgeGaps({
  token,
  onFaqCreated,
}: {
  token: string;
  /** Given where an admin works: answers can then become FAQ drafts. */
  onFaqCreated?: () => void;
}) {
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [selected, setSelected] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState("");
  const [reason, setReason] = useState("");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  const currentToken = useRef(token);
  currentToken.current = token;
  useEffect(() => {
    const controller = new AbortController();
    setSelected("");
    setAnswer("");
    setSources("");
    setReason("");
    setApproved(false);
    setMessage("");
    setGaps([]);
    setBusy(false);
    if (token)
      api<Gap[]>("/api/developer/knowledge-gaps", token, undefined, undefined, {
        signal: controller.signal,
      })
        .then((value) => {
          if (!controller.signal.aborted) setGaps(value);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setMessage(e.message);
        });
    return () => controller.abort();
  }, [token, reload]);
  return (
    <section className="panel">
      <h2>Câu hỏi còn thiếu kiến thức</h2>
      <p>
        Câu trả lời cần người duyệt và nguồn công khai. Ca kiểm tra mới được lưu
        ở danh sách đề xuất để duyệt riêng.
      </p>
      <button
        disabled={!token || busy}
        onClick={() => setReload((value) => value + 1)}
      >
        Tải lại
      </button>
      {message && <p role="status">{message}</p>}
      {!gaps.length && <p>Chưa có câu hỏi được ghi nhận.</p>}
      {gaps.map((gap) => (
        <div key={gap.id}>
          <button
            disabled={busy || gap.status !== "open"}
            onClick={() => {
              setSelected(gap.id);
              setAnswer("");
              setSources("");
              setReason("");
              setApproved(false);
            }}
          >
            {gap.question} · {gap.occurrences.length} lượt ·{" "}
            {gap.status === "resolved"
              ? `Đã xử lý, phiên bản ${gap.knowledge_version}`
              : gap.status === "dismissed"
                ? "Đã bỏ qua"
                : gap.status === "faq"
                  ? `Đã chuyển thành FAQ ${gap.faq_id}`
                  : "Chờ duyệt"}
          </button>
        </div>
      ))}
      {selected && (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (busy || !approved) return;
            setBusy(true);
            setMessage("");
            try {
              const result = await api<{ knowledge_version: number }>(
                `/api/developer/knowledge-gaps/${selected}/resolve`,
                token,
                {
                  answer,
                  cites: sources
                    .split(",")
                    .map((value) => value.trim())
                    .filter(Boolean),
                  approved: true,
                },
              );
              if (currentToken.current !== token) return;
              setGaps((rows) =>
                rows.map((row) =>
                  row.id === selected
                    ? {
                        ...row,
                        status: "resolved",
                        knowledge_version: result.knowledge_version,
                      }
                    : row,
                ),
              );
              setSelected("");
              setMessage(
                `Đã lưu phiên bản ${result.knowledge_version}. Nạp lại dịch vụ trợ lý để áp dụng.`,
              );
            } catch (e) {
              if (currentToken.current === token)
                setMessage(
                  e instanceof Error ? e.message : "Không lưu được câu trả lời",
                );
            } finally {
              if (currentToken.current === token) setBusy(false);
            }
          }}
        >
          <label>
            Câu trả lời đã kiểm tra
            <textarea
              required
              minLength={3}
              maxLength={4000}
              value={answer}
              disabled={busy}
              onChange={(e) => setAnswer(e.target.value)}
            />
          </label>
          <label>
            Mã nguồn kiến thức, cách nhau bằng dấu phẩy
            <input
              required
              value={sources}
              disabled={busy}
              placeholder="PB-05, FAQ-03"
              onChange={(e) => setSources(e.target.value)}
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={approved}
              disabled={busy}
              onChange={(e) => setApproved(e.target.checked)}
            />
            Tôi đã đối chiếu nguồn và duyệt câu trả lời này
          </label>
          <div className="faq-actions">
            <button disabled={busy || !approved}>Duyệt và lưu phiên bản</button>
            {onFaqCreated && (
              <button
                type="button"
                disabled={busy || answer.trim().length < 3}
                onClick={async () => {
                  setBusy(true);
                  setMessage("");
                  try {
                    const entry = await api<{ chunk_id: string }>(
                      `/api/developer/knowledge-gaps/${selected}/faq`,
                      token,
                      {
                        answer,
                        cites: sources
                          .split(",")
                          .map((value) => value.trim())
                          .filter(Boolean),
                      },
                    );
                    if (currentToken.current !== token) return;
                    setGaps((rows) =>
                      rows.map((row) =>
                        row.id === selected
                          ? { ...row, status: "faq", faq_id: entry.chunk_id }
                          : row,
                      ),
                    );
                    setSelected("");
                    setMessage(
                      "Đã tạo FAQ nháp. Vào phần FAQ theo đợt để duyệt và bật.",
                    );
                    onFaqCreated();
                  } catch (e) {
                    if (currentToken.current === token)
                      setMessage(
                        e instanceof Error ? e.message : "Không tạo được FAQ",
                      );
                  } finally {
                    if (currentToken.current === token) setBusy(false);
                  }
                }}
              >
                Chuyển thành FAQ nháp
              </button>
            )}
          </div>
          <label>
            Lý do bỏ qua, nếu câu hỏi không cần trả lời
            <input
              minLength={3}
              maxLength={500}
              value={reason}
              disabled={busy}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <div className="faq-actions">
            <button
              type="button"
              disabled={busy || reason.trim().length < 3}
              onClick={async () => {
                setBusy(true);
                setMessage("");
                try {
                  await api(
                    `/api/developer/knowledge-gaps/${selected}/dismiss`,
                    token,
                    { reason },
                  );
                  if (currentToken.current !== token) return;
                  setGaps((rows) =>
                    rows.map((row) =>
                      row.id === selected
                        ? { ...row, status: "dismissed" }
                        : row,
                    ),
                  );
                  setSelected("");
                  setMessage("Đã bỏ qua câu hỏi.");
                } catch (e) {
                  if (currentToken.current === token)
                    setMessage(
                      e instanceof Error ? e.message : "Không bỏ qua được",
                    );
                } finally {
                  if (currentToken.current === token) setBusy(false);
                }
              }}
            >
              Bỏ qua câu hỏi
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
