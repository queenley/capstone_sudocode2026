// /admin/nhan-su: staff accounts, stock, promotions (features/admin/admin-tools.tsx).
import type { Metadata } from "next";
import { StaffSection } from "@/features/admin/sections";

export const metadata: Metadata = { title: "Nhân sự & kho" };

export default function Page() {
  return <StaffSection />;
}
