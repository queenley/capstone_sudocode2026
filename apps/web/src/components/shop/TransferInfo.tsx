// How to pay an order by bank transfer: the shop's account, the exact amount,
// the note that matches the payment to the order, and a VietQR code that banking
// apps scan to fill all three in.
import { money } from "@/lib/catalog";

export type Transfer = {
  bank_name: string;
  account_no: string;
  account_name: string;
  amount: number;
  content: string;
  qr_url: string;
};

export default function TransferInfo({ transfer }: { transfer: Transfer }) {
  return (
    <div className="s-transfer">
      {/* eslint-disable-next-line @next/next/no-img-element -- an external, per-order QR image */}
      <img src={transfer.qr_url} alt="Mã VietQR để chuyển khoản" width={220} height={220} />
      <dl>
        <dt>Ngân hàng</dt>
        <dd>{transfer.bank_name || "—"}</dd>
        <dt>Số tài khoản</dt>
        <dd>
          <b>{transfer.account_no}</b>
        </dd>
        <dt>Chủ tài khoản</dt>
        <dd>{transfer.account_name}</dd>
        <dt>Số tiền</dt>
        <dd>
          <b>{money(transfer.amount)}</b>
        </dd>
        <dt>Nội dung</dt>
        <dd>
          <b>{transfer.content}</b>
        </dd>
      </dl>
      <p className="s-muted">
        Quét mã bằng ứng dụng ngân hàng, hoặc chuyển đúng số tiền với nội dung trên. Đơn được giao sau khi cửa hàng xác
        nhận đã nhận tiền.
      </p>
    </div>
  );
}
