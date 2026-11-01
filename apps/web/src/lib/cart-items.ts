// The cart's lines with current product data, re-read from the catalog.
import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { CatalogRow } from "@/lib/catalog";
import { CartLine } from "@/lib/cart";

export type CartItem = CartLine & { row: CatalogRow | null };

export function useCartItems(lines: CartLine[]) {
  const [rows, setRows] = useState<Record<string, CatalogRow | null>>({});
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const key = lines.map((l) => l.sku).sort().join(",");

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    const missing = lines.map((l) => l.sku).filter((sku) => !(sku in rows));
    if (!missing.length) return;
    Promise.all(
      missing.map((sku) =>
        api<CatalogRow>(`/api/catalog/${encodeURIComponent(sku)}`, "", undefined, undefined, { signal: controller.signal })
          .then((row) => [sku, row] as const)
          .catch((error) => {
            if (error.status === 404) return [sku, null] as const;
            throw error;
          }),
      ),
    )
      .then((pairs) => {
        if (controller.signal.aborted) return;
        setRows((old) => ({ ...old, ...Object.fromEntries(pairs) }));
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError("Chưa tải được thông tin sản phẩm. Giỏ hàng của bạn vẫn được giữ lại.");
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  return {
    items: lines.every((line) => line.sku in rows) ? lines.map((l) => ({ ...l, row: rows[l.sku] })) : null,
    error,
    retry: () => setAttempt((value) => value + 1),
  };
}

export function newKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    // Not a secure context (plain http on a LAN address): still unique enough per order attempt.
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  }
}
