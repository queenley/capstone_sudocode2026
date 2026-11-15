// /admin/cai-tien: the weekly round and its pipeline (features/admin/improvement-admin.tsx).
import type { Metadata } from "next";
import { ImprovementSection } from "@/features/admin/sections";

export const metadata: Metadata = { title: "Cải tiến hằng tuần" };

export default function Page() {
  return <ImprovementSection />;
}
