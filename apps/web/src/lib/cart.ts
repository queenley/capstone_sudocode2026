// The shopping cart, kept in this browser (localStorage) and shared by every
// component through useCart(). Prices are not stored: each is re-quoted from
// the Commerce API when the cart or checkout is shown.
import { useSyncExternalStore } from "react";

export type CartLine = { sku: string; qty: number };

const KEY = "shop-cart";
const listeners = new Set<() => void>();
let cache: CartLine[] | null = null;

function read(): CartLine[] {
  if (cache) return cache;
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || "[]");
    cache = Array.isArray(parsed)
      ? parsed.filter((l) => typeof l?.sku === "string" && Number.isInteger(l?.qty) && l.qty > 0)
      : [];
  } catch {
    cache = [];
  }
  return cache!;
}

function write(lines: CartLine[]) {
  cache = lines;
  try {
    localStorage.setItem(KEY, JSON.stringify(lines));
  } catch {
    /* private mode: the cart lives for this page only */
  }
  listeners.forEach((listener) => listener());
}

export const cart = {
  lines: read,
  add(sku: string, qty = 1) {
    const lines = read();
    const found = lines.find((l) => l.sku === sku);
    write(found ? lines.map((l) => (l.sku === sku ? { ...l, qty: Math.min(99, l.qty + qty) } : l)) : [...lines, { sku, qty }]);
  },
  set(sku: string, qty: number) {
    write(qty <= 0 ? read().filter((l) => l.sku !== sku) : read().map((l) => (l.sku === sku ? { ...l, qty: Math.min(99, qty) } : l)));
  },
  remove(sku: string) {
    write(read().filter((l) => l.sku !== sku));
  },
  clear() {
    write([]);
  },
};

const EMPTY: CartLine[] = [];

export function useCart(): CartLine[] {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      const onStorage = (event: StorageEvent) => {
        if (event.key === KEY) {
          cache = null;
          listener();
        }
      };
      window.addEventListener("storage", onStorage);
      return () => {
        listeners.delete(listener);
        window.removeEventListener("storage", onStorage);
      };
    },
    read,
    () => EMPTY,
  );
}
