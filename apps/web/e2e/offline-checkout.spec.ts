import { test, expect, Page } from "@playwright/test";

test.use({ channel: process.env.CI ? undefined : "chrome" });
test.skip(
  process.env.OFFLINE_STACK !== "1",
  "Requires tests/offline_api.py; never run against customer data.",
);

async function checkout(page: Page) {
  await page.route("https://**", (route) => route.abort());
  await page.addInitScript(() =>
    localStorage.setItem(
      "shop-cart",
      JSON.stringify([{ sku: "ASUS-V16-BLACK", qty: 1 }]),
    ),
  );
  await page.goto("/thanh-toan");
  await page
    .getByLabel("Số điện thoại", { exact: true })
    .fill("09" + String(Date.now()).slice(-8));
  await page.getByText("Tôi đồng ý để cửa hàng lưu").click();
  await page.getByRole("button", { name: "Gửi mã xác minh" }).click();
  const code = (await page.locator(".s-devnote b").textContent())!.trim();
  await page.getByLabel("Mã xác minh").fill(code);
  await page.getByRole("button", { name: "Xác minh", exact: true }).click();
  await expect(page.getByText("Số điện thoại đã được xác minh")).toBeVisible();
  await page
    .getByLabel(/Địa chỉ nhận hàng/)
    .fill("12 Test Street, synthetic browser fixture");
  await expect(page.getByRole("radio").last()).toBeChecked();
  await page.getByText("Tôi đã kiểm tra sản phẩm").click();
}

test("checkout uses both proxies, rejects duplicate clicks and preserves PATCH/auth contracts", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await checkout(page);
  let submitted = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/conversations\/[^/]+\/orders$/.test(request.url())
    )
      submitted++;
  });
  await page
    .getByRole("button", { name: /^Đặt hàng ·/ })
    .evaluate((button: HTMLButtonElement) => {
      button.click();
      button.click();
    });
  await expect(
    page.getByRole("heading", { name: "Đặt hàng thành công" }),
  ).toBeVisible();
  expect(submitted).toBe(1);
  const token = await page.evaluate(() =>
    localStorage.getItem("customer-token"),
  );
  const response = await page.request.patch("/backend/api/customer/me", {
    headers: {
      Authorization: `Bearer ${token}`,
      "X-Request-ID": "offline-browser-check",
    },
    data: { full_name: "Fixture customer" },
  });
  expect(response.status()).toBe(200);
  expect(response.headers()["x-request-id"]).toBe("offline-browser-check");
  expect((await response.json()).full_name).toBe("Fixture customer");
  await page.getByRole("link", { name: "Xem đơn hàng" }).click();
  await expect(page.locator(".s-order")).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("a lost response is recovered by key without creating a second order", async ({
  page,
}) => {
  await checkout(page);
  let submitted = 0;
  await page.route("**/backend/api/conversations/*/orders", async (route) => {
    submitted++;
    const committed = await route.fetch();
    expect(committed.status()).toBe(201);
    await route.fulfill({
      status: 504,
      json: { detail: "Synthetic response lost after commit" },
    });
  });
  await page.getByRole("button", { name: /^Đặt hàng ·/ }).click();
  await page.getByRole("button", { name: /Kiểm tra/ }).click();
  await expect(
    page.getByRole("heading", { name: "Đặt hàng thành công" }),
  ).toBeVisible();
  expect(submitted).toBe(1);
});

test("a changed quote requires a fresh confirmation before any order request", async ({
  page,
}) => {
  await checkout(page);
  let submitted = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/conversations\/[^/]+\/orders$/.test(request.url())
    )
      submitted++;
  });
  await page.route("**/backend/api/catalog/*/quote?*", async (route) => {
    const response = await route.fetch();
    const quote = await response.json();
    await route.fulfill({
      json: { ...quote, sale_price: "12345678.00", total: "12345678.00" },
    });
  });
  await page.getByRole("button", { name: /^Đặt hàng ·/ }).click();
  await expect(
    page.getByText(
      "Giá đã thay đổi. Vui lòng kiểm tra tổng tiền và xác nhận lại.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: /Tôi đã kiểm tra/ }),
  ).not.toBeChecked();
  expect(submitted).toBe(0);
});

test("a late OTP response cannot restore a session cleared in another tab", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "shop-cart",
      JSON.stringify([{ sku: "ASUS-V16-BLACK", qty: 1 }]),
    ),
  );
  await page.goto("/thanh-toan");
  await page
    .getByLabel("Số điện thoại", { exact: true })
    .fill("09" + String(Date.now()).slice(-8));
  await page.getByText("Tôi đồng ý để cửa hàng lưu").click();
  await page.getByRole("button", { name: "Gửi mã xác minh" }).click();
  const code = (await page.locator(".s-devnote b").textContent())!.trim();
  let release!: () => void;
  let started!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  const verifying = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route(
    "**/backend/api/conversations/*/identity/verify",
    async (route) => {
      const response = await route.fetch();
      started();
      await pending;
      await route.fulfill({ response });
    },
  );
  await page.getByLabel("Mã xác minh").fill(code);
  await page.getByRole("button", { name: "Xác minh", exact: true }).click();
  await verifying;
  await page.evaluate(() => {
    localStorage.removeItem("customer-token");
    window.dispatchEvent(
      new StorageEvent("storage", { key: "customer-token", newValue: null }),
    );
  });
  const returned = page.waitForResponse(response => response.url().endsWith("/identity/verify"));
  release();
  await returned;
  await page.evaluate(() => new Promise(requestAnimationFrame));
  expect(
    await page.evaluate(() => localStorage.getItem("customer-token")),
  ).toBeNull();
  await expect(page.getByRole("link", { name: "Đăng nhập hoặc đăng ký" })).toBeVisible();
});

test("mobile storefront and staff entry keep content inside the viewport and keyboard focus usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("https://**", route => route.abort());
  for (const path of ["/", "/gio-hang", "/thanh-toan", "/don-hang", "/calls"]) {
    await page.goto(path);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), path).toBe(true);
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement?.tagName), path).not.toBe("BODY");
  }
});
