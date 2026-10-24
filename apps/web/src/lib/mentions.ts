// The products an assistant message names, so the chat can show each one
// under the message: picture, price, link. Read from the text itself, so a
// message reloaded from the conversation's history (which keeps text only)
// shows them as well as one just streamed.
//
// A product is named by its full catalogue name ("Máy lọc nước RO Karofi 9
// lõi") or from its brand on ("Karofi 9 lõi", "AirPure X"), the way the
// assistant shortens it; never by the brand alone. Longer names are matched
// first, so "AirPure X/Y" (a filter) is not also read as "AirPure X". Case is
// ignored, word edges are respected; discontinued products are not offered.
import { fetchProducts, ShopProduct } from "@/lib/catalog";

let catalog: Promise<ShopProduct[]> | null = null;

/** The shop's products, fetched once per page and shared by every message. */
export function catalogOnce(): Promise<ShopProduct[]> {
  if (!catalog) {
    catalog = fetchProducts().catch((error) => {
      catalog = null; // try again on the next message
      throw error;
    });
  }
  return catalog;
}

type Key = { text: string; product: ShopProduct };

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Accessories and bundles share a model's short name ("Màng lọc thay thế AirPure Pro"). */
const SECONDARY = /phu-kien|combo/;

function keys(products: ShopProduct[]): Key[] {
  const found: Key[] = [];
  const shorts = new Map<string, ShopProduct[]>();
  for (const product of products) {
    if (/ngừng bán/i.test(product.name)) continue;
    found.push({ text: product.name.trim(), product });
    const at = product.brand ? product.name.toLowerCase().indexOf(product.brand.toLowerCase()) : -1;
    if (at > 0) {
      const short = product.name.slice(at).trim();
      if (short.length > product.brand.length + 1) {
        const lower = short.toLowerCase();
        shorts.set(lower, [...(shorts.get(lower) || []), product]);
      }
    }
  }
  // A short name several products share means the main one (not an accessory
  // or a bundle); when that is still not one product, only full names count.
  for (const [short, owners] of shorts) {
    const main = owners.length === 1 ? owners : owners.filter((p) => !SECONDARY.test(p.category));
    if (main.length === 1) found.push({ text: short, product: main[0] });
  }
  return found.sort((a, b) => b.text.length - a.text.length);
}

let cachedFor: ShopProduct[] | null = null;
let cachedKeys: Key[] = [];

/** The products *text* names, in the order it names them, at most *max*. */
export function productMentions(text: string, products: ShopProduct[], max = 4): ShopProduct[] {
  if (!text || !products.length) return [];
  if (cachedFor !== products) {
    cachedFor = products;
    cachedKeys = keys(products);
  }
  const taken: [number, number][] = [];
  const hits: { at: number; product: ShopProduct }[] = [];
  for (const key of cachedKeys) {
    const pattern = new RegExp(`(?<![\\p{L}\\p{N}])${escape(key.text)}(?![\\p{L}\\p{N}])`, "giu");
    for (const match of text.matchAll(pattern)) {
      const start = match.index ?? 0;
      const end = start + match[0].length;
      if (taken.some(([s, e]) => start < e && end > s)) continue; // inside a longer name already read
      taken.push([start, end]);
      hits.push({ at: start, product: key.product });
    }
  }
  const seen = new Set<string>();
  return hits
    .sort((a, b) => a.at - b.at)
    .map((hit) => hit.product)
    .filter((product) => !seen.has(product.ref) && seen.add(product.ref))
    .slice(0, max);
}
