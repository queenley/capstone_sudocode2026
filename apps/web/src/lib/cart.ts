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
      ? parsed.filter(
          (l) =>
            typeof l?.sku === "string" && Number.isInteger(l?.qty) && l.qty > 0,
        )
      : [];
  } catch {
    cache = [];
  }
  return cache!;
}

let serverToken = "";
let generation = 0;
let revision = 0;
let saveTimer: ReturnType<typeof setTimeout> | null = null;
let saves: Promise<unknown> = Promise.resolve();

function persist(token: string, lines: CartLine[], current: number) {
  const saving = saves
    .catch(() => undefined)
    .then(() => {
      if (current !== generation || token !== serverToken) return;
      return api<{ items: CartLine[] }>(
        "/api/customer/cart",
        token,
        { items: lines },
        "PUT",
      );
    });
  saves = saving;
  return saving;
}

function save() {
  if (!serverToken) return;
  if (saveTimer) clearTimeout(saveTimer);
  const token = serverToken;
  const current = generation;
  saveTimer = setTimeout(() => {
    if (current !== generation || token !== serverToken) return;
    void persist(token, read(), current).catch(() => undefined);
  }, 400);
}

function write(lines: CartLine[], toServer = true) {
  revision++;
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
    write(
      found
        ? lines.map((l) =>
            l.sku === sku ? { ...l, qty: Math.min(99, l.qty + qty) } : l,
          )
        : [...lines, { sku, qty }],
    );
  },
  set(sku: string, qty: number) {
    write(
      qty <= 0
        ? read().filter((l) => l.sku !== sku)
        : read().map((l) =>
            l.sku === sku ? { ...l, qty: Math.min(99, qty) } : l,
          ),
    );
  },
  remove(sku: string) {
    write(read().filter((l) => l.sku !== sku));
  },
  clear() {
    write([]);
  },
  /** Signed in: merge this browser's lines into the account's cart (the larger quantity wins) and keep them in step. */
  async attach(token: string) {
    if (serverToken === token) return;
    const current = ++generation;
    serverToken = token;
    try {
      const saved = await api<{ items: CartLine[] }>(
        "/api/customer/cart",
        token,
      );
      if (current !== generation || token !== serverToken) return;
      const merged = new Map(saved.items.map((l) => [l.sku, l.qty]));
      for (const l of read())
        merged.set(l.sku, Math.max(l.qty, merged.get(l.sku) || 0));
      const lines = [...merged].map(([sku, qty]) => ({ sku, qty }));
      write(lines, false);
      const merging = revision;
      if (
        lines.length !== saved.items.length ||
        lines.some(
          (l, i) =>
            l.qty !== saved.items[i]?.qty || l.sku !== saved.items[i]?.sku,
        )
      ) {
        const stored = await persist(token, lines, current);
        if (
          stored &&
          current === generation &&
          token === serverToken &&
          merging === revision
        )
          write(stored.items, false);
      }
    } catch {
      if (current === generation && token === serverToken) serverToken = "";
    }
  },
  /** Signed out: the account's cart stays on the server, this browser forgets it. */
  detach() {
    generation++;
    serverToken = "";
    if (saveTimer) clearTimeout(saveTimer);
    write([], false);
  },
  signedIn(): boolean {
    return Boolean(serverToken);
  },
  // Invalidates a pending account merge when another tab changes this cart.
  changed() {
    revision++;
    cache = null;
  },
};

const EMPTY: CartLine[] = [];

export function useCart(): CartLine[] {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      const onStorage = (event: StorageEvent) => {
        if (event.key === KEY) {
          cart.changed();
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
