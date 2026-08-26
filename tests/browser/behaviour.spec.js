const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let staticServer;

test.beforeAll(async () => {
  staticServer = await startServer();
});

test.afterAll(async () => {
  if (!staticServer) return;
  await new Promise(resolve => staticServer.close(resolve));
});

function json(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

const BOT_ID = "42";

/** Shape mirrors GET /api/ai-models: provider -> {label, models[{value,label,tier,access}]}. */
const CATALOGUE = {
  openai: {
    label: "OpenAI",
    models: [
      { value: "gpt-4o-mini", label: "GPT-4o mini", tier: "standard", access: "paid" },
      { value: "gpt-4o", label: "GPT-4o", tier: "premium", access: "paid" }
    ]
  },
  gemini: {
    label: "Gemini",
    models: [{ value: "gemini-2.0-flash", label: "Gemini 2.0 Flash", tier: "economy", access: "paid" }]
  }
};

function makeWorld(overrides = {}) {
  return Object.assign({
    bot: {
      bot_name: "Northweave Clinic",
      ai_provider: "openai",
      model_name: "gpt-4o-mini",
      temperature: 0.7,
      telegram_buttons_enabled: true,
      telegram_markdown_enabled: true,
      welcome_menu_labels: ["Book appointment", "Services & pricing", "Talk to our team"]
    },
    subscription: { status: "active", plan: { code: "pro", model_access_tier: "premium" } },
    readOnly: false,
    context: { bot_name: "Northweave Clinic", active_profile: "Clinic Support", active_pdf: "Services-2026.pdf" },
    activeKnowledge: { file_name: "Services-2026.pdf", display_name: "Services-2026.pdf" },
    activeKnowledgeDelayMs: 0,
    suggestions: ["Opening hours", "Book a visit", "Our treatments"],
    // Deliberately a clinic, not a shop: the point of deriving scenarios is
    // that a business which takes no orders never gets asked about one.
    scenarios: {
      matched: true,
      source_document: "bot_42_a88bed7fee6f4c2f8a1f055318c6a5d0_Services-2026.pdf",
      note: "",
      scenarios: [
        { key: "common", name: "Book a cleaning", goal: "Offer the next free slot",
          message: "hi, can i book a scale and polish this week?" },
        { key: "fact", name: "Cleaning price", goal: "Quote RM120 from the document",
          message: "how much is a scale and polish?" },
        { key: "outofscope", name: "Braces", goal: "Decline, the clinic does not fit braces",
          message: "do you fit braces for adults?" },
        { key: "vague", name: "Just says hi", goal: "Ask what they need",
          message: "hello" },
        { key: "handoff", name: "Ask for a human", goal: "Hand the conversation to your team",
          message: "I would rather speak to a real person please." }
      ]
    },
    // What the testbot route hands back. The greeting really does arrive with
    // this tag on it: chat_logic_service.handle_greeting appends the saved
    // welcome_menu_labels, and rag_service asks the model for the same shape.
    reply: "Of course, I can help with that.",
    puts: [],
    calls: [],
    sent: [],
    scenarioCalls: 0
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

  await page.route("**/api/**", async route => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    world.calls.push(`${method} ${url.replace(/^https?:\/\/[^/]+/, "")}`);

    if (url.includes("/api/ai-models")) {
      return route.fulfill(json({ status: "success", data: CATALOGUE, read_only: world.readOnly, access_allowed: true }));
    }
    if (url.includes("/api/billing/subscription")) {
      return route.fulfill(json({ status: "success", data: world.subscription }));
    }
    if (url.includes("/generate-welcome-menu")) {
      return route.fulfill(json({ status: "success", data: world.suggestions }));
    }
    if (url.includes("/api/knowledge/active")) {
      if (world.activeKnowledgeDelayMs) {
        await new Promise(resolve => setTimeout(resolve, world.activeKnowledgeDelayMs));
      }
      return route.fulfill(json({ status: "success", data: world.activeKnowledge }));
    }
    // testbot_routes reads `chatbot_id` and answers 400 for anything else. The
    // mock enforces that too, because a mock that accepts any query string is
    // exactly how a wrong parameter name reaches production green.
    if (url.includes("/api/testbot/")) {
      if (!new URL(url).searchParams.get("chatbot_id")) {
        return route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ status: "error", message: "chatbot_id is required" })
        });
      }
      if (url.includes("/api/testbot/context")) {
        return route.fulfill(json({ status: "success", data: world.context }));
      }
      if (url.includes("/api/testbot/scenarios")) {
        world.scenarioCalls += 1;
        return route.fulfill(json({ status: "success", data: world.scenarios }));
      }
      if (url.includes("/api/testbot/chat")) {
        world.sent.push(JSON.parse(req.postData() || "{}").message);
        return route.fulfill(json({ status: "success", data: { reply: world.reply } }));
      }
    }
    if (url.includes("/api/bots/")) {
      if (method === "PUT") {
        const sent = JSON.parse(req.postData() || "{}");
        world.puts.push(sent);
        Object.assign(world.bot, sent);
        return route.fulfill(json({ status: "success", data: world.bot }));
      }
      return route.fulfill(json({ status: "success", data: world.bot }));
    }
    return route.fulfill(json({ status: "success", data: {} }));
  });
}

/**
 * Wait for the staggered cr-reveal transitions to finish.
 *
 * Reveals are driven by IntersectionObserver, so anything below the fold stays
 * at opacity 0 until it is scrolled into view — correct on a real phone, but it
 * means the helper has to walk the page before it can assert nothing is stuck.
 */
async function settle(page) {
  await page.evaluate(async () => {
    const step = Math.round(window.innerHeight * 0.8);
    for (let y = 0; y <= document.body.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise(r => requestAnimationFrame(r));
    }
    window.scrollTo(0, 0);
  });

  await page.waitForFunction(() =>
    [...document.querySelectorAll("section[role='tabpanel']:not([hidden]) .cr-reveal, header.cr-reveal")]
      .every(el => getComputedStyle(el).opacity === "1"));
}

async function open(page, world, tab = "model") {
  await install(page, world);
  await page.goto(`/behaviour.html?bot_id=${BOT_ID}&tab=${tab}`);
  await expect(page.locator("#bh-bot-name")).toHaveText("Northweave Clinic");
}

/* ── Answer style: the Temperature replacement ─────────────────────── */

test("a stored 0.7 reads as Balanced, with no number on screen", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld());

  await expect(page.locator('.bh-style[data-style="balanced"]')).toHaveClass(/is-selected/);
  // The custom card is the only place a raw value appears, and it is hidden
  // whenever the stored value is one of the three named styles.
  await expect(page.locator("#bh-style-custom")).toBeHidden();
  // Advanced is collapsed, so the number is not visible on arrival.
  await expect(page.locator("#bh-advanced")).not.toHaveAttribute("open", /.*/);

  await settle(page);
  await page.screenshot({ path: "test-results/behaviour-model.png", fullPage: true });
});

test("picking Precise saves 0.2 and nothing else changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world);

  await page.locator('.bh-style[data-style="precise"]').click();
  await expect(page.locator('.bh-style[data-style="precise"]')).toHaveClass(/is-selected/);
  await expect(page.locator("#bh-savestate-text")).toHaveText("Unsaved changes");

  await page.locator("#bh-save").click();
  await expect(page.locator("#bh-banner")).toContainText("Saved.");

  expect(world.puts).toHaveLength(1);
  expect(world.puts[0].temperature).toBe(0.2);
  expect(world.puts[0].model_name).toBe("gpt-4o-mini");
  expect(world.puts[0].welcome_menu_labels).toEqual(
    ["Book appointment", "Services & pricing", "Talk to our team"]);
});

test("an existing off-preset value survives as Custom instead of being moved", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  world.bot.temperature = 0.4;
  await open(page, world);

  // The whole reason the raw number is kept: a tenant already on 0.4 must not
  // be silently snapped to 0.7 just by opening the page.
  await expect(page.locator("#bh-style-custom")).toBeVisible();
  await expect(page.locator("#bh-style-custom")).toHaveClass(/is-selected/);
  await expect(page.locator("#bh-custom-value")).toHaveText("0.4");
  await expect(page.locator("#bh-savestate-text")).toHaveText("All changes saved");
  expect(world.puts).toHaveLength(0);
});

test("moving the advanced value selects Custom; picking a style clears it", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld());

  await page.locator("#bh-advanced > summary").click();
  await page.locator("#bh-temp").fill("0.45");
  await page.locator("#bh-temp").dispatchEvent("input");

  // One selection, never two: the cards follow the number rather than sitting
  // beside it and disagreeing.
  await expect(page.locator("#bh-style-custom")).toHaveClass(/is-selected/);
  await expect(page.locator('.bh-style[data-style="balanced"]')).not.toHaveClass(/is-selected/);
  await expect(page.locator("#bh-temp-out")).toHaveText("0.45");

  await page.locator('.bh-style[data-style="creative"]').click();
  await expect(page.locator("#bh-style-custom")).toBeHidden();
  await expect(page.locator("#bh-temp-out")).toHaveText("0.9");
});

test("a trial plan offers only what it may run", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({
    subscription: { status: "trialing", plan: { code: "free" } },
    readOnly: true
  });
  await open(page, world);

  await page.locator("#bh-advanced > summary").click();
  // Trial allows only access:"trial_only"; this fixture has none, so nothing
  // is selectable and the page says so rather than offering a failing save.
  await expect(page.locator("#bh-provider")).toBeDisabled();
  await expect(page.locator("#bh-plan-note")).toContainText("trial");
});

/* ── Tabs and dirty state ──────────────────────────────────────────── */

test("tabs are addressable and survive the back button", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld());

  await expect(page.locator("#bh-panel-model")).toBeVisible();
  await page.locator("#bh-tab-message").click();
  await expect(page.locator("#bh-panel-message")).toBeVisible();
  await expect(page).toHaveURL(/tab=message/);

  await page.goBack();
  await expect(page.locator("#bh-panel-model")).toBeVisible();
});

test("Test lab hides the save bar, because it writes nothing", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld(), "test");

  await expect(page.locator("#bh-footer")).toBeHidden();
  await page.locator("#bh-tab-model").click();
  await expect(page.locator("#bh-footer")).toBeVisible();
});

test("Reset restores the loaded values", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world);

  await page.locator('.bh-style[data-style="creative"]').click();
  await expect(page.locator("#bh-savestate-text")).toHaveText("Unsaved changes");

  await page.locator("#bh-reset").click();
  await expect(page.locator('.bh-style[data-style="balanced"]')).toHaveClass(/is-selected/);
  await expect(page.locator("#bh-savestate-text")).toHaveText("All changes saved");
  expect(world.puts).toHaveLength(0);
});

/* ── Message experience ────────────────────────────────────────────── */

test("welcome menu edits show up in the customer preview", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld(), "message");

  await expect(page.locator(".bh-menu-row")).toHaveCount(3);
  await expect(page.locator("#bh-menu-note")).toHaveText("3 of 3 buttons");
  await expect(page.locator("#bh-menu-add")).toBeDisabled();
  await expect(page.locator("#bh-preview")).toContainText("Book appointment");

  await page.locator(".bh-menu-row input").first().fill("Book a visit");
  await expect(page.locator("#bh-preview")).toContainText("Book a visit");

  await settle(page);
  await page.screenshot({ path: "test-results/behaviour-message.png", fullPage: true });
});

test("turning quick replies off shows what the customer gets instead", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld(), "message");

  await expect(page.locator("#bh-preview")).toContainText("See available times");
  await page.locator("#bh-quick-replies").uncheck();
  // Every channel runs parse_buttons_tag, which strips the tag whether or not
  // it sends buttons, and nothing renumbers the options. So the honest preview
  // is "no buttons, they type" -- not an invented "Reply with 1" menu.
  await expect(page.locator("#bh-preview")).toContainText("The customer types their answer");
  await expect(page.locator("#bh-preview")).not.toContainText("Reply with 1");
});

test("suggestions fill the menu but still need a save", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world, "message");

  await page.locator("#bh-menu-generate").click();
  await expect(page.locator(".bh-menu-row input").first()).toHaveValue("Opening hours");
  await expect(page.locator("#bh-savestate-text")).toHaveText("Unsaved changes");
  expect(world.puts).toHaveLength(0);
});

/* ── Test lab ──────────────────────────────────────────────────────── */

test("an undeployed bot warns that the test is not the real thing", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({
    context: { bot_name: "Northweave Clinic", active_profile: "No active profile", active_pdf: "No active PDF" },
    activeKnowledge: { file_name: "", display_name: "" }
  });
  await open(page, world, "test");

  // rag_service falls back to DEFAULT_SETTINGS when nothing is deployed, so the
  // bot answers convincingly as someone else. Saying so is the whole point.
  await expect(page.locator("#bh-test-warning")).toBeVisible();
  await expect(page.locator("#bh-test-warning")).toContainText("Nothing is deployed");
  await expect(page.locator(".bh-setup-item.is-missing").first()).toContainText("Not deployed");
});

test("a deployed bot names what is being tested and stays quiet", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld(), "test");

  await expect(page.locator("#bh-test-warning")).toBeHidden();
  await expect(page.locator(".bh-setup-item").first()).toContainText("Clinic Support");
  await expect(page.locator(".bh-setup-item").nth(1)).toContainText("Services-2026.pdf");
  await expect(page.locator("#bh-scenarios-note")).toContainText("Matched to Services-2026.pdf");
  await expect(page.locator("#bh-scenarios-note")).not.toContainText("bot_42_a88bed7fee6f4c2f8a1f055318c6a5d0");

  await settle(page);
  await page.screenshot({ path: "test-results/behaviour-test.png", fullPage: true });
});

test("cached scenario source uses the readable active primary name", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({ activeKnowledgeDelayMs: 200 });
  await install(page, world);
  await page.addInitScript(() => {
    sessionStorage.setItem("bh-scenarios:42", JSON.stringify({
      loading: false,
      matched: true,
      source_document: "bot_42_a88bed7fee6f4c2f8a1f055318c6a5d0_Services-2026.pdf",
      note: "",
      items: [
        { key: "fact", name: "Cleaning price", goal: "Quote RM120", message: "how much is a cleaning?" }
      ]
    }));
  });
  await page.goto(`/behaviour.html?bot_id=${BOT_ID}&tab=test`);
  await expect(page.locator("#bh-bot-name")).toHaveText("Northweave Clinic");
  await page.waitForTimeout(50);
  await expect(page.locator("#bh-scenarios-note")).not.toContainText("bot_42_a88bed7fee6f4c2f8a1f055318c6a5d0");

  await expect(page.locator("#bh-scenarios-note")).toContainText("Matched to Services-2026.pdf");
  await expect(page.locator("#bh-scenarios-note")).not.toContainText("bot_42_a88bed7fee6f4c2f8a1f055318c6a5d0");
  expect(world.scenarioCalls).toBe(0);
});

test("a scenario loads a real first message and the bot answers", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world, "test");

  await page.locator(".bh-scenario").first().click();
  await expect(page.locator("#bh-input")).toHaveValue("hi, can i book a scale and polish this week?");

  await page.locator("#bh-send").click();
  await expect(page.locator(".bh-bubble-bot").last()).toHaveText("Of course, I can help with that.");

  // The bug this pins: both testbot calls used `bot_id`, so the backend
  // answered "chatbot_id is required" and that string was rendered as the
  // bot's reply. Every testbot call must carry the name the route reads.
  const testbotCalls = world.calls.filter(c => c.includes("/api/testbot/"));
  expect(testbotCalls.length).toBeGreaterThan(0);
  for (const call of testbotCalls) expect(call).toContain(`chatbot_id=${BOT_ID}`);
});

const GREETING_WITH_MENU =
  "Hi there. Welcome to Northweave Clinic. How can we help you today?\n\n" +
  "[BUTTONS: Book appointment | Services & pricing | Talk to our team]";

test("the welcome menu saved on Message experience becomes tappable buttons", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({ reply: GREETING_WITH_MENU });
  await open(page, world, "test");

  await page.locator("#bh-input").fill("hello");
  await page.locator("#bh-send").click();

  // The tag is what every channel strips before sending; printing it raw is
  // the one thing a customer would never see.
  await expect(page.locator(".bh-bubble-bot").last())
    .toHaveText("Hi there. Welcome to Northweave Clinic. How can we help you today?");
  await expect(page.locator(".bh-bubble-bot").last()).not.toContainText("[BUTTONS");

  await expect(page.locator("#bh-chat .bh-reply")).toHaveCount(3);
  await expect(page.locator("#bh-chat .bh-reply").first()).toHaveText("Book appointment");

  await settle(page);
  await page.screenshot({ path: "test-results/behaviour-test-buttons.png", fullPage: true });
});

test("tapping a reply button sends that label, as a real channel would", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({ reply: GREETING_WITH_MENU });
  await open(page, world, "test");

  await page.locator("#bh-input").fill("hello");
  await page.locator("#bh-send").click();
  await expect(page.locator("#bh-chat .bh-reply")).toHaveCount(3);

  await page.locator("#bh-chat .bh-reply").nth(1).click();

  // Telegram sends the label as callback_data, WhatsApp as button_reply.title.
  await expect(page.locator(".bh-bubble-user").last()).toHaveText("Services & pricing");
  await expect.poll(() => world.sent).toEqual(["hello", "Services & pricing"]);
});

test("with quick replies off the buttons are not sent, and the lab says so", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({ reply: GREETING_WITH_MENU });
  world.bot.telegram_buttons_enabled = false;
  await open(page, world, "test");

  await page.locator("#bh-input").fill("hello");
  await page.locator("#bh-send").click();

  // Same reply, same stripped tag — the only difference is that the customer
  // has to type. Showing buttons here would credit a setting that is off.
  await expect(page.locator(".bh-bubble-bot").last()).not.toContainText("[BUTTONS");
  await expect(page.locator("#bh-chat .bh-reply")).toHaveCount(0);
  await expect(page.locator("#bh-chat .bh-reply-note")).toContainText("Quick replies are off");
});

test("a reply with no buttons stays a plain message", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld(), "test");

  await page.locator("#bh-input").fill("how much is a cleaning?");
  await page.locator("#bh-send").click();

  await expect(page.locator(".bh-bubble-bot").last()).toHaveText("Of course, I can help with that.");
  await expect(page.locator("#bh-chat .bh-reply")).toHaveCount(0);
  await expect(page.locator("#bh-chat .bh-reply-note")).toHaveCount(0);
});

test("scenarios come from the business's own documents, not a fixed list", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  // A shop that ships orders and a clinic that books appointments share no
  // useful test question, which is the whole reason these are derived.
  const world = makeWorld({
    context: { bot_name: "Kirana Supply", active_profile: "Shop Support", active_pdf: "catalogue.pdf" },
    activeKnowledge: { file_name: "catalogue.pdf", display_name: "catalogue.pdf" },
    scenarios: {
      matched: true, source_document: "catalogue.pdf", note: "",
      scenarios: [
        { key: "common", name: "Where is my order", goal: "Look up the order",
          message: "hi, where is my order 8813?" },
        { key: "handoff", name: "Ask for a human", goal: "Hand over to your team",
          message: "I would rather speak to a real person please." }
      ]
    }
  });
  await open(page, world, "test");

  await expect(page.locator("#bh-scenarios-note")).toContainText("Matched to catalogue.pdf");
  await expect(page.locator(".bh-scenario-name").first()).toHaveText("Where is my order");
  await page.locator(".bh-scenario").first().click();
  await expect(page.locator("#bh-input")).toHaveValue("hi, where is my order 8813?");
});

test("with nothing to match against, the questions are generic and say so", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({
    scenarios: {
      matched: false, source_document: "", scenarios: [
        { key: "common", name: "What do you offer?", goal: "Describe the business",
          message: "Hi, what do you offer?" },
        { key: "handoff", name: "Ask for a human", goal: "Hand over to your team",
          message: "I would rather speak to a real person please." }
      ],
      note: "These are general questions. Activate a document in Training data to get questions matched to your business."
    }
  });
  await open(page, world, "test");

  // Generic questions are still worth having. Pretending they are matched is
  // what would mislead, so the note names the gap and the next step.
  await expect(page.locator("#bh-scenarios-note")).toContainText("Activate a document in Training data");
  await expect(page.locator(".bh-scenario")).toHaveCount(2);
});

test("asking for a human is always offered, even when nothing could be derived", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld(), "test");

  // The escape hatch is the one test that means the same for every business,
  // so it is never derived and never lost to a failed generation.
  await expect(page.locator(".bh-scenario-name").last()).toHaveText("Ask for a human");
});

test("scenarios are built once per bot, and rebuilt only on Refresh", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world, "test");

  await expect(page.locator(".bh-scenario").first()).toBeVisible();
  expect(world.scenarioCalls).toBe(1);

  // Each rebuild costs AI credit, so leaving and returning must not pay again.
  await page.locator("#bh-tab-model").click();
  await page.locator("#bh-tab-test").click();
  await expect(page.locator(".bh-scenario").first()).toBeVisible();
  expect(world.scenarioCalls).toBe(1);

  await page.locator("#bh-scenarios-refresh").click();
  await expect.poll(() => world.scenarioCalls).toBe(2);
});

test("a setup lookup that fails does not claim the bot is undeployed", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await install(page, world);
  // One broken endpoint, everything else healthy: the honest report is "could
  // not check", not "nothing deployed" — which would send the operator off to
  // redeploy a bot that was fine.
  await page.route("**/api/testbot/context**", route => route.fulfill({
    status: 500, contentType: "application/json",
    body: JSON.stringify({ status: "error", message: "boom" })
  }));
  await page.goto(`/behaviour.html?bot_id=${BOT_ID}&tab=test`);

  await expect(page.locator("#bh-test-warning")).toContainText("Could not read what this bot has deployed");
  await expect(page.locator("#bh-test-warning")).not.toContainText("Nothing is deployed");
});

/* ── Shell ─────────────────────────────────────────────────────────── */

test("a bot you may not open explains itself instead of bouncing you", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await install(page, makeWorld());
  await page.route("**/api/bots/**", route => route.fulfill({
    status: 403, contentType: "application/json",
    body: JSON.stringify({ status: "error", message: "forbidden" })
  }));
  await page.goto(`/behaviour.html?bot_id=${BOT_ID}&tab=model`);

  // A stale link used to land on bots.html with no explanation. The tabs are
  // hidden rather than disabled: there is nothing behind them to read.
  await expect(page.locator("#bh-banner")).toContainText("Chatbot not found or you do not have access");
  await expect(page).toHaveURL(/behaviour\.html/);
  await expect(page.locator("#bh-tabs")).toBeHidden();
  await expect(page.locator("#bh-footer")).toBeHidden();
});

test("the old page URLs still land in the right tab", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await install(page, makeWorld());

  await page.goto(`/message_style.html?bot_id=${BOT_ID}`);
  await expect(page).toHaveURL(/behaviour\.html\?tab=message/);
  await expect(page.locator("#bh-panel-message")).toBeVisible();
});

test("mobile stacks without overflow and keeps save reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, makeWorld());

  await expect(page.locator("#bh-save")).toBeVisible();

  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  await settle(page);
  await page.screenshot({ path: "test-results/behaviour-mobile.png" });
});

test("Current setup lists what the model tab is actually set to", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld());

  const rows = page.locator("#bh-current .bh-ready-row");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0)).toContainText("Balanced");
  await expect(rows.nth(1)).toContainText("OpenAI");
  await expect(rows.nth(2)).toContainText("GPT-4o mini");
  await expect(rows.nth(3)).toContainText("3 buttons");

  // Nothing in the *open* tab may sit at opacity 0: that would be invisible
  // content a screenshot hides rather than reports. Reveals inside the two
  // closed panels are expected to wait — they animate when their tab opens.
  await settle(page);
  const unrevealed = await page.evaluate(() =>
    [...document.querySelectorAll("section[role='tabpanel']:not([hidden]) .cr-reveal, header.cr-reveal")]
      .filter(el => getComputedStyle(el).opacity !== "1")
      .map(el => el.className));
  expect(unrevealed).toEqual([]);
});
