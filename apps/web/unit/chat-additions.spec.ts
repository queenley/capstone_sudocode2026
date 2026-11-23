import { test, expect } from "@playwright/test";
import type { ShopProduct } from "../src/lib/catalog";
import { newMentions } from "../src/lib/mentions";
import { mergeStep } from "../src/components/ui/StepTrail";
import { issue, valid } from "../src/lib/zalo-mock-session";

const product = (ref: string, name: string, brand: string): ShopProduct => ({
  ref, name, brand, category: "the-thao", description: null, image: null, imageCredit: null,
  variants: [], price: 1_990_000, listPrice: 1_990_000, available: 3,
});
const CATALOG = [product("SKU-HIKE", "Giày trekking HikePro", "HikePro"), product("SKU-TENT", "Lều cắm trại TrailMax", "TrailMax")];

test("a product gets its card under the first reply that names it, not under the next ones", () => {
  const first = "Dạ em chốt giày trekking HikePro size 43 giá 2.040.000đ ạ.";
  const again = "Dạ em đã tạo đơn giày trekking HikePro size 43, mã đơn OD600003 ạ.";
  expect(newMentions(first, [], CATALOG).map((p) => p.ref)).toEqual(["SKU-HIKE"]);
  expect(newMentions(again, [first], CATALOG)).toEqual([]);
  // A new product in a later reply still gets its own card.
  expect(newMentions("Anh/chị xem thêm Lều cắm trại TrailMax nhé, và giày trekking HikePro ạ.", [first], CATALOG)
    .map((p) => p.ref)).toEqual(["SKU-TENT"]);
});

test("a step's second event updates the first instead of adding a line", () => {
  let steps = mergeStep([], { id: 1, label: "Đang tìm sản phẩm phù hợp", status: "running" });
  steps = mergeStep(steps, { id: 2, label: "Đang lấy giá và khuyến mãi", status: "running" });
  steps = mergeStep(steps, { id: 1, label: "Đang tìm sản phẩm phù hợp", status: "ok" });
  expect(steps.map((s) => [s.id, s.status])).toEqual([[1, "ok"], [2, "running"]]);
});

test("the Zalo mock's cookie holds only with the server's key and before it expires", () => {
  const before = process.env.ZALO_MOCK_SECRET;
  process.env.ZALO_MOCK_SECRET = "a-test-key-of-at-least-16";
  try {
    const now = Date.UTC(2026, 10, 22);
    const value = issue(now)!;
    expect(valid(value, now)).toBe(true);
    expect(valid(value, now + 9 * 3600 * 1000)).toBe(false); // past its 8 hours
    expect(valid(value.replace(/.$/, (c) => (c === "A" ? "B" : "A")), now)).toBe(false);
    expect(valid(`${Math.floor(now / 1000) + 3600}.forged`, now)).toBe(false);
    process.env.ZALO_MOCK_SECRET = "another-key-of-16-chars";
    expect(valid(value, now)).toBe(false);
    process.env.ZALO_MOCK_SECRET = "short";
    expect(issue(now)).toBeNull();
  } finally {
    if (before === undefined) delete process.env.ZALO_MOCK_SECRET;
    else process.env.ZALO_MOCK_SECRET = before;
  }
});
