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

const identity = {
  user: {
    id: 9001,
    email: "operator@example.test",
    full_name: "Test Operator",
    status: "active"
  },
  platform_admin: {
    id: 7001,
    is_active: true,
    created_at: "2026-07-01T00:00:00+00:00",
    updated_at: "2026-07-02T00:00:00+00:00"
  }
};

const company = {
  id: 42,
  company_name: "Example Tenant <script>window.__xss = true</script>",
  business_type: "Education",
  status: "active",
  contact_email: "tenant@example.test",
  contact_phone: "+60000000000",
  created_at: "2026-07-01T00:00:00+00:00",
  updated_at: "2026-07-02T00:00:00+00:00"
};

const subscriptionSummary = {
  company: { id: 42 },
  subscription: {
    status: "trialing",
    plan: {
      code: "pro",
      name: "Pro",
      billing_interval: "monthly",
      currency: "MYR",
      price: "39.00"
    },
    current_period_start: "2026-07-01T00:00:00+00:00",
    current_period_end: "2026-08-01T00:00:00+00:00",
    trial_ends_at: "2026-07-15T00:00:00+00:00"
  }
};

const aiCreditSummary = {
  company: { id: 42 },
  period: {
    start: "2026-07-01T00:00:00+00:00",
    end: "2026-08-01T00:00:00+00:00"
  },
  credit_balance: {
    initialized: true,
    included_balance_micro_myr: 100000000,
    topup_balance_micro_myr: 25000000,
    total_balance_micro_myr: 125000000
  },
  usage: {
    request_count: 4,
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    provider_cost_micro_usd: 12345
  },
  charges: {
    transaction_count: 2,
    customer_charge_micro_myr: 1000000,
    uncovered_charge_micro_myr: 0,
    provider_cost_micro_usd: 12345
  }
};

function success(data) {
  return { status: 200, body: { status: "success", data } };
}

function failure(status, code, message = "Safe public message.") {
  return { status, body: { status: "error", code, message } };
}

function companyList(total, companies = [], extra = {}) {
  const limit = extra.limit || 25;
  const offset = extra.offset || 0;
  return {
    companies,
    pagination: {
      limit,
      offset,
      returned: companies.length,
      total,
      has_more: Boolean(extra.hasMore)
    },
    sort: { by: extra.sortBy || "created_at", order: extra.sortOrder || "desc" },
    filters: { search: null, status: extra.status || null }
  };
}

async function installSession(page, user = { role: "owner", platformAdminFlag: true }) {
  await page.addInitScript(({ userValue }) => {
    if (!window.location.pathname.includes("platform-admin")) return;
    sessionStorage.setItem("token", "fake-platform-token");
    sessionStorage.setItem("user", JSON.stringify(userValue));
    sessionStorage.setItem("isLoggedIn", "true");
    localStorage.setItem("platformAdminFlag", "true");
  }, { userValue: user });
}

async function mockPlatformApi(page, handler) {
  const calls = [];
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("**/api/platform-admin/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    calls.push({
      method: request.method(),
      path: url.pathname,
      search: url.search,
      authorization: request.headers().authorization || null
    });
    const response = await handler({ request, url, calls });
    await route.fulfill({
      status: response.status,
      contentType: "application/json",
      body: JSON.stringify(response.body)
    });
  });
  return calls;
}

async function openPlatformPage(page, path, handler, user) {
  await installSession(page, user);
  const calls = await mockPlatformApi(page, handler);
  await page.goto(path);
  return calls;
}

function defaultHandler({ url }) {
  if (url.pathname === "/api/platform-admin/me") return success(identity);
  if (url.pathname === "/api/platform-admin/companies") {
    if (url.searchParams.get("status") === "active") {
      return success(companyList(1, [], { limit: 1, status: "active" }));
    }
    if (url.searchParams.get("status") === "inactive") {
      return success(companyList(0, [], { limit: 1, status: "inactive" }));
    }
    return success(companyList(2, [company], { hasMore: true }));
  }
  if (url.pathname === "/api/platform-admin/companies/42") return success(company);
  if (url.pathname === "/api/platform-admin/companies/42/subscription") {
    return success(subscriptionSummary);
  }
  if (url.pathname === "/api/platform-admin/companies/42/ai-credit-usage") {
    return success(aiCreditSummary);
  }
  return failure(404, "company_not_found");
}

test.describe("platform-admin access gate", () => {
  test("hides platform content while /me is pending and starts page data only after success", async ({ page }) => {
    let releaseMe;
    const meGate = new Promise(resolve => {
      releaseMe = resolve;
    });
    const calls = await openPlatformPage(page, "/platform-admin.html", async ({ url }) => {
      if (url.pathname === "/api/platform-admin/me") {
        await meGate;
        return success(identity);
      }
      return defaultHandler({ url });
    });

    await expect(page.getByRole("heading", { name: "Checking access" })).toBeVisible();
    await expect(page.locator("#platform-app")).toBeHidden();
    expect(calls.map(call => call.path)).toEqual(["/api/platform-admin/me"]);

    releaseMe();
    await expect(page.getByRole("heading", { name: "Platform dashboard" })).toBeVisible();
    await expect(page.getByText("Platform Administration")).toBeVisible();
    expect(calls.filter(call => call.path === "/api/platform-admin/companies")).toHaveLength(3);
    expect(calls.every(call => call.method === "GET")).toBe(true);
    expect(calls.every(call => call.authorization === "Bearer fake-platform-token")).toBe(true);
  });

  for (const scenario of [
    { name: "401 logs out through existing behavior", response: failure(401, "invalid_token"), text: "login.html", unauthenticated: true },
    { name: "403 shows Access Denied", response: failure(403, "platform_admin_access_denied"), text: "Access Denied" },
    { name: "503 shows Temporarily Unavailable", response: failure(503, "platform_admin_data_unavailable", "Supabase service_role raw detail"), text: "Temporarily Unavailable" }
  ]) {
    test(scenario.name, async ({ page }) => {
      await openPlatformPage(page, "/platform-admin.html", ({ url }) => {
        if (url.pathname === "/api/platform-admin/me") return scenario.response;
        return defaultHandler({ url });
      });
      if (scenario.unauthenticated) {
        await expect(page).toHaveURL(/login\.html$/);
        await expect.poll(() => page.evaluate(() => sessionStorage.getItem("token"))).toBeNull();
      } else {
        await expect(page.getByText(scenario.text)).toBeVisible();
      }
      await expect(page.getByText("Supabase service_role raw detail")).toHaveCount(0);
      await expect(page.getByText("Platform dashboard")).toHaveCount(0);
    });
  }

  test("network failure shows unavailable state without raw details", async ({ page }) => {
    await installSession(page);
    await page.route("**/api/platform-admin/me", route => route.abort("failed"));
    await page.goto("/platform-admin.html");
    await expect(page.getByRole("heading", { name: "Temporarily Unavailable" })).toBeVisible();
    await expect(page.getByText("failed")).toHaveCount(0);
  });

  test("manual retry rechecks /me before page data", async ({ page }) => {
    let meCount = 0;
    const calls = await openPlatformPage(page, "/platform-admin.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/me") {
        meCount += 1;
        return meCount === 1
          ? failure(503, "platform_admin_data_unavailable")
          : success(identity);
      }
      return defaultHandler({ url });
    });

    await expect(page.getByRole("heading", { name: "Temporarily Unavailable" })).toBeVisible();
    await page.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByRole("heading", { name: "Platform dashboard" })).toBeVisible();
    expect(calls[1].path).toBe("/api/platform-admin/me");
    expect(calls.slice(2).every(call => call.path === "/api/platform-admin/companies")).toBe(true);
  });
});

test.describe("platform-admin state clearing and lifecycle", () => {
  test("403 after protected data clears sensitive content", async ({ page }) => {
    let listCount = 0;
    await openPlatformPage(page, "/platform-admin-companies.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies") {
        listCount += 1;
        return listCount === 1
          ? success(companyList(2, [company], { hasMore: true }))
          : failure(403, "platform_admin_access_denied");
      }
      return defaultHandler({ url });
    });

    await expect(page.getByRole("cell", { name: "Example Tenant <script>window.__xss = true</script>" })).toBeVisible();
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Access Denied" })).toBeVisible();
    await expect(page.getByText("Example Tenant")).toHaveCount(0);
  });

  test("503 after protected data clears stale content", async ({ page }) => {
    let listCount = 0;
    await openPlatformPage(page, "/platform-admin-companies.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies") {
        listCount += 1;
        return listCount === 1
          ? success(companyList(2, [company], { hasMore: true }))
          : failure(503, "platform_admin_data_unavailable", "raw backend failure");
      }
      return defaultHandler({ url });
    });

    await expect(page.getByRole("cell", { name: "Example Tenant <script>window.__xss = true</script>" })).toBeVisible();
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Temporarily Unavailable" })).toBeVisible();
    await expect(page.getByText("Example Tenant")).toHaveCount(0);
    await expect(page.getByText("raw backend failure")).toHaveCount(0);
  });

  test("late obsolete responses do not restore cleared content", async ({ page }) => {
    let releaseList;
    const delayedList = new Promise(resolve => {
      releaseList = resolve;
    });
    await openPlatformPage(page, "/platform-admin-companies.html", async ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies") {
        await delayedList;
        return success(companyList(1, [company]));
      }
      return defaultHandler({ url });
    });

    await expect(page.getByText("Loading companies")).toBeVisible();
    await page.evaluate(() => window.PlatformAdminShell.clearPlatformState());
    releaseList();
    await page.waitForTimeout(100);
    await expect(page.getByText("Example Tenant")).toHaveCount(0);
    await expect(page.locator("#platform-app")).toBeHidden();
  });

  test("logout and pagehide clear session state and sensitive DOM", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-companies.html", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("cell", { name: "Example Tenant <script>window.__xss = true</script>" })).toBeVisible();

    await page.getByRole("button", { name: "Logout" }).click();
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem("token"))).toBeNull();

    await openPlatformPage(page, "/platform-admin-companies.html", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("cell", { name: "Example Tenant <script>window.__xss = true</script>" })).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    await expect(page.getByText("Example Tenant")).toHaveCount(0);
  });
});

test.describe("platform-admin dashboard and directory", () => {
  test("dashboard loads intended counts and no write controls", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin.html", ({ url }) => defaultHandler({ url }));
    await expect(page.getByText("Total companies").locator("..").getByText("2")).toBeVisible();
    await expect(page.getByText("Active companies").locator("..").getByText("1")).toBeVisible();
    await expect(page.getByText("Inactive companies").locator("..").getByText("0")).toBeVisible();
    await expect(page.getByText("Internal / Read Only")).toBeVisible();
    await expect(page.getByRole("main").getByText("Test Operator")).toBeVisible();
    await assertReadOnlyBoundary(page);
  });

  test("directory renders safe text and sends expected query parameters", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-companies.html", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("cell", { name: "Example Tenant <script>window.__xss = true</script>" })).toBeVisible();
    await expect(page.locator("script", { hasText: "window.__xss = true" })).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__xss)).toBeUndefined();

    await page.getByLabel("Search companies").fill("school");
    await page.waitForTimeout(400);
    await page.getByLabel("Status").selectOption("active");
    await page.getByLabel("Sort field").selectOption("company_name");
    await page.getByLabel("Sort order").selectOption("asc");
    await page.getByLabel("Page size").selectOption("50");

    const listUrls = calls
      .filter(call => call.path === "/api/platform-admin/companies")
      .map(call => new URL("http://test" + call.search));
    expect(listUrls.some(url => url.searchParams.get("search") === "school")).toBe(true);
    expect(listUrls.some(url => url.searchParams.get("status") === "active")).toBe(true);
    expect(listUrls.some(url => url.searchParams.get("sort_by") === "company_name")).toBe(true);
    expect(listUrls.some(url => url.searchParams.get("sort_order") === "asc")).toBe(true);
    expect(listUrls.some(url => url.searchParams.get("limit") === "50")).toBe(true);
  });

  test("directory empty and unavailable states are distinct, and detail link uses positive ID", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-companies.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies") return success(companyList(0, []));
      return defaultHandler({ url });
    });
    await expect(page.getByRole("heading", { name: "No companies found" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Temporarily Unavailable" })).toHaveCount(0);

    await openPlatformPage(page, "/platform-admin-companies.html", ({ url }) => defaultHandler({ url }));
    const href = await page.getByRole("link", { name: "View details" }).first().getAttribute("href");
    expect(href).toBe("platform-admin-company.html?company_id=42");
  });
});

test.describe("platform-admin company detail", () => {
  test("invalid or missing company ID returns before protected detail calls", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-company.html?company_id=0", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "Invalid company" })).toBeVisible();
    expect(calls.map(call => call.path)).toEqual(["/api/platform-admin/me"]);
  });

  test("loads company first, then subscription and AI-credit summaries", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "Example Tenant <script>window.__xss = true</script>" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Subscription" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "AI-credit and usage" })).toBeVisible();
    await expect(page.locator("script", { hasText: "window.__xss = true" })).toHaveCount(0);

    const paths = calls.map(call => call.path);
    expect(paths.indexOf("/api/platform-admin/companies/42")).toBeGreaterThan(paths.indexOf("/api/platform-admin/me"));
    expect(paths.indexOf("/api/platform-admin/companies/42/subscription")).toBeGreaterThan(paths.indexOf("/api/platform-admin/companies/42"));
    expect(paths.indexOf("/api/platform-admin/companies/42/ai-credit-usage")).toBeGreaterThan(paths.indexOf("/api/platform-admin/companies/42"));
  });

  test("404 and secondary failures use fixed states without raw details", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42") return failure(404, "company_not_found");
      return defaultHandler({ url });
    });
    await expect(page.getByRole("heading", { name: "Company Not Found" })).toBeVisible();

    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/subscription") {
        return failure(503, "platform_admin_data_unavailable", "raw Supabase details");
      }
      return defaultHandler({ url });
    });
    await expect(page.getByRole("heading", { name: "Temporarily Unavailable" })).toBeVisible();
    await expect(page.getByText("raw Supabase details")).toHaveCount(0);
  });
});

test.describe("platform-admin navigation and role independence", () => {
  test("return link points to tenant app and tenant role/local flag do not authorize", async ({ page }) => {
    const calls = await openPlatformPage(
      page,
      "/platform-admin.html",
      ({ url }) => defaultHandler({ url }),
      { role: "member", platformAdminFlag: true }
    );
    await expect(page.getByRole("heading", { name: "Platform dashboard" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Return to Tenant App" }).first()).toHaveAttribute("href", "bots.html");
    expect(calls[0].path).toBe("/api/platform-admin/me");
  });

  test("does not expose unsupported read-write controls", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "AI-credit and usage" })).toBeVisible();
    await assertReadOnlyBoundary(page);
  });
});

async function assertReadOnlyBoundary(page) {
  for (const forbidden of [
    "Suspend Company",
    "Manage Users",
    "Change Plan",
    "Cancel Subscription",
    "Adjust Credit",
    "Impersonate",
    "Export",
    "Send Message",
    "Platform Admin Mapping"
  ]) {
    await expect(page.getByRole("button", { name: forbidden })).toHaveCount(0);
    await expect(page.getByRole("link", { name: forbidden })).toHaveCount(0);
  }
  await expect(page.locator("form")).toHaveCount(0);
}
