import { test, expect } from "@playwright/test";

test("buyer conversation, verification, order and returning memory", async ({
  page,
}) => {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.goto("/");
  await expect(page.locator("body")).not.toHaveCSS(
    "font-family",
    '"Times New Roman"',
  );
  expect(
    await page.evaluate(() =>
      getComputedStyle(document.documentElement)
        .getPropertyValue("--green")
        .trim(),
    ),
  ).toBe("#295a45");
  await expect(
    page.getByRole("heading", { name: "ASUS Vivobook 16" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New session", exact: true }).click();
  await page.getByRole("button", { name: "Remember me" }).click();
  await page
    .getByLabel("Phone number")
    .fill("09" + String(Date.now()).slice(-8));
  await page.getByLabel("I consent to identity linking").check();
  await page.getByRole("button", { name: "Request verification" }).click();
  const code = (await page.getByText("Development code:").textContent())?.match(
    /\d{6}/,
  )?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel("Verification code").fill(code!);
  await page.getByRole("button", { name: "Verify identity" }).click();
  await expect(
    page.getByText("Customer verified · context enabled"),
  ).toBeVisible();
  await page
    .getByLabel("Message", { exact: true })
    .fill("Ngân sách 18 triệu, thích màu đen để code");
  await page.getByRole("button", { name: "Send ↗" }).click();
  await expect(page.locator(".incoming").last()).toContainText("18000000");
  await page
    .locator(".product")
    .filter({ hasText: "ASUS Vivobook 16" })
    .getByRole("button", { name: "Discuss" })
    .click();
  await page.getByLabel("Message", { exact: true }).fill("Giá bao nhiêu?");
  await page.getByRole("button", { name: "Send ↗" }).click();
  await expect(page.locator(".incoming").last()).toContainText(
    "17,990,000 VND",
  );
  await page.getByRole("button", { name: "Place an order" }).click();
  await page.getByLabel("Shipping address").fill("123 Browser Test Street");
  await page.getByLabel("I confirm this SKU").check();
  await page.getByRole("button", { name: "Confirm order" }).click();
  await expect(page.getByRole("status")).toContainText("Order confirmed");
  await page.getByRole("button", { name: "End session" }).click();
  await page.getByRole("button", { name: "New session", exact: true }).click();
  await page
    .getByLabel("Message", { exact: true })
    .fill("Lần trước anh nói thích màu gì?");
  await page.getByRole("button", { name: "Send ↗" }).click();
  await expect(page.locator(".incoming").last()).toContainText("den");
  await page.screenshot({
    path: "../../reports/generated/buyer-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../../reports/generated/buyer-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(failures).toEqual([]);
});
