const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let staticServer;

test.beforeAll(async () => {
  staticServer = await startServer();
});

test.afterAll(async () => {
  if (!staticServer) return;
  await new Promise(resolve => staticServer.close(resolve));
});

function json(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

const BOT_ID = "42";

/**
 * Health with knowledge missing — the state the mockup shows.
 *
 * `match_result` is the tri-state the UI reads: true / false / null. The string
 * fields alongside it (`validation_status`, `match_status`) are display labels
 * the backend also returns; they carry their real values here precisely so a
 * regression that reads them again fails instead of quietly passing.
 */
const HEALTH_NEEDS_KNOWLEDGE = {
  ready: false,
  warnings: [],
  profile: { active: true, name: "Test - Support Specialist", ai_provider: "openai", model_name: "gpt-4o" },
  knowledge: {
    active: false, file_name: null, processing_status: null,
    validation_status: "Validation not checked", match_status: "unchecked",
    match_result: null, match_reason: ""
  },
  channels: { connected_count: 1, items: [{ type: "webchat", label: "Website", connected: true }] },
  delivery: { failed: 0, retrying: 0, permanent_failed: 0, last_success_at: null },
  activity: { last_message_at: "2026-08-17T06:31:45.000Z" }
};

const ANALYTICS = {
  status: "success",
  data: {
    total_users: 1248,
    total_messages: 4532,
    chart: {
      labels: ["May 13 Tue", "May 14 Wed", "May 15 Thu", "May 16 Fri", "May 17 Sat", "May 18 Sun", "May 19 Mon"],
      data: [312, 420, 512, 645, 732, 901, 1010]
    },
    recent_history: [
      { user: "1023", channel: "webchat", last_content: "How do I reset my password?", timestamp: new Date().toISOString() },
      { user: "0876", channel: "whatsapp", last_content: "Where can I view my invoices?", timestamp: new Date().toISOString() },
      { user: "0451", channel: "telegram", last_content: "Do you offer refunds?", timestamp: "2020-05-19T14:27:03.000Z" }
    ]
  }
};

async function installSession(page, role = "owner") {
  await page.addInitScript(({ roleValue }) => {
    sessionStorage.setItem("token", "fake-tenant-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify({
      id: 1, email: "owner@company.com", full_name: "Owner", role: roleValue
    }));
  }, { roleValue: role });
}

/**
 * @param health  health payload to serve
 * @param match   result for POST /api/match/check, or null to leave it unmocked
 * @returns {{matchCalls: number}} live counter for the auto-validation assertions
 */
async function mockApis(page, health = HEALTH_NEEDS_KNOWLEDGE, match = null) {
  const counters = { matchCalls: 0 };

  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());

  await page.route("**/api/**", async route => {
    const url = route.request().url();
    if (url.includes("/api/match/check")) {
      counters.matchCalls += 1;
      return route.fulfill(json(match || { status: "success", data: { validation_status: "completed", match: true, reason: "Aligned." } }));
    }
    if (url.includes("/api/dashboard/health")) {
      return route.fulfill(json({ status: "success", data: health }));
    }
    if (url.includes("/api/dashboard/live-workflow")) {
      return route.fulfill(json({ status: "success", data: { state: null } }));
    }
    if (url.includes("/api/bots/")) {
      return route.fulfill(json({ status: "success", data: { bot_name: "Test" } }));
    }
    if (url.includes("/api/analytics")) {
      return route.fulfill(json(ANALYTICS));
    }
    if (url.includes("/api/settings")) {
      return route.fulfill(json({ status: "success", data: { active_profile: "Test v1.0" } }));
    }
    if (url.includes("/api/knowledge/active")) {
      return route.fulfill(json({ status: "success", data: { file_name: null } }));
    }
    return route.fulfill(json({ status: "success", data: {} }));
  });

  return counters;
}

async function openDashboard(page) {
  await installSession(page);
  const counters = await mockApis(page);
  await page.goto(`/index.html?bot_id=${BOT_ID}`);
  await expect(page.locator("#dashboard-title")).toHaveText("Test");
  return counters;
}

test("desktop dashboard matches the mockup structure", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await openDashboard(page);

  // Header status line
  await expect(page.locator("#dash-live-label")).toHaveText("Setup incomplete");
  await expect(page.locator("#date-display")).not.toHaveText("--");

  // Four setup steps, with knowledge flagged and profile ready
  await expect(page.locator(".dash-step")).toHaveCount(4);
  await expect(page.locator('.dash-step[data-step="profile"] .dash-step-state')).toHaveText("Ready");
  await expect(page.locator('.dash-step[data-step="knowledge"] .dash-step-state')).toHaveText("Needs attention");
  await expect(page.locator('.dash-step[data-step="validate"] .dash-step-state')).toHaveText("Not checked");
  await expect(page.locator('.dash-step[data-step="channel"] .dash-step-state')).toHaveText("Connected");
  await expect(page.locator('.dash-step[data-step="profile"]')).toHaveClass(/is-done/);

  // Next step points at the first incomplete step
  await expect(page.locator("#dash-next-title")).toHaveText("Add primary knowledge");
  await expect(page.locator("#dash-next-cta-label")).toHaveText("Open knowledge");
  await expect(page.locator("#dash-next-cta")).toHaveAttribute("href", `new_linkdocs.html?bot_id=${BOT_ID}`);

  // Stats
  await expect(page.locator("#stat-total-users")).toHaveText("1,248");
  await expect(page.locator("#stat-total-msgs")).toHaveText("4,532");
  await expect(page.locator("#stat-active-profile")).toHaveText("Test v1.0");
  await expect(page.locator("#stat-active-pdf")).toHaveText("Not selected");

  // Trend chart renders one described figure with 7 points
  await expect(page.locator("#chart-container svg[role='img']")).toHaveCount(1);
  await expect(page.locator(".dash-chart-dot")).toHaveCount(7);
  await expect(page.locator("#dash-trend-total")).toHaveText("4,532");
  await expect(page.locator("#dash-trend-peak")).toContainText("1,010");

  // Activity table
  await expect(page.locator("#recent-history-body tr")).toHaveCount(3);
  await expect(page.locator("#recent-history-body tr").first()).toContainText("Web chat");
  await expect(page.locator("#recent-history-body tr").first()).toContainText("How do I reset my password?");

  // Workflow idle
  await expect(page.locator("#dash-flow-state")).toHaveText("Idle");

  await page.screenshot({ path: "test-results/dashboard-desktop.png", fullPage: true });
});

test("bot settings menu is a keyboard-operable disclosure", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await openDashboard(page);

  const trigger = page.locator("#dash-menu-trigger");
  const list = page.locator("#dash-menu-list");

  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(list).toBeHidden();

  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(list).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(list).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("mobile dashboard stacks and exposes the day stepper", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openDashboard(page);

  await expect(page.locator(".dash-daystep")).toBeVisible();
  await expect(page.locator("#dash-day-label")).toHaveText("May 19 Mon");
  await expect(page.locator("#dash-day-value")).toHaveText("1,010");
  await expect(page.locator("#dash-day-next")).toBeDisabled();

  await page.locator("#dash-day-prev").click();
  await expect(page.locator("#dash-day-label")).toHaveText("May 18 Sun");
  await expect(page.locator("#dash-day-value")).toHaveText("901");
  await expect(page.locator("#dash-day-next")).toBeEnabled();

  // No horizontal overflow at phone width
  const overflow = await page.evaluate(() => {
    const limit = document.documentElement.clientWidth;
    const offenders = [...document.querySelectorAll("*")]
      .filter(el => el.getBoundingClientRect().right > limit + 1)
      .slice(0, 6)
      .map(el => `${el.tagName}.${el.className || "(none)"} right=${Math.round(el.getBoundingClientRect().right)}`);
    return {
      overflow: document.documentElement.scrollWidth - limit,
      limit,
      offenders
    };
  });
  expect(overflow, JSON.stringify(overflow, null, 2)).toMatchObject({ overflow: 0 });

  await page.screenshot({ path: "test-results/dashboard-mobile.png", fullPage: true });
});

/** Knowledge active and the stored check already passed. */
const HEALTH_VALIDATED = {
  ...HEALTH_NEEDS_KNOWLEDGE,
  ready: true,
  knowledge: {
    active: true, file_name: "Aveon Knowledge Base.pdf",
    validation_status: "Profile validated", match_status: "unchecked",
    match_result: true, match_reason: "Both describe Aveon's AI support offering."
  }
};

test("setup complete flips the header to Live and retargets the next action", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await installSession(page);
  const counters = await mockApis(page, HEALTH_VALIDATED);
  await page.goto(`/index.html?bot_id=${BOT_ID}`);

  await expect(page.locator("#dash-live-label")).toHaveText("Live");
  await expect(page.locator("#dash-systems")).toHaveText("All systems operational");
  await expect(page.locator("#dash-next-title")).toHaveText("Setup complete");
  await expect(page.locator(".dash-step.is-done")).toHaveCount(4);

  // A stored pass is read, never re-run — that would bill credits for nothing.
  expect(counters.matchCalls).toBe(0);
});

test("a stored pass shows the Validate step as Passed", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await installSession(page);
  await mockApis(page, HEALTH_VALIDATED);
  await page.goto(`/index.html?bot_id=${BOT_ID}`);

  // Regression guard: this read the display label and so could never pass.
  await expect(page.locator('.dash-step[data-step="validate"] .dash-step-state')).toHaveText("Passed");
  await expect(page.locator('.dash-step[data-step="validate"]')).toHaveClass(/is-done/);
});

test("a stored failure shows the reason and routes the next action to bot config", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await installSession(page);
  const counters = await mockApis(page, {
    ...HEALTH_VALIDATED,
    ready: false,
    knowledge: {
      ...HEALTH_VALIDATED.knowledge,
      validation_status: "Profile mismatch",
      match_result: false,
      match_reason: "Profile describes an AI services firm; the document is a bakery menu."
    }
  });
  await page.goto(`/index.html?bot_id=${BOT_ID}`);

  await expect(page.locator('.dash-step[data-step="validate"] .dash-step-state')).toHaveText("Needs attention");
  await expect(page.locator('.dash-step[data-step="validate"] .dash-step-hint'))
    .toContainText("bakery menu");
  await expect(page.locator("#dash-next-title")).toHaveText("Profile and knowledge do not match");
  await expect(page.locator("#dash-next-cta")).toHaveAttribute("href", `new_prompt.html?bot_id=${BOT_ID}`);

  // A failure is the user's to resolve; retrying it automatically would bill
  // credits on every load for a problem only they can fix.
  expect(counters.matchCalls).toBe(0);
});

test("an owner auto-validates once when the stored result is stale", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await installSession(page, "owner");
  const counters = await mockApis(page, {
    ...HEALTH_VALIDATED,
    knowledge: { ...HEALTH_VALIDATED.knowledge, match_result: null, match_reason: "" }
  });
  await page.goto(`/index.html?bot_id=${BOT_ID}`);

  // No click anywhere in this test.
  await expect(page.locator('.dash-step[data-step="validate"] .dash-step-state')).toHaveText("Passed");
  expect(counters.matchCalls).toBe(1);
});

test("a member never triggers validation, because the endpoint would 403", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await installSession(page, "member");
  const counters = await mockApis(page, {
    ...HEALTH_VALIDATED,
    knowledge: { ...HEALTH_VALIDATED.knowledge, match_result: null, match_reason: "" }
  });
  await page.goto(`/index.html?bot_id=${BOT_ID}`);

  await expect(page.locator('.dash-step[data-step="validate"] .dash-step-state')).toHaveText("Not checked");
  expect(counters.matchCalls).toBe(0);
});

test("auto-validation does not retry when the check comes back unavailable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await installSession(page, "owner");
  const counters = await mockApis(
    page,
    { ...HEALTH_VALIDATED, knowledge: { ...HEALTH_VALIDATED.knowledge, match_result: null, match_reason: "" } },
    { status: "success", data: { validation_status: "unavailable", match: null, reason: "" } }
  );
  await page.goto(`/index.html?bot_id=${BOT_ID}`);

  await expect(page.locator('.dash-step[data-step="validate"] .dash-step-state')).toHaveText("Not checked");
  expect(counters.matchCalls).toBe(1);
});

test("mobile viewport shot (sticky sidebar at top)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openDashboard(page);
  await page.screenshot({ path: "test-results/dashboard-mobile-top.png" });
  await page.evaluate(() => window.scrollTo(0, 900));
  await page.screenshot({ path: "test-results/dashboard-mobile-scrolled.png" });

  // The shell must sit above the content, not inside it.
  const order = await page.evaluate(() => {
    const bar = document.querySelector("chatbot-sidebar .sidebar").getBoundingClientRect();
    const main = document.querySelector(".main-container").getBoundingClientRect();
    return { sidebarTop: Math.round(bar.top), mainTop: Math.round(main.top + window.scrollY) };
  });
  expect(order.sidebarTop).toBeLessThanOrEqual(1);
});
