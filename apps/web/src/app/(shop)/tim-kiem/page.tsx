"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import ProductListing from "@/components/product/ProductListing";
import Icon from "@/components/ui/Icon";
import { fetchProducts, ShopProduct } from "@/lib/catalog";
import { shopContext } from "@/lib/shop-context";

/** Common searches offered when the box is empty: the shop's departments, as a customer types them. */
const SUGGEST = ["máy lọc không khí", "máy lọc nước", "nồi chiên", "quạt", "giày", "áo khoác", "xe đẩy"];

function Results() {
  const q = useSearchParams().get("q") || "";
  const router = useRouter();
  const [products, setProducts] = useState<ShopProduct[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError("");
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
        if (active) setProducts([...exact, ...extra]);
      })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [q, attempt]);

  return (
    <div className="s-wrap s-page s-search-page">
      {/* The page's own search box (shop.css, "the search page"): the words searched stay in it, and with
          none the page lists everything under a few common searches. */}
      <header className="s-search-head">
        <h1 className="s-search-title">
          {q ? <>Kết quả cho <span className="s-search-q">“{q}”</span></> : "Tìm sản phẩm"}
        </h1>
        <form
          role="search"
          className="s-search"
          onSubmit={(event) => {
            event.preventDefault();
            const value = String(new FormData(event.currentTarget).get("q") || "").trim();
            router.push(value ? `/tim-kiem?q=${encodeURIComponent(value)}` : "/tim-kiem");
          }}
        >
          <Icon name="search" />
          <input key={q} type="search" name="q" defaultValue={q} placeholder="Máy lọc, nồi chiên, giày chạy bộ…" aria-label="Tìm sản phẩm" />
          <button type="submit">Tìm</button>
        </form>
        {!q && (
          <ul className="s-search-chips" aria-label="Tìm nhanh">
            {SUGGEST.map((word) => (
              <li key={word}><Link href={`/tim-kiem?q=${encodeURIComponent(word)}`}>{word}</Link></li>
            ))}
          </ul>
        )}
      </header>
      <ProductListing
        products={products}
        error={error}
        onRetry={() => setAttempt((value) => value + 1)}
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
