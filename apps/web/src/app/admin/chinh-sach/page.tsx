// /admin/chinh-sach: the policies the assistant reads (features/admin/policies-admin.tsx).
import type { Metadata } from "next";
import { PoliciesSection } from "@/features/admin/sections";

export const metadata: Metadata = { title: "Chính sách" };

export default function Page() {
  return <PoliciesSection />;
}
