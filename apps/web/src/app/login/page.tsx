"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/services/api";

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
            router.push("/" + result.role);
          } catch (e) {
            setError(e instanceof Error ? e.message : "Login failed");
          } finally {
            setBusy(false);
          }
        }}
      >
        <p className="eyebrow">STAFF ACCESS</p>
        <h1>Welcome back.</h1>
        <p>Sign in to continue your conversations.</p>
        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
        <label>
          Username
          <input
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            autoComplete="current-password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button disabled={busy} type="submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
