"use client";
// /ban-hang/hen-goi-lai: the call-backs the assistant booked, already moved off holidays and out-of-hours.
import { useSales } from "./sales-context";

export default function Callbacks() {
  const callbacks = useSales().callbacks || [];
  return (
    <>
      <p className="sl-muted">
        Lịch do trợ lý AI đặt khi khách hẹn gọi lại (giờ đã được dời khỏi ngày nghỉ và ngoài giờ làm việc). Số điện thoại
        đầy đủ xem trong hồ sơ cuộc gọi.
      </p>
      {callbacks.length === 0 ? (
        <p className="sl-muted sl-center">Chưa có lịch hẹn.</p>
      ) : (
        <table className="sl-table">
          <thead>
            <tr>
              <th>Thời gian</th>
              <th>Khách</th>
              <th>Ghi chú</th>
              <th>Mã</th>
            </tr>
          </thead>
          <tbody>
            {callbacks.map((cb) => (
              <tr key={cb.callback_id}>
                <td>
                  <b>{new Date(cb.callback_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })}</b>
                  {cb.moved_from && <small className="sl-muted"> (khách hẹn {cb.moved_from.replace("T", " ")})</small>}
                </td>
                <td>
                  {cb.customer_name || "Khách"} {cb.phone_last4 && <span className="sl-muted">···{cb.phone_last4}</span>}
                </td>
                <td>{cb.note || "—"}</td>
                <td className="sl-muted">{cb.callback_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
