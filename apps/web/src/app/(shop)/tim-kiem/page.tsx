"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import ProductListing from "@/components/product/ProductListing";
import { fetchProducts, ShopProduct } from "@/lib/catalog";
import { shopContext } from "@/lib/shop-context";

function Results() {
  const q = useSearchParams().get("q") || "";
  const [products, setProducts] = useState<ShopProduct[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setProducts(null);
    // The catalog matches whole phrases; also try each word so "giày chạy" finds "Giày chạy bộ".
    const words = q.split(/\s+/).filter((w) => w.length > 1);
    Promise.all([fetchProducts({ q }), ...words.slice(0, 4).map((w) => fetchProducts({ q: w }))])
      .then(([exact, ...partial]) => {
        const seen = new Set(exact.map((p) => p.ref));
        const extra = partial.flat().filter((p) => {
          const hits = words.filter((w) => (p.name + " " + p.brand).toLowerCase().includes(w.toLowerCase())).length;
          return !seen.has(p.ref) && hits >= Math.min(2, words.length) && (seen.add(p.ref), true);
        });
        setProducts([...exact, ...extra]);
      })
      .catch((e) => setError(e.message));
  }, [q]);

  return (
    <div className="s-wrap s-page">
      <h1 className="s-page-title">Kết quả cho “{q}”</h1>
      {error && <div className="s-alert">Không tìm được: {error}</div>}
      <ProductListing
        products={products}
        empty="Không tìm thấy sản phẩm. Hãy thử từ khóa khác, hoặc hỏi trợ lý để được gợi ý."
      />
      {products !== null && products.length === 0 && (
        <div className="s-center">
          <button className="s-btn" onClick={() => shopContext.openChat(`Tôi đang tìm: ${q}`)}>
            Hỏi trợ lý về “{q}”
          </button>
        </div>
      )}
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="s-wrap s-page">Đang tìm…</div>}>
      <Results />
    </Suspense>
  );
}
