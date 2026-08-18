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

/** Mutable per-test server state so writes are observable. */
function makeWorld(overrides = {}) {
  return Object.assign({
    activeProfile: "Test - Support Specialist",
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

  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());

  await page.route("**/api/**", async route => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    world.calls.push(`${method} ${url.replace(/^https?:\/\/[^/]+/, "")}`);

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
      return route.fulfill(json({ status: "success", data: { active_profile: world.activeProfile } }));
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
      return route.fulfill(json({ status: "success", data: { bot_name: "Test" } }));
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
