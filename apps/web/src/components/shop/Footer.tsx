"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/brand/Logo";
import { categoryName, DEPARTMENTS } from "@/lib/catalog";
import { HOTLINE, ZALO_URL } from "@/lib/contact";
import { shopContext } from "@/lib/shop-context";
import { MAIN_ACTION } from "./Header";

// taste-skill's footer-columns. On the home page it is footer.closing, the page's last screen: the dealt
// close (close-type: the h2, one line, the main action across the wrap) over the link columns. Every
// other page ends on the columns alone. Staff pages are reached with a full load (<a>), so the shop's
// stylesheets do not follow them there.
export default function Footer() {
  const home = usePathname() === "/";
  const links = (
    <div className="closing__links">
      <div className="grid">
        <div className="span-4 stack-4">
          <Link className="nav__logo" href="/" aria-label="Quivo"><Logo height={24} title="" /></Link>
          <p className="footer__lede">Gia dụng, thời trang và đồ mẹ bé, bán trên web, qua hotline và Zalo.</p>
        </div>
        <div className="span-2 footer__col">
          <h3>Danh mục</h3>
          <ul>
            {DEPARTMENTS.map((dept) => <li key={dept.slug}><Link href={`/danh-muc/${dept.slug}`}>{categoryName(dept.slug)}</Link></li>)}
            <li><Link href="/khuyen-mai">Khuyến mãi</Link></li>
          </ul>
        </div>
        <div className="span-2 footer__col">
          <h3>Mua hàng</h3>
          <ul>
            <li><Link href="/gio-hang">Giỏ hàng</Link></li>
            <li><Link href="/don-hang">Tra cứu đơn hàng</Link></li>
            <li><Link href="/chinh-sach">Đổi trả và bảo hành</Link></li>
          </ul>
        </div>
        <div className="span-2 footer__col">
          <h3>Liên hệ</h3>
          <ul>
            <li><a href={`tel:${HOTLINE.replace(/\s/g, "")}`}>Hotline {HOTLINE}</a></li>
            {ZALO_URL && <li><a href={ZALO_URL} target="_blank" rel="noreferrer">Zalo</a></li>}
            <li><button className="footer__link" type="button" onClick={() => shopContext.openChat()}>Chat trên web</button></li>
          </ul>
        </div>
        <div className="span-2 footer__col">
          <h3>Nhân viên</h3>
          <ul>
            <li><a href="/login">Đăng nhập</a></li>
            <li><a href="/ban-hang">Trang bán hàng</a></li>
          </ul>
        </div>
      </div>
      <div className="footer__legal">
        <span>© {new Date().getFullYear()} Quivo · dữ liệu sản phẩm minh họa cho dự án capstone. Trợ lý AI có thể sai; giá và tồn kho được xác nhận lại khi đặt hàng.</span>
        <Link className="credits" href="/anh">Ảnh qua Openverse, Flickr và Wikimedia Commons</Link>
      </div>
    </div>
  );

  if (!home) {
    return (
      <footer className="footer footer--app">
        <div className="wrap">{links}</div>
      </footer>
    );
  }
  return (
    <footer className="footer closing" id="contact" aria-labelledby="close-h">
      <div className="wrap">
        <div className="closing__cta close--type">
          <div className="section-head">
            <h2 id="close-h">Hỏi trợ lý trước khi mua</h2>
            <p>Trả lời ngay, cả đêm và cuối tuần. Khi cần người thật, trợ lý chuyển cuộc trò chuyện cho nhân viên.</p>
          </div>
          <button className="btn btn--primary btn--xl btn--wide" type="button" onClick={() => shopContext.openChat()}>
            {MAIN_ACTION}
            <svg className="m-arrow" viewBox="0 0 12 12" aria-hidden="true"><path className="m-arrow__stem" d="M1 6h8" /><path className="m-arrow__head" d="M4.5 2.5 8 6l-3.5 3.5" /></svg>
          </button>
        </div>
        {links}
      </div>
    </footer>
  );
}
