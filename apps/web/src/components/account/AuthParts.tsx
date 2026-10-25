"use client";
// Pieces shared by the account pages (đăng nhập, đăng ký, quên mật khẩu, tài khoản).
import Link from "next/link";
import React, { useState } from "react";
import type { CodeSent } from "@/lib/account";

/** Where to go after signing in: ?next=/thanh-toan, only a path on this site. */
export function nextPath(fallback = "/tai-khoan"): string {
  const next = new URLSearchParams(window.location.search).get("next") || "";
  return next.startsWith("/") && !next.startsWith("//") ? next : fallback;
}

/** Run a form task with busy and error state. */
export function useTask() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Có lỗi, vui lòng thử lại");
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, setError, run };
}

export function AuthCard({ title, lead, children, foot }: { title: string; lead?: string; children: React.ReactNode; foot?: React.ReactNode }) {
  return (
    <div className="s-wrap s-page s-auth">
      <div className="s-auth-card">
        <h1 className="s-page-title">{title}</h1>
        {lead && <p className="s-lead">{lead}</p>}
        {children}
        {foot && <div className="s-auth-foot">{foot}</div>}
      </div>
    </div>
  );
}

export function ErrorLine({ error }: { error: string }) {
  return error ? (
    <div className="s-alert" role="alert">
      {error}
    </div>
  ) : null;
}

export function PasswordInput({
  label,
  value,
  onChange,
  autoComplete = "current-password",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
}) {
  const [shown, setShown] = useState(false);
  return (
    <label>
      {label}
      <span className="s-password">
        <input
          type={shown ? "text" : "password"}
          autoComplete={autoComplete}
          required
          minLength={autoComplete === "new-password" ? 8 : undefined}
          maxLength={128}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button type="button" className="s-link-btn" onClick={() => setShown(!shown)} aria-label={shown ? "Ẩn mật khẩu" : "Hiện mật khẩu"}>
          {shown ? "Ẩn" : "Hiện"}
        </button>
      </span>
    </label>
  );
}

export function PhoneInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label>
      Số điện thoại
      <input
        type="tel"
        inputMode="tel"
        autoComplete="tel"
        required
        pattern="[0-9 +.\-]{9,15}"
        placeholder="09xx xxx xxx"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

/** The one-time code step: where it was sent, the development code when no SMS is configured. */
export function CodeStep({ sent, phone, code, onCode, onBack }: { sent: CodeSent; phone: string; code: string; onCode: (code: string) => void; onBack: () => void }) {
  return (
    <>
      <p className="s-muted">Mã gồm 6 chữ số đã được gửi tới {phone}. Mã có hiệu lực 5 phút.</p>
      {sent.development_code && (
        <p className="s-devnote">
          Môi trường thử nghiệm (chưa cấu hình SMS): mã là <b>{sent.development_code}</b>
        </p>
      )}
      <label>
        Mã xác minh
        <input
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          pattern="\d{6}"
          maxLength={6}
          value={code}
          onChange={(e) => onCode(e.target.value.replace(/\D/g, ""))}
        />
      </label>
      <button type="button" className="s-link-btn" onClick={onBack}>
        ← Sửa thông tin / gửi lại mã
      </button>
    </>
  );
}

export function SignInLinks() {
  return (
    <>
      Chưa có tài khoản? <Link href="/dang-ky">Đăng ký</Link> · <Link href="/quen-mat-khau">Quên mật khẩu</Link>
    </>
  );
}
