import { test, expect } from "@playwright/test";

// The storefront end to end, against the running stack (docker compose up):
// browse → product → cart → checkout with phone verification → order → my
// orders, then a question to the AI assistant in the chat widget.
test("shopper buys a product and asks the assistant", async ({ page }) => {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Mua đúng thứ nhà bạn cần/ })).toBeVisible();
  await expect(page.locator(".s-card").first()).toBeVisible();

  // A product with a single SKU, from the BTC catalogue the agent also sells.
  await page.goto("/san-pham/SKU-AP-X");
  await expect(page.getByRole("heading", { name: "Máy lọc không khí AirPure X" })).toBeVisible();
  await expect(page.locator(".s-price-lg strong")).toContainText("₫");
  await page.getByRole("button", { name: "Mua ngay" }).click();

  await expect(page).toHaveURL(/\/gio-hang$/);
  await expect(page.getByText("Máy lọc không khí AirPure X")).toBeVisible();
  await page.getByRole("link", { name: "Tiến hành đặt hàng" }).click();

  // Verify a fresh phone number with the development code.
  await expect(page).toHaveURL(/\/thanh-toan$/);
  await page.getByLabel("Số điện thoại", { exact: true }).fill("09" + String(Date.now()).slice(-8));
  await page.getByLabel("Họ và tên (không bắt buộc)").fill("Khách Kiểm Thử");
  await page.getByText("Tôi đồng ý để cửa hàng lưu").click();
  await page.getByRole("button", { name: "Gửi mã xác minh" }).click();
  const code = (await page.locator(".s-devnote b").textContent())?.trim();
  expect(code).toMatch(/^\d{6}$/);
  await page.getByLabel("Mã xác minh").fill(code!);
  await page.getByRole("button", { name: "Xác minh" }).click();
  await expect(page.getByText("Số điện thoại đã được xác minh")).toBeVisible();

  await page.getByLabel(/Địa chỉ nhận hàng/).fill("12 Hoàng Cầu, phường Ô Chợ Dừa, quận Đống Đa, Hà Nội");
  await page.getByText("Tôi đã kiểm tra sản phẩm").click();
  await page.getByRole("button", { name: /^Đặt hàng ·/ }).click();
  await expect(page.getByRole("heading", { name: "Đặt hàng thành công" })).toBeVisible();

  await page.getByRole("link", { name: "Xem đơn hàng" }).click();
  await expect(page.locator(".s-order").first()).toContainText("Máy lọc không khí AirPure X");

  // The assistant answers from the agent (needs a model key in .env).
  await page.getByRole("button", { name: "Chat với trợ lý" }).click();
  await page.getByLabel("Tin nhắn").fill("Máy lọc không khí AirPure X giá bao nhiêu?");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  // A price, in digits or in words (the agent may spell amounts out).
  await expect(page.locator(".s-msg-assistant p").last()).toContainText(/\d|triệu|nghìn/, { timeout: 60000 });

  expect(failures).toEqual([]);
});
