"use client";
import Link from "next/link";
import { Logo } from "@/components/brand/Logo";
import { categoryName, DEPARTMENTS } from "@/lib/catalog";
import { HOTLINE, ZALO_URL } from "@/lib/contact";
import { shopContext } from "@/lib/shop-context";
import { MAIN_ACTION } from "./Header";

// The storefront's footer, the same on every page: taste-skill's footer--dark on the inverse ground, in the
// home hero's deep emerald (shop.css, "the footer"). The brand block (logo, one line, the two ways to reach the
// shop) on the left, four link columns on the right, the legal line under a hairline. Staff pages are reached
// with a full load (<a>), so the shop's stylesheets do not follow them there.
const tel = `tel:${HOTLINE.replace(/\s/g, "")}`;

export default function Footer() {
  return (
    <footer className="footer footer--dark ground-inverse s-footer">
      <div className="wrap">
        <div className="s-footer__top">
          <div className="s-footer__brand">
            <Link className="nav__logo" href="/" aria-label="Quivo, trang chủ"><Logo height={28} title="" /></Link>
            <p className="s-footer__lede">Gia dụng, thời trang và đồ mẹ bé. Mua trên web, qua hotline hoặc Zalo, có trợ lý AI trả lời cả đêm.</p>
            <div className="s-footer__reach">
              <button className="btn btn--primary" type="button" onClick={() => shopContext.openChat()}>{MAIN_ACTION}</button>
              <a className="btn btn--secondary" href={tel}>Gọi {HOTLINE}</a>
            </div>
          </div>
          <nav className="s-footer__cols" aria-label="Liên kết cuối trang">
            <div className="footer__col">
              <h3>Danh mục</h3>
              <ul>
                {DEPARTMENTS.map((dept) => <li key={dept.slug}><Link href={`/danh-muc/${dept.slug}`}>{categoryName(dept.slug)}</Link></li>)}
                <li><Link href="/khuyen-mai">Khuyến mãi</Link></li>
              </ul>
            </div>
            <div className="footer__col">
              <h3>Mua hàng</h3>
              <ul>
                <li><Link href="/gio-hang">Giỏ hàng</Link></li>
                <li><Link href="/don-hang">Tra cứu đơn hàng</Link></li>
                <li><Link href="/chinh-sach">Đổi trả và bảo hành</Link></li>
              </ul>
            </div>
            <div className="footer__col">
              <h3>Liên hệ</h3>
              <ul>
                <li><a href={tel}>Hotline {HOTLINE}</a></li>
                {ZALO_URL && <li><a href={ZALO_URL} target="_blank" rel="noreferrer">Zalo</a></li>}
                <li><button className="footer__link" type="button" onClick={() => shopContext.openChat()}>Chat trên web</button></li>
              </ul>
            </div>
            <div className="footer__col">
              <h3>Nhân viên</h3>
              <ul>
                <li><a href="/login">Đăng nhập</a></li>
                <li><a href="/ban-hang">Trang bán hàng</a></li>
              </ul>
            </div>
          </nav>
        </div>
        <div className="footer__legal">
          <span>© {new Date().getFullYear()} Quivo · dữ liệu sản phẩm minh họa cho dự án capstone. Trợ lý AI có thể sai; giá và tồn kho được xác nhận lại khi đặt hàng.</span>
          <Link className="credits" href="/anh">Ảnh qua Openverse, Flickr và Wikimedia Commons</Link>
        </div>
      </div>
    </footer>
  );
}
