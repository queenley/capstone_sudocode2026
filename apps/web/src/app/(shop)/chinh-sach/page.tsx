"use client";
// A summary of the store policies the assistant answers from
// (apps/ai-agent-service/data/btc/policy, version 2026-10). The full text and
// edge cases are in those documents; the assistant cites them per question.
import { shopContext } from "@/lib/shop-context";
import { HOTLINE, ZALO_URL } from "@/lib/contact";
import Icon, { IconName } from "@/components/ui/Icon";

// Each section: its icon, the one fact most people come for (shown first), then the terms.
const SECTIONS: { id: string; title: string; icon: IconName; key: string; items: string[] }[] = [
  {
    id: "doi-tra",
    icon: "return",
    key: "Đổi trả trong 7 ngày",
    title: "Đổi trả",
    items: [
      "Đổi hoặc trả trong 7 ngày kể từ ngày nhận hàng; gia dụng và mẹ & bé lỗi kỹ thuật từ nhà sản xuất được đổi mới trong 30 ngày.",
      "Sản phẩm còn nguyên tem, nhãn, hộp, chưa qua sử dụng, kèm mã đơn hàng. Đồ lót, bình sữa, núm ti đã bóc seal không đổi trả.",
      "Thời trang: đổi size/màu lần đầu miễn phí hai chiều; từ lần thứ hai khách chịu 30.000₫/chiều.",
      "Hoàn tiền trong 3–5 ngày làm việc sau khi cửa hàng nhận lại hàng đạt điều kiện.",
      "Yêu cầu đổi trả qua hotline hoặc Zalo, cung cấp mã đơn và lý do; cửa hàng gửi người đến lấy hàng trong 1–2 ngày làm việc.",
    ],
  },
  {
    id: "giao-hang",
    icon: "truck",
    key: "Miễn phí cho đơn từ 2.000.000₫",
    title: "Giao hàng",
    items: [
      "Nội thành Hà Nội, TP.HCM, Đà Nẵng: 1–2 ngày làm việc; tỉnh thành khác: 2–4 ngày; vùng sâu, hải đảo: 5–7 ngày.",
      "Phí: 25.000₫ nội thành, 35.000₫ liên tỉnh; miễn phí cho đơn từ 2.000.000₫. Mẹ & bé miễn phí từ 500.000₫ trong thời gian chương trình.",
      "Hàng cồng kềnh (máy lọc nước, xe đẩy, ghế ô tô) phụ thu 30.000₫ ngoài nội thành.",
      "Đơn COD trên 2.000.000₫ được nhân viên gọi xác nhận trước khi giao.",
    ],
  },
  {
    id: "thanh-toan",
    icon: "card",
    key: "Trả khi nhận hàng cho đơn dưới 10.000.000₫",
    title: "Thanh toán",
    items: [
      "Thanh toán khi nhận hàng (COD) toàn quốc cho đơn dưới 10.000.000₫, phí thu hộ 0₫.",
      "Được kiểm tra ngoại quan trước khi thanh toán, không dùng thử.",
      "Cửa hàng chưa hỗ trợ trả góp.",
    ],
  },
  {
    id: "bao-hanh",
    icon: "shield",
    key: "Bảo hành đến 36 tháng",
    title: "Bảo hành",
    items: [
      "Máy lọc không khí AirPure, Samsung: 24 tháng; Xiaomi: 12 tháng. Máy lọc nước RO: 36 tháng thân máy (lõi lọc không bảo hành).",
      "Quạt, nồi chiên, máy hút sữa, máy tiệt trùng, xe đẩy, ghế ô tô: 12 tháng. Giày, áo khoác: không bảo hành, áp dụng đổi trả 7 ngày.",
      "Không bảo hành hao mòn tự nhiên (màng lọc, lõi lọc, pin) và hư hỏng do rơi vỡ, vào nước, dùng sai điện áp.",
      "Bảo hành mở rộng thêm 12 tháng: 8% giá sản phẩm, cho gia dụng trên 3.000.000₫, mua trong 15 ngày từ khi nhận hàng.",
    ],
  },
];

export default function PolicyPage() {
  return (
    <div className="s-wrap s-page">
      <header className="s-page-head">
        <h1 className="s-page-title">Chính sách cửa hàng</h1>
        <p className="s-lead">
          Tóm tắt chính sách hiện hành (phiên bản 10/2026). Trường hợp cụ thể, hãy hỏi trợ lý hoặc nhân viên để được trả
          lời theo đúng điều khoản.
        </p>
      </header>
      {/* The contents on the left (sticky on a desktop), the sections on the right (shop.css, "the policy page"). */}
      <div className="s-policy-layout">
        <nav className="s-policy-toc" aria-label="Các mục chính sách">
          {SECTIONS.map((section) => (
            <a key={section.id} href={`#${section.id}`}><Icon name={section.icon} size={18} />{section.title}</a>
          ))}
        </nav>
        <div className="s-policy-list">
          {SECTIONS.map((section) => (
            <section key={section.id} id={section.id} className="s-policy" aria-labelledby={`${section.id}-h`}>
              <div className="s-policy-head">
                <span className="s-policy-icon"><Icon name={section.icon} size={22} /></span>
                <div>
                  <h2 id={`${section.id}-h`}>{section.title}</h2>
                  <p className="s-policy-key">{section.key}</p>
                </div>
              </div>
              <ul>
                {section.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ))}
          <div className="s-policy-help">
            <p>Chưa thấy trường hợp của bạn? Hỏi trực tiếp, trợ lý trả lời theo đúng điều khoản.</p>
            <div className="s-center">
              <button className="s-btn" onClick={() => shopContext.openChat("Tôi muốn hỏi về chính sách đổi trả")}>
                <Icon name="chat" size={18} /> Hỏi trợ lý về chính sách
              </button>
              <a className="s-btn s-btn-outline" href={`tel:${HOTLINE.replace(/\s/g, "")}`}>
                <Icon name="phone" size={18} /> Gọi {HOTLINE}
              </a>
              {ZALO_URL && (
                <a className="s-btn s-btn-outline" href={ZALO_URL} target="_blank" rel="noreferrer">
                  Nhắn Zalo
                </a>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
