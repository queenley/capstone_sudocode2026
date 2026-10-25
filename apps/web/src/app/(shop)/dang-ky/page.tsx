"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthCard, CodeStep, ErrorLine, nextPath, PasswordInput, PhoneInput, useTask } from "@/components/account/AuthParts";
import { account, CodeSent, useAccount } from "@/lib/account";

export default function RegisterPage() {
  const router = useRouter();
  const { status, account: me } = useAccount();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [consent, setConsent] = useState(false);
  const [sent, setSent] = useState<CodeSent | null>(null);
  const [code, setCode] = useState("");
  const { busy, error, setError, run } = useTask();

  useEffect(() => {
    // A shopper who only verified a phone (no password yet) registers to finish their account.
    if (status === "signed-in" && me?.registered && !sent) router.replace(nextPath());
    if (me && !me.registered) {
      setName((old) => old || me.full_name || "");
      setPhone((old) => old || me.phone || "");
    }
  }, [status, me, sent, router]);

  return (
    <AuthCard
      title="Đăng ký tài khoản"
      lead={sent ? undefined : "Tài khoản gắn với số điện thoại của bạn: đơn hàng, giỏ hàng và lịch sử tư vấn qua hotline hay Zalo đều về một nơi."}
      foot={
        <>
          Đã có tài khoản? <Link href="/dang-nhap">Đăng nhập</Link>
        </>
      }
    >
      <form
        className="s-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!sent && password !== again) {
            setError("Hai lần nhập mật khẩu chưa khớp");
            return;
          }
          run(async () => {
            if (!sent) {
              setSent(await account.registerStart({ full_name: name.trim(), phone: phone.trim(), password, email: email.trim() || undefined }));
              return;
            }
            await account.registerVerify(sent.challenge_id, code);
            router.replace(nextPath());
          });
        }}
      >
        {!sent ? (
          <>
            <label>
              Họ và tên
              <input autoComplete="name" required minLength={2} maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <PhoneInput value={phone} onChange={setPhone} />
            <label>
              Email (không bắt buộc)
              <input type="email" autoComplete="email" maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <PasswordInput label="Mật khẩu (ít nhất 8 ký tự)" value={password} onChange={setPassword} autoComplete="new-password" />
            <PasswordInput label="Nhập lại mật khẩu" value={again} onChange={setAgain} autoComplete="new-password" />
            <label className="s-check">
              <input type="checkbox" required checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span>
                Tôi đồng ý để cửa hàng lưu số điện thoại, giỏ hàng và nhu cầu mua sắm để phục vụ tôi tốt hơn (xem{" "}
                <Link href="/chinh-sach">chính sách</Link>)
              </span>
            </label>
            <button className="s-btn" disabled={busy || !consent}>
              {busy ? "Đang gửi mã…" : "Tiếp tục: gửi mã xác minh"}
            </button>
          </>
        ) : (
          <>
            <CodeStep sent={sent} phone={phone} code={code} onCode={setCode} onBack={() => setSent(null)} />
            <button className="s-btn" disabled={busy || code.length !== 6}>
              {busy ? "Đang tạo tài khoản…" : "Xác minh và tạo tài khoản"}
            </button>
          </>
        )}
        <ErrorLine error={error} />
      </form>
    </AuthCard>
  );
}
