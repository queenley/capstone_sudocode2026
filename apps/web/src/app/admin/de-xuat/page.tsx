// /admin/de-xuat: proposals from conversations (features/admin/proposals.tsx).
import type { Metadata } from "next";
import Proposals from "@/features/admin/proposals";

export const metadata: Metadata = { title: "Đề xuất từ hội thoại" };

export default function Page() {
  return <Proposals />;
}
