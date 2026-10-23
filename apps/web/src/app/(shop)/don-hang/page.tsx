"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import VerifyPhone from "@/components/shop/VerifyPhone";
import TransferInfo, { Transfer } from "@/components/shop/TransferInfo";
import { api } from "@/services/api";
import { money } from "@/lib/catalog";
import { customerToken, setCustomerToken } from "@/lib/session";
import { shopContext } from "@/lib/shop-context";

type Order = {
  id: string;
  status: string;
  total: string;
  discount: string;
  created_at: string | null;
  payment_method: "cod" | "bank_transfer";
  payment_status: string;
  transfer: Transfer | null;
  items: { sku_code: string; name: string; quantity: number; unit_price: string; variant: Record<string, unknown> }[];
};

const PAYMENT: Record<string, string> = {
  unpaid: "Thanh toán khi nhận hàng",
  awaiting_transfer: "Chờ chuyển khoản",
  paid: "Đã thanh toán",
  refunded: "Đã hoàn tiền",
};

const STATUS: Record<string, string> = {
  confirmed: "Đã xác nhận",
  cancelled: "Đã hủy",
  shipping: "Đang giao",
  delivered: "Đã giao",
};

export default function OrdersPage() {
  const [token, setToken] = useState("");
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  const load = useCallback((t: string) => {
    setError("");
    api<Order[]>("/api/customer/orders", t)
      .then(setOrders)
      .catch((e) => {
        // A revoked or deleted customer: forget the token and verify again.
        setCustomerToken(null);
        setToken("");
        setError(e.message);
      });
  }, []);

  useEffect(() => {
    const t = customerToken();
    setToken(t);
    setReady(true);
    if (t) load(t);
  }, [load]);

  async function forget() {
    if (!window.confirm("Xóa số điện thoại, sở thích và lịch sử tư vấn đã lưu của bạn? Đơn hàng đã đặt vẫn được giữ để giao.")) return;
    try {
      await api("/api/customer/data", token, undefined, "DELETE");
      setCustomerToken(null);
      setToken("");
      setOrders(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không xóa được");
    }
  }

  if (!ready) return <div className="s-wrap s-page" />;

  if (!token)
    return (
      <div className="s-wrap s-page s-narrow">
        <h1 className="s-page-title">Đơn hàng của tôi</h1>
        <p className="s-lead">Xác minh số điện thoại đã dùng khi đặt hàng để xem đơn.</p>
        {error && <div className="s-alert">{error}</div>}
        <VerifyPhone
          onVerified={() => {
            const t = customerToken();
            setToken(t);
            load(t);
          }}
        />
      </div>
    );

  return (
    <div className="s-wrap s-page s-narrow">
      <h1 className="s-page-title">Đơn hàng của tôi</h1>
      {error && <div className="s-alert">{error}</div>}
      {orders === null ? (
        <p className="s-muted">Đang tải…</p>
      ) : orders.length === 0 ? (
        <div className="s-empty">
          Bạn chưa có đơn hàng nào. <Link href="/">Mua sắm ngay</Link>
        </div>
      ) : (
        <div className="s-orders">
          {orders.map((order) => (
            <article key={order.id} className="s-order">
              <header>
                <div>
                  <b>Đơn #{order.id.slice(0, 8).toUpperCase()}</b>
                  {order.created_at && <span className="s-muted"> · {new Date(order.created_at).toLocaleString("vi-VN")}</span>}
                </div>
                <span className={`s-status s-status-${order.status}`}>{STATUS[order.status] || order.status}</span>
              </header>
              {order.items.map((item) => (
                <div key={item.sku_code} className="s-order-item">
                  <span>
                    {item.name} × {item.quantity}
                    <small className="s-muted"> {item.sku_code}</small>
                  </span>
                  <span>{money(Number(item.unit_price) * item.quantity)}</span>
                </div>
              ))}
              {order.status !== "cancelled" && order.payment_status === "awaiting_transfer" && order.transfer && (
                <TransferInfo transfer={order.transfer} />
              )}
              <footer>
                <span>
                  Tổng: <b>{money(order.total)}</b>
                  <small className="s-muted">
                    {" · "}
                    {order.payment_method === "bank_transfer" ? "Chuyển khoản" : "COD"}
                    {" · "}
                    {PAYMENT[order.payment_status] || order.payment_status}
                  </small>
                </span>
                <button
                  className="s-link-btn"
                  onClick={() => shopContext.openChat(`Tôi muốn hỏi về đơn hàng #${order.id.slice(0, 8).toUpperCase()}`)}
                >
                  Hỏi về đơn này
                </button>
              </footer>
            </article>
          ))}
        </div>
      )}
      <div className="s-account-foot">
        <button className="s-link-btn" onClick={() => { setCustomerToken(null); setToken(""); setOrders(null); }}>
          Đăng xuất khỏi thiết bị này
        </button>
        <button className="s-link-btn s-danger" onClick={forget}>
          Xóa dữ liệu cá nhân của tôi
        </button>
      </div>
    </div>
  );
}
