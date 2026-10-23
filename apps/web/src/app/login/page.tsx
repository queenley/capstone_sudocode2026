"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/services/api";

/** Where to go after signing in: ?next= when it is a page of this site, else the role's home. */
function destination(role: string): string {
  const next = new URLSearchParams(window.location.search).get("next") || "";
  if (next.startsWith("/") && !next.startsWith("//")) return next;
  return role === "developer" ? "/developer" : "/ban-hang";
}

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <main className="shell">
      <header className="topbar">
        <Link className="logo" href="/">
          tiếp nối
        </Link>
      </header>
      <form
        className="panel loginpanel"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            const result = await api<{ access_token: string; role: string }>(
              "/api/auth/login",
              "",
              { username, password },
            );
            sessionStorage.setItem("staff-token", result.access_token);
            sessionStorage.setItem("staff-role", result.role);
            router.push(destination(result.role));
          } catch (e) {
            setError(e instanceof Error ? e.message : "Đăng nhập không thành công");
          } finally {
            setBusy(false);
          }
        }}
      >
        <p className="eyebrow">DÀNH CHO NHÂN VIÊN</p>
        <h1>Đăng nhập</h1>
        <p>Tư vấn viên, bán hàng và quản trị dùng tài khoản do quản trị viên cấp.</p>
        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
        <label>
          Tên đăng nhập
          <input
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label>
          Mật khẩu
          <input
            autoComplete="current-password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button disabled={busy} type="submit">
          {busy ? "Đang đăng nhập…" : "Đăng nhập"}
        </button>
      </form>
    </main>
  );
}
