import Link from "next/link";
import { LogoMark } from "@/components/brand/Logo";
import { categoryName, DEPARTMENTS } from "@/lib/catalog";
import { HOTLINE, ZALO_URL } from "@/lib/contact";

export default function Footer() {
  return (
    <footer className="s-footer">
      <div className="s-wrap s-footer-grid">
        <div>
          <div className="s-logo">
            <LogoMark className="s-logo-mark" />
            <span className="s-logo-text">
              <strong>Tiếp Nối</strong>
              <small>Trợ lý mua sắm AI</small>
            </span>
          </div>
          <p>
            Cửa hàng gia dụng, thời trang và đồ mẹ bé với trợ lý tư vấn AI trả lời 24/7 và đội ngũ nhân viên sẵn sàng hỗ
            trợ.
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
      <div className="s-wrap s-footer-base">
        <span>© {new Date().getFullYear()} Tiếp Nối. Dữ liệu sản phẩm minh họa cho dự án capstone.</span>
        <span>Trợ lý AI có thể sai; giá và tồn kho được xác nhận lại khi đặt hàng.</span>
      </div>
    </footer>
  );
}
