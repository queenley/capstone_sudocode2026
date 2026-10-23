"use client";
// The sales team's workspace: one place for live conversations and handoffs,
// orders, call-backs the assistant booked, and today's numbers.
//
// Sign-in is the staff login (/login): its token is in sessionStorage
// ("staff-token"). What a person sees follows their role, as the API enforces:
// consultants (agent) the conversations and call-backs, sellers the orders,
// admins everything.
import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import CallConsole from "@/features/call-console";
import { api, AgentCall } from "@/services/api";
import { colorName, money } from "@/lib/catalog";
import "./sales.css";

type Order = {
  id: string;
  status: string;
  total: string;
  created_at: string | null;
  conversation_id: string | null;
  shipping_address?: string;
  payment_method?: "cod" | "bank_transfer";
  payment_status?: string;
  items: { sku_code: string; name: string; quantity: number; unit_price: string; variant: Record<string, unknown> }[];
};
type Callback = {
  callback_id: string;
  callback_at: string;
  moved_from: string | null;
  note: string | null;
  phone_last4: string | null;
  customer_name: string | null;
};
type Tab = "overview" | "conversations" | "orders" | "callbacks";

const TABS: { id: Tab; label: string; needs: "calls" | "orders" | null }[] = [
  { id: "overview", label: "Tổng quan", needs: null },
  { id: "conversations", label: "Hội thoại & chuyển máy", needs: "calls" },
  { id: "orders", label: "Đơn hàng", needs: "orders" },
  { id: "callbacks", label: "Hẹn gọi lại", needs: "calls" },
];
const STATUS: Record<string, string> = { confirmed: "Chờ xử lý", cancelled: "Đã hủy", shipping: "Đang giao", delivered: "Đã giao" };
const CHANNEL: Record<string, string> = { web: "Web", zalo: "Zalo", hotline: "Hotline", facebook: "Facebook" };
const PAYMENT: Record<string, string> = { unpaid: "Chưa thu", awaiting_transfer: "Chờ chuyển khoản", paid: "Đã thanh toán", refunded: "Đã hoàn" };

function isToday(iso: string | null): boolean {
  if (!iso) return false;
  return new Date(iso).toDateString() === new Date().toDateString();
}

export default function SalesPage() {
  const [token, setToken] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [calls, setCalls] = useState<AgentCall[] | null>(null);
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [callbacks, setCallbacks] = useState<Callback[] | null>(null);
  const [access, setAccess] = useState({ calls: false, orders: false });
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setToken(sessionStorage.getItem("staff-token") || "");
    const wanted = new URLSearchParams(window.location.search).get("tab") as Tab | null;
    if (wanted && TABS.some((t) => t.id === wanted)) setTab(wanted);
  }, []);

  // What this token may read decides which sections exist (403 = not this role).
  const refresh = useCallback(async () => {
    if (!token) return;
    const [c, o, cb] = await Promise.allSettled([
      api<AgentCall[]>("/api/agent/calls?open_only=false&limit=100", token),
      api<Order[]>("/api/seller/orders", token),
      api<Callback[]>("/api/agent/callbacks", token),
    ]);
    setAccess({ calls: c.status === "fulfilled", orders: o.status === "fulfilled" });
    if (c.status === "fulfilled") setCalls(c.value);
    if (o.status === "fulfilled") setOrders(o.value);
    if (cb.status === "fulfilled") setCallbacks(cb.value);
    if (c.status === "rejected" && o.status === "rejected") setError("Tài khoản này không có quyền vào trang bán hàng.");
    else setError("");
    setChecked(true);
  }, [token]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [refresh]);

  function go(next: Tab) {
    setTab(next);
    window.history.replaceState(null, "", `/ban-hang?tab=${next}`);
  }

  if (token === null) return null;
  if (!token)
    return (
      <div className="sl-gate">
        <h1>Trang bán hàng</h1>
        <p>Đăng nhập bằng tài khoản nhân viên để xem hội thoại, đơn hàng và lịch gọi lại.</p>
        <Link className="sl-btn" href="/login?next=/ban-hang">
          Đăng nhập
        </Link>
      </div>
    );

  const visible = TABS.filter((t) => !t.needs || access[t.needs]);
  const waiting = (calls || []).filter((c) => c.handoff_status === "pending" && !c.ended_at);

  return (
    <div className="sl-app">
      <aside className="sl-side">
        <Link href="/" className="sl-logo">
          <span>t</span> tiếp<b>nối</b>
        </Link>
        <span className="sl-side-label">Bán hàng</span>
        <nav>
          {visible.map((t) => (
            <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => go(t.id)}>
              {t.label}
              {t.id === "conversations" && waiting.length > 0 && <span className="sl-dot">{waiting.length}</span>}
              {t.id === "callbacks" && (callbacks?.length || 0) > 0 && <span className="sl-count">{callbacks!.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sl-side-foot">
          <Link href="/developer">Agent Console</Link>
          <Link href="/admin">Quản trị</Link>
          <button
            onClick={() => {
              sessionStorage.removeItem("staff-token");
              setToken("");
            }}
          >
            Đăng xuất
          </button>
        </div>
      </aside>
      <main className="sl-main">
        {error && <div className="sl-alert">{error}</div>}
        {!checked ? (
          <p className="sl-muted">Đang tải…</p>
        ) : tab === "overview" ? (
          <Overview calls={calls} orders={orders} callbacks={callbacks} waiting={waiting} go={go} />
        ) : tab === "conversations" ? (
          <div className="sl-console">
            <CallConsole embedded />
          </div>
        ) : tab === "orders" ? (
          <Orders orders={orders || []} token={token} onChange={refresh} />
        ) : (
          <Callbacks callbacks={callbacks || []} />
        )}
      </main>
    </div>
  );
}

function Overview({
  calls,
  orders,
  callbacks,
  waiting,
  go,
}: {
  calls: AgentCall[] | null;
  orders: Order[] | null;
  callbacks: Callback[] | null;
  waiting: AgentCall[];
  go: (tab: Tab) => void;
}) {
  const open = (calls || []).filter((c) => !c.ended_at);
  const todayOrders = (orders || []).filter((o) => isToday(o.created_at) && o.status !== "cancelled");
  const revenue = todayOrders.reduce((sum, o) => sum + Number(o.total), 0);
  const pending = (orders || []).filter((o) => o.status === "confirmed");
  const byChannel = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of calls || []) counts[c.channel] = (counts[c.channel] || 0) + 1;
    return counts;
  }, [calls]);

  return (
    <>
      <h1>Tổng quan hôm nay</h1>
      <div className="sl-kpis">
        {calls && (
          <button className="sl-kpi" onClick={() => go("conversations")}>
            <span>Đang trò chuyện</span>
            <b>{open.length}</b>
            <small>{Object.entries(byChannel).map(([ch, n]) => `${CHANNEL[ch] || ch} ${n}`).join(" · ") || "—"}</small>
          </button>
        )}
        {calls && (
          <button className={`sl-kpi ${waiting.length ? "sl-kpi-hot" : ""}`} onClick={() => go("conversations")}>
            <span>Chờ nhân viên</span>
            <b>{waiting.length}</b>
            <small>Khách AI đã chuyển máy</small>
          </button>
        )}
        {orders && (
          <button className="sl-kpi" onClick={() => go("orders")}>
            <span>Đơn hôm nay</span>
            <b>{todayOrders.length}</b>
            <small>Doanh thu {money(revenue)}</small>
          </button>
        )}
        {orders && (
          <button className="sl-kpi" onClick={() => go("orders")}>
            <span>Đơn chờ xử lý</span>
            <b>{pending.length}</b>
            <small>Cần gọi xác nhận đơn trên 2 triệu</small>
          </button>
        )}
        {callbacks && (
          <button className="sl-kpi" onClick={() => go("callbacks")}>
            <span>Hẹn gọi lại</span>
            <b>{callbacks.length}</b>
            <small>Do trợ lý AI đặt lịch</small>
          </button>
        )}
      </div>

      <div className="sl-columns">
        {calls && (
          <section className="sl-panel">
            <header>
              <h2>Khách đang chờ nhân viên</h2>
              <button className="sl-link" onClick={() => go("conversations")}>
                Mở hội thoại →
              </button>
            </header>
            {waiting.length === 0 ? (
              <p className="sl-muted">Không có khách nào đang chờ. AI đang xử lý các cuộc trò chuyện.</p>
            ) : (
              waiting.slice(0, 6).map((c) => (
                <div key={c.id} className="sl-row">
                  <div>
                    <b>{c.customer_label || (c.phone_last4 ? `Khách ···${c.phone_last4}` : "Khách chưa xác định")}</b>
                    <small>
                      {CHANNEL[c.channel] || c.channel} · {c.handoff_reason || "Cần hỗ trợ"}
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
              <button className="sl-link" onClick={() => go("orders")}>
                Tất cả đơn →
              </button>
            </header>
            {orders.length === 0 ? (
              <p className="sl-muted">Chưa có đơn hàng.</p>
            ) : (
              orders.slice(0, 6).map((o) => (
                <div key={o.id} className="sl-row">
                  <div>
                    <b>#{o.id.slice(0, 8).toUpperCase()}</b>
                    <small>{o.items.map((i) => `${i.name} × ${i.quantity}`).join(", ")}</small>
                  </div>
                  <div className="sl-right">
                    <b>{money(o.total)}</b>
                    <span className={`sl-badge sl-badge-${o.status}`}>{STATUS[o.status] || o.status}</span>
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

function Orders({ orders, token, onChange }: { orders: Order[]; token: string; onChange: () => void }) {
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const shown = orders.filter(
    (o) =>
      (status === "all" || o.status === status) &&
      (!query.trim() ||
        o.id.toLowerCase().includes(query.trim().toLowerCase()) ||
        o.items.some((i) => (i.name + " " + i.sku_code).toLowerCase().includes(query.trim().toLowerCase()))),
  );

  async function paid(order: Order) {
    if (!window.confirm(`Xác nhận đã nhận đủ ${money(order.total)} cho đơn #${order.id.slice(0, 8).toUpperCase()}?`)) return;
    setBusy(order.id);
    setError("");
    try {
      await api(`/api/seller/orders/${order.id}/paid`, token, {});
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không cập nhật được");
    } finally {
      setBusy("");
    }
  }

  async function cancel(order: Order) {
    if (!window.confirm(`Hủy đơn #${order.id.slice(0, 8).toUpperCase()}? Hàng giữ cho đơn sẽ được trả lại kho.`)) return;
    setBusy(order.id);
    setError("");
    try {
      await api(`/api/seller/orders/${order.id}/cancel`, token, {});
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không hủy được");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <h1>Đơn hàng</h1>
      <div className="sl-toolbar">
        <input placeholder="Tìm mã đơn, sản phẩm, SKU…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">Tất cả trạng thái</option>
          {Object.entries(STATUS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <span className="sl-muted">{shown.length} đơn</span>
      </div>
      {error && <div className="sl-alert">{error}</div>}
      <table className="sl-table">
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
              <tr className={open === o.id ? "open" : ""} onClick={() => setOpen(open === o.id ? null : o.id)}>
                <td>
                  <b>#{o.id.slice(0, 8).toUpperCase()}</b>
                </td>
                <td>{o.created_at ? new Date(o.created_at).toLocaleString("vi-VN") : "—"}</td>
                <td>{o.items.map((i) => `${i.name} × ${i.quantity}`).join(", ")}</td>
                <td>
                  <b>{money(o.total)}</b>
                </td>
                <td>
                  <span className={`sl-badge sl-badge-${o.status}`}>{STATUS[o.status] || o.status}</span>
                </td>
                <td>
                  <span className={`sl-badge sl-pay-${o.payment_status || "unpaid"}`}>
                    {o.payment_method === "bank_transfer" ? "CK" : "COD"} · {PAYMENT[o.payment_status || "unpaid"]}
                  </span>
                </td>
                <td className="sl-actions">
                  {o.status === "confirmed" && o.payment_status !== "paid" && (
                    <button
                      className="sl-btn-small"
                      disabled={busy === o.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        paid(o);
                      }}
                    >
                      Đã nhận tiền
                    </button>
                  )}
                  {o.status === "confirmed" && (
                    <button
                      className="sl-btn-small sl-danger"
                      disabled={busy === o.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        cancel(o);
                      }}
                    >
                      Hủy
                    </button>
                  )}
                </td>
              </tr>
              {open === o.id && (
                <tr className="sl-detail">
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
                                {i.variant?.size !== undefined ? ` · Size ${i.variant.size}` : ""}
                                {i.variant?.color ? ` · ${colorName(i.variant.color)}` : ""}
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
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {shown.length === 0 && <p className="sl-muted sl-center">Không có đơn phù hợp.</p>}
    </>
  );
}

function Callbacks({ callbacks }: { callbacks: Callback[] }) {
  return (
    <>
      <h1>Hẹn gọi lại</h1>
      <p className="sl-muted">
        Lịch do trợ lý AI đặt khi khách hẹn gọi lại (giờ đã được dời khỏi ngày nghỉ và ngoài giờ làm việc). Số điện thoại
        đầy đủ xem trong hồ sơ cuộc gọi.
      </p>
      {callbacks.length === 0 ? (
        <p className="sl-muted sl-center">Chưa có lịch hẹn.</p>
      ) : (
        <table className="sl-table">
          <thead>
            <tr>
              <th>Thời gian</th>
              <th>Khách</th>
              <th>Ghi chú</th>
              <th>Mã</th>
            </tr>
          </thead>
          <tbody>
            {callbacks.map((cb) => (
              <tr key={cb.callback_id}>
                <td>
                  <b>{new Date(cb.callback_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })}</b>
                  {cb.moved_from && <small className="sl-muted"> (khách hẹn {cb.moved_from.replace("T", " ")})</small>}
                </td>
                <td>
                  {cb.customer_name || "Khách"} {cb.phone_last4 && <span className="sl-muted">···{cb.phone_last4}</span>}
                </td>
                <td>{cb.note || "—"}</td>
                <td className="sl-muted">{cb.callback_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
