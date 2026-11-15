// /admin/kien-thuc: knowledge gaps and the FAQ (features/admin/knowledge-gaps.tsx, faq-admin.tsx).
import type { Metadata } from "next";
import { KnowledgeSection } from "@/features/admin/sections";

export const metadata: Metadata = { title: "Kiến thức" };

export default function Page() {
  return <KnowledgeSection />;
}
