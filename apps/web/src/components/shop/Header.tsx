"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Logo } from "@/components/brand/Logo";
import { categoryName, DEPARTMENTS } from "@/lib/catalog";
import { firstName, useAccount } from "@/lib/account";
import { useCart } from "@/lib/cart";
import { shopContext } from "@/lib/shop-context";

// The storefront's bar: taste-skill's nav-split (public/assets/system.css, .nav--split). The departments
// on the left, each opening a full-width panel of its categories on hover; Quivo's logo in the middle;
// search, the account and the cart as plain words and the one main action, the assistant, on the right.
// Under 1024px the words move into a full-screen sheet behind the "Danh mục" button.

/** A photograph for each category's card in the panel: one of its products (data/seed/catalog). */
const PICTURE: Record<string, string> = {
  "gia-dung/may-loc-khong-khi": "/products/SKU-AP-PRO.jpg",
  "gia-dung/may-loc-nuoc": "/products/SKU-WF-RO10.jpg",
  "gia-dung/quat": "/products/SKU-FAN-DC1.jpg",
  "gia-dung/noi-chien": "/products/SKU-AF-4L.jpg",
  "thoi-trang/giay": "/products/SKU-SN-RUN1.jpg",
  "thoi-trang/ao-khoac": "/products/SKU-JK-DWN.jpg",
  "thoi-trang/phu-kien": "/products/SKU-SN-SOCK.jpg",
};

export const MAIN_ACTION = "Chat với trợ lý AI";

export default function Header() {
  const lines = useCart();
  const { status, account } = useAccount();
  const count = lines.reduce((sum, line) => sum + line.qty, 0);
  const pathname = usePathname();
  const [menu, setMenu] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);

  useEffect(() => setMenu(false), [pathname]);
  useEffect(() => {
    document.body.classList.toggle("nav-locked", menu);
    return () => document.body.classList.remove("nav-locked");
  }, [menu]);

  const current = (href: string) => (pathname === href ? "page" : undefined);

  return (
    <header className={`nav nav--split${menu ? " is-open" : ""}`}>
      <div className="wrap nav__bar">
        <a className="skip-link" href="#shop-content">Đến nội dung chính</a>
        <Link className="nav__logo" href="/" aria-label="Quivo, trang chủ">
          <Logo height={26} title="" />
        </Link>
        <nav
          id="shop-navigation"
          className="nav__links"
          aria-label="Danh mục sản phẩm"
          onKeyDown={(event) => {
            if (event.key === "Escape" && menu) {
              setMenu(false);
              menuButton.current?.focus();
            }
          }}
        >
          {DEPARTMENTS.map((dept) => {
            const cards = dept.children.filter((child) => PICTURE[child]).slice(0, 4);
            const rest = dept.children.filter((child) => !cards.includes(child));
            return (
              <div className="nav__item" key={dept.slug}>
                <Link className="nav__link" href={`/danh-muc/${dept.slug}`} aria-current={current(`/danh-muc/${dept.slug}`)}>
                  {categoryName(dept.slug)}
                  {cards.length > 0 && (
                    <svg className="chev" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  )}
                </Link>
                {cards.length > 0 && (
                  <div className="nav__menu">
                    <div className="wrap grid">
                      {rest.length > 0 && (
                        <div className="menu-col span-3">
                          <p className="t-label">Thêm trong {categoryName(dept.slug).toLowerCase()}</p>
                          {rest.map((child) => <Link key={child} href={`/danh-muc/${child}`}>{categoryName(child)}</Link>)}
                        </div>
                      )}
                      {cards.map((child) => (
                        <Link key={child} className={`menu-card ${rest.length ? "span-3" : "span-4"}`} href={`/danh-muc/${child}`}>
                          <div className="panel"><img className="frame__img" src={PICTURE[child]} alt="" /></div>
                          <span className="t-card">{categoryName(child)}</span>
                        </Link>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          <div className="nav__item"><Link className="nav__link" href="/khuyen-mai" aria-current={current("/khuyen-mai")}>Khuyến mãi</Link></div>
        </nav>
        <div className="nav__actions">
          <Link className="nav__link" href="/tim-kiem" aria-current={current("/tim-kiem")}>Tìm</Link>
          <Link className="nav__link" href={status === "signed-in" ? "/tai-khoan" : "/dang-nhap"}
            aria-label={status === "signed-in" ? "Tài khoản của tôi" : "Đăng nhập hoặc đăng ký"}>
            {status === "signed-in" ? firstName(account) : "Đăng nhập"}
          </Link>
          <Link className="nav__link" href="/gio-hang" aria-label={`Giỏ hàng, ${count} sản phẩm`}>
            Giỏ hàng{count > 0 ? ` (${count})` : ""}
          </Link>
          <button className="btn btn--primary" type="button" onClick={() => shopContext.openChat()}>{MAIN_ACTION}</button>
        </div>
        <button
          ref={menuButton}
          className="nav__toggle"
          type="button"
          aria-label="Danh mục"
          aria-controls="shop-navigation"
          aria-expanded={menu}
          onClick={() => setMenu(!menu)}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M2 5h14M2 13h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
        </button>
      </div>
    </header>
  );
}
