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

const operationsOverview = {
  generated_at: "2026-07-29T00:00:00+00:00",
  companies: {
    total: 2,
    active: 1,
    inactive: 1
  },
  subscriptions: {
    by_status: {
      trialing: 1,
      active: 1,
      past_due: 1,
      expired: 1,
      cancelled: 0
    },
    by_plan: [
      { code: "free", name: "Free", count: 1 },
      { code: "pro", name: "Pro <img src=x onerror=window.__planXss=true>", count: 1 }
    ]
  },
  attention_companies: [
    {
      company_id: 42,
      company_name: "Example Tenant <script>window.__xss = true</script>",
      company_status: "active",
      subscription_status: "past_due",
      plan_code: "pro",
      plan_name: "Pro <img src=x onerror=window.__planXss=true>",
      status_updated_at: "2026-07-29T00:00:00+00:00",
      current_period_end: "2026-07-28T00:00:00+00:00"
    }
  ]
};

const userList = {
  users: [
    {
      id: 32,
      full_name: "Operator <img src=x onerror=window.__userXss=true>",
      email: "operator@example.test",
      role: "admin",
      status: "active",
      created_at: "2026-07-01T00:00:00+00:00",
      updated_at: "2026-07-02T00:00:00+00:00"
    }
  ],
  pagination: { limit: 25, offset: 0, returned: 1, total: 1, has_more: false },
  sort: { by: "created_at", order: "desc" },
  filters: { search_applied: false }
};

const chatbotList = {
  chatbots: [
    {
      id: 29,
      bot_name: "Bot <svg onload=window.__botXss=true>",
      is_active: true,
      status: "active",
      language: "English",
      tone: "Friendly",
      ai_provider: "openrouter",
      model_name: "deepseek-v4-flash",
      created_at: "2026-07-01T00:00:00+00:00",
      updated_at: "2026-07-02T00:00:00+00:00"
    }
  ],
  pagination: { limit: 25, offset: 0, returned: 1, total: 1, has_more: false },
  sort: { by: "created_at", order: "desc" },
  filters: { search_applied: false, state: "current" }
};

const subscriptionHistory = {
  subscriptions: [
    {
      id: 501,
      status: "past_due",
      plan: {
        code: "pro",
        name: "Pro <img src=x onerror=window.__historyPlanXss=true>"
      },
      pending_plan: null,
      starts_at: null,
      current_period_start: "2026-07-01T00:00:00+00:00",
      current_period_end: "2026-08-01T00:00:00+00:00",
      trial_ends_at: null,
      cancelled_at: null,
      ends_at: null,
      plan_change_effective_at: null,
      cancellation_scheduled_at: null,
      cancellation_effective_at: null,
      status_updated_at: "2026-07-29T00:00:00+00:00",
      created_at: "2026-07-01T00:00:00+00:00",
      updated_at: "2026-07-29T00:00:00+00:00"
    }
  ],
  pagination: { limit: 25, offset: 0, returned: 1, total: 2, has_more: true },
  filters: { status: null, status_applied: false },
  ordering: { by: "created_at", order: "desc", tie_breaker: "id desc" }
};

const aiCreditTransactions = {
  transactions: [
    {
      id: 701,
      transaction_type: "usage_debit<script>window.__transactionTypeXss=true</script>",
      included_delta_micro_myr: -500000,
      topup_delta_micro_myr: null,
      included_balance_after_micro_myr: 9500000,
      topup_balance_after_micro_myr: 2000000,
      customer_charge_micro_myr: null,
      uncovered_charge_micro_myr: 0,
      period_start: null,
      period_end: null,
      created_at: "2026-07-15T12:00:00+00:00"
    }
  ],
  pagination: { limit: 25, offset: 0, returned: 1, total: 2, has_more: true },
  filters: { transaction_type: null },
  ordering: { by: "created_at", order: "desc", tie_breaker: "id desc" }
};

const filteredAiCreditTransactions = {
  transactions: [
    {
      id: 702,
      transaction_type: "usage_debit<img src=x onerror=window.__lateTransactionXss=true>",
      included_delta_micro_myr: -250000,
      topup_delta_micro_myr: 0,
      included_balance_after_micro_myr: 9250000,
      topup_balance_after_micro_myr: 2000000,
      customer_charge_micro_myr: 250000,
      uncovered_charge_micro_myr: 0,
      period_start: "2026-07-01T00:00:00+00:00",
      period_end: "2026-08-01T00:00:00+00:00",
      created_at: "2026-07-16T12:00:00+00:00"
    }
  ],
  pagination: { limit: 25, offset: 0, returned: 1, total: 1, has_more: false },
  filters: { transaction_type: "usage_debit" },
  ordering: { by: "created_at", order: "desc", tie_breaker: "id desc" }
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
  if (url.pathname === "/api/platform-admin/overview") return success(operationsOverview);
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
  if (url.pathname === "/api/platform-admin/companies/42/subscription-history") {
    return success(subscriptionHistory);
  }
  if (url.pathname === "/api/platform-admin/companies/42/ai-credit-usage") {
    return success(aiCreditSummary);
  }
  if (url.pathname === "/api/platform-admin/companies/42/ai-credit-transactions") {
    return success(aiCreditTransactions);
  }
  if (url.pathname === "/api/platform-admin/companies/42/users") {
    return success(userList);
  }
  if (url.pathname === "/api/platform-admin/companies/42/chatbots") {
    return success(chatbotList);
  }
  return failure(404, "company_not_found");
}

function metricCard(page, label) {
  return page.locator(".platform-metric").filter({
    has: page.locator(".platform-metric-label", { hasText: new RegExp(`^${label}$`) })
  });
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
    await expect(page.getByRole("heading", { name: "Platform operations" })).toBeVisible();
    await expect(page.getByText("Platform Administration")).toBeVisible();
    expect(calls.map(call => call.path)).toEqual(["/api/platform-admin/me", "/api/platform-admin/overview"]);
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
    await expect(page.getByRole("heading", { name: "Platform operations" })).toBeVisible();
    expect(calls[1].path).toBe("/api/platform-admin/me");
    expect(calls[2].path).toBe("/api/platform-admin/overview");
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
  test("dashboard loads operations overview and no write controls", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin.html", ({ url }) => defaultHandler({ url }));
    await expect(metricCard(page, "Total companies")).toContainText("2");
    await expect(metricCard(page, "Active companies")).toContainText("1");
    await expect(metricCard(page, "Inactive companies")).toContainText("1");
    await expect(metricCard(page, "Trialing")).toContainText("1");
    await expect(metricCard(page, "Past due")).toContainText("1");
    await expect(page.getByRole("heading", { name: "Subscription status" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Plan distribution" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Companies requiring attention" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Pro <img src=x onerror=window.__planXss=true>" }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Example Tenant <script>window.__xss = true</script>" })).toHaveAttribute("href", "platform-admin-company.html?company_id=42");
    await expect(page.locator("script", { hasText: "window.__xss = true" })).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__xss)).toBeUndefined();
    await expect.poll(() => page.evaluate(() => window.__planXss)).toBeUndefined();
    await expect(page.getByText("Internal / Read Only")).toBeVisible();
    await assertReadOnlyBoundary(page);
  });

  test("dashboard performs one overview request after authorization and handles empty attention", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/overview") {
        return success({ ...operationsOverview, attention_companies: [] });
      }
      return defaultHandler({ url });
    });
    await expect(page.getByText("No past-due or expired companies found.")).toBeVisible();
    expect(calls.map(call => call.path)).toEqual(["/api/platform-admin/me", "/api/platform-admin/overview"]);
    expect(calls.filter(call => call.path === "/api/platform-admin/companies")).toHaveLength(0);
  });

  test("dashboard unavailable and denied refreshes clear previously rendered overview data", async ({ page }) => {
    for (const scenario of [
      { status: 503, code: "platform_admin_data_unavailable", heading: "Temporarily Unavailable" },
      { status: 403, code: "platform_admin_access_denied", heading: "Access Denied" }
    ]) {
      let overviewCount = 0;
      await openPlatformPage(page, "/platform-admin.html", ({ url }) => {
        if (url.pathname === "/api/platform-admin/overview") {
          overviewCount += 1;
          return overviewCount === 1
            ? success(operationsOverview)
            : failure(scenario.status, scenario.code, "raw backend detail");
        }
        return defaultHandler({ url });
      });
      await expect(page.getByRole("heading", { name: "Platform operations" })).toBeVisible();
      await expect(page.getByText("Example Tenant")).toBeVisible();

      await page.reload();
      await expect(page.getByRole("heading", { name: scenario.heading })).toBeVisible();
      await expect(page.getByText("Example Tenant")).toHaveCount(0);
      await expect(page.getByText("Total companies")).toHaveCount(0);
      await expect(page.getByText("raw backend detail")).toHaveCount(0);
    }
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

test.describe("platform-admin support workspace", () => {
  test("support navigation and page data appear only after platform authorization", async ({ page }) => {
    let releaseMe;
    const meGate = new Promise(resolve => {
      releaseMe = resolve;
    });
    const calls = await openPlatformPage(page, "/platform-admin-support.html", async ({ url }) => {
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
    await expect(page.getByRole("heading", { name: "Support Workspace" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Support" })).toHaveAttribute("href", "platform-admin-support.html");
    expect(calls.map(call => call.path)).toEqual(["/api/platform-admin/me", "/api/platform-admin/overview"]);
    expect(calls.every(call => call.method === "GET")).toBe(true);
  });

  test("renders attention companies safely and links to existing investigation page", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-support.html", ({ url }) => defaultHandler({ url }));

    await expect(page.getByRole("heading", { name: "Support Workspace" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Companies requiring attention" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Example Tenant <script>window" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Pro <img src=x onerror=window.__planXss=true>" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Past due subscription" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Investigate" }).first()).toHaveAttribute("href", "platform-admin-company.html?company_id=42");
    expect(await page.evaluate(() => window.__xss || window.__planXss || false)).toBe(false);
    expect(calls.map(call => call.path)).toEqual(["/api/platform-admin/me", "/api/platform-admin/overview"]);
  });

  test("shows empty attention and bounded company lookup states", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-support.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/overview") {
        return success({ ...operationsOverview, attention_companies: [] });
      }
      if (url.pathname === "/api/platform-admin/companies") {
        return success(companyList(0, []));
      }
      return defaultHandler({ url });
    });

    await expect(page.getByText("No companies currently require attention.")).toBeVisible();
    await expect(page.getByText("Company results will appear after an intentional search.")).toBeVisible();
    await page.getByLabel("Company name or ID").fill("missing tenant");
    await page.getByRole("button", { name: "Search companies" }).click();
    await expect(page.getByText("No company search results found.")).toBeVisible();
    const companyCalls = calls.filter(call => call.path === "/api/platform-admin/companies");
    expect(companyCalls).toHaveLength(1);
    expect(companyCalls[0].search).toContain("limit=25");
    expect(companyCalls[0].search).toContain("offset=0");
    expect(companyCalls[0].search).toContain("sort_by=company_name");
    expect(companyCalls[0].search).toContain("sort_order=asc");
  });

  test("company lookup renders safe results and investigate navigates to company detail", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-support.html", ({ url }) => defaultHandler({ url }));

    await page.getByLabel("Company name or ID").fill("Example <img src=x onerror=window.__lookupXss=true>");
    await page.getByRole("button", { name: "Search companies" }).click();
    await expect(page.getByRole("cell", { name: "Example Tenant <script>window" }).nth(1)).toBeVisible();
    await expect(page.getByText("Showing 1 of 2 matching companies.")).toBeVisible();
    expect(await page.evaluate(() => window.__lookupXss || window.__xss || false)).toBe(false);
    const lookupCall = calls.find(call => call.path === "/api/platform-admin/companies");
    expect(lookupCall.search).toContain("search=Example");
    await page.getByRole("link", { name: "Investigate" }).last().click();
    await expect(page).toHaveURL(/platform-admin-company\.html\?company_id=42$/);
  });

  test("replaced support lookup requests suppress late stale results", async ({ page }) => {
    let releaseOldSearch;
    const oldSearch = new Promise(resolve => {
      releaseOldSearch = resolve;
    });
    const newCompany = {
      ...company,
      id: 43,
      company_name: "Newest Tenant",
      contact_email: "newest@example.test"
    };
    await openPlatformPage(page, "/platform-admin-support.html", async ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies" && url.searchParams.get("search") === "old") {
        await oldSearch;
        return success(companyList(1, [{ ...company, company_name: "Old Tenant" }]));
      }
      if (url.pathname === "/api/platform-admin/companies" && url.searchParams.get("search") === "new") {
        return success(companyList(1, [newCompany]));
      }
      return defaultHandler({ url });
    });

    await page.getByLabel("Company name or ID").fill("old");
    await page.getByRole("button", { name: "Search companies" }).click();
    await expect(page.getByText("Loading company results...")).toBeVisible();
    await page.getByLabel("Company name or ID").fill("new");
    await page.getByRole("button", { name: "Search companies" }).click();
    await expect(page.getByRole("cell", { name: "Newest Tenant" })).toBeVisible();
    releaseOldSearch();
    await page.waitForTimeout(100);
    await expect(page.getByText("Old Tenant")).toHaveCount(0);
    await expect(page.getByRole("cell", { name: "Newest Tenant" })).toBeVisible();
  });

  test("support access failures clear content and no write request or controls exist", async ({ page }) => {
    for (const scenario of [
      { status: 403, code: "platform_admin_access_denied", heading: "Access Denied" },
      { status: 503, code: "platform_admin_data_unavailable", heading: "Temporarily Unavailable" }
    ]) {
      const calls = await openPlatformPage(page, "/platform-admin-support.html", ({ url }) => {
        if (url.pathname === "/api/platform-admin/overview") return failure(scenario.status, scenario.code, "raw backend stack trace");
        return defaultHandler({ url });
      });
      await expect(page.getByRole("heading", { name: scenario.heading })).toBeVisible();
      await expect(page.getByText("raw backend stack trace")).toHaveCount(0);
      await expect(page.getByText("Support Workspace")).toHaveCount(0);
      expect(calls.every(call => call.method === "GET")).toBe(true);
    }

    await openPlatformPage(page, "/platform-admin-support.html", ({ url }) => defaultHandler({ url }));
    for (const label of ["Suspend", "Reactivate", "Impersonate", "Reset Password", "Adjust Credit", "Reconcile", "Export", "Create Ticket"]) {
      await expect(page.getByRole("button", { name: label })).toHaveCount(0);
      await expect(page.getByRole("link", { name: label })).toHaveCount(0);
    }
  });

  test("support workspace remains usable on mobile viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openPlatformPage(page, "/platform-admin-support.html", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "Support Workspace" })).toBeVisible();
    await expect(page.getByRole("link", { name: "View all companies" })).toBeVisible();
    await page.getByLabel("Company name or ID").fill("Example");
    await page.getByRole("button", { name: "Search companies" }).click();
    await expect(page.getByLabel("company result cards")).toBeVisible();
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
    await expect(page.getByRole("heading", { name: "Subscription", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "AI-credit and usage" })).toBeVisible();
    await expect(page.locator("script", { hasText: "window.__xss = true" })).toHaveCount(0);

    const paths = calls.map(call => call.path);
    expect(paths.indexOf("/api/platform-admin/companies/42")).toBeGreaterThan(paths.indexOf("/api/platform-admin/me"));
    expect(paths.indexOf("/api/platform-admin/companies/42/subscription")).toBeGreaterThan(paths.indexOf("/api/platform-admin/companies/42"));
    expect(paths.indexOf("/api/platform-admin/companies/42/ai-credit-usage")).toBeGreaterThan(paths.indexOf("/api/platform-admin/companies/42"));
    expect(paths).not.toContain("/api/platform-admin/companies/42/subscription-history");
    expect(paths).not.toContain("/api/platform-admin/companies/42/ai-credit-transactions");
    expect(paths).not.toContain("/api/platform-admin/companies/42/users");
    expect(paths).not.toContain("/api/platform-admin/companies/42/chatbots");
  });

  test("lazy subscription history loads with status filtering pagination and safe rendering", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "Subscription history" })).toBeVisible();
    expect(calls.map(call => call.path)).not.toContain("/api/platform-admin/companies/42/subscription-history");

    await page.getByRole("button", { name: "Load subscription history" }).click();
    await expect(page.getByRole("cell", { name: "Pro <img src=x onerror=window.__historyPlanXss=true>" })).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__historyPlanXss)).toBeUndefined();

    await page.getByLabel("Status").selectOption("past_due");
    await page.getByLabel("Page size").first().selectOption("50");
    await page.getByRole("button", { name: "Next" }).first().click();

    const historyUrls = calls
      .filter(call => call.path === "/api/platform-admin/companies/42/subscription-history")
      .map(call => new URL("http://test" + call.search));
    expect(historyUrls.length).toBeGreaterThanOrEqual(3);
    expect(historyUrls.some(url => url.searchParams.get("status") === "past_due")).toBe(true);
    expect(historyUrls.some(url => url.searchParams.get("limit") === "50")).toBe(true);
    expect(historyUrls.every(url => !url.searchParams.has("sort_by"))).toBe(true);
    expect(historyUrls.every(url => !url.searchParams.has("search"))).toBe(true);
  });

  test("subscription history empty unavailable retry and child 404 states are sanitized", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/subscription-history") {
        return success({
          ...subscriptionHistory,
          subscriptions: [],
          pagination: { limit: 25, offset: 0, returned: 0, total: 0, has_more: false }
        });
      }
      return defaultHandler({ url });
    });
    await page.getByRole("button", { name: "Load subscription history" }).click();
    await expect(page.getByText("No subscription history recorded.")).toBeVisible();

    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/subscription-history") {
        return failure(503, "platform_admin_data_unavailable", "raw Supabase details");
      }
      return defaultHandler({ url });
    });
    await page.getByRole("button", { name: "Load subscription history" }).click();
    await expect(page.getByText("Subscription history could not be loaded safely.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(page.getByText("raw Supabase details")).toHaveCount(0);

    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/subscription-history") {
        return failure(404, "company_not_found", "raw deleted company details");
      }
      return defaultHandler({ url });
    });
    await expect(page.getByRole("heading", { name: "AI-credit and usage" })).toBeVisible();
    await page.getByRole("button", { name: "Load subscription history" }).click();
    await expect(page.getByRole("heading", { name: "Company Not Found" })).toBeVisible();
    await expect(page.getByText("Example Tenant")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Subscription history" })).toHaveCount(0);
    await expect(page.getByText("Subscription history could not be loaded safely.")).toHaveCount(0);
    await expect(page.getByText("raw deleted company details")).toHaveCount(0);
  });

  test("lazy AI-credit transactions load with filtering pagination and safe null rendering", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "AI-credit transactions" })).toBeVisible();
    expect(calls.map(call => call.path)).not.toContain("/api/platform-admin/companies/42/ai-credit-transactions");

    await page.getByRole("button", { name: "Load AI-credit transactions" }).click();
    await expect(page.getByRole("cell", { name: /Usage Debit<script>window.*TransactionTypeXss=true/ })).toBeVisible();
    await expect(page.getByText("Not available").first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__transactionTypeXss)).toBeUndefined();

    await page.locator("#platform-ai-credit-transactions-type").selectOption("usage_debit");
    await page.locator("#platform-ai-credit-transactions-limit").selectOption("50");
    await page.locator("section.platform-panel")
      .filter({ has: page.getByRole("heading", { name: "AI-credit transactions" }) })
      .getByRole("button", { name: "Next" })
      .click();

    const transactionUrls = calls
      .filter(call => call.path === "/api/platform-admin/companies/42/ai-credit-transactions")
      .map(call => new URL("http://test" + call.search));
    expect(transactionUrls.length).toBeGreaterThanOrEqual(3);
    expect(transactionUrls.some(url => url.searchParams.get("transaction_type") === "usage_debit")).toBe(true);
    expect(transactionUrls.some(url => url.searchParams.get("limit") === "50")).toBe(true);
    expect(transactionUrls.every(url => !url.searchParams.has("sort_by"))).toBe(true);
    expect(transactionUrls.every(url => !url.searchParams.has("search"))).toBe(true);
    await assertReadOnlyBoundary(page);
  });

  test("AI-credit transaction empty unavailable retry and child 404 states are sanitized", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/ai-credit-transactions") {
        return success({
          ...aiCreditTransactions,
          transactions: [],
          pagination: { limit: 25, offset: 0, returned: 0, total: 0, has_more: false }
        });
      }
      return defaultHandler({ url });
    });
    await page.getByRole("button", { name: "Load AI-credit transactions" }).click();
    await expect(page.getByText("No AI-credit transactions recorded.")).toBeVisible();

    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/ai-credit-transactions") {
        return failure(503, "platform_admin_data_unavailable", "raw Supabase details");
      }
      return defaultHandler({ url });
    });
    await page.getByRole("button", { name: "Load AI-credit transactions" }).click();
    await expect(page.getByText("AI-credit transactions could not be loaded safely.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(page.getByText("raw Supabase details")).toHaveCount(0);

    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/ai-credit-transactions") {
        return failure(404, "company_not_found", "raw deleted company details");
      }
      return defaultHandler({ url });
    });
    await expect(page.getByRole("heading", { name: "AI-credit and usage" })).toBeVisible();
    await page.getByRole("button", { name: "Load AI-credit transactions" }).click();
    await expect(page.getByRole("heading", { name: "Company Not Found" })).toBeVisible();
    await expect(page.getByText("Example Tenant")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "AI-credit transactions" })).toHaveCount(0);
    await expect(page.getByText("AI-credit transactions could not be loaded safely.")).toHaveCount(0);
    await expect(page.getByText("raw deleted company details")).toHaveCount(0);
  });

  test("AI-credit transaction filter replaces pending request and suppresses late obsolete response", async ({ page }) => {
    let releaseUnfiltered;
    const slowObsolete = new Promise(resolve => {
      releaseUnfiltered = () => resolve(success({
        ...aiCreditTransactions,
        transactions: [{
          ...aiCreditTransactions.transactions[0],
          transaction_type: "refund<script>window.__obsoleteTransactionXss=true</script>"
        }]
      }));
    });
    const calls = await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/ai-credit-transactions") {
        if (url.searchParams.get("transaction_type") === "refund") {
          return slowObsolete;
        }
        if (url.searchParams.get("transaction_type") === "usage_debit") {
          return success(filteredAiCreditTransactions);
        }
        return success(aiCreditTransactions);
      }
      return defaultHandler({ url });
    });

    await page.getByRole("button", { name: "Load AI-credit transactions" }).click();
    await expect(page.getByRole("cell", { name: /Usage Debit<script>window.*TransactionTypeXss=true/ })).toBeVisible();
    await page.evaluate(() => {
      window.__obsoleteTransactionRenderState = "pending";
      PlatformAdminShell.runRequest("company-ai-credit-transactions", signal => (
        PlatformAdminApi.listCompanyAiCreditTransactions(42, {
          limit: 25,
          offset: 0,
          transactionType: "refund",
          signal
        })
      )).then(data => {
        const marker = document.createElement("div");
        marker.id = "obsolete-transaction-render";
        marker.textContent = data.transactions[0].transaction_type;
        document.body.append(marker);
        window.__obsoleteTransactionRenderState = "rendered";
      }).catch(error => {
        window.__obsoleteTransactionRenderState = error && error.category ? error.category : "rejected";
      });
    });
    await page.locator("#platform-ai-credit-transactions-type").selectOption("usage_debit");

    await expect(page.getByRole("cell", { name: /Usage Debit<img src=x onerror=window.*LateTransactionXss=true/ })).toBeVisible();
    await expect(page.getByText("MYR 0.25").first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__lateTransactionXss)).toBeUndefined();

    releaseUnfiltered();
    await page.waitForTimeout(100);
    await expect.poll(() => page.evaluate(() => window.__obsoleteTransactionRenderState)).toBe("aborted");
    await expect(page.locator("#obsolete-transaction-render")).toHaveCount(0);
    await expect(page.getByText("refund<script>window.__obsoleteTransactionXss=true</script>")).toHaveCount(0);
    await expect(page.getByText("MYR 0.25").first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__obsoleteTransactionXss)).toBeUndefined();

    const transactionUrls = calls
      .filter(call => call.path === "/api/platform-admin/companies/42/ai-credit-transactions")
      .map(call => new URL("http://test" + call.search));
    expect(transactionUrls.some(url => !url.searchParams.has("transaction_type"))).toBe(true);
    expect(transactionUrls.some(url => url.searchParams.get("transaction_type") === "usage_debit")).toBe(true);
  });

  test("lazy users and chatbots sections load safe fields with query parameters", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    expect(calls.map(call => call.path)).not.toContain("/api/platform-admin/companies/42/users");
    expect(calls.map(call => call.path)).not.toContain("/api/platform-admin/companies/42/chatbots");

    await page.getByRole("button", { name: "Load users" }).click();
    await expect(page.getByRole("cell", { name: "Operator <img src=x onerror=window.__userXss=true>" })).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__userXss)).toBeUndefined();
    await page.getByLabel("Search").fill("operator");
    await page.getByRole("button", { name: "Apply search" }).click();

    await page.getByRole("button", { name: "Load chatbots" }).click();
    await expect(page.getByRole("cell", { name: "Bot <svg onload=window.__botXss=true>" })).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__botXss)).toBeUndefined();
    await page.getByLabel("State").selectOption("archived");
    await page.getByLabel("Sort by").last().selectOption("bot_name");
    await page.getByLabel("Page size").last().selectOption("50");

    const userUrls = calls
      .filter(call => call.path === "/api/platform-admin/companies/42/users")
      .map(call => new URL("http://test" + call.search));
    expect(userUrls.some(url => url.searchParams.get("search") === "operator")).toBe(true);
    expect(userUrls.every(url => url.searchParams.get("sort_by"))).toBe(true);

    const chatbotUrls = calls
      .filter(call => call.path === "/api/platform-admin/companies/42/chatbots")
      .map(call => new URL("http://test" + call.search));
    expect(chatbotUrls.some(url => url.searchParams.get("state") === "archived")).toBe(true);
    expect(chatbotUrls.some(url => url.searchParams.get("sort_by") === "bot_name")).toBe(true);
    expect(chatbotUrls.some(url => url.searchParams.get("limit") === "50")).toBe(true);
  });

  test("child list empty and unavailable states are fixed and sanitized", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/users") {
        return success({ ...userList, users: [], pagination: { limit: 25, offset: 0, returned: 0, total: 0, has_more: false } });
      }
      if (url.pathname === "/api/platform-admin/companies/42/chatbots") {
        return failure(503, "platform_admin_data_unavailable", "raw Supabase details");
      }
      return defaultHandler({ url });
    });
    await page.getByRole("button", { name: "Load users" }).click();
    await expect(page.getByText("No users found for this company.")).toBeVisible();
    await page.getByRole("button", { name: "Load chatbots" }).click();
    await expect(page.getByText("Chatbots could not be loaded safely.")).toBeVisible();
    await expect(page.getByText("raw Supabase details")).toHaveCount(0);
  });

  test("child list 404 clears stale company detail instead of showing section unavailable", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/users") {
        return failure(404, "company_not_found", "raw deleted company details");
      }
      return defaultHandler({ url });
    });
    await expect(page.getByRole("heading", { name: "AI-credit and usage" })).toBeVisible();

    await page.getByRole("button", { name: "Load users" }).click();
    await expect(page.getByRole("heading", { name: "Company Not Found" })).toBeVisible();
    await expect(page.getByText("Example Tenant")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Company profile" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Subscription" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "AI-credit and usage" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Users" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Chatbots" })).toHaveCount(0);
    await expect(page.getByText("Users could not be loaded safely.")).toHaveCount(0);
    await expect(page.getByText("raw deleted company details")).toHaveCount(0);
  });

  test("child list 404 aborts active sibling requests and late responses do not restore stale content", async ({ page }) => {
    let releaseUsers;
    const delayedUsers = new Promise(resolve => {
      releaseUsers = () => resolve(success(userList));
    });
    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/users") return delayedUsers;
      if (url.pathname === "/api/platform-admin/companies/42/chatbots") {
        return failure(404, "company_not_found", "raw deleted company details");
      }
      return defaultHandler({ url });
    });

    await page.getByRole("button", { name: "Load users" }).click();
    await expect(page.getByText("Loading users")).toBeVisible();
    await page.getByRole("button", { name: "Load chatbots" }).click();
    await expect(page.getByRole("heading", { name: "Company Not Found" })).toBeVisible();

    releaseUsers();
    await page.waitForTimeout(100);
    await expect(page.getByText("Operator <img src=x onerror=window.__userXss=true>")).toHaveCount(0);
    await expect(page.getByText("Example Tenant")).toHaveCount(0);
    await expect(page.getByText("Chatbots could not be loaded safely.")).toHaveCount(0);
    await expect(page.getByText("raw deleted company details")).toHaveCount(0);
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
    await expect(page.getByRole("heading", { name: "Platform operations" })).toBeVisible();
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
    "Edit User",
    "Deactivate User",
    "Reset Password",
    "Invite User",
    "Edit Chatbot",
    "Delete Chatbot",
    "Restore Chatbot",
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
