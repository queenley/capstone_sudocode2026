import { test, expect, Page } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Screenshots of every page, before and after a design change (docs/plan/UI-REDESIGN-TASTE.md).
// Every backend request is answered here from synthetic data and written down, so the
// request list of two runs can be compared: a design change must not change it.
//   SNAP_LABEL=before WEB_URL=http://127.0.0.1:3317 npx playwright test e2e/redesign-snapshots.spec.ts
// Output: $SNAP_DIR/<label>/{<route>-<width>-<theme>.png, requests.json}, by default in the
// system temp folder: Playwright empties test-results/ on every run, which would lose the "before".
test.use({ channel: process.env.CI ? undefined : "chrome" });

const LABEL = process.env.SNAP_LABEL || "current";
const OUT = path.join(process.env.SNAP_DIR || path.join(os.tmpdir(), "quivo-redesign"), LABEL);
const WIDTHS = (process.env.SNAP_WIDTHS || "1440,1024,768,390").split(",").map(Number);
const THEMES = (process.env.SNAP_THEMES || "light,dark").split(",");

type Row = { sku_code: string; list_price: string; sale_price: string } & Record<string, unknown>;
const product = (over: Row): Row => ({
  id: over.sku_code, currency: "VND", image_url: null, image_credit: null, variant: {}, available: 5, ...over,
});
const CATALOG = [
  product({ product_ref: "SNAP-AIR", sku_code: "SNAP-AIR", name: "Máy lọc không khí cho phòng ngủ", brand: "AirPure", category: "gia-dung/may-loc-khong-khi",
    description: "Diện tích phòng phù hợp (m²): 45\nBộ lọc: HEPA H13", image_url: "/products/SKU-AP-X.jpg",
    image_credit: { title: "Air purifier", author: "Synthetic", author_url: "", license: "CC BY 2.0", license_url: "", source_url: "", provider: "wikimedia" },
    list_price: "5200000", sale_price: "4890000" }),
  product({ product_ref: "SNAP-WATER", sku_code: "SNAP-WATER", name: "Máy lọc nước RO để gầm", brand: "Karofi", category: "gia-dung/may-loc-nuoc",
    description: "Công suất lọc: 10 lít/giờ", list_price: "6900000", sale_price: "6900000" }),
  product({ product_ref: "SNAP-RUN", sku_code: "SNAP-RUN-40", name: "Giày chạy bộ nhẹ", brand: "RunLite", category: "thoi-trang/giay",
    image_url: "/products/SKU-SN-RUN1.jpg", variant: { size: "40", color: "den" }, list_price: "790000", sale_price: "690000" }),
  product({ product_ref: "SNAP-RUN", sku_code: "SNAP-RUN-41", name: "Giày chạy bộ nhẹ", brand: "RunLite", category: "thoi-trang/giay",
    image_url: "/products/SKU-SN-RUN1.jpg", variant: { size: "41", color: "den" }, list_price: "790000", sale_price: "690000", available: 0 }),
  product({ product_ref: "SNAP-BABY", sku_code: "SNAP-BABY", name: "Máy hút sữa điện đôi", brand: "MomCare", category: "me-be",
    list_price: "2490000", sale_price: "2290000" }),
];
const ORDER = {
  id: "snap-order-001", total: "4890000", status: "confirmed", payment_method: "cod", payment_status: "unpaid", transfer: null,
  created_at: "2026-11-01T02:00:00Z", shipping_address: "Đường Thử Nghiệm, Hà Nội", items: [{ ...CATALOG[0], quantity: 1, unit_price: "4890000" }],
};
const CALL = {
  id: 7, conversation_id: "snap-conversation", phone_last4: "0001", channel: "web", channel_ref: null, tier: "VERIFIED", lane: "CONTINUITY",
  route_reason: "a returning customer with a brief", mode: "copilot", customer_id: "snap-customer", customer_label: "Khách Thử Nghiệm",
  brief: [{ id: "B1", text: "Lần trước (05/11): tư vấn máy lọc không khí 4.890.000₫, khách hẹn hỏi người nhà" }, { id: "B2", text: "Phòng ngủ 25m², có trẻ nhỏ" }],
  brief_object: { is_returning: true, must_not_ask: ["room_area_m2", "has_children"], suggested_opening: "Dạ em chào chị, hôm trước bên em có tư vấn máy lọc không khí cho phòng 25m² ạ.", latency_ms: 140 },
  warnings: ["Khuyến mãi đã báo lần trước hết hạn ngày 06/11"], business_day: "2026-11-07", started_at: "2026-11-07T02:00:00Z", ended_at: null,
  turn_count: 2, handoff_status: "pending", handoff_reason: "khach_yeu_cau_gap_nguoi",
  handoff_brief: { customer_name: "Khách Thử Nghiệm", escalation_reason: "khach_yeu_cau_gap_nguoi", conversation_summary: "Khách quay lại hỏi giá máy lọc không khí đã tư vấn, muốn gặp nhân viên trước khi chốt.", product_advised: "SNAP-AIR", price_quoted_vnd: 4890000, open_questions: ["Có lắp đặt tại nhà không?"], next_action: "Xác nhận giá hiện tại rồi chốt đơn" },
  accepted_by: null, held_by_you: false,
  suggestion: { text: "Dạ giá hiện tại là 4.890.000₫, chị muốn em lên đơn giao về địa chỉ cũ không ạ?", used_lines: ["B1"], warnings: [] },
  memory_status: null, after_call: null,
  turns: [
    { id: 1, turn_id: "t1", speaker: "customer", content: "Chào em, hôm trước chị hỏi máy lọc không khí.", meta: {}, created_at: "2026-11-07T02:00:05Z" },
    { id: 2, turn_id: "t1", speaker: "agent", content: "Dạ em chào chị, máy lọc không khí cho phòng 25m² hiện giá 4.890.000₫ ạ.", meta: { lane: "CONTINUITY", tool_calls: [{ name: "pricing.get_quote", result: { ok: true } }], guard: { passed: true } }, created_at: "2026-11-07T02:00:08Z" },
    { id: 3, turn_id: "t2", speaker: "customer", content: "Cho chị gặp nhân viên nhé.", meta: {}, created_at: "2026-11-07T02:00:20Z" },
  ],
};

type Logged = { route: string; method: string; path: string; body?: string };
const log: Logged[] = [];

async function fixture(page: Page, route: string, theme: string) {
  await page.route("https://**", r => r.abort());
  await page.addInitScript(([t]) => {
    localStorage.setItem("theme", t);
    localStorage.setItem("shop-cart", JSON.stringify([{ sku: "SNAP-AIR", qty: 1 }]));
    sessionStorage.setItem("staff-token", "synthetic-staff-token");
  }, [theme]);
  await page.route("**/backend/**", async r => {
    const request = r.request();
    const url = new URL(request.url());
    const p = url.pathname.replace(/^\/backend/, "");
    log.push({ route, method: request.method(), path: p + url.search, body: request.postData() || undefined });
    const json = (value: unknown, status = 200) => r.fulfill({ status, json: value });
    if (p === "/api/catalog") return json(CATALOG);
    if (p === "/api/catalog/payment-methods") return json({ cod: { enabled: true, max_total: "10000000" }, bank_transfer: { enabled: true, bank_name: "Ngân hàng Thử" } });
    const sku = /^\/api\/catalog\/([^/]+)(\/quote)?$/.exec(p);
    if (sku) {
      const row = CATALOG.find(item => item.sku_code === decodeURIComponent(sku[1])) || CATALOG[0];
      return sku[2] ? json({ ...row, total: row.sale_price, discount: String(Number(row.list_price) - Number(row.sale_price)), promotions: [{ name: "Tặng bộ lọc", description: "Tặng một bộ lọc thay thế đến hết 22/11", type: "gift" }] }) : json(row);
    }
    if (p === "/api/conversations") return json({ conversation_id: "snap-conversation", conversation_token: "synthetic-conversation-token", customer_id: "snap-customer" });
    if (p === "/api/conversations/snap-conversation") return json({ messages: [], status: "open", customer_id: "snap-customer" });
    if (p === "/api/customer/me") return json({ customer_id: "snap-customer", full_name: "Khách Thử Nghiệm", phone: "0900000001", email: null, registered: true, registered_at: "2026-10-01T00:00:00Z" });
    if (p === "/api/customer/cart") return json({ items: [{ sku: "SNAP-AIR", qty: 1 }] });
    if (p === "/api/customer/orders" || p === "/api/seller/orders") return json([ORDER]);
    if (p === "/api/agent/welcome") return json({ returning: false, name: null, blocker: null, expires_at: new Date(Date.now() + 30_000).toISOString() });
    if (p === "/api/agent/calls") return json([CALL]);
    if (p === `/api/agent/calls/${CALL.id}`) return json(CALL);
    if (p === `/api/agent/calls/${CALL.id}/context`) return json({ customer_id: "snap-customer", facts: [{ slot: "room_area_m2", value: 25, status: "active", created_at: "2026-11-05T03:00:00Z", source: { call_id: "snap-call-1", channel: "web" } }, { slot: "has_children", value: true, status: "active", created_at: "2026-11-05T03:00:00Z", source: { call_id: "snap-call-1", channel: "web" } }], episodes: [{ call_id: "snap-call-1", started_at: "2026-11-05T03:00:00Z", channel: "web", summary: "Tư vấn máy lọc không khí 4.890.000₫, khách hẹn hỏi người nhà", outcome: "hen_goi_lai" }], orders: [] });
    if (p === "/api/agent/callbacks" || p === "/api/staff/conversations" || p.startsWith("/api/admin/")) return json([]);
    if (p.startsWith("/api/developer/knowledge")) return json([]);
    if (p.startsWith("/api/developer/")) return json({});
    return json({ detail: "Not in the snapshot fixture" }, 404);
  });
}

const ROUTES = [
  ["home", "/"], ["category", "/danh-muc/gia-dung"], ["search", "/tim-kiem?q=m%C3%A1y"], ["promotions", "/khuyen-mai"],
  ["product", "/san-pham/SNAP-AIR"], ["cart", "/gio-hang"], ["checkout", "/thanh-toan"], ["orders", "/don-hang"],
  ["account", "/tai-khoan"], ["policy", "/chinh-sach"], ["login", "/login"], ["sales", "/ban-hang"], ["calls", "/calls"],
  ["seller", "/seller"], ["admin", "/admin"], ["developer", "/developer"],
];

test.afterAll(() => {
  fs.mkdirSync(OUT, { recursive: true });
  // One line per distinct request of a route: what a design change must leave alone.
  const seen = [...new Set(log.map(entry => JSON.stringify(entry)))].map(line => JSON.parse(line)).sort((a, b) =>
    `${a.route} ${a.method} ${a.path}`.localeCompare(`${b.route} ${b.method} ${b.path}`));
  fs.writeFileSync(path.join(OUT, "requests.json"), JSON.stringify(seen, null, 2));
});

test("cards show the specs a shopper chooses by, and the room filter narrows the list", async ({ page }) => {
  await fixture(page, "room-filter", "light");
  await page.goto("/danh-muc/gia-dung");
  const air = page.locator(".s-card").filter({ hasText: "Máy lọc không khí cho phòng ngủ" });
  await expect(air.getByRole("list", { name: "Thông số chính" })).toContainText("Phòng đến 45 m²");
  const count = page.getByRole("status").filter({ hasText: "sản phẩm" });
  await expect(count).not.toHaveText("Đang tải…");
  const all = await count.textContent();
  // Only the 45 m² purifier suits a 30–45 m² room; none suits a bigger one.
  await page.getByRole("radio", { name: "30 – 45 m²" }).check();
  await expect(count).toHaveText("1 sản phẩm");
  await page.getByRole("radio", { name: "Trên 45 m²" }).check();
  await expect(count).toHaveText("0 sản phẩm");
  await page.getByRole("button", { name: "Xóa bộ lọc" }).click();
  await expect(count).toHaveText(all || "");
});

test("a product the assistant names goes to the cart from the chat, and a handoff says who answers", async ({ page }) => {
  await fixture(page, "chat", "light");
  let status = "open";
  let messages: { speaker: string; text: string }[] = [];
  const reply = "Dạ, Máy lọc không khí cho phòng ngủ hợp phòng 25 m² ạ.";
  await page.route("**/backend/api/conversations/snap-conversation/stream", route => {
    messages = [{ speaker: "customer", text: route.request().postDataJSON().message }, { speaker: "assistant", text: reply }];
    return route.fulfill({ contentType: "text/event-stream", body: `event: done\ndata: ${JSON.stringify({ reply, status })}\n\n` });
  });
  await page.route("**/backend/api/conversations/snap-conversation", route => route.fulfill({ json: { messages, status, customer_id: "snap-customer" } }));
  await page.goto("/");
  await page.getByRole("button", { name: "Chat với trợ lý", exact: true }).click();
  await page.getByLabel("Tin nhắn", { exact: true }).fill("Phòng 25 m² thì chọn máy nào?");
  await page.getByLabel("Tin nhắn", { exact: true }).press("Enter");
  const add = page.getByRole("dialog").getByRole("button", { name: "Thêm Máy lọc không khí cho phòng ngủ vào giỏ" });
  await expect(add).toBeVisible();
  await add.click();
  await expect(page.getByRole("dialog").getByRole("status").filter({ hasText: "Đã thêm 1" })).toBeVisible();
  await expect(page.getByText("Đã chuyển cho nhân viên")).toHaveCount(0);

  status = "handed_off";
  await page.getByLabel("Tin nhắn", { exact: true }).fill("Cho tôi gặp nhân viên");
  await page.getByLabel("Tin nhắn", { exact: true }).press("Enter");
  await expect(page.getByText("Đã chuyển cho nhân viên")).toBeVisible();
});

test("the call console shows why a call waits, what the assistant looked up and the brief it hands over", async ({ page }) => {
  await fixture(page, "console", "light");
  await page.goto("/calls");
  await page.getByLabel("Staff access token").fill("synthetic-staff-token");
  await page.getByRole("button", { name: "Kết nối", exact: true }).click();
  await page.locator(".queue-row", { hasText: "Khách Thử Nghiệm" }).click();
  await expect(page.locator(".queue-row", { hasText: "Khách Thử Nghiệm" })).toContainText("Khách muốn gặp nhân viên");
  await expect(page.getByText("Đã tra: pricing.get_quote")).toBeVisible();
  const brief = page.getByRole("region", { name: "Handoff brief" });
  await expect(brief).toContainText("Việc cần làm ngay");
  await expect(brief).toContainText("Xác nhận giá hiện tại rồi chốt đơn");
  await expect(brief).toContainText("4.890.000₫");
  await page.screenshot({ path: path.join(OUT, "console-selected-1440-light.png"), fullPage: true });
});

// The brief's demo, call 2 (C.6), on the new interface with synthetic data: the shop greets
// the returning customer with what was left open, the assistant's product goes to the cart
// from the chat, and the staff console shows the brief and what must not be asked again.
// The agent itself (memory, tools, model) is not exercised here; run_eval.py measures that.
test("demo call 2: returning welcome, chat to cart, and the staff brief", async ({ page }) => {
  await fixture(page, "demo", "light");
  await page.addInitScript(() => localStorage.setItem("customer-token", "synthetic-customer-token"));
  await page.route("**/backend/api/agent/welcome", route => route.fulfill({ json: {
    returning: true, name: "Hoa", blocker: { text: "cần hỏi người nhà", valid_until: new Date(Date.now() + 86_400_000).toISOString() },
    expires_at: new Date(Date.now() + 30_000).toISOString(),
  } }));
  const reply = "Dạ chị Hoa, Máy lọc không khí cho phòng ngủ vẫn giá 4.890.000₫ như hôm trước ạ.";
  let messages: { speaker: string; text: string }[] = [];
  await page.route("**/backend/api/conversations/snap-conversation/stream", route => {
    messages = [{ speaker: "customer", text: route.request().postDataJSON().message }, { speaker: "assistant", text: reply }];
    return route.fulfill({ contentType: "text/event-stream", body: `event: done\ndata: ${JSON.stringify({ reply, status: "open" })}\n\n` });
  });
  await page.route("**/backend/api/conversations/snap-conversation", route => route.fulfill({ json: { messages, status: "open", customer_id: "snap-customer" } }));

  await page.goto("/");
  const welcome = page.getByRole("complementary", { name: "Chào mừng Hoa quay lại!" });
  await expect(welcome).toContainText("cần hỏi người nhà");
  await page.screenshot({ path: path.join(OUT, "demo-1-welcome.png") });
  await welcome.getByRole("button", { name: /Tiếp tục tư vấn/ }).click();
  await page.getByLabel("Tin nhắn", { exact: true }).fill("Ông xã chị đồng ý rồi, giá vẫn như hôm trước đúng không?");
  await page.getByLabel("Tin nhắn", { exact: true }).press("Enter");
  await page.getByRole("dialog").getByRole("button", { name: "Thêm Máy lọc không khí cho phòng ngủ vào giỏ" }).click();
  await page.screenshot({ path: path.join(OUT, "demo-2-chat.png") });
  await page.getByRole("dialog").getByRole("link", { name: /Xem giỏ/ }).click();
  await expect(page.getByRole("link", { name: "Tiến hành đặt hàng" })).toBeVisible();

  await page.goto("/calls");
  await page.getByLabel("Staff access token").fill("synthetic-staff-token");
  await page.getByRole("button", { name: "Kết nối", exact: true }).click();
  await page.locator(".queue-row", { hasText: "Khách Thử Nghiệm" }).click();
  // The Call Brief leads the conversation, above the transcript.
  const brief = page.locator(".call-transcript-pane .call-brief-main");
  await expect(brief).toContainText("Lần trước (05/11)");
  await expect(brief).toContainText("room_area_m2, has_children");
  await page.screenshot({ path: path.join(OUT, "demo-3-console.png"), fullPage: true });
});

for (const [name, url] of ROUTES) {
  test(`snapshot ${name}`, async ({ page }) => {
    test.setTimeout(240_000);
    fs.mkdirSync(OUT, { recursive: true });
    for (const theme of THEMES) {
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await fixture(page, name, theme);
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: width < 640 ? 844 : 900 });
        await page.goto(url, { waitUntil: "load" });
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await page.waitForTimeout(400);
        await page.screenshot({ path: path.join(OUT, `${name}-${width}-${theme}.png`), fullPage: true, animations: "disabled" });
      }
    }
  });
}
