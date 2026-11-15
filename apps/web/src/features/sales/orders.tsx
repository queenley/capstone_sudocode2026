"use client";
// /ban-hang/don-hang: every order, its next step (giao hàng → đã giao, nhận hàng trả), the payment and the cancel.
// Each change asks first, then reloads the workspace's data so the assistant and the overview read the same thing.
import { Fragment, useState } from "react";
import UiIcon from "@/components/ui/Icon";
import { api } from "@/services/api";
import { colorName, money } from "@/lib/catalog";
import { NEXT_STEP, ORDER_STATUS, orderCode, PAYMENT } from "./labels";
import { useSales } from "./sales-context";
import type { Order } from "./types";

export default function Orders() {
  const { orders, token, refresh } = useSales();
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const words = query.trim().toLowerCase();
  const shown = (orders || []).filter(
    (o) =>
      (status === "all" || o.status === status) &&
      (!words ||
        orderCode(o).toLowerCase().includes(words) ||
        o.id.toLowerCase().includes(words) ||
        o.items.some((i) => (i.name + " " + i.sku_code).toLowerCase().includes(words))),
  );

  /** One change to one order: ask, post, reload; the error stays on the page. */
  async function change(order: Order, question: string, path: string, body: object, failed: string) {
    if (!window.confirm(question)) return;
    setBusy(order.id);
    setError("");
    try {
      await api(`/api/seller/orders/${order.id}/${path}`, token, body);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : failed);
    } finally {
      setBusy("");
    }
  }

  const step = (o: Order) => {
    const next = NEXT_STEP[o.status];
    if (next) change(o, `${orderCode(o)}: ${next.ask}`, "status", { status: next.status }, "Không cập nhật được");
  };
  const paid = (o: Order) =>
    change(o, `Xác nhận đã nhận đủ ${money(o.total)} cho đơn ${orderCode(o)}?`, "paid", {}, "Không cập nhật được");
  const cancel = (o: Order) =>
    change(o, `Hủy đơn ${orderCode(o)}? Hàng giữ cho đơn sẽ được trả lại kho.`, "cancel", {}, "Không hủy được");
  const toggle = (id: string) => setOpen(open === id ? null : id);

  return (
    <>
      <div className="sl-toolbar">
        <input aria-label="Tìm đơn hàng" placeholder="Tìm mã đơn, sản phẩm, SKU…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select aria-label="Lọc trạng thái đơn hàng" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">Tất cả trạng thái</option>
          {Object.entries(ORDER_STATUS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <span className="sl-muted" role="status">
          {shown.length} đơn
        </span>
      </div>
      {error && (
        <div className="sl-alert" role="alert">
          {error}
        </div>
      )}
      <table className="sl-table">
        <caption className="sr-only">Đơn hàng · chọn mã đơn để xem chi tiết</caption>
        <thead>
          <tr>
            <th>Mã đơn</th>
            <th>Thời gian</th>
            <th>Sản phẩm</th>
            <th>Tổng</th>
            <th>Trạng thái</th>
            <th>Thanh toán</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {shown.map((o) => (
            <Fragment key={o.id}>
              <tr className={open === o.id ? "open" : ""} onClick={() => toggle(o.id)}>
                <td>
                  <button
                    className="sl-order-toggle sl-code"
                    aria-label={`Chi tiết đơn ${orderCode(o)}`}
                    aria-expanded={open === o.id}
                    aria-controls={`order-${o.id}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggle(o.id);
                    }}
                  >
                    {orderCode(o)} <span aria-hidden="true">{open === o.id ? "−" : "+"}</span>
                  </button>
                </td>
                <td>{o.created_at ? new Date(o.created_at).toLocaleString("vi-VN") : "—"}</td>
                <td>{o.items.map((i) => `${i.name} × ${i.quantity}`).join(", ")}</td>
                <td>
                  <b>{money(o.total)}</b>
                </td>
                <td>
                  <span className={`sl-badge sl-badge-${o.status}`}>{ORDER_STATUS[o.status] || o.status}</span>
                </td>
                <td>
                  <span className={`sl-badge sl-pay-${o.payment_status || "unpaid"}`}>
                    {o.payment_method === "bank_transfer" ? "CK" : "COD"} · {PAYMENT[o.payment_status || "unpaid"]}
                  </span>
                </td>
                <td className="sl-actions" onClick={(e) => e.stopPropagation()}>
                  {NEXT_STEP[o.status] && (
                    <ActionButton label={NEXT_STEP[o.status].label} icon="truck" disabled={busy === o.id} onClick={() => step(o)} />
                  )}
                  {o.status === "confirmed" && o.payment_status !== "paid" && (
                    <ActionButton label="Đã nhận tiền" icon="check" tone="sl-action-paid" disabled={busy === o.id} onClick={() => paid(o)} />
                  )}
                  {o.status === "confirmed" && (
                    <ActionButton label="Hủy đơn" icon="close" tone="sl-danger sl-action-cancel" disabled={busy === o.id} onClick={() => cancel(o)} />
                  )}
                </td>
              </tr>
              {open === o.id && <OrderDetail order={o} />}
            </Fragment>
          ))}
        </tbody>
      </table>
      {shown.length === 0 && <p className="sl-muted sl-center">Không có đơn phù hợp.</p>}
    </>
  );
}

function ActionButton({
  label,
  icon,
  tone = "",
  disabled,
  onClick,
}: {
  label: string;
  icon: "truck" | "check" | "close";
  tone?: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button className={`sl-btn-small sl-action-icon ${tone}`.trim()} title={label} aria-label={label} disabled={disabled} onClick={onClick}>
      <UiIcon name={icon} />
    </button>
  );
}

function OrderDetail({ order: o }: { order: Order }) {
  return (
    <tr id={`order-${o.id}`} className="sl-detail">
      <td colSpan={7}>
        <div className="sl-detail-grid">
          <div>
            <h3>Sản phẩm</h3>
            {o.items.map((i) => (
              <div key={i.sku_code} className="sl-line">
                <span>
                  {i.name} × {i.quantity}
                  <small>
                    {" "}
                    {i.sku_code}
                    {i.variant?.size !== undefined ? ` · Size ${String(i.variant.size)}` : ""}
                    {i.variant?.color ? ` · ${colorName(i.variant.color as string)}` : ""}
                  </small>
                </span>
                <span>{money(Number(i.unit_price) * i.quantity)}</span>
              </div>
            ))}
          </div>
          <div>
            <h3>Giao hàng</h3>
            <p>{o.shipping_address || "—"}</p>
            <p className="sl-muted">
              {o.payment_method === "bank_transfer" ? "Chuyển khoản ngân hàng" : "Thanh toán khi nhận hàng (COD)"} ·{" "}
              {PAYMENT[o.payment_status || "unpaid"]}
            </p>
            {o.payment_method !== "bank_transfer" && Number(o.total) > 2_000_000 && o.status === "confirmed" && (
              <p className="sl-warn">Đơn COD trên 2 triệu: gọi xác nhận trước khi giao.</p>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}
