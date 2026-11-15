"use client";
// What every sales section reads, loaded once by the workspace's layout (app/ban-hang/layout.tsx) and kept while the
// person moves between sections: the calls, the orders, the call-backs, re-read every 10 seconds. What this token may
// read decides which sections exist (403 = not this role).
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, AgentCall } from "@/services/api";
import { salesHref } from "./nav";
import type { Callback, Order } from "./types";

type SalesData = {
  token: string;
  role: string;
  calls: AgentCall[] | null;
  orders: Order[] | null;
  callbacks: Callback[] | null;
  access: { calls: boolean; orders: boolean };
  checked: boolean;
  error: string;
  /** The open calls the assistant handed to a person, not yet taken. */
  waiting: AgentCall[];
  refresh: () => Promise<void>;
  /** The call the bell opened, for the console (``at``: the same call can be opened again). */
  focus: { id: number; at: number } | null;
  openCall: (id: number) => void;
};

const SalesContext = createContext<SalesData | null>(null);

export function useSales(): SalesData {
  const data = useContext(SalesContext);
  if (!data) throw new Error("useSales outside the sales workspace (app/ban-hang/layout.tsx)");
  return data;
}

export function SalesProvider({ token, role, children }: { token: string; role: string; children: React.ReactNode }) {
  const router = useRouter();
  const [calls, setCalls] = useState<AgentCall[] | null>(null);
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [callbacks, setCallbacks] = useState<Callback[] | null>(null);
  const [access, setAccess] = useState({ calls: false, orders: false });
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState("");
  const [focus, setFocus] = useState<{ id: number; at: number } | null>(null);

  const refresh = useCallback(async () => {
    const [c, o, cb] = await Promise.allSettled([
      api<AgentCall[]>("/api/agent/calls?open_only=false&limit=100", token),
      api<Order[]>("/api/seller/orders", token),
      api<Callback[]>("/api/agent/callbacks", token),
    ]);
    setAccess({ calls: c.status === "fulfilled", orders: o.status === "fulfilled" });
    if (c.status === "fulfilled") setCalls(c.value);
    if (o.status === "fulfilled") setOrders(o.value);
    if (cb.status === "fulfilled") setCallbacks(cb.value);
    setError(c.status === "rejected" && o.status === "rejected" ? "Tài khoản này không có quyền vào trang bán hàng." : "");
    setChecked(true);
  }, [token]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [refresh]);

  const openCall = useCallback(
    (id: number) => {
      setFocus({ id, at: Date.now() });
      router.push(salesHref("conversations"));
    },
    [router],
  );

  const value = useMemo<SalesData>(
    () => ({
      token,
      role,
      calls,
      orders,
      callbacks,
      access,
      checked,
      error,
      waiting: (calls || []).filter((c) => c.handoff_status === "pending" && !c.ended_at),
      refresh,
      focus,
      openCall,
    }),
    [token, role, calls, orders, callbacks, access, checked, error, refresh, focus, openCall],
  );

  return <SalesContext.Provider value={value}>{children}</SalesContext.Provider>;
}
