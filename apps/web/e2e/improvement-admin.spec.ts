import { test, expect, type Page, type Route } from "@playwright/test";

// docs/plan/001, parts C and D: the admin reviews the weekly round's proposals, switches a measured candidate on, and
// reads the evaluation history week by week. The API is mocked; access is the API's to refuse.
test.use({ channel: process.env.CI ? undefined : "chrome" });

const proposal = (decision: string | null = null) => ({
  id: "SK-weekly-2026-W46-budget-1",
  kind: "skill",
  decision,
  reviewer: decision ? "staff:u-1" : null,
  note: decision ? "ổn" : null,
  review_file: "x.json",
  body: {
    situation: "đơn vượt ngân sách",
    failure_code: "TSR.must_say",
    why: "Ba khách hỏi tổng tiền khi đơn vượt ngân sách.",
    flags: [],
    policy: [],
    evidence: [{ scenario_id: "SCN-BGT-L01", call: "call_1" }],
    entry: { text: "Khi tổng vượt ngân sách khách nói, báo tổng và phần vượt.", find: "", cites: ["PB-05"], where: "ordering.body" },
  },
});

const run = (week: string, tsr: number, cohort = "c1") => ({
  run_id: `run-${week}-${cohort}`,
  purpose: "weekly_frozen",
  week,
  started_at: `${week}T02:00:00+00:00`,
  cohort_sha256: cohort.padEnd(64, "0"),
  n_scenarios: 19,
  extractor_version: "product-extractor-v13",
  advisor_model: "gpt-5.6-luna",
  profile: "router",
  skills_version: null,
  kb_version: null,
  metrics: {
    full: { TSR: tsr, CCR: 60, RQR: 5, HR: 3, ttft_p95_ms: 2100, cost_per_turn_usd: 0.0031 },
    baseline_no_memory: { TSR: tsr - 20, CCR: 10, RQR: 12, HR: 4 },
  },
});

async function fixtures(page: Page, status = "waiting_review") {
  const sent: { url: string; body: unknown }[] = [];
  let current = { name: "weekly-2026-W46", week: "2026-11-09", status, base_skills_version: 0, candidate_skills_version: null as number | null, detail: {} as Record<string, unknown>, proposals: [proposal()] };
  await page.route("**/backend/api/**", (route: Route) => {
    const request = route.request();
    const url = request.url();
    if (request.method() === "POST") sent.push({ url, body: request.postDataJSON() });
    if (url.includes("/improvement/proposals/")) {
      const body = request.postDataJSON() as { decision: string };
      current = { ...current, proposals: [proposal(body.decision)] };
      return route.fulfill({ json: current.proposals[0] });
    }
    if (url.endsWith("/activate")) return route.fulfill({ json: { status: "active", skills_version: 1, reload_required: true } });
    if (url.includes("/improvement/rounds/")) return route.fulfill({ json: current });
    if (url.endsWith("/improvement/rounds"))
      return route.fulfill({
        json: {
          skills_version: 0,
          rounds: [{ ...current, proposals: 1, pending: current.proposals[0].decision ? 0 : 1 }, { name: "weekly-2026-W45", week: "2026-11-02", status: "active", base_skills_version: 0, candidate_skills_version: 1, detail: {}, proposals: 1, pending: 0 }],
        },
      });
    if (url.includes("/api/developer/evaluations"))
      return route.fulfill({ json: { runs: [run("2026-10-26", 30), run("2026-11-02", 38), run("2026-11-09", 45), run("2026-11-09", 90, "c2")] } });
    if (url.includes("/api/developer/faq")) return route.fulfill({ json: { day: "2026-11-12", entries: [], promotions: [] } });
    return route.fulfill({ json: [] });
  });
  await page.addInitScript(() => sessionStorage.setItem("staff-token", "admin-token"));
  return { sent, measured: () => {
    current = { ...current, status: "measured", candidate_skills_version: 1, detail: { comparison: { budget: { metrics: { TSR: { before: "50", after: "83.3" } }, fixed: [1, 2], broken: [], unstable: [], harm: [], calls: 6 } } } };
  } };
}

test("an admin approves one proposal and refuses another only with a reason", async ({ page }) => {
  const { sent } = await fixtures(page);
  await page.goto("/admin?tab=improvement");
  await page.getByRole("button", { name: "Mở 2026-11-09" }).click();
  const card = page.getByRole("article", { name: "Đề xuất SK-weekly-2026-W46-budget-1" });
  await expect(card.getByText("Khi tổng vượt ngân sách khách nói, báo tổng và phần vượt.")).toBeVisible();
  await expect(card.getByText("SCN-BGT-L01/call_1")).toBeVisible();
  await expect(card.getByRole("button", { name: /Từ chối/ })).toBeDisabled();
  await card.getByRole("button", { name: /Duyệt/ }).click();
  await expect(page.getByText(/Đã duyệt SK-weekly/)).toBeVisible();
  expect(sent[0]).toMatchObject({ body: { decision: "approved" } });
  expect(sent[0].url).toContain("/api/developer/improvement/proposals/SK-weekly-2026-W46-budget-1/review");
});

test("a measured candidate is switched on only after the admin confirms the measurement", async ({ page }) => {
  const { sent, measured } = await fixtures(page, "measured");
  measured();
  await page.goto("/admin?tab=improvement");
  await page.getByRole("button", { name: "Mở 2026-11-09" }).click();
  await expect(page.getByRole("table", { name: "Phép đo budget" })).toContainText("83.3");
  const go = page.getByRole("button", { name: "Bật skills v1" });
  await expect(go).toBeDisabled();
  await page.getByLabel(/Tôi đã xem phép đo/).check();
  await go.click();
  await expect(page.getByText(/Khởi động lại ai-agent-service/)).toBeVisible();
  expect(sent.at(-1)?.url).toContain("/improvement/rounds/weekly-2026-W46/activate");
});

test("the dashboard draws one cohort week by week, marks the skills switch, and has a table view", async ({ page }) => {
  await fixtures(page);
  await page.goto("/admin?tab=evaluation");
  const tsr = page.getByRole("figure", { name: "Task Success Rate (TSR)" });
  await expect(tsr).toBeVisible();
  // Two cohorts exist: one is drawn, and the page says why the other is not on the same line.
  await expect(page.getByText(/2 bộ kịch bản\/extractor khác nhau/)).toBeVisible();
  await page.getByLabel("Bộ kịch bản và extractor").selectOption({ index: 0 });
  await expect(tsr.getByText("45%")).toBeVisible();
  await expect(tsr.getByText("skills v1")).toBeVisible();
  await page.screenshot({ path: "test-results/admin-evaluation-dashboard.png", fullPage: true });
  await page.getByRole("button", { name: "Xem bảng" }).click();
  const table = page.getByRole("table", { name: "Lịch sử đánh giá" });
  await expect(table.getByRole("row")).toHaveCount(4);
  await expect(table).toContainText("45% / 25%");
});
