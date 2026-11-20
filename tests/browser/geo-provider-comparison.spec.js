"use strict";

/*
 * geo-provider-comparison.html, the first legacy app page moved onto AppLayout (F2 slice S3).
 * Behaviour checks from the F2 design, section 8, plus the page copy that tests/test_geo_frontend.py
 * used to pin in the HTML source. Every request stays local: https is aborted and /api/* is mocked.
 */

const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let server;
test.beforeAll(async () => { server = await startServer(); });
test.afterAll(async () => { if (server) await new Promise(resolve => server.close(resolve)); });

const ok = data => ({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data }) });
const CAPABILITIES = { comparison: { enabled: true, direct_openai_configured: true, openrouter_configured: true } };
const routeResult = citation => ({
  request_status: "complete", model: "gpt-search", latency_ms: 840, cost_usd: 0.01234,
  raw_response: "A provider answer.", citations: [citation], provider_metadata: { route: ["Omnexa", "OpenAI API"] }
});
const COMPARISON = {
  prompt: "Which WhatsApp automation providers are best for Malaysian SMEs?", country: "MY", language: "en",
  comparison: { answer_term_overlap_percent: 40, citation_domain_overlap_percent: 50 },
  direct: routeResult({ url: "https://example.com/direct", domain: "example.com" }),
  openrouter: routeResult({ url: "https://example.org/gateway", domain: "example.org" })
};

// Opens the page with a bot in the URL and in the session; it is a workspace page, so that bot must be ignored.
async function openComparison(page, { signedIn = true, comparison = route => route.fulfill(ok(COMPARISON)) } = {}) {
  const posts = [];
  await page.addInitScript(signedIn => {
    sessionStorage.setItem("selectedBotId", "7");
    if (!signedIn) return;
    sessionStorage.setItem("token", "geo-route-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify({ id: 1, company_id: 42, role: "owner", status: "active" }));
  }, signedIn);
  // Fonts and lucide: the page and the sidebar work without them.
  await page.route(/^https:/, route => route.abort());
  // Every API answers 200, so a 401 logout can never redirect in place of the page's own sign-in gate.
  await page.route("**/api/**", route => {
    const { pathname } = new URL(route.request().url());
    if (pathname === "/api/geo/capabilities") return route.fulfill(ok(CAPABILITIES));
    if (pathname === "/api/geo/provider-comparison" && route.request().method() === "POST") {
      posts.push(route.request().postDataJSON());
      return comparison(route);
    }
    return route.fulfill(ok({}));
  });
  await page.goto("/geo-provider-comparison.html?bot_id=7");
  return posts;
}

test("keeps workspace scope with a bot selected and marks GEO Analysis as the current page", async ({ page }) => {
  await openComparison(page);
  const sidebar = page.locator("chatbot-sidebar");
  await expect(sidebar.getByRole("link", { name: "GEO Analysis", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(sidebar.getByRole("link", { name: "Conversations", exact: true })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "Campaigns", exact: true })).toHaveCount(0);
});

test("names both routes and what one run costs", async ({ page }) => {
  // Moved from tests/test_geo_frontend.py (page-copy pins). The badge said "Two paid API calls" until
  // 6319ae4 changed it to the monthly check allowance a run reserves.
  await openComparison(page);
  await expect(page.locator(".route-map")).toContainText("Omnexa");
  await expect(page.locator("#route-openrouter-card h3")).toHaveText("OpenRouter → OpenAI");
  await expect(page.locator(".route-lab-badge")).toHaveText("2 monthly provider checks");
});

test("a submit sends one comparison request, even if submitted again while it runs", async ({ page }) => {
  let release;
  const held = new Promise(resolve => { release = resolve; });
  const posts = await openComparison(page, { comparison: async route => { await held; return route.fulfill(ok(COMPARISON)); } });
  await expect(page.locator("#route-submit")).toBeEnabled();

  await page.locator("#route-submit").click();
  await expect.poll(() => posts.length).toBe(1);
  // A second submit while the first is in flight (Enter in a field, a double click) must not charge again.
  await page.locator("#route-form").evaluate(form => form.requestSubmit());
  await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 300))); // room for a second request to leave
  release();

  await expect(page.locator("#route-results")).toBeVisible();
  expect(posts).toEqual([{ prompt: COMPARISON.prompt, country: "MY", language: "en" }]);
});

test("citation links open in a new tab without handing over the page", async ({ page }) => {
  await openComparison(page);
  await page.locator("#route-submit").click();
  const links = page.locator("#route-direct-citations a, #route-openrouter-citations a");
  await expect(links).toHaveCount(2);
  for (const link of await links.all()) {
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(link).toHaveAttribute("target", "_blank");
  }
});

test("a signed-out visitor is sent to the sign-in page", async ({ page }) => {
  await openComparison(page, { signedIn: false });
  await expect(page).toHaveURL(/\/login\.html$/);
});
