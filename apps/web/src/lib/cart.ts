// The shopping cart, kept in this browser (localStorage) and shared by every
// component through useCart(). Prices are not stored: each is re-quoted from
// the Commerce API when the cart or checkout is shown.
//
// Signed in (lib/account.ts), the cart is also the account's on the server
// (`/api/customer/cart`): on login the browser's lines are merged into it, and
// every change is saved back, so it follows the shopper to another device and
// the assistant can read it. Signing out empties this browser's copy.
import { useSyncExternalStore } from "react";
import { api } from "@/services/api";

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

let serverToken = "";
let saveTimer: ReturnType<typeof setTimeout> | null = null;

function save() {
  if (!serverToken) return;
  if (saveTimer) clearTimeout(saveTimer);
  const token = serverToken;
  saveTimer = setTimeout(() => {
    api("/api/customer/cart", token, { items: read() }, "PUT").catch(() => undefined);
  }, 400);
}

function write(lines: CartLine[], toServer = true) {
  cache = lines;
  try {
    localStorage.setItem(KEY, JSON.stringify(lines));
  } catch {
    /* private mode: the cart lives for this page only */
  }
  listeners.forEach((listener) => listener());
  if (toServer) save();
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
  /** Signed in: merge this browser's lines into the account's cart (the larger quantity wins) and keep them in step. */
  async attach(token: string) {
    serverToken = token;
    try {
      const saved = await api<{ items: CartLine[] }>("/api/customer/cart", token);
      const merged = new Map(saved.items.map((l) => [l.sku, l.qty]));
      for (const l of read()) merged.set(l.sku, Math.max(l.qty, merged.get(l.sku) || 0));
      const lines = [...merged].map(([sku, qty]) => ({ sku, qty }));
      write(lines, false);
      if (lines.length !== saved.items.length || lines.some((l, i) => l.qty !== saved.items[i]?.qty || l.sku !== saved.items[i]?.sku)) {
        const stored = await api<{ items: CartLine[] }>("/api/customer/cart", token, { items: lines }, "PUT");
        write(stored.items, false); // codes the shop no longer sells are dropped by the server
      }
    } catch {
      /* the cart stays local until the next page load */
    }
  },
  /** Signed out: the account's cart stays on the server, this browser forgets it. */
  detach() {
    serverToken = "";
    if (saveTimer) clearTimeout(saveTimer);
    write([], false);
  },
  signedIn(): boolean {
    return Boolean(serverToken);
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
