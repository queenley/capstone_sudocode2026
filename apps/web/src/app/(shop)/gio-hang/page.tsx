"use client";
import Link from "next/link";
import EmptyState from "@/components/shop/EmptyState";
import Icon from "@/components/ui/Icon";

/** Orders from this total ship free (store policy, chinh-sach#giao-hang). */
const FREE_SHIPPING = 2_000_000;
import { useEffect, useState } from "react";
import ProductArt from "@/components/product/ProductArt";
import { money, variantLabel } from "@/lib/catalog";
import { cart, useCart } from "@/lib/cart";
import { useCartItems } from "@/lib/cart-items";
import { useAccount } from "@/lib/account";
import { awaitsCall, CALL_NOTE, CustomerOrder, isOpen, orderCode, statusLabel } from "@/lib/orders";
import { customerToken } from "@/lib/session";
import { api } from "@/services/api";

export default function CartPage() {
  const lines = useCart();
  const { items, error, retry } = useCartItems(lines);
  const subtotal = (items || []).reduce((sum, i) => sum + (i.row ? Number(i.row.sale_price) * i.qty : 0), 0);
  const listTotal = (items || []).reduce((sum, i) => sum + (i.row ? Number(i.row.list_price) * i.qty : 0), 0);
  const problems = (items || []).filter((i) => !i.row || i.row.available < i.qty);

  if (!lines.length)
    return (
      <EmptyState
        title="Giỏ hàng trống"
        line="Hãy chọn vài sản phẩm, hoặc hỏi trợ lý để được gợi ý."
        actions={<Link className="s-btn" href="/">Tiếp tục mua sắm</Link>}
      >
        <OpenOrders />
      </EmptyState>
    );

  return (
    <div className="s-wrap s-page">
      <h1 className="s-page-title">Giỏ hàng ({lines.reduce((s, l) => s + l.qty, 0)})</h1>
      <p className="s-lead">Kiểm tra sản phẩm và số lượng trước khi đặt hàng.</p>
      {error && <div className="s-alert" role="alert">{error} <button className="s-link-btn" onClick={retry}>Thử lại</button></div>}
      {!items && !error && <p className="s-muted" role="status">Đang kiểm tra giá và tồn kho…</p>}
      <div className="s-cart">
        <div className="s-cart-lines">
          {(items || lines.map((l) => ({ ...l, row: null }))).map((item) => (
            <div className="s-cart-line" key={item.sku}>
              <ProductArt category={item.row?.category || ""} size="thumb" image={item.row?.image_url} alt={item.row?.name || ""} />
              <div className="s-cart-line-info">
                {item.row ? (
                  <Link href={`/san-pham/${encodeURIComponent(item.row.product_ref || item.sku)}`}>
                    <b>{item.row.name}</b>
                  </Link>
                ) : (
                  <b>{items ? `Sản phẩm ${item.sku} không còn bán` : error ? item.sku : "Đang tải…"}</b>
                )}
                <span className="s-muted">
                  {item.sku}
                  {item.row && variantLabel(item.row) ? ` · ${variantLabel(item.row)}` : ""}
                </span>
                {item.row && item.row.available < item.qty && (
                  <span className="s-warn">
                    {item.row.available > 0 ? `Chỉ còn ${item.row.available} sản phẩm` : "Tạm hết hàng"}
                  </span>
                )}
              </div>
              <div className="s-qty">
                <button disabled={item.qty <= 1} onClick={() => cart.set(item.sku, item.qty - 1)} aria-label={`Giảm số lượng ${item.row?.name || item.sku}`}>
                  −
                </button>
                <span aria-live="polite" aria-atomic="true">{item.qty}</span>
                <button disabled={!item.row || item.qty >= Math.min(99, item.row.available)} onClick={() => cart.set(item.sku, item.qty + 1)} aria-label={`Tăng số lượng ${item.row?.name || item.sku}`}>
                  +
                </button>
              </div>
              <div className="s-cart-line-price">
                {item.row && <b>{money(Number(item.row.sale_price) * item.qty)}</b>}
                <button className="s-link-btn s-danger" aria-label={`Xóa ${item.row?.name || item.sku} khỏi giỏ`} onClick={() => cart.remove(item.sku)}>
                  <Icon name="trash" size={16} /> Xóa
                </button>
              </div>
            </div>
          ))}
        </div>
        <aside className="s-summary">
          <h2>Tóm tắt đơn hàng</h2>
          <div className="s-summary-row">
            <span>Tạm tính</span>
            <span>{items ? money(listTotal) : "—"}</span>
          </div>
          {listTotal > subtotal && (
            <div className="s-summary-row s-good">
              <span>Giảm giá</span>
              <span>−{money(listTotal - subtotal)}</span>
            </div>
          )}
          <div className="s-summary-row">
            <span>Phí giao hàng</span>
            <span>{!items ? "—" : subtotal >= FREE_SHIPPING ? "Miễn phí" : "Tính khi xác nhận"}</span>
          </div>
          {/* How far the cart is from free delivery: a bar and one line, so the shopper knows before checkout. */}
          {items && (
            <div className="s-ship-meter" role="status">
              <Icon name="truck" size={18} />
              <div>
                <p>{subtotal >= FREE_SHIPPING ? "Đơn của bạn được miễn phí giao hàng." : `Mua thêm ${money(FREE_SHIPPING - subtotal)} để được miễn phí giao hàng.`}</p>
                <span className="s-ship-meter__bar" aria-hidden="true"><i style={{ width: `${Math.min(100, (subtotal / FREE_SHIPPING) * 100)}%` }} /></span>
              </div>
            </div>
          )}
          <div className="s-summary-total">
            <span>Tổng cộng</span>
            <b>{items ? money(subtotal) : "—"}</b>
          </div>
          {problems.length || !items ? (
            <button className="s-btn s-btn-lg s-btn-block" disabled>Tiến hành đặt hàng</button>
          ) : (
            <Link className="s-btn s-btn-lg s-btn-block" href="/thanh-toan">Tiến hành đặt hàng</Link>
          )}
          {problems.length > 0 && <p className="s-warn">Điều chỉnh số lượng các sản phẩm không đủ hàng để tiếp tục.</p>}
          <ul className="s-summary-trust">
            <li><Icon name="card" size={16} /> Trả khi nhận hàng cho đơn dưới 10.000.000₫</li>
            <li><Icon name="return" size={16} /> Đổi trả trong 7 ngày</li>
          </ul>
          <Link className="s-link-btn s-back-link" href="/">
            <Icon name="arrow-left" size={16} /> Tiếp tục mua sắm
          </Link>
        </aside>
      </div>
    </div>
  );
}

/** A signed-in customer with an empty cart may be looking for what they already ordered: the orders still on their
 *  way, and which of them the shop will call about before shipping. */
function OpenOrders() {
  const { account } = useAccount();
  const [orders, setOrders] = useState<CustomerOrder[] | null>(null);

  useEffect(() => {
    const token = customerToken();
    if (!account || !token) return;
    api<CustomerOrder[]>("/api/customer/orders", token)
      .then((all) => setOrders(all.filter(isOpen)))
      .catch(() => setOrders([]));
  }, [account]);

  if (!account || !orders?.length) return null;
  return (
    <section className="s-open-orders" aria-label="Đơn hàng đang xử lý">
      <h2>Bạn có {orders.length} đơn đang xử lý</h2>
      <ul>
        {orders.slice(0, 3).map((order) => (
          <li key={order.id}>
            <span>
              <b>{orderCode(order)}</b>
              <small>{order.items.map((i) => `${i.name} × ${i.quantity}`).join(", ")}</small>
            </span>
            <span className={`s-status s-status-${awaitsCall(order) ? "call" : order.status}`}>{statusLabel(order)}</span>
          </li>
        ))}
      </ul>
      {orders.some(awaitsCall) && <p className="s-order-note">{CALL_NOTE}</p>}
      <Link className="s-link-btn" href="/don-hang">
        Xem tất cả đơn hàng →
      </Link>
    </section>
  );
}
