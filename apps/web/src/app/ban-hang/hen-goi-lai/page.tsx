// /ban-hang/hen-goi-lai: call-backs the assistant booked (features/sales/callbacks.tsx).
import type { Metadata } from "next";
import Callbacks from "@/features/sales/callbacks";

export const metadata: Metadata = { title: "Hẹn gọi lại" };

export default function Page() {
  return <Callbacks />;
}
