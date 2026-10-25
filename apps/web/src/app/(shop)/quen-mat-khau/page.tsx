"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthCard, CodeStep, ErrorLine, PasswordInput, PhoneInput, useTask } from "@/components/account/AuthParts";
import { account, CodeSent } from "@/lib/account";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [sent, setSent] = useState<CodeSent | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useTask();

  return (
    <AuthCard
      title="Lấy lại mật khẩu"
      lead={sent ? undefined : "Nhập số điện thoại của tài khoản, cửa hàng sẽ gửi mã xác minh để bạn đặt mật khẩu mới."}
      foot={
        <>
          Nhớ ra mật khẩu? <Link href="/dang-nhap">Đăng nhập</Link>
        </>
      }
    >
      <form
        className="s-form"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            if (!sent) {
              setSent(await account.resetStart(phone.trim()));
              return;
            }
            await account.resetVerify(sent.challenge_id, code, password);
            router.replace("/tai-khoan");
          });
        }}
      >
        {!sent ? (
          <>
            <PhoneInput value={phone} onChange={setPhone} />
            <button className="s-btn" disabled={busy}>
              {busy ? "Đang gửi mã…" : "Gửi mã xác minh"}
            </button>
          </>
        ) : (
          <>
            <CodeStep sent={sent} phone={phone} code={code} onCode={setCode} onBack={() => setSent(null)} />
            <PasswordInput label="Mật khẩu mới (ít nhất 8 ký tự)" value={password} onChange={setPassword} autoComplete="new-password" />
            <p className="s-muted">Đặt mật khẩu mới sẽ đăng xuất tài khoản trên các thiết bị khác.</p>
            <button className="s-btn" disabled={busy || code.length !== 6 || password.length < 8}>
              {busy ? "Đang lưu…" : "Đặt mật khẩu mới"}
            </button>
          </>
        )}
        <ErrorLine error={error} />
      </form>
    </AuthCard>
  );
}
