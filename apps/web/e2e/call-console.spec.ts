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
