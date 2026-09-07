const { test, expect } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");
const path = require("path");

let server;
let base;
test.beforeAll(async () => { server = await startServer(0); base = `http://127.0.0.1:${server.address().port}`; });
test.afterAll(async () => { if (server) await new Promise(resolve => server.close(resolve)); });

const paging = (rows, offset = 0, total = rows.length) => ({ offset, limit: 25, returned: rows.length, total, has_more: offset + rows.length < total });
const now = "2026-09-07T01:00:00Z";
function fixtures() {
  const company = { id: 42, company_id: 42, company_name: "Tenant <img src=x onerror=window.injected=true>", status: "active", contact_email: "tenant@example.test", created_at: now };
  const billing = { ...company, subscription_status: "active", current_plan: { name: "Growth", code: "growth" }, current_period_end: now, ai_credit_total_balance_micro_myr: 2000000, subscription_order_attention: { pending_count: 1, failed_count: 2, reconciliation_required_count: 1 } };
  const person = { platform_admin_user_id: 9, user_id: 99, user_email: "staff@example.test", user_full_name: "Test Staff", platform_role: "admin", modules: { billing: true, support: false, customers: true }, is_active: true };
  const approval = { id: 7, type: "manual_payment", company_id: 42, summary: "Review supporting receipt", reason: "Check the manual receipt before proceeding", status: "pending", requester_platform_admin_user_id: 9, created_at: now, execution_status: "not_executed" };
  const ticket = { id: 5, company_id: 42, company: { company_name: "Tenant" }, title: "Invoice inquiry", redacted_summary: "An invoice needs review", status: "open", priority: "normal", assigned_platform_admin_user_id: 9 };
  const order = { id: 31, status: "pending", amount_sen: 38900, new_plan: { name: "Growth" }, created_at: now, reconciliation_required: true };
  return { company, billing, person, approval, ticket, order, events: [], replies: [] };
}
async function setup(page, override) {
  const state = fixtures(), calls = [];
  await page.addInitScript(() => { sessionStorage.setItem("token", "mock-superadmin-token"); sessionStorage.setItem("user", JSON.stringify({ id: 1, email: "test@example.test", role: "admin" })); });
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.replace("/api/platform-admin", "");
    const call = { path, method: request.method(), body: request.postDataJSON(), query: Object.fromEntries(url.searchParams) }; calls.push(call);
    const custom = override ? await override(call, state) : null;
    if (custom) { await route.fulfill({ status: custom.status || 200, contentType: "application/json", body: JSON.stringify(custom.body) }); return; }
    let data;
    if (path === "/me") data = { user: { id: 1, full_name: "Test Super Admin", email: "super@example.test" }, platform_admin: { id: 1, is_active: true }, platform_role: "super_admin", modules: { billing: true, support: true, customers: true }, landing_page: "superadmin.html" };
    else if (path === "/overview") data = { generated_at: now, companies: { active: 4 }, subscriptions: { by_status: { active: 3, trialing: 0, past_due: 0, expired: 0, cancelled: 0 }, by_plan: [{ code: "growth", name: "Growth", count: 3 }] }, operational_alerts: { alerts: [] } };
    else if (path === "/billing/overview") data = { generated_at: now, subscription_orders: { pending_count: 2, failed_count: 1, reconciliation_required_count: 1 } };
    else if (path === "/billing/companies") data = { companies: [state.billing], pagination: paging([state.billing]) };
    else if (path === "/companies") { const rows = !call.query.search || state.company.company_name.includes(call.query.search) ? [state.company] : []; data = { companies: rows, pagination: paging(rows) }; }
    else if (path === "/companies/42") data = state.company;
    else if (path === "/companies/42/subscription") data = { company: state.company, subscription: { id: 2, status: "active", plan: { name: "Growth" }, current_period_end: now } };
    else if (path === "/companies/42/ai-credit-usage") data = { credit_balance: { initialized: false }, period: {} };
    else if (path === "/companies/42/billing-orders") data = { billing_orders: [state.order], pagination: paging([state.order]) };
    else if (path === "/companies/42/billing-orders/31/recheck") data = { order: state.order, source: "existing_reconciliation", outcome: "still_pending" };
    else if (path === "/platform-admin-users" && call.method === "POST") { state.person.user_id = call.body.user_id; state.person.modules = { billing: false, support: false, customers: false }; data = { platform_admin_user: state.person }; }
    else if (path === "/platform-admin-users") data = { platform_admin_users: [state.person], pagination: paging([state.person]) };
    else if (path === "/platform-admin-users/9") data = { platform_admin_user: state.person };
    else if (path === "/platform-admin-users/9/access") { Object.assign(state.person, call.body); data = { platform_admin_user: state.person }; }
    else if (path === "/approval-requests") data = { requests: [state.approval], pagination: paging([state.approval]) };
    else if (path === "/approval-requests/7") data = { request: state.approval };
    else if (path === "/approval-requests/7/decision") { Object.assign(state.approval, { status: call.body.status, decision_reason: call.body.reason, reviewed_at: now }); data = { request: state.approval }; }
    else if (path === "/support-cases") data = { cases: [state.ticket], pagination: paging([state.ticket]) };
    else if (path === "/tenant-support-requests") data = { requests: [{ request_id: 8, company_id: 42, status: "open", category: "account", created_at: now }], pagination: paging([{}]) };
    else if (path === "/tenant-support-requests/8") data = { request: { request_id: 8, company_id: 42, title: "Customer question", redacted_description: "Please help", status: "open" } };
    else if (path === "/tenant-support-requests/8/convert") data = { converted_platform_support_case_id: 5 };
    else if (path === "/support-cases/5") data = { case: state.ticket, events: state.events, events_pagination: paging(state.events), status_transitions: state.ticket.status === "resolved" ? ["in_progress"] : ["resolved", "in_progress"], source_tenant_request: { request_id: 8 } };
    else if (path === "/support-cases/5/replies" && call.method === "GET") data = { replies: state.replies, pagination: paging(state.replies) };
    else if (path === "/support-case-assignees") data = { assignees: [{ id: 9, user_email: "staff@example.test", user_full_name: "Test Staff" }] };
    else if (path === "/support-cases/5/notes") { state.events.push({ redacted_note: call.body.redacted_note, created_at: now }); data = { case: state.ticket }; }
    else if (path === "/support-cases/5/replies") { state.replies.push({ redacted_body: call.body.redacted_body, created_at: now }); data = { reply: state.replies.at(-1) }; }
    else if (path === "/support-cases/5/status") { state.ticket.status = call.body.status; data = { case: state.ticket }; }
    else if (path === "/help/articles") data = { articles: [{ id: 2, title: "Billing help", category: "billing_question", body: "Contact the billing team", is_published: false }] };
    else if (path === "/audit-events") data = { audit_events: [{ id: 4, action: "platform_admin.company.read", resource_type: "company", resource_id: "42", created_at: now }], pagination: paging([{}]) };
    else { await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ status: "error", code: "unexpected_unmocked_api" }) }); return; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data }) });
  });
  return { state, calls };
}

test("all ten sections use server records and keep untrusted content inert", async ({ page }, testInfo) => {
  const errors = []; page.on("pageerror", error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await setup(page);
  await page.goto(`${base}/superadmin.html`);
  await expect(page.getByRole("heading", { name: "Subscriptions by plan" })).toBeVisible();
  await expect(page.locator(".metric-value").first()).toHaveText("4");
  await page.screenshot({ path: process.env.PORTAL_SCREENSHOT_DIR ? path.join(process.env.PORTAL_SCREENSHOT_DIR, "superadmin-desktop.png") : testInfo.outputPath("superadmin-desktop.png"), fullPage: true });
  for (const [hash, title] of [["payments", "Payments"], ["customers", "Customers"], ["subscriptions", "Subscriptions"], ["support", "Help Desk"], ["approvals", "Approvals"], ["team", "Team & permissions"], ["help", "Help articles"], ["activity", "Activity log"], ["settings", "Settings"]]) {
    await page.locator(`#navigation a[href='#${hash}']`).click();
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    if (hash !== "settings") await expect(page.locator("#list-content .table-total")).toBeVisible();
  }
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  expect(errors).toEqual([]);
  await page.goto(`${base}/superadmin.html#customers`);
  await page.locator("#list-search").fill("missing");
  await expect(page.getByRole("heading", { name: "No matching records" })).toBeVisible();
  await page.getByRole("button", { name: "Clear list search" }).click();
  await expect(page.getByText("Tenant <img src=x onerror=window.injected=true>", { exact: true })).toBeVisible();
});

test("a failed approval is never shown as approved; a recorded decision is never shown as executed", async ({ page }) => {
  let fail = true;
  const { calls } = await setup(page, call => call.path.endsWith("/decision") && fail ? { status: 503, body: { status: "error" } } : null);
  await page.goto(`${base}/superadmin.html#approvals`);
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await page.getByRole("button", { name: "Approve request", exact: true }).click();
  await page.locator("#confirm-submit").click();
  await expect(page.locator("#confirm-error")).toContainText("at least 3");
  expect(calls.filter(call => call.path.endsWith("/decision"))).toHaveLength(0);
  await page.getByLabel("Reason Required").fill("Receipt has been reviewed");
  await page.locator("#confirm-submit").click();
  await expect(page.locator("#confirm-error")).toContainText("could not");
  expect(calls.filter(call => call.path.endsWith("/decision"))).toHaveLength(1);
  await expect(page.locator("#detail-content .status")).toHaveText("Pending");
  fail = false;
  await page.locator("#confirm-submit").click();
  await expect(page.locator("#confirm-dialog")).not.toBeVisible();
  await expect(page.locator("#detail-content .status")).toHaveText("Approved");
  await expect(page.locator("#detail-content")).toContainText("Not executed");
  await expect(page.locator("#detail-content [data-action=approve]")).toHaveCount(0);
});

test("permission editing sends explicit module booleans and server-confirmed role", async ({ page }) => {
  const { calls } = await setup(page);
  await page.goto(`${base}/superadmin.html#team`);
  await page.getByRole("button", { name: "Edit access" }).click();
  await page.locator("#module-billing").uncheck();
  await page.locator("#module-support").check();
  await page.getByRole("button", { name: "Review permission changes" }).click();
  await page.locator("#confirm-reason").fill("Support responsibilities assigned");
  await page.locator("#confirm-submit").click();
  await expect(page.locator("#confirm-dialog")).not.toBeVisible();
  expect(calls.find(call => call.path.endsWith("/access")).body).toEqual({ platform_role: "admin", modules: { billing: false, support: true, customers: true }, reason: "Support responsibilities assigned" });
  await expect(page.locator("#module-billing")).not.toBeChecked();
});

test("support keeps private notes separate from confirmed public replies and maps status transitions", async ({ page }) => {
  const { calls } = await setup(page);
  await page.goto(`${base}/superadmin.html#support`);
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await page.getByRole("button", { name: "Private note", exact: true }).click();
  await page.locator("#message-body").fill("Internal coordination note");
  await page.getByRole("button", { name: "Save private note" }).click();
  await expect(page.locator(".support-message.private")).toContainText("Internal coordination note");
  await page.getByRole("button", { name: "Reply to customer", exact: true }).click();
  await page.locator("#message-body").fill("Your invoice is being reviewed");
  await page.getByRole("button", { name: "Review customer reply" }).click();
  expect(calls.filter(call => call.method === "POST" && call.path.endsWith("/replies"))).toHaveLength(0);
  await page.locator("#confirm-submit").click();
  await expect(page.locator("#confirm-dialog")).not.toBeVisible();
  await expect(page.locator(".support-message:not(.private)")).toContainText("Your invoice is being reviewed");
  await page.getByRole("button", { name: "Resolved", exact: true }).click();
  await page.locator("#confirm-submit").click();
  await expect(page.getByRole("button", { name: "Reopen case" })).toBeVisible();
});

test("server denial clears customer data and closes the active drawer", async ({ page }) => {
  let denied = false;
  await setup(page, call => call.path === "/companies/42/billing-orders" && denied ? { status: 403, body: { status: "error", code: "platform_admin_access_denied" } } : null);
  await page.goto(`${base}/superadmin.html#customers`);
  await page.getByRole("button", { name: "View", exact: true }).click();
  denied = true;
  await page.getByRole("button", { name: "View payments", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Access Denied", exact: true })).toBeVisible();
  await expect(page.locator("#platform-app")).not.toBeVisible();
  await expect(page.locator("#detail-dialog")).not.toBeVisible();
  await expect(page.locator("#main")).toBeEmpty();
});

test("payment recheck preserves sen units and confirms possible paid-order activation", async ({ page }) => {
  const { calls } = await setup(page);
  await page.goto(`${base}/superadmin.html#payments`);
  await page.getByRole("button", { name: "View payments", exact: true }).click();
  await page.getByRole("button", { name: "Details", exact: true }).click();
  await expect(page.locator(".detail-amount")).toContainText("38,900");
  await page.getByRole("button", { name: "Recheck payment" }).click();
  await expect(page.locator("#confirm-description")).toContainText("retry activation");
  expect(calls.filter(call => call.method === "POST")).toHaveLength(0);
  await page.locator("#confirm-submit").click();
  await expect(page.locator("#toast")).toContainText("Payment recheck completed");
  await expect(page.locator("#detail-operation-error")).toContainText("Still Pending");
  expect(calls.filter(call => call.method === "POST").map(call => call.path)).toEqual(["/companies/42/billing-orders/31/recheck"]);
});

test("narrow layout keeps navigation and drawer usable without document overflow", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  await page.goto(`${base}/superadmin.html#overview`);
  await expect(page.getByRole("heading", { name: "Subscriptions by plan" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: process.env.PORTAL_SCREENSHOT_DIR ? path.join(process.env.PORTAL_SCREENSHOT_DIR, "superadmin-mobile.png") : testInfo.outputPath("superadmin-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.locator("#navigation a[href='#approvals']").click();
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await expect(page.locator("#detail-dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#detail-dialog")).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("new staff starts with no modules and opens its explicit permission editor", async ({ page }) => {
  const { calls } = await setup(page);
  await page.goto(`${base}/superadmin.html#team`);
  await page.getByRole("button", { name: "Add existing user" }).click();
  await page.getByLabel("Existing user ID").fill("101");
  await page.getByRole("button", { name: "Review access creation" }).click();
  await expect(page.locator("#confirm-description")).toContainText("no assigned modules");
  await page.locator("#confirm-submit").click();
  await expect(page.locator("#confirm-dialog")).not.toBeVisible();
  expect(calls.find(call => call.path === "/platform-admin-users" && call.method === "POST").body).toEqual({ user_id: 101 });
  await expect(page.locator("#module-billing")).not.toBeChecked();
  await expect(page.locator("#module-support")).not.toBeChecked();
  await expect(page.locator("#module-customers")).not.toBeChecked();
});

test("search text remains transient while customer requests and page filters keep working", async ({ page }) => {
  const pii = "alex.private@example.test";
  const { calls } = await setup(page, (call, state) => {
    if (call.path === "/platform-admin-users") return { body: { status: "success", data: { platform_admin_users: [state.person], pagination: paging([state.person], Number(call.query.offset || 0), 50) } } };
    if (call.path !== "/companies") return null;
    const offset = Number(call.query.offset || 0);
    return { body: { status: "success", data: { companies: [state.company], pagination: paging([state.company], offset, 50) } } };
  });
  await page.addInitScript(() => {
    window.searchNavigation = [];
    for (const method of ["pushState", "replaceState"]) {
      const original = history[method].bind(history);
      history[method] = (...args) => { window.searchNavigation.push(String(args[2] || "")); return original(...args); };
    }
    addEventListener("hashchange", () => window.searchNavigation.push(location.hash));
  });
  await page.goto(`${base}/superadmin.html#customers?status=active&offset=25`);
  await page.locator("#list-search").fill(pii);
  await expect.poll(() => calls.filter(call => call.path === "/companies").at(-1)?.query).toMatchObject({ search: pii, status: "active", offset: "0" });
  await expect(page.locator("#list-content .table-total")).toBeVisible();
  expect(new URL(page.url()).hash).toBe("#customers?status=active");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect.poll(() => calls.filter(call => call.path === "/companies").at(-1)?.query).toMatchObject({ search: pii, status: "active", offset: "25" });
  await expect(page.locator("#list-search")).toHaveValue(pii);
  await page.getByRole("button", { name: "Clear list search" }).click();
  await expect(page.locator("#list-search")).toHaveValue("");
  await expect.poll(() => calls.filter(call => call.path === "/companies").at(-1)?.query.search).toBeUndefined();
  await page.locator("#global-search").fill(pii);
  await page.locator("#global-search").press("Enter");
  await expect(page.locator("#list-search")).toHaveValue(pii);
  await expect.poll(() => calls.filter(call => call.path === "/companies").at(-1)?.query.search).toBe(pii);
  expect(new URL(page.url()).hash).toBe("#customers");
  // A second global search on the same hash must trigger a new server request.
  const nextPii = "jamie.private@example.test";
  await page.locator("#global-search").fill(nextPii);
  await page.locator("#global-search").press("Enter");
  await expect.poll(() => calls.filter(call => call.path === "/companies").at(-1)?.query.search).toBe(nextPii);
  await page.locator("#navigation a[href='#team']").click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect.poll(() => calls.filter(call => call.path === "/platform-admin-users").at(-1)?.query.offset).toBe("25");
  await page.locator("#list-search").fill("staff@example.test");
  await expect(page.getByRole("button", { name: "Edit access" })).toBeVisible();
  await page.locator("#list-search").fill("absent@example.test");
  await expect(page.getByRole("heading", { name: "No matching records" })).toBeVisible();
  await page.getByRole("button", { name: "Clear list search" }).click();
  await expect(page.getByRole("button", { name: "Edit access" })).toBeVisible();
  expect(new URL(page.url()).hash).toBe("#team?offset=25");
  await page.locator("#navigation a[href='#customers']").click();
  await expect(page.locator("#list-search")).toHaveValue(nextPii);
  const navigation = await page.evaluate(() => [...window.searchNavigation, location.href]);
  expect(navigation.every(url => !/[?&]q=/.test(url) && !url.includes("example.test") && !url.includes("%40"))).toBe(true);
  await page.reload();
  await expect(page.locator("#list-search")).toHaveValue("");
  await expect.poll(() => calls.filter(call => call.path === "/companies").at(-1)?.query.search).toBeUndefined();
});

test("overview charts encode exact counts and status links open the matching subscription filter", async ({ page }, testInfo) => {
  const { calls } = await setup(page, call => call.path === "/overview" ? { body: { status: "success", data: {
    generated_at: now, companies: { active: 4 }, operational_alerts: { alerts: [] },
    subscriptions: { by_plan: [{ name: "Growth", count: 4 }, { name: "Essential", count: 2 }, { name: "Free", count: 6 }],
      by_status: { active: 6, trialing: 2, past_due: 1, expired: 3, cancelled: 0 } }
  } } } : null);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${base}/superadmin.html`);
  const plans = page.getByRole("region", { name: "Subscriptions by plan", exact: true });
  await expect(plans.locator(".chart-row-label>span")).toHaveText(["Free", "Growth", "Essential"]);
  await expect(plans.locator(".chart-row-label>strong")).toHaveText(["6", "4", "2"]);
  const widths = await plans.locator(".chart-bar").evaluateAll(bars => bars.map(bar => bar.getBoundingClientRect().width));
  expect(widths[0] / widths[2]).toBeCloseTo(3, 1);
  expect(widths[1] / widths[2]).toBeCloseTo(2, 1);
  await expect(page.locator(".status-center strong")).toHaveText("12");
  await expect(page.locator(".status-legend strong")).toHaveText(["6", "2", "1", "3", "0"]);
  const payments = page.getByRole("region", { name: "Payment follow-up", exact: true });
  await expect(payments.locator(".chart-row-label>strong")).toHaveText(["2", "1", "1"]);
  await expect(payments).toContainText("queues may overlap");
  await page.screenshot({ path: testInfo.outputPath("superadmin-charts-desktop.png"), fullPage: true });
  const pastDue = page.locator(".status-legend").getByRole("link", { name: "Past due 1" });
  await pastDue.focus();
  await pastDue.press("Enter");
  await expect(page).toHaveURL(/#subscriptions\?status=past_due$/);
  await expect(page.locator("#status-filter")).toHaveValue("past_due");
  await expect.poll(() => calls.filter(call => call.path === "/billing/companies").at(-1)?.query.subscription_status).toBe("past_due");
});

test("zero and unavailable chart data stay distinct and untrusted plan labels remain text", async ({ page }) => {
  let missing = false, unlisted = false;
  const zeroStatuses = { active: 0, trialing: 0, past_due: 0, expired: 0, cancelled: 0 };
  await setup(page, call => {
    if (call.path === "/overview") return { body: { status: "success", data: {
      generated_at: now, companies: { active: 0 }, operational_alerts: { alerts: [] },
      subscriptions: { by_status: unlisted ? { ...zeroStatuses, active: 7 } : missing ? { active: 7 } : zeroStatuses,
        by_plan: missing && !unlisted ? [{ name: '<img src=x onerror="window.injected=true">', count: null }] : [] }
    } } };
    if (call.path === "/billing/overview") return { body: { status: "success", data: { generated_at: now,
      subscription_orders: missing ? { pending_count: "0", failed_count: -1, reconciliation_required_count: null }
        : { pending_count: 0, failed_count: 0, reconciliation_required_count: 0 } } } };
    return null;
  });
  await page.goto(`${base}/superadmin.html`);
  await expect(page.locator(".status-center strong")).toHaveText("0");
  await expect(page.getByRole("region", { name: "Subscriptions by plan", exact: true })).toContainText("No subscriptions with a listed plan");
  const payments = page.getByRole("region", { name: "Payment follow-up", exact: true });
  await expect(payments.locator(".chart-row-label>strong")).toHaveText(["0", "0", "0"]);
  await expect(payments).toContainText("No records in these categories");
  missing = true;
  await page.getByRole("button", { name: "Refresh records" }).click();
  await expect(page.getByText("Chart unavailable: some status counts are missing.")).toBeVisible();
  await expect(page.locator(".status-donut")).toHaveCount(0);
  await expect(page.locator(".status-legend strong")).toHaveText(["7", "Not available", "Not available", "Not available", "Not available"]);
  await expect(payments.locator(".chart-row-label>strong")).toHaveText(["Not available", "Not available", "Not available"]);
  await expect(page.locator(".chart-bar-row img")).toHaveCount(0);
  await expect(page.getByText('<img src=x onerror="window.injected=true">', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  expect(await page.locator(".chart-bar").evaluateAll(bars => bars.every(bar => Number.isFinite(bar.getBoundingClientRect().width)))).toBe(true);
  unlisted = true;
  await page.getByRole("button", { name: "Refresh records" }).click();
  await expect(page.locator(".status-center strong")).toHaveText("7");
  await expect(page.getByRole("region", { name: "Subscriptions by plan", exact: true })).toContainText("No subscriptions with a listed plan");
  await expect(page.getByText("No subscriptions yet", { exact: true })).toHaveCount(0);
});

test("chart sources fail independently and recover through the existing refresh action", async ({ page }) => {
  let failedPath = "/billing/overview";
  await setup(page, call => call.path === failedPath ? { status: 503, body: { status: "error", code: "platform_admin_data_unavailable" } } : null);
  await page.goto(`${base}/superadmin.html`);
  const plans = page.getByRole("region", { name: "Subscriptions by plan", exact: true });
  const payments = page.getByRole("region", { name: "Payment follow-up", exact: true });
  await expect(payments.getByRole("alert")).toBeVisible();
  await expect(plans.locator(".chart-bar-row")).toHaveCount(1);
  await expect(page.locator(".status-donut")).toBeVisible();
  failedPath = "/overview";
  await page.getByRole("button", { name: "Refresh records" }).click();
  await expect(plans.getByRole("alert")).toBeVisible();
  await expect(page.locator(".status-donut")).toHaveCount(0);
  await expect(payments.locator(".chart-row-label>strong")).toHaveText(["2", "1", "1"]);
  failedPath = null;
  await page.getByRole("button", { name: "Refresh records" }).click();
  await expect(page.locator(".analytics-grid [role=alert]")).toHaveCount(0);
  await expect(page.locator(".status-center strong")).toHaveText("3");
});

test("charts retain readable values on narrow screens and in forced colors", async ({ page }, testInfo) => {
  const longName = "Enterprise".repeat(18);
  await setup(page, call => call.path === "/overview" ? { body: { status: "success", data: {
    generated_at: now, companies: { active: 4 }, operational_alerts: { alerts: [] },
    subscriptions: { by_plan: [{ name: longName, count: 7 }], by_status: { active: 7, trialing: 0, past_due: 0, expired: 0, cancelled: 0 } }
  } } } : null);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/superadmin.html`);
  await expect(page.locator(".status-center strong")).toHaveText("7");
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.locator(".status-chart-link").evaluateAll(links => links.every(link => link.getBoundingClientRect().height >= 44))).toBe(true);
    await expect(page.getByText(longName, { exact: true })).toBeVisible();
  }
  await page.screenshot({ path: testInfo.outputPath("superadmin-charts-mobile.png"), fullPage: true });
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await expect(page.locator(".status-legend strong")).toHaveText(["7", "0", "0", "0", "0"]);
  await expect(page.locator(".status-chart-link").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});


test("staff can read the escaped self-service trail on incoming requests and cases", async ({ page }) => {
  const context = { searches: ["connect <img src=x onerror=window.trailInjected=true>"], viewed: ["Connection help"], unhelpful: ["Link setup"], from_page: "support" };
  await setup(page, (call, state) => {
    if (call.path === "/tenant-support-requests/8") return { body: { status: "success", data: { request: { request_id: 8, company_id: 42, title: "Customer question", status: "new", escalation_context: context } } } };
    if (call.path === "/support-cases/5") return { body: { status: "success", data: { case: state.ticket, events: [], events_pagination: paging([]), status_transitions: [], source_tenant_request: { request_id: 8, escalation_context: context } } } };
    return null;
  });
  for (const [hash, action] of [["support?tab=incoming", "incoming"], ["support", "ticket"]]) {
    await page.goto(`${base}/superadmin.html#${hash}`);
    await page.locator(`#list-content [data-action=${action}]`).first().click();
    const trail = page.getByRole("region", { name: "Self-service trail" });
    await expect(trail).toContainText(context.searches[0]);
    await expect(trail).toContainText("Connection help");
    await expect(trail.locator("img")).toHaveCount(0);
  }
  expect(await page.evaluate(() => window.trailInjected)).toBeUndefined();
});

test("help editor preserves and updates article display order", async ({ page }) => {
  const article = { id: 2, title: "Billing help", category: "billing_question", body: "Contact the billing team", is_published: false, sort_order: 12 };
  const { calls } = await setup(page, call => {
    if (call.path === "/help/articles") return { body: { status: "success", data: { articles: [article] } } };
    if (call.path === "/help/articles/2" && call.method === "PATCH") { Object.assign(article, call.body); return { body: { status: "success", data: { article } } }; }
    return null;
  });
  await page.goto(`${base}/superadmin.html#help`);
  await page.locator('#list-content [data-action=article]').first().click();
  await page.getByRole("button", { name: "Edit article", exact: true }).click();
  await expect(page.getByLabel("Display order", { exact: true })).toHaveValue("12");
  await page.getByLabel("Display order", { exact: true }).fill("3");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.locator("#detail-dialog")).not.toBeVisible();
  expect(calls.find(call => call.method === "PATCH" && call.path === "/help/articles/2").body.sort_order).toBe(3);
});
