"use client";
// The staff sign-in both workspaces share (/ban-hang, /admin). The login (/login) keeps the token and the role in
// sessionStorage ("staff-token", "staff-role"). The role only decides which links are shown: the API checks every call.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Logo } from "@/components/brand/Logo";

export type StaffSession = {
  /** null while the page has not read sessionStorage yet; "" when nobody is signed in. */
  token: string | null;
  role: string;
  signOut: () => void;
};

export function useStaffSession(): StaffSession {
  const [token, setToken] = useState<string | null>(null);
  const [role, setRole] = useState("");

  useEffect(() => {
    setToken(sessionStorage.getItem("staff-token") || "");
    setRole(sessionStorage.getItem("staff-role") || "");
  }, []);

  const signOut = useCallback(() => {
    sessionStorage.removeItem("staff-token");
    sessionStorage.removeItem("staff-role");
    setToken("");
    setRole("");
  }, []);

  return { token, role, signOut };
}

/** What a signed-out person sees in a staff workspace: one card and the way to the login, back to ``next`` after. */
export function StaffGate({ title, text, next }: { title: string; text: string; next: string }) {
  return (
    <div className="sl-gate">
      <div className="sl-gate-card">
        <Logo height={40} className="text-brand" />
        <h1>{title}</h1>
        <p>{text}</p>
        <Link className="sl-btn" href={`/login?next=${encodeURIComponent(next)}`}>
          Đăng nhập
        </Link>
      </div>
    </div>
  );
}
