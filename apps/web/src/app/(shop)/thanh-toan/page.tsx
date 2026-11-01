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
import { customerToken, openSession, ShopSession } from "@/lib/session";
import { useAccount } from "@/lib/account";

type Quote = {
  sku_code: string;
  sale_price: string;
  total: string;
  discount: string;
};
type Payment = "cod" | "bank_transfer";
type Methods = {
  cod: { enabled: boolean; max_total: string };
  bank_transfer: { enabled: boolean; bank_name: string | null };
};
type Order = {
  id: string;
  total: string;
  payment_method: Payment;
  items: { sku_code: string; name: string; quantity: number }[];
  transfer: Transfer | null;
};

export default function CheckoutPage() {
  const lines = useCart();
  const { items, error: catalogError, retry: retryCatalog } = useCartItems(lines);
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
  const [quotes, setQuotes] = useState<Quote[] | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [recoveryPending, setRecoveryPending] = useState(false);
  const submitting = useRef(false);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const errorNotice = useRef<HTMLDivElement>(null);
  useEffect(() => { if (placed) resultHeading.current?.focus(); }, [placed]);
  useEffect(() => { if (error) errorNotice.current?.focus(); }, [error]);
  const epoch = useRef(0);
  const attempt = useRef<{
    body: Record<string, unknown>;
    token: string;
  } | null>(null);
  const linesKey = JSON.stringify(lines);
  const fingerprint = JSON.stringify([
    lines,
    address,
    note,
    payment,
    session?.conversation_id,
  ]);
  const latest = useRef(fingerprint);
  latest.current = fingerprint;
  // One key for this checkout: a retried click never creates a second order.
  const key = useRef("");

  useEffect(() => {
    let active = true;
    epoch.current++;
    submitting.current = false;
    attempt.current = null;
    key.current = "";
    setSession(null);
    setPlaced(null);
    setAddress("");
    setNote("");
    setBusy(false);
    setUncertain(false);
    setRecoveryPending(false);
    setChecking(true);
    openSession()
      .then(async (session) => {
        if (!active) return;
        setSession(session);
        if (!session.customer_id) return;
        let saved = "";
        try {
          saved =
            sessionStorage.getItem(`checkout-pending:${session.customer_id}`) ||
            "";
        } catch {
          /* unavailable */
        }
        key.current = saved;
        if (saved) {
          setRecoveryPending(true);
          try {
            const recovered = await api<Order>(
              `/api/customer/orders/by-key/${encodeURIComponent(saved)}`,
              customerToken(),
            );
            if (active) {
              setPlaced(recovered);
              setRecoveryPending(false);
              try {
                sessionStorage.removeItem(
                  `checkout-pending:${session.customer_id}`,
                );
              } catch {
                /* unavailable */
              }
            }
          } catch (e) {
            if (active) {
              if ((e as { status?: number }).status === 404)
                setRecoveryPending(false);
              else
                setError(
                  "Chưa kiểm tra được đơn trước đó. Vui lòng tải lại trang để kiểm tra.",
                );
            }
          }
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    api<Methods>("/api/catalog/payment-methods")
      .then((methods) => {
        if (active) setMethods(methods);
      })
      .catch(() => {
        if (active)
          setError(
            "Chưa tải được phương thức thanh toán. Vui lòng tải lại trang.",
          );
      });
    return () => {
      active = false;
      epoch.current++;
    };
  }, [me?.customer_id]);

  useEffect(() => {
    const controller = new AbortController();
    setQuotes(null);
    if (lines.length)
      Promise.all(
        lines.map((item) =>
          api<Quote>(
            `/api/catalog/${encodeURIComponent(item.sku)}/quote?quantity=${item.qty}`,
            "",
            undefined,
            undefined,
            { signal: controller.signal },
          ),
        ),
      )
        .then((value) => {
          if (!controller.signal.aborted) setQuotes(value);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linesKey]);

  useEffect(() => {
    setConfirmed(false);
  }, [fingerprint, quotes]);

  const verified = !!session?.customer_id;
  const total = (quotes || []).reduce((s, quote) => s + Number(quote.total), 0);
  const codLimit = Number(methods?.cod.max_total || 10_000_000);
  const codAllowed = !!methods?.cod.enabled && total < codLimit;
  const transferAllowed = !!methods?.bank_transfer.enabled;

  // COD is not offered at or above the limit (policy VC-03): switch to transfer when possible.
  useEffect(() => {
    if (payment === "cod" && !codAllowed && transferAllowed)
      setPayment("bank_transfer");
  }, [payment, codAllowed, transferAllowed]);

  async function placeOrder() {
    if (
      !session ||
      !items ||
      !quotes ||
      recoveryPending ||
      (!confirmed && !uncertain) ||
      submitting.current ||
      !session.customer_id
    )
      return;
    submitting.current = true;
    const token = customerToken();
    const currentEpoch = epoch.current;
    const current = () =>
      epoch.current === currentEpoch && customerToken() === token;
    const shown = fingerprint;
    setBusy(true);
    setError("");
    try {
      if (!attempt.current) {
        const currentQuotes = await Promise.all(
          items.map((item) =>
            api<Quote>(
              `/api/catalog/${encodeURIComponent(item.sku)}/quote?quantity=${item.qty}`,
            ),
          ),
        );
        if (!current() || latest.current !== shown) return;
        if (
          JSON.stringify(
            currentQuotes.map((q) => [q.sku_code, q.sale_price, q.total]),
          ) !==
          JSON.stringify(quotes.map((q) => [q.sku_code, q.sale_price, q.total]))
        ) {
          setQuotes(currentQuotes);
          setError(
            "Giá đã thay đổi. Vui lòng kiểm tra tổng tiền và xác nhận lại.",
          );
          return;
        }
        key.current ||= newKey();
        attempt.current = {
          token,
          body: {
            items: items.map((item, i) => ({
              sku_code: item.sku,
              quantity: item.qty,
              expected_unit_price: quotes[i].sale_price,
            })),
            shipping_address: note.trim()
              ? `${address.trim()} (Ghi chú: ${note.trim()})`
              : address.trim(),
            expected_total: quotes
              .reduce((sum, q) => sum + Number(q.total), 0)
              .toFixed(2),
            confirmed: true,
            idempotency_key: key.current,
            payment_method: payment,
          },
        };
        try {
          sessionStorage.setItem(
            `checkout-pending:${session.customer_id}`,
            key.current,
          );
        } catch {
          /* unavailable */
        }
      }
      if (attempt.current.token !== token) {
        attempt.current = null;
        return;
      }
      let order: Order | null = null;
      if (uncertain) {
        try {
          order = await api<Order>(
            `/api/customer/orders/by-key/${encodeURIComponent(key.current)}`,
            token,
          );
        } catch (e) {
          if ((e as { status?: number }).status !== 404) throw e;
        }
        if (!current()) return;
      }
      order ||= await api<Order>(
        `/api/conversations/${session.conversation_id}/orders`,
        session.conversation_token,
        attempt.current.body,
      );
      if (!current()) return;
      attempt.current = null;
      setUncertain(false);
      try {
        sessionStorage.removeItem(`checkout-pending:${session.customer_id}`);
      } catch {
        /* unavailable */
      }
      if (latest.current === shown) cart.clear();
      setPlaced(order);
    } catch (e) {
      if (!current()) return;
      const status = (e as { status?: number }).status;
      if (
        status &&
        status >= 400 &&
        status < 500 &&
        ![408, 409, 429].includes(status)
      ) {
        attempt.current = null;
        key.current = "";
        setUncertain(false);
        setConfirmed(false);
        try {
          sessionStorage.removeItem(`checkout-pending:${session.customer_id}`);
        } catch {
          /* unavailable */
        }
      } else setUncertain(Boolean(attempt.current));
      setError(e instanceof Error ? e.message : "Không đặt được đơn hàng");
    } finally {
      if (current()) {
        submitting.current = false;
        setBusy(false);
      }
    }
  }

  if (placed) {
    return (
      <div className="s-wrap s-page s-done">
        <div className="s-done-icon">✓</div>
        <h1 ref={resultHeading} tabIndex={-1}>Đặt hàng thành công</h1>
        <p>
          Mã đơn <b>#{placed.id.slice(0, 8).toUpperCase()}</b> ·{" "}
          {money(placed.total)}.{" "}
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
  const nextStep = uncertain
    ? "Chưa rõ kết quả lần đặt trước. Hãy kiểm tra lại đơn trước khi thao tác tiếp."
    : !verified
      ? "Hoàn tất xác minh số điện thoại để tiếp tục."
      : !items || !quotes || !methods
        ? "Cần tải đủ giá, tồn kho và phương thức thanh toán trước khi đặt."
        : address.trim().length < 10
          ? "Nhập địa chỉ nhận hàng đầy đủ ở bước 2."
          : !canPay
            ? "Chọn phương thức thanh toán khả dụng ở bước 3."
            : !confirmed
              ? "Đánh dấu xác nhận sau khi kiểm tra lại đơn hàng."
              : "Bạn đã sẵn sàng đặt hàng. Giá sẽ được kiểm tra lại một lần nữa.";

  return (
    <div className="s-wrap s-page">
      <h1 className="s-page-title">Đặt hàng</h1>
      <p className="s-lead">4 bước để hoàn tất đơn hàng. Các mục bắt buộc được ghi rõ bên dưới.</p>
      <Link className="s-link-btn s-back-link" href="/gio-hang">← Chỉnh sửa giỏ hàng</Link>
      {error && <div ref={errorNotice} className="s-alert" role="alert" tabIndex={-1}>{error}</div>}
      {catalogError && <div className="s-alert" role="alert">{catalogError} <button className="s-link-btn" onClick={retryCatalog}>Thử lại thông tin sản phẩm</button></div>}
      <div className="s-cart">
        <div className="s-steps">
          <section className="s-step">
            <h2>
              <span className="s-step-no">1</span> Xác minh số điện thoại
            </h2>
            {checking ? (
              <p className="s-muted" role="status">Đang kiểm tra…</p>
            ) : verified ? (
              <p className="s-good">
                {me?.registered
                  ? `✓ Đặt hàng với tài khoản ${me.full_name || ""} (${me.phone || ""}).`
                  : "✓ Số điện thoại đã được xác minh trên thiết bị này."}
              </p>
            ) : (
              <>
                <p className="s-muted">
                  Để bảo vệ đơn hàng, cửa hàng cần xác minh số điện thoại của
                  bạn một lần.
                </p>
                <VerifyPhone onVerified={setSession} />
              </>
            )}
          </section>
          <section className={`s-step ${verified ? "" : "s-step-locked"}`}>
            <h2>
              <span className="s-step-no">2</span> Địa chỉ giao hàng
            </h2>
            <label>
              Địa chỉ nhận hàng · bắt buộc (số nhà, đường, phường/xã, quận/huyện,
              tỉnh/thành)
              <textarea
                rows={3}
                required
                disabled={!verified || busy || uncertain}
                autoComplete="street-address"
                aria-invalid={address.trim().length > 0 && address.trim().length < 10}
                aria-describedby="checkout-help"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </label>
            <label>
              Ghi chú cho người giao (không bắt buộc)
              <input
                disabled={!verified || busy || uncertain}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
          </section>
          <section className={`s-step ${verified ? "" : "s-step-locked"}`}>
            <h2>
              <span className="s-step-no">3</span> Thanh toán
            </h2>
            <div
              className="s-pay-options"
              role="radiogroup"
              aria-label="Phương thức thanh toán"
            >
              <label
                className={`s-pay-option ${payment === "cod" ? "active" : ""} ${codAllowed ? "" : "off"}`}
              >
                <input
                  type="radio"
                  name="payment"
                  disabled={!verified || !codAllowed || busy || uncertain}
                  checked={payment === "cod"}
                  onChange={() => setPayment("cod")}
                />
                <span>
                  <b>Thanh toán khi nhận hàng (COD)</b>
                  <small>
                    {codAllowed
                      ? "Miễn phí thu hộ. Kiểm tra hàng trước khi trả tiền."
                      : methods?.cod.enabled ? `Chỉ cho đơn dưới ${money(codLimit)}` : "Cửa hàng chưa mở COD"}
                  </small>
                </span>
              </label>
              <label
                className={`s-pay-option ${payment === "bank_transfer" ? "active" : ""} ${transferAllowed ? "" : "off"}`}
              >
                <input
                  type="radio"
                  name="payment"
                  disabled={!verified || !transferAllowed || busy || uncertain}
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
            {methods && !codAllowed && !transferAllowed && (
              <p className="s-warn">
                Chưa có phương thức thanh toán phù hợp cho đơn này. Vui lòng liên hệ cửa hàng để được hỗ trợ.
              </p>
            )}
          </section>
          <section className={`s-step ${verified ? "" : "s-step-locked"}`}>
            <h2>
              <span className="s-step-no">4</span> Xác nhận
            </h2>
            <label className="s-check">
              <input
                type="checkbox"
                disabled={!verified || !quotes || busy || uncertain}
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              Tôi đã kiểm tra sản phẩm, số lượng, địa chỉ và đồng ý đặt hàng
            </label>
            <button
              className="s-btn s-btn-lg"
              aria-busy={busy}
              aria-describedby="checkout-help"
              disabled={
                !verified ||
                recoveryPending ||
                (!confirmed && !uncertain) ||
                !canPay ||
                !methods ||
                address.trim().length < 10 ||
                busy ||
                !items ||
                !quotes
              }
              onClick={placeOrder}
            >
              {busy
                ? "Đang kiểm tra đơn…"
                : uncertain
                  ? "Kiểm tra lại đơn hàng"
                  : `Đặt hàng · ${money(total)}`}
            </button>
            <p id="checkout-help" className="s-muted" role="status">{nextStep}</p>
            {verified &&
              address.trim().length > 0 &&
              address.trim().length < 10 && (
                <p className="s-warn">Địa chỉ cần đầy đủ hơn để giao hàng.</p>
              )}
          </section>
        </div>
        <aside className="s-summary">
          <h2>Đơn hàng của bạn</h2>
          {(items || []).map((item) => (
            <div key={item.sku} className="s-summary-item">
              <span>
                {item.row?.name || item.sku} × {item.qty}
                {item.row && variantLabel(item.row) && (
                  <small>{variantLabel(item.row)}</small>
                )}
              </span>
              <span>
                {quotes?.find((q) => q.sku_code === item.sku)
                  ? money(quotes.find((q) => q.sku_code === item.sku)!.total)
                  : "…"}
              </span>
            </div>
          ))}
          <div className="s-summary-row">
            <span>Phí giao hàng</span>
            <span>
              {total >= 2_000_000 ? "Miễn phí" : "Nhân viên báo khi xác nhận"}
            </span>
          </div>
          <div className="s-summary-total">
            <span>Tổng cộng</span>
            <b>{quotes ? money(total) : "—"}</b>
          </div>
          <p className="s-muted">
            Giá được kiểm tra lại ngay khi đặt. Nếu giá thay đổi, hệ thống sẽ
            báo để bạn xác nhận lại.
          </p>
        </aside>
      </div>
    </div>
  );
}
