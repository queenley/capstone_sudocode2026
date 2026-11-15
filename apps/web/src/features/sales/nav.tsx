// The sales workspace's sections, one route each (app/ban-hang/<slug>/page.tsx), and the icons its sidebar draws.

export type SalesPageId = "overview" | "conversations" | "orders" | "callbacks";

export type SalesPage = {
  id: SalesPageId;
  href: string;
  label: string;
  hint: string;
  /** What the token must be allowed to read for the section to exist (403 = not this role). */
  needs: "calls" | "orders" | null;
};

export const SALES_PAGES: SalesPage[] = [
  { id: "overview", href: "/ban-hang/tong-quan", label: "Tổng quan", hint: "Số liệu hôm nay của cả cửa hàng", needs: null },
  { id: "conversations", href: "/ban-hang/hoi-thoai", label: "Hội thoại & chuyển máy", hint: "Web, Zalo, hotline: nhận cuộc AI chuyển cho nhân viên", needs: "calls" },
  { id: "orders", href: "/ban-hang/don-hang", label: "Đơn hàng", hint: "Xác nhận, đối soát thanh toán, hủy đơn", needs: "orders" },
  { id: "callbacks", href: "/ban-hang/hen-goi-lai", label: "Hẹn gọi lại", hint: "Lịch do trợ lý AI đặt với khách", needs: "calls" },
];

export const salesHref = (id: SalesPageId) => SALES_PAGES.find((p) => p.id === id)!.href;

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
  overview: <path d="M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z" />,
  conversations: <path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12zM8 11h.01M12 11h.01M16 11h.01" />,
  orders: <path d="M6 2h12l2 4v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6zM4 6h16M9 11h6M9 15h4" />,
  callbacks: <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z" />,
  console: <path d="M4 17l6-6-6-6M12 19h8" />,
  admin: <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4" />,
  logout: <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />,
  money: <path d="M2 7h20v10H2zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 12h.01M18 12h.01" />,
  clock: <path d="M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2" />,
  alert: <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01" />,
};

export const SalesIcon = ({ name }: { name: keyof typeof ICONS }) => <svg {...svg}>{ICONS[name]}</svg>;
