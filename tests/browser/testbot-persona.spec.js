/**
 * Browser e2e for the derived persona, driven through the Behaviour Studio Test lab tab
 * (frontend/behaviour.html?tab=test; frontend/testbot.html now redirects there).
 *
 * Unlike the sibling specs, this one does NOT mock /api/**. Mocking the chat
 * endpoint would make every assertion here a tautology: it would prove the page
 * renders whatever the server said, not that the derived persona reached the
 * reply. Instead `testbot_persona_server.py` serves the real Flask app --
 * create_app() already mounts frontend/ at the root origin -- with only the
 * Supabase and LLM-provider boundaries doubled, at the same seams the pytest
 * suite doubles them.
 *
 * MONEY: no billed LLM call is possible. The provider is replaced by the
 * grounded stub and the failover provider is made to raise. Running this costs
 * nothing.
 *
 *   pnpm test:testbot-persona-browser
 */

const { expect, test } = require("@playwright/test");
const { spawn } = require("child_process");
const path = require("path");

const PORT = Number(process.env.TESTBOT_E2E_PORT || 4174);
const ORIGIN = `http://127.0.0.1:${PORT}`;
const ROOT = path.resolve(__dirname, "..", "..");
const PYTHON =
  process.env.E2E_PYTHON || path.join(ROOT, ".venv", "Scripts", "python.exe");
// Overridable so the same spec can be pointed at a deliberately mutated
// harness, which is how this file was proved non-vacuous.
const SERVER =
  process.env.TESTBOT_E2E_SERVER || path.join(__dirname, "testbot_persona_server.py");
const BOOT_TIMEOUT_MS = 60000;

test.use({ baseURL: ORIGIN });

let server;
/** The persona constants, served by the harness so this file cannot drift. */
let fixtures;

async function waitForHealth() {
  const deadline = Date.now() + BOOT_TIMEOUT_MS;
  let lastError = "not started";

  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${ORIGIN}/__e2e__/health`);
      if (response.ok) {
        return;
      }
      lastError = `status ${response.status}`;
    } catch (error) {
      lastError = error.message;
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }

  throw new Error(`harness server never became healthy: ${lastError}`);
}

test.beforeAll(async () => {
  server = spawn(PYTHON, [SERVER], {
    cwd: ROOT,
    env: { ...process.env, TESTBOT_E2E_PORT: String(PORT) },
    stdio: ["ignore", "pipe", "pipe"]
  });

  const log = [];
  server.stdout.on("data", chunk => log.push(String(chunk)));
  server.stderr.on("data", chunk => log.push(String(chunk)));
  server.on("exit", code => log.push(`\n[server exited with code ${code}]`));

  try {
    await waitForHealth();
  } catch (error) {
    throw new Error(`${error.message}\n--- harness output ---\n${log.join("")}`);
  }

  fixtures = await (await fetch(`${ORIGIN}/__e2e__/fixtures`)).json();
});

test.afterAll(async () => {
  if (!server || server.exitCode !== null) {
    return;
  }
  // Werkzeug on Windows leaves the socket bound if only the parent is signalled.
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(server.pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    server.kill("SIGTERM");
  }
});

/** Point the harness at one of the three cases under test. */
async function activateScenario(name) {
  const response = await fetch(`${ORIGIN}/__e2e__/scenario`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
  expect(response.ok, `failed to activate scenario ${name}`).toBe(true);
}

async function providerState() {
  return (await fetch(`${ORIGIN}/__e2e__/provider`)).json();
}

test.beforeEach(async ({ page }) => {
  // Same offline treatment the sibling specs give third-party assets.
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());

  await page.addInitScript(() => {
    sessionStorage.setItem("token", "e2e-testbot-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem(
      "user",
      JSON.stringify({
        id: 1,
        email: "owner@example.com",
        role: "admin",
        company_id: 42
      })
    );
  });
});

/**
 * Load the page for a scenario and wait until it is ready to take a message.
 *
 * Retargeted on 2026-08-18 when testbot.html was merged into the Behaviour
 * Studio's Test lab tab. The resolved profile is no longer printed as the first
 * bot bubble; it is named in the Active setup strip, which is what this now
 * waits on. NOT VERIFIED: this spec's Flask harness does not start in the
 * current environment, so all three cases fail at activateScenario before ever
 * reaching a page. Re-run once that harness works.
 */
async function openTestbot(page, scenario) {
  await activateScenario(scenario);
  await page.goto(`/behaviour.html?tab=test&bot_id=${fixtures.chatbotId}`);

  await expect(page.locator(".bh-setup-item").first()).toBeVisible();
  await expect(page.locator("#bh-input")).toBeEnabled();
}

/** Send a message the way a user does and return the reply text on screen. */
async function ask(page, text) {
  const replied = page.waitForResponse(
    response =>
      response.url().includes("/api/testbot/chat") &&
      response.request().method() === "POST"
  );

  await page.fill("#bh-input", text);
  await page.click("#bh-send");
  await replied;

  // sendTestMessage() removes the pending bubble before appending the reply.
  await expect(
    page.locator(".bh-bubble-bot").filter({ hasText: "Typing" })
  ).toHaveCount(0);

  return (await page.locator(".bh-bubble-bot").last().innerText()).trim();
}

// ===================================================================
// CASE 1: an e-commerce knowledge set yields replies about that store
// ===================================================================

test("an ingested e-commerce knowledge set makes the bot name what the store sells", async ({
  page
}) => {
  await openTestbot(page, "ecommerce");

  // The deployment precondition, visible in the browser: the profile the
  // derivation wrote is the one the page resolved. Now read from the Active
  // setup strip rather than an opening chat bubble.
  await expect(page.locator(".bh-setup-item").first()).toContainText("Default Profile");

  const reply = await ask(page, fixtures.productQuestion);

  expect(reply).toContain(fixtures.derivedCompany);
  // These terms reach the prompt only through retrieved knowledge, never
  // through the persona description, so this asserts the RAG channel too.
  for (const term of fixtures.knowledgeOnlyTerms) {
    expect(reply).toContain(term);
  }
  expect(reply).not.toContain(fixtures.placeholderCompany);
});

// ===================================================================
// CASE 2: no ingested documents -> the generic greeting
// ===================================================================

test("a bot with no ingested documents falls back to the generic greeting", async ({
  page
}) => {
  await openTestbot(page, "no_documents");

  const reply = await ask(page, "hi");

  expect(reply).toBe(fixtures.genericGreeting);
  // Greeting is a local intent: it must not reach a provider at all.
  expect((await providerState()).called).toBe(false);
});

// ===================================================================
// CASE 3: a client override wins over the derived value
// ===================================================================

test("a client override beats the value a re-derivation proposed", async ({ page }) => {
  await openTestbot(page, "client_override");

  const reply = await ask(page, fixtures.productQuestion);

  expect(reply).toContain(fixtures.overrideCompany);
  expect(reply).not.toContain(fixtures.rejectedCompany);
});
