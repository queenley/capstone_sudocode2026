"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { categoryName, DEPARTMENTS } from "@/lib/catalog";
import { useCart } from "@/lib/cart";
import { HOTLINE, ZALO_URL } from "@/lib/contact";

export default function Header() {
  const lines = useCart();
  const count = lines.reduce((sum, line) => sum + line.qty, 0);
  const router = useRouter();
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    setMenu(false);
  }, [pathname]);

  function search(event: FormEvent) {
    event.preventDefault();
    const q = query.trim();
    if (q) router.push(`/tim-kiem?q=${encodeURIComponent(q)}`);
  }

  return (
    <header className="s-header">
      <div className="s-topline">
        <div className="s-wrap s-topline-inner">
          <span>Miễn phí giao hàng cho đơn từ 2.000.000₫ · Đổi trả theo chính sách cửa hàng</span>
          <span className="s-topline-links">
            <a href={`tel:${HOTLINE.replace(/\s/g, "")}`}>☏ Hotline {HOTLINE}</a>
            {ZALO_URL && (
              <a href={ZALO_URL} target="_blank" rel="noreferrer">
                Zalo
              </a>
            )}
            <Link href="/don-hang">Đơn hàng của tôi</Link>
            <Link href="/login">Nhân viên</Link>
          </span>
        </div>
      </div>
      <div className="s-wrap s-mainbar">
        <button className="s-menu-btn" aria-label="Danh mục" aria-expanded={menu} onClick={() => setMenu(!menu)}>
          ☰
        </button>
        <Link href="/" className="s-logo" aria-label="Tiếp Nối, trang chủ">
          <span className="s-logo-mark">t</span>
          <span>
            tiếp<b>nối</b>
          </span>
        </Link>
        <form className="s-search" role="search" onSubmit={search}>
          <input
            aria-label="Tìm sản phẩm"
            placeholder="Tìm máy lọc không khí, giày chạy bộ, đồ cho bé…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" aria-label="Tìm">
            Tìm
          </button>
        </form>
        <Link href="/gio-hang" className="s-cart-link" aria-label={`Giỏ hàng, ${count} sản phẩm`}>
          <span className="s-cart-icon">🛒</span>
          <span className="s-cart-text">Giỏ hàng</span>
          {count > 0 && <span className="s-cart-count">{count}</span>}
        </Link>
      </div>
      <nav className={`s-nav ${menu ? "open" : ""}`} aria-label="Danh mục sản phẩm">
        <div className="s-wrap s-nav-inner">
          {DEPARTMENTS.map((dept) => (
            <div className="s-nav-item" key={dept.slug}>
              <Link href={`/danh-muc/${dept.slug}`}>{categoryName(dept.slug)}</Link>
              {dept.children.length > 0 && (
                <div className="s-nav-drop">
                  {dept.children.map((child) => (
                    <Link key={child} href={`/danh-muc/${child}`}>
                      {categoryName(child)}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ))}
          <Link href="/khuyen-mai" className="s-nav-hot">
            Khuyến mãi
          </Link>
          <Link href="/chinh-sach">Chính sách</Link>
        </div>
      </nav>
    </header>
  );
}
