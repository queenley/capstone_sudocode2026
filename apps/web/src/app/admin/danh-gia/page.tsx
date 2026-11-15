// /admin/danh-gia: the organisers' metrics by week (features/admin/evaluation-dashboard.tsx).
import type { Metadata } from "next";
import { EvaluationSection } from "@/features/admin/sections";

export const metadata: Metadata = { title: "Đánh giá" };

export default function Page() {
  return <EvaluationSection />;
}
