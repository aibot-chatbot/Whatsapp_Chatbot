/* Regression coverage for the first-load failure on frontend/bots.html.
 *
 * ROOT CAUSE (reproduced 2026-08-26): bots.html loaded lucide from a CDN as a
 * render-blocking script and then called lucide.createIcons() as the FIRST
 * statement of its inline block. When that CDN was slow, blocked or briefly
 * unavailable, the statement threw ReferenceError, which aborted the whole
 * inline script. requireLogin() never ran and the DOMContentLoaded listener
 * was never registered, so fetchBots() was never called and the page sat on
 * its hardcoded skeleton forever. A reload appeared to fix it only because
 * the retry was served from the browser HTTP cache.
 *
 * The rule these tests defend: rendering icons is decoration, and decoration
 * must never gate data loading.
 */

const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let staticServer;

test.beforeAll(async () => { staticServer = await startServer(); });
test.afterAll(async () => {
    if (staticServer) await new Promise(r => staticServer.close(r));
});

function json(status, body) {
    return { status, contentType: "application/json", body: JSON.stringify(body) };
}

const BOTS = [
    { id: 7, bot_name: "Support Bot", bot_description: "Answers billing questions.",
      language: "English", config_tone: "Friendly", is_active: true }
];

const USAGE = {
    period: { start: "2026-08-01T00:00:00Z", end: "2026-09-01T00:00:00Z" },
    plan: { id: 2, name: "Essential", code: "essential" },
    usage: { chatbots: { used: 1, limit: 2 } }
};

async function open(page, options) {
    const opts = options || {};
    await page.addInitScript(() => {
        sessionStorage.setItem("token", "fake-tenant-token");
        sessionStorage.setItem("isLoggedIn", "true");
        sessionStorage.setItem("user", JSON.stringify({ id: 1, company_id: 42, role: "owner" }));
    });
    await page.route("https://fonts.googleapis.com/**", r => r.abort());
    await page.route("https://fonts.gstatic.com/**", r => r.abort());

    if (opts.blockCdn) {
        await page.route("https://unpkg.com/**", r => r.abort());
    } else {
        await page.route("https://unpkg.com/**", r => r.fulfill({
            status: 200, contentType: "application/javascript",
            body: "window.lucide={createIcons:function(){}};"
        }));
    }

    let botsCalls = 0;
    await page.route("**/api/**", route => {
        const p = new URL(route.request().url()).pathname;
        if (p === "/api/bots") {
            botsCalls += 1;
            if (opts.failFirstN && botsCalls <= opts.failFirstN) {
                return route.fulfill(json(503, { status: "error", message: "Service unavailable" }));
            }
            return route.fulfill(json(200, { status: "success", data: BOTS }));
        }
        if (p === "/api/billing/usage") {
            return route.fulfill(json(200, { status: "success", data: USAGE }));
        }
        if (p === "/api/platform-admin/me") {
            return route.fulfill(json(403, { status: "error" }));
        }
        return route.fulfill(json(200, { status: "success", data: [] }));
    });

    await page.goto("/bots.html");
    return () => botsCalls;
}

test.describe("bots.html first load", () => {
    test("loads the bot list when the icon CDN is available", async ({ page }) => {
        await open(page);
        await expect(page.locator(".glass-card")).toHaveCount(1);
        await expect(page.locator(".bot-title")).toHaveText("Support Bot");
    });

    test("still loads the bot list when the icon CDN is unreachable", async ({ page }) => {
        // This is the reported bug. Icons are allowed to be missing; the data
        // is not. Before the fix this left the page on its skeleton forever
        // and never issued a single API request.
        const calls = await open(page, { blockCdn: true });

        await expect(page.locator(".glass-card")).toHaveCount(1);
        await expect(page.locator(".bot-title")).toHaveText("Support Bot");
        expect(calls(), "fetchBots must run even with no icon library").toBeGreaterThan(0);
        await expect(page.locator("#bots-grid .skeleton-row")).toHaveCount(0);
    });

    test("a transient server error recovers without the user reloading", async ({ page }) => {
        // The user should never be shown a dead end they have to click out of
        // for a blip that resolves on its own.
        const calls = await open(page, { failFirstN: 2 });

        await expect(page.locator(".glass-card")).toHaveCount(1, { timeout: 20000 });
        expect(calls(), "should have retried past the failures").toBeGreaterThan(2);
    });

    test("keeps a live loading state visible while it retries", async ({ page }) => {
        await open(page, { failFirstN: 2 });
        // Something must still say "working" rather than "failed" during the
        // automatic recovery.
        await expect(page.locator("#bots-grid .skeleton-row").first()).toBeVisible();
        await expect(page.locator(".glass-card")).toHaveCount(1, { timeout: 20000 });
    });
});
