"use client";
// What every admin section shares, from the workspace's layout (app/admin/layout.tsx): the staff token and the one
// notice line under the top bar (a confirmation or an error). The notice clears when the admin moves to another section.
import { createContext, useContext } from "react";

export type AdminData = { token: string; notice: string; setNotice: (text: string) => void };

export const AdminContext = createContext<AdminData | null>(null);

export function useAdmin(): AdminData {
  const data = useContext(AdminContext);
  if (!data) throw new Error("useAdmin outside the admin workspace (app/admin/layout.tsx)");
  return data;
}
