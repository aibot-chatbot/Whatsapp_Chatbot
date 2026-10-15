"use strict";

const path = require("path");
const { expect, test } = require("@playwright/test");
const { ARTIFACTS, BOT_ID, PUBLIC_KEY, createWorld, startJourneyServer } = require("./client-journey-server");

// UI integration only. PDF extraction, matching, AI replies, persistence and
// publication are explicitly simulated by a separate loopback fixture server.
test.setTimeout(90000);
test.use({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });

let fixture;
test.beforeEach(async ({ page }) => {
  fixture = await startJourneyServer({ world: createWorld() });
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    return url.origin === fixture.url ? route.continue() : route.abort();
  });
});
test.afterEach(async () => {
  if (!fixture) return;
  fixture.server.closeAllConnections();
  await new Promise(resolve => fixture.server.close(resolve));
});

const PDF = { name: "Acme-hours.pdf", mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4\n% Synthetic fixture only: Acme opens Monday to Friday, 9am to 5pm.\n%%EOF\n") };

async function choosePdf(page) {
  await page.getByRole("button", { name: "Upload a document", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add a knowledge source" });
  await expect(dialog).toBeVisible();
  await dialog.locator("#file-input").setInputFiles(PDF);
  await dialog.getByRole("button", { name: "Upload Primary PDF", exact: true }).click();
}

async function capture(page, name) {
  await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: "instant" }));
  await page.screenshot({ path: path.join(ARTIFACTS, `mock-${name}.png`), fullPage: true, animations: "disabled" });
}

test("first client creates, uploads, applies, tests and explicitly publishes with a persistent key", async ({ page }) => {
  const world = fixture.world;
  const navigations = [];
  page.on("framenavigated", frame => { if (frame === page.mainFrame()) navigations.push(frame.url()); });
  let finishUpload;
  let finishMatch;
  world.uploadGate = new Promise(resolve => { finishUpload = resolve; });
  world.matchGate = new Promise(resolve => { finishMatch = resolve; });

  try {
    await page.goto(`${fixture.url}/bots.html`);
    await expect(page.getByRole("heading", { name: "My bots", exact: true })).toBeVisible();
    await page.locator("[data-create-bot-trigger]").first().click();
    await page.locator("#bot-name").fill("Acme Support");
    await page.locator("#bot-description").fill("Answer opening-hours questions from our document.");
    await capture(page, "01-create-bot");
    await page.locator("#submit-create-btn").click();

    await expect(page).toHaveURL(new RegExp(`/new_linkdocs\\.html\\?bot_id=${BOT_ID}&setup=1$`));
    await page.waitForLoadState("load");
    await expect(page.getByRole("heading", { name: "Start with one PDF", exact: true })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("link", { name: "Continue to instructions" })).toHaveCount(0);
    expect(await page.evaluate(() => sessionStorage.getItem("selectedBotId"))).toBe(String(BOT_ID));
    expect(world.calls.filter(call => call.method === "POST" && call.path === "/api/bots")).toHaveLength(1);
    await capture(page, "knowledge-empty");

    await choosePdf(page);
    await expect.poll(() => world.uploadStarted).toBe(true);
    await expect(page.getByRole("link", { name: "Continue to instructions" })).toHaveCount(0);
    finishUpload();
    await expect(page.getByRole("heading", { name: "Your document is ready", exact: true })).toBeVisible();
    await expect(page.locator(".kw-guided-upload")).toContainText(PDF.name);
    expect(world.calls.find(call => call.path === "/upload-pdf").query).toBe(`?chatbot_id=${BOT_ID}`);
    await capture(page, "02-document-ready");
    await page.getByRole("link", { name: "Continue to instructions" }).click();

    await expect(page).toHaveURL(new RegExp(`/new_prompt\\.html\\?bot_id=${BOT_ID}&setup=1$`));
    await expect(page.locator("#bc-bot-name")).toHaveText("Acme Support");
    await expect(page.locator("#bc-deploy")).toBeDisabled();
    expect(world.calls.filter(call => call.path === "/api/match/check")).toHaveLength(0);
    await page.locator("#bc-create").click();
    await page.locator("#bc-f-name").fill("Acme customer support");
    await page.locator("#bc-f-bot").fill("Acme Support");
    await page.locator("#bc-f-company").fill("Acme");
    await page.locator("#bc-f-desc").fill("Acme helps customers with product support and opening hours.");
    await page.locator("#bc-f-tone").fill("Friendly and clear");
    await page.locator("#bc-f-extra").fill("Use our document. Ask our team when the answer is missing.");
    await page.locator("#bc-save").click();
    await expect(page.locator(".bc-profile-row")).toHaveCount(1);
    expect(world.calls.filter(call => call.path === "/api/match/check")).toHaveLength(0);
    await page.locator("#bc-preview").getByRole("button", { name: "Choose these instructions", exact: true }).click();
    await expect.poll(() => world.matchStarted).toBe(true);
    await expect(page.locator("#bc-deploy")).toBeDisabled();
    expect(world.calls.filter(call => call.path === "/api/settings/apply-profile")).toHaveLength(0);
    finishMatch();
    await expect(page.locator("#bc-deploy")).toBeEnabled();
    await page.locator("#bc-deploy").click();
    await expect(page.locator("#bc-continue-test")).toBeVisible();
    await expect(page).toHaveURL(/new_prompt\.html/);
    expect(world.deployedProfile).toBe("Acme customer support");
    expect(world.deployedPdf).toBe(PDF.name);
    expect(world.widget.is_enabled).toBe(false);
    await capture(page, "03-instructions-applied");
    await page.locator("#bc-continue-test").click();

    await expect(page).toHaveURL(new RegExp(`/behaviour\\.html\\?tab=test&bot_id=${BOT_ID}&setup=1$`));
    expect(navigations.some(url => url.includes(`/testbot.html?bot_id=${BOT_ID}&setup=1`))).toBe(true);
    await expect(page.locator("#bh-tab-test")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#bh-setup")).toContainText("Acme customer support");
    await expect(page.locator("#bh-setup")).toContainText(PDF.name);
    await page.locator("#bh-input").fill("What are your opening hours?");
    await page.locator("#bh-send").click();
    await expect(page.locator("#bh-chat")).toContainText("We are open Monday to Friday, 9am to 5pm.");
    expect(world.messages).toEqual(["What are your opening hours?"]);
    await capture(page, "04-test-reply");
    await page.locator("#bh-choose-channel").click();

    await expect(page).toHaveURL(new RegExp(`/integration\\.html\\?bot_id=${BOT_ID}&setup=1$`));
    await expect(page.locator("#pub-options > .pub-option")).toHaveCount(5);
    expect(world.widgetWrites).toHaveLength(0);
    await expect(page.locator("#pub-live-count")).toHaveText("0");
    await capture(page, "05-channel-choice");
    await page.getByRole("button", { name: "Choose website", exact: true }).click();
    expect(world.widgetWrites).toHaveLength(0);
    await page.getByRole("button", { name: "Enable website and share link", exact: true }).click();
    await expect(page.locator("#pub-live-body .kw-pill-ready")).toContainText("Enabled · not checked");
    expect(world.widgetWrites).toEqual([{ is_enabled: true }]);
    await page.reload();
    const share = page.locator("#pub-live-body .kw-idrow code");
    await expect(share).toHaveText(`https://bot.example.test/chat/${PUBLIC_KEY}`);
    await expect(page.locator("#pub-live-body .kw-pill-ready")).toContainText("Enabled · not checked");
    await capture(page, "06-website-enabled");

    await page.getByRole("button", { name: "Turn the link off", exact: true }).click();
    await page.locator("#pub-confirm-ok").click();
    await expect.poll(() => world.widget.is_enabled).toBe(false);
    await expect(page.locator("#pub-live-count")).toHaveText("0");
    await page.reload();
    // The intentionally unavailable Meta configuration uses the real GET
    // retry budget before the page finishes rendering all channel status.
    await expect(page.locator("#pub-live-count")).toHaveText("0", { timeout: 15000 });
    // The explicitly selected channel is addressable and restored after reload.
    await expect(page.getByRole("button", { name: "Choose website", exact: true })).toHaveAttribute("aria-expanded", "true");
    await page.getByRole("button", { name: "Enable website and share link", exact: true }).click();
    await expect(share).toHaveText(`https://bot.example.test/chat/${PUBLIC_KEY}`);
    expect(world.widget.public_key).toBe(PUBLIC_KEY);
    expect(world.widgetWrites).toEqual([{ is_enabled: true }, { is_enabled: false }, { is_enabled: true }]);
    expect(world.calls.some(call => call.path.includes("regenerate-key"))).toBe(false);
    expect(world.unexpected).toEqual([]);
    await capture(page, "07-website-reconnected");
  } finally {
    finishUpload();
    finishMatch();
  }
});

test("pending, failed, mismatched and unreadable knowledge never unlock instructions", async ({ page }) => {
  const world = fixture.world;
  world.bot = { id: BOT_ID, bot_name: "Acme Support", draft_profile_name: "" };
  world.files = [{ id: 11, file_name: PDF.name, file_type: "pdf", role: "primary",
    is_active: true, is_enabled: true, processing_status: "processing" }];
  const url = `${fixture.url}/new_linkdocs.html?bot_id=${BOT_ID}&setup=1`;
  for (const status of ["processing", "failed"]) {
    world.files[0].processing_status = status;
    await page.goto(url);
    await expect(page.getByRole("button", { name: "Check document status", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Continue to instructions" })).toHaveCount(0);
  }
  world.files[0].processing_status = "completed";
  world.activeFileOverride = { file_name: "different.pdf" };
  await page.goto(url);
  await expect(page.getByRole("button", { name: "Check document status", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Continue to instructions" })).toHaveCount(0);
  world.activeFileOverride = null;
  world.knowledgeReadFailure = true;
  await page.goto(url);
  await expect(page.getByRole("button", { name: "Check documents again", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Continue to instructions" })).toHaveCount(0);
  world.knowledgeReadFailure = false;
  await page.getByRole("button", { name: "Check documents again", exact: true }).click();
  await expect(page.getByRole("link", { name: "Continue to instructions" })).toBeVisible();
  expect(world.unexpected).toEqual([]);
});

test("an accepted upload with failed extraction never reports a ready document", async ({ page }) => {
  const world = fixture.world;
  world.bot = { id: BOT_ID, bot_name: "Acme Support", draft_profile_name: "" };
  world.uploadFailure = true;
  await page.goto(`${fixture.url}/new_linkdocs.html?bot_id=${BOT_ID}&setup=1`);
  await choosePdf(page);
  await expect(page.getByRole("status").filter({ hasText: "Synthetic extraction found no readable text." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your document is ready", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Continue to instructions" })).toHaveCount(0);
  expect(world.files).toEqual([]);
  expect(world.unexpected).toEqual([]);
});
