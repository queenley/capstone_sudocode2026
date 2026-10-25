"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { Logo } from "@/components/brand/Logo";
import ThemeToggle from "@/components/theme/ThemeToggle";
import { categoryName, DEPARTMENTS } from "@/lib/catalog";
import { firstName, useAccount } from "@/lib/account";
import { useCart } from "@/lib/cart";
import { HOTLINE, ZALO_URL } from "@/lib/contact";

const icon = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

export default function Header() {
  const lines = useCart();
  const { status, account } = useAccount();
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

  const active = (href: string) => (pathname === href || pathname.startsWith(href + "/") ? "active" : undefined);

  return (
    <header className="s-header">
      <div className="s-topline">
        <div className="s-wrap s-topline-inner">
          <span className="s-topline-promo">
            <span className="s-topline-tag">Ưu đãi</span>
            <span>Miễn phí giao hàng cho đơn từ 2.000.000₫ · Đổi trả theo chính sách cửa hàng</span>
          </span>
          <span className="s-topline-links">
            <a href={`tel:${HOTLINE.replace(/\s/g, "")}`}>☏ Hotline {HOTLINE}</a>
            {ZALO_URL && (
              <a href={ZALO_URL} target="_blank" rel="noreferrer">
                Zalo
              </a>
            )}
            <Link href="/login">Nhân viên</Link>
          </span>
        </div>
      </div>
      <div className="s-wrap s-mainbar">
        <button className="s-menu-btn" aria-label="Danh mục" aria-expanded={menu} onClick={() => setMenu(!menu)}>
          ☰
        </button>
        <Link href="/" className="s-logo" aria-label="Quivo, trang chủ">
          {/* The wordmark's "Q" is the mark: one image, no separate icon beside it. */}
          <span className="s-logo-text">
            <Logo height={30} title="" className="text-brand" />
            <small className="hidden xs:block">Trợ lý mua sắm AI</small>
          </span>
        </Link>
        <form className="s-search" role="search" onSubmit={search}>
          <svg {...icon}>
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            aria-label="Tìm sản phẩm"
            placeholder="Tìm máy lọc không khí, giày chạy bộ, đồ cho bé…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit">Tìm</button>
        </form>
        <div className="s-header-actions">
          <Link
            href={status === "signed-in" ? "/tai-khoan" : "/dang-nhap"}
            className="s-header-link s-account-link"
            aria-label={status === "signed-in" ? "Tài khoản của tôi" : "Đăng nhập hoặc đăng ký"}
          >
            <svg {...icon}>
              <circle cx="12" cy="8" r="4" />
              <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" />
            </svg>
            <span>
              {status === "signed-in" ? (
                <>
                  <small>Xin chào</small>
                  {firstName(account)}
                </>
              ) : (
                <>
                  <small>Đăng nhập</small>
                  Tài khoản
                </>
              )}
            </span>
          </Link>
          <Link href="/don-hang" className="s-header-link" aria-label="Đơn hàng của tôi">
            <svg {...icon}>
              <path d="M6 2h12l2 4v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6z" />
              <path d="M4 6h16M9 11h6M9 15h4" />
            </svg>
            <span>Đơn hàng</span>
          </Link>
          <ThemeToggle />
          <Link href="/gio-hang" className="s-cart-link" aria-label={`Giỏ hàng, ${count} sản phẩm`}>
            <svg {...icon}>
              <circle cx="9" cy="20" r="1.5" />
              <circle cx="18" cy="20" r="1.5" />
              <path d="M2 3h3l2.6 12.4a2 2 0 0 0 2 1.6h8.2a2 2 0 0 0 2-1.5L21 8H6" />
            </svg>
            <span className="s-cart-text">Giỏ hàng</span>
            {count > 0 && <span className="s-cart-count">{count}</span>}
          </Link>
        </div>
      </div>
      <nav className={`s-nav ${menu ? "open" : ""}`} aria-label="Danh mục sản phẩm">
        <div className="s-wrap s-nav-inner">
          <Link href="/" className={pathname === "/" ? "active" : undefined}>
            Trang chủ
          </Link>
          {DEPARTMENTS.map((dept) => (
            <div className="s-nav-item" key={dept.slug}>
              <Link href={`/danh-muc/${dept.slug}`} className={active(`/danh-muc/${dept.slug}`)}>
                {categoryName(dept.slug)}
              </Link>
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
          <Link href="/khuyen-mai" className={"s-nav-hot " + (active("/khuyen-mai") || "")}>
            Khuyến mãi
          </Link>
          <Link href="/chinh-sach" className={active("/chinh-sach")}>
            Chính sách
          </Link>
        </div>
      </nav>
    </header>
  );
}
