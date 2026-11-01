import { test, expect } from "@playwright/test";

// Requires tests/offline_api.py. Never point this opt-in test at a real account backend.
test.skip(process.env.RUN_OFFLINE_WELCOME !== "1", "Requires the dedicated offline API fixture");
test.use({ channel: process.env.CI ? undefined : "chrome" });

test("real BFF and authenticated welcome contract render the synthetic ledger without model work", async ({ page }) => {
  const errors: string[] = [];
  const sideEffects: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (/\/(stream|turns|voice)(\?|$)/.test(request.url())) sideEffects.push(request.url());
  });
  await page.route("https://**", route => route.abort());
  const denied = await page.request.get("/backend/api/agent/welcome");
  expect(denied.status()).toBe(401);
  const start = await page.request.post("/backend/api/customer/register/start", { data: {
    full_name: "Khách Offline Welcome", phone: `090${Date.now().toString().slice(-7)}`, password: "offline-fixture-pass",
  } });
  expect(start.ok()).toBe(true);
  const challenge = await start.json();
  expect(challenge.development_code).toBeTruthy();
  const verified = await page.request.post("/backend/api/customer/register/verify", { data: { challenge_id: challenge.challenge_id, code: challenge.development_code } });
  expect(verified.ok()).toBe(true);
  const session = await verified.json();
  await page.goto("/");
  await page.evaluate(token => localStorage.setItem("customer-token", token), session.customer_token);
  await page.reload();
  const popup = page.getByRole("complementary", { name: /Chào mừng/ });
  await expect(popup).toContainText("Khách Offline Welcome");
  await expect(popup).toContainText("cần hỏi người nhà");
  await page.getByRole("button", { name: "Tiếp tục tư vấn" }).click();
  await expect(page.getByRole("dialog", { name: "Trò chuyện với cửa hàng" })).toBeVisible();
  await expect(page.locator(".s-msg")).toHaveCount(0);
  await expect(page.getByLabel("Tin nhắn", { exact: true })).toBeFocused();
  expect(sideEffects).toEqual([]);
  expect(errors).toEqual([]);
});
