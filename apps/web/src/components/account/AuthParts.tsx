"use client";
// Pieces shared by the account pages (đăng nhập, đăng ký, quên mật khẩu, tài khoản).
import Link from "next/link";
import React, { useState } from "react";
import type { CodeSent } from "@/lib/account";
import Icon from "@/components/ui/Icon";

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

/** What an account gives, as the sign-in page says it: shown beside every account form on a desktop. */
const ACCOUNT_GIVES = [
  "Giỏ hàng giữ nguyên trên mọi thiết bị",
  "Xem và tra cứu đơn hàng đã đặt",
  "Trợ lý AI tư vấn theo lịch sử mua sắm",
];

// The account pages' frame (shop.css, "the account pages"): on a desktop the shop's photograph under its
// emerald shade with what an account gives on the left, the form on the right; on a phone the form alone.
export function AuthCard({ title, lead, children, foot }: { title: string; lead?: string; children: React.ReactNode; foot?: React.ReactNode }) {
  return (
    <div className="s-wrap s-page s-auth">
      <div className="s-auth-shell">
        <aside className="s-auth-side" aria-hidden="true">
          <img src="/assets/img/photo-f107853503-960.webp" alt="" width={960} height={722} decoding="async" />
          <div className="s-auth-side__words">
            <p className="s-auth-side__kicker">Tài khoản Quivo</p>
            <p className="s-auth-side__title">Mua sắm cùng trợ lý AI nhớ bạn là ai</p>
            <ul>
              {ACCOUNT_GIVES.map((line) => (
                <li key={line}><Icon name="check" size={16} />{line}</li>
              ))}
            </ul>
          </div>
        </aside>
        <div className="s-auth-card">
          <h1 className="s-auth-title">{title}</h1>
          {lead && <p className="s-auth-lead">{lead}</p>}
          {children}
          {foot && <div className="s-auth-foot">{foot}</div>}
        </div>
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
  aside,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
  /** A link beside the label, e.g. "Quên mật khẩu?" (outside the <label>, so a click on it is its own). */
  aside?: React.ReactNode;
}) {
  const [shown, setShown] = useState(false);
  const id = React.useId();
  return (
    <div className="s-field">
      <div className="s-field-head">
        <label htmlFor={id}>{label}</label>
        {aside}
      </div>
      <span className="s-password">
        <input
          id={id}
          type={shown ? "text" : "password"}
          autoComplete={autoComplete}
          required
          minLength={autoComplete === "new-password" ? 8 : undefined}
          maxLength={128}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button type="button" className="s-password-eye" onClick={() => setShown(!shown)}
          aria-label={shown ? "Ẩn mật khẩu" : "Hiện mật khẩu"} aria-pressed={shown} title={shown ? "Ẩn mật khẩu" : "Hiện mật khẩu"}>
          <Icon name={shown ? "eye-off" : "eye"} size={18} />
        </button>
      </span>
    </div>
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
