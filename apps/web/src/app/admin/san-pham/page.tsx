// /admin/san-pham: add a product (features/admin/catalog.tsx).
import type { Metadata } from "next";
import Catalog from "@/features/admin/catalog";

export const metadata: Metadata = { title: "Sản phẩm" };

export default function Page() {
  return <Catalog />;
}
