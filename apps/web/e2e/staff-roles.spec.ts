import { test, expect, type Page } from "@playwright/test";

// docs/plan/001-vong-cai-tien-hang-tuan-va-dashboard.md, part A: the admin has a workspace of its own, and the sales
// team's page links to it only for an admin. Access itself is the API's (403), so the page is only checked for where
// it sends a person and which links it offers.
test.use({ channel: process.env.CI ? undefined : "chrome" });

async function backend(page: Page, role: string) {
  await page.route("**/backend/api/**", (route) => {
    const url = route.request().url();
    if (url.endsWith("/api/auth/login")) return route.fulfill({ json: { access_token: `${role}-token`, role } });
    // The admin's default section lists FAQ entries: an empty listing in the shape the panel reads.
    if (url.includes("/api/developer/faq")) return route.fulfill({ json: { day: "2026-11-12", entries: [], promotions: [] } });
    return route.fulfill({ json: [] });
  });
}

async function signIn(page: Page, role: string) {
  await backend(page, role);
  await page.goto("/login");
  await page.getByLabel("Tên đăng nhập").fill(`${role}1`);
  await page.getByLabel("Mật khẩu").fill("synthetic-password");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
}

test("an admin signs in to the admin workspace, not the sales page", async ({ page }) => {
  await signIn(page, "admin");
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("navigation", { name: "Khu vực quản trị" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Kiến thức", exact: true })).toBeVisible();
  await expect(page.getByLabel("Staff access token")).toHaveCount(0);
});

for (const role of ["seller", "agent"]) {
  test(`a ${role} signs in to the sales page, which has no link to the admin workspace`, async ({ page }) => {
    await signIn(page, role);
    await expect(page).toHaveURL(/\/ban-hang$/);
    await expect(page.getByRole("navigation", { name: "Khu vực bán hàng" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Quản trị" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Agent Console" })).toHaveCount(0);
  });
}

test("an admin on the sales page has the way back to the admin workspace", async ({ page }) => {
  await signIn(page, "admin");
  await expect(page).toHaveURL(/\/admin$/);
  await page.getByRole("link", { name: "Trang bán hàng" }).click();
  await expect(page).toHaveURL(/\/ban-hang/);
  await expect(page.getByRole("link", { name: "Quản trị" })).toBeVisible();
});

test("the admin workspace without a sign-in asks for one", async ({ page }) => {
  await backend(page, "admin");
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Trang quản trị" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Đăng nhập" })).toHaveAttribute("href", "/login?next=/admin");
});
