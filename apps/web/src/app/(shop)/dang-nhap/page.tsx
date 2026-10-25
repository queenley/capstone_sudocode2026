"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthCard, ErrorLine, nextPath, PasswordInput, PhoneInput, useTask } from "@/components/account/AuthParts";
import { account, useAccount } from "@/lib/account";

export default function LoginPage() {
  const router = useRouter();
  const { status } = useAccount();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useTask();

  useEffect(() => {
    if (status === "signed-in") router.replace(nextPath());
  }, [status, router]);

  return (
    <AuthCard
      title="Đăng nhập"
      lead="Đăng nhập để giữ giỏ hàng trên mọi thiết bị, xem đơn hàng và để trợ lý AI tư vấn theo lịch sử mua sắm của bạn."
      foot={
        <>
          Chưa có tài khoản? <Link href="/dang-ky">Đăng ký ngay</Link>
        </>
      }
    >
      <form
        className="s-form"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            await account.login(phone.trim(), password);
            router.replace(nextPath());
          });
        }}
      >
        <PhoneInput value={phone} onChange={setPhone} />
        <PasswordInput label="Mật khẩu" value={password} onChange={setPassword} />
        <div className="s-row s-row-between">
          <button className="s-btn" disabled={busy}>
            {busy ? "Đang đăng nhập…" : "Đăng nhập"}
          </button>
          <Link href="/quen-mat-khau" className="s-link-btn">
            Quên mật khẩu?
          </Link>
        </div>
        <ErrorLine error={error} />
      </form>
    </AuthCard>
  );
}
