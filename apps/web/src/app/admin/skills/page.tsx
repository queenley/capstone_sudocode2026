// /admin/skills: the advisor's skills and their versions (features/admin/skills-admin.tsx).
import type { Metadata } from "next";
import { SkillsSection } from "@/features/admin/sections";

export const metadata: Metadata = { title: "Skills của trợ lý" };

export default function Page() {
  return <SkillsSection />;
}
