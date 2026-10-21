const { expect, test } = require("@playwright/test");
const fs = require("fs");
const path = require("path");
const { startServer } = require("./platform-admin-static-server");

let staticServer;

test.beforeAll(async () => {
  staticServer = await startServer();
});

test.afterAll(async () => {
  if (!staticServer) return;
  await new Promise(resolve => staticServer.close(resolve));
});

function json(status, body = {}) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

const FEATURE_KEYS = [
  "single_website_scraping",
  "batch_website_scraping",
  "ai_generated_reports",
  "ai_assisted_menu_generation",
  "crm_lead_assignment",
  "unified_knowledge_ingestion",
  "ai_derived_persona",
  "conversation_memory"
];

const PUBLIC_PRICING_FEATURES = [
  "ai_derived_persona",
  "conversation_memory",
  "unified_knowledge_ingestion",
  "ai_assisted_menu_generation",
  "ai_generated_reports",
  "crm_lead_assignment",
  "single_website_scraping",
  "batch_website_scraping"
];

const PLAN_FLAGS = {
  free: {
    single_website_scraping: false,
    batch_website_scraping: false,
    ai_generated_reports: false,
    ai_assisted_menu_generation: false,
    crm_lead_assignment: false,
    unified_knowledge_ingestion: false,
    ai_derived_persona: false,
    conversation_memory: false
  },
  essential: {
    single_website_scraping: false,
    batch_website_scraping: false,
    ai_generated_reports: false,
    ai_assisted_menu_generation: false,
    crm_lead_assignment: false,
    unified_knowledge_ingestion: false,
    ai_derived_persona: true,
    conversation_memory: true
  },
  advanced: {
    single_website_scraping: true,
    batch_website_scraping: false,
    ai_generated_reports: false,
    ai_assisted_menu_generation: true,
    crm_lead_assignment: true,
    unified_knowledge_ingestion: true,
    ai_derived_persona: true,
    conversation_memory: true
  },
  pro: {
    single_website_scraping: true,
    batch_website_scraping: true,
    ai_generated_reports: true,
    ai_assisted_menu_generation: true,
    crm_lead_assignment: true,
    unified_knowledge_ingestion: true,
    ai_derived_persona: true,
    conversation_memory: true
  }
};

const PLANS = [
  {
    id: 1, code: "free", name: "Free", description: "Try the platform.",
    price: "0", currency: "MYR", billing_interval: "monthly",
    chatbot_limit: 1, team_member_limit: 1, channel_limit: 1,
    knowledge_file_limit: 3, knowledge_storage_limit_bytes: 52428800,
    model_access_tier: "economy", included_ai_credit_micro_myr: 1000000,
    feature_flags: PLAN_FLAGS.free
  },
  {
    id: 2, code: "essential", name: "Essential", description: "Essential plan.",
    price: "133.50", currency: "MYR", billing_interval: "monthly",
    chatbot_limit: 1, team_member_limit: 1, channel_limit: 1,
    knowledge_file_limit: 5, knowledge_storage_limit_bytes: 52428800,
    model_access_tier: "economy", included_ai_credit_micro_myr: 5000000,
    feature_flags: PLAN_FLAGS.essential
  },
  {
    id: 3, code: "advanced", name: "Advanced", description: "Advanced plan.",
    price: "283.50", currency: "MYR", billing_interval: "monthly",
    chatbot_limit: 2, team_member_limit: 3, channel_limit: 2,
    knowledge_file_limit: 25, knowledge_storage_limit_bytes: 262144000,
    model_access_tier: "standard", included_ai_credit_micro_myr: 20000000,
    feature_flags: PLAN_FLAGS.advanced
  },
  {
    id: 4, code: "pro", name: "Pro", description: "Premium plan.",
    price: "561.00", currency: "MYR", billing_interval: "monthly",
    chatbot_limit: 3, team_member_limit: 5, channel_limit: 4,
    knowledge_file_limit: 75, knowledge_storage_limit_bytes: 1073741824,
    model_access_tier: "premium", included_ai_credit_micro_myr: 60000000,
    feature_flags: PLAN_FLAGS.pro
  }
];

const CATALOGUE = {
  deepseek: {
    label: "DeepSeek",
    models: [{ value: "deepseek-chat", label: "DeepSeek Chat", tier: "economy", access: "trial_only" }]
  },
  gemini: {
    label: "Gemini",
    models: [{ value: "gemini-2.0-flash", label: "Gemini 2.0 Flash", tier: "economy", access: "paid" }]
  },
  openai: {
    label: "OpenAI",
    models: [
      { value: "gpt-4o-mini", label: "GPT-4o mini", tier: "standard", access: "paid" },
      { value: "gpt-4o", label: "GPT-4o", tier: "premium", access: "paid" }
    ]
  }
};

function plan(code, overrides = {}) {
  const found = PLANS.find(p => p.code === code);
  return JSON.parse(JSON.stringify(Object.assign({}, found, overrides)));
}

function subscription(code, overrides = {}) {
  const selected = plan(code);
  return Object.assign({
    id: 100 + selected.id,
    company_id: 42,
    plan_id: selected.id,
    status: code === "free" ? "trialing" : "active",
    current_period_start: "2026-08-01T00:00:00Z",
    current_period_end: "2026-09-01T00:00:00Z",
    trial_ends_at: code === "free" ? "2026-09-01T00:00:00Z" : null,
    cancellation_effective_at: null,
    pending_plan: null,
    plan_change_effective_at: null,
    can_renew: false,
    renewal_required: false,
    plan: selected
  }, overrides);
}

function usageFor(code, mode = "below") {
  const selected = plan(code);
  const at = mode === "at";
  return {
    period: { start: "2026-08-01T00:00:00Z", end: "2026-09-01T00:00:00Z", end_source: "stored" },
    plan: { id: selected.id, name: selected.name, code: selected.code, billing_interval: "monthly" },
    usage: {
      chatbots: { used: at ? selected.chatbot_limit : Math.max(0, selected.chatbot_limit - 1), limit: selected.chatbot_limit },
      team_members: { used: at ? selected.team_member_limit : Math.max(1, selected.team_member_limit - 1), limit: selected.team_member_limit, pending_invitations: 0 },
      channels: { used: at ? selected.channel_limit : Math.max(0, selected.channel_limit - 1), limit: selected.channel_limit },
      knowledge_files: { used: Math.min(2, selected.knowledge_file_limit), limit: selected.knowledge_file_limit },
      knowledge_storage_bytes: { used: 10485760, limit: selected.knowledge_storage_limit_bytes },
      ai_tokens: { input_tokens: 100, output_tokens: 50, total_tokens: 150 }
    }
  };
}

function installSession(page) {
  return page.addInitScript(() => {
    sessionStorage.setItem("token", "fake-tenant-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify({
      id: 7, company_id: 42, email: "owner@example.test", full_name: "Owner", role: "owner"
    }));
  });
}

async function installMocks(page, world) {
  await installSession(page);
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("https://unpkg.com/lucide**", route => route.fulfill({
    status: 200,
    contentType: "application/javascript",
    body: "window.lucide={createIcons:function(){}};"
  }));

  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    world.calls.push({ method, pathname: url.pathname, search: url.search, body: request.postData() || "" });

    if (url.pathname === "/api/billing/plans") {
      return route.fulfill(json(200, { status: "success", data: world.plans || PLANS }));
    }
    if (url.pathname === "/api/billing/subscription") {
      return route.fulfill(json(200, { status: "success", data: world.subscription }));
    }
    if (url.pathname === "/api/billing/usage") {
      return route.fulfill(json(200, { status: "success", data: world.usage || usageFor(world.code) }));
    }
    if (url.pathname === "/api/billing/ai-credit/summary") {
      return route.fulfill(json(200, { status: "success", data: {
        initialised: true,
        subscription_id: world.subscription && world.subscription.id,
        included_balance_micro_myr: (world.subscription && world.subscription.plan.included_ai_credit_micro_myr) || 0,
        topup_balance_micro_myr: 0,
        total_balance_micro_myr: (world.subscription && world.subscription.plan.included_ai_credit_micro_myr) || 0,
        currency: "MYR",
        unit: "micro_myr"
      } }));
    }
    if (url.pathname === "/api/platform-admin/me") {
      return route.fulfill(json(403, { status: "error" }));
    }
    if (url.pathname === "/api/workspace") {
      const team = (world.usage || usageFor(world.code)).usage.team_members;
      return route.fulfill(json(200, { status: "success", data: {
        company: { name: "Company A", contact_email: "", contact_phone: "" },
        current_user_role: "owner",
        active_member_count: team.used,
        pending_invitation_count: team.pending_invitations || 0,
        plan_member_limit: team.limit,
        remaining_seats: Math.max(0, team.limit - team.used - (team.pending_invitations || 0)),
        can_edit_company: true,
        can_manage_team: true
      } }));
    }
    if (url.pathname === "/api/users") {
      const count = (world.usage || usageFor(world.code)).usage.team_members.used;
      return route.fulfill(json(200, { status: "success", data: Array.from({ length: count }, (_, i) => ({
        id: i + 1,
        email: `member${i + 1}@example.test`,
        full_name: `Member ${i + 1}`,
        role: i === 0 ? "owner" : "agent"
      })) }));
    }
    if (url.pathname === "/api/invites") {
      return route.fulfill(json(200, { status: "success", data: [] }));
    }
    if (url.pathname === "/api/bots" || url.pathname === "/api/bots/archived") {
      const count = (world.usage || usageFor(world.code)).usage.chatbots.used;
      return route.fulfill(json(200, { status: "success", data: Array.from({ length: count }, (_, i) => ({
        id: String(40 + i),
        bot_name: `Bot ${i + 1}`,
        description: "Mock bot",
        active: true
      })) }));
    }
    if (url.pathname === "/api/bots/42") {
      return route.fulfill(json(200, { status: "success", data: {
        id: 42,
        bot_name: "Northweave Clinic",
        ai_provider: "openai",
        model_name: "gpt-4o",
        temperature: 0.7,
        welcome_menu_labels: ["Book appointment", "Services", "Human help"]
      } }));
    }
    if (url.pathname === "/api/bots/42/generate-welcome-menu") {
      world.menuCalls += 1;
      const allowed = !world.forceMenuDenial
        && world.subscription
        && (world.subscription.status === "active" || world.subscription.status === "trialing")
        && world.subscription.plan
        && world.subscription.plan.feature_flags
        && world.subscription.plan.feature_flags.ai_assisted_menu_generation === true;
      return route.fulfill(allowed
        ? json(200, { status: "success", data: ["Book appointment", "Services", "Human help"] })
        : json(403, { status: "error", code: "feature_not_available", message: "AI-assisted menu generation is not available on this plan." }));
    }
    if (url.pathname === "/api/ai-models") {
      return route.fulfill(json(200, { status: "success", data: CATALOGUE, read_only: false, access_allowed: true }));
    }
    if (url.pathname === "/api/knowledge/active") {
      return route.fulfill(json(200, { status: "success", data: { file_name: "primary.pdf", display_name: "Primary.pdf" } }));
    }
    if (url.pathname === "/api/knowledge/files") {
      return route.fulfill(json(200, { status: "success", data: [{
        id: 1,
        file_name: "primary.pdf",
        original_file_name: "Primary.pdf",
        display_name: "Primary.pdf",
        file_type: "pdf",
        file_size: 10000,
        is_active: true,
        is_enabled: true,
        retrieval_role: "primary",
        processing_status: "ready"
      }] }));
    }
    if (url.pathname === "/api/knowledge/scrape-analyze") {
      const allowed = world.subscription
        && world.subscription.plan
        && world.subscription.plan.feature_flags
        && world.subscription.plan.feature_flags.single_website_scraping === true;
      return route.fulfill(allowed
        ? json(200, { status: "success", data: { links: ["https://example.test/help"] } })
        : json(403, { status: "error", code: "feature_not_available", message: "Website import is not available on this plan." }));
    }
    if (url.pathname === "/api/bots/42/widget") {
      return route.fulfill(json(200, { status: "success", data: {
        widget: {
          public_key: "wgt_plan",
          display_name: "Northweave Clinic",
          is_enabled: true,
          theme_color: "#2563eb",
          launcher_label: "Chat",
          welcome_message: "Hi",
          lead_capture_enabled: false
        },
        embed: {
          share_url: "https://bot.example.test/chat/wgt_plan",
          script_url: "https://bot.example.test/widget.js",
          iframe_url: "https://bot.example.test/widget/wgt_plan",
          script_snippet: "<script></script>",
          iframe_snippet: "<iframe></iframe>"
        }
      } }));
    }
    if (url.pathname === "/api/whatsapp/embedded-signup/config") {
      return route.fulfill(json(500, { status: "error", message: "WhatsApp Embedded Signup is not configured." }));
    }
    if (["/api/telegram/channels", "/api/wasender/channels", "/api/whatsapp/channels", "/api/whatchimp/channels"].includes(url.pathname)) {
      return route.fulfill(json(200, { status: "success", data: [] }));
    }
    if (url.pathname === "/api/knowledge/graph") {
      return route.fulfill(json(200, { status: "success", data: { nodes: [], edges: [] } }));
    }
    if (url.pathname === "/api/knowledge/refinement/questions") {
      return route.fulfill(json(200, { status: "success", data: { questions: [] } }));
    }
    return route.fulfill(json(418, { status: "error", message: `Unhandled mocked endpoint: ${url.pathname}` }));
  });
}

function makeWorld(code, overrides = {}) {
  const sub = overrides.subscription === undefined
    ? subscription(code, overrides.subscriptionOverrides || {})
    : overrides.subscription;
  return Object.assign({
    code,
    subscription: sub,
    usage: usageFor(code, overrides.usageMode || "below"),
    plans: PLANS,
    calls: [],
    menuCalls: 0,
    forceMenuDenial: false
  }, overrides);
}

function linkdocsPlanFeatureSource() {
  const source = fs.readFileSync(path.join(__dirname, "..", "..", "frontend", "new_linkdocs.html"), "utf8");
  const match = source.match(/const hasPlanFeature = \(flags, featureKey\) => \{[\s\S]*?\n            \};/);
  if (!match) {
    throw new Error("Could not find new_linkdocs.html hasPlanFeature helper");
  }
  return match[0].replace("const hasPlanFeature =", "window.__hasPlanFeature =");
}

async function openPricing(page, world) {
  await installMocks(page, world);
  await page.goto("/pricing.html");
  await expect(page.locator(".plan-card")).toHaveCount(4);
}

async function openBehaviour(page, world, tab = "model") {
  await installMocks(page, world);
  await page.goto(`/behaviour.html?bot_id=42&tab=${tab}`);
  await expect(page.locator("#bh-bot-name")).toHaveText("Northweave Clinic");
}

async function openKnowledge(page, world) {
  await installMocks(page, world);
  await page.goto("/new_linkdocs.html?bot_id=42");
  await expect(page.getByRole("button", { name: "Add source" }).first()).toBeVisible();
}

test.describe("plan fixture contract", () => {
  for (const code of ["free", "essential", "advanced", "pro"]) {
    test(`${code} exposes the current seeded limits and feature flags on pricing`, async ({ page }) => {
      const world = makeWorld(code);
      await openPricing(page, world);

      const selected = plan(code);
      const card = page.locator(`.plan-card[data-plan-code="${code}"]`);
      await expect(card.locator('[data-feature-key="chatbot_limit"]')).toContainText(String(selected.chatbot_limit));
      await expect(card.locator('[data-feature-key="team_member_limit"]')).toContainText(String(selected.team_member_limit));
      await expect(card.locator('[data-feature-key="channel_limit"]')).toContainText(String(selected.channel_limit));
      await expect(card.locator('[data-feature-key="knowledge_file_limit"]')).toContainText(String(selected.knowledge_file_limit));
      await expect(card.locator('[data-feature-key="included_ai_credit_micro_myr"]')).toContainText(`RM ${selected.included_ai_credit_micro_myr / 1000000}`);

      for (const feature of PUBLIC_PRICING_FEATURES) {
        await expect(card.locator(`[data-feature-key="${feature}"]`)).toHaveAttribute(
          "data-enabled",
          selected.feature_flags[feature] === true ? "true" : "false"
        );
      }
    });
  }
});

test.describe("visible limit controls", () => {
  test("workspace sidebar uses the bot icon and keeps GEO beside My bots", async ({ page }) => {
    const world = makeWorld("pro");
    await installMocks(page, world);
    await page.goto("/bots.html");
    await expect(page.locator('chatbot-sidebar .nav-list a[href="bots.html"] i'))
      .toHaveAttribute("data-lucide", "bot");
    await expect(page.locator('chatbot-sidebar .nav-list a[href="geo-analysis.html"]')).toHaveCount(1);
    await expect(page.locator('chatbot-sidebar .sidebar-bottom-section a[href="geo-analysis.html"]')).toHaveCount(0);
  });

  test("bot sidebar keeps the back arrow and moves GEO into the workspace footer", async ({ page }) => {
    const world = makeWorld("pro");
    await installMocks(page, world);
    await page.goto("/integration.html?bot_id=42");
    await expect(page.locator('chatbot-sidebar .nav-list a[href="bots.html"] i'))
      .toHaveAttribute("data-lucide", "arrow-left");
    await expect(page.locator('chatbot-sidebar .nav-list a[href="geo-analysis.html"]')).toHaveCount(0);
    await expect(page.locator('chatbot-sidebar .sidebar-bottom-section a[href="geo-analysis.html"]')).toHaveCount(1);
  });

  test("chatbot creation is enabled below the plan limit and blocked at the limit", async ({ page }) => {
    const below = makeWorld("advanced");
    await installMocks(page, below);
    await page.goto("/bots.html");
    await expect(page.locator('[data-create-bot-trigger="true"]').first()).toBeEnabled();
    await expect(page.locator("#plan-usage-count")).toHaveText("1/2");

    const atLimit = makeWorld("advanced", { usageMode: "at" });
    await page.unroute("**/api/**");
    await installMocks(page, atLimit);
    await page.goto("/bots.html");
    await expect(page.locator('[data-create-bot-trigger="true"]').first()).toBeDisabled();
    await expect(page.locator("#chatbot-limit-helper")).toContainText("Chatbot limit reached");
  });

  test("team invitation follows the current plan seat limit", async ({ page }) => {
    const world = makeWorld("essential", { usageMode: "at" });
    await installMocks(page, world);
    await page.goto("/team.html");
    await expect(page.locator("#tm-invite")).toBeDisabled();
    await expect(page.locator(".team-seats-used")).toHaveText("1");
    await expect(page.locator(".team-seats-limit")).toHaveText("of 1 seats");
    await expect(page.locator("#tm-seats")).toContainText("Team limit reached");
    await expect(page.locator("#tm-upgrade")).toBeVisible();
  });

  test("channel publishing marks every connector full when channel slots are exhausted", async ({ page }) => {
    const world = makeWorld("pro", { usageMode: "at" });
    await installMocks(page, world);
    await page.goto("/integration.html?bot_id=42");
    await expect(page.locator('[data-option="telegram"]')).toContainText("Plan full");
  });

  test("publish screen upgrades a stale Pro two-channel response to the four-channel contract", async ({ page }) => {
    const staleUsage = usageFor("pro");
    staleUsage.usage.channels = { used: 2, limit: 2 };
    const world = makeWorld("pro", { usage: staleUsage });
    await installMocks(page, world);
    await page.goto("/integration.html?bot_id=42");
    await expect(page.locator("#pub-slots")).toHaveText("2 of 4");
    await expect(page.locator("#pub-slot-note")).toHaveText("2 of 4 paid slots used across all your bots");
    await expect(page.locator('[data-option="telegram"]')).not.toContainText("Plan full");
  });
});

test.describe("AI model and AI menu entitlements", () => {
  test("model selector filters each plan to its allowed tier", async ({ page }) => {
    const cases = [
      ["free", ["DeepSeek Chat"], ["Gemini 2.0 Flash", "GPT-4o mini", "GPT-4o"]],
      ["essential", ["Gemini 2.0 Flash"], ["DeepSeek Chat", "GPT-4o mini", "GPT-4o"]],
      ["advanced", ["Gemini 2.0 Flash", "GPT-4o mini"], ["DeepSeek Chat", "GPT-4o"]],
      ["pro", ["Gemini 2.0 Flash", "GPT-4o mini", "GPT-4o"], ["DeepSeek Chat"]]
    ];

    for (const [code, included, excluded] of cases) {
      const world = makeWorld(code);
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await openBehaviour(page, world, "model");
      const optionLabels = await page.evaluate(() => {
        // A single model list now holds every allowed model; there is no provider picker.
        return Array.from(document.querySelector("#bh-model").options).map(model => model.textContent);
      });
      for (const label of included) {
        expect(optionLabels).toContain(label);
      }
      for (const label of excluded) {
        expect(optionLabels).not.toContain(label);
      }
    }
  });

  for (const code of ["free", "essential", "advanced", "pro"]) {
    test(`${code} shows AI menu generation according to ai_assisted_menu_generation`, async ({ page }) => {
      const world = makeWorld(code);
      await openBehaviour(page, world, "message");

      const button = page.locator("#bh-menu-generate");
      if (PLAN_FLAGS[code].ai_assisted_menu_generation) {
        await expect(button).toBeEnabled();
        await button.click();
        await expect(page.locator(".bh-menu-row input").first()).toHaveValue("Book appointment");
        expect(world.menuCalls).toBe(1);
      } else {
        await expect(button).toBeDisabled();
        expect(world.menuCalls).toBe(0);
      }
    });
  }
});

test.describe("website knowledge import entitlement", () => {
  test("new_linkdocs website-import feature predicate fails closed", async ({ page }) => {
    await page.addScriptTag({ content: linkdocsPlanFeatureSource() });
    const cases = [
      [{ single_website_scraping: true }, true, "exact true allows website import"],
      [{ single_website_scraping: false }, false, "exact false denies website import"],
      [{ batch_website_scraping: true }, false, "missing single_website_scraping denies website import"],
      [null, false, "null flags deny website import"],
      ["true", false, "non-object flags deny website import"],
      [{ single_website_scraping: "true" }, false, "string true denies website import"],
      [{ single_website_scraping: 1 }, false, "integer one denies website import"],
      [PLAN_FLAGS.advanced, true, "Advanced still allows website import"],
      [PLAN_FLAGS.pro, true, "Pro still allows website import"],
      [Object.assign({}, PLAN_FLAGS.essential, { single_website_scraping: "true" }), false, "lower plan malformed data does not gain website import"]
    ];

    for (const [flags, expected, label] of cases) {
      const actual = await page.evaluate(
        ([inputFlags]) => window.__hasPlanFeature(inputFlags, "single_website_scraping"),
        [flags]
      );
      expect(actual, label).toBe(expected);
    }
  });

  test("new_linkdocs batch-selection predicate fails closed", async ({ page }) => {
    await page.addScriptTag({ content: linkdocsPlanFeatureSource() });
    const cases = [
      [{ batch_website_scraping: true }, true],
      [{ batch_website_scraping: false }, false],
      [{ single_website_scraping: true }, false],
      [null, false],
      ["true", false],
      [{ batch_website_scraping: "true" }, false],
      [{ batch_website_scraping: 1 }, false],
      [PLAN_FLAGS.advanced, false],
      [PLAN_FLAGS.pro, true]
    ];

    for (const [flags, expected] of cases) {
      await expect.poll(async () => page.evaluate(
        ([inputFlags]) => window.__hasPlanFeature(inputFlags, "batch_website_scraping"),
        [flags]
      )).toBe(expected);
    }
  });
});

test.describe("plan transitions, edge cases, and tenant context", () => {
  test("scheduled downgrade keeps current pro privileges visible until the effective date", async ({ page }) => {
    const world = makeWorld("pro", {
      subscriptionOverrides: {
        pending_plan: { id: 2, code: "essential", name: "Essential" },
        plan_change_effective_at: "2026-09-01T00:00:00Z"
      }
    });
    await openPricing(page, world);
    await expect(page.locator("#pri-current")).toContainText("Changes to Essential");
    await page.goto("/behaviour.html?bot_id=42&tab=message");
    await expect(page.locator("#bh-menu-generate")).toBeEnabled();
  });

  test("expired paid subscription hides paid-only models and does not enable restricted menu generation", async ({ page }) => {
    const world = makeWorld("pro", { subscriptionOverrides: { status: "expired" } });
    await openBehaviour(page, world, "model");
    await expect(page.locator("#bh-model")).toBeDisabled();
    await page.goto("/behaviour.html?bot_id=42&tab=message");
    await expect(page.locator("#bh-menu-generate")).toBeDisabled();
    expect(world.menuCalls).toBe(0);
  });

  test("missing subscription data does not enable restricted menu generation", async ({ page }) => {
    const world = makeWorld("pro", { subscription: null });
    await openBehaviour(page, world, "message");
    await expect(page.locator("#bh-menu-generate")).toBeDisabled();
    expect(world.menuCalls).toBe(0);
  });

  test("backend-denied AI menu generation remains handled as defense in depth", async ({ page }) => {
    const world = makeWorld("pro", { forceMenuDenial: true });
    await openBehaviour(page, world, "message");
    await expect(page.locator("#bh-menu-generate")).toBeEnabled();
    await page.locator("#bh-menu-generate").click();
    await expect(page.locator("#bh-banner")).toContainText("AI-assisted menu generation is not available");
    expect(world.menuCalls).toBe(1);
  });

  test("malformed feature flags do not render public pricing features as included", async ({ page }) => {
    const world = makeWorld("pro");
    world.plans = PLANS.map(item => item.code === "pro" ? plan("pro", { feature_flags: "yes please" }) : item);
    await openPricing(page, world);
    const card = page.locator('.plan-card[data-plan-code="pro"]');
    for (const feature of PUBLIC_PRICING_FEATURES) {
      await expect(card.locator(`[data-feature-key="${feature}"]`)).toHaveAttribute("data-enabled", "false");
    }
  });

  test("query-string company_id cannot escalate the mocked tenant plan", async ({ page }) => {
    const world = makeWorld("essential");
    await installMocks(page, world);
    await page.goto("/pricing.html?company_id=99");
    await expect(page.locator("#pri-current")).toContainText("Essential");
    await expect(page.locator('.plan-card[data-plan-code="pro"] [data-feature-key="batch_website_scraping"]')).toHaveAttribute("data-enabled", "true");
    await expect(page.locator('.plan-card[data-plan-code="essential"] [data-feature-key="batch_website_scraping"]')).toHaveAttribute("data-enabled", "false");
    expect(world.calls.filter(call => call.search.includes("company_id=99"))).toHaveLength(0);
  });
});
