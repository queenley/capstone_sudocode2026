"use client";
import Link from "next/link";
import React, { useEffect, useMemo, useRef, useState } from "react";
import ProductCard from "@/components/product/ProductCard";
import { categoryName, discountPercent, fetchProducts, ShopProduct } from "@/lib/catalog";
import { IMG, RANGE, ROWS, TERMS } from "./content";

// The home page's sections, in page order (app/(shop)/page.tsx): a store front, as shoppers expect one.
// The banner is one line high; the products lead the page.

/** One strip across the top: the photograph as a band, what the shop sells, its delivery offer. */
export function HomeBanner() {
  return (
    <section className="s-home-banner s-home-block" data-enter aria-labelledby="home-h">
      <img
        className="s-home-banner__bg"
        src={`${IMG}/photo-f107853503-1280.webp`}
        srcSet={`${IMG}/photo-f107853503-960.webp 960w, ${IMG}/photo-f107853503-1280.webp 1280w, ${IMG}/photo-f107853503.webp 1920w`}
        sizes="100vw" width={1920} height={1444} alt="" aria-hidden="true"
        fetchPriority="high" decoding="async"
      />
      <div className="s-wrap s-home-banner__row">
        <div>
          <h1 id="home-h">Gia dụng, thời trang và đồ mẹ bé</h1>
          <p>Giao miễn phí cho đơn từ 2.000.000₫ · Đổi trả trong 7 ngày</p>
        </div>
        <Link className="s-btn" href="/khuyen-mai">Xem hàng giảm giá</Link>
      </div>
    </section>
  );
}

/** The departments as small pictures in one row: a shortcut to each listing. */
export function CategoryStrip() {
  return (
    <nav className="s-wrap s-home-cats" aria-label="Danh mục">
      {RANGE.map((item) => (
        <Link key={item.slug} className="s-home-cat" href={`/danh-muc/${item.slug}`}>
          <span className="s-home-cat__pic"><img src={item.picture} alt="" width={96} height={96} loading="lazy" decoding="async" /></span>
          <span>{categoryName(item.slug)}</span>
        </Link>
      ))}
    </nav>
  );
}

/** The shop's catalogue, read once for the whole page. */
function useProducts() {
  const [products, setProducts] = useState<ShopProduct[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    fetchProducts()
      .then((all) => { if (active) setProducts(all); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);
  return { products, failed };
}

/** With a photograph, then in stock, then the deepest discount: what a shop puts in its window. */
function byAppeal(a: ShopProduct, b: ShopProduct) {
  return Number(Boolean(b.image)) - Number(Boolean(a.image))
    || Number(b.available > 0) - Number(a.available > 0)
    || discountPercent(b.price, b.listPrice) - discountPercent(a.price, a.listPrice);
}

/** One product from each category in turn, so the window shows the whole shop, not one department. */
function featured(products: ShopProduct[], count: number): ShopProduct[] {
  const groups = new Map<string, ShopProduct[]>();
  for (const product of [...products].sort(byAppeal)) {
    const key = product.category;
    groups.set(key, [...(groups.get(key) || []), product]);
  }
  const lists = [...groups.values()];
  const picked: ShopProduct[] = [];
  for (let round = 0; picked.length < count && lists.some((list) => list.length > round); round++) {
    for (const list of lists) if (list[round] && picked.length < count) picked.push(list[round]);
  }
  return picked;
}

function inCategory(product: ShopProduct, row: (typeof ROWS)[number]) {
  const inside = row.slugs.some((slug) => product.category === slug || product.category.startsWith(slug + "/"));
  return inside && !row.except?.some((slug) => product.category === slug || product.category.startsWith(slug + "/"));
}

const SLIDE_MS = 4000;

/** "Sản phẩm nổi bật": four at a time, moving on by one every few seconds; arrows, a pause, and a swipe on a phone. */
function FeaturedCarousel({ products }: { products: ShopProduct[] }) {
  const track = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(false);
  const [held, setHeld] = useState(false);
  const [still, setStill] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setStill(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  function step(direction: 1 | -1) {
    const el = track.current;
    const card = el?.querySelector<HTMLElement>(".s-home-slide");
    if (!el || !card) return;
    const width = card.offsetWidth + parseFloat(getComputedStyle(el).columnGap || "16");
    const end = el.scrollWidth - el.clientWidth - 4;
    const left = direction > 0 && el.scrollLeft >= end ? 0
      : direction < 0 && el.scrollLeft <= 4 ? el.scrollWidth
        : el.scrollLeft + direction * width;
    el.scrollTo({ left, behavior: still ? "auto" : "smooth" });
  }

  useEffect(() => {
    if (paused || held || still || products.length <= 4) return;
    const timer = window.setInterval(() => step(1), SLIDE_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused, held, still, products.length]);

  return (
    <div className="s-home-carousel" onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)} onBlur={() => setHeld(false)}>
      <div className="s-home-carousel__controls">
        <button type="button" className="s-home-round" onClick={() => step(-1)} aria-label="Sản phẩm trước">‹</button>
        <button type="button" className="s-home-round" onClick={() => step(1)} aria-label="Sản phẩm tiếp theo">›</button>
        {!still && products.length > 4 && (
          <button type="button" className="s-home-pause" onClick={() => setPaused((value) => !value)} aria-pressed={paused}>
            {paused ? "Chạy tiếp" : "Tạm dừng"}
          </button>
        )}
      </div>
      <div className="s-home-track" ref={track} aria-roledescription="băng chuyền" aria-label="Sản phẩm nổi bật">
        {products.map((product, index) => (
          <div className="s-home-slide" key={product.ref} aria-roledescription="trang" aria-label={`${index + 1} / ${products.length}`}>
            <ProductCard product={product} />
          </div>
        ))}
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="s-grid s-home-grid" aria-hidden="true">
      {[0, 1, 2, 3].map((i) => <div className="s-home-skeleton" key={i} />)}
    </div>
  );
}

/** The featured window, then one row of four per department, each with a link to all of it. */
export function ProductSections() {
  const { products, failed } = useProducts();
  const showcase = useMemo(() => (products ? featured(products, 12) : []), [products]);
  const rows = useMemo(
    () => ROWS.map((row) => ({ ...row, items: (products || []).filter((p) => inCategory(p, row)).sort(byAppeal).slice(0, 4) }))
      .filter((row) => !products || row.items.length > 0),
    [products],
  );
  if (failed) {
    return (
      <section className="s-wrap s-home-section s-home-block">
        <p className="s-muted">Chưa tải được sản phẩm. <Link href="/danh-muc/gia-dung">Xem danh mục Gia dụng</Link></p>
      </section>
    );
  }
  return (
    <>
      <section className="s-wrap s-home-section s-home-block" aria-labelledby="noi-bat-h">
        <div className="s-home-head">
          <h2 id="noi-bat-h">Sản phẩm nổi bật</h2>
          <Link className="s-home-more" href="/khuyen-mai">Xem tất cả ưu đãi →</Link>
        </div>
        {products ? <FeaturedCarousel products={showcase} /> : <Skeleton />}
      </section>
      {rows.map((row) => (
        <section className="s-wrap s-home-section s-home-block" key={row.id} aria-labelledby={`${row.id}-h`}>
          <div className="s-home-head">
            <h2 id={`${row.id}-h`}>{row.title}</h2>
            <Link className="s-home-more" href={`/danh-muc/${row.href}`}>Xem thêm →</Link>
          </div>
          {products ? (
            <div className="s-grid s-home-grid">
              {row.items.map((product) => <ProductCard key={product.ref} product={product} />)}
            </div>
          ) : <Skeleton />}
        </section>
      ))}
    </>
  );
}

/** Delivery, payment, returns and warranty in one band, each with its figure. */
export function TermsStrip() {
  return (
    <section className="s-home-terms s-home-block" aria-labelledby="mua-hang-h">
      <div className="s-wrap">
        <div className="s-home-head">
          <h2 id="mua-hang-h">Mua sắm tại Quivo</h2>
          <Link className="s-home-more" href="/chinh-sach">Đọc chính sách →</Link>
        </div>
        <ul className="s-home-terms__list">
          {TERMS.map((term) => (
            <li key={term.name}>
              <strong>{term.name}</strong>
              <span className="s-home-terms__value">{term.value}</span>
              <p>{term.line}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
