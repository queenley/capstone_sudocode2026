import { test, expect, type Page, type Route } from "@playwright/test";

test.use({ channel: process.env.CI ? undefined : "chrome" });

type Row = Record<string, unknown>;
const draft = (id: string, title: string): Row => ({
  chunk_id: id,
  title,
  text: "Trả lời đã soạn.",
  status: "draft",
  valid_from: null,
  valid_to: null,
  campaign: "11-11",
  applies_to: [],
  cites: ["KM-03"],
  approved_by: null,
  effective: {
    valid_from: "2026-11-11",
    valid_to: "2026-11-12",
    applies_to: ["category:gia-dung"],
  },
  in_force: false,
  editable: true,
});

async function fixtures(page: Page) {
  const rows = [draft("FAQ-1", "Đợt 11/11 có cộng dồn không?")];
  const sent: { method: string; body: Row | null }[] = [];
  await page.route("**/backend/api/**", (route: Route) => {
    const request = route.request();
    if (!request.url().includes("/api/developer/faq"))
      return route.fulfill({ json: [] });
    const method = request.method();
    const body = request.postDataJSON() as Row | null;
    if (method === "GET")
      return route.fulfill({
        json: {
          day: "2026-11-07",
          entries: rows,
          promotions: [
            {
              code: "11-11",
              name: "Giảm giá 11/11",
              start: "2026-11-11",
              end: "2026-11-12",
            },
          ],
        },
      });
    sent.push({ method, body });
    if (method === "DELETE") {
      rows.splice(0, rows.length);
      return route.fulfill({ json: { status: "deleted" } });
    }
    if (method === "POST") {
      if (String(body?.text).includes("300.000"))
        return route.fulfill({
          status: 422,
          json: { detail: "Câu trả lời có số tiền hoặc phần trăm." },
        });
      rows.push({ ...draft("FAQ-2", String(body?.title)), text: body?.text });
      return route.fulfill({ json: rows[rows.length - 1] });
    }
    rows[0] = {
      ...rows[0],
      status: body?.status,
      in_force: body?.status === "live",
      approved_by: body?.status === "live" ? "admin" : null,
    };
    return route.fulfill({ json: rows[0] });
  });
  await page.addInitScript(() => {
    sessionStorage.setItem("staff-token", "admin-token");
  });
  return sent;
}

async function open(page: Page) {
  await page.goto("/admin");
  return page.getByRole("region", { name: "FAQ theo đợt" });
}

test("an admin approves a draft, and only after confirming the sources", async ({
  page,
}) => {
  const sent = await fixtures(page);
  const panel = await open(page);
  await expect(panel.getByText("Đợt 11/11 có cộng dồn không?")).toBeVisible();
  await expect(panel.getByText(/Nháp · 2026-11-11 đến 2026-11-12/)).toBeVisible();
  await panel.getByRole("button", { name: "Sửa Đợt 11/11" }).click();
  const go = panel.getByRole("button", { name: "Duyệt và bật" });
  await expect(go).toBeDisabled();
  await panel.getByLabel("Tôi đã đối chiếu nguồn").check();
  await go.click();
  await expect(panel.getByText("Đã bật FAQ.")).toBeVisible();
  await expect(panel.getByText(/Đang áp dụng/)).toBeVisible();
  expect(sent[0]).toMatchObject({
    method: "PUT",
    body: { status: "live", approved: true, cites: ["KM-03"] },
  });
});

test("the gate's reason reaches the admin and the form stays open", async ({
  page,
}) => {
  await fixtures(page);
  const panel = await open(page);
  await panel.getByRole("button", { name: "Thêm FAQ" }).click();
  await panel.getByLabel("Câu hỏi").fill("Giảm bao nhiêu?");
  await panel.getByRole("textbox", { name: "Câu trả lời" }).fill("Giảm 300.000đ");
  await panel.getByRole("button", { name: "Lưu nháp" }).click();
  await expect(panel.getByRole("status")).toContainText("số tiền");
  await expect(panel.getByRole("textbox", { name: "Câu trả lời" })).toHaveValue("Giảm 300.000đ");
});

test("deleting asks first", async ({ page }) => {
  const sent = await fixtures(page);
  const panel = await open(page);
  page.once("dialog", (dialog) => dialog.dismiss());
  await panel.getByRole("button", { name: "Xóa Đợt 11/11" }).click();
  expect(sent).toHaveLength(0);
  page.once("dialog", (dialog) => dialog.accept());
  await panel.getByRole("button", { name: "Xóa Đợt 11/11" }).click();
  await expect(panel.getByText("Chưa có mục FAQ nào.")).toBeVisible();
  expect(sent[0].method).toBe("DELETE");
});
