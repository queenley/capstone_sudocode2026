// The storefront's view of the Commerce catalog (`GET /api/catalog`).
//
// The API returns one row per sellable SKU; products with sizes or colours
// have one row per variant, all sharing the product's `product_ref`. The shop
// shows products, so rows are grouped here.
import { api, CommerceCatalogItem, ImageCredit } from "@/services/api";

export type CatalogRow = CommerceCatalogItem & { product_ref: string | null };

export type ShopProduct = {
  ref: string;
  name: string;
  brand: string;
  category: string;
  description: string | null;
  image: string | null;
  imageCredit: ImageCredit | null;
  variants: CatalogRow[];
  /** The cheapest sale price among the variants, and its list price. */
  price: number;
  listPrice: number;
  available: number;
};

export const CATEGORY_NAMES: Record<string, string> = {
  "gia-dung": "Gia dụng",
  "gia-dung/may-loc-khong-khi": "Máy lọc không khí",
  "gia-dung/may-loc-nuoc": "Máy lọc nước",
  "gia-dung/quat": "Quạt",
  "gia-dung/noi-chien": "Nồi chiên không dầu",
  "gia-dung/phu-kien": "Phụ kiện gia dụng",
  "gia-dung/combo": "Combo tiết kiệm",
  "thoi-trang": "Thời trang",
  "thoi-trang/giay": "Giày",
  "thoi-trang/ao-khoac": "Áo khoác",
  "thoi-trang/phu-kien": "Phụ kiện thời trang",
  "me-be": "Mẹ & Bé",
};

/** Top-level departments, in menu order, with their sub-categories. */
export const DEPARTMENTS: { slug: string; children: string[] }[] = [
  {
    slug: "gia-dung",
    children: [
      "gia-dung/may-loc-khong-khi",
      "gia-dung/may-loc-nuoc",
      "gia-dung/quat",
      "gia-dung/noi-chien",
      "gia-dung/phu-kien",
      "gia-dung/combo",
    ],
  },
  { slug: "thoi-trang", children: ["thoi-trang/giay", "thoi-trang/ao-khoac", "thoi-trang/phu-kien"] },
  { slug: "me-be", children: [] },
];

export function categoryName(slug: string): string {
  return CATEGORY_NAMES[slug] || slug.split("/").pop()!.replace(/-/g, " ");
}

export function money(value: number | string): string {
  return Number(value).toLocaleString("vi-VN") + "₫";
}

export function discountPercent(price: number, listPrice: number): number {
  return listPrice > price ? Math.round((1 - price / listPrice) * 100) : 0;
}

/** The catalog's colour codes (unaccented) as shoppers read them. */
const COLOR_NAMES: Record<string, string> = { den: "Đen", trang: "Trắng", xam: "Xám", be: "Be", navy: "Xanh navy" };

export function colorName(code: unknown): string {
  const key = String(code ?? "");
  return COLOR_NAMES[key.toLowerCase()] || key;
}

export function variantLabel(row: CatalogRow): string {
  const v = (row.variant || {}) as Record<string, unknown>;
  return [v.size !== undefined ? `Size ${v.size}` : "", v.color ? colorName(v.color) : ""]
    .filter(Boolean)
    .join(" · ");
}

export function groupProducts(rows: CatalogRow[]): ShopProduct[] {
  const byRef = new Map<string, ShopProduct>();
  for (const row of rows) {
    const ref = row.product_ref || row.sku_code;
    let product = byRef.get(ref);
    if (!product) {
      product = {
        ref,
        name: row.name,
        brand: row.brand,
        category: row.category,
        description: row.description,
        image: row.image_url || null,
        imageCredit: row.image_credit || null,
        variants: [],
        price: Infinity,
        listPrice: 0,
        available: 0,
      };
      byRef.set(ref, product);
    }
    product.variants.push(row);
    const price = Number(row.sale_price);
    if (price < product.price) {
      product.price = price;
      product.listPrice = Number(row.list_price);
    }
    product.available += Math.max(0, row.available);
  }
  return [...byRef.values()];
}

export async function fetchProducts(params: { q?: string; category?: string } = {}): Promise<ShopProduct[]> {
  const search = new URLSearchParams({ limit: "500" });
  if (params.q) search.set("q", params.q);
  if (params.category) search.set("category", params.category);
  return groupProducts(await api<CatalogRow[]>(`/api/catalog?${search}`));
}

/** The description's "Label: value" lines, as the seed writes them. */
export function specifications(description: string | null): [string, string][] {
  return (description || "")
    .split("\n")
    .map((line) => line.split(/:\s(.*)/s))
    .filter((parts) => parts.length >= 2 && parts[0].trim())
    .map((parts) => [parts[0].trim(), parts[1].trim()]);
}
