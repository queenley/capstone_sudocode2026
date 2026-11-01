"use client";
// A filterable, sortable grid of products: brand, price band, in-stock only.
import { useId, useMemo, useState } from "react";
import ProductCard from "./ProductCard";
import { discountPercent, ShopProduct } from "@/lib/catalog";

const PRICE_BANDS: { label: string; min: number; max: number }[] = [
  { label: "Dưới 1 triệu", min: 0, max: 1_000_000 },
  { label: "1 – 3 triệu", min: 1_000_000, max: 3_000_000 },
  { label: "3 – 7 triệu", min: 3_000_000, max: 7_000_000 },
  { label: "Trên 7 triệu", min: 7_000_000, max: Infinity },
];

type Sort = "popular" | "price-asc" | "price-desc" | "discount";

export default function ProductListing({ products, empty, error, onRetry }: { products: ShopProduct[] | null; empty?: string; error?: string; onRetry?: () => void }) {
  const filterId = useId();
  const [brands, setBrands] = useState<string[]>([]);
  const [band, setBand] = useState(-1);
  const [inStock, setInStock] = useState(false);
  const [sort, setSort] = useState<Sort>("popular");
  const [filtersOpen, setFiltersOpen] = useState(false);

  const allBrands = useMemo(() => [...new Set((products || []).map((p) => p.brand).filter(Boolean))].sort(), [products]);

  const shown = useMemo(() => {
    let list = (products || []).filter(
      (p) =>
        (!brands.length || brands.includes(p.brand)) &&
        (band < 0 || (p.price >= PRICE_BANDS[band].min && p.price < PRICE_BANDS[band].max)) &&
        (!inStock || p.available > 0),
    );
    if (sort === "price-asc") list = [...list].sort((a, b) => a.price - b.price);
    if (sort === "price-desc") list = [...list].sort((a, b) => b.price - a.price);
    if (sort === "discount")
      list = [...list].sort((a, b) => discountPercent(b.price, b.listPrice) - discountPercent(a.price, a.listPrice));
    if (sort === "popular") list = [...list].sort((a, b) => Number(b.available > 0) - Number(a.available > 0));
    return list;
  }, [products, brands, band, inStock, sort]);

  return (
    <div className="s-listing">
      <aside id={filterId} className={`s-filters ${filtersOpen ? "open" : ""}`}>
        <h3>Bộ lọc</h3>
        {allBrands.length > 1 && (
          <fieldset>
            <legend>Thương hiệu</legend>
            {allBrands.map((brand) => (
              <label key={brand} className="s-check">
                <input
                  type="checkbox"
                  checked={brands.includes(brand)}
                  onChange={(e) => setBrands(e.target.checked ? [...brands, brand] : brands.filter((b) => b !== brand))}
                />
                {brand}
              </label>
            ))}
          </fieldset>
        )}
        <fieldset>
          <legend>Khoảng giá</legend>
          {PRICE_BANDS.map((b, i) => (
            <label key={b.label} className="s-check">
              <input type="radio" name="band" checked={band === i} onChange={() => setBand(i)} />
              {b.label}
            </label>
          ))}
          {band >= 0 && (
            <button className="s-link-btn" onClick={() => setBand(-1)}>
              Bỏ lọc giá
            </button>
          )}
        </fieldset>
        <fieldset>
          <legend>Tình trạng</legend>
          <label className="s-check">
            <input type="checkbox" checked={inStock} onChange={(e) => setInStock(e.target.checked)} />
            Chỉ hiện hàng còn
          </label>
        </fieldset>
      </aside>
      <div>
        <div className="s-listing-bar">
          <button className="s-btn s-btn-ghost s-filter-toggle" aria-expanded={filtersOpen} aria-controls={filterId} onClick={() => setFiltersOpen(!filtersOpen)}>
            Bộ lọc
          </button>
          <span role="status">{error ? "Chưa tải được sản phẩm" : products === null ? "Đang tải…" : `${shown.length} sản phẩm`}</span>
          <label className="s-sort">
            Sắp xếp
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
              <option value="popular">Nổi bật</option>
              <option value="price-asc">Giá tăng dần</option>
              <option value="price-desc">Giá giảm dần</option>
              <option value="discount">Giảm giá nhiều</option>
            </select>
          </label>
        </div>
        {error ? <div className="s-load-error" role="alert">
          <h2>Chưa tải được sản phẩm</h2>
          <p>{error}</p>
          {onRetry && <button className="s-btn s-btn-outline" onClick={onRetry}>Thử lại</button>}
        </div> : <div className="s-grid" aria-busy={products === null}>
          {products === null
            ? Array.from({ length: 8 }, (_, i) => <div key={i} className="s-card s-skeleton" aria-hidden="true" />)
            : shown.map((p) => <ProductCard key={p.ref} product={p} />)}
        </div>}
        {!error && products !== null && shown.length === 0 && (
          <div className="s-empty"><p>{empty || "Không có sản phẩm phù hợp với bộ lọc."}</p>
            {(brands.length > 0 || band >= 0 || inStock) && <button className="s-btn s-btn-outline" onClick={() => { setBrands([]); setBand(-1); setInStock(false); }}>Xóa bộ lọc</button>}
          </div>
        )}
      </div>
    </div>
  );
}
