"use client";
import Link from "next/link";
import ProductArt from "@/components/product/ProductArt";
import { money, variantLabel } from "@/lib/catalog";
import { cart, useCart } from "@/lib/cart";
import { useCartItems } from "@/lib/cart-items";

export default function CartPage() {
  const lines = useCart();
  const { items, error } = useCartItems(lines);
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
      {error && <div className="s-alert">{error}</div>}
      <div className="s-cart">
        <div className="s-cart-lines">
          {(items || lines.map((l) => ({ ...l, row: null }))).map((item) => (
            <div className="s-cart-line" key={item.sku}>
              <ProductArt category={item.row?.category || ""} size="thumb" />
              <div className="s-cart-line-info">
                {item.row ? (
                  <Link href={`/san-pham/${encodeURIComponent(item.row.product_ref || item.sku)}`}>
                    <b>{item.row.name}</b>
                  </Link>
                ) : (
                  <b>{items ? `Sản phẩm ${item.sku} không còn bán` : "Đang tải…"}</b>
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
                <button onClick={() => cart.set(item.sku, item.qty - 1)} aria-label="Giảm">
                  −
                </button>
                <span>{item.qty}</span>
                <button onClick={() => cart.set(item.sku, item.qty + 1)} aria-label="Tăng">
                  +
                </button>
              </div>
              <div className="s-cart-line-price">
                {item.row && <b>{money(Number(item.row.sale_price) * item.qty)}</b>}
                <button className="s-link-btn" onClick={() => cart.remove(item.sku)}>
                  Xóa
                </button>
              </div>
            </div>
          ))}
        </div>
        <aside className="s-summary">
          <h3>Tóm tắt đơn hàng</h3>
          <div className="s-summary-row">
            <span>Tạm tính</span>
            <span>{money(listTotal)}</span>
          </div>
          {listTotal > subtotal && (
            <div className="s-summary-row s-good">
              <span>Giảm giá</span>
              <span>−{money(listTotal - subtotal)}</span>
            </div>
          )}
          <div className="s-summary-row">
            <span>Phí giao hàng</span>
            <span>{subtotal >= 2_000_000 ? "Miễn phí" : "Tính khi xác nhận"}</span>
          </div>
          <div className="s-summary-total">
            <span>Tổng cộng</span>
            <b>{money(subtotal)}</b>
          </div>
          <Link
            className={`s-btn s-btn-lg s-btn-block ${problems.length || !items ? "disabled" : ""}`}
            href={problems.length || !items ? "#" : "/thanh-toan"}
            aria-disabled={problems.length > 0 || !items}
          >
            Tiến hành đặt hàng
          </Link>
          {problems.length > 0 && <p className="s-warn">Điều chỉnh số lượng các sản phẩm không đủ hàng để tiếp tục.</p>}
          <Link className="s-link-btn" href="/">
            ← Tiếp tục mua sắm
          </Link>
        </aside>
      </div>
    </div>
  );
}
