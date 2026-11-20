const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let staticServer;
const BOT_ID = "42";
const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
const leads = [
  { id: 1, customer_name: "Amina", customer_phone: "+601", source_channel: "web", status: "new", priority: "high", lead_type: "follow_up", follow_up_date: yesterday, assigned_to: "", summary: "Asked about a quote", notes: "", created_at: "2026-08-25T08:00:00Z", updated_at: "2026-08-25T08:00:00Z", conversation_id: 7 },
  { id: 2, customer_name: "Daniel", customer_phone: "+602", source_channel: "whatsapp", status: "qualified", priority: "medium", lead_type: "staff_attention", follow_up_date: null, assigned_to: "Kai", summary: "Needs a product demo", notes: "Call next week", created_at: "2026-08-24T08:00:00Z", updated_at: "2026-08-25T08:00:00Z", conversation_id: 8 }
];

test.beforeAll(async () => { staticServer = await startServer(); });
test.afterAll(async () => { if (staticServer) await new Promise(resolve => staticServer.close(resolve)); });

function json(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

async function openWorkspace(page, role = "owner", flags = { crm_lead_assignment: true, ai_generated_reports: true }) {
  await page.addInitScript(({ roleValue }) => {
    sessionStorage.setItem("token", "test-token");
    sessionStorage.setItem("selectedBotId", "42");
    sessionStorage.setItem("user", JSON.stringify({ role: roleValue, full_name: "Test user" }));
  }, { roleValue: role });
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("**/api/**", async route => {
    const url = route.request().url();
    if (url.includes("/api/billing/subscription")) return route.fulfill(json({ status: "success", data: { plan: { code: "pro", feature_flags: flags } } }));
    if (url.includes("/api/bots/")) return route.fulfill(json({ status: "success", data: { bot_name: "Support Bot" } }));
    if (url.includes("/api/crm/leads/") && route.request().method() === "PATCH") {
      const payload = JSON.parse(route.request().postData() || "{}");
      const lead = { ...leads[0], ...payload };
      return route.fulfill(json({ status: "success", data: { lead } }));
    }
    if (url.includes("/api/crm/leads")) return route.fulfill(json({ status: "success", data: { leads } }));
    if (url.includes("/api/analytics/report")) return route.fulfill(json({ status: "success", data: { report: "# Weekly summary\n\n- Two conversations need review.\n\n| Metric | Value |\n| --- | --- |\n| Messages | 12 |" } }));
    if (url.includes("/api/analytics")) return route.fulfill(json({ status: "success", data: { total_users: 8, total_messages: 12, chart: { labels: ["Mon", "Tue", "Wed"], data: [2, 4, 6] } } }));
    if (url.includes("/api/agent/insights")) return route.fulfill(json({ status: "success", data: { summary: { follow_up_opportunities: 1, needs_staff_attention: 0, negative_feedback: 0, missing_answers: 0 }, recent: [] } }));
    return route.fulfill(json({ status: "success", data: {} }));
  });
  await page.goto(`/crm.html?bot_id=${BOT_ID}`, { waitUntil: "domcontentloaded" });
}

test("desktop daily brief and lead actions are usable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openWorkspace(page);
  await expect(page.locator("#page-title")).toHaveText("Support Bot insights");
  await expect(page.locator("#daily-actions .ia-action-row")).toHaveCount(3);
  await expect(page.locator("#daily-actions")).toContainText("overdue follow-up");
  await page.screenshot({ path: "test-results/insights-actions-today.png", fullPage: true });
  await page.locator("#daily-actions .ia-action-row").first().click();
  await expect(page.locator("#lead-follow-up-filter")).toHaveValue("overdue");
  await expect(page.locator("#leads-table-body tr")).toHaveCount(1);
  await page.getByRole("tab", { name: "Today" }).click();
  await page.locator("#open-action-queue").click();
  await expect(page.locator('[data-view-panel="leads"]')).toBeVisible();
  await page.locator("#clear-lead-filters").click();
  await expect(page.locator("#leads-table-body tr")).toHaveCount(2);
  await page.locator("#lead-assignment-filter").selectOption("unassigned");
  await page.locator("#lead-type-filter").selectOption("follow_up");
  await expect(page.locator("#leads-table-body tr")).toHaveCount(1);
  await page.locator("#clear-lead-filters").click();
  await page.locator("#lead-status-filter").selectOption("new");
  await expect(page.locator("#leads-table-body tr")).toHaveCount(1);
  await page.locator("#leads-table-body tr").first().getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#ia-status")).toHaveText("Lead saved.");
  await page.screenshot({ path: "test-results/insights-actions-desktop.png", fullPage: true });
});

test("performance report and owner-only signals work on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openWorkspace(page, "owner");
  await page.getByRole("tab", { name: "Performance" }).click();
  await expect(page.locator("#performance-chart .ia-chart-col")).toHaveCount(3);
  await page.locator("#generate-report").click();
  await expect(page.locator("#report-output")).toContainText("Weekly summary");
  await page.getByRole("tab", { name: "AI Signals" }).click();
  await expect(page.locator("#signals-summary")).toContainText("Follow-up opportunities");
  await page.screenshot({ path: "test-results/insights-actions-mobile.png", fullPage: true });
});

test("the page keeps its Insights layout: dashboard-page plus insights-page on <body>", async ({ page }) => {
  // The page frame writes class="dashboard-page" and appends the page's own class; insights-actions.css
  // lays the page out under .insights-page. Replaces the body-class source pin of test_crm_frontend_status.py.
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openWorkspace(page);
  await expect(page.locator("body")).toHaveClass(/^dashboard-page insights-page(\s|$)/);
  await expect(page.locator("main.main-container")).toHaveCSS("max-width", "1320px");
});

test("members do not see the AI Signals view", async ({ page }) => {
  await openWorkspace(page, "member");
  await expect(page.locator("#signals-tab")).toBeHidden();
  await expect(page.locator('[data-view-panel="signals"]')).toBeHidden();
});

test("legacy Reports entry lands in the Performance view", async ({ page }) => {
  await page.addInitScript(({ botId }) => {
    sessionStorage.setItem("token", "test-token");
    sessionStorage.setItem("selectedBotId", botId);
    sessionStorage.setItem("user", JSON.stringify({ role: "owner", full_name: "Test user" }));
  }, { botId: BOT_ID });
  await page.route("**/api/**", route => route.fulfill(json({ status: "success", data: { bot_name: "Support Bot", total_users: 0, total_messages: 0, chart: { labels: [], data: [] }, leads: [] } })));
  await page.goto(`/reports.html?bot_id=${BOT_ID}`, { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/crm\.html\?bot_id=42&view=performance$/);
});

for (const flags of [{ crm_lead_assignment: false, ai_generated_reports: false }, {}]) {
  test(`server flags fail closed for assignment and reports: ${JSON.stringify(flags)}`, async ({ page }) => {
    await openWorkspace(page, "owner", flags);
    await page.locator("#leads-tab").click();
    await expect(page.getByRole("textbox", { name: "Assigned staff member" }).first()).toBeDisabled();
    const requestPromise = page.waitForRequest(request => request.method() === "PATCH" && request.url().includes("/api/crm/leads/"));
    await page.locator("#leads-table-body tr").nth(1).getByRole("button", { name: "Save", exact: true }).click();
    expect((await requestPromise).postDataJSON()).not.toHaveProperty("assigned_to");
    await page.getByRole("tab", { name: "Performance" }).click();
    await expect(page.locator("#generate-report")).toBeDisabled();
  });
}
