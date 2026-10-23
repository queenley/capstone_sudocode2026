// The cart's lines with current product data, re-read from the catalog.
import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { CatalogRow } from "@/lib/catalog";
import { CartLine } from "@/lib/cart";

export type CartItem = CartLine & { row: CatalogRow | null };

export function useCartItems(lines: CartLine[]): { items: CartItem[] | null; error: string } {
  const [rows, setRows] = useState<Record<string, CatalogRow | null>>({});
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const key = lines.map((l) => l.sku).sort().join(",");

  useEffect(() => {
    const missing = lines.map((l) => l.sku).filter((sku) => !(sku in rows));
    if (!missing.length) {
      setLoaded(true);
      return;
    }
    Promise.all(
      missing.map((sku) =>
        api<CatalogRow>(`/api/catalog/${encodeURIComponent(sku)}`)
          .then((row) => [sku, row] as const)
          .catch(() => [sku, null] as const),
      ),
    )
      .then((pairs) => {
        setRows((old) => ({ ...old, ...Object.fromEntries(pairs) }));
        setLoaded(true);
      })
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return {
    items: loaded || !lines.length ? lines.map((l) => ({ ...l, row: rows[l.sku] ?? null })) : null,
    error,
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
