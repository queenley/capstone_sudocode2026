// The admin workspace's sections, one route each (app/admin/<slug>/page.tsx), and the icons its sidebar draws.

export type AdminPageId = "knowledge" | "policies" | "skills" | "improvement" | "evaluation" | "proposals" | "catalog" | "staff";

export type AdminPage = { id: AdminPageId; href: string; label: string; hint: string };

export const ADMIN_PAGES: AdminPage[] = [
  { id: "knowledge", href: "/admin/kien-thuc", label: "Kiến thức", hint: "Câu khách hỏi mà tài liệu chưa có, và FAQ chờ duyệt" },
  { id: "policies", href: "/admin/chinh-sach", label: "Chính sách", hint: "Bộ chính sách trợ lý dựa vào: tìm, xem hiệu lực, mục nội bộ" },
  { id: "skills", href: "/admin/skills", label: "Skills của trợ lý", hint: "Cách trợ lý làm từng việc: xem, sửa, thêm, bật version" },
  { id: "improvement", href: "/admin/cai-tien", label: "Cải tiến hằng tuần", hint: "Đề xuất của Reflection mỗi tuần: duyệt, xem phép đo, rồi mới bật" },
  { id: "evaluation", href: "/admin/danh-gia", label: "Đánh giá", hint: "Chỉ số BTC theo từng tuần, cùng bộ kịch bản và cùng extractor" },
  { id: "proposals", href: "/admin/de-xuat", label: "Đề xuất từ hội thoại", hint: "Đề xuất từ hội thoại; chỉ thành kiến thức khi có người duyệt" },
  { id: "catalog", href: "/admin/san-pham", label: "Sản phẩm", hint: "Thêm sản phẩm vào catalog" },
  { id: "staff", href: "/admin/nhan-su", label: "Nhân sự & kho", hint: "Tài khoản nhân viên, tồn kho, khuyến mãi" },
];

const svg = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};
const ICONS = {
  knowledge: <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5" />,
  proposals: <path d="M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9" />,
  improvement: <path d="M21 12a9 9 0 1 1-3-6.7M21 4v5h-5" />,
  policies: <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h6" />,
  skills: <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z" />,
  evaluation: <path d="M3 3v18h18M7 15l4-4 3 3 5-6" />,
  catalog: <path d="M21 16V8l-9-5-9 5v8l9 5zM3.3 7L12 12l8.7-5M12 22V12" />,
  staff: <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8" />,
  sales: <path d="M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z" />,
  console: <path d="M4 17l6-6-6-6M12 19h8" />,
  logout: <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />,
};

export const AdminIcon = ({ name }: { name: keyof typeof ICONS }) => <svg {...svg}>{ICONS[name]}</svg>;
