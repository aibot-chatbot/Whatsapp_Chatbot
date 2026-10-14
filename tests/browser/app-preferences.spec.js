const fs = require("fs");
const path = require("path");
const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let staticServer;
test.beforeAll(async () => { staticServer = await startServer(); });
test.afterAll(async () => { if (staticServer) await new Promise(resolve => staticServer.close(resolve)); });

test("loads shared preferences on every full page except landing and the embedded widget", async () => {
  const frontend = path.resolve(__dirname, "..", "..", "frontend");
  const excluded = new Set(["landing.html", "training.html", "widget-chat.html"]);
  const pages = fs.readdirSync(frontend).filter(name => name.endsWith(".html") && !excluded.has(name));
  expect(pages.length).toBeGreaterThan(35);
  for (const page of pages) {
    const html = fs.readFileSync(path.join(frontend, page), "utf8");
    expect(html, page).toContain('assets/css/app-preferences.css');
    expect(html, page).toContain('assets/js/app-preferences.js');
  }
});

test("persists language and theme on an auth page", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("omnexa-theme", "light");
    localStorage.setItem("omnexa-language", "zh-CN");
  });
  await page.route(/^https:/, route => route.abort());
  await page.goto("/login.html");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.locator("h1")).toHaveText("登录 Omnexa");
  await expect(page.locator(".omnexa-preferences")).toBeVisible();
  await page.selectOption(".omnexa-preferences select", "ms");
  await expect(page.locator("h1")).toHaveText("Log masuk ke Omnexa");
  await page.click(".omnexa-preferences button");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("keeps native fields and select options readable in light mode", async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem("token", "browser-test-token");
    sessionStorage.setItem("selectedBotId", "1");
    sessionStorage.setItem("user", JSON.stringify({ role: "owner", email: "owner@example.com" }));
    localStorage.setItem("omnexa-theme", "light");
    localStorage.setItem("omnexa-language", "en");
  });
  await page.route(/^https:/, route => route.abort());
  await page.route("**/api/**", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data: {} }) }));
  await page.goto("/index.html?bot_id=1");
  const range = page.locator("#dash-range");
  await expect(range).toBeAttached();
  const palette = await range.evaluate(select => {
    const field = getComputedStyle(select);
    const option = getComputedStyle(select.options[0]);
    return {
      fieldBackground: field.backgroundColor,
      fieldColor: field.color,
      optionBackground: option.backgroundColor,
      optionColor: option.color,
      colorScheme: field.colorScheme
    };
  });
  expect(palette).toMatchObject({
    fieldBackground: "rgb(253, 252, 250)",
    fieldColor: "rgb(35, 36, 31)",
    optionBackground: "rgb(251, 250, 247)",
    optionColor: "rgb(35, 36, 31)"
  });
  expect(palette.colorScheme).toContain("light");
});

test("translates complete dashboard sentences without mixed English", async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem("token", "browser-test-token");
    sessionStorage.setItem("selectedBotId", "1");
    sessionStorage.setItem("user", JSON.stringify({ role: "owner", email: "owner@example.com" }));
    localStorage.setItem("omnexa-theme", "light");
    localStorage.setItem("omnexa-language", "en");
  });
  await page.route(/^https:/, route => route.abort());
  await page.route("**/api/**", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data: {} }) }));
  await page.goto("/index.html?bot_id=1");

  await page.evaluate(() => window.OmnexaAppPreferences.setLanguage("zh-CN"));
  await expect(page.locator("body")).toContainText("添加主要知识以获得准确答案。");
  await expect(page.locator("body")).not.toContainText("Add primary knowledge to get accurate answers.");

  await page.evaluate(() => window.OmnexaAppPreferences.setLanguage("ms"));
  await expect(page.locator("body")).toContainText("Tambah pengetahuan utama untuk mendapatkan jawapan yang tepat.");
  await expect(page.locator("body")).not.toContainText("Add primary knowledge to get accurate answers.");
});

test("translates content generated after load and rerenders structured messages on language changes", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("omnexa-language", "zh-CN");
  });
  await page.route(/^https:/, route => route.abort());
  await page.goto("/login.html");

  await page.evaluate(() => {
    const host = document.createElement("section");
    host.id = "generated-localization-test";
    const action = document.createElement("p");
    window.OmnexaAppPreferences.text(action, "geo.action.local_context", {});
    const lateLabel = document.createElement("button");
    lateLabel.textContent = "Billing";
    lateLabel.setAttribute("aria-label", "Billing");
    host.append(action, lateLabel);
    document.body.appendChild(host);
  });

  await expect(page.locator("#generated-localization-test p")).toContainText("加入真实的本地情境");
  await expect(page.locator("#generated-localization-test button")).toHaveText("账单");
  await expect(page.locator("#generated-localization-test button")).toHaveAttribute("aria-label", "账单");

  await page.evaluate(() => window.OmnexaAppPreferences.setLanguage("ms"));
  await expect(page.locator("#generated-localization-test p")).toContainText("Tambah konteks tempatan yang sebenar");
  await expect(page.locator("#generated-localization-test button")).toHaveText("Pengebilan");
  await expect(page.locator("#generated-localization-test button")).toHaveAttribute("aria-label", "Pengebilan");
});

test("translates generated GEO findings while preserving business evidence", async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem("token", "browser-test-token");
    sessionStorage.setItem("user", JSON.stringify({ role: "owner", email: "owner@example.com" }));
    localStorage.setItem("omnexa-language", "zh-CN");
  });
  await page.route(/^https:/, route => route.abort());
  const capabilities = {
    plan: { label: "Pro" },
    limits: { monthly_executions: 120, prompts: 4, executions: 20, history: 10, minimum_reliable_samples: 3 },
    usage: { used: 1, remaining: 119, resets_at: "2026-11-01T00:00:00Z" },
    platforms: {}
  };
  const finding = {
    platform: "chatgpt", priority: "high", score: 30,
    title: "Improve AI mentions in ChatGPT Search", title_key: "geo.finding.title",
    title_params: { platform: "ChatGPT Search" },
    summary: "Mention rate 50% (1/2 completed checks); no reliable mention rank was found.",
    summary_key: "geo.finding.summary.insufficient_unranked",
    summary_params: { mention_rate: 50, mentioned: 1, checks: 2 },
    action_pillars: [
      { key: "website", title: "Website / landing page", title_key: "geo.pillar.website", message_key: "geo.action.website", params: { prompt: "best chatbot in KL", competitors: "Rival" }, action: "Website action" },
      { key: "authority_posts", title: "Articles on trusted platforms", title_key: "geo.pillar.authority_posts", message_key: "geo.action.authority_posts", params: { prompt: "best chatbot in KL", channels: "LinkedIn and Medium" }, action: "Post action" },
      { key: "local_context", title: "Local landmarks and context", title_key: "geo.pillar.local_context", message_key: "geo.action.local_context", params: {}, action: "Local action" },
      { key: "crawler_technical", title: "Technical fixes for AI crawlers", title_key: "geo.pillar.crawler_technical", message_key: "geo.action.crawler_technical", params: {}, action: "Crawler action" }
    ],
    evidence: [{ platform: "chatgpt", prompt: "best chatbot in KL" }]
  };
  const analysis = {
    id: 7, brand_name: "Acme KL", country: "MY", created_at: "2026-10-14T04:00:00Z", status: "complete",
    platforms: ["chatgpt"], prompts: ["best chatbot in KL"],
    methodology: { formula: "Mention-focused deterministic scoring" },
    metrics: {
      geo_score: 30, mention_rate: 50, mentioned_samples: 1, successful_samples: 2, sample_size: 2,
      minimum_reliable_samples: 3, mention_rate_confidence_interval: { lower: 10, upper: 90 },
      score_breakdown: {}, findings: [finding],
      platform_summary: { chatgpt: { mention_rate: 50, mentioned_samples: 1, successful_samples: 2,
        minimum_reliable_samples: 3, average_mention_rank: null, mention_rank_prominence: 0, sample_quality: "insufficient" } }
    },
    executions: [{ prompt_index: 0, prompt: "best chatbot in KL", platform: "chatgpt", model: "gpt-test",
      request_status: "complete", brand_mentioned: true, recommendation_position: null,
      raw_response: "Acme KL is visible near KLCC.", citations: [] }]
  };
  await page.route("**/api/geo/capabilities", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data: capabilities }) }));
  await page.route(/\/api\/geo\/analyses\?limit=/, route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data: [{ id: 7, brand_name: "Acme KL", created_at: analysis.created_at, status: "complete", metrics: analysis.metrics }] }) }));
  await page.route("**/api/geo/analyses/7", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data: analysis }) }));
  await page.goto("/geo-analysis.html");
  await page.locator("#geo-history button").click();

  await expect(page.locator(".geo-action-pillars > li")).toHaveCount(4);
  await expect(page.locator("#geo-findings")).toContainText("网站 / 落地页");
  await expect(page.locator("#geo-findings")).toContainText("本地地标与情境");
  await expect(page.locator("#geo-findings")).toContainText("AI 爬虫技术修复");
  await expect(page.locator("#geo-evidence .geo-response")).toHaveText("Acme KL is visible near KLCC.");

  await page.evaluate(() => window.OmnexaAppPreferences.setLanguage("ms"));
  await expect(page.locator("#geo-findings")).toContainText("Laman web / halaman pendaratan");
  await expect(page.locator("#geo-findings")).toContainText("Mercu tanda dan konteks tempatan");
  await expect(page.locator("#geo-findings")).toContainText("Pembaikan teknikal untuk perayap AI");
  await expect(page.locator("#geo-evidence .geo-response")).toHaveText("Acme KL is visible near KLCC.");
});

test("places responsive controls inside the authenticated sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    sessionStorage.setItem("token", "browser-test-token");
    sessionStorage.setItem("selectedBotId", "1");
    sessionStorage.setItem("user", JSON.stringify({ role: "owner", email: "owner@example.com" }));
    localStorage.setItem("omnexa-theme", "dark");
    localStorage.setItem("omnexa-language", "en");
  });
  await page.route(/^https:/, route => route.abort());
  await page.route("**/api/**", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", data: {} }) }));
  await page.goto("/index.html?bot_id=1");
  const controls = page.locator("chatbot-sidebar .sidebar-bottom-section .omnexa-preferences");
  await expect(controls).toBeAttached();
  const sidebarToggle = page.locator("chatbot-sidebar .sidebar-toggle");
  await sidebarToggle.click();
  await expect(controls).toBeVisible();
  await page.selectOption(".omnexa-preferences select", "ms");
  await expect(page.locator("chatbot-sidebar .nav-group-header").first()).toHaveText("Sediakan bot anda");
  await expect(page.locator("chatbot-sidebar .nav-link", { hasText: "Tambah pengetahuan" })).toBeVisible();
  await expect(page).toHaveTitle("Bot dipilih - Papan pemuka | Omnexa");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
