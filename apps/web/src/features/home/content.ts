import { HOTLINE } from "@/lib/contact";

/** The photographs folder of the storefront kit (public/assets/img, credited on /anh). */
export const IMG = "/assets/img";

/** The range: a category, the catalogue photo that shows it, and its alt text. */
export const RANGE: { slug: string; picture: string; alt: string }[] = [
  { slug: "gia-dung/may-loc-khong-khi", picture: "/products/SKU-AP-X.jpg", alt: "Máy lọc không khí trắng đặt cạnh sofa" },
  { slug: "gia-dung/may-loc-nuoc", picture: "/products/SKU-WF-RO9.jpg", alt: "Vòi máy lọc nước đang rót vào cốc thủy tinh" },
  { slug: "gia-dung/noi-chien", picture: "/products/SKU-AF-XM.jpg", alt: "Lò chiên không dầu đang nướng bánh" },
  { slug: "gia-dung/quat", picture: "/products/SKU-FAN-SEN.jpg", alt: "Quạt đứng giữa đồ đạc trong một nhà kho" },
  { slug: "thoi-trang/giay", picture: "/products/SKU-SN-RUN2.jpg", alt: "Đôi giày chạy bộ màu xám dây đỏ đặt trên hộp giày" },
  { slug: "thoi-trang/ao-khoac", picture: "/products/SKU-JK-WND.jpg", alt: "Người phụ nữ mặc áo khoác gió đứng trên boong tàu" },
  { slug: "me-be", picture: "/products/SKU-MB-STR1.jpg", alt: "Ba chiếc xe đẩy em bé dựng cạnh bức tường đá" },
  { slug: "gia-dung/combo", picture: "/products/SKU-BDL-AIR.jpg", alt: "Mặt trên của máy lọc không khí với bảng điều khiển cảm ứng" },
];

/** What the assistant does, one row each in #tro-ly. */
export const ASSIST: { icon: "sparkles" | "cart" | "headset"; name: string; line: string }[] = [
  { icon: "sparkles", name: "Tư vấn theo nhu cầu", line: "Diện tích phòng, tuổi của bé, cỡ giày: trợ lý hỏi lại cho đủ rồi mới gợi ý." },
  { icon: "cart", name: "Đặt hàng trong khung chat", line: "Thêm vào giỏ, xác minh số điện thoại và đặt mà không rời trang." },
  { icon: "headset", name: "Chuyển cho nhân viên", line: "Khi bạn muốn nói với người thật, nhân viên nhận cả cuộc trò chuyện." },
];

// From the store policy (chinh-sach), version 10/2026, and the catalogue.
export const TERMS: { name: string; line: string; value: string }[] = [
  { name: "Giao hàng", line: "Nội thành Hà Nội, TP.HCM, Đà Nẵng 1–2 ngày làm việc; tỉnh khác 2–4 ngày.", value: "Miễn phí từ 2.000.000₫" },
  { name: "Thanh toán", line: "Trả khi nhận hàng cho đơn dưới 10.000.000₫, hoặc chuyển khoản VietQR.", value: "Phí thu hộ 0₫" },
  { name: "Đổi trả", line: "Gia dụng và đồ mẹ bé lỗi kỹ thuật từ nhà sản xuất được đổi mới trong 30 ngày.", value: "7 ngày" },
  { name: "Bảo hành", line: "Máy lọc nước RO 36 tháng, máy lọc không khí đến 24 tháng.", value: "Đến 36 tháng" },
];

export const QUESTIONS: { q: string; a: string }[] = [
  { q: "Trợ lý AI lấy giá ở đâu?", a: "Từ hệ thống bán hàng của Quivo, cùng nguồn với trang sản phẩm. Giá và tồn kho được xác nhận lại khi bạn đặt hàng." },
  { q: "Khi nào trợ lý chuyển tôi cho nhân viên?", a: "Khi bạn yêu cầu, hoặc khi trợ lý không chắc câu trả lời. Nhân viên nhận cuộc trò chuyện kèm những gì bạn đã nói." },
  { q: "Trợ lý có nhớ tôi ở lần sau không?", a: "Có, sau khi bạn xác minh số điện thoại: lần sau trợ lý nhớ nhu cầu và đơn hàng cũ. Bạn có thể yêu cầu xóa những gì trợ lý nhớ." },
  { q: "Tôi có gọi điện cho Quivo được không?", a: `Có. Gọi hotline ${HOTLINE}, hoặc bấm Gọi thoại trong khung chat để gọi qua web, không tốn cước.` },
];
