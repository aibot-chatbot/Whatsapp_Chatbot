const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

let staticServer;

const plans = [
  {
    code: "free",
    name: "Free",
    description: "Basic plan for trying the chatbot platform.",
    price: "0",
    currency: "MYR",
    billing_interval: "monthly",
    chatbot_limit: 1,
    team_member_limit: 1,
    channel_limit: 1,
    knowledge_file_limit: 3,
    knowledge_storage_limit_bytes: 52428800,
    model_access_tier: "economy",
    included_ai_credit_micro_myr: 1000000,
    feature_flags: {
      single_website_scraping: false,
      batch_website_scraping: false,
      availability_booking: false,
      knowledge_refinement: false,
      ai_assisted_menu_generation: false,
      ai_generated_reports: false,
      crm_lead_assignment: false
    }
  },
  {
    code: "essential",
    name: "Essential",
    description: "Essential plan - 1 chatbot, 1 channel, 5 knowledge files, 50 MB storage",
    price: "39",
    currency: "MYR",
    billing_interval: "monthly",
    chatbot_limit: 1,
    team_member_limit: 1,
    channel_limit: 1,
    knowledge_file_limit: 5,
    knowledge_storage_limit_bytes: 52428800,
    model_access_tier: "economy",
    included_ai_credit_micro_myr: 5000000,
    feature_flags: {
      single_website_scraping: false,
      batch_website_scraping: false,
      availability_booking: false,
      knowledge_refinement: false,
      ai_assisted_menu_generation: false,
      ai_generated_reports: false,
      crm_lead_assignment: false
    }
  },
  {
    code: "advanced",
    name: "Advanced",
    description: "Advanced plan - 2 chatbots, 2 channels, 25 knowledge files, 250 MB storage",
    price: "89",
    currency: "MYR",
    billing_interval: "monthly",
    chatbot_limit: 2,
    team_member_limit: 3,
    channel_limit: 2,
    knowledge_file_limit: 25,
    knowledge_storage_limit_bytes: 262144000,
    model_access_tier: "standard",
    included_ai_credit_micro_myr: 20000000,
    feature_flags: {
      single_website_scraping: true,
      batch_website_scraping: false,
      availability_booking: false,
      knowledge_refinement: false,
      ai_assisted_menu_generation: true,
      ai_generated_reports: false,
      crm_lead_assignment: true
    }
  },
  {
    code: "pro",
    name: "Pro",
    description: "Temporary example plan with unlimited resource limits.",
    publicDescription: "Premium plan for teams that need the highest published limits and full feature access.",
    price: "169",
    currency: "MYR",
    billing_interval: "monthly",
    chatbot_limit: 3,
    team_member_limit: 5,
    channel_limit: 2,
    knowledge_file_limit: 75,
    knowledge_storage_limit_bytes: 1073741824,
    model_access_tier: "premium",
    included_ai_credit_micro_myr: 60000000,
    feature_flags: {
      single_website_scraping: true,
      batch_website_scraping: true,
      availability_booking: true,
      knowledge_refinement: true,
      ai_assisted_menu_generation: true,
      ai_generated_reports: true,
      crm_lead_assignment: true
    }
  }
];

// The four other plan flags a card now lists, with the values the live plans carry.
const MORE_PLAN_FLAGS = {
  free: { ai_derived_persona: false, conversation_memory: false, unified_knowledge_ingestion: false, automation_workflows: false },
  essential: { ai_derived_persona: true, conversation_memory: true, unified_knowledge_ingestion: false, automation_workflows: false },
  advanced: { ai_derived_persona: true, conversation_memory: true, unified_knowledge_ingestion: true, automation_workflows: false },
  pro: { ai_derived_persona: true, conversation_memory: true, unified_knowledge_ingestion: true, automation_workflows: true }
};
plans.forEach(plan => Object.assign(plan.feature_flags, MORE_PLAN_FLAGS[plan.code]));

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

async function mockStaticAssets(page) {
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("https://unpkg.com/**", route => route.fulfill({
    status: 200,
    contentType: "application/javascript",
    body: "window.lucide={createIcons:function(){}};"
  }));
}

async function openLanding(page, loggedIn = false) {
  await mockStaticAssets(page);
  if (loggedIn) {
    await page.addInitScript(() => {
      sessionStorage.setItem("token", "fake-tenant-token");
      sessionStorage.setItem("isLoggedIn", "true");
    });
  }
  await page.goto("/landing.html");
  await expect(page.locator("[data-plan-code]")).toHaveCount(4);
}

async function openAuthenticatedPricing(page, planOverrides = plans) {
  await mockStaticAssets(page);
  await page.addInitScript(() => {
    sessionStorage.setItem("token", "fake-tenant-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify({
      id: 1,
      company_id: 42,
      email: "tenant@example.test",
      full_name: "Tenant Operator",
      role: "owner"
    }));
  });
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/billing/plans") {
      return route.fulfill(json(200, { status: "success", data: planOverrides }));
    }
    if (url.pathname === "/api/billing/subscription") {
      return route.fulfill(json(200, {
        status: "success",
        data: { status: "trialing", plan: { code: "free", name: "Free" } }
      }));
    }
    if (url.pathname === "/api/platform-admin/me") {
      return route.fulfill(json(403, { status: "error", code: "platform_admin_access_denied" }));
    }
    return route.fulfill(json(200, { status: "success", data: [] }));
  });
  await page.goto("/pricing.html");
  await expect(page.locator(".plan-card")).toHaveCount(4);
}

async function cardTextByName(page, selector, nameSelector) {
  return page.locator(selector).evaluateAll((cards, childSelector) => {
    const output = {};
    for (const card of cards) {
      const name = card.querySelector(childSelector).textContent.trim();
      output[name] = card.textContent.replace(/\s+/g, " ").trim();
    }
    return output;
  }, nameSelector);
}

async function planCards(page, selector, nameSelector, priceSelector, descriptionSelector) {
  return page.locator(selector).evaluateAll((cards, selectors) => cards.map(card => {
    const features = {};
    card.querySelectorAll("[data-feature-key]").forEach(item => {
      features[item.dataset.featureKey] = {
        enabled: item.dataset.enabled === "true",
        text: item.textContent.replace(/\s+/g, " ").trim()
      };
    });
    return {
      code: card.dataset.planCode || null,
      name: card.querySelector(selectors.nameSelector).textContent.trim(),
      price: card.querySelector(selectors.priceSelector).textContent.replace(/\s+/g, " ").trim(),
      description: card.querySelector(selectors.descriptionSelector).textContent.replace(/\s+/g, " ").trim(),
      features
    };
  }), { nameSelector, priceSelector, descriptionSelector });
}

function expectedFeatureMap(plan) {
  const storage = plan.knowledge_storage_limit_bytes >= 1073741824
    ? `${plan.knowledge_storage_limit_bytes / 1073741824} GB`
    : `${plan.knowledge_storage_limit_bytes / 1048576} MB`;
  const tier = `AI Models: ${{
    free: "1 entry model",
    essential: "GPT-6 Luna, Gemini 3.8 Flash",
    advanced: "GPT-6 Luna, Gemini 3.8 Flash, Claude Haiku 4.5",
    pro: "GPT-6.1 Sol, Claude Sonnet 5.5, Gemini 3.1 Pro"
  }[plan.code]}`;
  return {
    chatbot_limit: { enabled: true, text: `${plan.chatbot_limit} ${plan.chatbot_limit === 1 ? "Chatbot" : "Chatbots"}` },
    team_member_limit: { enabled: true, text: `${plan.team_member_limit} ${plan.team_member_limit === 1 ? "Team Member" : "Team Members"}` },
    channel_limit: { enabled: true, text: `${plan.channel_limit} ${plan.channel_limit === 1 ? "Channel" : "Channels"}` },
    knowledge_file_limit: { enabled: true, text: `${plan.knowledge_file_limit} ${plan.knowledge_file_limit === 1 ? "Knowledge File" : "Knowledge Files"}` },
    knowledge_storage_limit_bytes: { enabled: true, text: `${storage} Storage` },
    model_access_tier: { enabled: true, text: tier },
    included_ai_credit_micro_myr: { enabled: true, text: `AI Credit: RM ${(plan.included_ai_credit_micro_myr / 1000000).toFixed(2)}` },
    chat_bookings: { enabled: true, text: "Chat Booking Requests" },
    ai_derived_persona: { enabled: plan.feature_flags.ai_derived_persona, text: "AI-Derived Bot Persona" },
    conversation_memory: { enabled: plan.feature_flags.conversation_memory, text: "Conversation Memory" },
    crm_lead_assignment: { enabled: plan.feature_flags.crm_lead_assignment, text: "CRM Lead Assignment" },
    single_website_scraping: { enabled: plan.feature_flags.single_website_scraping, text: "Single Website Scraping" },
    ai_assisted_menu_generation: { enabled: plan.feature_flags.ai_assisted_menu_generation, text: "AI-Assisted Menu Generation" },
    unified_knowledge_ingestion: { enabled: plan.feature_flags.unified_knowledge_ingestion, text: "Guided Knowledge Ingestion" },
    ai_generated_reports: { enabled: plan.feature_flags.ai_generated_reports, text: "AI-Generated Reports" },
    automation_workflows: { enabled: plan.feature_flags.automation_workflows, text: "Automation Workflows" },
    knowledge_refinement: { enabled: plan.feature_flags.knowledge_refinement, text: "Knowledge Refinement Q&A" },
    batch_website_scraping: { enabled: plan.feature_flags.batch_website_scraping, text: "Batch Website Scraping" },
    availability_booking: { enabled: plan.feature_flags.availability_booking, text: "Availability Booking" }
  };
}

// The eleven plan flags, last and in this order on every card (the order a plan first gains them).
const approvedFeatureFlagOrder = [
  "ai_derived_persona",
  "conversation_memory",
  "crm_lead_assignment",
  "single_website_scraping",
  "ai_assisted_menu_generation",
  "unified_knowledge_ingestion",
  "ai_generated_reports",
  "automation_workflows",
  "knowledge_refinement",
  "batch_website_scraping",
  "availability_booking"
];

function normalizedPrice(text) {
  if (/free/i.test(text)) return 0;
  const match = text.match(/RM\s+([0-9]+(?:\.[0-9]+)?)/);
  return match ? Number(match[1]) : NaN;
}

function expectedDescription(plan, surface) {
  if (surface === "landing" && plan.publicDescription) return plan.publicDescription;
  return plan.description;
}

function expectPlanCardMatches(card, plan, surface) {
  expect(card.name, `${surface} name for ${plan.code}`).toBe(plan.name);
  expect(normalizedPrice(card.price), `${surface} price for ${plan.code}`).toBe(Number(plan.price));
  expect(card.description, `${surface} description for ${plan.code}`).toBe(expectedDescription(plan, surface));

  const expectedFeatures = expectedFeatureMap(plan);
  expect(Object.keys(card.features).sort(), `${surface} feature keys for ${plan.code}`).toEqual(Object.keys(expectedFeatures).sort());
  for (const [key, expected] of Object.entries(expectedFeatures)) {
    expect(card.features[key].enabled, `${surface} ${plan.code}.${key} enabled state`).toBe(expected.enabled);
    expect(card.features[key].text, `${surface} ${plan.code}.${key} text`).toContain(expected.text);
  }
}

test.describe("public landing pricing", () => {
  test("renders the four publishing plans with no unapproved price", async ({ page }) => {
    // The landing page must advertise exactly the catalogue the billing system
    // charges: subscription_plans, which /api/billing/plans serves elsewhere.
    await openLanding(page);
    const names = await page.locator(".plan h3").allTextContents();
    expect(names).toEqual(["Free", "Essential", "Advanced", "Pro"]);

    await expect(page.locator(".plan[data-plan-code='free'] .price")).toHaveText("RM 0");
    await expect(page.locator(".plan[data-plan-code='essential'] .price")).toHaveText("RM 39");
    await expect(page.locator(".plan[data-plan-code='advanced'] .price")).toHaveText("RM 89");
    await expect(page.locator(".plan[data-plan-code='pro'] .price")).toHaveText("RM 169");
    await expect(page.locator(".plan .tbc")).toHaveCount(0);

    const pageText = await page.locator("body").textContent();
    expect(pageText).not.toContain("RM 29.00");
    expect(pageText).not.toContain("RM 79.00");
    expect(pageText).not.toContain("RM 199.00");
    expect(pageText).not.toMatch(/Email Support|Priority Email Support|24\/7 Dedicated Support|Basic Support/);
    expect(pageText).not.toMatch(/Temporary example|unlimited resource limits/i);
  });

  test("authenticated pricing still matches the published plan catalogue", async ({ page }) => {
    // Landing no longer mirrors this catalogue by design; the authenticated
    // pricing screen remains the source of truth and stays pinned.
    await openAuthenticatedPricing(page);
    const pricingCards = await planCards(page, ".plan-card", ".plan-name", ".plan-price", ".plan-desc");
    expect(pricingCards.map(card => card.name)).toEqual(plans.map(plan => plan.name));

    for (let i = 0; i < plans.length; i += 1) {
      expectPlanCardMatches(pricingCards[i], plans[i], "billing");
    }
  });

  test("authenticated pricing renders HTML-like API plan text safely", async ({ page }) => {
    const maliciousPlans = plans.map(plan => ({ ...plan }));
    maliciousPlans[0] = {
      ...maliciousPlans[0],
      name: "Free <img src=x onerror=\"window.__pricingInjected=true\">",
      description: "Description <script>window.__pricingInjected=true</script>"
    };
    await page.addInitScript(() => {
      window.__pricingInjected = false;
    });

    await openAuthenticatedPricing(page, maliciousPlans);
    await expect(page.locator(".plan-name").first()).toContainText("<img");
    await expect(page.locator(".plan-desc").first()).toContainText("<script>");
    await expect(page.locator(".plan-card img")).toHaveCount(0);
    await expect(page.locator(".plan-card script")).toHaveCount(0);
    await expect(page.locator(".plan-card")).toHaveCount(4);
    await expect(page.locator(".plan-name")).toHaveText([
      maliciousPlans[0].name,
      "Essential",
      "Advanced",
      "Pro"
    ]);
    expect(await page.evaluate(() => window.__pricingInjected)).toBe(false);
  });

  test("authenticated pricing only renders approved customer-facing feature flags", async ({ page }) => {
    const plansWithInternalFlags = plans.map(plan => ({
      ...plan,
      feature_flags: {
        ...plan.feature_flags,
        internal_margin_override: true
      }
    }));
    delete plansWithInternalFlags[1].feature_flags.ai_generated_reports;

    await openAuthenticatedPricing(page, plansWithInternalFlags);
    const essentialFeatures = await page.locator(".plan-card").nth(1).locator("[data-feature-key]").evaluateAll(items => items.map(item => ({
      key: item.dataset.featureKey,
      enabled: item.dataset.enabled,
      text: item.textContent.replace(/\s+/g, " ").trim()
    })));

    expect(essentialFeatures.map(feature => feature.key).slice(-11)).toEqual(approvedFeatureFlagOrder);
    expect(essentialFeatures).toHaveLength(18);
    expect(essentialFeatures.some(feature => feature.key === "internal_margin_override")).toBe(false);
    expect(essentialFeatures.map(feature => feature.text).join(" ")).not.toMatch(/internal margin override/i);

    const approvedRows = essentialFeatures.filter(feature => approvedFeatureFlagOrder.includes(feature.key));
    expect(approvedRows).toHaveLength(11);
    expect(approvedRows.find(feature => feature.key === "ai_generated_reports").enabled).toBe("false");
    for (const key of approvedFeatureFlagOrder) {
      expect(approvedRows.find(feature => feature.key === key), `${key} row`).toBeTruthy();
    }
  });

  test("landing pricing layout stays inside the viewport on desktop and mobile", async ({ page }) => {
    for (const width of [1440, 1280, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: width <= 390 ? 900 : 760 });
      await openLanding(page);
      const cards = await page.locator(".price-card").evaluateAll(items => items.map(card => {
        const rect = card.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width };
      }));
      for (const rect of cards) {
        expect(rect.left).toBeGreaterThanOrEqual(0);
        expect(rect.right).toBeLessThanOrEqual(width);
        expect(rect.width).toBeGreaterThanOrEqual(Math.min(240, width - 40));
      }
    }
  });

  test("landing CTAs switch between logged-out registration and logged-in app destinations", async ({ page }) => {
    await openLanding(page);
    await expect(page.locator("#hero-primary-cta")).toHaveAttribute("href", "register.html");
    await expect(page.locator("[data-plan-cta='advanced']")).toHaveAttribute("href", "register.html");

    const authedPage = await page.context().newPage();
    await openLanding(authedPage, true);
    await expect(authedPage.locator("#hero-primary-cta")).toHaveAttribute("href", "bots.html");
    await expect(authedPage.locator("#bottom-cta-btn")).toHaveAttribute("href", "bots.html");
    await expect(authedPage.locator("[data-plan-cta='advanced']")).toHaveAttribute("href", "pricing.html");
  });
});
