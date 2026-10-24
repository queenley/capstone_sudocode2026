"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LogoMark } from "@/components/brand/Logo";
import ThemeToggle from "@/components/theme/ThemeToggle";
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
    <main className="auth">
      <section className="auth-brand">
        <Link className="auth-logo" href="/">
          <LogoMark />
          <span>
            <strong>Tiếp Nối</strong>
            <small>Bán hàng & chăm sóc khách</small>
          </span>
        </Link>
        <div>
          <h2>Một nơi cho mọi cuộc trò chuyện với khách</h2>
          <ul>
            <li>Nhận cuộc AI chuyển máy từ web, Zalo và hotline, kèm Call Brief</li>
            <li>Xác nhận đơn, đối soát chuyển khoản, theo dõi lịch hẹn gọi lại</li>
            <li>Gợi ý câu trả lời của trợ lý, luôn theo đúng giá và chính sách</li>
          </ul>
        </div>
        <small>Dành cho nhân viên Tiếp Nối · Tài khoản do quản trị viên cấp</small>
      </section>
      <section className="auth-side">
        <div className="auth-top">
          <Link href="/">← Về cửa hàng</Link>
          <ThemeToggle />
        </div>
        <form
          className="auth-card"
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
          <p className="auth-lead">Tư vấn viên, bán hàng và quản trị dùng tài khoản do quản trị viên cấp.</p>
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
      </section>
    </main>
  );
}
