"use client";
// Checkout: verify the phone (one-time code), give the delivery address,
// choose how to pay, confirm. The whole cart is one order: every line is
// quoted again right before it is placed (`expected_*` must match), and stock
// for all lines is reserved together or not at all.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import VerifyPhone from "@/components/shop/VerifyPhone";
import TransferInfo, { Transfer } from "@/components/shop/TransferInfo";
import { api } from "@/services/api";
import { money, variantLabel } from "@/lib/catalog";
import { cart, useCart } from "@/lib/cart";
import { newKey, useCartItems } from "@/lib/cart-items";
import { openSession, ShopSession } from "@/lib/session";
import { useAccount } from "@/lib/account";

type Quote = { sku_code: string; sale_price: string; total: string; discount: string };
type Payment = "cod" | "bank_transfer";
type Methods = { cod: { enabled: boolean; max_total: string }; bank_transfer: { enabled: boolean; bank_name: string | null } };
type Order = {
  id: string;
  total: string;
  payment_method: Payment;
  items: { sku_code: string; name: string; quantity: number }[];
  transfer: Transfer | null;
};

export default function CheckoutPage() {
  const lines = useCart();
  const { items } = useCartItems(lines);
  const { account: me } = useAccount();
  const [session, setSession] = useState<ShopSession | null>(null);
  const [checking, setChecking] = useState(true);
  const [methods, setMethods] = useState<Methods | null>(null);
  const [payment, setPayment] = useState<Payment>("cod");
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [placed, setPlaced] = useState<Order | null>(null);
  // One key for this checkout: a retried click never creates a second order.
  const key = useRef("");

  useEffect(() => {
    openSession()
      .then(setSession)
      .catch((e) => setError(e.message))
      .finally(() => setChecking(false));
    api<Methods>("/api/catalog/payment-methods")
      .then(setMethods)
      .catch(() => setMethods({ cod: { enabled: true, max_total: "10000000" }, bank_transfer: { enabled: false, bank_name: null } }));
  }, []);

  const verified = !!session?.customer_id;
  const total = (items || []).reduce((s, i) => s + (i.row ? Number(i.row.sale_price) * i.qty : 0), 0);
  const codLimit = Number(methods?.cod.max_total || 10_000_000);
  const codAllowed = total < codLimit;
  const transferAllowed = !!methods?.bank_transfer.enabled;

  // COD is not offered at or above the limit (policy VC-03): switch to transfer when possible.
  useEffect(() => {
    if (payment === "cod" && !codAllowed && transferAllowed) setPayment("bank_transfer");
  }, [payment, codAllowed, transferAllowed]);

  async function placeOrder() {
    if (!session || !items) return;
    setBusy(true);
    setError("");
    try {
      const quotes = await Promise.all(
        items.map((item) => api<Quote>(`/api/catalog/${encodeURIComponent(item.sku)}/quote?quantity=${item.qty}`)),
      );
      key.current ||= newKey();
      const order = await api<Order>(`/api/conversations/${session.conversation_id}/orders`, session.conversation_token, {
        items: items.map((item, i) => ({ sku_code: item.sku, quantity: item.qty, expected_unit_price: quotes[i].sale_price })),
        shipping_address: note.trim() ? `${address.trim()} (Ghi chú: ${note.trim()})` : address.trim(),
        expected_total: quotes.reduce((sum, q) => sum + Number(q.total), 0).toFixed(2),
        confirmed: true,
        idempotency_key: key.current,
        payment_method: payment,
      });
      cart.clear();
      setPlaced(order);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không đặt được đơn hàng");
    } finally {
      setBusy(false);
    }
  }

  if (placed) {
    return (
      <div className="s-wrap s-page s-done">
        <div className="s-done-icon">✓</div>
        <h1>Đặt hàng thành công</h1>
        <p>
          Mã đơn <b>#{placed.id.slice(0, 8).toUpperCase()}</b> · {money(placed.total)}.{" "}
          {placed.payment_method === "bank_transfer"
            ? "Vui lòng chuyển khoản theo thông tin dưới đây."
            : "Bạn thanh toán khi nhận hàng. Nhân viên sẽ liên hệ xác nhận và giao hàng."}
        </p>
        <div className="s-done-list">
          {placed.items.map((item) => (
            <div key={item.sku_code}>
              <b>{item.name}</b> × {item.quantity}
            </div>
          ))}
        </div>
        {placed.transfer && <TransferInfo transfer={placed.transfer} />}
        <div className="s-row s-center">
          <Link className="s-btn" href="/don-hang">
            Xem đơn hàng
          </Link>
          <Link className="s-btn s-btn-outline" href="/">
            Tiếp tục mua sắm
          </Link>
        </div>
      </div>
    );
  }

  if (!lines.length)
    return (
      <div className="s-wrap s-page s-empty-state">
        <h1>Chưa có sản phẩm để đặt</h1>
        <Link className="s-btn" href="/">
          Tiếp tục mua sắm
        </Link>
      </div>
    );

  const canPay = payment === "cod" ? codAllowed : transferAllowed;

  return (
    <div className="s-wrap s-page">
      <h1 className="s-page-title">Đặt hàng</h1>
      {error && <div className="s-alert">{error}</div>}
      <div className="s-cart">
        <div className="s-steps">
          <section className="s-step">
            <h2>
              <span className="s-step-no">1</span> Xác minh số điện thoại
            </h2>
            {checking ? (
              <p className="s-muted">Đang kiểm tra…</p>
            ) : verified ? (
              <p className="s-good">
                {me?.registered
                  ? `✓ Đặt hàng với tài khoản ${me.full_name || ""} (${me.phone || ""}).`
                  : "✓ Số điện thoại đã được xác minh trên thiết bị này."}
              </p>
            ) : (
              <>
                <p className="s-muted">Để bảo vệ đơn hàng, cửa hàng cần xác minh số điện thoại của bạn một lần.</p>
                <VerifyPhone onVerified={setSession} />
              </>
            )}
          </section>
          <section className={`s-step ${verified ? "" : "s-step-locked"}`}>
            <h2>
              <span className="s-step-no">2</span> Địa chỉ giao hàng
            </h2>
            <label>
              Địa chỉ nhận hàng (số nhà, đường, phường/xã, quận/huyện, tỉnh/thành)
              <textarea
                rows={3}
                required
                disabled={!verified}
                autoComplete="street-address"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </label>
            <label>
              Ghi chú cho người giao (không bắt buộc)
              <input disabled={!verified} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
          </section>
          <section className={`s-step ${verified ? "" : "s-step-locked"}`}>
            <h2>
              <span className="s-step-no">3</span> Thanh toán
            </h2>
            <div className="s-pay-options" role="radiogroup" aria-label="Phương thức thanh toán">
              <label className={`s-pay-option ${payment === "cod" ? "active" : ""} ${codAllowed ? "" : "off"}`}>
                <input
                  type="radio"
                  name="payment"
                  disabled={!verified || !codAllowed}
                  checked={payment === "cod"}
                  onChange={() => setPayment("cod")}
                />
                <span>
                  <b>Thanh toán khi nhận hàng (COD)</b>
                  <small>
                    {codAllowed ? "Miễn phí thu hộ. Kiểm tra hàng trước khi trả tiền." : `Chỉ cho đơn dưới ${money(codLimit)}`}
                  </small>
                </span>
              </label>
              <label className={`s-pay-option ${payment === "bank_transfer" ? "active" : ""} ${transferAllowed ? "" : "off"}`}>
                <input
                  type="radio"
                  name="payment"
                  disabled={!verified || !transferAllowed}
                  checked={payment === "bank_transfer"}
                  onChange={() => setPayment("bank_transfer")}
                />
                <span>
                  <b>Chuyển khoản ngân hàng (VietQR)</b>
                  <small>
                    {transferAllowed
                      ? `Quét mã QR sau khi đặt${methods?.bank_transfer.bank_name ? ` · ${methods.bank_transfer.bank_name}` : ""}. Đơn được ưu tiên xử lý.`
                      : "Cửa hàng chưa mở chuyển khoản"}
                  </small>
                </span>
              </label>
            </div>
            {!codAllowed && !transferAllowed && (
              <p className="s-warn">
                Đơn từ {money(codLimit)} cần chuyển khoản trước. Hãy liên hệ cửa hàng hoặc tách thành nhiều đơn.
              </p>
            )}
          </section>
          <section className={`s-step ${verified ? "" : "s-step-locked"}`}>
            <h2>
              <span className="s-step-no">4</span> Xác nhận
            </h2>
            <label className="s-check">
              <input type="checkbox" disabled={!verified} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              Tôi đã kiểm tra sản phẩm, số lượng, địa chỉ và đồng ý đặt hàng
            </label>
            <button
              className="s-btn s-btn-lg"
              disabled={!verified || !confirmed || !canPay || address.trim().length < 10 || busy || !items}
              onClick={placeOrder}
            >
              {busy ? "Đang đặt hàng…" : `Đặt hàng · ${money(total)}`}
            </button>
            {verified && address.trim().length > 0 && address.trim().length < 10 && (
              <p className="s-warn">Địa chỉ cần đầy đủ hơn để giao hàng.</p>
            )}
          </section>
        </div>
        <aside className="s-summary">
          <h3>Đơn hàng của bạn</h3>
          {(items || []).map((item) => (
            <div key={item.sku} className="s-summary-item">
              <span>
                {item.row?.name || item.sku} × {item.qty}
                {item.row && variantLabel(item.row) && <small>{variantLabel(item.row)}</small>}
              </span>
              <span>{item.row ? money(Number(item.row.sale_price) * item.qty) : "…"}</span>
            </div>
          ))}
          <div className="s-summary-row">
            <span>Phí giao hàng</span>
            <span>{total >= 2_000_000 ? "Miễn phí" : "Nhân viên báo khi xác nhận"}</span>
          </div>
          <div className="s-summary-total">
            <span>Tổng cộng</span>
            <b>{money(total)}</b>
          </div>
          <p className="s-muted">Giá được kiểm tra lại ngay khi đặt. Nếu giá thay đổi, hệ thống sẽ báo để bạn xác nhận lại.</p>
        </aside>
      </div>
    </div>
  );
}
