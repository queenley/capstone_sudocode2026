import { test, expect, Page, Route } from "@playwright/test";

test.use({ channel: process.env.CI ? undefined : "chrome" });
const person = (id = "A") => ({ customer_id: id, full_name: `Khách ${id}`, phone: "0900000000", email: null, registered: true, registered_at: null });
const greeting = (name = "Khách An", blocker = "cần hỏi người nhà") => ({
  returning: true, name, blocker: { text: blocker, valid_until: new Date(Date.now() + 60_000).toISOString() }, expires_at: new Date(Date.now() + 30_000).toISOString(),
});
const empty = () => ({ returning: false, name: null, blocker: null, expires_at: new Date(Date.now() + 30_000).toISOString() });
const panel = (page: Page) => page.getByRole("complementary", { name: /Chào mừng|Trợ lý luôn/ });
const json = (route: Route, value: unknown, status = 200) => route.fulfill({ json: value, status });

async function fixture(page: Page, signedIn = true) {
  const requests: string[] = [];
  const unknown: string[] = [];
  const errors: string[] = [];
  let revoked = false;
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://**", route => route.abort());
  if (signedIn) await page.addInitScript(() => { if (!localStorage.getItem("fixture-initialized")) { localStorage.setItem("customer-token", "token-A"); localStorage.setItem("fixture-initialized", "1"); } });
  await page.route("**/backend/**", route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/backend/, "");
    requests.push(`${request.method()} ${path}`);
    if (path === "/api/agent/welcome") return json(route, greeting());
    if (path === "/api/customer/me") return json(route, revoked ? { detail: "revoked" } : person(request.headers().authorization === "Bearer token-B" ? "B" : "A"), revoked ? 401 : 200);
    if (path === "/api/customer/cart") return json(route, { items: [] });
    if (path === "/api/customer/orders") return json(route, []);
    if (path === "/api/customer/logout") { revoked = true; return json(route, {}); }
    if (path === "/api/customer/data") { revoked = true; return json(route, { agent_data_status: "pending", deletion_id: "fixture-deletion", deletion_token: "fixture-receipt" }); }
    if (path === "/api/customer/deletions/fixture-deletion") return json(route, { status: "pending" });
    if (path === "/api/catalog") return json(route, []);
    if (path === "/api/conversations") return json(route, { conversation_id: "fixture-conversation", conversation_token: "fixture-token", customer_id: "A" });
    if (path === "/api/conversations/fixture-conversation") return json(route, { messages: [{ speaker: "customer", text: "Câu hỏi đã lưu" }], status: "open", customer_id: "A" });
    unknown.push(`${request.method()} ${path}`);
    return json(route, { detail: "Unmocked route blocked" }, 404);
  });
  return { requests, check: () => { expect(unknown).toEqual([]); expect(errors).toEqual([]); } };
}

test("anonymous browsers never request or show personal memory", async ({ page }) => {
  const f = await fixture(page, false);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Chat với trợ lý", exact: true })).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
  expect(f.requests.some(path => path.includes("welcome"))).toBe(false);
  f.check();
});

test("welcome loads without a call, dismisses by keyboard and stays dismissed across navigation/reload", async ({ page }) => {
  const f = await fixture(page);
  await page.goto("/");
  await expect(panel(page)).toContainText("Chào mừng Khách An quay lại!");
  await expect(panel(page)).toContainText("cần hỏi người nhà");
  await page.screenshot({ path: test.info().outputPath("returning-desktop.png") });
  await expect(page.getByRole("button", { name: "Đóng lời chào" })).not.toBeFocused();
  expect(f.requests.filter(path => /conversations|stream|turns|orders/.test(path))).toEqual([]);
  await page.getByRole("button", { name: "Đóng lời chào" }).focus();
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Chat với trợ lý", exact: true })).toBeFocused();
  await page.getByRole("link", { name: "Tài khoản của tôi" }).click();
  await expect(page).toHaveURL(/tai-khoan/);
  await expect(panel(page)).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Tài khoản của tôi" })).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
  expect(f.requests.filter(path => path.endsWith("/welcome"))).toHaveLength(1);
  f.check();
});

test("continue resumes the owned conversation without sending a message and returns focus to the launcher", async ({ page }) => {
  const f = await fixture(page);
  await page.addInitScript(() => {
    sessionStorage.setItem("conversation", JSON.stringify({ conversation_id: "fixture-conversation", conversation_token: "fixture-token", customer_id: "A" }));
    sessionStorage.setItem("conversation-customer", "token-A");
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Tiếp tục tư vấn" }).click();
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "Trò chuyện với cửa hàng" })).toBeVisible();
  await expect(page.locator(".s-msg")).toContainText("Câu hỏi đã lưu");
  expect(f.requests.filter(path => path.startsWith("POST"))).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Chat với trợ lý", exact: true })).toBeFocused();
  f.check();
});

test("switching away and back does not repeat a welcome already shown to that account", async ({ page }) => {
  const f = await fixture(page);
  await page.goto("/");
  await expect(panel(page)).toBeVisible();
  for (const token of ["token-B", "token-A"]) {
    await page.evaluate(token => {
      const oldValue = localStorage.getItem("customer-token");
      localStorage.setItem("customer-token", token);
      window.dispatchEvent(new StorageEvent("storage", { key: "customer-token", oldValue, newValue: token }));
    }, token);
    if (token === "token-B") await expect(panel(page)).toBeVisible();
    else await expect(panel(page)).toHaveCount(0);
  }
  expect(f.requests.filter(path => path.endsWith("/welcome"))).toHaveLength(2);
  f.check();
});

test("same-tab logout cancels a delayed personal welcome", async ({ page }) => {
  const f = await fixture(page);
  let release!: () => void;
  const pending = new Promise<void>(r => release = r);
  await page.route("**/backend/api/agent/welcome", async route => { await pending; return json(route, greeting("Tên cũ sau logout")); });
  await page.goto("/tai-khoan");
  await page.getByRole("button", { name: "Đăng xuất", exact: true }).click();
  release();
  await expect(page).toHaveURL(/\/$/);
  await expect(panel(page)).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("Tên cũ sau logout");
  f.check();
});

test("a delayed welcome cannot follow logout or be shown on another account", async ({ page }) => {
  const f = await fixture(page);
  let release!: () => void;
  let started!: () => void;
  const pending = new Promise<void>(r => release = r);
  const requested = new Promise<void>(r => started = r);
  await page.route("**/backend/api/agent/welcome", async route => {
    if (route.request().headers().authorization === "Bearer token-A") {
      started(); await pending; return json(route, greeting("Tên cũ bí mật", "blocker bí mật"));
    }
    return json(route, greeting("Khách Bình", "so sánh giá"));
  });
  await page.goto("/");
  await requested;
  await page.evaluate(() => {
    localStorage.setItem("customer-token", "token-B");
    window.dispatchEvent(new StorageEvent("storage", { key: "customer-token", oldValue: "token-A", newValue: "token-B" }));
  });
  await expect(panel(page)).toContainText("Khách Bình");
  release();
  await expect(panel(page)).not.toContainText("Tên cũ bí mật");
  await page.evaluate(() => {
    localStorage.removeItem("customer-token");
    window.dispatchEvent(new StorageEvent("storage", { key: "customer-token", oldValue: "token-B", newValue: null }));
  });
  await expect(panel(page)).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("blocker bí mật");
  f.check();
});

test("deleting data cancels an in-flight welcome before the delete response", async ({ page }) => {
  const f = await fixture(page);
  let releaseWelcome!: () => void;
  let releaseDelete!: () => void;
  let started!: () => void;
  const pendingWelcome = new Promise<void>(r => releaseWelcome = r);
  const pendingDelete = new Promise<void>(r => releaseDelete = r);
  const deleteStarted = new Promise<void>(r => started = r);
  await page.route("**/backend/api/agent/welcome", async route => { await pendingWelcome; return json(route, greeting("Tên đã xóa", "Chuyện đã xóa")); });
  await page.route("**/backend/api/customer/data", async route => { started(); await pendingDelete; return json(route, { agent_data_status: "pending", deletion_id: "fixture-deletion", deletion_token: "fixture-receipt" }); });
  page.on("dialog", dialog => dialog.accept());
  await page.goto("/don-hang");
  await page.getByRole("button", { name: "Xóa dữ liệu cá nhân của tôi" }).click();
  await deleteStarted;
  releaseWelcome();
  await expect(panel(page)).toHaveCount(0);
  releaseDelete();
  await expect(page.locator("body")).toContainText("Kho của trợ lý đang tiếp tục xử lý");
  await expect(page.locator("body")).not.toContainText("Tên đã xóa");
  await page.reload();
  await expect(panel(page)).toHaveCount(0);
  f.check();
});

test("pending/deleted memory has no popup; a revoked token drops the account", async ({ page }) => {
  const f = await fixture(page);
  await page.route("**/backend/api/agent/welcome", route => json(route, empty()));
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Tài khoản của tôi" })).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
  await page.route("**/backend/api/customer/me", route => json(route, { detail: "revoked" }, 401));
  await page.route("**/backend/api/agent/welcome", route => json(route, { detail: "revoked" }, 401));
  await page.reload();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("customer-token"))).toBeNull();
  await expect(panel(page)).toHaveCount(0);
  f.check();
});

test("slow/error welcome keeps chat usable and retry never exposes server error details", async ({ page }) => {
  const f = await fixture(page);
  let release!: () => void;
  const pending = new Promise<void>(r => release = r);
  let attempt = 0;
  await page.route("**/backend/api/agent/welcome", async route => {
    if (attempt++ === 0) { await pending; return json(route, { detail: "private server detail" }, 503); }
    return json(route, greeting());
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Chat với trợ lý", exact: true })).toBeEnabled();
  await expect(panel(page)).toHaveCount(0);
  release();
  await expect(panel(page)).toContainText("Chưa tải được phần tư vấn trước");
  await expect(panel(page)).not.toContainText("private server detail");
  await page.getByRole("button", { name: "Thử lại", exact: true }).click();
  await expect(panel(page)).toContainText("Khách An");
  f.check();
});

test("expired responses and blur cannot leave old personal information visible", async ({ page }) => {
  const f = await fixture(page);
  let attempt = 0;
  await page.route("**/backend/api/agent/welcome", route => json(route, attempt++ === 0 ? { ...greeting(), expires_at: new Date(Date.now() + 800).toISOString() } : empty()));
  await page.goto("/");
  await expect(panel(page)).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(panel(page)).toHaveCount(0);
  f.check();
});

test("long untrusted text remains inert and readable on mobile in both themes", async ({ page }) => {
  const f = await fixture(page);
  await page.setViewportSize({ width: 320, height: 640 });
  const hostile = '<img src=x onerror="window.pwned=true">';
  await page.route("**/backend/api/agent/welcome", route => json(route, greeting(hostile + "Tên rất dài ".repeat(10), hostile + "cân nhắc ".repeat(35))));
  await page.goto("/");
  await expect(panel(page)).toContainText(hostile);
  await expect(panel(page).locator("img,script")).toHaveCount(0);
  expect(await page.evaluate(() => (window as typeof window & { pwned?: boolean }).pwned)).toBeUndefined();
  for (const theme of ["light", "dark"]) {
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const box = await panel(page).boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(320);
    await page.getByRole("button", { name: "Tiếp tục tư vấn" }).scrollIntoViewIfNeeded();
    expect(await page.locator(".s-returning-content").evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    await expect(page.getByRole("button", { name: "Đóng lời chào" })).toBeInViewport();
    await page.screenshot({ path: test.info().outputPath(`returning-320-${theme}.png`) });
  }
  await page.getByRole("button", { name: "Đóng lời chào" }).click();
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(f.requests.filter(path => /conversations|stream|turns/.test(path))).toEqual([]);
  f.check();
});

test("mobile welcome keeps the close action and continue button in view", async ({ page }) => {
  const f = await fixture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(panel(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "Đóng lời chào" })).toBeInViewport();
  expect(await page.getByRole("button", { name: "Đóng lời chào" }).evaluate(element => getComputedStyle(element).color)).not.toBe("rgb(255, 255, 255)");
  await expect(page.getByRole("button", { name: "Tiếp tục tư vấn" })).toBeInViewport();
  await page.screenshot({ path: test.info().outputPath("returning-mobile.png") });
  f.check();
});
