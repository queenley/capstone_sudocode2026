"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import ProductArt from "@/components/product/ProductArt";
import ProductCard from "@/components/product/ProductCard";
import { categoryName, DEPARTMENTS, discountPercent, fetchProducts, ShopProduct } from "@/lib/catalog";
import { shopContext } from "@/lib/shop-context";
import { HOTLINE, ZALO_URL } from "@/lib/contact";

const TILES = [
  "gia-dung/may-loc-khong-khi",
  "gia-dung/may-loc-nuoc",
  "gia-dung/noi-chien",
  "gia-dung/quat",
  "thoi-trang/giay",
  "thoi-trang/ao-khoac",
  "me-be",
  "gia-dung/combo",
];

export default function HomePage() {
  const [products, setProducts] = useState<ShopProduct[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchProducts()
      .then(setProducts)
      .catch((e) => setError(e.message));
  }, []);

  const deals = useMemo(
    () =>
      (products || [])
        .filter((p) => p.available > 0 && discountPercent(p.price, p.listPrice) > 0)
        .sort((a, b) => discountPercent(b.price, b.listPrice) - discountPercent(a.price, a.listPrice))
        .slice(0, 8),
    [products],
  );
  const featured = useMemo(
    () =>
      DEPARTMENTS.map((dept) => ({
        dept,
        items: (products || []).filter((p) => p.category.startsWith(dept.slug) && p.available > 0).slice(0, 4),
      })),
    [products],
  );

  return (
    <>
      <section className="s-hero">
        <div className="s-wrap s-hero-inner">
          <div className="s-hero-copy">
            <span className="s-eyebrow">Tư vấn bởi AI · Nhân viên hỗ trợ khi cần</span>
            <h1>Mua đúng thứ nhà bạn cần, hỏi gì cũng có người trả lời.</h1>
            <p>
              Máy lọc không khí, máy lọc nước, giày chạy bộ, đồ cho bé… Trợ lý Tiếp Nối báo giá, tồn kho và khuyến mãi
              theo đúng dữ liệu cửa hàng, nhớ nhu cầu của bạn cho lần sau.
            </p>
            <div className="s-hero-cta">
              <button className="s-btn s-btn-lg" onClick={() => shopContext.openChat()}>
                Chat với trợ lý
              </button>
              <Link className="s-btn s-btn-lg s-btn-outline" href="/danh-muc/gia-dung">
                Xem sản phẩm
              </Link>
            </div>
            <ul className="s-hero-points">
              <li>Giá và khuyến mãi lấy trực tiếp từ hệ thống</li>
              <li>Hotline {HOTLINE}, gọi được ngay trên web</li>
              <li>{ZALO_URL ? "Nhắn tin qua Zalo OA" : "Chat 24/7 trên website"}</li>
            </ul>
          </div>
          <div className="s-hero-art">
            <ProductArt category="gia-dung/may-loc-khong-khi" brand="AirPure" size="hero" />
            <div className="s-hero-bubble">
              <b>Khách:</b> Phòng 25m², có bé nhỏ thì chọn máy nào?
              <br />
              <b>Trợ lý:</b> Dạ AirPure Pro có khóa trẻ em, lọc HEPA H13, phù hợp phòng đến 45m² ạ…
            </div>
          </div>
        </div>
      </section>

      <section className="s-wrap s-section">
        <div className="s-section-head">
          <h2>Danh mục nổi bật</h2>
        </div>
        <div className="s-tiles">
          {TILES.map((slug) => (
            <Link key={slug} href={`/danh-muc/${slug}`} className="s-tile">
              <ProductArt category={slug} size="thumb" />
              <span>{categoryName(slug)}</span>
            </Link>
          ))}
        </div>
      </section>

      {error && (
        <div className="s-wrap">
          <div className="s-alert">Không tải được sản phẩm: {error}</div>
        </div>
      )}

      {(products === null || deals.length > 0) && (
        <section className="s-wrap s-section">
          <div className="s-section-head">
            <h2>Đang giảm giá</h2>
            <Link href="/khuyen-mai">Xem tất cả →</Link>
          </div>
          <div className="s-grid">
            {products === null
              ? Array.from({ length: 4 }, (_, i) => <div key={i} className="s-card s-skeleton" />)
              : deals.map((p) => <ProductCard key={p.ref} product={p} />)}
          </div>
        </section>
      )}

      <section className="s-wrap s-section">
        <div className="s-assist">
          <div>
            <h2>Ba cách để được tư vấn</h2>
            <p>Cùng một trợ lý, cùng một hồ sơ khách hàng: chat trên web, gọi hotline hay nhắn Zalo đều được tiếp nối.</p>
          </div>
          <div className="s-assist-cards">
            <button className="s-assist-card" onClick={() => shopContext.openChat()}>
              <span>💬</span>
              <b>Chat trên website</b>
              <small>Trả lời ngay, 24/7</small>
            </button>
            <a className="s-assist-card" href={`tel:${HOTLINE.replace(/\s/g, "")}`}>
              <span>☏</span>
              <b>Hotline {HOTLINE}</b>
              <small>Hoặc bấm ☏ trong khung chat để gọi qua web</small>
            </a>
            {ZALO_URL ? (
              <a className="s-assist-card" href={ZALO_URL} target="_blank" rel="noreferrer">
                <span>Z</span>
                <b>Zalo Official Account</b>
                <small>Nhắn tin, nhận thông báo đơn hàng</small>
              </a>
            ) : (
              <Link className="s-assist-card" href="/don-hang">
                <span>📦</span>
                <b>Tra cứu đơn hàng</b>
                <small>Xác minh số điện thoại để xem đơn</small>
              </Link>
            )}
          </div>
        </div>
      </section>

      {featured.map(({ dept, items }) =>
        items.length ? (
          <section key={dept.slug} className="s-wrap s-section">
            <div className="s-section-head">
              <h2>{categoryName(dept.slug)}</h2>
              <Link href={`/danh-muc/${dept.slug}`}>Xem tất cả →</Link>
            </div>
            <div className="s-grid">
              {items.map((p) => (
                <ProductCard key={p.ref} product={p} />
              ))}
            </div>
          </section>
        ) : null,
      )}
    </>
  );
}
