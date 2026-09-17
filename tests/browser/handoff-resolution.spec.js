const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let server;
let origin;
test.beforeAll(async () => {
  server = await startServer(0);
  origin = `http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async () => { if (server) await new Promise(resolve => server.close(resolve)); });

async function openConversation(page, world) {
  await page.addInitScript(() => {
    sessionStorage.setItem("token", "fake-tenant-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify({ id: 1, company_id: 42, role: "owner", email: "owner@example.test" }));
  });
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url());
    let data = [];
    if (url.pathname === "/api/conversations") data = [{
      id: 10, chatbot_id: 7, bot_name: "Support bot", customer_name: "Test customer",
      source_channel: world.channel || "telegram", updated_at: "2026-09-14T00:00:00Z", message_count: 1
    }];
    if (url.pathname === "/api/crm/leads") data = { leads: [] };
    if (url.pathname.endsWith("/messages")) data = [{
      id: 1, sender_type: "customer", message_text: "I need a human", created_at: "2026-09-14T00:00:00Z"
    }];
    if (url.pathname === "/api/agent/escalations") {
      if (url.searchParams.has("conversation_id")) {
        expect(url.searchParams.get("conversation_id")).toBe("10");
        if (world.refreshFails) return route.abort("failed");
      }
      data = world.actions.map(id => ({ id, chatbot_id: 7, conversation_id: 10, intent: "handoff_request", status: "detected" }));
    }
    if (url.pathname.endsWith("/resolve")) {
      const action = Number(url.pathname.split("/").at(-2));
      world.resolved.push(action);
      world.actions = world.actions.filter(id => id !== action);
      data = { already_resolved: false, ai_resumed: !world.legacyPaused && !world.actions.length,
        notification_status: world.notificationFailed ? "failed" : "sent" };
    }
    if (url.pathname.endsWith('/agent-reply') && world.replyError) {
      return route.fulfill({ status: world.replyError.status, contentType: 'application/json',
        body: JSON.stringify({ status: 'error', code: world.replyError.code, message: world.replyError.message }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data }) });
  });
  await page.goto(`${origin}/conversations.html?conversation_id=10`);
  await expect(page.locator("#conv-resolve-btn")).toBeVisible();
}

test("resolving one handoff retains Awaiting human until all requests are resolved", async ({ page }) => {
  const world = { actions: [100, 101], resolved: [] };
  await openConversation(page, world);
  await page.locator("#conv-resolve-btn").click();
  await expect(page.locator("#conv-compose-status")).toContainText("AI replies remain paused");
  await expect(page.locator("#conv-escalated-pill")).toBeVisible();
  expect(world.actions).toHaveLength(1);
  await page.locator("#conv-resolve-btn").click();
  await expect(page.locator("#conv-compose-status")).toContainText("AI replies resume with the next customer message");
  await expect(page.locator("#conv-escalated-pill")).toBeHidden();
  await expect(page.locator("#conv-resolve-btn")).toBeHidden();
  expect(world.resolved).toEqual([101, 100]);
  await page.screenshot({ path: test.info().outputPath("handoff-all-resolved.png"), fullPage: true });
});

test("failed handoff refresh stays paused and allows an idempotent retry", async ({ page }) => {
  const world = { actions: [100], resolved: [], refreshFails: true };
  await openConversation(page, world);
  await page.locator("#conv-resolve-btn").click();
  await expect(page.locator("#conv-compose-status")).toContainText("Could not confirm the handoff status");
  await expect(page.locator("#conv-escalated-pill")).toBeVisible();
  await expect(page.locator("#conv-resolve-btn")).toBeEnabled();
  world.refreshFails = false;
  await page.locator("#conv-resolve-btn").click();
  await expect(page.locator("#conv-resolve-btn")).toBeHidden();
});

test("Telegram closure delivery failure is visible after successful resolution", async ({ page }) => {
  const world = { actions: [100], resolved: [], notificationFailed: true };
  await openConversation(page, world);
  await page.locator("#conv-resolve-btn").click();
  await expect(page.locator("#conv-compose-status")).toContainText("end-of-service message could not be delivered to Telegram");
  await expect(page.locator("#conv-escalated-pill")).toBeHidden();
});

for (const channel of ['telegram', 'whatsapp', 'wasender']) {
  test(`${channel} rejected staff reply preserves the draft and shows the provider failure`, async ({ page }) => {
    const world = { actions: [100], resolved: [], channel, replyError: {
      status: 409, code: 'CHANNEL_REPLACED', message: 'This conversation belongs to a previous bot or number.'
    } };
    await openConversation(page, world);
    await page.locator('#conv-reply-text').fill('This draft must remain available.');
    await page.locator('#conv-reply-send').click();
    await expect(page.locator('#conv-compose-status')).toContainText('previous bot or number');
    await expect(page.locator('#conv-reply-text')).toHaveValue('This draft must remain available.');
    await expect(page.locator('#conv-escalated-pill')).toBeVisible();
    world.replyError = { status: 502, code: 'DELIVERY_FAILED', message: 'The provider did not accept the message. Try again.' };
    await page.locator('#conv-reply-send').click();
    await expect(page.locator('#conv-compose-status')).toContainText('provider did not accept');
    await expect(page.locator('#conv-reply-text')).toHaveValue('This draft must remain available.');
    await expect(page.locator('#conv-reply-send')).toBeEnabled();
  });
}

test('Resolve preserves the server-reported legacy handoff pause', async ({ page }) => {
  const world = { actions: [100], resolved: [], legacyPaused: true };
  await openConversation(page, world);
  await page.locator('#conv-resolve-btn').click();
  await expect(page.locator('#conv-compose-status')).toContainText('AI replies remain paused');
  await expect(page.locator('#conv-compose-status')).not.toContainText('AI replies resume with');
});
