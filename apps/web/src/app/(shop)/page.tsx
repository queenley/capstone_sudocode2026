"use client";
import Link from "next/link";
import React, { useEffect, useMemo, useState } from "react";
import ProductArt from "@/components/product/ProductArt";
import ProductCard from "@/components/product/ProductCard";
import { categoryName, DEPARTMENTS, discountPercent, fetchProducts, ShopProduct } from "@/lib/catalog";
import { shopContext } from "@/lib/shop-context";
import { HOTLINE, ZALO_URL } from "@/lib/contact";

const icon = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

// From the store policy (chinh-sach), version 10/2026.
const PROMISES: { title: string; text: string; icon: React.ReactNode }[] = [
  {
    title: "Đổi trả trong 7 ngày",
    text: "Gia dụng và mẹ & bé lỗi kỹ thuật từ nhà sản xuất được đổi mới trong 30 ngày.",
    icon: <path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.2L3 16M3 21v-5h5" />,
  },
  {
    title: "Giao nhanh, miễn phí từ 2 triệu",
    text: "Nội thành Hà Nội, TP.HCM, Đà Nẵng 1–2 ngày làm việc; tỉnh khác 2–4 ngày.",
    icon: <path d="M3 7h11v9H3zM14 10h4l3 3v3h-7M7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM17 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z" />,
  },
  {
    title: "COD, kiểm hàng khi nhận",
    text: "Thanh toán khi nhận cho đơn dưới 10.000.000₫, phí thu hộ 0₫, hoặc chuyển khoản VietQR.",
    icon: <path d="M2 7h20v10H2zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 12h.01M18 12h.01" />,
  },
  {
    title: "Bảo hành đến 36 tháng",
    text: "Máy lọc nước RO 36 tháng, máy lọc không khí đến 24 tháng, theo từng hãng.",
    icon: <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4" />,
  },
];

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
            <h1>
              Mua đúng thứ nhà bạn cần, <em>hỏi gì cũng có người trả lời.</em>
            </h1>
            <p>
              Máy lọc không khí, máy lọc nước, giày chạy bộ, đồ cho bé… Trợ lý Quivo báo giá, tồn kho và khuyến mãi
              theo đúng dữ liệu cửa hàng, nhớ nhu cầu của bạn cho lần sau.
            </p>
            <div className="s-hero-stats">
              <div>
                <strong>24/7</strong>
                <span>Trợ lý AI tư vấn</span>
              </div>
              <div>
                <strong>3 kênh</strong>
                <span>Web · Zalo · Hotline</span>
              </div>
              <div>
                <strong>{products ? products.length : "…"}</strong>
                <span>Sản phẩm đang bán</span>
              </div>
            </div>
            <div className="s-hero-cta">
              <button className="s-btn s-btn-lg" onClick={() => shopContext.openChat()}>
                Chat với trợ lý AI
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
            <span className="s-hero-live">Trợ lý đang trực tuyến</span>
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
          <div>
            <span className="s-section-kicker">Mua theo nhu cầu</span>
            <h2>Danh mục nổi bật</h2>
          </div>
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

      <section className="s-wrap s-section">
        <div className="s-promises">
          {PROMISES.map((promise) => (
            <article className="s-promise" key={promise.title}>
              <span className="s-promise-icon">
                <svg {...icon}>{promise.icon}</svg>
              </span>
              <h3>{promise.title}</h3>
              <p>{promise.text}</p>
            </article>
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
