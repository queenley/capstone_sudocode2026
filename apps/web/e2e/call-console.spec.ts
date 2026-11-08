import { test, expect } from "@playwright/test";

test.use({ channel: process.env.CI ? undefined : "chrome" });
const call = (id: number) => ({
  id,
  customer_label: `Fixture ${id}`,
  customer_id: null,
  phone_last4: null,
  channel: "web",
  channel_ref: null,
  tier: "UNKNOWN",
  lane: "NEW",
  mode: "speak",
  brief: [],
  brief_object: null,
  warnings: [],
  started_at: "2026-10-31T00:00:00Z",
  ended_at: null,
  turn_count: 0,
  handoff_status: null,
  suggestion: null,
  accepted_by: null,
  held_by_you: false,
  turns: [],
  memory_status: null,
  after_call: null,
});

test("a delayed call response cannot replace the newly selected call", async ({
  page,
}) => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  let started!: () => void;
  const loading = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route("**/backend/api/agent/calls**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/context"))
      return route.fulfill({
        json: {
          facts: [],
          episodes: [],
          orders: [],
          identity_confirmed: false,
          memory_status: null,
        },
      });
    if (url.pathname.endsWith("/calls"))
      return route.fulfill({ json: [call(1), call(2)] });
    if (url.pathname.endsWith("/1")) {
      started();
      await pending;
      return route.fulfill({ json: call(1) });
    }
    return route.fulfill({ json: call(2) });
  });
  await page.goto("/calls");
  await page.getByLabel("Staff access token").fill("offline-staff");
  await page.getByRole("button", { name: "Kết nối", exact: true }).click();
  await loading;
  await page.locator(".queue-row", { hasText: "Fixture 2" }).click();
  await expect(page.locator(".call-transcript-pane h2")).toContainText(
    "Fixture 2",
  );
  release();
  await expect(page.locator(".call-transcript-pane h2")).toContainText(
    "Fixture 2",
  );
  await expect(page.getByRole("textbox", { name: /trả lời/i })).toHaveCount(0);
});

test("changing staff credentials clears the previous queue and transcript", async ({
  page,
}) => {
  await page.route("**/backend/api/agent/calls**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/context"))
      return route.fulfill({
        json: {
          facts: [],
          episodes: [],
          orders: [],
          identity_confirmed: false,
          memory_status: null,
        },
      });
    return route.fulfill({
      json: url.pathname.endsWith("/calls") ? [call(1)] : call(1),
    });
  });
  await page.goto("/calls");
  await page.getByLabel("Staff access token").fill("offline-staff-one");
  await page.getByRole("button", { name: "Kết nối", exact: true }).click();
  await expect(page.locator(".call-transcript-pane h2")).toContainText(
    "Fixture 1",
  );
  await page.getByLabel("Staff access token").fill("offline-staff-two");
  await expect(page.locator(".queue-row")).toHaveCount(0);
  await expect(page.locator(".call-transcript-pane h2")).toHaveCount(0);
});

const context = {
  facts: [],
  episodes: [],
  orders: [],
  identity_confirmed: false,
  memory_status: null,
};

test("one customer's sessions on every channel are one row, switched above the brief", async ({
  page,
}) => {
  const lan = (id: number, channel: string, started_at: string, ended_at: string | null) => ({
    ...call(id),
    customer_label: "Chị Lan",
    customer_id: "C-LAN",
    channel,
    started_at,
    ended_at,
    turn_count: 3,
    brief: [{ id: "B1", text: `Brief của phiên ${id}` }],
  });
  const calls = [
    lan(11, "web", "2026-11-01T02:00:00Z", "2026-11-01T02:10:00Z"),
    lan(12, "zalo", "2026-11-03T02:00:00Z", "2026-11-03T02:10:00Z"),
    lan(13, "hotline", "2026-11-08T02:00:00Z", null),
    call(14),
  ];
  await page.route("**/backend/api/agent/handoffs/stream", (route) => route.abort());
  await page.route("**/backend/api/agent/calls**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/context")) return route.fulfill({ json: context });
    if (url.pathname.endsWith("/calls")) return route.fulfill({ json: calls });
    const id = Number(url.pathname.split("/").pop());
    return route.fulfill({ json: calls.find((c) => c.id === id) });
  });
  await page.goto("/calls");
  await page.getByLabel("Staff access token").fill("offline-staff");
  await page.getByRole("button", { name: "Kết nối", exact: true }).click();

  await expect(page.locator(".queue-row")).toHaveCount(2);
  const row = page.locator(".queue-row", { hasText: "Chị Lan" });
  await expect(row).toContainText("3 phiên · Hotline, Zalo, Web chat");
  await row.click();
  // The open session leads; the brief sits above the transcript.
  const brief = page.locator(".call-transcript-pane .call-brief-main");
  await expect(brief).toContainText("Brief của phiên 13");
  const sessions = page.getByRole("navigation", { name: "Các phiên của khách này" });
  await expect(sessions.getByRole("button")).toHaveCount(3);
  await sessions.getByRole("button", { name: /Zalo/ }).click();
  await expect(brief).toContainText("Brief của phiên 12");
  await expect(sessions.getByRole("button", { name: /Zalo/ })).toHaveAttribute("aria-current", "true");
});

test("a handoff pushed on the stream turns the bell red, and the bell opens the call", async ({
  page,
}) => {
  const waiting = {
    ...call(21),
    customer_label: "Anh Minh",
    customer_id: "C-MINH",
    mode: "copilot",
    handoff_status: "pending",
    handoff_reason: "khach_yeu_cau_gap_nguoi",
    handoff_requested_at: new Date().toISOString(),
  };
  const calls = [call(20), waiting];
  await page.route("**/backend/api/agent/handoffs/stream", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body:
        "retry: 3000\n\n: keepalive\n\n" +
        `event: handoffs\ndata: ${JSON.stringify({ source: "kafka", waiting: [waiting] })}\n\n`,
    }),
  );
  await page.route("**/backend/api/agent/calls**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/context")) return route.fulfill({ json: context });
    if (url.pathname.endsWith("/calls")) return route.fulfill({ json: calls });
    const id = Number(url.pathname.split("/").pop());
    return route.fulfill({ json: calls.find((c) => c.id === id) });
  });
  await page.goto("/calls");
  await page.getByLabel("Staff access token").fill("offline-staff");
  await page.getByRole("button", { name: "Kết nối", exact: true }).click();

  const bell = page.getByRole("button", { name: "1 khách đang chờ nhân viên" });
  await expect(bell).toBeVisible();
  await expect(bell).toHaveClass(/ringing/);
  await expect(page.locator(".handoff-toast")).toContainText("Anh Minh");
  await bell.click();
  const panel = page.getByRole("dialog", { name: "Khách chờ nhân viên" });
  await expect(panel).toContainText("Trực tiếp qua Kafka");
  await expect(panel).toContainText("Khách muốn gặp nhân viên");
  await panel.getByRole("button", { name: /Anh Minh/ }).click();
  await expect(page.locator(".call-transcript-pane h2")).toContainText("Anh Minh");
  await expect(page.locator(".call-brief-main.waiting")).toBeVisible();
});

test("without the stream the bell polls the queue", async ({ page }) => {
  const waiting = { ...call(31), customer_label: "Chị Hà", handoff_status: "pending", handoff_reason: "khieu_nai_nghiem_trong" };
  await page.route("**/backend/api/agent/handoffs/stream", (route) => route.fulfill({ status: 502, json: {} }));
  await page.route("**/backend/api/agent/calls**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/context")) return route.fulfill({ json: context });
    if (url.pathname.endsWith("/calls")) return route.fulfill({ json: [waiting] });
    return route.fulfill({ json: waiting });
  });
  await page.goto("/calls");
  await page.getByLabel("Staff access token").fill("offline-staff");
  await page.getByRole("button", { name: "Kết nối", exact: true }).click();
  const bell = page.getByRole("button", { name: "1 khách đang chờ nhân viên" });
  await expect(bell).toBeVisible({ timeout: 10_000 });
  await bell.click();
  await expect(page.getByRole("dialog", { name: "Khách chờ nhân viên" })).toContainText("trang tự tải lại");
});

test("the sales workspace's bell opens the waiting call in the conversations tab", async ({ page }) => {
  const waiting = { ...call(41), customer_label: "Cô Bình", mode: "copilot", handoff_status: "pending", handoff_reason: "khac" };
  await page.addInitScript(() => sessionStorage.setItem("staff-token", "offline-staff"));
  await page.route("**/backend/api/agent/handoffs/stream", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: `event: handoffs\ndata: ${JSON.stringify({ source: "polling", waiting: [waiting] })}\n\n`,
    }),
  );
  await page.route("**/backend/api/seller/orders", (route) => route.fulfill({ status: 403, json: { detail: "no" } }));
  await page.route("**/backend/api/agent/callbacks", (route) => route.fulfill({ json: [] }));
  await page.route("**/backend/api/agent/calls**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/context")) return route.fulfill({ json: context });
    if (url.pathname.endsWith("/calls")) return route.fulfill({ json: [call(40), waiting] });
    const id = Number(url.pathname.split("/").pop());
    return route.fulfill({ json: id === 41 ? waiting : call(40) });
  });
  await page.goto("/ban-hang");
  await page.getByRole("button", { name: "1 khách đang chờ nhân viên" }).click();
  await page.getByRole("dialog", { name: "Khách chờ nhân viên" }).getByRole("button", { name: /Cô Bình/ }).click();
  await expect(page.getByRole("button", { name: /Hội thoại & chuyển máy/ })).toHaveAttribute("aria-current", "page");
  await expect(page.locator(".call-transcript-pane h2")).toContainText("Cô Bình");
});
