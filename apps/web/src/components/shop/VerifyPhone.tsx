"use client";
// Verify the shopper's phone number with a one-time code (Identity service),
// on their current conversation. On success the customer token is kept on
// this device, so later visits, chats and orders are recognised.
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/services/api";
import { account } from "@/lib/account";
import {
  customerToken,
  openSession,
  setCustomerToken,
  ShopSession,
  verifiedSession,
} from "@/lib/session";

type Challenge = {
  challenge_id: string;
  delivery: string;
  development_code?: string;
};

export default function VerifyPhone({
  onVerified,
}: {
  onVerified: (session: ShopSession) => void;
}) {
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [consent, setConsent] = useState(false);
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [session, setSession] = useState<ShopSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pathname = usePathname();
  const active = useRef(true);
  const inFlight = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  async function run(
    task: (
      current: () => boolean,
      acceptedToken: (value: string) => void,
    ) => Promise<void>,
  ) {
    if (inFlight.current) return;
    inFlight.current = true;
    const revision = account.revision();
    let expected = customerToken();
    const current = () =>
      active.current &&
      revision === account.revision() &&
      expected === customerToken();
    setBusy(true);
    setError("");
    try {
      await task(current, (value) => {
        expected = value;
      });
    } catch (e) {
      if (!current()) return;
      const message = e instanceof Error ? e.message : "";
      // A number already verified (it may be a household's) cannot prove which person is back.
      setError(
        message.startsWith("Returning/shared identifier")
          ? "Số điện thoại này đã có tài khoản hoặc đã được xác minh trước đây. Hãy đăng nhập (hoặc lấy lại mật khẩu) để tiếp tục."
          : message === "Incorrect verification code"
            ? "Mã xác minh chưa đúng, vui lòng kiểm tra lại."
            : message === "Challenge expired or invalid"
              ? "Mã đã hết hạn hoặc nhập sai quá nhiều lần. Hãy gửi lại mã mới."
              : message || "Có lỗi, vui lòng thử lại",
      );
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }

  return (
    <form
      className="s-form"
      aria-busy={busy}
      onSubmit={(e) => {
        e.preventDefault();
        run(async (current, acceptedToken) => {
          if (!challenge) {
            const s = session || (await openSession());
            if (!current()) return;
            setSession(s);
            const sent = await api<Challenge>(
              `/api/conversations/${s.conversation_id}/identity/challenge`,
              s.conversation_token,
              {
                kind: "phone",
                value: phone.trim(),
                consent,
              },
            );
            if (current()) setChallenge(sent);
            return;
          }
          const s = session!;
          const result = await api<{
            customer_id: string;
            customer_token: string;
          }>(
            `/api/conversations/${s.conversation_id}/identity/verify`,
            s.conversation_token,
            {
              challenge_id: challenge.challenge_id,
              code: code.trim(),
              full_name: name.trim(),
              customer_token: customerToken(),
            },
          );
          if (!current()) return;
          setCustomerToken(result.customer_token);
          acceptedToken(result.customer_token);
          const verified = { ...s, customer_id: result.customer_id };
          verifiedSession(verified);
          await account.verified();
          if (current()) onVerified(verified);
        });
      }}
    >
      {!challenge ? (
        <>
          <label>
            Số điện thoại
            <input
              type="tel"
              disabled={busy}
              inputMode="tel"
              autoComplete="tel"
              required
              pattern="[0-9 +.\-]{9,15}"
              placeholder="09xx xxx xxx"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          </label>
          <label>
            Họ và tên (không bắt buộc)
            <input
              disabled={busy}
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="s-check">
            <input
              type="checkbox"
              disabled={busy}
              required
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            Tôi đồng ý để cửa hàng lưu số điện thoại và nhu cầu mua sắm để phục
            vụ tôi tốt hơn
          </label>
          <button className="s-btn" disabled={busy || !consent}>
            {busy ? "Đang gửi mã…" : "Gửi mã xác minh"}
          </button>
        </>
      ) : (
        <>
          <p className="s-muted">Mã gồm 6 chữ số đã được gửi tới {phone}.</p>
          {challenge.development_code && (
            <p className="s-devnote">
              Môi trường thử nghiệm (chưa cấu hình SMS): mã là{" "}
              <b>{challenge.development_code}</b>
            </p>
          )}
          <label>
            Mã xác minh
            <input
              autoFocus
              inputMode="numeric"
              disabled={busy}
              autoComplete="one-time-code"
              required
              pattern="\d{6}"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            />
          </label>
          <div className="s-row">
            <button
              className="s-btn"
              disabled={busy || code.trim().length !== 6}
            >
              {busy ? "Đang xác minh…" : "Xác minh"}
            </button>
            <button
              type="button"
              disabled={busy}
              className="s-link-btn"
              onClick={() => { setChallenge(null); setCode(""); setError(""); }}
            >
              Đổi số điện thoại
            </button>
          </div>
        </>
      )}
      {error && (
        <div className="s-alert" role="alert">
          {error}
        </div>
      )}
      <p className="s-muted s-small">
        Đã có tài khoản?{" "}
        <Link href={`/dang-nhap?next=${encodeURIComponent(pathname)}`}>
          Đăng nhập
        </Link>{" "}
        · <Link href="/dang-ky">Đăng ký</Link>
      </p>
    </form>
  );
}
