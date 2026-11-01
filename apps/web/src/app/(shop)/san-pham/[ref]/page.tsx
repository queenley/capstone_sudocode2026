"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ProductArt, { PhotoCredit } from "@/components/product/ProductArt";
import ProductCard from "@/components/product/ProductCard";
import { api } from "@/services/api";
import {
  categoryName,
  CatalogRow,
  colorName,
  discountPercent,
  fetchProducts,
  money,
  ShopProduct,
  specifications,
  variantLabel,
} from "@/lib/catalog";
import { cart } from "@/lib/cart";
import { shopContext } from "@/lib/shop-context";

type Quote = CatalogRow & { total: string; discount: string; promotions: { name: string; description: string; type: string }[] };

export default function ProductPage() {
  const ref = decodeURIComponent(useParams<{ ref: string }>().ref);
  const router = useRouter();
  const [all, setAll] = useState<ShopProduct[] | null>(null);
  const [error, setError] = useState("");
  const [skuCode, setSkuCode] = useState("");
  const [qty, setQty] = useState(1);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [added, setAdded] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError("");
    fetchProducts()
      .then((products) => { if (active) setAll(products); })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [attempt]);

  const product = useMemo(() => all?.find((p) => p.ref === ref) || null, [all, ref]);
  const variant = product?.variants.find((v) => v.sku_code === skuCode) || null;

  // Pick the first variant in stock, and tell the chat what is being viewed.
  useEffect(() => {
    if (!product) return;
    const first = product.variants.find((v) => v.available > 0) || product.variants[0];
    setSkuCode(first.sku_code);
    return () => shopContext.leave();
  }, [product]);

  useEffect(() => {
    if (!product || !skuCode) return;
    const controller = new AbortController();
    setQty(1);
    setAdded(false);
    shopContext.viewing(skuCode, product.name);
    setQuote(null);
    api<Quote>(`/api/catalog/${encodeURIComponent(skuCode)}/quote`, "", undefined, undefined, { signal: controller.signal })
      .then((quote) => { if (!controller.signal.aborted) setQuote(quote); })
      .catch(() => { if (!controller.signal.aborted) setQuote(null); });
    return () => controller.abort();
  }, [product, skuCode]);

  const related = useMemo(
    () => (all || []).filter((p) => product && p.category === product.category && p.ref !== product.ref).slice(0, 4),
    [all, product],
  );

  if (error) return <div className="s-wrap s-page"><div className="s-load-error" role="alert"><h1 className="s-page-title">Chưa tải được sản phẩm</h1><p>{error}</p><button className="s-btn s-btn-outline" onClick={() => setAttempt((value) => value + 1)}>Thử lại</button></div></div>;
  if (all === null) return <div className="s-wrap s-page"><p role="status">Đang tải sản phẩm…</p><div className="s-detail s-skeleton-block" aria-hidden="true" /></div>;
  if (!product)
    return (
      <div className="s-wrap s-page s-empty">
        Không tìm thấy sản phẩm này. <Link href="/">Về trang chủ</Link>
      </div>
    );

  const price = Number(variant?.sale_price ?? product.price);
  const list = Number(variant?.list_price ?? product.listPrice);
  const off = discountPercent(price, list);
  const available = variant ? variant.available : product.available;
  const specs = specifications(product.description);
  const sizes = [...new Set(product.variants.map((v) => (v.variant as Record<string, unknown>)?.size).filter((s) => s !== undefined))];
  const colors = [...new Set(product.variants.map((v) => (v.variant as Record<string, unknown>)?.color).filter(Boolean))];
  const current = (variant?.variant || {}) as Record<string, unknown>;

  function pick(size: unknown, color: unknown) {
    const match =
      product!.variants.find(
        (v) => (v.variant as Record<string, unknown>)?.size === size && (v.variant as Record<string, unknown>)?.color === color,
      ) ||
      product!.variants.find((v) => (v.variant as Record<string, unknown>)?.[size !== undefined ? "size" : "color"] === (size ?? color));
    if (match) setSkuCode(match.sku_code);
  }

  function addToCart(go: boolean) {
    if (!variant) return;
    cart.add(variant.sku_code, qty);
    if (go) router.push("/gio-hang");
    else {
      setAdded(true);
      setTimeout(() => setAdded(false), 2500);
    }
  }

  return (
    <div className="s-wrap s-page">
      <nav className="s-crumbs" aria-label="Đường dẫn">
        <Link href="/">Trang chủ</Link>
        <span>/</span>
        <Link href={`/danh-muc/${product.category}`}>{categoryName(product.category)}</Link>
        <span>/</span>
        <span>{product.name}</span>
      </nav>
      <div className="s-detail">
        <div className="s-detail-media">
          <ProductArt category={product.category} brand={product.brand} size="hero" image={product.image} alt={product.name} />
          {off > 0 && <span className="s-badge s-badge-sale s-badge-lg">-{off}%</span>}
          {product.image && product.imageCredit && <PhotoCredit credit={product.imageCredit} />}
        </div>
        <div className="s-detail-info">
          <span className="s-card-cat">{product.brand}</span>
          <h1>{product.name}</h1>
          <div className="s-detail-sku">Mã: {skuCode}</div>
          <div className="s-price s-price-lg">
            <strong>{money(price)}</strong>
            {off > 0 && (
              <>
                <s>{money(list)}</s>
                <span className="s-save">Tiết kiệm {money(list - price)}</span>
              </>
            )}
          </div>

          {quote && quote.promotions.length > 0 && (
            <div className="s-promos">
              <b>Ưu đãi đang áp dụng</b>
              <ul>
                {quote.promotions.map((p) => (
                  <li key={p.name}>{p.description || p.name}</li>
                ))}
              </ul>
            </div>
          )}

          {sizes.length > 0 && (
            <div className="s-options">
              <span>Kích cỡ</span>
              <div>
                {sizes.map((size) => {
                  const any = product.variants.some(
                    (v) => (v.variant as Record<string, unknown>)?.size === size && v.available > 0,
                  );
                  return (
                    <button
                      key={String(size)}
                      className={`s-option ${current.size === size ? "active" : ""} ${any ? "" : "out"}`}
                      aria-pressed={current.size === size}
                      onClick={() => pick(size, current.color)}
                    >
                      {String(size)}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {colors.length > 0 && (
            <div className="s-options">
              <span>Màu sắc</span>
              <div>
                {colors.map((color) => (
                  <button
                    key={String(color)}
                    className={`s-option ${current.color === color ? "active" : ""}`}
                    aria-pressed={current.color === color}
                    onClick={() => pick(sizes.length ? current.size : undefined, color)}
                  >
                    {colorName(color)}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className={`s-stock ${available > 0 ? "in" : "out"}`}>
            {available > 0 ? (available <= 5 ? `Chỉ còn ${available} sản phẩm` : "Còn hàng") : "Tạm hết hàng"}
            {variant && variantLabel(variant) && <span> · {variantLabel(variant)}</span>}
          </div>

          <div className="s-buy">
            <div className="s-qty" aria-label="Số lượng">
              <button disabled={qty <= 1} onClick={() => setQty(Math.max(1, qty - 1))} aria-label="Giảm">
                −
              </button>
              <span aria-live="polite">{qty}</span>
              <button disabled={qty >= Math.min(99, available)} onClick={() => setQty(Math.min(99, Math.max(1, available), qty + 1))} aria-label="Tăng">
                +
              </button>
            </div>
            <button className="s-btn s-btn-lg s-btn-outline" disabled={available <= 0} onClick={() => addToCart(false)}>
              {added ? "Đã thêm ✓" : "Thêm vào giỏ"}
            </button>
            <button className="s-btn s-btn-lg" disabled={available <= 0} onClick={() => addToCart(true)}>
              Mua ngay
            </button>
          </div>
          <button className="s-ask" onClick={() => shopContext.openChat(`Tư vấn giúp tôi về ${product.name}`)}>
            💬 Hỏi trợ lý về sản phẩm này
            <small>Giá theo khu vực, đổi máy cũ, so sánh với mẫu khác…</small>
          </button>
          <ul className="s-perks">
            <li>Giao nhanh, miễn phí cho đơn từ 2.000.000₫</li>
            <li>Thanh toán khi nhận hàng (COD)</li>
            <li>Đổi trả theo chính sách cửa hàng</li>
          </ul>
        </div>
      </div>

      {specs.length > 0 && (
        <section className="s-section">
          <h2>Thông số sản phẩm</h2>
          <table className="s-specs">
            <tbody>
              {specs.map(([label, value]) => (
                <tr key={label}>
                  <th>{label}</th>
                  <td>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {related.length > 0 && (
        <section className="s-section">
          <div className="s-section-head">
            <h2>Sản phẩm tương tự</h2>
          </div>
          <div className="s-grid">
            {related.map((p) => (
              <ProductCard key={p.ref} product={p} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
