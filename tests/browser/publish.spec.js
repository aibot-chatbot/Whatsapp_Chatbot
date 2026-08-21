const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let staticServer;

test.beforeAll(async () => { staticServer = await startServer(); });
test.afterAll(async () => {
  if (!staticServer) return;
  await new Promise(resolve => staticServer.close(resolve));
});

function json(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

const BOT_ID = "42";
const SHARE_URL = "https://bot.example.test/chat/wgt_9f2ac1";

function makeWorld(overrides = {}) {
  return Object.assign({
    widget: {
      id: 7, chatbot_id: 42, public_key: "wgt_9f2ac1", is_enabled: true,
      display_name: "Northweave Clinic", subtitle: "We reply in a minute",
      primary_color: "#3e9c89", text_color: "#ffffff", avatar_url: "",
      launcher_position: "right", launcher_label: "Chat",
      welcome_message: "Hello, how can we help?", input_placeholder: "Type your message...",
      suggested_questions: ["Opening hours", "Where are you?"],
      show_branding: true, branding_text: "Powered by AI",
      collect_lead: false, lead_prompt: "", lead_require_name: true,
      lead_require_email: true, lead_require_phone: false,
      allowed_domains: [], max_messages_per_session: 50
    },
    embed: {
      base_url: "https://bot.example.test",
      script_url: "https://bot.example.test/widget.js",
      share_url: SHARE_URL,
      iframe_url: "https://bot.example.test/widget/wgt_9f2ac1",
      script_snippet: '<script src="https://bot.example.test/widget.js" data-chatbot-key="wgt_9f2ac1" defer></script>',
      iframe_snippet: '<iframe src="https://bot.example.test/widget/wgt_9f2ac1"></iframe>'
    },
    telegram: [],
    whatsapp: [],
    wasender: [],
    usage: { channels: { used: 0, limit: 2 } },
    // The operator has not finished Meta approval, which is the production
    // default. The route answers 500 in that state, not 404.
    metaConfigured: false,
    telegramConnect: null,
    calls: [],
    puts: []
  }, overrides);
}

async function install(page, world) {
  await page.addInitScript(() => {
    sessionStorage.setItem("token", "fake-tenant-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify({
      id: 1, email: "owner@northweave.test", full_name: "Owner", role: "owner"
    }));
  });

  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("https://connect.facebook.net/**", route => route.abort());

  await page.route("**/api/**", async route => {
    const req = route.request();
    const url = req.url();
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    world.calls.push(`${req.method()} ${path}`);

    if (path.includes("/widget/regenerate-key")) {
      world.widget = Object.assign({}, world.widget, { public_key: "wgt_new1" });
      world.embed = Object.assign({}, world.embed, {
        share_url: "https://bot.example.test/chat/wgt_new1"
      });
      return route.fulfill(json({ status: "success", data: { widget: world.widget, embed: world.embed } }));
    }

    if (path.includes(`/api/bots/${BOT_ID}/widget`)) {
      if (req.method() === "PUT") {
        const body = JSON.parse(req.postData() || "{}");
        world.puts.push(body);
        world.widget = Object.assign({}, world.widget, body);
      }
      return route.fulfill(json({ status: "success", data: { widget: world.widget, embed: world.embed } }));
    }

    if (path.includes("/api/billing/usage")) {
      return route.fulfill(json({ status: "success", data: { usage: world.usage } }));
    }

    if (path.includes("/api/whatsapp/embedded-signup/config")) {
      if (!world.metaConfigured) {
        return route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({
            status: "error",
            message: "WhatsApp Embedded Signup is not configured. Missing app ID or configuration ID."
          })
        });
      }
      return route.fulfill(json({
        status: "success",
        data: { app_id: "111", config_id: "222", graph_api_version: "v22.0" }
      }));
    }

    if (path.includes("/api/telegram/connect")) {
      const outcome = world.telegramConnect;
      if (outcome && outcome.error) {
        return route.fulfill({
          status: outcome.status || 400,
          contentType: "application/json",
          body: JSON.stringify({ status: "error", message: outcome.error })
        });
      }
      world.telegram = [{
        id: 3, chatbot_id: 42, bot_username: "northweave_bot", telegram_bot_id: "8123",
        connection_status: "connected", is_active: true, last_error: null
      }];
      return route.fulfill(json({
        status: "success",
        data: { id: 3, bot_username: "northweave_bot", connection_status: "connected" }
      }));
    }

    for (const kind of ["telegram", "whatsapp", "wasender"]) {
      if (path.includes(`/api/${kind}/channels`)) {
        if (req.method() === "PUT") {
          world[kind] = [];
          return route.fulfill(json({ status: "success", data: {} }));
        }
        return route.fulfill(json({ status: "success", data: world[kind] }));
      }
    }

    return route.fulfill(json({ status: "success", data: {} }));
  });
}

async function open(page, world) {
  await install(page, world);
  await page.goto(`/integration.html?bot_id=${BOT_ID}`);
  await expect(page.locator("#pub-live-body .pub-share")).toBeVisible();
}

test("the share link and its QR are the first thing on the page", async ({ page }) => {
  const world = makeWorld();
  await open(page, world);

  // Section order is the reading order and the tab order.
  const sections = await page.locator("main > .kw-panel, main > .pub-settings")
    .evaluateAll(nodes => nodes.map(n => n.id));
  expect(sections).toEqual(["pub-live", "pub-add", "pub-settings"]);

  // The QR is real vector output, not a placeholder.
  const qr = page.locator("#pub-qr svg");
  await expect(qr).toBeVisible();
  await expect(qr).toHaveAttribute("role", "img");
  await expect(qr).toHaveAttribute("aria-label", /QR code/i);
  expect(await page.locator("#pub-qr svg path").count()).toBe(1);

  // The same link is present as selectable text, so the QR is never the only path.
  await expect(page.locator("#pub-live-body .kw-idrow code")).toHaveText(SHARE_URL);
  await expect(page.getByRole("button", { name: "Copy link" })).toBeVisible();

  // The code snippet is demoted: it is behind a disclosure, below the link.
  await expect(page.locator("#pub-flow-website")).toBeHidden();
});

test("no technical word reaches the default path", async ({ page }) => {
  await open(page, makeWorld());

  const visible = await page.locator("main").innerText();
  for (const word of ["webhook", "verify token", "phone number id", "session id",
                      "bearer", "app id", "api key"]) {
    expect(visible.toLowerCase()).not.toContain(word);
  }

  // And the button that asked the owner to certify their own setup is gone.
  expect(visible).not.toContain("Completed Setup");
});

test("every settings disclosure starts closed", async ({ page }) => {
  await open(page, makeWorld());

  for (const id of ["#pub-look", "#pub-lead", "#pub-adv", "#pub-wasender"]) {
    await expect(page.locator(id)).not.toHaveAttribute("open", /.*/);
  }
});

test("a disabled link reads as off and offers one tap to fix it", async ({ page }) => {
  const world = makeWorld();
  world.widget.is_enabled = false;
  await open(page, world);

  await expect(page.locator("#pub-live-body .kw-pill-off")).toContainText("Turned off");
  await expect(page.locator("#pub-live-count")).toHaveText("0");

  const turnOn = page.getByRole("button", { name: "Turn the link on" });
  await expect(turnOn).toBeVisible();
  await turnOn.click();

  await expect(page.locator("#pub-live-body .kw-pill-ready")).toContainText("Working");
  expect(world.puts.at(-1)).toEqual({ is_enabled: true });
});

test("turning the link off asks first, because printed links break", async ({ page }) => {
  const world = makeWorld();
  await open(page, world);

  await page.getByRole("button", { name: "Turn the link off" }).click();
  await expect(page.locator("#pub-confirm")).toBeVisible();
  await expect(page.locator("#pub-confirm-title")).toHaveText("Turn the link off?");

  await page.locator("#pub-confirm-cancel").click();
  await expect(page.locator("#pub-confirm")).toBeHidden();
  expect(world.puts).toHaveLength(0);
});

test("WhatsApp reads as a real state when the operator has not enabled it", async ({ page }) => {
  await open(page, makeWorld());

  const row = page.locator('[data-option="whatsapp"]');
  await expect(row).toHaveClass(/is-quiet/);
  await expect(row.locator(".kw-badge-support")).toHaveText("Not available yet");
  // Never a live-looking button that cannot work.
  await expect(row.locator("#pub-meta-connect")).toHaveCount(0);
  await expect(row).toContainText("still finishing our approval");
});

test("a full plan explains itself instead of failing after the click", async ({ page }) => {
  const world = makeWorld();
  world.usage = { channels: { used: 2, limit: 2 } };
  await open(page, world);

  const row = page.locator('[data-option="telegram"]');
  await expect(row.locator(".kw-badge-support").last()).toContainText("Plan full");
  await expect(row).toContainText("already in use");
  await expect(row.getByRole("link", { name: "See plans" })).toBeVisible();
  await expect(row.locator("[data-flow-open]")).toHaveCount(0);
});

test("the Telegram guide is inline, addressable, and an accordion of one", async ({ page }) => {
  await open(page, makeWorld());

  const trigger = page.locator('[data-flow-open="telegram"]');
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await trigger.click();

  await expect(page.locator("#pub-flow-telegram")).toBeVisible();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  // The URL carries the state, so switching to Telegram and back survives.
  expect(page.url()).toContain("connect=telegram");

  // Three steps, each with a copyable value or a diagram, then one field.
  await expect(page.locator("#pub-flow-telegram .pub-guide-step")).toHaveCount(3);
  await expect(page.locator("#pub-flow-telegram .kw-idrow code").first()).toHaveText("@BotFather");
  await expect(page.locator("#pub-flow-telegram .pub-shot svg")).toHaveCount(3);

  // A beginner has to be able to see that their paste worked.
  await expect(page.locator("#pub-telegram-code")).toHaveAttribute("type", "text");
  await expect(page.locator("#pub-flow-telegram label[for='pub-telegram-code']"))
    .toHaveText("Paste the code here");

  // Opening the website flow closes this one.
  await page.locator('[data-flow-open="website"]').click();
  await expect(page.locator("#pub-flow-telegram")).toBeHidden();
  await expect(page.locator("#pub-flow-website")).toBeVisible();
});

test("a valid code shows the bot's real name and moves it to the live list", async ({ page }) => {
  const world = makeWorld();
  await open(page, world);

  await page.locator('[data-flow-open="telegram"]').click();
  await page.locator("#pub-telegram-code").fill("8123456789:AAHxxxxxxxxxxxxxxxxxxxxx");
  await page.locator("#pub-telegram-connect").click();

  // The row migrates from "add" into "live". That move is the proof.
  const liveRow = page.locator('#pub-live-body [data-live="telegram"]');
  await expect(liveRow).toBeVisible();
  await expect(liveRow).toContainText("@northweave_bot");
  await expect(liveRow.locator(".kw-pill-ready")).toContainText("Working");
  await expect(liveRow.getByRole("link", { name: /Open in Telegram/ }))
    .toHaveAttribute("href", "https://t.me/northweave_bot");

  await expect(page.locator("#pub-live-count")).toHaveText("2");
  await expect(page.locator('[data-option="telegram"]')).toHaveCount(0);
});

test("a malformed code is caught before a request is sent", async ({ page }) => {
  const world = makeWorld();
  await open(page, world);

  await page.locator('[data-flow-open="telegram"]').click();
  await page.locator("#pub-telegram-code").fill("not-a-token");
  await page.locator("#pub-telegram-connect").click();

  await expect(page.locator("#pub-telegram-result .kw-banner-error"))
    .toContainText("does not look like the right code");
  expect(world.calls.filter(c => c.includes("/api/telegram/connect"))).toHaveLength(0);
});

test("a rejected code explains itself without vendor jargon", async ({ page }) => {
  const world = makeWorld();
  world.telegramConnect = { status: 400, error: "Unauthorized" };
  await open(page, world);

  await page.locator('[data-flow-open="telegram"]').click();
  await page.locator("#pub-telegram-code").fill("8123456789:AAHxxxxxxxxxxxxxxxxxxxxx");
  await page.locator("#pub-telegram-connect").click();

  const banner = page.locator("#pub-telegram-result .kw-banner-error");
  await expect(banner).toContainText("Copy the whole line from BotFather");
  await expect(banner).not.toContainText("Unauthorized");
});

test("a broken channel offers a repair, not a shrug", async ({ page }) => {
  const world = makeWorld();
  world.telegram = [{
    id: 3, chatbot_id: 42, bot_username: "northweave_bot",
    connection_status: "failed", is_active: true, last_error: "getMe failed"
  }];
  await open(page, world);

  const row = page.locator('#pub-live-body [data-live="telegram"]');
  await expect(row.locator(".kw-pill-review")).toContainText("Needs a fix");
  await expect(row).toContainText("stopped accepting messages");
  await expect(row).not.toContainText("getMe");
  await expect(row.getByRole("button", { name: "Set it up again" })).toBeVisible();
});

test("making a new link warns that printed copies stop working", async ({ page }) => {
  const world = makeWorld();
  await open(page, world);

  await page.locator("#pub-adv > summary").click();
  await page.locator("#pub-regenerate").click();

  await expect(page.locator("#pub-confirm-title")).toHaveText("Make a new link?");
  await expect(page.locator("#pub-confirm-body")).toContainText("already printed");

  await page.locator("#pub-confirm-ok").click();
  await expect(page.locator("#pub-live-body .kw-idrow code"))
    .toHaveText("https://bot.example.test/chat/wgt_new1");
});

test("lead fields stay hidden until the owner asks for them", async ({ page }) => {
  await open(page, makeWorld());

  await page.locator("#pub-lead > summary").click();
  await expect(page.locator('[data-depends="ww-collect_lead"]').first()).toBeHidden();

  await page.locator("#ww-collect_lead").check();
  await expect(page.locator('[data-depends="ww-collect_lead"]').first()).toBeVisible();
});

test("phone width stacks without overflowing", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 850 });
  await open(page, makeWorld());

  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  await expect(page.locator("#pub-qr svg")).toBeVisible();
});

test("option descriptions stay readable at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 850 });
  await open(page, makeWorld());

  // Regression: the shared sheet hides kw-tab-icon below 768, which left an
  // empty 34px grid column and auto-placed the copy into it. Every
  // description rendered one word per line.
  const widths = await page.locator(".pub-option-copy").evaluateAll(nodes =>
    nodes.map(n => Math.round(n.getBoundingClientRect().width)));

  expect(widths.length).toBeGreaterThan(0);
  for (const width of widths) expect(width).toBeGreaterThan(180);

  await expect(page.locator('[data-option="website"] .kw-tab-icon')).toBeVisible();
});
