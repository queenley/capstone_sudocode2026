"use client";
// The admin's three standing tasks, each its own form: a staff account, a stock count, a fixed promotion.
// Each form names its own SKU: one shared SKU field let a stock update and a promotion land on different products
// without the admin seeing it. The admin page (/admin) and the role workspace (/admin as a role) both show it.
import { useState } from "react";
import { api } from "@/services/api";

const ROLES: { id: string; label: string }[] = [
  { id: "agent", label: "Tư vấn viên (agent)" },
  { id: "seller", label: "Bán hàng (seller)" },
  { id: "developer", label: "Kỹ thuật (developer)" },
  { id: "admin", label: "Quản trị (admin)" },
];

export default function AdminTools({
  token,
  onError,
}: {
  token: string;
  /** The page's one notice line: errors and confirmations both go there. */
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("agent");
  const [stockSku, setStockSku] = useState("");
  const [stock, setStock] = useState(0);
  const [promoSku, setPromoSku] = useState("");
  const [amount, setAmount] = useState("0");
  const [channel, setChannel] = useState("web");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  async function perform(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Không thực hiện được");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="ad-tools">
      <form
        className="sl-panel ad-form"
        aria-labelledby="ad-staff"
        onSubmit={(e) => {
          e.preventDefault();
          perform(async () => {
            await api("/api/admin/users", token, { username, password, role });
            setPassword("");
            onError(`Đã tạo tài khoản ${username}.`);
          });
        }}
      >
        <h2 id="ad-staff">Tài khoản nhân viên</h2>
        <p className="ad-lead">Nhân viên đăng nhập ở /login bằng tên và mật khẩu này, rồi tự vào trang của vai trò.</p>
        <label>
          Tên đăng nhập
          <input required minLength={3} autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label>
          <span>Mật khẩu ban đầu <small>· ít nhất 12 ký tự</small></span>
          <input
            required
            minLength={12}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <label>
          Vai trò
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <button className="sl-btn" disabled={busy} type="submit">
          Tạo tài khoản
        </button>
      </form>

      <form
        className="sl-panel ad-form"
        aria-labelledby="ad-stock"
        onSubmit={(e) => {
          e.preventDefault();
          perform(async () => {
            await api("/api/admin/inventory/" + encodeURIComponent(stockSku), token, { quantity_on_hand: stock }, "PUT");
            onError(`Đã cập nhật tồn kho ${stockSku}: ${stock}.`);
          });
        }}
      >
        <h2 id="ad-stock">Tồn kho</h2>
        <p className="ad-lead">Số đếm thực tế trong kho. Agent đọc tồn kho từ đây khi báo còn hàng.</p>
        <label>
          Mã SKU
          <input required value={stockSku} onChange={(e) => setStockSku(e.target.value)} />
        </label>
        <label>
          Số lượng trong kho
          <input type="number" min={0} required value={stock} onChange={(e) => setStock(Number(e.target.value))} />
        </label>
        <button className="sl-btn" disabled={busy} type="submit">
          Cập nhật tồn kho
        </button>
      </form>

      <form
        className="sl-panel ad-form"
        aria-labelledby="ad-promo"
        onSubmit={(e) => {
          e.preventDefault();
          perform(async () => {
            await api("/api/admin/promotions", token, {
              sku_code: promoSku,
              channel,
              name: "Reviewed discount",
              description: "Fixed discount approved by the store administrator.",
              promotion_type: "fixed",
              value: amount,
              starts_at: new Date(start).toISOString(),
              ends_at: new Date(end).toISOString(),
            });
            onError(`Đã tạo khuyến mãi cho ${promoSku}.`);
          });
        }}
      >
        <h2 id="ad-promo">Khuyến mãi giảm thẳng</h2>
        <p className="ad-lead">Giảm một số tiền cố định trên mỗi sản phẩm, trong khoảng thời gian chọn.</p>
        <div className="ad-pair">
          <label>
            Mã SKU
            <input required value={promoSku} onChange={(e) => setPromoSku(e.target.value)} />
          </label>
          <label>
            Kênh
            <input required value={channel} onChange={(e) => setChannel(e.target.value)} />
          </label>
        </div>
        <label>
          Giảm mỗi sản phẩm (đ)
          <input min={0} required type="number" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <div className="ad-pair">
          <label>
            Bắt đầu
            <input required type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            Kết thúc
            <input required type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
        </div>
        <button className="sl-btn" disabled={busy} type="submit">
          Tạo khuyến mãi
        </button>
      </form>
    </div>
  );
}
