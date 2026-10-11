import Workspace from "@/features/workspace";
import { notFound } from "next/navigation";
export default async function RolePage({
  params,
}: {
  params: Promise<{ role: string }>;
}) {
  const { role } = await params;
  if (!["agent", "admin", "seller", "developer"].includes(role)) notFound();
  return <Workspace role={role} />;
}
