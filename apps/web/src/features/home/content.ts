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

/** The home page's rows: a department or a few categories, four products each, and the listing "Xem thêm" opens. */
export const ROWS: { id: string; title: string; href: string; slugs: string[]; except?: string[] }[] = [
  { id: "may-loc", title: "Máy lọc không khí", href: "gia-dung/may-loc-khong-khi", slugs: ["gia-dung/may-loc-khong-khi"] },
  { id: "giay", title: "Giày dép", href: "thoi-trang/giay", slugs: ["thoi-trang/giay"] },
  { id: "thoi-trang", title: "Thời trang", href: "thoi-trang", slugs: ["thoi-trang"], except: ["thoi-trang/giay"] },
  { id: "me-be", title: "Mẹ & Bé", href: "me-be", slugs: ["me-be"] },
  { id: "gia-dung", title: "Gia dụng cho bếp và nhà", href: "gia-dung", slugs: ["gia-dung"], except: ["gia-dung/may-loc-khong-khi"] },
];

// From the store policy (chinh-sach), version 10/2026, and the catalogue.
export const TERMS: { name: string; line: string; value: string }[] = [
  { name: "Giao hàng", line: "Nội thành Hà Nội, TP.HCM, Đà Nẵng 1–2 ngày làm việc; tỉnh khác 2–4 ngày.", value: "Miễn phí từ 2.000.000₫" },
  { name: "Thanh toán", line: "Trả khi nhận hàng cho đơn dưới 10.000.000₫, hoặc chuyển khoản VietQR.", value: "Phí thu hộ 0₫" },
  { name: "Đổi trả", line: "Gia dụng và đồ mẹ bé lỗi kỹ thuật từ nhà sản xuất được đổi mới trong 30 ngày.", value: "7 ngày" },
  { name: "Bảo hành", line: "Máy lọc nước RO 36 tháng, máy lọc không khí đến 24 tháng.", value: "Đến 36 tháng" },
];
