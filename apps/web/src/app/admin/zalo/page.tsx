// /admin/zalo: the Zalo mock, for admins only (features/admin/zalo-mock.tsx).
import type { Metadata } from "next";
import ZaloMock from "@/features/admin/zalo-mock";

export const metadata: Metadata = { title: "Zalo mock" };

export default function Page() {
  return <ZaloMock />;
}
