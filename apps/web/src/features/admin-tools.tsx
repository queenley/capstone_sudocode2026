"use client";
import { useState } from "react";
import { api } from "@/services/api";

export default function AdminTools({
  token,
  onError,
}: {
  token: string;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("agent");
  const [sku, setSku] = useState("");
  const [stock, setStock] = useState(0);
  const [amount, setAmount] = useState("0");
  const [channel, setChannel] = useState("web");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  async function perform(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="admin-tools">
      <summary>Manage staff, inventory and promotions</summary>
      <h3>Create staff account</h3>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          perform(async () => {
            await api("/api/admin/users", token, { username, password, role });
            setPassword("");
            onError("Account created.");
          });
        }}
      >
        <label>
          Username
          <input
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label>
          Initial password
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
          Role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {["agent", "admin", "seller", "developer"].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <button disabled={busy} type="submit">
          Create account
        </button>
      </form>
      <h3>Inventory</h3>
      <label>
        SKU code
        <input value={sku} onChange={(e) => setSku(e.target.value)} />
      </label>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          perform(async () => {
            await api(
              "/api/admin/inventory/" + encodeURIComponent(sku),
              token,
              { quantity_on_hand: stock },
              "PUT",
            );
            onError("Inventory updated.");
          });
        }}
      >
        <label>
          Quantity on hand
          <input
            type="number"
            min={0}
            required
            value={stock}
            onChange={(e) => setStock(Number(e.target.value))}
          />
        </label>
        <button disabled={busy || !sku} type="submit">
          Update stock
        </button>
      </form>
      <h3>Create fixed promotion</h3>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          perform(async () => {
            await api("/api/admin/promotions", token, {
              sku_code: sku,
              channel,
              name: "Reviewed discount",
              description:
                "Fixed discount approved by the store administrator.",
              promotion_type: "fixed",
              value: amount,
              starts_at: new Date(start).toISOString(),
              ends_at: new Date(end).toISOString(),
            });
            onError("Promotion created.");
          });
        }}
      >
        <label>
          Channel
          <input
            required
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
          />
        </label>
        <label>
          Discount per item (VND)
          <input
            min={0}
            required
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        <label>
          Starts at (your timezone)
          <input
            required
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label>
          Ends at (your timezone)
          <input
            required
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
        <button disabled={busy || !sku} type="submit">
          Create promotion
        </button>
      </form>
    </details>
  );
}
