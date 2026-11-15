"use client";
// /ban-hang/tong-quan: today's numbers, who waits for a person, the latest orders. Each card links to its section.
import Link from "next/link";
import { useMemo } from "react";
import { money } from "@/lib/catalog";
import { reasonLabel } from "./handoff-reasons";
import { CHANNEL, isToday, ORDER_STATUS, orderCode } from "./labels";
import { SalesIcon, salesHref } from "./nav";
import { useSales } from "./sales-context";

export default function Overview() {
  const { calls, orders, callbacks, waiting } = useSales();
  const open = (calls || []).filter((c) => !c.ended_at);
  const todayOrders = (orders || []).filter((o) => isToday(o.created_at) && o.status !== "cancelled");
  const revenue = todayOrders.reduce((sum, o) => sum + Number(o.total), 0);
  const pending = (orders || []).filter((o) => o.status === "confirmed");
  const byChannel = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of calls || []) counts[c.channel] = (counts[c.channel] || 0) + 1;
    return counts;
  }, [calls]);
  const conversations = salesHref("conversations");
  const orderList = salesHref("orders");

  return (
    <>
      <div className="sl-kpis">
        {calls && (
          <Link className="sl-kpi" href={conversations}>
            <i>
              <SalesIcon name="conversations" />
            </i>
            <span>Đang trò chuyện</span>
            <b>{open.length}</b>
            <small>{Object.entries(byChannel).map(([ch, n]) => `${CHANNEL[ch] || ch} ${n}`).join(" · ") || "—"}</small>
          </Link>
        )}
        {calls && (
          <Link className={`sl-kpi ${waiting.length ? "sl-kpi-hot" : ""}`} href={conversations}>
            <i>
              <SalesIcon name="alert" />
            </i>
            <span>Chờ nhân viên</span>
            <b>{waiting.length}</b>
            <small>Khách AI đã chuyển máy</small>
          </Link>
        )}
        {orders && (
          <Link className="sl-kpi" href={orderList}>
            <i>
              <SalesIcon name="money" />
            </i>
            <span>Đơn hôm nay</span>
            <b>{todayOrders.length}</b>
            <small>Doanh thu {money(revenue)}</small>
          </Link>
        )}
        {orders && (
          <Link className="sl-kpi sl-kpi-warn" href={orderList}>
            <i>
              <SalesIcon name="orders" />
            </i>
            <span>Đơn chờ xử lý</span>
            <b>{pending.length}</b>
            <small>Cần gọi xác nhận đơn trên 2 triệu</small>
          </Link>
        )}
        {callbacks && (
          <Link className="sl-kpi" href={salesHref("callbacks")}>
            <i>
              <SalesIcon name="clock" />
            </i>
            <span>Hẹn gọi lại</span>
            <b>{callbacks.length}</b>
            <small>Do trợ lý AI đặt lịch</small>
          </Link>
        )}
      </div>

      <div className="sl-columns">
        {calls && (
          <section className="sl-panel">
            <header>
              <h2>Khách đang chờ nhân viên</h2>
              <Link className="sl-link" href={conversations}>
                Mở hội thoại →
              </Link>
            </header>
            {waiting.length === 0 ? (
              <p className="sl-muted">Không có khách nào đang chờ. AI đang xử lý các cuộc trò chuyện.</p>
            ) : (
              waiting.slice(0, 6).map((c) => (
                <div key={c.id} className="sl-row">
                  <div>
                    <b>{c.customer_label || (c.phone_last4 ? `Khách ···${c.phone_last4}` : "Khách chưa xác định")}</b>
                    <small>
                      {CHANNEL[c.channel] || c.channel} · {c.handoff_reason ? reasonLabel(c.handoff_reason) : "Cần hỗ trợ"}
                    </small>
                  </div>
                  <span className="sl-badge sl-badge-hot">Chờ nhận</span>
                </div>
              ))
            )}
          </section>
        )}
        {orders && (
          <section className="sl-panel">
            <header>
              <h2>Đơn mới nhất</h2>
              <Link className="sl-link" href={orderList}>
                Tất cả đơn →
              </Link>
            </header>
            {orders.length === 0 ? (
              <p className="sl-muted">Chưa có đơn hàng.</p>
            ) : (
              orders.slice(0, 6).map((o) => (
                <div key={o.id} className="sl-row">
                  <div>
                    <b className="sl-code">{orderCode(o)}</b>
                    <small>{o.items.map((i) => `${i.name} × ${i.quantity}`).join(", ")}</small>
                  </div>
                  <div className="sl-right">
                    <b>{money(o.total)}</b>
                    <span className={`sl-badge sl-badge-${o.status}`}>{ORDER_STATUS[o.status] || o.status}</span>
                  </div>
                </div>
              ))
            )}
          </section>
        )}
      </div>
    </>
  );
}
