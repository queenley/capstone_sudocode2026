import Link from "next/link";
import { Logo } from "@/components/brand/Logo";
import { categoryName, DEPARTMENTS } from "@/lib/catalog";
import { HOTLINE, ZALO_URL } from "@/lib/contact";

export default function Footer() {
  return (
    <footer className="s-footer">
      {/* One column on a phone, two from 480px, the brand and three link columns from 1024px. */}
      <div className="s-wrap grid grid-cols-1 gap-7 xs:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr] [&_a]:block [&_a]:py-1 [&_a:hover]:text-accent">
        <div>
          <div className="s-logo">
            <span className="s-logo-text">
              <Logo height={34} className="text-on-chrome" />
              <small>Trợ lý mua sắm AI</small>
            </span>
          </div>
          <p>
            Cửa hàng gia dụng, thời trang và đồ mẹ bé với trợ lý tư vấn AI trả
            lời 24/7 và đội ngũ nhân viên sẵn sàng hỗ trợ.
          </p>
        </div>
        <div>
          <h4>Danh mục</h4>
          {DEPARTMENTS.map((dept) => (
            <Link key={dept.slug} href={`/danh-muc/${dept.slug}`}>
              {categoryName(dept.slug)}
            </Link>
          ))}
          <Link href="/khuyen-mai">Khuyến mãi</Link>
        </div>
        <div>
          <h4>Hỗ trợ khách hàng</h4>
          <Link href="/chinh-sach">Đổi trả, bảo hành, giao hàng</Link>
          <Link href="/don-hang">Tra cứu đơn hàng</Link>
          <a href={`tel:${HOTLINE.replace(/\s/g, "")}`}>Hotline {HOTLINE}</a>
          {ZALO_URL && (
            <a href={ZALO_URL} target="_blank" rel="noreferrer">
              Nhắn tin qua Zalo
            </a>
          )}
        </div>
        <div>
          <h4>Dành cho nhân viên</h4>
          <Link href="/login">Đăng nhập</Link>
          <Link href="/ban-hang">Trang bán hàng</Link>
        </div>
      </div>
      <div className="s-wrap mt-7 flex flex-col gap-2 border-t border-white/12 pt-4 pb-6 text-xs sm:flex-row sm:justify-between sm:gap-4">
        <span>
          © {new Date().getFullYear()} Quivo. Dữ liệu sản phẩm minh họa cho
          dự án capstone.
        </span>
        <span>
          Trợ lý AI có thể sai; giá và tồn kho được xác nhận lại khi đặt hàng.
        </span>
      </div>
    </footer>
  );
}
