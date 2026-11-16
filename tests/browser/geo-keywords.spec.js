const os = require("os");
const path = require("path");
const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let staticServer;

test.beforeAll(async () => { staticServer = await startServer(); });
test.afterAll(async () => {
  if (staticServer) await new Promise(resolve => staticServer.close(resolve));
});

function response(data) {
  return { status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data }) };
}

const capabilities = {
  plan: { code: "pro", label: "Pro" },
  limits: { keywords: 10, prompts: 4, executions: 1, monthly_executions: 120, history: 50 },
  usage: { used: 0, remaining: 120, resets_at: "2026-11-01T00:00:00Z" },
  platforms: {
    chatgpt: { configured: true, included: true, mode: "official_api" },
    gemini: { configured: false, included: true, mode: "official_api" },
    claude: { configured: false, included: true, mode: "official_api" },
    deepseek: { configured: false, included: true, mode: "official_api" },
    perplexity: { configured: false, included: true, mode: "official_api" }
  }
};

async function prepare(page, capture) {
  await page.addInitScript(() => {
    sessionStorage.setItem("token", "geo-browser-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify({ id: 1, company_id: 42, role: "owner" }));
  });
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("https://unpkg.com/**", route => route.fulfill({
    status: 200, contentType: "application/javascript", body: "window.lucide={createIcons:function(){}};"
  }));
  await page.route("**/api/**", async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/geo/capabilities") return route.fulfill(response(capabilities));
    if (pathname === "/api/geo/analyses" && request.method() === "GET") return route.fulfill(response([]));
    if (pathname === "/api/geo/analyses" && request.method() === "POST") {
      capture.body = request.postDataJSON();
      const topic = `Keyword topic: ${capture.body.keywords.join(" · ")}`;
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
        status: "success",
        data: {
          id: "11111111-1111-4111-8111-111111111111", status: "complete",
          brand_name: capture.body.brand_name, country: "MY", created_at: "2026-10-26T12:00:00Z",
          platforms: ["chatgpt"], prompts: [topic],
          methodology: { formula: "60% mention rate + 40% mention-rank prominence", keywords: capture.body.keywords, notes: "Keyword topic test." },
          metrics: { geo_score: 0, mention_rate: 0, sample_size: 1, successful_samples: 1,
            mentioned_samples: 0, mention_rate_confidence_interval: { lower: 0, upper: 79.35 },
            platform_summary: { chatgpt: { mention_rate: 0, successful_samples: 1,
              mentioned_samples: 0, average_mention_rank: null, mention_rank_prominence: 0,
              sample_quality: "insufficient", minimum_reliable_samples: 3 } },
            findings: [], rolling_summary: { minimum_reliable_samples: 3, platform_summary: {}, overall: {} } },
          executions: [{ prompt_index: 0, prompt: topic, platform: "chatgpt", model: "test",
            request_status: "complete", brand_mentioned: false, recommendation_position: null,
            raw_response: "1. Example provider", citations: [] }]
        }
      }) });
    }
    return route.fulfill(response({}));
  });
}

test("creates removable keyword chips, enforces ten, and submits one topic", async ({ page }) => {
  const capture = {};
  const errors = [];
  page.on("console", message => {
    const text = message.text();
    const expectedExternalNoise = text.includes("integrity' attribute") || text.includes("Failed to load resource");
    if (message.type() === "error" && !expectedExternalNoise) errors.push(text);
  });
  await prepare(page, capture);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/geo-analysis.html");
  await expect(page).toHaveTitle(/GEO Analysis/);
  await expect(page.locator("#geo-workspace")).toBeVisible();

  const input = page.locator("#geo-keyword-input");
  await input.fill("AI chatbot Malaysia");
  await input.press("Enter");
  await expect(page.locator(".geo-keyword-chip")).toHaveCount(1);
  await expect(page.locator("#geo-keyword-counter")).toHaveText("1 / 10");

  await page.locator('[data-keyword-example="WhatsApp automation"]').click();
  await expect(page.locator(".geo-keyword-chip")).toHaveCount(2);
  await page.locator(".geo-keyword-chip button").first().click();
  await expect(page.locator(".geo-keyword-chip")).toHaveCount(1);

  for (let index = 1; index <= 9; index += 1) {
    await input.fill(`buyer intent ${index}`);
    await input.press("Enter");
  }
  await expect(page.locator("#geo-keyword-counter")).toHaveText("10 / 10");
  await input.fill("eleventh keyword");
  await input.press("Enter");
  await expect(page.locator("#geo-keyword-error")).toContainText("up to 10 keywords");
  await expect(page.locator(".geo-keyword-chip")).toHaveCount(10);
  await expect(page.locator("#geo-run-equation")).toContainText("AI models: 1");
  await expect(page.locator("#geo-run-equation")).toContainText("provider checks: 1");

  await input.fill("");
  await page.locator("#geo-brand").fill("Omnexa");
  await page.locator("#geo-submit").click();
  await expect(page.locator("#geo-results")).toBeVisible();
  expect(capture.body.keywords).toHaveLength(10);
  expect(capture.body).not.toHaveProperty("prompts");
  expect(errors).toEqual([]);
  await page.screenshot({ path: path.join(os.tmpdir(), "omnexa-geo-keywords-desktop.png"), fullPage: true });
});

test("keyword field wraps without horizontal overflow on mobile", async ({ page }) => {
  const capture = {};
  await prepare(page, capture);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/geo-analysis.html");
  const input = page.locator("#geo-keyword-input");
  for (const keyword of ["AI chatbot Malaysia", "WhatsApp automation", "customer service AI", "small business support"]) {
    await input.fill(keyword);
    await input.press("Enter");
  }
  await expect(page.locator(".geo-keyword-chip")).toHaveCount(4);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
  await page.screenshot({ path: path.join(os.tmpdir(), "omnexa-geo-keywords-mobile.png"), fullPage: true });
});

test("a signed-out visitor is sent to the sign-in page", async ({ page }) => {
  // The page's requireLogin() call is assets/js/require-login.js, loaded by AppLayout. Every API answers
  // 200, so a 401 logout cannot redirect in its place. Replaces the "requireLogin();" source pin.
  await page.route(/^https:/, route => route.abort());
  await page.route("**/api/**", route => route.fulfill(response(capabilities)));
  await page.goto("/geo-analysis.html");
  await expect(page).toHaveURL(/\/login\.html$/);
});
