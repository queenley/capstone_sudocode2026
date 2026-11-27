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

/** A draft from the web research (docs/plan/002, section 11): never published as such. */
type Suggestion = {
  gap_id: string;
  status: "ready" | "flagged" | "no_answer";
  gate: string[];
  answer: string;
  cites: string[];
  sources: string[];
  note: string;
  grounds?: "documents" | "web" | "documents_and_web" | "none";
  /** The sources on a manufacturer's domain the shop allows: the only ones a customer may be given. */
  official_sources?: string[];
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
  /** Manufacturer pages the reviewer gives the customer with the answer (docs/plan/002, section 12). */
  const [links, setLinks] = useState<string[]>([]);
  useEffect(() => setLinks([]), [selected]);
  const [reason, setReason] = useState("");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  const [suggestions, setSuggestions] = useState<Record<string, Suggestion>>(
    {},
  );
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
    setSuggestions({});
    setBusy(false);
    if (token) {
      api<Gap[]>("/api/developer/knowledge-gaps", token, undefined, undefined, {
        signal: controller.signal,
      })
        .then((value) => {
          if (!controller.signal.aborted) setGaps(value);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setMessage(e.message);
        });
      // Optional: without the research, or on an older service, the gaps work as before.
      api<{ suggestions: Suggestion[] }>(
        "/api/developer/improvement/market/gap-suggestions",
        token,
        undefined,
        undefined,
        { signal: controller.signal },
      )
        .then((value) => {
          if (!controller.signal.aborted)
            setSuggestions(
              Object.fromEntries(value.suggestions.map((s) => [s.gap_id, s])),
            );
        })
        .catch(() => undefined);
    }
    return () => controller.abort();
  }, [token, reload]);
  const suggestion = selected ? suggestions[selected] : undefined;
  return (
    <section className="panel">
      <h2>Câu hỏi còn thiếu kiến thức</h2>
      <p>
        Câu trả lời cần người duyệt và nguồn công khai. Ca kiểm tra mới được lưu
        ở danh sách đề xuất để duyệt riêng.
      </p>
      <button
        className="ad-btn-quiet"
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
                  : suggestions[gap.id]?.status === "ready"
                    ? "Chờ duyệt · có gợi ý"
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
                  references: links,
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
          {suggestion && suggestion.status !== "no_answer" && (
            <div className="gap-suggestion">
              <h3>Gợi ý từ tìm kiếm web (chưa kiểm chứng)</h3>
              {suggestion.grounds === "documents" && (
                <p role="note">
                  Tài liệu đã trả lời câu này ({suggestion.cites.join(", ")}):
                  trợ lý tra cứu sót, không phải thiếu kiến thức. Báo đội kỹ
                  thuật thay vì thêm câu trả lời mới.
                </p>
              )}
              {suggestion.gate.length > 0 && (
                <ul role="alert">
                  {suggestion.gate.map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
              )}
              <p>{suggestion.answer}</p>
              {suggestion.note && (
                <p>
                  <small>Cần kiểm: {suggestion.note}</small>
                </p>
              )}
              {suggestion.sources.length > 0 && (
                <ul>
                  {suggestion.sources.map((url) => (
                    <li key={url}>
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                      >
                        {url}
                      </a>
                      {suggestion.official_sources?.includes(url) && (
                        <label>
                          <input
                            type="checkbox"
                            checked={links.includes(url)}
                            disabled={busy}
                            onChange={(e) =>
                              setLinks((old) =>
                                e.target.checked
                                  ? [...old, url]
                                  : old.filter((link) => link !== url),
                              )
                            }
                          />{" "}
                          Trang chính hãng: gửi kèm link này cho khách
                        </label>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {suggestion.status === "ready" && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setAnswer(suggestion.answer);
                    setSources(suggestion.cites.join(", "));
                  }}
                >
                  Dùng gợi ý
                </button>
              )}
              {suggestion.status === "ready" && !suggestion.cites.length && (
                <p>
                  <small>
                    Gợi ý chỉ dựa vào trang web, không có mã tài liệu: mở link
                    để đối chiếu. Chọn một trang chính hãng ở trên để duyệt
                    bằng link đó, hoặc dùng &ldquo;Chuyển thành FAQ nháp&rdquo;.
                  </small>
                </p>
              )}
            </div>
          )}
          {suggestion?.status === "no_answer" && (
            <p>
              <small>
                Tìm trên web không ra câu trả lời đáng tin cho câu này.
                {suggestion.note && ` Ghi chú: ${suggestion.note}`}
              </small>
            </p>
          )}
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
            {links.length > 0 && " (không bắt buộc khi đã chọn trang chính hãng)"}
            <input
              required={!links.length}
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
