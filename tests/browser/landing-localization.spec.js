const path = require("path");
const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

const MEDIA_DIR = path.join(__dirname, "..", "..", "frontend", "assets", "media");

let staticServer;

test.beforeAll(async () => {
  staticServer = await startServer();
});

test.afterAll(async () => {
  if (staticServer) await new Promise(resolve => staticServer.close(resolve));
});

test.beforeEach(async ({ page }) => {
  await page.route(/^https:/, route => route.abort());
  // The hero media is served from the Supabase CDN; answer every clip and poster with
  // one repo video and poster so the spec stays offline.
  await page.route(/\/landing\/media\/[\w-]+\.(mp4|webp)$/, route =>
    route.fulfill({ path: path.join(MEDIA_DIR,
      route.request().url().endsWith(".mp4") ? "promotion-video.mp4" : "promotion-video-poster.webp") }));
  await page.goto("/landing.html");
});

test("exposes the requested identity and preference controls", async ({ page }) => {
  await expect(page).toHaveTitle("Omnexa | WhatsApp Telegram AI chatbot, CRM and broadcasts for Malaysian businesses");
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", /^data:image\/svg\+xml;base64,/);
  const heroVideo = page.locator("#robot");
  await expect(heroVideo).toHaveAttribute("autoplay", "");
  await expect(heroVideo).toHaveAttribute("muted", "");
  await expect(heroVideo).toHaveAttribute("loop", "");
  await expect(heroVideo).toHaveAttribute("playsinline", "");
  await expect(heroVideo).toHaveAttribute("poster", "https://manertvcpqtsmegqvhuc.supabase.co/storage/v1/object/public/landing/media/hero-loop-v1-poster.webp");
  await expect(heroVideo.locator("source")).toHaveAttribute("src", "https://manertvcpqtsmegqvhuc.supabase.co/storage/v1/object/public/landing/media/hero-loop-v1.mp4");
  await expect(page.locator(".bloom, .spec")).toHaveCount(0);
  const visualEffects = await heroVideo.evaluate(video => {
    const styles = getComputedStyle(video);
    return { filter: styles.filter, mask: styles.maskImage };
  });
  expect(visualEffects).toEqual({ filter: "none", mask: "none" });
  const beforePointerMove = await heroVideo.boundingBox();
  await page.mouse.move(20, 20);
  await page.mouse.move(1200, 700);
  await page.waitForTimeout(150);
  const afterPointerMove = await heroVideo.boundingBox();
  expect(afterPointerMove.x).toBeCloseTo(beforePointerMove.x, 1);
  expect(afterPointerMove.y).toBeCloseTo(beforePointerMove.y, 1);
  expect(await heroVideo.evaluate(video => video.muted)).toBe(true);
  await expect.poll(
    () => heroVideo.evaluate(video => video.readyState >= 2 && !video.paused && video.currentTime > 0),
    { timeout: 10000 }
  ).toBe(true);
  await expect(page.locator("#language-select")).toBeVisible();
  await expect(page.locator("#theme-toggle")).toBeVisible();
});

test("switches every inventoried string between English, Chinese and Malay", async ({ page }) => {
  for (const [language, copy] of [
    ["zh-CN", {
      eyebrow: "专为马来西亚企业打造",
      heading: "让您的业务自动扩展",
      lede: "Omnexa 将 WhatsApp、Telegram、AI 客服代理、自动化工作流、SEO 与 GEO 排名以及网站托管整合到一个统一平台中。",
      cta: "开始免费试用", note: "免费 7 天，无需信用卡", website: "网站聊天", soon: "即将推出"
    }],
    ["ms", {
      eyebrow: "Dibina untuk perniagaan Malaysia",
      heading: "Skalakan perniagaan anda secara automatik",
      lede: "Omnexa menggabungkan WhatsApp, Telegram dan ejen pelanggan AI, aliran kerja automatik, kedudukan SEO dan GEO serta pengehosan laman web dalam satu platform bersepadu.",
      cta: "Mulakan percubaan percuma", note: "Percuma 7 hari, tanpa kad", website: "Sembang laman web", soon: "Akan datang"
    }],
    ["en", {
      eyebrow: "Built for Malaysian businesses",
      heading: "Scale Your Business on Autopilot",
      lede: "Omnexa combines WhatsApp, Telegram and AI customer agents, automated workflows, SEO and GEO ranking, and website hosting in one unified platform.",
      cta: "Start free trial", note: "7 days free, no card required", website: "Website chat", soon: "Soon"
    }]
  ]) {
    await page.selectOption("#language-select", language);
    await expect(page.locator("html")).toHaveAttribute("lang", language);
    const hero = page.locator("section.hero");
    await expect(hero.locator(".eyebrow")).toContainText(copy.eyebrow);
    await expect(hero.locator("h1")).toHaveText(copy.heading);
    await expect(hero.locator(".lede")).toHaveText(copy.lede);
    await expect(hero.locator(".btn").first()).toHaveText(copy.cta);
    await expect(hero.locator(".muted")).toHaveText(copy.note);
    await expect(hero.locator(".chip", { hasText: copy.website })).toBeVisible();
    await expect(hero.locator(".chip.soon b").first()).toHaveText(copy.soon);
    expect(await page.evaluate(() => window.__OMNEXA_I18N_MISSING__)).toEqual([]);
  }
});

test("persists light mode and stays within desktop, tablet and mobile viewports", async ({ page }) => {
  await page.click("#theme-toggle");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("#theme-color")).toHaveAttribute("content", "#F7FAFC");
  const languagePalette = await page.locator("#language-select").evaluate(select => {
    const field = getComputedStyle(select);
    const option = getComputedStyle(select.options[0]);
    return { fieldColor: field.color, optionBackground: option.backgroundColor, optionColor: option.color };
  });
  expect(languagePalette).toEqual({
    fieldColor: "rgb(15, 23, 42)",
    optionBackground: "rgb(255, 255, 255)",
    optionColor: "rgb(15, 23, 42)"
  });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.waitForTimeout(100);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await expect(page.locator("#language-select")).toBeVisible();
    await expect(page.locator("#theme-toggle")).toBeVisible();
  }
});
