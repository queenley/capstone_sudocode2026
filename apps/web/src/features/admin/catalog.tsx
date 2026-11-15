"use client";
// /admin/san-pham: add one product to the catalogue (POST /api/admin/catalog).
import { useState } from "react";
import { api } from "@/services/api";
import { useAdmin } from "./admin-context";

type Product = {
  name: string;
  brand: string;
  category: string;
  sku_code: string;
  list_price: string;
  sale_price: string;
  stock: number;
};

const FIELDS: { key: keyof Product; label: string; type: "text" | "number" }[] = [
  { key: "name", label: "Tên sản phẩm", type: "text" },
  { key: "brand", label: "Thương hiệu", type: "text" },
  { key: "category", label: "Danh mục", type: "text" },
  { key: "sku_code", label: "Mã SKU", type: "text" },
  { key: "list_price", label: "Giá niêm yết (đ)", type: "number" },
  { key: "sale_price", label: "Giá bán (đ)", type: "number" },
  { key: "stock", label: "Tồn kho", type: "number" },
];
const EMPTY: Product = { name: "", brand: "", category: "laptop", sku_code: "", list_price: "0", sale_price: "0", stock: 0 };

export default function Catalog() {
  const { token, setNotice } = useAdmin();
  const [product, setProduct] = useState<Product>(EMPTY);
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="sl-panel"
      aria-label="Thêm sản phẩm"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await api("/api/admin/catalog", token, product);
          setNotice("Đã thêm sản phẩm.");
          setProduct(EMPTY);
        } catch (error) {
          setNotice(error instanceof Error ? error.message : "Không thêm được sản phẩm");
        } finally {
          setBusy(false);
        }
      }}
    >
      {FIELDS.map(({ key, label, type }) => (
        <label key={key}>
          {label}
          <input
            required
            type={type}
            min={type === "number" ? "0" : undefined}
            value={product[key]}
            onChange={(e) => setProduct((old) => ({ ...old, [key]: key === "stock" ? Number(e.target.value) : e.target.value }))}
          />
        </label>
      ))}
      <button className="sl-btn" disabled={busy} type="submit">
        Thêm sản phẩm
      </button>
    </form>
  );
}
