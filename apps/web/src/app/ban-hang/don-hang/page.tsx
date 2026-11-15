// /ban-hang/don-hang: orders, payments, shipping steps (features/sales/orders.tsx).
import type { Metadata } from "next";
import Orders from "@/features/sales/orders";

export const metadata: Metadata = { title: "Đơn hàng" };

export default function Page() {
  return <Orders />;
}
