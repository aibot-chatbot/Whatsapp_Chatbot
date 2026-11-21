const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let staticServer;
let staticOrigin;

test.beforeAll(async () => {
  staticServer = await startServer(0);
  staticOrigin = `http://127.0.0.1:${staticServer.address().port}`;
});
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
      delivery: { persistent_url: true, base_kind: 'permanent', base_configured: true,
        reachability: 'not_checked', message: 'A permanent address is configured.' },
      base_url: "https://bot.example.test",
      script_url: "https://bot.example.test/widget.js",
      share_url: SHARE_URL,
      iframe_url: "https://bot.example.test/widget/wgt_9f2ac1",
      script_snippet: '<script src="https://bot.example.test/widget.js" data-chatbot-key="wgt_9f2ac1" defer></script>',
      iframe_snippet: '<iframe src="https://bot.example.test/widget/wgt_9f2ac1"></iframe>'
    },
    "channel-server": [],
    telegram: [],
    whatsapp: [],
    usage: { channels: { used: 0, limit: 2 } },
    // The operator has not finished Meta approval, which is the production
    // default. The route answers 500 in that state, not 404.
    metaConfigured: false,
    role: "owner",
    publishTest: { enabled: true, allowed: true, can_override: true, state: "passed", run: null },
    telegramConnect: null,
    telegramDelivery: { delivery_status: "connected", message: "The connection is ready." },
    whatsappDelivery: { delivery_status: "connected" },
    providerResults: {}, providerRequests: [],
    telegramTokens: [],
    calls: [],
    puts: []
  }, overrides);
}

async function install(page, world) {
  for (const kind of ['telegram', 'whatsapp', 'channel-server']) {
    world[kind] = world[kind].map(row => row.connection_status === 'connected' && row.verified_at === undefined
      ? { ...row, verified_at: '2026-09-14T04:00:00Z' } : row);
  }
  await page.addInitScript(role => {
    sessionStorage.setItem("token", "fake-tenant-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify({
      id: 1, email: "operator@northweave.test", full_name: "Operator", role
    }));
  }, world.role);

  await page.route('**/*', route => {
    const target = new URL(route.request().url());
    return target.hostname === '127.0.0.1' ? route.continue() : route.abort();
  });

  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("https://connect.facebook.net/**", route => route.abort());

  await page.route("**/api/**", async route => {
    const req = route.request();
    const url = req.url();
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    world.calls.push(`${req.method()} ${path}`);

    if (path.includes("/api/testbot/publish-test?") && req.method() === "GET") {
      return route.fulfill(json({ status: "success", data: world.publishTest }));
    }

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
      world.telegramTokens.push(JSON.parse(req.postData() || "{}").bot_token);
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
        connection_status: "connected", is_active: true, last_error: null,
        verified_at: '2026-09-14T04:00:00Z'
      }];
      return route.fulfill(json({
        status: "success",
        data: { id: 3, bot_username: "northweave_bot", connection_status: "connected" }
      }));
    }

    if (path.startsWith("/api/channel-server/connect") && req.method() === "POST") {
      const body = req.postDataJSON();
      expect(body.risk_consent).toBe(true);
      world["channel-server"] = [{id: 8, is_active: true, connection_status: "pending", phone_number: body.phone_number}];
      if (body.method === "qr") return route.fulfill(json({status: "success", channel_id: 8, method: "qr"}));
      return route.fulfill(json({status: "success", channel_id: 8, pairing_code: "ABCD1234"}));
    }
    if (/^\/api\/channel-server\/channels\/\d+\/qr/.test(path) && req.method() === "GET") {
      return route.fulfill(json({status: "success", channel_id: 8, qr: "data:image/png;base64,iVBORw0KGgo="}));
    }
    const delivery = path.match(/\/api\/(telegram|whatsapp)\/channels\/[^/]+\/delivery/);
    if (delivery) {
      return route.fulfill(json({ status: "success", data: world[delivery[1] + 'Delivery'] }));
    }

    const setup = path.match(/\/api\/(whatsapp)\/(connect|embedded-signup\/complete|channels\/[^/]+\/reconnect)/);
    if (setup && ['POST', 'PUT'].includes(req.method())) {
      const kind = setup[1];
      const body = JSON.parse(req.postData() || '{}');
      world.providerRequests.push({ kind, body, method: req.method(), path });
      const outcome = world.providerResults[kind] || {};
      if (outcome.error) return route.fulfill({ status: outcome.status || 400,
        contentType: 'application/json', body: JSON.stringify({ status: 'error', message: outcome.error }) });
      const current = world[kind][0] || {};
      const record = { id: 40, chatbot_id: 42, is_active: !outcome.pending,
        connection_status: outcome.pending ? 'pending' : 'connected', session_id: body.session_id || '456',
        verified_at: outcome.pending ? null : '2026-09-14T04:00:00Z',
        phone_number: body.phone_number || current.phone_number,
        display_phone_number: body.phone_number || current.display_phone_number,
         };
      world[kind] = [record, ...world[kind].filter(row => row.id !== record.id).map(row => outcome.pending ? row : { ...row, is_active: false, connection_status: 'disconnected' })];
      return route.fulfill({ status: outcome.pending ? 202 : 200, contentType: 'application/json',
        body: JSON.stringify({ status: outcome.pending ? 'pending' : 'success', data: record,
          next_action: outcome.pending ? 'configure_webhook' : undefined }) });
    }

    for (const kind of ["telegram", "whatsapp", "channel-server"]) {
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
  await page.goto(`${staticOrigin}/integration.html?bot_id=${BOT_ID}`);
  await expect(page.locator("#pub-options > .pub-option")).toHaveCount(4, { timeout: 15000 });
}

test.describe("Test before publishing", () => {
  const first = { key: "common", status: "ok", checks: [] };
  const flagged = { key: "fact", status: "unchecked", checks: [
    { category: "review", subtype: "incomplete", label: "Partly checked. The AI review was unavailable." }
  ] };
  const run = { run_id: "sample-run", scenario_keys: ["common", "fact"], answers: [], flagged_keys: [], passed: false };
  const initial = { enabled: true, allowed: false, can_override: true, state: "not_tested", run: null };
  const review = { ...initial, state: "needs_review", run: { ...run, answers: [first, flagged], flagged_keys: ["fact"] } };
  const savedGrades = "Only saved grades are shown for answers without a preview. Run tests again to see the full answers.";

  test("answers the server scenarios in order and enables connections after a pass", async ({ page }) => {
    const world = makeWorld({ publishTest: initial });
    await open(page, world);
    const telegram = page.getByRole("button", { name: "Choose Telegram" });
    await expect(telegram).toBeDisabled();
    await expect(page.getByRole("button", { name: "Manage website" })).toBeEnabled();
    const requests = [];
    let secondAnswer;
    await page.route("**/api/testbot/publish-test**", async route => {
      const req = route.request();
      if (req.method() === "GET") return route.fulfill(json({ status: "success", data: world.publishTest }));
      if (!new URL(req.url()).pathname.endsWith("/answer")) {
        world.publishTest = { ...initial, state: "running", run };
        return route.fulfill(json({ status: "success", data: { ...world.publishTest, ticket: "opaque" } }));
      }
      const body = req.postDataJSON();
      requests.push(body);
      const done = body.key === "fact";
      if (done) await new Promise(resolve => { secondAnswer = resolve; });
      world.publishTest = { ...initial, allowed: done, state: done ? "passed" : "running",
        run: { ...run, passed: done, answers: done ? [first, { key: "fact", status: "unchecked", checks: [] }] : [first] } };
      return route.fulfill(json({ status: "success", data: { ...world.publishTest, question: "What do you offer?", reply: "<b>Business reply</b>" } }));
    });
    await page.getByRole("button", { name: "Run tests" }).click();
    await expect(page.locator("#pub-test-status")).toHaveText("Question 2 of 2");
    await expect.poll(() => typeof secondAnswer).toBe("function");
    secondAnswer();
    await expect(page.locator("#pub-test-status")).toHaveText("Passed");
    await expect(page.locator("#pub-test-results")).toContainText("Checked: no issues found.");
    await expect(page.locator("#pub-test-results")).toContainText("Not checked.");
    await expect(page.locator("#pub-test-results")).toContainText("<b>Business reply</b>");
    await expect(page.getByText(savedGrades)).toBeHidden();
    await expect(page.locator("#pub-test-results b")).toHaveCount(0);
    expect(requests).toEqual([{ ticket: "opaque", key: "common" }, { ticket: "opaque", key: "fact" }]);
    await expect(telegram).toBeEnabled();
    await page.reload();
    await expect(page.getByText(savedGrades)).toBeVisible();
    await expect(page.locator("#pub-test-results")).not.toContainText("Business reply");
    await expect(page.locator("#pub-test-results")).toContainText("Checked: no issues found.");
    expect(requests).toHaveLength(2);
  });

  test("an admin can acknowledge another operator's saved grades without a paid rerun", async ({ page }) => {
    const twoFlagged = { ...review, run: { ...review.run, answers: [
      { key: "common", status: "attention", checks: [{ category: "facts", subtype: "price", label: "A price that is not in your knowledge." }] },
      flagged
    ], flagged_keys: ["common", "fact"] } };
    const world = makeWorld({ role: "admin", publishTest: twoFlagged });
    await open(page, world);
    const submit = page.getByRole("button", { name: "Publish anyway" });
    await expect(submit).toBeDisabled();
    await expect(page.getByText(savedGrades)).toBeVisible();
    await expect(page.locator("#pub-test-results")).toContainText(flagged.checks[0].label);
    await page.getByRole("checkbox", { name: "I acknowledge the flagged result for answer 1." }).check();
    await expect(submit).toBeDisabled();
    await page.getByRole("checkbox", { name: "I acknowledge the flagged result for answer 2." }).check();
    await page.route("**/api/testbot/publish-test/sample-run/override?chatbot_id=42", route => {
      expect(route.request().postDataJSON()).toEqual({ acknowledged_keys: ["common", "fact"] });
      world.publishTest = { ...twoFlagged, allowed: true, state: "overridden" };
      return route.fulfill(json({ status: "success", data: world.publishTest }));
    });
    await submit.click();
    await expect(page.getByRole("button", { name: "Choose Telegram" })).toBeEnabled();
    await expect(page.locator("#pub-test-status")).toHaveText("Approved to publish");
    expect(world.calls).not.toContain("POST /api/testbot/publish-test?chatbot_id=42");
  });

  test("a changed fingerprint blocks the Meta popup", async ({ page }) => {
    const world = makeWorld({ metaConfigured: true });
    await open(page, world);
    await page.getByRole("button", { name: "Choose WhatsApp", exact: true }).click();
    await page.locator("#pub-meta-phone").fill("+60123456789");
    await page.evaluate(() => { window.FB = { login() { window.metaPopupOpened = true; } }; });
    world.publishTest = { ...initial, state: "outdated" };
    await page.getByRole("button", { name: "Connect with Meta" }).click();
    await expect(page.locator("#pub-test-status")).toHaveText("Out of date because training data or settings changed");
    expect(await page.evaluate(() => Boolean(window.metaPopupOpened))).toBe(false);
    expect(world.providerRequests).toHaveLength(0);
  });

  test("a server gate conflict shows the new test state without reporting a failed connection", async ({ page }) => {
    const world = makeWorld();
    await open(page, world);
    await page.getByRole("button", { name: "Choose Telegram" }).click();
    await page.getByLabel("Paste the code here").fill("8123456789:TEST_FIXTURE_ONLY");
    await page.route("**/api/telegram/connect?chatbot_id=42", route => {
      world.publishTest = { ...initial, state: "outdated" };
      return route.fulfill({ status: 409, contentType: "application/json",
        body: JSON.stringify({ status: "error", code: "PUBLISH_TEST_REQUIRED", message: "Run publish tests again." }) });
    });
    await page.locator("#pub-telegram-connect").click();
    await expect(page.locator("#pub-test-status")).toHaveText("Out of date because training data or settings changed");
    await expect(page.locator("#pub-telegram-connect")).toBeDisabled();
    expect(await page.evaluate(() => sessionStorage.getItem("telegramAttemptFailed:42"))).toBeNull();
  });

  test("Continue with Meta runs its own gate check after popup activation expires", async ({ page }) => {
    const world = makeWorld({ metaConfigured: true });
    await open(page, world);
    const sdk = "window.FB = { init() {}, login(done) { window.metaLogins++; done({}); } };";
    await page.route("https://connect.facebook.net/**", route => route.fulfill({ contentType: "text/javascript", body: sdk }));
    await page.evaluate(() => {
      window.metaLogins = 0;
      window.metaActive = false;
      Object.defineProperty(navigator, "userActivation", { get: () => ({ isActive: window.metaActive }) });
    });
    await page.getByRole("button", { name: "Choose WhatsApp", exact: true }).click();
    await page.locator("#pub-meta-phone").fill("+60123456789");
    const statusReads = () => world.calls.filter(call => call === "GET /api/testbot/publish-test?chatbot_id=42").length;
    const initialReads = statusReads();
    await page.getByRole("button", { name: "Connect with Meta" }).click();
    await expect(page.getByRole("button", { name: "Continue with Meta" })).toBeEnabled();
    expect(statusReads()).toBe(initialReads + 1);
    expect(await page.evaluate(() => window.metaLogins)).toBe(0);
    await page.evaluate(() => { window.metaActive = true; });
    world.publishTest = { ...initial, state: "outdated" };
    await page.getByRole("button", { name: "Continue with Meta" }).click();
    await expect(page.locator("#pub-test-status")).toHaveText("Out of date because training data or settings changed");
    expect(statusReads()).toBe(initialReads + 2);
    expect(await page.evaluate(() => window.metaLogins)).toBe(0);
  });

  test("a superseded Meta preflight cannot use a previously displayed pass", async ({ page }) => {
    await open(page, makeWorld({ metaConfigured: true }));
    const readers = [];
    let sdkLoads = 0;
    await page.route("https://connect.facebook.net/**", route => {
      sdkLoads++;
      return route.fulfill({ contentType: "text/javascript", body: "window.FB = { init() {}, login(done) { done({}); } };" });
    });
    await page.route("**/api/testbot/publish-test?chatbot_id=42", async route => {
      await new Promise(resolve => readers.push(resolve));
      return route.fulfill(json({ status: "success", data: { ...initial, state: "outdated" } }));
    });
    await page.getByRole("button", { name: "Choose WhatsApp", exact: true }).click();
    await page.locator("#pub-meta-phone").fill("+60123456789");
    await page.getByRole("button", { name: "Connect with Meta" }).click();
    await expect.poll(() => readers.length).toBe(1);
    await page.getByRole("button", { name: "Check again" }).click();
    await expect.poll(() => readers.length).toBe(2);
    readers[0]();
    await expect(page.locator("#pub-meta-connect")).toHaveText("Connect with Meta");
    expect(sdkLoads).toBe(0);
    readers[1]();
    await expect(page.locator("#pub-test-status")).toHaveText("Out of date because training data or settings changed");
  });
});

test("equal channel choices come before existing connections", async ({ page }) => {
  const world = makeWorld();
  await open(page, world);

  // Section order is the reading order and the tab order.
  const sections = await page.locator("main > .kw-panel, main > .pub-settings")
    .evaluateAll(nodes => nodes.map(n => n.id));
  expect(sections).toEqual(["pub-test", "pub-add", "pub-live", "pub-settings"]);
  await expect(page.locator('#pub-options > .pub-option.is-lead')).toHaveCount(0);
  expect(world.puts).toHaveLength(0);

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

  for (const id of ["#pub-look", "#pub-lead", "#pub-adv"]) {
    await expect(page.locator(id)).not.toHaveAttribute("open", /.*/);
  }
});

test("a disabled link reads as off and offers one tap to fix it", async ({ page }) => {
  const world = makeWorld();
  world.widget.is_enabled = false;
  await open(page, world);

  await expect(page.locator('[data-option="website"] .kw-pill-off')).toContainText("Turned off");
  await expect(page.locator("#pub-live-count")).toHaveText("0");

  await page.getByRole('button', { name: 'Choose website', exact: true }).click();
  expect(world.puts).toHaveLength(0);
  const turnOn = page.getByRole("button", { name: "Enable website and share link", exact: true });
  await expect(turnOn).toBeVisible();
  await turnOn.click();

  await expect(page.locator("#pub-live-body .kw-pill-ready")).toContainText("Enabled · not checked");
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

test("Meta sign-in unavailable still allows explicit verified Cloud API setup", async ({ page }) => {
  await open(page, makeWorld());

  const row = page.locator('[data-option="whatsapp"]');
  await row.getByRole('button', { name: 'Choose WhatsApp' }).click();
  await expect(row.locator("#pub-meta-connect")).toHaveCount(0);
  await expect(row).toContainText("Meta sign-in is unavailable");
  await row.getByText('Use existing Meta Cloud API credentials', { exact: true }).click();
  await expect(row.locator('#pub-meta-token')).toHaveAttribute('type', 'password');
  await expect(row.locator('#pub-meta-manual-connect')).toBeVisible();
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

test("a full plan names every bot holding a slot, not just this one", async ({ page }) => {
  // Slots are shared by all the company's bots. With one channel here and
  // the other slot on another bot, "Plan full" must say where it went.
  const world = makeWorld({
    usage: { channels: { used: 2, limit: 2, slots: [
      { provider: "telegram", chatbot_id: 53, bot_name: "Olympic <b>Edu</b>" },
      { provider: "whatsapp_link", chatbot_id: 42, bot_name: "Northweave Clinic" }
    ] } },
    "channel-server": [{ id: 3, phone_number: "+60110000000", connection_status: "connected", is_active: true }]
  });
  await open(page, world);

  await expect(page.locator("#pub-slots")).toHaveText("2 of 2");
  await expect(page.locator("#pub-slot-note")).toHaveText("2 of 2 paid slots used across all your bots");

  const row = page.locator('[data-option="telegram"]');
  await expect(row.locator(".kw-badge-support").last()).toContainText("Plan full");
  await expect(row).toContainText("already in use: Telegram on Olympic <b>Edu</b>, WhatsApp (linked device) on this bot.");
  // The bot name is text, never markup, and it leads to where that slot is freed.
  await expect(row.locator("b")).toHaveCount(0);
  await expect(row.getByRole("link", { name: "Olympic <b>Edu</b>" }))
    .toHaveAttribute("href", "integration.html?bot_id=53");
  await expect(page.locator('[data-option="whatsapp"]'))
    .toContainText("All plan channels are in use: Telegram on Olympic <b>Edu</b>");
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

  // Provider credentials stay masked while the verified identity confirms setup.
  await expect(page.locator("#pub-telegram-code")).toHaveAttribute("type", "password");
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
  await expect(liveRow.locator(".kw-pill-ready")).toContainText("Connected");
  await expect(liveRow.getByRole("link", { name: /Open in Telegram/ }))
    .toHaveAttribute("href", "https://t.me/northweave_bot");

  await expect(page.locator("#pub-live-count")).toHaveText("2");
  await expect(page.locator('[data-option="telegram"]')).toContainText('Manage connection');
});

test("Telegram regression: latest failed attempt stays visible above the previous bot", async ({ page }) => {
  const world = makeWorld({ telegram: [
    { id: 8, bot_username: "new_bot", connection_status: "failed", is_active: false },
    { id: 3, bot_username: "old_bot", connection_status: "connected", is_active: true }
  ] });
  await open(page, world);
  const row = page.locator('#pub-live-body [data-live="telegram"]');
  await expect(row).toContainText("@new_bot");
  await expect(row).toContainText("Needs a fix");
  await expect(row).toContainText("Previous bot @old_bot is still enabled");
  await expect(row.locator('.kw-pill-ready')).toHaveCount(0);
  await page.locator('#pub-live').scrollIntoViewIfNeeded();
  await expect(page.locator('#pub-live')).toHaveCSS('opacity', '1');
  await row.screenshot({ path: test.info().outputPath('telegram-failure-state.png') });
  await page.screenshot({ path: test.info().outputPath('telegram-latest-attempt-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 850 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
    .toBeLessThanOrEqual(0);
  await row.scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath('telegram-latest-attempt-mobile.png'), fullPage: true });
});

for (const deliveryStatus of ['failed', 'unknown']) {
  test(`Telegram regression: ${deliveryStatus} delivery cannot display Connected`, async ({ page }) => {
    const world = makeWorld({
      telegram: [{ id: 3, bot_username: 'old_bot', connection_status: 'connected', is_active: true }],
      telegramDelivery: { delivery_status: deliveryStatus, message: 'Connection needs checking.' }
    });
    await open(page, world);
    const row = page.locator('#pub-live-body [data-live="telegram"]');
    await expect(row.locator('.kw-pill-ready')).toHaveCount(0);
    await expect(row).toContainText(deliveryStatus === 'failed' ? 'Needs a fix' : 'Check needed');
    expect(world.calls.some(call => call.includes('/channels/3/delivery'))).toBe(true);
  });
}

test('Telegram regression: changing bot submits the new code and preserves a failed attempt on refresh', async ({ page }) => {
  const world = makeWorld({
    telegram: [{ id: 3, bot_username: 'old_bot', connection_status: 'connected', is_active: true }],
    telegramConnect: { status: 400, error: 'Unauthorized' }
  });
  await open(page, world);
  await page.getByRole('button', { name: 'Change bot', exact: true }).click();
  const newCode = '9999999999:NEWxxxxxxxxxxxxxxxxxxxxx';
  await page.locator('#pub-telegram-code').fill(newCode);
  await page.locator('#pub-telegram-connect').click();
  await expect(page.locator('#pub-telegram-result')).toContainText('Copy the whole line');
  expect(world.telegramTokens).toEqual([newCode]);
  expect(world.calls.some(call => call.includes('/reconnect'))).toBe(false);
  await page.locator('#pub-recheck').click();
  await expect(page.locator('#pub-live-body')).toContainText('New Telegram connection failed');
  await expect(page.locator('#pub-live-body')).toContainText('@old_bot');
  await page.reload();
  await expect(page.locator('#pub-live-body')).toContainText('New Telegram connection failed');
  expect(await page.evaluate(() => Object.values(sessionStorage).join(' '))).not.toContain(newCode);
});

test('Telegram regression: disconnect then connect uses the replacement identity', async ({ page }) => {
  const world = makeWorld({ telegram: [
    { id: 3, bot_username: 'old_bot', connection_status: 'connected', is_active: true }
  ] });
  await open(page, world);
  await page.locator('[data-disconnect="telegram"]').click();
  await page.locator('#pub-confirm-ok').click();
  await page.locator('[data-flow-open="telegram"]').click();
  await page.locator('#pub-telegram-code').fill('9999999999:NEWxxxxxxxxxxxxxxxxxxxxx');
  await page.locator('#pub-telegram-connect').click();
  await expect(page.locator('#pub-live-body [data-live="telegram"]')).toContainText('@northweave_bot');
  await expect(page.locator('#pub-live-body')).not.toContainText('@old_bot');
  expect(world.telegramTokens).toEqual(['9999999999:NEWxxxxxxxxxxxxxxxxxxxxx']);
  expect(world.calls.some(call => call.includes('/reconnect'))).toBe(false);
});

test('Telegram regression: an incomplete health response stays unverified', async ({ page }) => {
  await open(page, makeWorld({
    telegram: [{ id: 3, bot_username: 'old_bot', connection_status: 'connected', is_active: true }],
    telegramDelivery: {}
  }));
  await expect(page.locator('#pub-live-body [data-live="telegram"]')).toContainText('Check needed');
  await expect(page.locator('#pub-live-body [data-live="telegram"] .kw-pill-ready')).toHaveCount(0);
});

test('Telegram regression: successful replacement shows only the new identity', async ({ page }) => {
  const world = makeWorld({ telegram: [
    { id: 3, bot_username: 'old_bot', connection_status: 'connected', is_active: true }
  ] });
  await open(page, world);
  await page.getByRole('button', { name: 'Change bot', exact: true }).click();
  await page.locator('#pub-telegram-code').fill('9999999999:NEWxxxxxxxxxxxxxxxxxxxxx');
  await page.locator('#pub-telegram-connect').click();
  const row = page.locator('#pub-live-body [data-live="telegram"]');
  await expect(row).toContainText('@northweave_bot');
  await expect(row.locator('.kw-pill-ready')).toContainText('Connected');
  await expect(page.locator('#pub-live-body')).not.toContainText('@old_bot');
  await expect(page.locator('#pub-flow-telegram')).toBeHidden();
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
  await expect(row).toContainText("This Telegram connection needs a fix");
  await expect(row).not.toContainText("getMe");
  await expect(row.getByRole("button", { name: "Reconnect same bot" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Change bot", exact: true })).toBeVisible();
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

test('choosing Telegram does not enable website, including after reload', async ({ page }) => {
  test.setTimeout(45000);
  const world = makeWorld();
  world.widget.is_enabled = false;
  await open(page, world);
  await expect(page.getByText('No channels connected yet', { exact: true })).toBeVisible();
  await expect(page.locator('#pub-settings')).toBeHidden();
  await page.getByRole('button', { name: 'Choose Telegram', exact: true }).click();
  await page.locator('#pub-telegram-code').fill('8123456789:AAHxxxxxxxxxxxxxxxxxxxxx');
  await page.locator('#pub-telegram-connect').click();
  await expect(page.locator('#pub-live-body [data-live="telegram"]')).toBeVisible();
  await expect(page.locator('#pub-live-body .pub-share')).toHaveCount(0);
  expect(world.puts).toHaveLength(0);
  expect(world.widget.is_enabled).toBe(false);
  await page.reload();
  await expect(page.locator('[data-option="website"]')).toContainText('Turned off');
  expect(world.puts).toHaveLength(0);
});

test('a temporary website address is never reported as working', async ({ page }) => {
  const world = makeWorld();
  world.embed.delivery = { persistent_url: false, base_kind: 'temporary',
    reachability: 'not_checked', message: 'This test link can stop when the tunnel closes. A permanent address is needed.' };
  await open(page, world);
  await expect(page.locator('#pub-live-body')).toContainText('Address needs setup');
  await expect(page.locator('#pub-live-body')).toContainText('A permanent address is needed');
  await expect(page.locator('#pub-live-count')).toHaveText('0');
  await expect(page.locator('#pub-live-body')).not.toContainText('Working');
});

test('disconnect and reconnect keep the same share link; settings cannot publish it', async ({ page }) => {
  test.setTimeout(45000);
  const world = makeWorld();
  await open(page, world);
  await page.getByRole('button', { name: 'Turn the link off', exact: true }).click();
  await expect(page.locator('#pub-confirm-cancel')).toBeFocused();
  await page.locator('#pub-confirm-ok').click();
  await expect(page.locator('[data-option="website"]')).toContainText('Turned off');
  await page.reload();
  await page.getByRole('button', { name: 'Choose website', exact: true }).click();
  await page.locator('#pub-look > summary').click();
  await page.locator('#ww-display_name').fill('New display name');
  await page.locator('[data-save="look"]').click();
  await expect(page.locator('[data-savestate="look"]')).toContainText('still off');
  expect(world.puts.at(-1)).not.toHaveProperty('is_enabled');
  await page.getByRole('button', { name: 'Enable website and share link', exact: true }).click();
  await expect(page.locator('#pub-live-body .kw-idrow code')).toHaveText(SHARE_URL);
  expect(world.calls.some(call => call.includes('regenerate-key'))).toBe(false);
});

test('a website read failure cannot hide a connected Telegram channel', async ({ page }) => {
  const world = makeWorld({ telegram: [{ id: 3, bot_username: 'northweave_bot',
    connection_status: 'connected', is_active: true }] });
  await install(page, world);
  await page.route('**/api/bots/42/widget', route => route.fulfill({ status: 400,
    contentType: 'application/json', body: JSON.stringify({ status: 'error' }) }));
  await page.goto(`${staticOrigin}/integration.html?bot_id=42`);
  await expect(page.locator('#pub-live-body [data-live="telegram"]')).toBeVisible();
  await expect(page.locator('#pub-live-body')).toContainText('could not be refreshed');
});

test('an unknown connection state is never presented as an empty account', async ({ page }) => {
  await install(page, makeWorld());
  await page.route('**/api/bots/42/widget', route => route.fulfill({ status: 400,
    contentType: 'application/json', body: JSON.stringify({ status: 'error' }) }));
  await page.goto(`${staticOrigin}/integration.html?bot_id=42`);
  await expect(page.locator('#pub-live-body')).toContainText('could not be refreshed');
  await expect(page.getByRole('heading', { name: 'No channels connected yet' })).toHaveCount(0);
  await expect(page.locator('#pub-live-count')).toHaveText('-');
});

async function fillMeta(page, phone = '+60123456789') {
  await page.locator('[data-flow-open="whatsapp"]').click();
  await page.locator('#pub-meta-phone').fill(phone);
  await page.locator('#pub-flow-whatsapp summary').click();
  await page.locator('#pub-meta-waba').fill('1234');
  await page.locator('#pub-meta-number-id').fill('5678');
  await page.locator('#pub-meta-token').fill('new-meta-test-token');
}

test('Meta replacement accepts new number and credentials even when the plan is full', async ({ page }) => {
  const world = makeWorld({ usage: { channels: { used: 2, limit: 2 } }, whatsapp: [
    { id: 3, display_phone_number: '+60110000000', connection_status: 'connected', is_active: true }
  ] });
  await open(page, world);
  await fillMeta(page);
  await expect(page.locator('#pub-flow-whatsapp')).toContainText('stays enabled until the new number is verified');
  await page.locator('#pub-meta-manual-connect').click();
  await expect(page.locator('[data-live="whatsapp"]')).toContainText('+60123456789');
  await expect(page.locator('#pub-flow-whatsapp')).toBeHidden();
  expect(world.providerRequests).toEqual([expect.objectContaining({ kind: 'whatsapp', method: 'POST', body: {
    phone_number: '+60123456789', access_token: 'new-meta-test-token', waba_id: '1234', phone_number_id: '5678'
  } })]);
  expect(world.whatsapp.filter(row => row.is_active)).toHaveLength(1);
  expect(await page.evaluate(() => Object.values(sessionStorage).join(' '))).not.toContain('new-meta-test-token');
});

test('phone validation prevents a provider request with a local-only number', async ({ page }) => {
  const world = makeWorld();
  await open(page, world);
  await fillMeta(page, '0123456789');
  await page.locator('#pub-meta-manual-connect').click();
  expect(world.providerRequests).toHaveLength(0);
  expect(await page.locator('#pub-meta-phone').evaluate(input => input.validity.valid)).toBe(false);
});

test('failed Meta replacement stays visible after reload and retains the old number', async ({ page }) => {
  test.slow(); // Two full page loads plus the publish-test status on each: ~16 s on a loaded PC.
  const world = makeWorld({ whatsapp: [
    { id: 3, display_phone_number: '+60110000000', connection_status: 'connected', is_active: true }
  ], providerResults: { whatsapp: { error: 'The verified number does not match.', status: 400 } } });
  await open(page, world);
  await fillMeta(page);
  await page.locator('#pub-meta-manual-connect').click();
  await expect(page.locator('#pub-live-body')).toContainText('New WhatsApp Business connection failed');
  await page.reload();
  await expect(page.locator('#pub-live-body')).toContainText('New WhatsApp Business connection failed');
  await expect(page.locator('[data-live="whatsapp"]')).toContainText('+60110000000');
  expect(world.whatsapp[0].is_active).toBe(true);
});

test('Meta failed webhook never show Connected', async ({ page }) => {
  const world = makeWorld({
    whatsapp: [{ id: 2, display_phone_number: '+60110000000', is_active: true, connection_status: 'connected' }],
    whatsappDelivery: { delivery_status: 'failed' },
  });
  await open(page, world);
  await expect(page.locator('[data-live="whatsapp"]')).toContainText('Needs a fix');
  await expect(page.locator('[data-live="whatsapp"] .kw-pill-ready')).toHaveCount(0);
});

test('replacement forms fit a phone viewport', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 850 });
  await open(page, makeWorld());
  await fillMeta(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  for (const width of await page.locator('#pub-flow-whatsapp input:visible').evaluateAll(inputs => inputs.map(input => input.getBoundingClientRect().width))) expect(width).toBeGreaterThan(180);
  await page.locator('#pub-flow-whatsapp').screenshot({ path: testInfo.outputPath('meta-replacement-mobile.png') });
});

test('healthy provider readback cannot enable an unverified legacy connection', async ({ page }) => {
  const world = makeWorld();
  for (const kind of ['telegram', 'whatsapp']) {
    world[kind] = [{ id: 3, phone_number: '+60120000000', bot_username: 'old_bot',
      is_active: true, connection_status: 'connected', verified_at: null }];
  }
  await open(page, world);
  for (const kind of ['telegram', 'whatsapp']) {
    await expect(page.locator(`[data-live="${kind}"]`)).toContainText('Check needed');
    await expect(page.locator(`[data-live="${kind}"] .kw-pill-ready`)).toHaveCount(0);
  }
});


test("linked device requires consent, shows a pairing code and detects connection", async ({ page }) => {
  const world = makeWorld();
  await open(page, world);
  const card = page.locator("#pub-linked");
  await expect(page.locator("#pub-options > .pub-option").first()).toContainText("Recommended");
  await expect(card).toContainText("WhatsApp may restrict or ban this number.");
  await card.getByLabel("Phone number").fill("0123456789");
  const pair = card.getByRole("button", { name: "Get pairing code" });
  await expect(pair).toBeDisabled();
  await card.getByLabel("I understand the risk").check();
  await pair.click();
  await expect(card.locator("output")).toHaveText("ABCD1234");
  await expect(card).toContainText("Link with phone number instead");
  Object.assign(world["channel-server"][0], {connection_status: "connected", verified_at: "now"});
  await expect(card.locator("#pub-linked-status")).toHaveText("Connected", {timeout: 12000});
  await expect(card.getByRole("button", {name: "Disconnect"})).toBeVisible();
  await card.getByRole("button", {name: "Disconnect"}).click();
  await expect(card.locator("form")).toBeVisible();
  await expect(card.locator("output")).toBeEmpty();
});

test("linked device accepts a number typed with + and spaces", async ({ page }) => {
  const world = makeWorld();
  await open(page, world);
  const card = page.locator("#pub-linked");
  await card.getByLabel("Phone number").fill("+60 12-345 6789");
  await card.getByLabel("I understand the risk").check();
  const pair = card.getByRole("button", { name: "Get pairing code" });
  await expect(pair).toBeEnabled();
  await pair.click();
  await expect(card.locator("output")).toHaveText("ABCD1234");
  expect(world["channel-server"][0].phone_number).toBe("60123456789");
});

test("linked device can link by scanning a QR code instead of a pairing code", async ({ page }) => {
  const world = makeWorld();
  await open(page, world);
  const card = page.locator("#pub-linked");
  await card.getByLabel("Phone number").fill("+60 12-345 6789");
  const scan = card.getByRole("button", { name: "Scan QR code instead" });
  await expect(scan).toBeDisabled();
  await card.getByLabel("I understand the risk").check();
  await scan.click();
  const qr = card.getByRole("img", { name: "WhatsApp QR code" });
  await expect(qr).toBeVisible();
  await expect(qr).toHaveAttribute("src", /^data:image\/png;base64,/);
  await expect(card).toContainText("scan this QR code");
  await expect(card.locator("output")).toBeEmpty();
  Object.assign(world["channel-server"][0], {connection_status: "connected", verified_at: "now"});
  await expect(card.locator("#pub-linked-status")).toHaveText("Connected", {timeout: 12000});
  await expect(qr).toBeHidden();
});

test("linked-device consent does not bypass a pending publish test", async ({ page }) => {
  const world = makeWorld({publishTest: {enabled: true, allowed: false, state: "not_tested"}});
  await open(page, world);
  const card = page.locator("#pub-linked");
  await card.getByLabel("Phone number").fill("0123456789");
  await card.getByLabel("I understand the risk").check();
  const pair = card.getByRole("button", {name: "Get pairing code"});
  await expect(pair).toBeDisabled();
  await expect(pair).toHaveAttribute("aria-describedby", /pub-test-status/);
  expect(world.calls.some(call => call.startsWith("POST /api/channel-server"))).toBe(false);
});
