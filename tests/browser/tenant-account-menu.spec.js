const fs = require("fs");
const path = require("path");
const { expect, test } = require("@playwright/test");
const { servedFile, startServer } = require("./platform-admin-static-server");

const ROOT = path.resolve(__dirname, "..", "..");
// Local copies of React/ReactDOM/Babel/vis, kept by client-journey-server.js; never downloaded here.
const VENDOR_DIR = path.join(ROOT, "output", "client-journey-review", "vendor");
const VENDORED = [
  [/^https:\/\/unpkg\.com\/react@18\//, "react.js"],
  [/^https:\/\/unpkg\.com\/react-dom@18\//, "react-dom.js"],
  [/^https:\/\/unpkg\.com\/@babel\/standalone\//, "babel.js"],
  [/^https:\/\/unpkg\.com\/vis-network\//, "vis.js"]
];
const LUCIDE_STUB = `
  window.lucide = {
    createIcons: function(options) {
      var root = options && options.root ? options.root : document;
      root.querySelectorAll("i[data-lucide]").forEach(function(icon) {
        var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("data-lucide", icon.getAttribute("data-lucide"));
        svg.setAttribute("aria-hidden", icon.getAttribute("aria-hidden") || "true");
        icon.replaceWith(svg);
      });
    }
  };
`;

// The 6 workspace pages; every other sidebar page is bot-scoped (workspacePaths in sidebar-component.js).
const WORKSPACE_PAGES = ["billing.html", "bots.html", "geo-analysis.html", "geo-provider-comparison.html", "pricing.html", "team.html"];

// Top-level page files in dir, named as the .html URL they serve; a missing folder is empty.
function pageNames(dir, ext) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true })
    .filter(entry => entry.isFile() && entry.name.endsWith(ext) && !entry.name.startsWith("_"))
    .map(entry => entry.name.slice(0, -ext.length) + ".html");
}

// Every served page (legacy frontend/ plus migrated web/src/pages), read the way the static server serves
// it. globalSetup has already built web/dist when this runs.
const SERVED_PAGES = [...new Set([
  ...pageNames(path.join(ROOT, "frontend"), ".html"),
  ...pageNames(path.join(ROOT, "web", "src", "pages"), ".astro")
])].sort();
function servedHtml(name) {
  const file = servedFile(`/${name}`);
  return file ? fs.readFileSync(file, "utf8") : "";
}
const SIDEBAR_PAGES = SERVED_PAGES.filter(name => /<chatbot-sidebar[\s>]/.test(servedHtml(name)));

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

async function installTenantSession(page, user = {}) {
  await page.addInitScript(({ userValue }) => {
    if (window.location.pathname.endsWith("/login.html")) return;
    sessionStorage.setItem("token", "fake-tenant-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify(Object.assign({
      id: 123,
      email: "tenant@example.test",
      full_name: "Tenant Operator",
      role: "owner"
    }, userValue)));
    localStorage.setItem("platformAdminFlag", "true");
    sessionStorage.setItem("is_platform_admin", "true");
  }, { userValue: user });
}

// realReact: serve the local React/Babel copies so React-rendered pages (new_linkdocs) mount their sidebar.
async function mockTenantPageApis(page, platformHandler, supportHandler, { realReact = false } = {}) {
  const calls = [];
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("https://unpkg.com/**", route => {
    const match = realReact && VENDORED.find(([pattern]) => pattern.test(route.request().url()));
    if (match) {
      return route.fulfill({ path: path.join(VENDOR_DIR, match[1]), contentType: "application/javascript", headers: { "Access-Control-Allow-Origin": "*" } });
    }
    return route.fulfill({ status: 200, contentType: "application/javascript", body: LUCIDE_STUB });
  });
  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    calls.push({
      method: request.method(),
      path: url.pathname,
      authorization: request.headers().authorization || null
    });
    if (url.pathname === "/api/platform-admin/me") {
      const response = await platformHandler({ request, url, calls });
      if (response && response.abort) {
        await route.abort("failed");
        return;
      }
      await route.fulfill(json(response.status, response.body));
      return;
    }
    if (url.pathname.startsWith("/api/support/requests") && supportHandler) {
      const response = await supportHandler({ request, url, calls });
      await route.fulfill(json(response.status, response.body));
      return;
    }
    await route.fulfill(json(200, { status: "success", data: [] }));
  });
  return calls;
}

async function openTenantPage(page, path, platformHandler = () => ({ status: 403, body: { status: "error", code: "platform_admin_access_denied" } }), user, supportHandler, options) {
  await installTenantSession(page, user);
  const calls = await mockTenantPageApis(page, platformHandler, supportHandler, options);
  await page.goto(path);
  await expect(page.locator("tenant-account-menu")).toHaveCount(1);
  return calls;
}

async function openAccountMenu(page) {
  await page.getByRole("button", { name: "Open account menu" }).click();
}

// bots.html mounts the shared sidebar since 28ff481 (its own rail is gone), so its mobile menu is the sidebar's.
async function openSidebarOnMobile(page) {
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.locator("chatbot-sidebar .sidebar.mobile-open")).toHaveCount(1);
}

async function accountMenuRect(page) {
  return page.locator("tenant-account-menu").evaluate(element => {
    const menu = element.shadowRoot.querySelector(".menu");
    const rect = menu.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height
    };
  });
}

async function accountButtonRect(page) {
  return page.locator("tenant-account-menu").evaluate(element => {
    const button = element.shadowRoot.querySelector(".account-button");
    const rect = button.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height
    };
  });
}

async function accountMenuMetrics(page) {
  return page.locator("tenant-account-menu").evaluate(element => {
    const menu = element.shadowRoot.querySelector(".menu");
    const item = element.shadowRoot.querySelector(".item");
    const svgs = Array.from(element.shadowRoot.querySelectorAll(".item svg[data-lucide]"))
      .map(svg => svg.getAttribute("data-lucide"));
    const menuStyle = getComputedStyle(menu);
    const itemStyle = getComputedStyle(item);
    return {
      menuPosition: menuStyle.position,
      menuPaddingLeft: menuStyle.paddingLeft,
      itemPaddingLeft: itemStyle.paddingLeft,
      icons: svgs
    };
  });
}

async function legacySidebarAccountLinks(page) {
  return page.locator("chatbot-sidebar").evaluate(sidebar => {
    return Array.from(sidebar.querySelectorAll("a, button"))
      .filter(element => {
        const text = (element.textContent || "").trim();
        const href = element.getAttribute("href") || "";
        return (
          (text === "Profile" && /profile\.html/.test(href)) ||
          text === "Logout" ||
          element.classList.contains("logout-link")
        );
      })
      .map(element => ({
        tag: element.tagName.toLowerCase(),
        text: (element.textContent || "").trim(),
        href: element.getAttribute("href") || ""
      }));
  });
}

async function elementRect(page, selector) {
  return page.locator(selector).evaluate(element => {
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height
    };
  });
}

function intersects(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function expectInsideViewport(rect, viewport) {
  expect(rect.left).toBeGreaterThanOrEqual(0);
  expect(rect.top).toBeGreaterThanOrEqual(0);
  expect(rect.right).toBeLessThanOrEqual(viewport.width);
  expect(rect.bottom).toBeLessThanOrEqual(viewport.height);
}

// The dashboard header no longer carries a standalone date pill; the
// timestamp lives inline in the status line under the bot name, alongside the
// Bot settings trigger. The readability and collision rules are unchanged.
async function dateReadability(page) {
  return page.locator(".dash-statusline").evaluate(line => {
    const text = line.querySelector("#date-display");
    const textRect = text.getBoundingClientRect();
    return {
      width: line.getBoundingClientRect().width,
      clientWidth: line.clientWidth,
      scrollWidth: line.scrollWidth,
      textWidth: textRect.width,
      lineCount: text.getClientRects().length,
      text: text.textContent
    };
  });
}

function expectReadableDate(metrics, width) {
  expect(metrics.scrollWidth, `status line is clipped at ${width}px`).toBeLessThanOrEqual(metrics.clientWidth + 1);
  expect(metrics.textWidth, `date text collapsed into one-character lines at ${width}px`).toBeGreaterThanOrEqual(70);
  expect(metrics.lineCount, `date text wraps too aggressively at ${width}px`).toBeLessThanOrEqual(2);
  expect(metrics.text, `date text is empty at ${width}px`).toMatch(/\S/);
}

test.describe("tenant account menu shared placement", () => {
  test("bots page uses the shared account menu with Profile, Support, and Logout", async ({ page }) => {
    const calls = await openTenantPage(page, "/bots.html");

    await expect(page.locator(".header-actions tenant-account-menu")).toHaveCount(0);
    await expect(page.locator("chatbot-sidebar .sidebar-bottom-section tenant-account-menu")).toHaveCount(1);
    await expect(page.locator("tenant-account-menu")).toHaveCount(1);
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Profile" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Support" })).toHaveAttribute("href", /support\.html$/);
    await expect(page.getByRole("menuitem", { name: "Logout" })).toBeVisible();
    expect(calls.filter(call => call.path === "/api/platform-admin/me")).toHaveLength(1);
    await expect(page.getByRole("menuitem", { name: "Platform Administration", includeHidden: true })).toBeHidden();
  });

  test("representative bot dashboard gets account menu in sidebar and sidebar omits local Profile and Logout links", async ({ page }) => {
    await openTenantPage(page, "/index.html?bot_id=42");

    await expect(page.locator("chatbot-sidebar tenant-account-menu")).toHaveCount(1);
    await expect(page.locator(".tenant-account-menu-floating")).toHaveCount(0);
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Profile" })).toHaveAttribute("href", /profile\.html\?bot_id=42$/);
    expect(await legacySidebarAccountLinks(page)).toEqual([]);
  });

  test("representative non-dashboard sidebar page gets the shared account menu", async ({ page }) => {
    await openTenantPage(page, "/profile.html?bot_id=42");

    await expect(page.locator("chatbot-sidebar tenant-account-menu")).toHaveCount(1);
    await expect(page.locator(".tenant-account-menu-floating")).toHaveCount(0);
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Profile" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Support" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Logout" })).toBeVisible();
    expect(await legacySidebarAccountLinks(page)).toEqual([]);
  });

  test("shared-sidebar account submenu uses sidebar alignment and renders Lucide SVG icons", async ({ page }) => {
    // AppLayout and the sidebar fallback load SRI-pinned Lucide, which no stub response can satisfy.
    // Seed Lucide before the page runs so the sidebar takes its "lucide already loaded" path.
    await page.addInitScript({ content: LUCIDE_STUB });
    await openTenantPage(page, "/index.html?bot_id=42");

    await openAccountMenu(page);
    const metrics = await accountMenuMetrics(page);
    expect(metrics.menuPosition).toBe("static");
    expect(metrics.menuPaddingLeft).toBe("8px");
    expect(metrics.itemPaddingLeft).toBe("10px");
    expect(metrics.icons).toEqual(expect.arrayContaining(["user-circle", "circle-help", "log-out"]));
  });

  test("bots account submenu uses the same Lucide SVG icon rendering", async ({ page }) => {
    // bots.html is on AppLayout now, so its lucide tag is SRI-pinned too: seed Lucide like the test above.
    await page.addInitScript({ content: LUCIDE_STUB });
    await openTenantPage(page, "/bots.html");

    await openAccountMenu(page);
    const metrics = await accountMenuMetrics(page);
    expect(metrics.menuPosition).toBe("static");
    expect(metrics.menuPaddingLeft).toBe("8px");
    expect(metrics.icons).toEqual(expect.arrayContaining(["user-circle", "circle-help", "log-out"]));
  });

  test("opens by keyboard and closes with Escape and outside click at desktop and narrow widths", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await openTenantPage(page, "/bots.html");

    await page.getByRole("button", { name: "Open account menu" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("menu")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toBeHidden();

    await page.setViewportSize({ width: 360, height: 720 });
    await openSidebarOnMobile(page);
    await openAccountMenu(page);
    await expect(page.getByRole("menu")).toBeVisible();
    await page.mouse.click(5, 5);
    await expect(page.getByRole("menu")).toBeHidden();
  });

  test("bots mobile navigation exposes the account menu at narrow widths", async ({ page }) => {
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: 760 });
      await openTenantPage(page, "/bots.html");

      await expect(page.locator("tenant-account-menu")).toHaveCount(1);
      await expect(page.locator(".header-actions tenant-account-menu")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible();
      await openSidebarOnMobile(page);
      await expect(page.getByRole("link", { name: "Bots" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Team" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Billing" })).toBeVisible();

      await openAccountMenu(page);
      await expect(page.getByRole("menuitem", { name: "Profile" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Support" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Logout" })).toBeVisible();
      const rect = await accountMenuRect(page);
      expect(rect.left).toBeGreaterThanOrEqual(0);
      expect(rect.right).toBeLessThanOrEqual(width);
      expect(rect.top).toBeGreaterThanOrEqual(0);
    }
  });

  test("mobile sidebar exposes the sidebar account menu inside the viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 760 });
    await openTenantPage(page, "/index.html?bot_id=42");

    await page.getByRole("button", { name: "Open menu" }).click();
    await expect(page.locator("chatbot-sidebar .sidebar.mobile-open")).toHaveCount(1);
    await openAccountMenu(page);
    await expect(page.getByRole("menu")).toBeVisible();
    let rect = await accountMenuRect(page);
    expect(rect.left).toBeGreaterThanOrEqual(0);
    expect(rect.right).toBeLessThanOrEqual(390);
    expect(rect.top).toBeGreaterThanOrEqual(0);
    await page.keyboard.press("Escape");

    await openAccountMenu(page);
    await expect(page.getByRole("menu")).toBeVisible();
    rect = await accountMenuRect(page);
    expect(rect.left).toBeGreaterThanOrEqual(0);
    expect(rect.right).toBeLessThanOrEqual(390);
  });

  test("expanded mobile navigation scrolls without covering the account footer", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 540 });
    await openTenantPage(page, "/index.html?bot_id=42");
    await page.getByRole("button", { name: "Open menu" }).click();
    await page.locator("chatbot-sidebar details").evaluateAll(groups => {
      groups.forEach(group => { group.open = true; });
    });
    const lastLink = page.locator("chatbot-sidebar .nav-list a").last();
    await lastLink.scrollIntoViewIfNeeded();
    const linkRect = await lastLink.boundingBox();
    const footerRect = await elementRect(page, "chatbot-sidebar .sidebar-bottom-section");
    expect(linkRect.y + linkRect.height).toBeLessThanOrEqual(footerRect.top + 1);
    await openAccountMenu(page);
    expectInsideViewport(await accountMenuRect(page), page.viewportSize());
  });

  test("dashboard header and account menu do not overlap across responsive widths", async ({ page }) => {
    for (const width of [1440, 1280, 1024, 768, 390, 320]) {
      const height = width <= 390 ? 760 : 720;
      await page.setViewportSize({ width, height });
      await openTenantPage(page, "/index.html?bot_id=42");
      await expect(page.locator("#dashboard-title")).toBeVisible();
      await expect(page.locator(".dash-statusline")).toBeVisible();

      const viewport = page.viewportSize();
      const accountButton = await accountButtonRect(page);
      const statusline = await elementRect(page, ".dash-statusline");
      const title = await elementRect(page, "#dashboard-title");
      // The Bot settings trigger sits at the header's right edge. The account
      // row now lives in the sidebar, so it should never collide with header
      // content in either its compact or expanded form.
      const settings = await elementRect(page, "#dash-menu-trigger");
      const dateMetrics = await dateReadability(page);
      const titleToStatusGap = statusline.top - title.bottom;

      expectInsideViewport(accountButton, viewport);
      expectInsideViewport(statusline, viewport);
      expectInsideViewport(title, viewport);
      expectInsideViewport(settings, viewport);
      expect(titleToStatusGap, `status line drifts from the title at ${width}px`).toBeGreaterThanOrEqual(0);
      expect(titleToStatusGap, `status line drifts from the title at ${width}px`).toBeLessThanOrEqual(48);
      expectReadableDate(dateMetrics, width);
      expect(intersects(accountButton, statusline), `closed account button overlaps status line at ${width}px`).toBe(false);
      expect(intersects(accountButton, settings), `closed account button overlaps Bot settings at ${width}px`).toBe(false);

      if (width <= 768) {
        await page.getByRole("button", { name: "Open menu" }).click();
        await expect(page.locator("chatbot-sidebar .sidebar.mobile-open")).toHaveCount(1);
      }
      await openAccountMenu(page);
      const accountMenu = await accountMenuRect(page);
      const openStatusline = await elementRect(page, ".dash-statusline");
      const openTitle = await elementRect(page, "#dashboard-title");
      const openDateMetrics = await dateReadability(page);
      expectInsideViewport(accountMenu, viewport);
      expectInsideViewport(openStatusline, viewport);
      expectInsideViewport(openTitle, viewport);
      expectReadableDate(openDateMetrics, width);
      // The open dropdown is allowed to cover the Bot settings trigger beside
      // it — that is what a dropdown does, and closing it restores access. It
      // must never cover page content, which is the rule asserted here.
      expect(intersects(accountMenu, openStatusline), `open account menu overlaps status line at ${width}px`).toBe(false);
      expect(intersects(accountMenu, openTitle), `open account menu overlaps the bot name at ${width}px`).toBe(false);
      await page.keyboard.press("Escape");
      const closedAgainStatusline = await elementRect(page, ".dash-statusline");
      const closedAgainTitle = await elementRect(page, "#dashboard-title");
      const closedAgainGap = closedAgainStatusline.top - closedAgainTitle.bottom;
      expect(closedAgainGap, `header stays displaced after menu closes at ${width}px`).toBeGreaterThanOrEqual(0);
      expect(closedAgainGap, `header stays displaced after menu closes at ${width}px`).toBeLessThanOrEqual(48);

      if (width <= 768) {
        await expect(page.locator("chatbot-sidebar .sidebar.mobile-open")).toHaveCount(1);
        await expect(page.getByRole("button", { name: "Open account menu" })).toBeVisible();
        const mobileAccountButton = await accountButtonRect(page);
        expectInsideViewport(mobileAccountButton, viewport);
      }
    }
  });

  test("late-rendered sidebar pages receive exactly one sidebar account menu", async ({ page }) => {
    await installTenantSession(page);
    await mockTenantPageApis(page, () => ({
      status: 403,
      body: { status: "error", code: "platform_admin_access_denied" }
    }));
    await page.goto("/new_linkdocs.html?bot_id=42");
    await expect(page.locator("tenant-account-menu")).toHaveCount(0);

    await page.evaluate(() => {
      const sidebar = document.createElement("chatbot-sidebar");
      document.body.appendChild(sidebar);
    });
    await expect(page.locator("tenant-account-menu")).toHaveCount(1);
    await expect(page.locator("chatbot-sidebar tenant-account-menu")).toHaveCount(1);

    await page.evaluate(() => {
      const sidebar = document.createElement("chatbot-sidebar");
      document.body.appendChild(sidebar);
    });
    await expect(page.locator("tenant-account-menu")).toHaveCount(1);
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Profile" })).toBeVisible();
  });

  test("public and platform pages do not receive the tenant account menu", async ({ page }) => {
    await installTenantSession(page);
    await mockTenantPageApis(page, () => ({
      status: 403,
      body: { status: "error", code: "platform_admin_access_denied" }
    }));

    for (const path of ["/landing.html", "/login.html", "/platform-admin.html"]) {
      await page.goto(path);
      await expect(page.locator("tenant-account-menu")).toHaveCount(0);
    }
  });
});

test.describe("tenant support page", () => {
  test("opens from the shared account menu and renders bounded help and request content", async ({ page }) => {
    await openTenantPage(page, "/bots.html");

    await openAccountMenu(page);
    await page.getByRole("menuitem", { name: "Support" }).click();
    await expect(page).toHaveURL(/support\.html$/);
    await expect(page.getByRole("heading", { name: "Support", exact: true })).toBeVisible();
    await expect(page.getByRole("searchbox")).toBeVisible();
    await expect(page.getByRole("group", { name: "Filter articles by category" })).toBeVisible();
    await page.getByRole("button", { name: "Talk to a human", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Contact the support team" })).toBeVisible();
    await expect(page.locator("#support-request-form")).toHaveCount(1);
    await expect(page.locator("#sup-category option")).toHaveText([
      "Technical", "Account", "Chatbot", "Integration", "Billing question", "AI credits", "Other"
    ]);
    await expect(page.locator("tenant-account-menu")).toHaveCount(1);
    await expect(page.locator("input[type=file]")).toHaveCount(0);
    await expect(page.locator("#support-request-form").getByRole("button", { name: /message|email|billing|impersonat|export|chart/i })).toHaveCount(0);
  });

  test("direct authenticated navigation works and renders safe account context", async ({ page }) => {
    await openTenantPage(page, "/support.html", undefined, {
      full_name: "Tenant Operator",
      email: "tenant@example.test",
      role: "member"
    });

    await expect(page.getByRole("heading", { name: "Support", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Talk to a human", exact: true }).click();
    await expect(page.locator("#sup-trail-account")).toHaveText("Tenant Operator");
    await expect(page.locator("#sup-trail-email")).toHaveText("tenant@example.test");
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Support" })).toBeVisible();
  });

  test("submits only the legacy support fields without urgency or escalation context", async ({ page }) => {
    const submissions = [];
    const supportHandler = async ({ request }) => {
      if (request.method() === "POST") {
        const payload = request.postDataJSON();
        submissions.push(payload);
        return {
          status: 200,
          body: { status: "success", data: { request_id: 31 } }
        };
      }
      return { status: 200, body: { status: "success", data: { requests: [] } } };
    };
    await openTenantPage(page, "/support.html", undefined, undefined, supportHandler);
    await page.getByRole("button", { name: "Talk to a human", exact: true }).click();
    await expect(page.locator("#sup-urgency")).toHaveCount(0);
    await page.locator("#sup-category").selectOption("technical");
    await page.locator("#sup-subject").fill("Cannot connect a number");
    await page.locator("#sup-description").fill("The connect button does nothing.");
    await page.getByRole("button", { name: "Send to support", exact: true }).click();
    await expect(page.locator("#support-request-form")).toContainText("reference #31");
    expect(submissions).toEqual([{
      category: "technical",
      title: "Cannot connect a number",
      redacted_description: "The connect button does nothing."
    }]);
  });

  test("renders tenant support history and public replies without internal fields", async ({ page }) => {
    await page.addInitScript(() => {
      window.__tenantSupportXss = false;
    });
    const supportHandler = async ({ request, url }) => {
      if (request.method() !== "GET") {
        return { status: 405, body: { status: "error" } };
      }
      if (url.pathname === "/api/support/requests") {
        return {
          status: 200,
          body: {
            status: "success",
            data: {
              requests: [{
                request_id: 31,
                category: "technical",
                status: "converted",
                created_at: "2026-08-06T00:00:00+00:00"
              }]
            }
          }
        };
      }
      return {
        status: 200,
        body: {
          status: "success",
          data: {
            request: {
              request_id: 31,
              category: "technical",
              status: "converted",
              title: "<img src=x onerror=window.__tenantSupportXss=true>",
              redacted_description: "Safe tenant description",
              created_at: "2026-08-06T00:00:00+00:00",
              updated_at: "2026-08-06T00:01:00+00:00"
            },
            replies: [{
              reply_id: 44,
              request_id: 31,
              author_type: "platform_admin",
              redacted_body: "<script>window.__tenantSupportXss=true</script>",
              redacted_note: "Internal note must not render",
              author_platform_admin_user_id: 3,
              created_at: "2026-08-06T00:02:00+00:00"
            }]
          }
        }
      };
    };
    await openTenantPage(page, "/support.html", undefined, undefined, supportHandler);
    await page.getByRole("button", { name: "#31 Support request converted" }).click();
    await expect(page.getByText("<img src=x onerror=window.__tenantSupportXss=true>")).toBeVisible();
    await expect(page.getByText("<script>window.__tenantSupportXss=true</script>")).toBeVisible();
    await expect(page.getByText("Internal note must not render")).toHaveCount(0);
    await expect(page.getByText("author_platform_admin_user_id")).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__tenantSupportXss)).toBe(false);
  });

  test("unauthenticated direct navigation redirects to login", async ({ page }) => {
    await mockTenantPageApis(page, () => ({
      status: 403,
      body: { status: "error", code: "platform_admin_access_denied" }
    }));

    await page.goto("/support.html");
    await expect(page).toHaveURL(/login\.html$/);
  });

  test("account name and email with HTML-like text render as text only", async ({ page }) => {
    await page.addInitScript(() => {
      window.__supportInjected = false;
    });
    await openTenantPage(page, "/support.html", undefined, {
      full_name: "<img src=x onerror=window.__supportInjected=true>",
      email: "<script>window.__supportInjected=true</script>",
      role: "owner"
    });

    await page.getByRole("button", { name: "Talk to a human", exact: true }).click();
    await expect(page.locator("#sup-trail-account")).toHaveText("<img src=x onerror=window.__supportInjected=true>");
    await expect(page.locator("#sup-trail-email")).toHaveText("<script>window.__supportInjected=true</script>");
    await expect(page.locator("#sup-trail-account img")).toHaveCount(0);
    await expect(page.locator("#sup-trail-email script")).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__supportInjected)).toBe(false);
  });

  test("support page remains usable at mobile width with no duplicate menu", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 760 });
    await openTenantPage(page, "/support.html");

    await expect(page.locator("tenant-account-menu")).toHaveCount(1);
    await page.getByRole("button", { name: "Open menu" }).click();
    await expect(page.locator("chatbot-sidebar .sidebar.mobile-open")).toHaveCount(1);
    await openAccountMenu(page);
    await expect(page.getByRole("menu")).toBeVisible();
    const rect = await accountMenuRect(page);
    expect(rect.left).toBeGreaterThanOrEqual(0);
    expect(rect.right).toBeLessThanOrEqual(390);
    await expect(page.getByRole("menuitem", { name: "Support" })).toBeVisible();
  });

  test("all rendered Support quick links resolve to local static pages", async ({ page }) => {
    await openTenantPage(page, "/support.html");
    const hrefs = await page.locator("[data-support-link]").evaluateAll(links =>
      links.map(link => link.getAttribute("href"))
    );

    expect(hrefs.length).toBeGreaterThan(0);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    for (const href of hrefs) {
      expect(href).toMatch(/^[a-z_]+\.html$/);
      const response = await page.request.get(new URL(href, page.url()).toString());
      expect(response.status(), href).toBe(200);
    }
  });
});

test.describe("tenant account menu platform-admin discovery", () => {
  test("platform option is hidden before first open and 200 reveals it from one live check", async ({ page }) => {
    const calls = await openTenantPage(page, "/bots.html", () => ({
      status: 200,
      body: { status: "success", data: { platform_admin: { id: 1 } } }
    }));

    await expect(page.getByRole("menuitem", { name: "Platform Administration", includeHidden: true })).toBeHidden();
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Platform Administration" })).toBeVisible();
    expect(calls.filter(call => call.path === "/api/platform-admin/me")).toHaveLength(1);
    expect(calls.find(call => call.path === "/api/platform-admin/me").authorization).toBe("Bearer fake-tenant-token");
  });

  for (const scenario of [
    { name: "403 keeps platform option hidden", status: 403 },
    { name: "503 keeps platform option hidden without raw details", status: 503 }
  ]) {
    test(scenario.name, async ({ page }) => {
      await openTenantPage(page, "/bots.html", () => ({
        status: scenario.status,
        body: { status: "error", message: "raw backend detail that must not render" }
      }));

      await openAccountMenu(page);
      await expect(page.getByRole("menuitem", { name: "Platform Administration", includeHidden: true })).toBeHidden();
      await expect(page.locator("body")).not.toContainText("raw backend detail");
    });
  }

  test("network failure keeps platform option hidden and can be retried on a later open", async ({ page }) => {
    let attempts = 0;
    const calls = await openTenantPage(page, "/bots.html", () => {
      attempts += 1;
      if (attempts === 1) return { abort: true };
      return { status: 200, body: { status: "success", data: { platform_admin: { id: 1 } } } };
    });

    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Platform Administration", includeHidden: true })).toBeHidden();
    await page.keyboard.press("Escape");
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Platform Administration" })).toBeVisible();
    expect(calls.filter(call => call.path === "/api/platform-admin/me")).toHaveLength(2);
  });

  test("401 follows logout behavior", async ({ page }) => {
    await openTenantPage(page, "/bots.html", () => ({
      status: 401,
      body: { status: "error", code: "authentication_required" }
    }));

    await openAccountMenu(page);
    await expect(page).toHaveURL(/login\.html$/);
    const token = await page.evaluate(() => sessionStorage.getItem("token"));
    expect(token).toBeNull();
  });

  test("repeated opens do not duplicate pending platform checks", async ({ page }) => {
    let resolvePlatform;
    const calls = await openTenantPage(page, "/bots.html", () => new Promise(resolve => {
      resolvePlatform = () => resolve({ status: 200, body: { status: "success", data: { platform_admin: { id: 1 } } } });
    }));

    await openAccountMenu(page);
    await page.mouse.click(5, 5);
    await openAccountMenu(page);
    expect(calls.filter(call => call.path === "/api/platform-admin/me")).toHaveLength(1);
    resolvePlatform();
    await expect(page.getByRole("menuitem", { name: "Platform Administration" })).toBeVisible();
  });

  test("page reload performs a new live check and tenant role/local flags do not reveal the option", async ({ page }) => {
    let allow = false;
    const calls = await openTenantPage(page, "/bots.html", () => ({
      status: allow ? 200 : 403,
      body: allow
        ? { status: "success", data: { platform_admin: { id: 1 } } }
        : { status: "error", code: "platform_admin_access_denied" }
    }), { role: "admin" });

    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Platform Administration", includeHidden: true })).toBeHidden();
    allow = true;
    await page.reload();
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Platform Administration" })).toBeVisible();
    expect(calls.filter(call => call.path === "/api/platform-admin/me")).toHaveLength(2);
  });

  test("clicking Platform Administration navigates there and the platform page performs its own /me request", async ({ page }) => {
    const calls = await openTenantPage(page, "/bots.html", () => ({
      status: 200,
      body: { status: "success", data: { user: {}, platform_admin: { id: 1 } } }
    }));

    await openAccountMenu(page);
    await page.getByRole("menuitem", { name: "Platform Administration" }).click();
    await expect(page).toHaveURL(/platform-admin\.html$/);
    await expect(page.locator("body")).toContainText("Platform Administration");
    expect(calls.filter(call => call.path === "/api/platform-admin/me").length).toBeGreaterThanOrEqual(2);
  });
});

test.describe("tenant account menu navigation and read-only boundary", () => {
  test("Profile, Logout, and Return to Tenant App keep their intended destinations", async ({ page }) => {
    await openTenantPage(page, "/bots.html", () => ({
      status: 200,
      body: { status: "success", data: { user: {}, platform_admin: { id: 1 } } }
    }));

    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Profile" })).toHaveAttribute("href", /profile\.html$/);
    await expect(page.getByRole("menuitem", { name: "Support" })).toHaveAttribute("href", /support\.html$/);
    await page.getByRole("menuitem", { name: "Logout" }).click();
    await expect(page).toHaveURL(/login\.html$/);
  });

  test("platform-admin Return to Tenant App still points to bots.html", async ({ page }) => {
    await installTenantSession(page);
    await mockTenantPageApis(page, () => ({
      status: 403,
      body: { status: "error", code: "platform_admin_access_denied" }
    }));
    await page.goto("/platform-admin.html");

    await expect(page.getByRole("link", { name: "Return to Tenant App" })).toHaveAttribute("href", "bots.html");
  });

  test("menu persists no platform authorization and exposes no platform write controls", async ({ page }) => {
    await openTenantPage(page, "/bots.html", () => ({
      status: 200,
      body: { status: "success", data: { platform_admin: { id: 1 } } }
    }));

    await openAccountMenu(page);
    const storage = await page.evaluate(() => ({
      localKeys: Object.keys(localStorage),
      sessionKeys: Object.keys(sessionStorage)
    }));
    expect(storage.localKeys).not.toContain("platform_admin");
    expect(storage.sessionKeys).not.toContain("platform_admin");
    await expect(page.locator("body")).not.toContainText("Suspend Company");
    await expect(page.locator("body")).not.toContainText("Credit Adjustment");
    await expect(page.locator("body")).not.toContainText("Impersonate");
    await expect(page.locator("body")).not.toContainText("Export");
  });
});

test.describe("shared shell on every sidebar page", () => {
  test("20 served pages mount the shared sidebar: 6 workspace pages and 14 bot pages", () => {
    // 45 served pages minus the 25 without the tenant shell: 4 public (landing, privacy, terms,
    // widget-chat), 5 sign-in pages, 6 redirect stubs and 10 platform-admin pages.
    expect(SIDEBAR_PAGES).toHaveLength(20);
    expect(SIDEBAR_PAGES).toEqual(expect.arrayContaining(WORKSPACE_PAGES));
  });

  for (const name of SIDEBAR_PAGES) {
    const workspace = WORKSPACE_PAGES.includes(name);
    test(`${name} mounts one shared sidebar in ${workspace ? "workspace" : "bot"} scope`, async ({ page }) => {
      const needsReact = /unpkg\.com\/react@/.test(servedHtml(name));
      test.skip(needsReact && !fs.existsSync(path.join(VENDOR_DIR, "babel.js")), `needs the local React/Babel copies in ${VENDOR_DIR}`);
      if (needsReact) test.slow();
      const loaded = new Set();
      page.on("response", response => {
        if (response.ok()) loaded.add(new URL(response.url()).pathname);
      });
      await page.addInitScript(() => sessionStorage.setItem("selectedBotId", "7"));

      // A bot in the URL and in the session: workspace pages must still render workspace scope.
      await openTenantPage(page, `/${name}?bot_id=7`, undefined, undefined, undefined, { realReact: true });

      const sidebar = page.locator("chatbot-sidebar");
      await expect(sidebar).toHaveCount(1);
      await expect(sidebar.locator(".sidebar-bottom-section tenant-account-menu")).toHaveCount(1);
      // One shell implementation, loaded from its current URLs rather than copied into the page.
      expect([...loaded]).toEqual(expect.arrayContaining(["/sidebar-component.js", "/assets/js/shared-ui.js", "/assets/js/auth.js"]));
      expect(await page.evaluate(() => [
        typeof authenticatedFetch,
        Boolean(customElements.get("chatbot-sidebar")),
        Boolean(customElements.get("tenant-account-menu"))
      ])).toEqual(["function", true, true]);
      if (workspace) {
        await expect(sidebar.getByRole("link", { name: "Overview", exact: true })).toHaveCount(0);
        await expect(sidebar.getByRole("link", { name: "Conversations", exact: true })).toHaveCount(0);
        // The sidebar's own links only (light DOM). The account menu's Profile link keeps the selected bot on
        // purpose (preserve-bot-query), because profile.html is a bot-scope page.
        expect(await sidebar.evaluate(element => Array.from(element.querySelectorAll("a[href]"))
          .map(link => link.getAttribute("href")).filter(href => href.includes("bot_id=")))).toEqual([]);
      } else {
        await expect(sidebar.getByRole("link", { name: "Overview", exact: true })).toHaveAttribute("href", "index.html?bot_id=7");
        await expect(sidebar.getByRole("link", { name: "Conversations", exact: true })).toHaveAttribute("href", "conversations.html?bot_id=7");
      }
    });
  }
});
