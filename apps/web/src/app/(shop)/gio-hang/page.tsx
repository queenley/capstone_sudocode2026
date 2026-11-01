"use client";
import Link from "next/link";
import ProductArt from "@/components/product/ProductArt";
import { money, variantLabel } from "@/lib/catalog";
import { cart, useCart } from "@/lib/cart";
import { useCartItems } from "@/lib/cart-items";

export default function CartPage() {
  const lines = useCart();
  const { items, error, retry } = useCartItems(lines);
  const subtotal = (items || []).reduce((sum, i) => sum + (i.row ? Number(i.row.sale_price) * i.qty : 0), 0);
  const listTotal = (items || []).reduce((sum, i) => sum + (i.row ? Number(i.row.list_price) * i.qty : 0), 0);
  const problems = (items || []).filter((i) => !i.row || i.row.available < i.qty);

  if (!lines.length)
    return (
      <div className="s-wrap s-page s-empty-state">
        <h1>Giỏ hàng trống</h1>
        <p>Hãy chọn vài sản phẩm, hoặc hỏi trợ lý để được gợi ý.</p>
        <Link className="s-btn" href="/">
          Tiếp tục mua sắm
        </Link>
      </div>
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
                  Xóa
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
            <span>{!items ? "—" : subtotal >= 2_000_000 ? "Miễn phí" : "Tính khi xác nhận"}</span>
          </div>
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
          <Link className="s-link-btn" href="/">
            ← Tiếp tục mua sắm
          </Link>
        </aside>
      </div>
    </div>
  );
}
