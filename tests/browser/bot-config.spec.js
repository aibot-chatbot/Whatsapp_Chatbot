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

const PROFILES = [
  { name: "Customer Support Pro", tone: "Helpful, empathetic", bot_name: "Aveon Helper", company_name: "Aveon", business_description: "Support for Aveon customers.", additional_instructions: "Be warm.", custom_prompt: "", updated_at: "2025-05-14T10:22:00Z" },
  { name: "Test - Support Specialist", tone: "Clear, professional", bot_name: "Test", company_name: "Aveon", business_description: "Aveon provides smart AI solutions.", additional_instructions: "Always be accurate and concise.", custom_prompt: "", updated_at: "2025-05-18T09:41:00Z" },
  { name: "Sales Assistant", tone: "Friendly, consultative", bot_name: "Aveon Sales", company_name: "Aveon", business_description: "Helps prospects.", additional_instructions: "", custom_prompt: "", updated_at: "2025-05-10T16:05:00Z" }
];

// Static API fixtures copied from the pure industry catalog, version 1.0.0.
const INDUSTRY_TEMPLATES = [
  {
    "id": "restaurant",
    "version": "1.0.0",
    "name": "Restaurant",
    "description": "Answer dining, menu and restaurant policy questions from business information.",
    "questions": [
      "Which branch are you asking about?",
      "What date would you prefer?",
      "What time would you prefer?",
      "How many people would be dining?"
    ],
    "required_information": [
      "Business name, branch addresses and time zone",
      "Published opening hours, menu and prices",
      "Reservation, cancellation and contact policies"
    ],
    "unavailable_actions": [
      "Checking live table availability or holding a table",
      "Creating, changing or cancelling a reservation",
      "Combining tables, collecting deposits or placing paid orders"
    ]
  },
  {
    "id": "clinic",
    "version": "1.0.0",
    "name": "Clinic",
    "description": "Answer clinic administrative questions from published services and policies.",
    "questions": [
      "Which clinic branch are you asking about?",
      "Which administrative service or doctor are you asking about?",
      "What date would you prefer?",
      "What time would you prefer?"
    ],
    "required_information": [
      "Clinic name, branch addresses, opening hours and time zone",
      "Published services, doctor information and administrative fees",
      "Appointment, queue, cancellation and contact policies"
    ],
    "unavailable_actions": [
      "Checking live slots or creating, changing or cancelling an appointment",
      "Issuing queue tickets or guaranteeing a consultation time",
      "Diagnosis, clinical triage, medication or dosage advice",
      "Accessing medical records, insurance or unnecessary health history"
    ]
  },
  {
    "id": "tuition_center",
    "version": "1.0.0",
    "name": "Tuition centre",
    "description": "Explain published courses, schedules, trial policies and enrollment applications.",
    "questions": [
      "Which subject are you interested in?",
      "Which school year or learning stage is the course for?",
      "Which branch would you prefer?",
      "What lesson time would you prefer?"
    ],
    "required_information": [
      "Centre name, branches, time zone, subjects and eligible school years",
      "Published teaching languages, lesson formats, course descriptions and fees",
      "Published classes, terms and dated lesson sessions",
      "Trial, cancellation, application review and guardian verification policies"
    ],
    "unavailable_actions": [
      "Checking live capacity or booking, changing or cancelling a trial",
      "Submitting or withdrawing an application, reserving a place or confirming enrollment",
      "Accessing student records or accepting unverified guardian authority",
      "Collecting fees, changing prices or guaranteeing academic results"
    ]
  },
  {
    "id": "general",
    "version": "1.0.0",
    "name": "General business",
    "description": "Answer from your business documents when no specialized industry profile applies.",
    "questions": [
      "What would you like to know about this business?",
      "Which service or branch are you asking about?"
    ],
    "required_information": [
      "Business name and description",
      "Published services, opening hours and contact information"
    ],
    "unavailable_actions": [
      "Executing reservations, payments, enrollment or other business changes",
      "Accessing internal reports or private customer records"
    ]
  }
];

function industrySuggestion(overrides = {}) {
  return Object.assign({
    draft: { proposal_id: "proposal-1", source_file_id: 11, source_path: "restaurant-guide.pdf", template_id: "restaurant", candidate_ids: ["restaurant"], evidence: ["The document describes restaurant branches and a menu."], status: "suggested", template_version: "1.0.0" },
    published: null,
    templates: INDUSTRY_TEMPLATES,
    can_confirm: true
  }, overrides);
}

/** Mutable per-test server state so writes are observable. */
function makeWorld(overrides = {}) {
  return Object.assign({
    activeProfile: "Test - Support Specialist",
    deployedProfile: "Test - Support Specialist",
    activeKnowledge: "Aveon Knowledge Base.pdf",
    files: [{ file_name: "https://aveon.example/faq", file_type: "url" }],
    channels: 1,
    // What POST /api/match/check returns when it runs.
    matchResult: { match: true, validation_status: "completed", reason: "Both describe Aveon." },
    // What GET /api/dashboard/health reports as already stored. null = never
    // checked or invalidated server-side, which is what arms the auto-check.
    storedMatch: null,
    storedReason: "",
    profiles: PROFILES.slice(),
    industry: industrySuggestion({ draft: null, can_confirm: false }),
    industryConfirmations: [],
    industryReviews: [],
    calls: []
  }, overrides);
}

function matchCalls(world) {
  return world.calls.filter(c => c.startsWith("POST /api/match/check")).length;
}

async function install(page, world) {
  await page.addInitScript(() => {
    sessionStorage.setItem("token", "fake-tenant-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify({
      id: 1, email: "admin@aveon.com", full_name: "Admin User", role: "owner"
    }));
  });

  await page.route("**/*", route => new URL(route.request().url()).origin === "http://127.0.0.1:4173"
    ? route.continue() : route.abort());

  await page.route("**/api/**", async route => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    world.calls.push(`${method} ${url.replace(/^https?:\/\/[^/]+/, "")}`);

    if (url.includes("/api/settings/industry-template/confirm")) {
      const body = JSON.parse(req.postData() || "{}");
      world.industryConfirmations.push(body);
      if (world.industryConfirmGate) await world.industryConfirmGate;
      if (world.industryConfirmStatus) return route.fulfill({ ...json({ status: "error" }), status: world.industryConfirmStatus });
      world.industry.published = { template_id: body.template_id, template_version: "1.0.0", proposal_id: body.proposal_id };
      world.industry.can_confirm = false;
      return route.fulfill(json({ status: "success", data: world.industry }));
    }
    if (url.includes("/api/settings/industry-template/review")) {
      const body = JSON.parse(req.postData() || "{}");
      world.industryReviews.push(body);
      world.industry.draft = { ...world.industry.draft, proposal_id: "proposal-review" };
      world.industry.can_confirm = true;
      return route.fulfill(json({ status: "success", data: world.industry }));
    }
    if (url.includes("/api/settings/industry-template")) {
      if (world.industryLoadStatus) return route.fulfill({ ...json({ status: "error" }), status: world.industryLoadStatus });
      return route.fulfill(json({ status: "success", data: world.industry }));
    }

    if (url.includes("/api/dashboard/health")) {
      return route.fulfill(json({
        status: "success",
        data: {
          channels: { connected_count: world.channels },
          // The stored validation the page seeds from, so a reload does not
          // claim "not validated" when the backend has a result.
          knowledge: { match_result: world.storedMatch, match_reason: world.storedReason }
        }
      }));
    }
    if (url.includes("/api/settings/active-profile")) {
      world.activeProfile = JSON.parse(req.postData() || "{}").active_profile;
      return route.fulfill(json({ status: "success" }));
    }
    if (url.includes("/api/settings/apply-profile")) {
      return route.fulfill(json({ status: "success", message: "Bot deployed." }));
    }
    if (url.includes("/api/settings")) {
      return route.fulfill(json({ status: "success", data: { active_profile: world.deployedProfile || "None" } }));
    }
    if (url.includes("/api/profiles")) {
      if (method === "POST") {
        const sent = JSON.parse(req.postData() || "{}");
        world.profiles = world.profiles.filter(p => p.name !== sent.name).concat([sent]);
        return route.fulfill(json({ status: "success" }));
      }
      if (method === "DELETE") {
        const name = decodeURIComponent(url.split("/api/profiles/")[1].split("?")[0]);
        world.profiles = world.profiles.filter(p => p.name !== name);
        return route.fulfill(json({ status: "success" }));
      }
      return route.fulfill(json({ status: "success", data: world.profiles }));
    }
    if (url.includes("/api/knowledge/active")) {
      return route.fulfill(json({ status: "success", data: { file_name: world.activeKnowledge } }));
    }
    if (url.includes("/api/knowledge/files")) {
      return route.fulfill(json({ status: "success", data: world.files }));
    }
    if (url.includes("/api/match/check")) {
      return route.fulfill(json({ status: "success", data: world.matchResult }));
    }
    if (url.includes("/api/bots/")) {
      return route.fulfill(json({ status: "success", data: { bot_name: "Test", draft_profile_name: world.activeProfile } }));
    }
    return route.fulfill(json({ status: "success", data: {} }));
  });
}

async function open(page, world) {
  await install(page, world);
  await page.goto(`/new_prompt.html?bot_id=${BOT_ID}`);
  await expect(page.locator("#bc-bot-name")).toHaveText("Test");
}

test("loads the wizard and validates itself without a click", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world);

  // Nothing is clicked in this test. The stored result is null, both inputs
  // exist, so the page checks itself and step 3 completes on its own.
  await expect(page.locator("#bc-ready-count")).toHaveText("3");
  await expect(page.locator('.bc-step[data-step="profile"]')).toHaveClass(/is-done/);
  await expect(page.locator('.bc-step[data-step="knowledge"]')).toHaveClass(/is-done/);
  await expect(page.locator('.bc-step[data-step="validate"]')).toHaveClass(/is-done/);
  await expect(page.locator('.bc-step[data-step="deploy"]')).toHaveClass(/is-current/);
  await expect(page.locator("#bc-deploy")).toBeEnabled();
  expect(matchCalls(world)).toBe(1);

  // Three profiles, the active one flagged
  await expect(page.locator(".bc-profile-row")).toHaveCount(3);
  await expect(page.locator(".bc-profile-row.is-selected .bc-profile-name")).toHaveText("Test - Support Specialist");

  // Readiness panel
  await expect(page.locator(".bc-ready-row")).toHaveCount(5);
  await expect(page.locator(".bc-ready-row").nth(3)).toContainText("Validated");

  await page.screenshot({ path: "test-results/bot-config-desktop.png", fullPage: true });
});

test("a stored pass is reused instead of re-run", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({ storedMatch: true, storedReason: "Both describe Aveon." });
  await open(page, world);

  await expect(page.locator("#bc-validate-status")).toHaveText("Validation passed.");
  await expect(page.locator("#bc-deploy")).toBeEnabled();
  // Re-running a stored pass would bill AI credits for an answer already held.
  expect(matchCalls(world)).toBe(0);
  // The button is a re-check now, not the primary path.
  await expect(page.locator("#bc-validate-label")).toHaveText("Re-validate");
});

test("deploy unlocks off the automatic check and then deploys", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world);

  const deploy = page.locator("#bc-deploy");
  await expect(page.locator("#bc-validate-status")).toHaveText("Validation passed.");
  await expect(deploy).toBeEnabled();
  await expect(page.locator("#bc-deploy-gate")).not.toHaveClass(/is-locked/);

  await deploy.click();
  await expect(page.locator("#bc-page-banner")).toContainText("Bot deployed.");
  expect(world.calls.some(c => c.startsWith("PUT /api/settings/apply-profile"))).toBe(true);
});

test("an automatic mismatch keeps deploy locked, names the reason, and does not retry", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({
    matchResult: {
      match: false,
      validation_status: "completed",
      reason: "Profile describes an AI services firm; the document is a bakery menu."
    }
  });
  await open(page, world);

  await expect(page.locator("#bc-validate-status")).toHaveText("Mismatch detected.");
  await expect(page.locator("#bc-validate-reason")).toContainText("bakery menu");
  await expect(page.locator("#bc-page-banner")).toContainText("bakery menu");
  await expect(page.locator("#bc-deploy")).toBeDisabled();
  await expect(page.locator("#bc-deploy-copy"))
    .toHaveText("Profile and primary knowledge do not match. Fix them before deploying.");

  // The user has to resolve this; retrying on a loop would bill credits for a
  // problem only they can fix.
  expect(matchCalls(world)).toBe(1);
});

test("an unavailable check leaves a manual retry and does not loop", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({
    matchResult: { match: null, validation_status: "unavailable", reason: "" }
  });
  await open(page, world);

  await expect(page.locator("#bc-validate-status")).toHaveText("Couldn't check right now.");
  await expect(page.locator("#bc-deploy")).toBeDisabled();
  expect(matchCalls(world)).toBe(1);

  await page.locator("#bc-validate").click();
  expect(matchCalls(world)).toBe(2);
});

test("missing knowledge blocks validation entirely — nothing is spent", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({ activeKnowledge: "" });
  await open(page, world);

  await expect(page.locator("#bc-ready-count")).toHaveText("1");
  await expect(page.locator("#bc-validate")).toBeDisabled();
  await expect(page.locator("#bc-deploy")).toBeDisabled();
  await expect(page.locator("#bc-deploy-copy")).toHaveText("Select active primary knowledge first.");
  expect(matchCalls(world)).toBe(0);
});

test("switching the active profile re-checks the new pairing on its own", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world);

  await expect(page.locator("#bc-deploy")).toBeEnabled();
  expect(matchCalls(world)).toBe(1);

  // Pick a different profile and activate it
  await page.locator(".bc-profile-row", { hasText: "Sales Assistant" }).locator("input").check();
  await page.locator("#bc-preview").getByText("Use this profile").click();

  // The server nulls last_match_result on set_active_profile, so the new pairing
  // validates itself rather than demanding another click.
  await expect(page.locator("#bc-validate-status")).toHaveText("Validation passed.");
  await expect(page.locator("#bc-deploy")).toBeEnabled();
  await expect(page.locator("#bc-ready-count")).toHaveText("3");
  expect(matchCalls(world)).toBe(2);
});

test("saving a profile re-checks it against the knowledge", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world);
  expect(matchCalls(world)).toBe(1);

  await page.locator("#bc-edit").click();
  await expect(page.locator("#bc-modal")).toHaveClass(/is-open/);
  await expect(page.locator("#bc-f-name")).toHaveValue("Test - Support Specialist");

  await page.locator("#bc-f-company").fill("Aveon Global");
  await page.locator("#bc-save").click();

  await expect(page.locator("#bc-modal")).not.toHaveClass(/is-open/);
  expect(matchCalls(world)).toBe(2);

  const saved = world.profiles.find(p => p.name === "Test - Support Specialist");
  expect(saved.company_name).toBe("Aveon Global");
});

test("Escape closes the editor and returns focus", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld());

  await page.locator("#bc-create").click();
  await expect(page.locator("#bc-modal")).toHaveClass(/is-open/);

  await page.keyboard.press("Escape");
  await expect(page.locator("#bc-modal")).not.toHaveClass(/is-open/);
  await expect(page.locator("#bc-create")).toBeFocused();
});

test("mobile shows the sticky action bar and does not overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, makeWorld());

  await expect(page.locator(".bc-actionbar")).toBeVisible();

  // The automatic check has already unlocked Deploy; the bar's left button is a
  // re-check rather than the gate it used to be.
  await expect(page.locator("#bc-deploy-mobile")).toBeEnabled();
  await expect(page.locator("#bc-validate-mobile")).toHaveText("Re-validate");

  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  await page.screenshot({ path: "test-results/bot-config-mobile.png" });
});

test("editing a profile preserves a free-text tone instead of blanking it", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld();
  await open(page, world);

  // "Clear, professional" is what the backend actually stores — persona
  // derivation writes free text, it is not one of three fixed options.
  await page.locator("#bc-edit").click();
  await expect(page.locator("#bc-f-tone")).toHaveValue("Clear, professional");

  await page.locator("#bc-f-company").fill("Aveon Global");
  await page.locator("#bc-save").click();
  await expect(page.locator("#bc-modal")).not.toHaveClass(/is-open/);

  // merge_persona_write treats a present-but-blank field as a deliberate
  // delete, so sending "" here would silently destroy the stored tone.
  const saved = world.profiles.find(p => p.name === "Test - Support Specialist");
  expect(saved.tone).toBe("Clear, professional");
  expect(saved.company_name).toBe("Aveon Global");
});

test("supporting websites read as optional, not as an outstanding task", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await open(page, makeWorld({ files: [] }));

  const row = page.locator(".bc-ready-row").nth(2);
  await expect(row).toContainText("Supporting websites");
  await expect(row).toContainText("Optional");
  await expect(row).not.toContainText("Needs attention");

  // And it must never gate deployment.
  await expect(page.locator("#bc-deploy")).toBeEnabled();
});

test("guided setup waits for apply success and lets the owner continue to testing", async ({ page }) => {
  const world = makeWorld({ storedMatch: true });
  await install(page, world);
  await page.goto(`/new_prompt.html?bot_id=${BOT_ID}&setup=1`);
  await expect(page.locator("#bc-setup-journey")).toBeVisible();
  await expect(page.locator("#bc-validate-title")).toHaveText("Check instructions");
  await expect(page.locator("#bc-validate-copy")).not.toContainText("active profile");
  await expect(page.locator("#bc-validate-status")).toHaveText("Instructions match the PDF.");
  await expect(page.locator("#bc-validate-label")).toHaveText("Check again");
  await expect(page.locator("#bc-setup-next")).toBeHidden();
  await expect(page.locator("#bc-deploy")).toBeEnabled();
  await expect(page.locator("#bc-deploy")).toContainText("Apply instructions");

  await page.locator("#bc-deploy").click();
  await expect(page.locator("#bc-continue-test")).toBeVisible();
  await expect(page.locator("#bc-continue-test")).toBeFocused();
  await expect(page.locator("#bc-continue-test")).toHaveAttribute("href", `testbot.html?bot_id=${BOT_ID}&setup=1`);
  expect(world.calls.filter(c => c.startsWith("PUT /api/settings/apply-profile"))).toHaveLength(1);
  // The old success path redirected after 1.2 seconds, before it could be read.
  await page.waitForTimeout(1400);
  await expect(page).toHaveURL(new RegExp(`/new_prompt\\.html\\?bot_id=${BOT_ID}&setup=1$`));
  await expect(page.locator("#bc-deploy")).toBeHidden();
});

test("guided setup cannot continue when the profile and document do not match", async ({ page }) => {
  const world = makeWorld({ storedMatch: false, storedReason: "The document describes a different business." });
  await install(page, world);
  await page.goto(`/new_prompt.html?bot_id=${BOT_ID}&setup=1`);
  await expect(page.locator("#bc-validate-status")).toHaveText("Mismatch detected.");
  await expect(page.locator("#bc-deploy")).toBeDisabled();
  await expect(page.locator("#bc-deploy-copy")).toHaveText("Your instructions and PDF do not match. Review them before applying.");
  await expect(page.locator("#bc-setup-next")).toBeHidden();
  expect(world.calls.some(c => c.startsWith("PUT /api/settings/apply-profile"))).toBe(false);
});

test("a fresh bot cannot validate the deployed None label as a selected profile", async ({ page }) => {
  const world = makeWorld({ activeProfile: null, deployedProfile: null, profiles: [], storedMatch: null });
  await install(page, world);
  await page.goto(`/new_prompt.html?bot_id=${BOT_ID}&setup=1`);
  await expect(page.locator("#bc-profiles")).toContainText("No instructions yet");
  await expect(page.locator("#bc-deploy-copy")).toHaveText("Choose instructions for your bot first.");
  await expect(page.locator("#bc-validate")).toBeDisabled();
  await expect(page.locator("#bc-deploy")).toBeDisabled();
  expect(matchCalls(world)).toBe(0);
});

test("reloading setup keeps the selected draft even before it is deployed", async ({ page }) => {
  const world = makeWorld({ activeProfile: "Sales Assistant", deployedProfile: null, storedMatch: true });
  await install(page, world);
  await page.goto(`/new_prompt.html?bot_id=${BOT_ID}&setup=1`);
  await expect(page.locator(".bc-profile-row.is-selected .bc-profile-name")).toHaveText("Sales Assistant");
  await page.reload();
  await expect(page.locator(".bc-profile-row.is-selected .bc-profile-name")).toHaveText("Sales Assistant");
  await expect(page.locator("#bc-deploy")).toBeEnabled();
  expect(world.calls.some(c => /^GET \/api\/settings(?:\?|$)/.test(c))).toBe(false);
});

test("guided instruction save tells the owner to choose it before any check", async ({ page }) => {
  const world = makeWorld({ activeProfile: null, deployedProfile: null, profiles: [], storedMatch: null });
  await install(page, world);
  await page.goto(`/new_prompt.html?bot_id=${BOT_ID}&setup=1`);
  await page.locator("#bc-create").click();
  await expect(page.locator("#bc-modal-title")).toHaveText("Create instructions");
  await expect(page.locator("#bc-save")).toHaveText("Save instructions");
  await page.locator("#bc-f-name").fill("Bakery support");
  await page.locator("#bc-f-bot").fill("Bakery helper");
  await page.locator("#bc-f-company").fill("Bakery");
  await page.locator("#bc-f-tone").fill("Friendly");
  await page.locator("#bc-f-desc").fill("A bakery answering menu questions.");
  await page.locator("#bc-save").click();
  await expect(page.locator("#bc-page-banner")).toContainText("Choose these instructions to check them against your PDF.");
  await expect(page.getByRole("button", { name: "Choose these instructions", exact: true })).toBeVisible();
  expect(matchCalls(world)).toBe(0);
  expect(world.calls.some(c => c.startsWith("PUT /api/settings/active-profile"))).toBe(false);
  expect(world.calls.some(c => c.startsWith("PUT /api/settings/apply-profile"))).toBe(false);
});

test("advanced prompt disclosure preserves a saved override when closed", async ({ page }) => {
  const profiles = PROFILES.map(profile => ({ ...profile, custom_prompt: "Use the bakery menu." }));
  const world = makeWorld({ profiles, storedMatch: true });
  await install(page, world);
  await page.goto(`/new_prompt.html?bot_id=${BOT_ID}&setup=1`);
  await page.locator("#bc-edit").click();
  const details = page.locator("#bc-prompt-options");
  await expect(details).not.toHaveAttribute("open");
  await expect(page.locator("#bc-f-prompt")).toBeHidden();
  await expect(page.locator("#bc-f-prompt")).toHaveValue("Use the bakery menu.");
  await details.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#bc-f-prompt")).toBeVisible();
  await page.locator("#bc-f-prompt").fill("Answer only from the bakery menu.");
  await details.locator("summary").click();
  await page.locator("#bc-save").click();
  await expect(page.locator("#bc-modal")).not.toHaveClass(/is-open/);
  expect(world.profiles.find(profile => profile.name === world.activeProfile).custom_prompt).toBe("Answer only from the bakery menu.");
});

test("industry suggestions stay read-only until explicitly confirmed and applied", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const world = makeWorld({ industry: industrySuggestion(), storedMatch: true });
  await open(page, world);
  await expect(page.locator("#bc-industry-status")).toContainText("Suggested industry");
  await expect(page.locator("#bc-industry-evidence")).toContainText("restaurant branches and a menu");
  await expect(page.locator("#bc-industry-source")).toContainText("restaurant-guide.pdf");
  await expect(page.locator("#bc-industry-panel")).toContainText("Check your documents include");
  await page.getByLabel("Industry", { exact: true }).selectOption("tuition_center");
  await expect(page.locator("#bc-industry-checklist")).toContainText("course descriptions and fees");
  expect(world.industryConfirmations).toEqual([]);
  expect(world.calls.filter(c => c.startsWith("GET /api/settings/industry-template"))).toHaveLength(1);
  await page.locator("#bc-industry-panel").screenshot({ path: test.info().outputPath("industry-desktop.png") });
  await page.getByRole("button", { name: "Confirm and apply industry", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#bc-industry-published")).toContainText("Tuition centre");
  await expect(page.locator("#bc-industry-confirm")).toBeDisabled();
  await page.reload();
  await expect(page.locator("#bc-industry-status")).toContainText("confirmed and applied");
  await expect(page.locator("#bc-industry-status")).not.toContainText("unavailable");
  expect(world.industryConfirmations).toEqual([{ proposal_id: "proposal-1", template_id: "tuition_center" }]);
  expect(world.calls.some(c => c.startsWith("PUT /api/settings/apply-profile") || c.startsWith("POST /api/profiles"))).toBe(false);
  expect(world.profiles).toEqual(PROFILES);
});

test("unknown industry allows an explicit choice without inventing document facts", async ({ page }) => {
  const industry = industrySuggestion();
  industry.draft = { ...industry.draft, template_id: null, candidate_ids: [], status: "uncertain", evidence: [] };
  const world = makeWorld({ industry });
  await open(page, world);
  await expect(page.locator("#bc-industry-status")).toContainText("could not confidently identify");
  await expect(page.locator("#bc-industry-confirm")).toBeDisabled();
  await page.getByLabel("Industry", { exact: true }).selectOption("restaurant");
  await expect(page.locator("#bc-industry-confirm")).toBeEnabled();
  expect(world.industryConfirmations).toEqual([]);
});

test("a confirmed industry can be corrected without replacing live guidance until confirmation", async ({ page }) => {
  const world = makeWorld({ industry: industrySuggestion(), storedMatch: true });
  await open(page, world);
  await expect(page.locator("#bc-industry-change")).toBeHidden();
  await page.locator("#bc-industry-confirm").click();
  await expect(page.locator("#bc-industry-published")).toContainText("Restaurant");
  await expect(page.getByRole("button", { name: "Change industry", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Change industry", exact: true }).click();
  await expect(page.locator("#bc-industry-status")).toContainText("stays active until you confirm");
  await expect(page.locator("#bc-industry-select")).toBeEnabled();
  await expect(page.locator("#bc-industry-select")).toHaveValue("restaurant");
  await expect(page.locator("#bc-industry-published")).toContainText("Restaurant");
  expect(world.industryReviews).toEqual([{ proposal_id: "proposal-1" }]);
  expect(world.industryConfirmations).toHaveLength(1);
  await page.locator("#bc-industry-select").selectOption("tuition_center");
  await expect(page.locator("#bc-industry-published")).toContainText("Restaurant");
  await page.locator("#bc-industry-confirm").click();
  await expect(page.locator("#bc-industry-published")).toContainText("Tuition centre");
  expect(world.industryConfirmations.at(-1)).toEqual({ proposal_id: "proposal-review", template_id: "tuition_center" });
  expect(world.calls.some(c => c.startsWith("PUT /api/settings/apply-profile") || c.startsWith("POST /api/profiles"))).toBe(false);
});

test("a fresh bot with empty industry objects never reports confirmation", async ({ page }) => {
  const world = makeWorld({ industry: industrySuggestion({ draft: {}, published: {}, can_confirm: false }) });
  await open(page, world);
  await expect(page.locator("#bc-industry-status")).toContainText("No industry suggestion");
  await expect(page.locator("#bc-industry-status")).not.toContainText("confirmed");
  await expect(page.locator("#bc-industry-published")).toHaveText("No industry guidance has been applied.");
  await expect(page.locator("#bc-industry-confirm")).toBeDisabled();
  expect(world.industryConfirmations).toEqual([]);
});

test("industry confirmation keeps the live template visible and blocks duplicate requests", async ({ page }) => {
  let finish;
  const world = makeWorld({ industry: industrySuggestion({ published: { template_id: "tuition_center", template_version: "1.0.0" } }),
    industryConfirmGate: new Promise(resolve => { finish = resolve; }) });
  await open(page, world);
  await page.locator("#bc-industry-confirm").click();
  try {
    await expect.poll(() => world.industryConfirmations.length).toBe(1);
    await expect(page.locator("#bc-industry-confirm")).toBeDisabled();
    await expect(page.locator("#bc-industry-select")).toBeDisabled();
    await expect(page.locator("#bc-industry-published")).toContainText("Tuition centre");
    await page.locator("#bc-industry-form").evaluate(form => form.dispatchEvent(new Event("submit", { cancelable: true })));
    expect(world.industryConfirmations).toHaveLength(1);
  } finally { finish(); }
  await expect(page.locator("#bc-industry-published")).toContainText("Restaurant");
});

for (const status of [400, 409, 503]) {
  test(`industry confirmation ${status} preserves selection and does not claim success`, async ({ page }) => {
    const world = makeWorld({ industry: industrySuggestion({ published: { template_id: "restaurant", template_version: "1.0.0" } }), industryConfirmStatus: status });
    await open(page, world);
    await page.locator("#bc-industry-select").selectOption("tuition_center");
    await page.locator("#bc-industry-confirm").click();
    await expect(page.locator("#bc-industry-error")).not.toBeEmpty();
    await expect(page.locator("#bc-industry-select")).toHaveValue("tuition_center");
    await expect(page.locator("#bc-industry-published")).toContainText("Restaurant");
    if (status === 409) {
      await expect(page.locator("#bc-industry-error")).toContainText("changed");
      await expect(page.locator("#bc-industry-confirm")).toBeDisabled();
      world.industry.draft = { ...world.industry.draft, proposal_id: "proposal-2", template_id: "tuition_center" };
      world.industryConfirmStatus = null;
      await page.locator("#bc-industry-reload").click();
      await expect(page.locator("#bc-industry-confirm")).toBeEnabled();
      await page.locator("#bc-industry-confirm").click();
      await expect(page.locator("#bc-industry-published")).toContainText("Tuition centre");
      expect(world.industryConfirmations.at(-1).proposal_id).toBe("proposal-2");
    } else {
      world.industryConfirmStatus = null;
      await page.locator("#bc-industry-confirm").click();
      await expect(page.locator("#bc-industry-published")).toContainText("Tuition centre");
    }
  });
}

test("industry read failure and missing draft offer truthful recovery", async ({ page }) => {
  const world = makeWorld({ industryLoadStatus: 503 });
  await open(page, world);
  await expect(page.locator("#bc-industry-error")).toContainText("unavailable");
  await expect(page.locator("#bc-industry-published")).toContainText("not been checked");
  await expect(page.locator("#bc-industry-confirm")).toBeDisabled();
  world.industryLoadStatus = null;
  await page.getByRole("button", { name: "Reload industry suggestion", exact: true }).click();
  await expect(page.locator("#bc-industry-status")).toContainText("No industry suggestion");
  await expect(page.locator("#bc-industry-status")).toContainText("readable primary document");
});

test("industry permission and evidence stay safe on mobile", async ({ page }) => {
  const industry = industrySuggestion({ can_confirm: false });
  industry.draft.evidence = ['<img src=x onerror="window.industryInjected=true">', "x".repeat(240)];
  industry.draft.source_path = `${"n".repeat(240)}.pdf`;
  const world = makeWorld({ industry });
  await page.setViewportSize({ width: 375, height: 812 });
  await open(page, world);
  await expect(page.locator("#bc-industry-evidence")).toContainText("<img");
  expect(await page.evaluate(() => window.industryInjected)).toBeUndefined();
  await expect(page.locator("#bc-industry-confirm")).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await page.locator("#bc-industry-panel").evaluate(panel => panel.scrollWidth <= panel.clientWidth)).toBe(true);
  // A taller capture shows the whole card between the existing fixed bars;
  // interaction and overflow checks above still use the 375 x 812 viewport.
  await page.setViewportSize({ width: 375, height: 1800 });
  await page.goto(`/new_prompt.html?bot_id=${BOT_ID}&setup=1`);
  await expect(page.locator("#bc-industry-evidence")).toContainText("<img");
  await page.locator("#bc-industry-panel").screenshot({ path: test.info().outputPath("industry-mobile.png") });
  expect(world.industryConfirmations).toEqual([]);
});
