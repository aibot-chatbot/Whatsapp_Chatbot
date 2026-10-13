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
