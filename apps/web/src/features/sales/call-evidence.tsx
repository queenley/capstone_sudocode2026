"use client";
// The consultant's side panel of a call, in two parts (globals.css, "the call's evidence"):
//   1. This conversation: who, which channel, what the customer said, the products named (each a link to its page,
//      so Sales opens what the assistant quoted) and the orders.
//   2. The call's details, folded: tier, lane, guard and tools of each assistant turn, the long-term memory.
// What a consultant needs to take over sits on top in plain words; what a developer reads is one click away.
import React, { useEffect, useState } from "react";
import { api, AgentCallDetail, AgentTurn } from "@/services/api";
import { fetchProducts } from "@/lib/catalog";
import { reasonLabel } from "@/features/sales/handoff-reasons";

export const CHANNEL_NAMES: Record<string, string> = {
  hotline: "Hotline",
  web: "Web chat",
  zalo: "Zalo",
  facebook: "Fanpage",
};

const TIER: Record<string, string> = {
  VERIFIED: "Đã xác minh",
  PROBABLE: "Chưa chắc chắn, đang hỏi lại",
  AMBIGUOUS: "Số dùng chung, chưa rõ là ai",
  UNKNOWN: "Chưa xác định",
};

const ORDER_STATUS: Record<string, string> = {
  created: "Chờ xử lý",
  confirmed: "Chờ xử lý",
  shipping: "Đang giao",
  delivered: "Đã giao",
  fulfilled: "Đã giao",
  return_requested: "Khách yêu cầu trả",
  returned: "Đã trả hàng",
  cancelled: "Đã hủy",
};

const money = (value?: number | null) => (value == null ? "" : `${value.toLocaleString("vi-VN")}₫`);

export type NamedProduct = { sku: string; name?: string; price?: number };

type ToolCall = { name?: string; args?: Record<string, unknown>; result?: { ok?: boolean; data?: unknown } };

const toolsOf = (turn: AgentTurn) => ((turn.meta?.tool_calls as ToolCall[] | undefined) || []);
const tool = (name?: string) => (name || "").replace("_", ".");
const record = (value: unknown) => (value && typeof value === "object" ? (value as Record<string, unknown>) : {});
const num = (value: unknown) => (typeof value === "number" ? value : undefined);
const str = (value: unknown) => (typeof value === "string" && value ? value : undefined);

/** The products a turn (or a whole call) rests on: quoted, checked, ordered or named in a reply; first seen first.
 * A search's results count only when a reply names them: a search lists eight products, the customer heard one. */
export function productsOf(turns: AgentTurn[], brief?: Record<string, unknown> | null): NamedProduct[] {
  const found = new Map<string, NamedProduct>();
  const names = new Map<string, string>();
  const said = turns.filter((t) => t.speaker === "agent").map((t) => t.content.toLowerCase()).join("\n");
  const add = (sku?: string, name?: string, price?: number) => {
    if (!sku) return;
    const known = found.get(sku) || { sku };
    found.set(sku, { sku, name: known.name || name || names.get(sku), price: known.price ?? price });
  };
  for (const turn of turns) {
    for (const call of toolsOf(turn)) {
      const name = tool(call.name);
      const args = record(call.args);
      const data = record(call.result?.data);
      if (name === "catalog.search") {
        for (const item of (data.items as Record<string, unknown>[] | undefined) || []) {
          const sku = str(item.sku);
          const label = str(item.name);
          if (sku && label) names.set(sku, label);
          if (sku && (said.includes(sku.toLowerCase()) || (label && said.includes(label.toLowerCase())))) {
            add(sku, label, num(item.list_price_vnd));
          }
        }
      } else if (name === "pricing.get_quote") {
        add(str(data.sku) || str(args.sku), str(data.name), num(data.final_price_vnd));
      } else if (name === "pricing.quote_order") {
        for (const unit of (data.units as Record<string, unknown>[] | undefined) || []) add(str(unit.sku), undefined, num(unit.final_price_vnd));
      } else if (name === "inventory.check") {
        add(str(data.sku) || str(args.sku));
      } else if (name === "order.create") {
        if (args.lines) for (const line of args.lines as Record<string, unknown>[]) add(str(line.sku), undefined, num(line.price_vnd));
        else add(str(args.sku), undefined, num(args.price_vnd));
      } else if (name === "order.update") {
        add(str(args.new_variant_sku));
      } else if (name === "order.status") {
        for (const order of (data.orders as Record<string, unknown>[] | undefined) || []) add(str(order.sku), undefined, num(order.price_vnd));
      }
    }
  }
  const advised = brief?.product_advised;
  for (const sku of Array.isArray(advised) ? advised : [advised]) add(str(sku));
  return [...found.values()].map((p) => ({ ...p, name: p.name || names.get(p.sku) }));
}

// The shop's names, by product and variant code, fetched once for every chat on the page: an order or a quote
// carries only a code (SKU-AP-Y), and a consultant reads "Máy lọc không khí AirPure Y".
let catalogNames: Promise<Map<string, string>> | null = null;
function loadNames(): Promise<Map<string, string>> {
  catalogNames ??= fetchProducts()
    .then((products) => {
      const names = new Map<string, string>();
      for (const product of products) {
        names.set(product.ref, product.name);
        for (const variant of product.variants) {
          const attributes = Object.values((variant.variant as Record<string, unknown>) || {}).filter(Boolean).join(" · ");
          names.set(variant.sku_code, attributes ? `${product.name} (${attributes})` : product.name);
        }
      }
      return names;
    })
    .catch(() => {
      catalogNames = null; // try again next time
      return new Map<string, string>();
    });
  return catalogNames;
}

function useNames(): Map<string, string> {
  const [names, setNames] = useState<Map<string, string>>(new Map());
  useEffect(() => {
    let active = true;
    loadNames().then((found) => { if (active) setNames(found); });
    return () => { active = false; };
  }, []);
  return names;
}

/** Each product as a link to its page on the shop, in a new tab: the consultant keeps the chat open. */
export function ProductLinks({ products, compact = false }: { products: NamedProduct[]; compact?: boolean }) {
  const names = useNames();
  if (!products.length) return null;
  products = products.map((p) => ({ ...p, name: names.get(p.sku) || p.name }));
  return (
    <ul className={"product-links" + (compact ? " compact" : "")}>
      {products.map((p) => (
        <li key={p.sku}>
          <a href={`/san-pham/${encodeURIComponent(p.sku)}`} target="_blank" rel="noreferrer">
            <span className="product-links__name">{p.name || p.sku}</span>
            {!compact && (
              <span className="product-links__meta">
                {p.name ? p.sku : ""}
                {p.price != null ? `${p.name ? " · " : ""}${money(p.price)}` : ""}
              </span>
            )}
          </a>
        </li>
      ))}
    </ul>
  );
}

type Context = {
  identity_confirmed: boolean;
  memory_status: string | null;
  call_facts?: { slot: string; value: unknown; text: string }[];
  facts: { slot: string; value: unknown; status: string; created_at: string; source: { call_id?: string } }[];
  episodes: { call_id: string; started_at: string; channel: string; summary: string; outcome: string }[];
  orders: { order_id: string; sku: string; qty: number; status: string }[];
};

const MEMORY_STATUS: Record<string, string> = {
  "": "ghi sau khi cuộc gọi kết thúc",
  pending: "đang ghi sau cuộc gọi…",
  done: "đã ghi",
  failed: "ghi không thành công",
  deleted: "đã xóa theo yêu cầu",
};

function useCallContext(callId: number, token: string) {
  const [context, setContext] = useState<Context | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api<Context>(`/api/agent/calls/${callId}/context`, token, undefined, undefined, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setContext(value); })
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [callId, token, reload]);
  return { context, error, reload: () => setReload((n) => n + 1) };
}

export default function CallEvidence({ detail, token }: { detail: AgentCallDetail; token: string }) {
  const { context, error, reload } = useCallContext(detail.id, token);
  const names = useNames();
  const products = productsOf(detail.turns, detail.handoff_brief);
  const said = context?.call_facts || [];
  return (
    <>
      <section className="evidence-part" aria-labelledby="ev-now">
        <h2 id="ev-now">Cuộc trò chuyện này</h2>
        <dl className="evidence-who">
          <dt>Khách</dt>
          <dd>{detail.customer_label || "Chưa biết tên"}</dd>
          <dt>Kênh</dt>
          <dd>
            <span className={`channel-badge channel-${detail.channel}`}>{CHANNEL_NAMES[detail.channel] || detail.channel}</span>
          </dd>
          <dt>Danh tính</dt>
          <dd className={detail.tier === "VERIFIED" ? "ok" : "warn"}>{TIER[detail.tier] || detail.tier}</dd>
        </dl>

        <h3>Sản phẩm trong cuộc này</h3>
        {products.length ? <ProductLinks products={products} /> : <p className="empty">Chưa nhắc sản phẩm nào.</p>}

        {said.length > 0 && (
          <>
            <h3>Khách đã nói</h3>
            <ul className="evidence-said">
              {said.map((fact) => <li key={fact.slot}>{fact.text}</li>)}
            </ul>
          </>
        )}

        {context && context.orders.length > 0 && (
          <>
            <h3>Đơn hàng</h3>
            <ul className="evidence-orders">
              {context.orders.map((order) => (
                <li key={order.order_id}>
                  <b>{order.order_id}</b>
                  <a href={`/san-pham/${encodeURIComponent(order.sku)}`} target="_blank" rel="noreferrer">{names.get(order.sku) || order.sku}</a>
                  <span>× {order.qty} · {ORDER_STATUS[order.status] || order.status}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        {error && <p className="empty" role="alert">{error}</p>}
      </section>

      <details className="evidence-part evidence-details">
        <summary>
          <span>Chi tiết cuộc gọi</span>
          <small>kênh, định tuyến, từng lượt của trợ lý, bộ nhớ</small>
        </summary>
        <dl className="facts">
          <dt>Kênh</dt>
          <dd>{CHANNEL_NAMES[detail.channel] || detail.channel}{detail.channel_ref ? ` · ${detail.channel_ref}` : ""}</dd>
          <dt>Bắt đầu</dt>
          <dd>{new Date(detail.started_at).toLocaleString("vi-VN")}</dd>
          {detail.ended_at && (<><dt>Kết thúc</dt><dd>{new Date(detail.ended_at).toLocaleString("vi-VN")}</dd></>)}
          <dt>Mã khách</dt>
          <dd>{detail.customer_id || "—"} · {detail.tier}</dd>
          <dt>Lane</dt>
          <dd>{detail.lane}{detail.route_reason ? ` — ${detail.route_reason}` : ""}</dd>
          <dt>Ngày nghiệp vụ</dt>
          <dd>{detail.business_day || "—"}</dd>
          {detail.handoff_status && (
            <>
              <dt>Chuyển máy</dt>
              <dd>{detail.handoff_status === "pending" ? "đang chờ" : "đã nhận"}{detail.handoff_reason ? ` — ${reasonLabel(detail.handoff_reason)}` : ""}</dd>
            </>
          )}
        </dl>

        <h3>Các lượt của trợ lý</h3>
        <TurnsDetail turns={detail.turns} />

        <h3>Bộ nhớ dài hạn</h3>
        <p className="empty">
          {MEMORY_STATUS[context?.memory_status || ""] || context?.memory_status}
          {" · "}
          <button type="button" className="link-button" onClick={reload}>Tải lại</button>
        </p>
        {context && context.facts.filter((f) => f.status === "active").length > 0 && (
          <ul className="evidence-facts">
            {context.facts.filter((f) => f.status === "active").map((fact, index) => (
              <li key={`${fact.slot}-${index}`}>
                <code>{fact.slot}</code> {typeof fact.value === "string" ? fact.value : JSON.stringify(fact.value)}
              </li>
            ))}
          </ul>
        )}
        {context && context.episodes.length > 0 && (
          <>
            <h3>Các cuộc trước</h3>
            <ul className="evidence-episodes">
              {context.episodes.map((episode) => (
                <li key={episode.call_id}>
                  <small>{new Date(episode.started_at).toLocaleDateString("vi-VN")} · {CHANNEL_NAMES[episode.channel] || episode.channel}</small>
                  {episode.summary}
                </li>
              ))}
            </ul>
          </>
        )}
        {detail.after_call && (
          <details className="evidence-raw">
            <summary>Kết quả sau cuộc gọi (JSON)</summary>
            <pre>{JSON.stringify(detail.after_call, null, 2)}</pre>
          </details>
        )}
      </details>
    </>
  );
}

function TurnsDetail({ turns }: { turns: AgentTurn[] }) {
  const agent = turns.filter((t) => t.speaker === "agent");
  if (!agent.length) return <p className="empty">Chưa có lượt nào.</p>;
  return (
    <ol className="evidence-turns">
      {agent.map((t) => {
        const guard = (t.meta?.guard as { passed?: boolean; hard?: { reasons?: string[] }; soft?: { reasons?: string[] } }) || {};
        const reasons = [...(guard.hard?.reasons || []), ...(guard.soft?.reasons || [])];
        return (
          <li key={t.id}>
            <span>{String(t.meta?.lane || "—")}</span>
            <span className="chips">
              {toolsOf(t).map((call, j) => (
                <span key={j} className={"chip" + (call.result?.ok === false ? " bad" : "")}>{tool(call.name)}</span>
              ))}
            </span>
            <small>
              Guard {guard.passed === false ? "trượt" : "đạt"}
              {Number(t.meta?.regenerations) > 0 ? ` · viết lại ${String(t.meta?.regenerations)} lần` : ""}
              {t.meta?.fallback ? " · câu an toàn" : ""}
              {t.meta?.model ? ` · ${String(t.meta.model)}` : ""}
            </small>
            {reasons.length > 0 && <small className="bad-text">{reasons.join(" ")}</small>}
          </li>
        );
      })}
    </ol>
  );
}
