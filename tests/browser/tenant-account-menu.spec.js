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

async function mockTenantPageApis(page, platformHandler) {
  const calls = [];
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("https://unpkg.com/**", route => route.fulfill({
    status: 200,
    contentType: "application/javascript",
    body: "window.lucide={createIcons:function(){}};"
  }));
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
    await route.fulfill(json(200, { status: "success", data: [] }));
  });
  return calls;
}

async function openTenantPage(page, path, platformHandler = () => ({ status: 403, body: { status: "error", code: "platform_admin_access_denied" } }), user) {
  await installTenantSession(page, user);
  const calls = await mockTenantPageApis(page, platformHandler);
  await page.goto(path);
  await expect(page.locator("tenant-account-menu")).toHaveCount(1);
  return calls;
}

async function openAccountMenu(page) {
  await page.getByRole("button", { name: "Open account menu" }).click();
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

async function datePillReadability(page) {
  return page.locator("#dashboard-date-pill").evaluate(pill => {
    const text = pill.querySelector("#date-display");
    const textRect = text.getBoundingClientRect();
    return {
      width: pill.getBoundingClientRect().width,
      clientWidth: pill.clientWidth,
      scrollWidth: pill.scrollWidth,
      textWidth: textRect.width,
      textHeight: textRect.height,
      lineCount: text.getClientRects().length,
      text: text.textContent
    };
  });
}

function expectReadableDate(metrics, width) {
  expect(metrics.width, `date pill is too narrow to read at ${width}px`).toBeGreaterThanOrEqual(90);
  expect(metrics.scrollWidth, `date text is clipped at ${width}px`).toBeLessThanOrEqual(metrics.clientWidth + 1);
  expect(metrics.textWidth, `date text collapsed into one-character lines at ${width}px`).toBeGreaterThanOrEqual(70);
  expect(metrics.lineCount, `date text wraps too aggressively at ${width}px`).toBeLessThanOrEqual(2);
  expect(metrics.text, `date text is empty at ${width}px`).toMatch(/\S/);
}

test.describe("tenant account menu shared placement", () => {
  test("bots page uses the shared account menu with Profile, Support, and Logout", async ({ page }) => {
    const calls = await openTenantPage(page, "/bots.html");

    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Profile" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Support" })).toHaveAttribute("href", /support\.html$/);
    await expect(page.getByRole("menuitem", { name: "Logout" })).toBeVisible();
    expect(calls.filter(call => call.path === "/api/platform-admin/me")).toHaveLength(1);
    await expect(page.getByRole("menuitem", { name: "Platform Administration", includeHidden: true })).toBeHidden();
  });

  test("representative bot dashboard gets account menu outside sidebar and sidebar omits Profile and Logout", async ({ page }) => {
    await openTenantPage(page, "/index.html?bot_id=42");

    await expect(page.locator("chatbot-sidebar tenant-account-menu")).toHaveCount(0);
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Profile" })).toHaveAttribute("href", /profile\.html\?bot_id=42$/);
    await expect(page.locator("chatbot-sidebar")).not.toContainText("Profile");
    await expect(page.locator("chatbot-sidebar")).not.toContainText("Logout");
  });

  test("representative non-dashboard sidebar page gets the shared account menu", async ({ page }) => {
    await openTenantPage(page, "/profile.html?bot_id=42");

    await expect(page.locator("chatbot-sidebar tenant-account-menu")).toHaveCount(0);
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Profile" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Support" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Logout" })).toBeVisible();
    await expect(page.locator("chatbot-sidebar")).not.toContainText("Profile");
    await expect(page.locator("chatbot-sidebar")).not.toContainText("Logout");
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
    await openAccountMenu(page);
    await expect(page.getByRole("menu")).toBeVisible();
    await page.mouse.click(5, 5);
    await expect(page.getByRole("menu")).toBeHidden();
  });

  test("mobile sidebar does not block the floating account menu", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 760 });
    await openTenantPage(page, "/index.html?bot_id=42");

    await openAccountMenu(page);
    await expect(page.getByRole("menu")).toBeVisible();
    let rect = await accountMenuRect(page);
    expect(rect.left).toBeGreaterThanOrEqual(0);
    expect(rect.right).toBeLessThanOrEqual(390);
    expect(rect.top).toBeGreaterThanOrEqual(0);
    await page.keyboard.press("Escape");

    await page.getByRole("button", { name: "Open menu" }).click();
    await expect(page.locator("chatbot-sidebar .sidebar.mobile-open")).toHaveCount(1);
    await openAccountMenu(page);
    await expect(page.getByRole("menu")).toBeVisible();
    rect = await accountMenuRect(page);
    expect(rect.left).toBeGreaterThanOrEqual(0);
    expect(rect.right).toBeLessThanOrEqual(390);
  });

  test("dashboard date pill and account menu do not overlap across responsive widths", async ({ page }) => {
    for (const width of [1440, 1280, 1024, 768, 390, 320]) {
      const height = width <= 390 ? 760 : 720;
      await page.setViewportSize({ width, height });
      await openTenantPage(page, "/index.html?bot_id=42");
      await expect(page.getByRole("heading", { name: /Dashboard/ })).toBeVisible();
      await expect(page.locator("#dashboard-date-pill")).toBeVisible();

      const viewport = page.viewportSize();
      const accountButton = await accountButtonRect(page);
      const datePill = await elementRect(page, "#dashboard-date-pill");
      const title = await elementRect(page, "#dashboard-title");
      const subtitle = await elementRect(page, "#dashboard-subtitle");
      const dateMetrics = await datePillReadability(page);
      const subtitleToDateGap = datePill.top - subtitle.bottom;
      const titleToDateOffset = datePill.top - title.top;

      expectInsideViewport(accountButton, viewport);
      expectInsideViewport(datePill, viewport);
      expectInsideViewport(title, viewport);
      expectInsideViewport(subtitle, viewport);
      expect(subtitleToDateGap, `date pill has excessive subtitle gap at ${width}px`).toBeGreaterThanOrEqual(0);
      expect(subtitleToDateGap, `date pill has excessive subtitle gap at ${width}px`).toBeLessThanOrEqual(48);
      expect(titleToDateOffset, `date pill is displaced too far from dashboard title at ${width}px`).toBeLessThanOrEqual(180);
      expectReadableDate(dateMetrics, width);
      expect(intersects(accountButton, datePill), `closed account button overlaps date pill at ${width}px`).toBe(false);

      await openAccountMenu(page);
      const accountMenu = await accountMenuRect(page);
      const openDatePill = await elementRect(page, "#dashboard-date-pill");
      const openTitle = await elementRect(page, "#dashboard-title");
      const openSubtitle = await elementRect(page, "#dashboard-subtitle");
      const openDateMetrics = await datePillReadability(page);
      expectInsideViewport(accountMenu, viewport);
      expectInsideViewport(openDatePill, viewport);
      expectInsideViewport(openTitle, viewport);
      expectInsideViewport(openSubtitle, viewport);
      expectReadableDate(openDateMetrics, width);
      expect(intersects(accountMenu, openDatePill), `open account menu overlaps date pill at ${width}px`).toBe(false);
      await page.keyboard.press("Escape");
      const closedAgainDatePill = await elementRect(page, "#dashboard-date-pill");
      const closedAgainSubtitle = await elementRect(page, "#dashboard-subtitle");
      const closedAgainGap = closedAgainDatePill.top - closedAgainSubtitle.bottom;
      expect(closedAgainGap, `header stays displaced after menu closes at ${width}px`).toBeGreaterThanOrEqual(0);
      expect(closedAgainGap, `header stays displaced after menu closes at ${width}px`).toBeLessThanOrEqual(48);

      if (width <= 768) {
        await page.getByRole("button", { name: "Open menu" }).click();
        await expect(page.locator("chatbot-sidebar .sidebar.mobile-open")).toHaveCount(1);
        await expect(page.getByRole("button", { name: "Open account menu" })).toBeVisible();
        const mobileAccountButton = await accountButtonRect(page);
        expectInsideViewport(mobileAccountButton, viewport);
      }
    }
  });

  test("late-rendered sidebar pages receive exactly one floating account menu", async ({ page }) => {
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
    await expect(page.getByRole("heading", { name: "Support" })).toBeVisible();
    await expect(page.getByText("Common Help Topics")).toBeVisible();
    await expect(page.getByText("Billing And AI Credits")).toBeVisible();
    await expect(page.getByText("Submit a Support Request")).toBeVisible();
    await expect(page.locator("#support-request-form")).toHaveCount(1);
    await expect(page.locator("#support-request-category option")).toHaveCount(8);
    await expect(page.locator("tenant-account-menu")).toHaveCount(1);
    await expect(page.locator("input[type=file]")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /message|email|billing|impersonat|export|chart/i })).toHaveCount(0);
  });

  test("direct authenticated navigation works and renders safe account context", async ({ page }) => {
    await openTenantPage(page, "/support.html", undefined, {
      full_name: "Tenant Operator",
      email: "tenant@example.test",
      role: "member"
    });

    await expect(page.getByRole("heading", { name: "Support" })).toBeVisible();
    await expect(page.locator("#support-account-name")).toHaveText("Tenant Operator");
    await expect(page.locator("#support-account-email")).toHaveText("tenant@example.test");
    await openAccountMenu(page);
    await expect(page.getByRole("menuitem", { name: "Support" })).toBeVisible();
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

    await expect(page.locator("#support-account-name")).toHaveText("<img src=x onerror=window.__supportInjected=true>");
    await expect(page.locator("#support-account-email")).toHaveText("<script>window.__supportInjected=true</script>");
    await expect(page.locator("#support-account-name img")).toHaveCount(0);
    await expect(page.locator("#support-account-email script")).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__supportInjected)).toBe(false);
  });

  test("support page remains usable at mobile width with no duplicate menu", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 760 });
    await openTenantPage(page, "/support.html");

    await expect(page.locator("tenant-account-menu")).toHaveCount(1);
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
