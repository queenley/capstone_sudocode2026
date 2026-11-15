// The admin workspace (/admin/*): the frame, the sign-in and the notice line stay while the admin moves between
// sections; each section is its own route below (kien-thuc, chinh-sach, skills, cai-tien, danh-gia, de-xuat, …).
import type { Metadata } from "next";
import AdminShell from "@/features/admin/admin-shell";
import "../ban-hang/sales.css";
import "./admin.css";

export const metadata: Metadata = { title: { default: "Quản trị", template: "%s · Quản trị · Quivo" } };

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
