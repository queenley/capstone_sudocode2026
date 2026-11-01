import { test, expect, Page } from "@playwright/test";

// Every backend request is fulfilled here. This suite cannot reach a real agent.
test.use({ channel: process.env.CI ? undefined : "chrome" });
const row = {
  id: "fixture-product", product_ref: "FIXTURE-AIR", sku_code: "FIXTURE-AIR-WHITE",
  name: "Máy lọc không khí cho phòng khách", brand: "Quivo", category: "gia-dung/may-loc-khong-khi",
  description: "Diện tích: 25m²\nBảo hành: 24 tháng", image_url: null, variant: { color: "trang" },
  list_price: "3000000", sale_price: "2500000", currency: "VND", available: 2,
};
const order = {
  id: "fixture-order-001", total: "2500000", status: "confirmed", payment_method: "cod",
  payment_status: "unpaid", transfer: null, created_at: "2026-11-01T02:00:00Z",
  shipping_address: "12 Đường Thử Nghiệm, Hà Nội", items: [{ ...row, quantity: 1, unit_price: "2500000" }],
};
const errors = new WeakMap<Page, string[]>();
const unhandled = new WeakMap<Page, string[]>();

async function fixture(page: Page) {
  let verified = false;
  let messages: { speaker: string; text: string }[] = [];
  const unknown: string[] = [];
  const runtime: string[] = [];
  errors.set(page, runtime);
  unhandled.set(page, unknown);
  page.on("pageerror", error => runtime.push(error.message));
  await page.route("https://**", route => route.abort());
  await page.addInitScript(() => {
    localStorage.setItem("theme", "light");
    localStorage.setItem("shop-cart", JSON.stringify([{ sku: "FIXTURE-AIR-WHITE", qty: 1 }]));
    sessionStorage.setItem("staff-token", "synthetic-staff-token");
  });
  await page.route("**/backend/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/backend/, "");
    const json = (value: unknown, status = 200) => route.fulfill({ status, json: value });
    if (path === "/api/catalog") return json([row]);
    if (path === "/api/catalog/payment-methods") return json({ cod: { enabled: true, max_total: "10000000" }, bank_transfer: { enabled: false, bank_name: null } });
    if (path.endsWith("/quote")) return json({ ...row, total: String(Number(row.sale_price) * Number(url.searchParams.get("quantity") || 1)), discount: "500000", promotions: [] });
    if (path === `/api/catalog/${row.sku_code}`) return json(row);
    if (path === "/api/conversations") return json({ conversation_id: "fixture-conversation", conversation_token: "synthetic-conversation-token", customer_id: verified ? "fixture-customer" : null });
    if (path.endsWith("/identity/challenge")) return json({ challenge_id: "fixture-challenge", development_code: "123456", delivery: "development" });
    if (path.endsWith("/identity/verify")) { verified = true; return json({ customer_id: "fixture-customer", customer_token: "synthetic-customer-token" }); }
    if (path === "/api/customer/me") return json({ customer_id: "fixture-customer", full_name: "Khách Thử Nghiệm", phone: "0900000000", email: null, registered: false, registered_at: null });
    if (path === "/api/customer/cart") return json({ items: [{ sku: row.sku_code, qty: 1 }] });
    if (path.endsWith("/stream")) {
      messages = [{ speaker: "customer", text: request.postDataJSON().message }, { speaker: "assistant", text: "Đây là câu trả lời giả dùng để kiểm tra giao diện." }];
      return route.fulfill({ contentType: "text/event-stream", body: 'event: done\ndata: {"reply":"Đây là câu trả lời giả dùng để kiểm tra giao diện.","status":"open"}\n\n' });
    }
    if (path === "/api/conversations/fixture-conversation") return json({ messages, status: "open", customer_id: verified ? "fixture-customer" : null });
    if (path === "/api/conversations/fixture-conversation/orders") return json(order, 201);
    if (path === "/api/customer/orders") return json([order]);
    if (path === "/api/seller/orders") return json([order]);
    if (path === "/api/agent/calls" || path === "/api/agent/callbacks") return json([]);
    if (path === "/api/agent/welcome") return json({ returning: false, name: null, blocker: null, expires_at: new Date(Date.now() + 30_000).toISOString() });
    unknown.push(`${request.method()} ${path}`);
    return json({ detail: "Unmocked request blocked by frontend fixture" }, 404);
  });
}

test.beforeEach(async ({ page }) => fixture(page));
test.afterEach(async ({ page }) => {
  expect(errors.get(page), "browser runtime errors").toEqual([]);
  expect(unhandled.get(page), "all backend requests must have a fixture").toEqual([]);
});

for (const width of [320, 390, 768, 1440]) {
  test(`priority routes fit ${width}px in light and dark themes`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/", "/danh-muc/gia-dung", "/san-pham/FIXTURE-AIR", "/gio-hang", "/thanh-toan", "/don-hang", "/calls", "/ban-hang?tab=orders"]) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      await expect(page.locator(".s-skeleton, .s-skeleton-block")).toHaveCount(0);
      for (const theme of ["light", "dark"]) {
        await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${path} / ${theme} / ${width}px`).toBe(true);
        if ((width === 390 && ["/gio-hang", "/thanh-toan"].includes(path)) || (width === 1440 && ["/", "/ban-hang?tab=orders"].includes(path))) await page.screenshot({ path: test.info().outputPath(`${path.replace(/[^a-z]/gi, "") || "home"}-${width}-${theme}.png`), fullPage: true });
      }
    }
  });
}

test("skip link, mobile menu, chat focus, Escape and IME are keyboard usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Đến nội dung chính" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#shop-content")).toBeFocused();
  const menu = page.getByRole("button", { name: "Danh mục", exact: true });
  await menu.click();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("navigation", { name: "Danh mục sản phẩm" }).getByRole("link").first().focus();
  await page.keyboard.press("Escape");
  await expect(menu).toBeFocused();
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  const trigger = page.getByRole("button", { name: "Chat với trợ lý", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Trò chuyện với cửa hàng" });
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("Tin nhắn", { exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Đóng", exact: true }).focus();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "Gọi thoại", exact: true })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate(element => element.matches(":modal"))).toBe(true);
  const input = page.getByLabel("Tin nhắn", { exact: true });
  await input.focus();
  // Native modal dialogs make background controls inert, including programmatic focus.
  await page.getByRole("link", { name: "Quivo, trang chủ", includeHidden: true }).evaluate((element: HTMLElement) => element.focus());
  await expect(input).toBeFocused();
  await input.fill("giá sản phẩm");
  await input.dispatchEvent("keydown", { key: "Enter", isComposing: true });
  await expect(input).toHaveValue("giá sản phẩm");
  await input.press("Enter");
  await expect(dialog.locator(".s-msg-assistant").last()).toContainText("Đây là câu trả lời giả");
  await dialog.screenshot({ path: test.info().outputPath("chat-mobile.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  const otherTrigger = page.getByRole("button", { name: "Chat với trợ lý AI", exact: true });
  await otherTrigger.click();
  await page.getByRole("button", { name: "Đóng", exact: true }).click();
  await expect(otherTrigger).toBeFocused();
});

test("microphone denial stays in an accessible nested dialog and returns to chat", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException("Synthetic denial", "NotAllowedError"); };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Chat với trợ lý", exact: true }).click();
  const launch = page.getByRole("button", { name: "Gọi thoại", exact: true });
  await launch.click();
  const voice = page.getByRole("dialog", { name: "Cuộc gọi thoại", exact: true });
  await expect(voice.getByRole("alert")).toContainText("Trình duyệt chưa cho phép dùng micro");
  await voice.screenshot({ path: test.info().outputPath("voice-permission-error.png") });
  await page.keyboard.press("Escape");
  await expect(voice).toHaveCount(0);
  await expect(launch).toBeFocused();
});

test("catalog and cart recover from temporary errors without declaring products removed", async ({ page }) => {
  let failed = true;
  await page.route("**/backend/api/catalog?*", route => failed ? route.fulfill({ status: 503, json: { detail: "Tạm mất kết nối" } }) : route.fallback());
  await page.goto("/danh-muc/gia-dung");
  await expect(page.getByRole("alert").filter({ hasText: "Tạm mất kết nối" })).toBeVisible();
  await expect(page.locator(".s-skeleton")).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Thử lại", exact: true }).click();
  await expect(page.locator(".s-card-title")).toHaveText(row.name);
  let cartFailed = true;
  await page.route(`**/backend/api/catalog/${row.sku_code}`, route => cartFailed ? route.fulfill({ status: 503, json: { detail: "Temporary fixture failure" } }) : route.fallback());
  await page.goto("/gio-hang");
  await expect(page.getByRole("alert").filter({ hasText: "Giỏ hàng của bạn vẫn được giữ lại" })).toBeVisible();
  await expect(page.getByText(/không còn bán/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Tiến hành đặt hàng" })).toBeDisabled();
  cartFailed = false;
  await page.getByRole("button", { name: "Thử lại", exact: true }).click();
  await expect(page.getByRole("link", { name: "Tiến hành đặt hàng" })).toBeVisible();
  const decrease = page.getByRole("button", { name: /^Giảm số lượng/ });
  const increase = page.getByRole("button", { name: /^Tăng số lượng/ });
  await expect(decrease).toBeDisabled();
  await increase.click();
  await expect(increase).toBeDisabled();
  await expect(page.locator(".s-qty span")).toHaveText("2");
});

test("adding a product gives feedback and filtered empty results offer recovery", async ({ page }) => {
  await page.goto("/danh-muc/gia-dung");
  await page.getByRole("button", { name: `Thêm ${row.name} vào giỏ` }).click();
  await expect(page.getByRole("status").filter({ hasText: "Đã thêm 1" })).toBeVisible();
  await page.getByRole("radio", { name: "Dưới 1 triệu" }).check();
  await expect(page.locator(".s-card")).toHaveCount(0);
  await page.getByRole("button", { name: "Xóa bộ lọc" }).click();
  await expect(page.locator(".s-card")).toHaveCount(1);
});

test("checkout guides required steps, focuses OTP and guards duplicate submission", async ({ page }) => {
  await page.goto("/thanh-toan");
  await expect(page.locator("#checkout-help")).toContainText("Hoàn tất xác minh");
  await page.getByLabel("Số điện thoại", { exact: true }).fill("0900000000");
  await page.getByRole("checkbox", { name: /Tôi đồng ý để cửa hàng/ }).check();
  await page.getByRole("button", { name: "Gửi mã xác minh" }).click();
  await expect(page.getByLabel("Mã xác minh", { exact: true })).toBeFocused();
  await page.getByLabel("Mã xác minh", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Xác minh", exact: true }).click();
  await expect(page.getByText("Số điện thoại đã được xác minh")).toBeVisible();
  await expect(page.locator("#checkout-help")).toContainText("Nhập địa chỉ");
  await page.getByLabel(/Địa chỉ nhận hàng/).fill(order.shipping_address);
  await expect(page.locator("#checkout-help")).toContainText("Đánh dấu xác nhận");
  await page.getByRole("checkbox", { name: /Tôi đã kiểm tra sản phẩm/ }).check();
  let submitted = 0;
  page.on("request", request => { if (request.method() === "POST" && request.url().endsWith("/orders")) submitted++; });
  await page.getByRole("button", { name: /^Đặt hàng ·/ }).evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await expect(page.getByRole("heading", { name: "Đặt hàng thành công" })).toBeFocused();
  expect(submitted).toBe(1);
});

test("staff can open order details with the keyboard and filter by a labelled field", async ({ page }) => {
  await page.goto("/ban-hang?tab=orders");
  const disclosure = page.getByRole("button", { name: /^Chi tiết đơn/ });
  await disclosure.focus();
  await page.keyboard.press("Enter");
  await expect(disclosure).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".sl-detail")).toContainText(order.shipping_address);
  await page.getByLabel("Tìm đơn hàng", { exact: true }).fill("không tồn tại");
  await expect(page.getByRole("status")).toHaveText("0 đơn");
});

test("missing routes have a branded recovery page", async ({ page }) => {
  await page.goto("/fixture-missing-page");
  await expect(page.getByRole("heading", { name: "Trang này chưa có ở Quivo" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Về cửa hàng", exact: true })).toHaveAttribute("href", "/");
});

test("shared text, primary button and field borders meet contrast targets in both themes", async ({ page }) => {
  await page.goto("/");
  for (const theme of ["light", "dark"]) {
    const ratios = await page.evaluate(theme => {
      document.documentElement.dataset.theme = theme;
      const probe = document.createElement("span");
      document.body.append(probe);
      const rgb = (token: string) => {
        probe.style.color = `var(${token})`;
        return getComputedStyle(probe).color.match(/[\d.]+/g)!.slice(0, 3).map(Number);
      };
      const luminance = (rgb: number[]) => rgb.map(value => {
        const normalized = value / 255;
        return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
      const contrast = (a: string, b: string) => {
        const first = luminance(rgb(a)), second = luminance(rgb(b));
        return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
      };
      const result = { primary: contrast("--on-brand", "--brand"), primaryHover: contrast("--on-brand", "--brand-strong"), body: contrast("--ink", "--surface"), muted: contrast("--muted", "--surface-2"), fieldBorder: contrast("--line-strong", "--surface") };
      probe.remove();
      return result;
    }, theme);
    for (const key of ["primary", "primaryHover", "body", "muted"] as const) expect(ratios[key], `${theme} ${key}`).toBeGreaterThanOrEqual(4.5);
    expect(ratios.fieldBorder, `${theme} field boundary`).toBeGreaterThanOrEqual(3);
  }
});

test("new cart SKUs stay pending until loaded and only a 404 is shown as removed", async ({ page }) => {
  await page.goto("/gio-hang");
  await expect(page.getByRole("link", { name: "Tiến hành đặt hàng" })).toBeVisible();
  let release!: () => void;
  let started!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const loading = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/backend/api/catalog/FIXTURE-SECOND", async route => {
    started();
    await pending;
    await route.fulfill({ json: { ...row, sku_code: "FIXTURE-SECOND", name: "Sản phẩm thứ hai" } });
  });
  await page.evaluate(() => {
    localStorage.setItem("shop-cart", JSON.stringify([{ sku: "FIXTURE-AIR-WHITE", qty: 1 }, { sku: "FIXTURE-SECOND", qty: 1 }]));
    window.dispatchEvent(new StorageEvent("storage", { key: "shop-cart" }));
  });
  await loading;
  await expect(page.getByText(/không còn bán/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Tiến hành đặt hàng" })).toBeDisabled();
  release();
  await expect(page.getByText("Sản phẩm thứ hai", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Tiến hành đặt hàng" })).toBeVisible();
  await page.route("**/backend/api/catalog/FIXTURE-REMOVED", route => route.fulfill({ status: 404, json: { detail: "Removed synthetic SKU" } }));
  await page.evaluate(() => {
    localStorage.setItem("shop-cart", JSON.stringify([{ sku: "FIXTURE-REMOVED", qty: 1 }]));
    window.dispatchEvent(new StorageEvent("storage", { key: "shop-cart" }));
  });
  await expect(page.getByText("Sản phẩm FIXTURE-REMOVED không còn bán", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tiến hành đặt hàng" })).toBeDisabled();
});

test("checkout respects disabled COD and selects an available payment method", async ({ page }) => {
  await page.route("**/backend/api/catalog/payment-methods", route => route.fulfill({ json: { cod: { enabled: false, max_total: "10000000" }, bank_transfer: { enabled: true, bank_name: "Fixture Bank" } } }));
  await page.goto("/thanh-toan");
  await expect(page.getByRole("radio").last()).toBeChecked();
  await expect(page.getByText("Cửa hàng chưa mở COD", { exact: true })).toBeVisible();
});

test("a populated copilot console stays readable on mobile and desktop", async ({ page }) => {
  const call = {
    id: 1, conversation_id: "fixture-conversation", customer_id: null,
    customer_label: "Khách đang cần tư vấn máy lọc không khí cho phòng có trẻ nhỏ", phone_last4: null,
    channel: "web", channel_ref: null, tier: "UNKNOWN", lane: "NEW", route_reason: null,
    mode: "copilot", brief: [], brief_object: null, warnings: [], business_day: "2026-11-01",
    started_at: "2026-11-01T02:00:00Z", ended_at: null, turn_count: 1,
    handoff_status: "accepted", handoff_reason: "Khách cần gặp nhân viên", handoff_brief: null,
    accepted_by: "fixture-staff", held_by_you: true, memory_status: null, after_call: null,
    suggestion: { text: "Anh/chị cho em biết diện tích phòng để chọn máy phù hợp nhé.", used_lines: [] },
    turns: [{ id: 1, turn_id: "fixture-turn", speaker: "customer", content: "Tôi cần chọn máy lọc cho phòng có trẻ nhỏ, nhờ nhân viên tư vấn thêm giúp tôi.", meta: {}, created_at: "2026-11-01T02:00:00Z" }],
  };
  await page.route("**/backend/api/agent/calls**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/context")) return route.fulfill({ json: { identity_confirmed: false, memory_status: null, facts: [], episodes: [], orders: [] } });
    return route.fulfill({ json: path.endsWith("/calls") ? [call] : call });
  });
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/calls");
    await page.getByRole("button", { name: "Kết nối", exact: true }).click();
    await expect(page.getByLabel("Trả lời khách", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Gửi nguyên văn", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect(await page.locator(".message p").evaluate(element => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(14);
    if (width === 390) {
      const label = await page.locator(".authbar .check").boundingBox();
      const refresh = await page.getByRole("button", { name: "Làm mới", exact: true }).boundingBox();
      expect(refresh!.y).toBeGreaterThanOrEqual(label!.y + label!.height);
    }
    await page.getByRole("button", { name: "Làm mới", exact: true }).focus();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: test.info().outputPath(`copilot-${width}.png`), fullPage: true });
  }
});
