// The sales workspace (/ban-hang/*): the frame and the data every section shares stay while the person moves between
// sections; each section is its own route below (tong-quan, hoi-thoai, don-hang, hen-goi-lai).
import type { Metadata } from "next";
import SalesShell from "@/features/sales/sales-shell";
import "./sales.css";

export const metadata: Metadata = { title: { default: "Bán hàng", template: "%s · Bán hàng · Quivo" } };

export default function SalesLayout({ children }: { children: React.ReactNode }) {
  return <SalesShell>{children}</SalesShell>;
}
