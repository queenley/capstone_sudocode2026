"use client";
import Link from "next/link";
import { useState } from "react";
import ProductArt from "./ProductArt";
import { categoryName, discountPercent, money, ShopProduct } from "@/lib/catalog";
import { cart } from "@/lib/cart";
import { keySpecs } from "./specs";

export default function ProductCard({ product }: { product: ShopProduct }) {
  const [added, setAdded] = useState(0);
  const off = discountPercent(product.price, product.listPrice);
  const single = product.variants.length === 1 ? product.variants[0] : null;
  const soldOut = product.available <= 0;
  const specs = keySpecs(product.description);
  return (
    <article className="s-card">
      <Link href={`/san-pham/${encodeURIComponent(product.ref)}`} className="s-card-link">
        <div className="s-card-media">
          <ProductArt category={product.category} brand={product.brand} image={product.image} alt={product.name} />
          {off > 0 && <span className="s-badge s-badge-sale">-{off}%</span>}
          {soldOut && <span className="s-badge s-badge-out">Hết hàng</span>}
        </div>
        <div className="s-card-body">
          <span className="s-card-cat">{categoryName(product.category)}</span>
          <h3 className="s-card-title">{product.name}</h3>
          {specs.length > 0 && (
            <ul className="s-card-specs" aria-label="Thông số chính">
              {specs.map((spec) => (
                <li key={spec}>{spec}</li>
              ))}
            </ul>
          )}
          <div className="s-price">
            <strong>
              {product.variants.length > 1 && <small>Từ </small>}
              {money(product.price)}
            </strong>
            {off > 0 && <s>{money(product.listPrice)}</s>}
          </div>
          {product.variants.length > 1 && <span className="s-card-note">{product.variants.length} lựa chọn</span>}
        </div>
      </Link>
      <div className="s-card-actions">
        {single && !soldOut ? (
          <button className="s-btn s-btn-ghost" onClick={() => { cart.add(single.sku_code); setAdded((value) => value + 1); }} aria-label={`Thêm ${product.name} vào giỏ`}>
            Thêm vào giỏ
          </button>
        ) : (
          <Link className="s-btn s-btn-ghost" href={`/san-pham/${encodeURIComponent(product.ref)}`}>
            {soldOut ? "Xem chi tiết" : "Chọn phân loại"}
          </Link>
        )}
        {single && !soldOut && <p className="s-card-confirmation" role="status">{added > 0 && <Link key={added} href="/gio-hang">Đã thêm {added} · Xem giỏ hàng →</Link>}</p>}
      </div>
    </article>
  );
}
