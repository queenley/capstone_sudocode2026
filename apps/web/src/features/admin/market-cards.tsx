"use client";
// Battlecards from the offline market research (docs/plan/002-so-sanh-doi-thu-tu-web.md): a person approves each
// one before it becomes a knowledge version. What the research saw of other sellers is shown here for the reviewer
// only; it is never published.
import { useEffect, useRef, useState } from "react";
import { api } from "@/services/api";

type Point = { text: string; cites: string[] };
type Competitor = {
  name?: string;
  brand?: string;
  seller?: string;
  url?: string;
  specs?: string;
};
type Card = {
  id: string;
  sku: string;
  product?: string;
  round?: string;
  status: "pending" | "flagged" | "approved" | "rejected";
  gate: string[];
  card: { compared_on: string[]; points: Point[]; questions: string[] };
  competitors: Competitor[];
  chunk_id?: string;
  knowledge_version?: number;
  reviewer?: string;
  note?: string;
};

const LABEL: Record<Card["status"], string> = {
  pending: "Chờ duyệt",
  flagged: "Bị cổng chặn",
  approved: "Đã duyệt",
  rejected: "Đã từ chối",
};

export default function MarketCards({ token }: { token: string }) {
  const [cards, setCards] = useState<Card[]>([]);
  const [selected, setSelected] = useState("");
  const [checked, setChecked] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  const currentToken = useRef(token);
  currentToken.current = token;

  useEffect(() => {
    const controller = new AbortController();
    setCards([]);
    setSelected("");
    setMessage("");
    if (token)
      api<{ cards: Card[] }>(
        "/api/developer/improvement/market/cards",
        token,
        undefined,
        undefined,
        {
          signal: controller.signal,
        },
      )
        .then((value) => {
          if (!controller.signal.aborted) setCards(value.cards);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setMessage(e.message);
        });
    return () => controller.abort();
  }, [token, reload]);

  async function decide(card: Card, decision: "approved" | "rejected") {
    setBusy(true);
    setMessage("");
    try {
      const result = await api<{ card: Card; reload_required: boolean }>(
        `/api/developer/improvement/market/cards/${card.id}/review`,
        token,
        { decision, note: decision === "rejected" ? reason : "" },
      );
      if (currentToken.current !== token) return;
      setCards((rows) =>
        rows.map((row) => (row.id === card.id ? result.card : row)),
      );
      setSelected("");
      setChecked(false);
      setReason("");
      setMessage(
        decision === "approved"
          ? `Đã lưu ${result.card.chunk_id} vào phiên bản ${result.card.knowledge_version}. Nạp lại dịch vụ trợ lý để áp dụng.`
          : "Đã từ chối thẻ.",
      );
    } catch (e) {
      if (currentToken.current === token)
        setMessage(
          e instanceof Error ? e.message : "Không lưu được quyết định",
        );
    } finally {
      if (currentToken.current === token) setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Thẻ so sánh thị trường</h2>
      <p>
        Mỗi thẻ chỉ nói điều khách nhận được khi mua ở shop, có trích tài liệu.
        Không so giá, không nêu nơi bán khác (PB-02, PB-04). Phần sản phẩm nơi
        khác chỉ để người duyệt đọc, không bao giờ đến tay trợ lý.
      </p>
      <button
        className="ad-btn-quiet"
        disabled={!token || busy}
        onClick={() => setReload((value) => value + 1)}
      >
        Tải lại
      </button>
      {message && <p role="status">{message}</p>}
      {!cards.length && (
        <p>
          Chưa có thẻ. Chạy{" "}
          <code>
            python -m ai_agent_service.pipeline.improve market-research
            --category …
          </code>
        </p>
      )}
      {cards.map((card) => (
        <article key={card.id} className="market-card">
          <button
            disabled={busy}
            onClick={() => {
              setSelected(selected === card.id ? "" : card.id);
              setChecked(false);
              setReason("");
            }}
          >
            {card.product || card.sku} · {LABEL[card.status]}
            {card.chunk_id
              ? ` · ${card.chunk_id}, phiên bản ${card.knowledge_version}`
              : ""}
          </button>
          {selected === card.id && (
            <div>
              {card.gate.length > 0 && (
                <ul role="alert">
                  {card.gate.map((reasonText) => (
                    <li key={reasonText}>{reasonText}</li>
                  ))}
                </ul>
              )}
              <h3>Trợ lý sẽ đọc</h3>
              <ul>
                {card.card.points.map((point, index) => (
                  <li key={index}>
                    {point.text} <small>({point.cites.join(", ")})</small>
                  </li>
                ))}
              </ul>
              {card.card.compared_on.length > 0 && (
                <p>Khách hay so về: {card.card.compared_on.join(", ")}</p>
              )}
              {card.card.questions.length > 0 && (
                <p>
                  Câu khách có thể nói (chỉ để tìm kiếm):{" "}
                  {card.card.questions.join(" · ")}
                </p>
              )}
              <details>
                <summary>
                  Sản phẩm nơi khác mà vòng nghiên cứu thấy (
                  {card.competitors.length}), nội bộ
                </summary>
                <ul>
                  {card.competitors.map((other, index) => (
                    <li key={index}>
                      {[other.name, other.brand, other.seller, other.specs]
                        .filter(Boolean)
                        .join(" · ")}
                      {other.url && (
                        <>
                          {" "}
                          <a
                            href={other.url}
                            target="_blank"
                            rel="noopener noreferrer nofollow"
                          >
                            nguồn
                          </a>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
              {card.status === "pending" && (
                <div className="faq-actions">
                  <label>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={busy}
                      onChange={(e) => setChecked(e.target.checked)}
                    />
                    Tôi đã đối chiếu từng ý với tài liệu được trích
                  </label>
                  <button
                    disabled={busy || !checked}
                    onClick={() => decide(card, "approved")}
                  >
                    Duyệt và lưu phiên bản
                  </button>
                  <input
                    placeholder="Lý do từ chối"
                    minLength={3}
                    maxLength={500}
                    value={reason}
                    disabled={busy}
                    onChange={(e) => setReason(e.target.value)}
                  />
                  <button
                    type="button"
                    disabled={busy || reason.trim().length < 3}
                    onClick={() => decide(card, "rejected")}
                  >
                    Từ chối
                  </button>
                </div>
              )}
            </div>
          )}
        </article>
      ))}
    </section>
  );
}
