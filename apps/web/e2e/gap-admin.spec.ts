import { test, expect, type Page, type Route } from "@playwright/test";

test.use({ channel: process.env.CI ? undefined : "chrome" });

async function fixtures(page: Page) {
  const sent: { url: string; body: unknown }[] = [];
  await page.route("**/backend/api/**", (route: Route) => {
    const request = route.request();
    const url = request.url();
    if (url.endsWith("/knowledge-gaps"))
      return route.fulfill({
        json: [
          {
            id: "abc",
            question: "Máy có dùng được ở độ cao 3000m không?",
            status: "open",
            occurrences: [{ call_id: "1", turn_id: "t1" }],
          },
        ],
      });
    if (url.includes("/knowledge-gaps/")) {
      sent.push({ url, body: request.postDataJSON() });
      if (url.endsWith("/faq"))
        return route.fulfill({ json: { chunk_id: "FAQ-GAP-ABC" } });
      if (url.endsWith("/resolve") && sent.length === 1)
        return route.fulfill({
          status: 422,
          json: { detail: "Câu trả lời có số tiền hoặc phần trăm." },
        });
      return route.fulfill({
        json: url.endsWith("/resolve")
          ? { status: "resolved", knowledge_version: 1 }
          : { status: "dismissed" },
      });
    }
    return route.fulfill({
      json: url.includes("/faq")
        ? {
            day: "2026-11-07",
            promotions: [],
            entries: sent.some((one) => one.url.endsWith("/faq"))
              ? [
                  {
                    chunk_id: "FAQ-GAP-ABC",
                    title: "Gap đã chuyển",
                    text: "Dạ em chưa có thông tin.",
                    status: "draft",
                    valid_from: null,
                    valid_to: null,
                    campaign: null,
                    applies_to: [],
                    cites: [],
                    approved_by: null,
                    effective: {
                      valid_from: null,
                      valid_to: null,
                      applies_to: [],
                    },
                    in_force: false,
                    editable: true,
                  },
                ]
              : [],
          }
        : [],
    });
  });
  await page.addInitScript(() =>
    sessionStorage.setItem("staff-token", "admin-token"),
  );
  await page.goto("/admin");
  await page
    .getByRole("button", { name: /Máy có dùng được ở độ cao/ })
    .click();
  return sent;
}

test("an admin approves a gap, and sees why the gate refused it first", async ({
  page,
}) => {
  const sent = await fixtures(page);
  await page.getByLabel("Câu trả lời đã kiểm tra").fill("Giá 200.000đ");
  await page.getByLabel(/Mã nguồn kiến thức/).fill("PB-05");
  const approve = page.getByRole("button", { name: "Duyệt và lưu phiên bản" });
  await expect(approve).toBeDisabled();
  await page.getByLabel(/Tôi đã đối chiếu nguồn/).check();
  await approve.click();
  await expect(page.getByText("Câu trả lời có số tiền")).toBeVisible();
  await page.getByLabel("Câu trả lời đã kiểm tra").fill("Dạ em chưa có thông tin.");
  await approve.click();
  await expect(page.getByText(/Đã lưu phiên bản 1/)).toBeVisible();
  expect(sent[1].body).toMatchObject({ cites: ["PB-05"], approved: true });
});

test("an answer becomes a draft FAQ that shows up to be approved", async ({
  page,
}) => {
  const sent = await fixtures(page);
  await page.getByLabel("Câu trả lời đã kiểm tra").fill("Dạ em chưa có thông tin.");
  await page.getByRole("button", { name: "Chuyển thành FAQ nháp" }).click();
  await expect(page.getByText(/Đã tạo FAQ nháp/)).toBeVisible();
  await expect(page.getByText(/Đã chuyển thành FAQ FAQ-GAP-ABC/)).toBeVisible();
  await expect(page.getByText("Gap đã chuyển")).toBeVisible();
  expect(sent[0].url).toContain("/knowledge-gaps/abc/faq");
});

test("an admin dismisses a question, only with a reason", async ({ page }) => {
  const sent = await fixtures(page);
  const dismiss = page.getByRole("button", { name: "Bỏ qua câu hỏi" });
  await expect(dismiss).toBeDisabled();
  await page.getByLabel(/Lý do bỏ qua/).fill("Ngoài phạm vi");
  await dismiss.click();
  await expect(page.getByText("Đã bỏ qua câu hỏi.")).toBeVisible();
  await expect(page.getByText(/Đã bỏ qua$/)).toBeVisible();
  expect(sent[0]).toMatchObject({ body: { reason: "Ngoài phạm vi" } });
});
