// /ban-hang/hoi-thoai: live conversations and hand-offs (features/sales/conversations.tsx).
import type { Metadata } from "next";
import Conversations from "@/features/sales/conversations";

export const metadata: Metadata = { title: "Hội thoại & chuyển máy" };

export default function Page() {
  return <Conversations />;
}
