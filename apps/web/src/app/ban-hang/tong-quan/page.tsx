// /ban-hang/tong-quan: today's numbers (features/sales/overview.tsx).
import type { Metadata } from "next";
import Overview from "@/features/sales/overview";

export const metadata: Metadata = { title: "Tổng quan bán hàng" };

export default function Page() {
  return <Overview />;
}
