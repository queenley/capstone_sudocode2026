"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorLine, PasswordInput, useTask } from "@/components/account/AuthParts";
import { account, useAccount } from "@/lib/account";
import { useCart } from "@/lib/cart";
import { shopContext } from "@/lib/shop-context";

export default function AccountPage() {
  const router = useRouter();
  const { status, account: me } = useAccount();
  const lines = useCart();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [saved, setSaved] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const profile = useTask();
  const password = useTask();

  useEffect(() => {
    if (status === "guest") router.replace("/dang-nhap?next=/tai-khoan");
  }, [status, router]);

  useEffect(() => {
    setName(me?.full_name || "");
    setEmail(me?.email || "");
  }, [me]);

  if (status !== "signed-in" || !me) return <div className="s-wrap s-page" />;

  const items = lines.reduce((sum, line) => sum + line.qty, 0);

  return (
    <div className="s-wrap s-page s-narrow">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="s-page-title">Tài khoản của tôi</h1>
          <p className="s-muted">
            {me.phone}
            {me.registered_at && <> · thành viên từ {new Date(me.registered_at).toLocaleDateString("vi-VN")}</>}
          </p>
        </div>
        <button
          className="s-btn s-btn-ghost s-btn-inline"
          onClick={async () => {
            await account.logout();
            router.replace("/");
          }}
        >
          Đăng xuất
        </button>
      </div>

      <div className="my-[18px] grid grid-cols-1 gap-3 xs:grid-cols-2 sm:grid-cols-3">
        <Link href="/don-hang" className="s-account-tile">
          <b>Đơn hàng</b>
          <span>Xem trạng thái, thanh toán</span>
        </Link>
        <Link href="/gio-hang" className="s-account-tile">
          <b>Giỏ hàng</b>
          <span>{items ? `${items} sản phẩm, lưu theo tài khoản` : "Đang trống"}</span>
        </Link>
        <button className="s-account-tile" onClick={() => shopContext.openChat("Giỏ hàng của tôi có gì?")}>
          <b>Hỏi trợ lý AI</b>
          <span>Trợ lý xem được giỏ hàng và đơn của bạn</span>
        </button>
      </div>

      {!me.registered && (
        <div className="s-alert s-alert-info">
          Bạn đang dùng số điện thoại đã xác minh, chưa có mật khẩu. <Link href="/dang-ky">Hoàn tất đăng ký</Link> với số {me.phone} để
          đăng nhập trên thiết bị khác; lịch sử mua sắm vẫn được giữ.
        </div>
      )}

      <section className="s-account-section">
        <h2>Thông tin cá nhân</h2>
        <form
          className="s-form"
          onSubmit={(e) => {
            e.preventDefault();
            setSaved("");
            profile.run(async () => {
              await account.update({ full_name: name.trim(), email: email.trim() });
              setSaved("Đã lưu thông tin");
            });
          }}
        >
          <label>
            Họ và tên
            <input autoComplete="name" required minLength={2} maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Email
            <input type="email" autoComplete="email" maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Số điện thoại
            <input value={me.phone || ""} disabled />
          </label>
          <div className="s-row">
            <button className="s-btn" disabled={profile.busy}>
              {profile.busy ? "Đang lưu…" : "Lưu thay đổi"}
            </button>
            {saved && <span className="s-ok">{saved}</span>}
          </div>
          <ErrorLine error={profile.error} />
        </form>
      </section>

      {me.registered && (
        <section className="s-account-section">
          <h2>Đổi mật khẩu</h2>
          <form
            className="s-form"
            onSubmit={(e) => {
              e.preventDefault();
              password.run(async () => {
                await account.changePassword(current, next);
                setCurrent("");
                setNext("");
                password.setError("");
                setSaved("Đã đổi mật khẩu; các thiết bị khác đã được đăng xuất");
              });
            }}
          >
            <PasswordInput label="Mật khẩu hiện tại" value={current} onChange={setCurrent} />
            <PasswordInput label="Mật khẩu mới (ít nhất 8 ký tự)" value={next} onChange={setNext} autoComplete="new-password" />
            <button className="s-btn" disabled={password.busy || next.length < 8}>
              {password.busy ? "Đang đổi…" : "Đổi mật khẩu"}
            </button>
            <ErrorLine error={password.error} />
          </form>
        </section>
      )}
    </div>
  );
}
