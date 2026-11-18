"use strict";

/*
 * F1 safety net for the Astro migration. Every frontend/*.html page must:
 *   (a) load with HTTP 200,
 *   (b) raise no uncaught page error,
 *   (c) log no console.error beyond its own commented allowlist,
 *   (d) show one landmark a user sees,
 *   (e) request its main API (`mainApi`), so a page that stops loading its data fails.
 * The static server serves web/dist first, so the same spec re-checks each page once migrated.
 * No request leaves the machine: every off-origin request is aborted or answered locally, and a
 * request to any host not listed in THIRD_PARTY fails the test.
 */

const fs = require("fs");
const path = require("path");
const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

const ORIGIN = "http://127.0.0.1:4173";
const BOT_ID = "7";
const WIDGET_KEY = "wgt_smoke_test";
const VENDOR_DIR = path.resolve(__dirname, "../../output/client-journey-review/vendor");
// Pages only ever call lucide.createIcons(); a no-op keeps the icon CDN out of the run.
const LUCIDE_SHIM = "window.lucide = { createIcons: function () {} };";
// new_linkdocs ships compiled JavaScript and still uses these three CDN libraries at runtime.
const VENDORED = [
  [/^https:\/\/unpkg\.com\/react@18\//, "react.js"],
  [/^https:\/\/unpkg\.com\/react-dom@18\//, "react-dom.js"],
  [/^https:\/\/unpkg\.com\/vis-network\//, "vis.js"]
];

// Hosts the pages load from today. Each is aborted or answered locally; any other host fails the test.
const THIRD_PARTY = new Set([
  "fonts.googleapis.com", "fonts.gstatic.com",      // web fonts; pages fall back to system fonts
  "unpkg.com",                                      // lucide (stub), React/ReactDOM/vis (local copies)
  "cdnjs.cloudflare.com",                           // GSAP; landing stays static without it
  "accounts.google.com",                            // Google sign-in script; auth pages hide the button
  "manertvcpqtsmegqvhuc.supabase.co"                // decorative auth-page images
]);

const TENANT_USER = { id: 1, company_id: 42, role: "owner", email: "owner@example.test", status: "active" };
const PLATFORM_IDENTITY = {
  user: { id: 9001, email: "operator@example.test", full_name: "Smoke Operator", status: "active" },
  platform_admin: { id: 7001, is_active: true },
  platform_role: "super_admin",
  modules: { billing: true, support: true, customers: true }
};
const EMPTY_PAGE = { limit: 25, offset: 0, returned: 0, total: 0, has_more: false };

const ok = data => ({ status: 200, body: { status: "success", data } });
const raw = (body, status = 200) => ({ status, body });
const h1 = name => page => page.getByRole("heading", { level: 1, name, exact: typeof name === "string" });

// Answers every page may ask for; a page's own `api` entries win.
const COMMON_API = {
  "/api/bots/7": ok({ id: 7, bot_name: "Smoke Bot" }),
  "/api/platform-admin/me": ok(PLATFORM_IDENTITY)
};

/*
 * access: public = no session; auth = sign-in flow page, no token;
 *         tenant = seeded tenant token; platform = tenant token + platform admin flag.
 * lands:  legacy URL that redirects; the landmark is checked on the destination.
 * query:  the URL a page settles on (bot pages add ?bot_id themselves); opening it directly
 *         keeps the run free of self-redirect races.
 * mainApi: pathname (or RegExp for paths with ids) the page must request; null states why it has none.
 * consoleAllow: [{ pattern, url?, why }] - each allowed console.error states its reason.
 */
const PAGES = [
  { file: "landing.html", access: "public", mainApi: null, landmark: h1("Scale Your Business on Autopilot") }, // static marketing page: no API call
  { file: "privacy.html", access: "public", mainApi: null, landmark: h1("Privacy Policy") }, // static legal page: no API call
  { file: "terms.html", access: "public", mainApi: null, landmark: h1("Terms & Conditions") }, // static legal page: no API call
  // Flask serves the visitor widget at /chat/<public_key> and the page reads the key from that path.
  {
    file: "widget-chat.html", access: "public", mainApi: `/api/widget/${WIDGET_KEY}/config`, route: `/chat/${WIDGET_KEY}`,
    api: {
      [`/api/widget/${WIDGET_KEY}/config`]: ok({ display_name: "Smoke Shop", welcome_message: "Welcome", suggested_questions: [] }),
      [`/api/widget/${WIDGET_KEY}/session`]: ok({ session_id: "smoke-session" }),
      [`/api/widget/${WIDGET_KEY}/messages`]: ok({ messages: [], last_message_id: 0, has_more: false, awaiting_human: false }),
      [`/api/widget/${WIDGET_KEY}/tuition`]: raw({ status: "error", code: "tuition_disabled" }, 503)
    },
    consoleAllow: [{
      pattern: /^Failed to load resource: the server responded with a status of 404/,
      url: /\/chat\/favicon\.svg$/,
      why: "favicon.svg is linked relatively, so /chat/<key> asks for /chat/favicon.svg; Flask routes that to the chat page, so no icon there either"
    }],
    landmark: page => page.getByRole("log")
  },

  { file: "login.html", access: "auth", mainApi: "/api/auth/google-config", landmark: h1("Sign in to Omnexa") },
  { file: "register.html", access: "auth", mainApi: "/api/auth/google-config", landmark: h1("Create your Omnexa account") },
  { file: "forgot.html", access: "auth", mainApi: "/api/auth/turnstile-config", landmark: h1("Reset your password") },
  { file: "verify-email.html", access: "auth", mainApi: null, session: { pending_verification_email: "new@example.test" }, landmark: h1("Check your email") }, // calls the API only when the user submits or resends the code
  {
    file: "accept-invite.html", access: "auth", mainApi: "/api/invites/validate", query: "?token=smoke-invite",
    api: { "/api/invites/validate": raw({ status: "success", valid: true, email: "invitee@example.test", role: "member" }) },
    landmark: h1("Accept your invitation")
  },

  { file: "index.html", access: "tenant", mainApi: "/api/dashboard/health", query: "?bot_id=7", landmark: h1("Smoke Bot") },
  { file: "bots.html", access: "tenant", mainApi: "/api/bots", landmark: h1("My bots") },
  { file: "analysis.html", access: "tenant", mainApi: /^\/api\/chatbots\/\d+\/analysis$/, landmark: h1("Analysis") },
  { file: "behaviour.html", access: "tenant", mainApi: "/api/ai-models", query: "?bot_id=7&tab=model", landmark: h1("Behaviour Studio") },
  { file: "billing.html", access: "tenant", mainApi: "/api/billing/subscription/orders", landmark: h1("Billing") },
  { file: "bookings.html", access: "tenant", mainApi: "/api/bookings", landmark: h1("Bookings") },
  {
    file: "broadcast.html", access: "tenant", mainApi: "/api/broadcast/campaigns",
    api: { "/api/broadcast/campaigns": ok([]), "/api/media-attachments": ok([]), "/api/meta-templates": ok([]) },
    landmark: h1("Broadcast")
  },
  { file: "conversations.html", access: "tenant", mainApi: "/api/conversations", landmark: h1("Conversations") },
  { file: "crm.html", access: "tenant", mainApi: "/api/crm/leads", query: "?bot_id=7&view=today", landmark: h1(/insights$/) },
  { file: "geo-analysis.html", access: "tenant", mainApi: "/api/geo/capabilities", landmark: h1("See how AI describes your brand") },
  { file: "geo-provider-comparison.html", access: "tenant", mainApi: "/api/geo/capabilities", landmark: h1("Same question. Two delivery routes.") },
  {
    file: "integration.html", access: "tenant", mainApi: "/api/whatsapp/channels", query: "?bot_id=7",
    api: {
      "/api/telegram/channels": ok([]), "/api/whatsapp/channels": ok([]),
      "/api/wasender/channels": ok([]), "/api/whatchimp/channels": ok([])
    },
    landmark: h1("Publish your bot")
  },
  {
    file: "media_attachments.html", access: "tenant", mainApi: "/api/media-attachments",
    api: { "/api/media-attachments": ok([]), "/api/meta-templates": ok([]) },
    landmark: h1("Media Attachments")
  },
  { file: "meta_templates.html", access: "tenant", mainApi: "/api/meta-templates", api: { "/api/meta-templates": ok([]) }, landmark: h1("Message Templates") },
  {
    file: "new_linkdocs.html", access: "tenant", mainApi: "/api/knowledge/files", query: "?bot_id=7", vendor: true,
    api: { "/api/knowledge/files": ok([]) },
    landmark: h1("Knowledge workspace")
  },
  { file: "new_prompt.html", access: "tenant", mainApi: "/api/profiles", query: "?bot_id=7", api: { "/api/profiles": ok([]) }, landmark: h1(/^Bot configuration/) },
  { file: "pricing.html", access: "tenant", mainApi: "/api/billing/plans", landmark: h1("Plans & Usage") },
  { file: "profile.html", access: "tenant", mainApi: "/api/user", landmark: h1("Profile") },
  { file: "support.html", access: "tenant", mainApi: "/api/support/requests", landmark: h1("Support") },
  { file: "team.html", access: "tenant", mainApi: "/api/users", landmark: h1("Team") },
  // Redirect stubs only forward (mainApi: null); each destination's own entry checks its data call.
  { file: "customer_insights.html", access: "tenant", mainApi: null, lands: "/crm.html", landmark: h1(/insights$/) },
  { file: "reports.html", access: "tenant", mainApi: null, lands: "/crm.html", landmark: h1(/insights$/) },
  { file: "message_style.html", access: "tenant", mainApi: null, lands: "/behaviour.html", landmark: h1("Behaviour Studio") },
  { file: "model_settings.html", access: "tenant", mainApi: null, lands: "/behaviour.html", landmark: h1("Behaviour Studio") },
  { file: "testbot.html", access: "tenant", mainApi: null, lands: "/behaviour.html", landmark: h1("Behaviour Studio") },
  { file: "training.html", access: "tenant", mainApi: null, lands: "/support.html", landmark: h1("Support") },

  { file: "admin.html", access: "platform", mainApi: "/api/platform-admin/approval-requests", api: { "/api/platform-admin/me": ok({ ...PLATFORM_IDENTITY, platform_role: "admin" }) }, landmark: h1("Your work, at a glance") },
  { file: "superadmin.html", access: "platform", mainApi: "/api/platform-admin/overview", landmark: h1("Overview") },
  { file: "platform-admin.html", access: "platform", mainApi: "/api/platform-admin/overview", landmark: h1("Platform operations") },
  { file: "platform-admin-audit-events.html", access: "platform", mainApi: "/api/platform-admin/audit-events", landmark: h1("Audit Logs") },
  { file: "platform-admin-billing.html", access: "platform", mainApi: "/api/platform-admin/billing/companies", landmark: h1("Platform Billing & Subscriptions") },
  {
    file: "platform-admin-companies.html", access: "platform", mainApi: "/api/platform-admin/companies",
    api: { "/api/platform-admin/companies": ok({ companies: [], pagination: EMPTY_PAGE, sort: { by: "created_at", order: "desc" }, filters: { search: null, status: null } }) },
    landmark: h1("Company directory")
  },
  {
    file: "platform-admin-company.html", access: "platform", mainApi: /^\/api\/platform-admin\/companies\/\d+$/, query: "?company_id=42",
    api: { "/api/platform-admin/companies/42": ok({ id: 42, company_name: "Smoke Tenant", status: "active", created_at: "2026-07-01T00:00:00+00:00" }) },
    landmark: h1("Smoke Tenant")
  },
  { file: "platform-admin-help.html", access: "platform", mainApi: "/api/platform-admin/help/articles", api: { "/api/platform-admin/help/articles": ok({ articles: [] }) }, landmark: h1("Help Articles") },
  { file: "platform-admin-support.html", access: "platform", mainApi: "/api/platform-admin/support-cases", landmark: h1("Support Workspace") },
  { file: "platform-admin-users.html", access: "platform", mainApi: "/api/platform-admin/platform-admin-users", landmark: h1("Platform Admin Management") }
];

let server;

test.beforeAll(async () => {
  server = await startServer();
});

test.afterAll(async () => {
  if (server) await new Promise(resolve => server.close(resolve));
});

// Service workers would fetch outside the route handlers; the DNS rule is a second wall behind them.
test.use({
  serviceWorkers: "block",
  launchOptions: { args: ["--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"] }
});

function apiResponse(entry, url) {
  return (entry.api || {})[url.pathname] || COMMON_API[url.pathname] || ok({});
}

function offOriginResponse(url) {
  if (url.startsWith("https://unpkg.com/lucide")) return { body: LUCIDE_SHIM };
  const match = VENDORED.find(([pattern]) => pattern.test(url));
  const file = match && path.join(VENDOR_DIR, match[1]);
  return file && fs.existsSync(file) ? { path: file } : null;
}

// Aborts or locally answers every off-origin request. `unexpected` lists hosts outside
// THIRD_PARTY; `leaked` lists requests that bypassed the route. Both must stay empty.
async function guardNetwork(context, entry) {
  const intercepted = new Set();
  const unexpected = [];
  const apiPaths = [];
  const issued = [];
  context.on("request", request => issued.push(request.url()));
  await context.routeWebSocket(url => url.origin !== ORIGIN, ws => {
    intercepted.add(ws.url());
    unexpected.push(ws.url());
    ws.close();
  });
  await context.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== ORIGIN) {
      intercepted.add(request.url());
      if (!THIRD_PARTY.has(url.host)) unexpected.push(request.url());
      const local = offOriginResponse(request.url());
      if (!local) return route.abort();
      return route.fulfill({ status: 200, contentType: "application/javascript", headers: { "Access-Control-Allow-Origin": "*" }, ...local });
    }
    if (url.pathname.startsWith("/api/")) {
      apiPaths.push(url.pathname);
      const { status, body } = apiResponse(entry, url);
      return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    }
    if (entry.route && url.pathname === entry.route) {
      return route.fulfill({ response: await route.fetch({ url: `${ORIGIN}/${entry.file}` }) });
    }
    return route.continue();
  });
  return {
    intercepted,
    unexpected,
    apiPaths,
    leaked: () => issued.filter(u => /^(https?|wss?):/.test(u) && !u.startsWith(ORIGIN) && !intercepted.has(u))
  };
}

async function seedSession(page, entry) {
  const signedIn = entry.access === "tenant" || entry.access === "platform";
  const session = {
    ...(signedIn ? { token: "smoke-token", isLoggedIn: "true", selectedBotId: BOT_ID, user: JSON.stringify(TENANT_USER) } : {}),
    ...entry.session
  };
  await page.addInitScript(({ values, platform }) => {
    for (const [key, value] of Object.entries(values)) sessionStorage.setItem(key, value);
    if (platform) localStorage.setItem("platformAdminFlag", "true");
  }, { values: session, platform: entry.access === "platform" });
}

function watchErrors(page, entry, intercepted) {
  const pageErrors = [];
  const consoleErrors = [];
  const allow = entry.consoleAllow || [];
  page.on("pageerror", error => pageErrors.push(error.message));
  page.on("console", message => {
    if (message.type() !== "error") return;
    const text = message.text();
    const source = message.location().url;
    // The guard's own work surfaces as these two messages; they are not page behaviour.
    if (text.startsWith("Failed to load resource") && intercepted.has(source)) return;
    const sri = /^Failed to find a valid digest in the 'integrity' attribute for resource '([^']+)'/.exec(text);
    if (sri && intercepted.has(sri[1])) return;
    if (allow.some(rule => rule.pattern.test(text) && (!rule.url || rule.url.test(source)))) return;
    consoleErrors.push(text);
  });
  return { pageErrors, consoleErrors };
}

test("network guard blocks an unlisted host and reports it as unexpected", async ({ page }) => {
  const probe = "https://example.com/smoke-leak-probe";
  const guard = await guardNetwork(page.context(), PAGES.find(p => p.file === "privacy.html"));
  await page.goto("/privacy.html");
  const outcome = await page.evaluate(url => fetch(url).then(() => "reached", () => "blocked"), probe);
  expect(outcome).toBe("blocked");
  // Every page test asserts `unexpected` is empty, so this request would fail any of them.
  expect(guard.unexpected).toEqual([probe]);
  expect(guard.leaked()).toEqual([]);
});

// Top-level page files in dir, named as the .html URL they serve; a missing folder is empty.
function pageUrls(dir, ext, { skipUnderscore = false } = {}) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true })
    .filter(d => d.isFile() && d.name.endsWith(ext) && !(skipUnderscore && d.name.startsWith("_")))
    .map(d => d.name.slice(0, -ext.length) + ".html");
}

test("every page, legacy or migrated, is covered by the smoke table", () => {
  const legacy = pageUrls(path.resolve(__dirname, "../../frontend"), ".html");
  // Astro does not route files that start with "_".
  const migrated = pageUrls(path.resolve(__dirname, "../../web/src/pages"), ".astro", { skipUnderscore: true });
  // A page is legacy or migrated, never both: a duplicate is a move that kept the legacy file.
  expect(legacy.filter(file => migrated.includes(file))).toEqual([]);
  expect(PAGES.map(p => p.file).sort()).toEqual([...legacy, ...migrated].sort());
  // Every page states its main API, or null with the reason it has none.
  expect(PAGES.filter(p => p.mainApi === undefined).map(p => p.file)).toEqual([]);
});

// Every file under dir, as a /-separated path relative to it; a missing folder is empty.
function filesUnder(dir, prefix = "") {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(d => d.isDirectory()
    ? filesUnder(path.join(dir, d.name), `${prefix}${d.name}/`)
    : [`${prefix}${d.name}`]);
}

test("no web/public asset shadows a legacy frontend/ file", () => {
  // Serving is dist-first (app/frontend_files.py), so a copy in web/public would silently win at the
  // same URL while the Python suite keeps reading frontend/. An asset lives in exactly one place.
  const legacy = path.resolve(__dirname, "../../frontend");
  const assets = filesUnder(path.resolve(__dirname, "../../web/public"));
  expect(assets.length).toBeGreaterThan(0);  // a moved or renamed web/public must not pass with nothing checked
  const shadowed = assets.filter(file => fs.existsSync(path.join(legacy, file)));
  expect(shadowed).toEqual([]);
});

// An attribute by its exact name: "(^|space)name", so data-src= or data-type= never counts as src= or type=.
const hasAttr = (attrs, name, value = "") => new RegExp(`(?:^|\\s)${name}\\s*=\\s*["']?${value}`, "i").test(attrs);

test("every built page loads its scripts from files", () => {
  // CSP rule for migrated pages: no inline script. JSON-LD is data, not script, so it may stay inline.
  const dist = path.resolve(__dirname, "../../web/dist");
  const built = filesUnder(dist).filter(name => name.endsWith(".html"));  // nested pages too
  expect(built.length).toBeGreaterThan(0);
  const inline = built.flatMap(name => [...fs.readFileSync(path.join(dist, name), "utf8").matchAll(/<script\b([^>]*)>/gi)]
    .map(match => match[1])
    .filter(attrs => !hasAttr(attrs, "src") && !hasAttr(attrs, "type", "application/ld\\+json"))
    .map(attrs => `${name}: <script${attrs}>`));
  expect(inline).toEqual([]);
});

// The AppLayout frame (F2 design, section 5): the shell in one fixed order, loaded from its URLs.
const SHELL_CSS = ["assets/css/shared-glass.css", "assets/css/dashboard-control-room.css",
  "assets/css/control-room-motion.css", "assets/css/app-preferences.css"];
const SHELL_SCRIPTS = [
  ["assets/js/theme-boot.js", false], ["assets/js/shared-ui.js", false], ["assets/js/kw-a11y.js", false],
  ["assets/js/auth.js", false], ["assets/js/require-login.js", false], ["sidebar-component.js", false],
  ["assets/js/resilient-load.js", false], ["assets/js/control-room-motion.js", true],
  ["https://unpkg.com/lucide@1.31.0/dist/umd/lucide.js", true], ["assets/js/app-preferences.js", true]
];

test("pages on AppLayout load the shared shell in the fixed order", async ({ request }) => {
  const pagesDir = path.resolve(__dirname, "../../web/src/pages");
  // Routed page files only (no sub-folders, no "_" files); the import may omit ".astro".
  const adopters = pageUrls(pagesDir, ".astro", { skipUnderscore: true })
    .filter(file => /from\s+["']\.\.\/layouts\/AppLayout(?:\.astro)?["']/
      .test(fs.readFileSync(path.join(pagesDir, file.replace(/\.html$/, ".astro")), "utf8")));
  expect(adopters).toEqual(expect.arrayContaining(["pricing.html", "geo-provider-comparison.html", "analysis.html", "behaviour.html", "billing.html", "bookings.html", "bots.html", "broadcast.html", "conversations.html", "crm.html", "geo-analysis.html", "index.html", "integration.html", "meta_templates.html", "new_prompt.html", "profile.html", "support.html", "team.html"]));
  // The lucide tag must carry the same pin as the sidebar's own fallback loader.
  const sidebarSri = /script\.integrity = '([^']+)'/.exec(fs.readFileSync(path.resolve(__dirname, "../../frontend/sidebar-component.js"), "utf8"))[1];
  for (const file of adopters) {
    const html = await (await request.get(`/${file}`)).text();
    const tags = [...html.matchAll(/<script\b([^>]*)>/gi)].map(m => m[1]);
    const attr = (attrs, name) => (new RegExp(`(?:^|\\s)${name}="([^"]*)"`).exec(attrs) || [])[1];
    const adminOnly = /<AppLayout\b[^>]*\badminOnly(?:\s|[=>])/.test(fs.readFileSync(path.join(pagesDir, file.replace(/\.html$/, ".astro")), "utf8"));
    const sources = tags.map(attrs => attr(attrs, "src"));
    expect(sources.filter(src => src === "assets/js/require-admin-or-owner.js"), file).toHaveLength(adminOnly ? 1 : 0);
    if (adminOnly) expect(sources[sources.indexOf("assets/js/require-login.js") + 1], file).toBe("assets/js/require-admin-or-owner.js");
    const shell = tags.filter(attrs => SHELL_SCRIPTS.some(([src]) => attr(attrs, "src") === src))
      .map(attrs => [attr(attrs, "src"), /(?:^|\s)defer(?=[\s=>]|$)/.test(attrs)]);
    expect(shell, file).toEqual(SHELL_SCRIPTS);
    const lucide = tags.find(attrs => attr(attrs, "src") === SHELL_SCRIPTS[8][0]);
    expect(attr(lucide, "integrity"), file).toBe(sidebarSri);
    expect(attr(lucide, "crossorigin"), file).toBe("anonymous");
    const css = [...html.matchAll(/<link\b[^>]*\brel="stylesheet"[^>]*\bhref="([^"]+)"/gi)].map(m => m[1])
      .filter(href => SHELL_CSS.includes(href));
    expect(css, file).toEqual(SHELL_CSS);
    // Page CSS (slot "head") sits after the shell CSS and before app-preferences.css, so it wins at equal specificity.
    const local = [...html.matchAll(/<link\b[^>]*\brel="stylesheet"[^>]*\bhref="([^"]+)"/gi)].map(m => m[1])
      .filter(href => !/^https?:/.test(href));
    for (const href of local.filter(href => !SHELL_CSS.includes(href))) {
      expect(local.indexOf(href), `${file}: ${href}`).toBeGreaterThan(local.indexOf("assets/css/control-room-motion.css"));
      expect(local.indexOf(href), `${file}: ${href}`).toBeLessThan(local.indexOf("assets/css/app-preferences.css"));
    }
    // The control-room type: Geist, JetBrains Mono and Space Grotesk in one Google Fonts stylesheet.
    const fonts = [...html.matchAll(/<link\b[^>]*\bhref="(https:\/\/fonts\.googleapis\.com\/css2\?[^"]+)"/gi)].map(m => m[1]);
    // Bots also loads its legacy stylesheet for JetBrains Mono 600.
    expect(fonts, file).toHaveLength(file === "bots.html" ? 2 : 1);
    for (const family of ["family=Geist", "family=JetBrains+Mono", "family=Space+Grotesk"]) expect(fonts[0], file).toContain(family);
    // "dashboard-page" first; a page may append its own classes (AppLayout's bodyClass).
    expect(html, file).toMatch(/<body class="dashboard-page(?: [^"]+)?">\s*<chatbot-sidebar><\/chatbot-sidebar>/);
    if (file === "profile.html") {
      // Replaces test_profile_redesign_frontend.py's shared focus CSS, stylesheet-order and body-class pins.
      // Content and external page-script pins stay in Python via page_source_path.
      expect(adminOnly).toBe(false);
      expect(html).toContain('<title>Profile | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page">');
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/profile.css", SHELL_CSS[3]]);
      expect(sources.at(-1)).toBe("assets/js/profile.js");
      expect(html.indexOf('src="assets/js/profile.js"')).toBeGreaterThan(html.indexOf('id="pro-announce"'));
      expect(html).toContain('code to <span id="pro-delete-email">');
      expect(html).toContain('pattern="[0-9]{6}"');
    }
    if (file === "billing.html") {
      // Replaces test_profile_frontend_labels.py::TestProfileJavaScriptSyntax's inline-script pin:
      // billing.html renders for tenant access below checks parsing/runtime errors; the page keeps only external scripts.
      expect(adminOnly).toBe(false);
      expect(html).toContain('<title>Billing | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page">');
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/billing.css", SHELL_CSS[3]]);
      expect(sources.at(-1)).toBe("assets/js/billing.js");
      expect(html.indexOf('src="assets/js/billing.js"')).toBeGreaterThan(html.indexOf('id="bl-order-dismiss"'));
      expect(html).not.toMatch(/<script\b(?![^>]*\bsrc=)[^>]*>\s*\S/i);
      expect(html).toContain('<title id="bl-gauge-a11y">Included AI credit remaining this period</title>');
      // Both backdrops remain outside main, directly under body.
      const afterMain = html.slice(html.indexOf("</main>") + "</main>".length);
      expect(afterMain).toMatch(/^\s*(?:<!--[\s\S]*?-->\s*)?<div class="kw-backdrop" id="bl-confirm">/);
      expect(afterMain).toMatch(/<\/div>\s*<\/div>\s*<div class="kw-backdrop" id="bl-order-modal">/);
      expect(afterMain).toMatch(/<\/div>\s*<\/div>\s*<script src="assets\/js\/billing\.js"><\/script>\s*<\/body>/);
    }
    if (file === "index.html") {
      // Replaces test_dashboard_control_room_frontend.py::test_dashboard_uses_stitch_control_room_design_contract
      // shell CSS, three font-family and exact body-class pins; the common checks above pin CSS and fonts.
      expect(adminOnly).toBe(false);
      expect(html).toContain('<title>Dashboard | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page">');
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/dashboard-overview.css",
        "assets/css/bot-setup-journey.css", "assets/css/product-tour.css", SHELL_CSS[3]]);
      const pageHead = [...html.matchAll(/<(?:link|script)\b[^>]*(?:href|src)="(assets\/(?:css|js)\/(?:dashboard-overview|bot-setup-journey|product-tour)\.[^"]+)"[^>]*>/gi)]
        .map(m => [m[1], /(?:^|\s)defer(?=[\s=>]|$)/.test(m[0])]);
      expect(pageHead).toEqual([["assets/css/dashboard-overview.css", false],
        ["assets/css/bot-setup-journey.css", false], ["assets/js/bot-setup-journey.js", true],
        ["assets/css/product-tour.css", false], ["assets/js/product-tour.js", true]]);
      expect(sources.filter(src => /^https?:/.test(src))).toEqual([SHELL_SCRIPTS[8][0]]);
      expect(sources.at(-1)).toBe("assets/js/index.js");
      expect(html).toMatch(/<\/main>\s*<script src="assets\/js\/index\.js"><\/script>\s*<\/body>/);
    }
    if (file === "bots.html") {
      // Replaces the sidebar script and mount pins in test_bots_chatbot_limit_frontend.py
      // and test_tenant_account_menu_frontend.py. The shared shell check above pins the script order.
      expect(html.match(/<chatbot-sidebar><\/chatbot-sidebar>/g)).toHaveLength(1);
      expect(adminOnly).toBe(false);
      expect(html).toContain('<title>Bots | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page">');
      expect(fonts[1]).toBe("https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=JetBrains+Mono:wght@500;600&family=Space+Grotesk:wght@500;600;700&display=swap");
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/product-tour.css", SHELL_CSS[3]]);
      // fetchBots() can finish before deferred scripts run and calls omnexaTour.offer().
      const tour = tags.filter(attrs => attr(attrs, "src") === "assets/js/product-tour.js");
      expect(tour).toHaveLength(1);
      expect(attr(tour[0], "data-resume")).toBe("manual");
      expect(tour[0]).not.toMatch(/\s(?:async|defer|type="module")(?=[\s=>]|$)/i);
      expect(sources.indexOf("assets/js/product-tour.js")).toBeLessThan(sources.indexOf("assets/js/bots.js"));
    }
    if (file === "conversations.html") {
      // Replaces test_conversations_frontend.py's shell CSS, font and body pins on the served page.
      // The inbox source still bans Lucide/unpkg; only AppLayout's SRI-checked script is allowed here.
      expect(adminOnly).toBe(false);
      expect(html).toContain('<title>Conversations | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page">');
      expect(html).not.toContain("family=Outfit");
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/conversations.css",
        "assets/css/product-tour.css", SHELL_CSS[3]]);
      const head = html.slice(0, html.indexOf("</head>"));
      const pageHead = [...head.matchAll(/<(?:link|script)\b[^>]*(?:href|src)="(assets\/(?:css\/(?:conversations|product-tour)\.css|js\/product-tour\.js))"[^>]*>/gi)]
        .map(m => [m[1], /(?:^|\s)defer(?=[\s=>]|$)/.test(m[0])]);
      expect(pageHead).toEqual([["assets/css/conversations.css", false],
        ["assets/css/product-tour.css", false], ["assets/js/product-tour.js", true]]);
      expect(sources.filter(src => /^https?:/.test(src))).toEqual([SHELL_SCRIPTS[8][0]]);
      expect(html).toMatch(/<\/main>\s*<script src="assets\/js\/conversations\.js"><\/script>\s*<\/body>/);
    }
    if (file === "integration.html") {
      // Replaces test_publish_frontend.py's shell CSS, fonts, body class and external-script pins.
      // The common shell checks cover the three fonts, login/admin order and Lucide's pin and SRI.
      expect(adminOnly).toBe(true);
      expect(html).toContain('<title>Publish your bot | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page">');
      expect(html).not.toContain("family=Outfit");
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/publish.css",
        "assets/css/bot-setup-journey.css", "assets/css/product-tour.css", SHELL_CSS[3]]);
      const pageHead = [...html.matchAll(/<(?:link|script)\b[^>]*(?:href|src)="(assets\/(?:css\/(?:publish|bot-setup-journey|product-tour)\.css|js\/(?:bot-setup-journey|product-tour|qrcode-gen|control-room-motion)\.js))"[^>]*>/gi)]
        .map(m => [m[1], /(?:^|\s)defer(?=[\s=>]|$)/.test(m[0])]);
      expect(pageHead).toEqual([["assets/css/publish.css", false],
        ["assets/css/bot-setup-journey.css", false], ["assets/js/bot-setup-journey.js", true],
        ["assets/css/product-tour.css", false], ["assets/js/product-tour.js", true],
        ["assets/js/qrcode-gen.js", true], ["assets/js/control-room-motion.js", true]]);
      expect(sources.filter(src => /^https?:/.test(src))).toEqual([SHELL_SCRIPTS[8][0]]);
      expect(html).toMatch(/id="pub-announce"><\/p>\s*<script src="assets\/js\/integration\.js"><\/script>\s*<\/body>/);
    }
    if (file === "new_prompt.html") {
      // Replaces test_frontend_metadata.py's title/favicon coverage for this migrated page;
      // the common metadata test below pins the favicon. Python content/script pins remain
      // in test_knowledge_ui_display_consistency.py and test_persona_derivation.py.
      expect(adminOnly).toBe(true);
      expect(html).toContain('<title>Bot Configuration | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page">');
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/bot-config.css",
        "assets/css/bot-setup-journey.css", "assets/css/product-tour.css", SHELL_CSS[3]]);
      const pageHead = [...html.matchAll(/<(?:link|script)\b[^>]*(?:href|src)="(assets\/(?:css|js)\/(?:bot-config|bot-setup-journey|product-tour|industry-template)\.[^"]+)"[^>]*>/gi)]
        .map(m => [m[1], /(?:^|\s)defer(?=[\s=>]|$)/.test(m[0])]);
      expect(pageHead).toEqual([["assets/css/bot-config.css", false],
        ["assets/css/bot-setup-journey.css", false], ["assets/js/bot-setup-journey.js", true],
        ["assets/css/product-tour.css", false], ["assets/js/product-tour.js", true],
        ["assets/js/industry-template.js", true]]);
      expect(sources.filter(src => /^https?:/.test(src))).toEqual([SHELL_SCRIPTS[8][0]]);
      expect(sources.at(-1)).toBe("assets/js/new_prompt.js");
      expect(html).toMatch(/<\/div>\s*<script src="assets\/js\/new_prompt\.js"><\/script>\s*<\/body>/);
    }
    if (file === "support.html") {
      // Replaces test_platform_admin_frontend.py's sidebar/login pins and
      // test_tenant_account_menu_frontend.py's shared CSS/scripts, sidebar/login and remote-script pins.
      // The common shell checks above cover shared-glass.css, shared-ui.js, auth.js and sidebar-component.js.
      expect(adminOnly).toBe(false);
      expect(html).toContain('<title>Support | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page">');
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/support.css", SHELL_CSS[3]]);
      expect(sources.filter(src => /^https?:/.test(src))).toEqual([SHELL_SCRIPTS[8][0]]);
      expect(fs.readFileSync(path.resolve(__dirname, "../../web/public/assets/js/require-login.js"), "utf8")).toContain("requireLogin();");
      expect(sources.at(-1)).toBe("assets/js/support.js");
      expect(html).toMatch(/<\/main>\s*<script src="assets\/js\/support\.js"><\/script>\s*<\/body>/);
    }
    if (file === "analysis.html") {
      // Preserves the legacy head, admin gate, body class and end-script order on the built page.
      // Content and layout-script pins stay in test_analysis_layout_frontend.py via page_source_path.
      expect(adminOnly).toBe(true);
      expect(html).toContain('<title>Analysis | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page analysis-page">');
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/analysis.css", SHELL_CSS[3]]);
      expect(sources.slice(-3)).toEqual(["assets/js/analysis-tuition.js", "assets/js/analysis-layout.js", "assets/js/analysis.js"]);
      expect(html.indexOf('src="assets/js/analysis-tuition.js"')).toBeGreaterThan(html.indexOf('id="tuition-bookings"'));
    }
    if (file === "bookings.html") {
      // Replaces test_bookings_frontend.py's shell order, resilient-load and CSS/external-script pins.
      // AppLayout intentionally puts preferences after page CSS and adds the pinned, deferred lucide.
      expect(adminOnly).toBe(false);
      expect(html).toContain('<title>Bookings | Omnexa</title>');
      expect(html).toContain('<body class="dashboard-page bookings-page">');
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/bookings.css", SHELL_CSS[3]]);
      expect(sources.filter(src => /^https?:/.test(src))).toEqual([SHELL_SCRIPTS[8][0]]);
      expect(sources.at(-2)).toBe("assets/js/bookings.js");
      expect(sources.at(-1)).toBe("assets/js/bookings-availability.js");
      expect(html.indexOf('src="assets/js/resilient-load.js"')).toBeLessThan(html.indexOf('src="assets/js/bookings.js"'));
      expect(html.indexOf('src="assets/js/bookings.js"')).toBeGreaterThan(html.indexOf('id="av-package-modal"'));
    }
    if (file === "broadcast.html") {
      // Replaces test_broadcast_templates_frontend.py's four shell/style/logic/keyboard tests.
      // Shared CSS, fonts, keyboard helper and login/admin order are pinned above;
      // "every built page loads its scripts from files" replaces the inline-script exception.
      expect(html).toContain("dashboard-icon");
      expect(html).not.toContain("family=Outfit");
      expect(html).not.toContain("#050b18");
      expect(html).not.toMatch(/<style\b/i);
      expect(html.slice(html.indexOf(">", html.indexOf("<html")) + 1)).not.toMatch(/\bstyle\s*=/i);
      expect(html).toContain('<body class="dashboard-page">');
      expect(adminOnly).toBe(true);
      expect(html).toContain('<title>Broadcast | Omnexa</title>');
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/whatsapp-preview.css",
        "assets/css/broadcast.css", SHELL_CSS[3]]);
      expect(sources.at(-1)).toBe("assets/js/broadcast.js");
      expect(html.indexOf('src="assets/js/broadcast.js"')).toBeGreaterThan(html.indexOf('id="bc-confirm"'));
    }
    if (file === "meta_templates.html") {
      // Replaces test_broadcast_templates_frontend.py's shell/inline-style pins.
      expect(html).not.toContain("family=Outfit");
      expect(html).not.toMatch(/<style\b/i);
      expect(html.slice(html.indexOf(">", html.indexOf("<html")) + 1)).not.toMatch(/\bstyle\s*=/i);
      expect(html).toContain('<body class="dashboard-page">');
      expect(adminOnly).toBe(true);
      expect(html).toContain('<title>Message Templates | Omnexa</title>');
      expect(local).toEqual([...SHELL_CSS.slice(0, 3), "assets/css/whatsapp-preview.css",
        "assets/css/meta-templates.css", SHELL_CSS[3]]);
      expect(sources.at(-1)).toBe("assets/js/meta-templates.js");
      expect(html.indexOf('src="assets/js/meta-templates.js"')).toBeGreaterThan(html.indexOf('id="mt-confirm"'));
    }
  }
});

// tests/test_frontend_metadata.py reads frontend/ only, so the served head (built or legacy) is checked here.
test("every page serves one Omnexa title and the shared favicon", async ({ request }) => {
  for (const { file } of PAGES) {
    const response = await request.get(`/${file}`);
    expect(response.status(), file).toBe(200);
    const head = /<head\b[^>]*>([\s\S]*?)(?:<\/head>|<body\b|$)/i.exec(await response.text());
    expect(head, file).not.toBeNull();
    const titles = [...head[1].matchAll(/<title\b[^>]*>([\s\S]*?)<\/title>/gi)].map(m => m[1]);
    expect(titles, file).toHaveLength(1);
    expect(titles[0], file).toContain("Omnexa");
    const icons = head[1].match(/<link\b(?=[^>]*\brel="icon")(?=[^>]*\bhref="favicon\.svg")(?=[^>]*\btype="image\/svg\+xml")[^>]*>/gi);
    expect(icons, file).toHaveLength(1);
  }
});

// The Python suite stays Node-free, so the built legal pages are checked whole here.
test("legal pages are served with their last section", async ({ request }) => {
  for (const [file, lastSection] of [["privacy.html", 'id="en-s21"'], ["terms.html", 'id="t-s17"']]) {
    const response = await request.get(`/${file}`);
    expect(response.status(), file).toBe(200);
    expect(await response.text(), file).toContain(lastSection);
  }
});

for (const entry of PAGES) {
  test(`${entry.file} renders for ${entry.access} access`, async ({ page }) => {
    if (entry.vendor) {
      test.skip(VENDORED.some(([, file]) => !fs.existsSync(path.join(VENDOR_DIR, file))),
        `needs local React, ReactDOM and vis copies in ${VENDOR_DIR}`);
    }
    const guard = await guardNetwork(page.context(), entry);
    const errors = watchErrors(page, entry, guard.intercepted);
    await seedSession(page, entry);
    const docPath = entry.route || `/${entry.file}`;
    const documentResponse = page.waitForResponse(r => r.request().isNavigationRequest() && new URL(r.url()).pathname === docPath);

    await page.goto(docPath + (entry.query || ""));
    expect((await documentResponse).status()).toBe(200);
    if (entry.lands) await page.waitForURL(url => url.pathname === entry.lands);
    // Settle startup requests so errors thrown while rendering their responses are caught.
    await page.waitForLoadState("networkidle");

    await expect(entry.landmark(page)).toBeVisible();
    expect(new URL(page.url()).pathname).toBe(entry.lands || docPath);
    if (entry.mainApi) {
      const isMain = p => (typeof entry.mainApi === "string" ? p === entry.mainApi : entry.mainApi.test(p));
      expect(guard.apiPaths.some(isMain),
        `${entry.file} must request ${entry.mainApi}; it requested: ${guard.apiPaths.join(", ") || "nothing"}`).toBe(true);
    }
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
    expect(guard.unexpected).toEqual([]);
    expect(guard.leaked()).toEqual([]);
  });
}
