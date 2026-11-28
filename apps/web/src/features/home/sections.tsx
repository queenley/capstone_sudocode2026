"use client";
import Link from "next/link";
import React, { useEffect, useMemo, useRef, useState } from "react";
import ProductCard from "@/components/product/ProductCard";
import Icon from "@/components/ui/Icon";
import { categoryName, discountPercent, fetchProducts, money, ShopProduct } from "@/lib/catalog";
import { shopContext } from "@/lib/shop-context";
import { RANGE, ROWS, TERMS } from "./content";

// The home page's sections, in page order (HomeStore, app/(shop)/page.tsx): a store front, as shoppers expect one.
// A short hero whose window turns through four featured products; then the products lead the page.

const HERO_MS = 4000;

/**
 * The hero: a full-width band on the brand green whose four slides, one featured product each, move on by
 * themselves every four seconds, in a loop; the four dots under them say which one shows and pick one. The band
 * holds still while the pointer or the keyboard is on it, when paused, and under reduced motion; a swipe turns
 * it on a phone. (The client's choice over the taste kit's "no carousel" rule, 2026-11-28.)
 */
export function HomeHero({ products }: { products: ShopProduct[] | null }) {
  const slides = (products || []).slice(0, 4);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [held, setHeld] = useState(false);
  const [still, setStill] = useState(false);
  const touch = useRef<number | null>(null);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setStill(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  const running = !paused && !held && !still && slides.length > 1;
  useEffect(() => {
    if (!running) return;
    const timer = window.setTimeout(() => setIndex((i) => (i + 1) % slides.length), HERO_MS);
    return () => window.clearTimeout(timer);
  }, [running, index, slides.length]);

  const go = (next: number) => setIndex((next + slides.length) % slides.length);

  return (
    <section className="s-home-hero s-home-block" data-enter aria-labelledby="home-h">
      <h1 id="home-h" className="s-home-hero__h1 s-wrap">Gia dụng, thời trang và đồ mẹ bé chính hãng</h1>
      <div
        className="s-home-show"
        aria-roledescription="băng chuyền"
        aria-label="Sản phẩm nổi bật"
        onMouseEnter={() => setHeld(true)}
        onMouseLeave={() => setHeld(false)}
        onFocus={() => setHeld(true)}
        onBlur={() => setHeld(false)}
        onTouchStart={(event) => { touch.current = event.touches[0].clientX; }}
        onTouchEnd={(event) => {
          const from = touch.current;
          touch.current = null;
          if (from === null) return;
          const moved = event.changedTouches[0].clientX - from;
          if (Math.abs(moved) > 40) go(index + (moved < 0 ? 1 : -1));
        }}
      >
        {slides.length > 0 ? (
          <>
            <div className="s-home-show__viewport">
              <div className="s-home-show__track" style={{ transform: `translateX(-${index * 100}%)` }}>
                {slides.map((product, i) => {
                  const off = discountPercent(product.price, product.listPrice);
                  return (
                    <div
                      key={product.ref}
                      className={`s-home-show__slide${i === index ? " is-on" : ""}`}
                      aria-hidden={i !== index}
                      aria-roledescription="trang"
                      aria-label={`${i + 1} / ${slides.length}: ${product.name}`}
                    >
                      <div className="s-wrap s-home-show__row">
                        <div className="s-home-show__info">
                          <span className="s-home-show__cat">{categoryName(product.category)}</span>
                          <strong>{product.name}</strong>
                          <span className="s-home-show__price">
                            {money(product.price)}
                            {off > 0 && <s>{money(product.listPrice)}</s>}
                            {off > 0 && <span className="s-home-show__off">-{off}%</span>}
                          </span>
                          <span className="s-home-show__actions">
                            <Link className="s-btn s-btn-lg s-home-show__buy" href={`/san-pham/${encodeURIComponent(product.ref)}`}
                              tabIndex={i === index ? 0 : -1}>
                              Xem sản phẩm
                            </Link>
                            <button type="button" className="s-btn s-btn-lg s-home-show__ask" tabIndex={i === index ? 0 : -1}
                              onClick={() => shopContext.openChat()}>
                              <Icon name="assistant" size={20} /> Hỏi tư vấn
                            </button>
                          </span>
                        </div>
                        <Link className="s-home-show__pic" href={`/san-pham/${encodeURIComponent(product.ref)}`}
                          tabIndex={-1} aria-hidden="true">
                          {product.image && <img src={product.image} alt="" loading={i === 0 ? "eager" : "lazy"} decoding="async" />}
                        </Link>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="s-home-show__dots">
              {slides.map((product, i) => (
                <button
                  key={product.ref}
                  type="button"
                  className={`s-home-show__dot${i === index ? " is-on" : ""}`}
                  aria-label={`Xem ${product.name}`}
                  aria-current={i === index ? "true" : undefined}
                  onClick={() => go(i)}
                >
                  <span style={i === index && running ? { animationDuration: `${HERO_MS}ms` } : undefined} key={`${i}-${index}`} />
                </button>
              ))}
              {!still && slides.length > 1 && (
                <button type="button" className="s-home-show__pause" onClick={() => setPaused((value) => !value)}
                  aria-pressed={paused} aria-label={paused ? "Chạy tiếp" : "Tạm dừng"} title={paused ? "Chạy tiếp" : "Tạm dừng"}>
                  {paused ? "▶" : "❚❚"}
                </button>
              )}
            </div>
          </>
        ) : (
          <div className="s-wrap"><div className="s-home-show__placeholder s-home-skeleton" aria-hidden="true" /></div>
        )}
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

/** The whole page: the catalogue is read once, the hero takes the first four featured products. */
export function HomeStore() {
  const { products, failed } = useProducts();
  const showcase = useMemo(() => (products ? featured(products, 16) : null), [products]);
  return (
    <>
      <HomeHero products={showcase} />
      <CategoryStrip />
      <ProductSections products={products} failed={failed} showcase={showcase ? showcase.slice(4) : []} />
      <TermsStrip />
    </>
  );
}

/** The featured window, then one row of four per department, each with a link to all of it. */
function ProductSections({ products, failed, showcase }: {
  products: ShopProduct[] | null; failed: boolean; showcase: ShopProduct[];
}) {
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
      {(!products || showcase.length > 0) && <section className="s-wrap s-home-section s-home-block" aria-labelledby="noi-bat-h">
        <div className="s-home-head">
          <h2 id="noi-bat-h">Sản phẩm nổi bật</h2>
          <Link className="s-home-more" href="/khuyen-mai">Xem tất cả ưu đãi →</Link>
        </div>
        {products ? <FeaturedCarousel products={showcase} /> : <Skeleton />}
      </section>}
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
