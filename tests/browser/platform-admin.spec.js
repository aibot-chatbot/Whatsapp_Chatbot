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

const platformAdminUsers = {
  platform_admin_users: [
    {
      platform_admin_user_id: 7001,
      user_id: 9001,
      is_active: true,
      created_at: "2026-07-01T00:00:00+00:00",
      updated_at: "2026-07-02T00:00:00+00:00",
      created_by_user_id: null,
      user_email: "operator@example.test",
      user_full_name: "Test Operator",
      user_status: "active",
      creator_user_id: null,
      creator_email: null,
      creator_full_name: null,
      recent_platform_admin_activity_at: "2026-07-03T00:00:00+00:00"
    },
    {
      platform_admin_user_id: 7002,
      user_id: 9002,
      is_active: false,
      created_at: "2026-07-04T00:00:00+00:00",
      updated_at: "2026-07-05T00:00:00+00:00",
      created_by_user_id: 9001,
      user_email: "second@example.test",
      user_full_name: "Second Operator <script>window.__adminUserXss=true</script>",
      user_status: "active",
      creator_user_id: 9001,
      creator_email: "operator@example.test",
      creator_full_name: "Test Operator",
      recent_platform_admin_activity_at: null
    }
  ],
  pagination: { limit: 100, offset: 0, returned: 2, total: 2, has_more: false },
  filters: { is_active: null }
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

const supportCase = {
  id: 9,
  company_id: 42,
  company: { id: 42, company_name: "Example Tenant <script>window.__xss = true</script>", status: "active" },
  created_by_platform_admin_user_id: 7001,
  assigned_platform_admin_user_id: 7001,
  status: "open",
  priority: "normal",
  title: "Review tenant activation <script>window.__caseXss=true</script>",
  redacted_summary: "Safe internal summary only.",
  created_at: "2026-07-30T00:00:00+00:00",
  updated_at: "2026-07-30T00:00:00+00:00",
  closed_at: null
};

const supportCaseDetail = {
  case: supportCase,
  source_tenant_request: { request_id: 31, company_id: 42, status: "converted" },
  status_transitions: ["in_progress", "waiting_for_tenant", "resolved"],
  events: [
    {
      id: 1,
      case_id: 9,
      event_type: "created",
      actor_platform_admin_user_id: 7001,
      new_status: "open",
      new_priority: "normal",
      created_at: "2026-07-30T00:00:00+00:00"
    },
    {
      id: 2,
      case_id: 9,
      event_type: "assignment_changed",
      actor_platform_admin_user_id: 7001,
      old_assigned_platform_admin_user_id: null,
      new_assigned_platform_admin_user_id: 7001,
      created_at: "2026-07-30T00:01:00+00:00"
    },
    {
      id: 3,
      case_id: 9,
      event_type: "note_added",
      actor_platform_admin_user_id: 7001,
      redacted_note: "Safe note <img src=x onerror=window.__noteXss=true>",
      created_at: "2026-07-30T00:02:00+00:00"
    }
  ]
};

const supportCases = {
  cases: [supportCase],
  pagination: { limit: 25, offset: 0, returned: 1, total: 1, has_more: false },
  filters: { company_id: null, status: null, priority: null }
};

const supportCaseAssignees = {
  assignees: [{ id: 7001, user_id: 9001, is_active: true }]
};

const supportCaseReplies = {
  case: supportCase,
  source_tenant_request: { request_id: 31, company_id: 42, status: "converted" },
  replies: [{
    reply_id: 44,
    request_id: 31,
    case_id: 9,
    company_id: 42,
    author_type: "platform_admin",
    redacted_body: "Visible update <img src=x onerror=window.__replyXss=true>",
    visibility_status: "visible",
    created_at: "2026-07-30T00:03:00+00:00"
  }],
  notifications: [{
    notification_id: 50,
    reply_id: 44,
    channel: "in_app",
    status: "pending",
    attempt_count: 0,
    created_at: "2026-07-30T00:03:00+00:00"
  }]
};

const tenantSupportRequests = {
  requests: [],
  pagination: { limit: 25, offset: 0, returned: 0, total: 0, has_more: false },
  filters: { company_id: null, category: null, status: null }
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
  ],
  operational_alerts: {
    alerts: [
      {
        type: "subscription_past_due",
        severity: "warning",
        company_id: 42,
        company_name: "Example Tenant <script>window.__xss = true</script>",
        company_status: "active",
        summary: "Subscription is past due",
        details: {
          subscription_status: "past_due",
          plan_code: "pro",
          plan_name: "Pro <img src=x onerror=window.__alertPlanXss=true>",
          current_period_end: "2026-07-28T00:00:00+00:00",
          status_updated_at: "2026-07-29T00:00:00+00:00"
        },
        investigation_url: "platform-admin-company.html?company_id=42"
      },
      {
        type: "subscription_expired",
        severity: "critical",
        company_id: 43,
        company_name: "Expired Tenant <svg onload=window.__expiredAlertXss=true>",
        company_status: "active",
        summary: "Subscription is expired",
        details: {
          subscription_status: "expired",
          plan_code: "free",
          plan_name: "Free",
          current_period_end: "2026-07-20T00:00:00+00:00",
          status_updated_at: "2026-07-21T00:00:00+00:00"
        },
        investigation_url: "platform-admin-company.html?company_id=43"
      }
    ],
    summary: { total: 2, critical: 1, warning: 1, info: 0 },
    limits: { max_alerts: 10 }
  }
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

const billingOrders = {
  billing_orders: [
    {
      id: 901,
      status: "credited<script>window.__billingStatusXss=true</script>",
      amount_sen: 3900,
      new_plan: {
        code: "pro",
        name: "Pro <img src=x onerror=window.__billingPlanXss=true>"
      },
      source_plan: null,
      activation_status: "completed",
      activation_type: "upgrade",
      reconciliation_required: false,
      created_at: "2026-07-01T00:00:00+00:00",
      updated_at: "2026-07-01T00:03:00+00:00",
      paid_at: "2026-07-01T00:01:00+00:00",
      credited_at: null,
      expires_at: "2026-07-02T00:00:00+00:00",
      activation_claimed_at: "2026-07-01T00:01:10+00:00",
      activation_completed_at: "2026-07-01T00:02:00+00:00",
      credit_granted_at: null
    }
  ],
  pagination: { limit: 25, offset: 0, returned: 1, total: 2, has_more: true },
  filters: {
    status: null,
    status_applied: false,
    created_after: null,
    created_after_applied: false,
    created_before: null,
    created_before_applied: false
  },
  ordering: { by: "created_at", order: "desc", tie_breaker: "id desc" },
  amount_units: {
    amount_sen: "integer sen as stored; currency is not returned or inferred"
  }
};

const filteredBillingOrders = {
  billing_orders: [
    {
      id: 902,
      status: "pending<img src=x onerror=window.__lateBillingXss=true>",
      amount_sen: null,
      new_plan: null,
      source_plan: {
        code: "advanced",
        name: "Advanced"
      },
      activation_status: null,
      activation_type: null,
      reconciliation_required: true,
      created_at: "2026-07-02T00:00:00+00:00",
      updated_at: null,
      paid_at: null,
      credited_at: null,
      expires_at: null,
      activation_claimed_at: null,
      activation_completed_at: null,
      credit_granted_at: null
    }
  ],
  pagination: { limit: 50, offset: 25, returned: 1, total: 26, has_more: false },
  filters: {
    status: "pending",
    status_applied: true,
    created_after: "2026-07-01T00:00:00+00:00",
    created_after_applied: true,
    created_before: "2026-08-01T00:00:00+00:00",
    created_before_applied: true
  },
  ordering: { by: "created_at", order: "desc", tie_breaker: "id desc" },
  amount_units: {
    amount_sen: "integer sen as stored; currency is not returned or inferred"
  }
};

const auditEvents = {
  audit_events: [
    {
      id: 801,
      actor: { platform_admin_user_id: 7001 },
      action: "platform_admin.company.read<script>window.__auditActionXss=true</script>",
      resource_type: "company<img src=x onerror=window.__auditResourceXss=true>",
      resource_id: "42",
      metadata: {
        outcome: "success",
        endpoint: "/api/platform-admin/companies/<company_id>",
        http_method: "GET",
        limit: 25,
        returned_count: 1,
        token: "must-not-render",
        raw_payload: { secret: "must-not-render" }
      },
      created_at: "2026-07-31T08:00:00+00:00"
    }
  ],
  pagination: { limit: 25, offset: 0, returned: 1, total: 2, has_more: true },
  filters: {
    action: null,
    resource_type: null,
    actor_user_id: null,
    resource_id: null,
    created_after: null,
    created_before: null
  },
  ordering: { by: "created_at", order: "desc", tie_breaker: "id desc" }
};

const filteredAuditEvents = {
  audit_events: [
    {
      id: 802,
      actor: { platform_admin_user_id: 7002 },
      action: "platform_admin.audit_events.list",
      resource_type: "platform_admin_audit_events",
      resource_id: null,
      metadata: {
        outcome: "success",
        endpoint: "/api/platform-admin/audit-events",
        http_method: "GET",
        action_filter_applied: true,
        resource_type_filter_applied: false,
        actor_user_id_filter_applied: false,
        resource_id_filter_applied: true,
        created_after_filter_applied: true,
        created_before_filter_applied: true,
        returned_count: 1
      },
      created_at: "2026-07-31T09:00:00+00:00"
    }
  ],
  pagination: { limit: 50, offset: 25, returned: 1, total: 26, has_more: false },
  filters: {
    action: "platform_admin.audit_events.list",
    resource_type: null,
    actor_user_id: null,
    resource_id: "42",
    created_after: "2026-07-31T00:00:00+00:00",
    created_before: "2026-08-01T00:00:00+00:00"
  },
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
  if (url.pathname === "/api/platform-admin/audit-events") return success(auditEvents);
  if (url.pathname === "/api/platform-admin/platform-admin-users") return success(platformAdminUsers);
  if (url.pathname === "/api/platform-admin/platform-admin-users/7002/active") {
    return success({
      platform_admin_user: {
        platform_admin_user_id: 7002,
        user_id: 9002,
        is_active: true
      }
    });
  }
  if (url.pathname === "/api/platform-admin/support-case-assignees") return success(supportCaseAssignees);
  if (url.pathname === "/api/platform-admin/support-cases") return success(supportCases);
  if (url.pathname === "/api/platform-admin/support-cases/9") return success(supportCaseDetail);
  if (url.pathname === "/api/platform-admin/support-cases/9/replies") return success(supportCaseReplies);
  if (url.pathname === "/api/platform-admin/tenant-support-requests") return success(tenantSupportRequests);
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
  if (url.pathname === "/api/platform-admin/companies/42/billing-orders") {
    return success(billingOrders);
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
    await expect(page.getByRole("heading", { name: "Operational alerts" })).toBeVisible();
    await expect(metricCard(page, "Total alerts")).toContainText("2");
    await expect(metricCard(page, "Critical alerts")).toContainText("1");
    await expect(metricCard(page, "Warning alerts")).toContainText("1");
    await expect(metricCard(page, "Info alerts")).toContainText("0");
    await expect(page.getByRole("cell", { name: "Subscription is past due" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Subscription is expired" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Pro <img src=x onerror=window.__alertPlanXss=true>" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Expired Tenant <svg onload=window.__expiredAlertXss=true>" })).toHaveAttribute("href", "platform-admin-company.html?company_id=43");
    await expect(page.getByRole("heading", { name: "Companies requiring attention" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Pro <img src=x onerror=window.__planXss=true>" }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Example Tenant <script>window.__xss = true</script>" }).first()).toHaveAttribute("href", "platform-admin-company.html?company_id=42");
    await expect(page.locator("script", { hasText: "window.__xss = true" })).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__xss)).toBeUndefined();
    await expect.poll(() => page.evaluate(() => window.__planXss)).toBeUndefined();
    await expect.poll(() => page.evaluate(() => window.__alertPlanXss)).toBeUndefined();
    await expect.poll(() => page.evaluate(() => window.__expiredAlertXss)).toBeUndefined();
    await expect(page.getByText("Internal / Controlled Access")).toBeVisible();
    await assertReadOnlyBoundary(page);
  });

  test("dashboard performs one overview request after authorization and handles empty attention", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/overview") {
        return success({
          ...operationsOverview,
          attention_companies: [],
          operational_alerts: {
            alerts: [],
            summary: { total: 0, critical: 0, warning: 0, info: 0 },
            limits: { max_alerts: 10 }
          }
        });
      }
      return defaultHandler({ url });
    });
    await expect(page.getByText("No operational alerts found.")).toBeVisible();
    await expect(page.getByText("No past-due or expired companies found.")).toBeVisible();
    expect(calls.map(call => call.path)).toEqual(["/api/platform-admin/me", "/api/platform-admin/overview"]);
    expect(calls.filter(call => call.path === "/api/platform-admin/companies")).toHaveLength(0);
  });

  test("dashboard derives operational alerts from legacy attention response", async ({ page }) => {
    const legacyOverview = {
      ...operationsOverview,
      operational_alerts: undefined,
      attention_companies: [
        {
          company_id: 42,
          company_name: "Legacy Tenant <script>window.__legacyAlertXss=true</script>",
          company_status: "active",
          subscription_status: "expired",
          plan_code: "pro",
          plan_name: "Legacy Pro",
          status_updated_at: "2026-07-29T00:00:00+00:00",
          current_period_end: "2026-07-28T00:00:00+00:00"
        }
      ]
    };
    delete legacyOverview.operational_alerts;
    await openPlatformPage(page, "/platform-admin.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/overview") return success(legacyOverview);
      return defaultHandler({ url });
    });
    await expect(metricCard(page, "Total alerts")).toContainText("1");
    await expect(metricCard(page, "Critical alerts")).toContainText("1");
    await expect(page.getByRole("cell", { name: "Subscription is expired" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Legacy Tenant <script>window.__legacyAlertXss=true</script>" }).first()).toHaveAttribute("href", "platform-admin-company.html?company_id=42");
    await expect.poll(() => page.evaluate(() => window.__legacyAlertXss)).toBeUndefined();
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
      await expect(page.getByText("Example Tenant").first()).toBeVisible();

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
    await expect(page.getByText("No tenant-submitted support requests found.")).toBeVisible();
    expect(calls.map(call => call.path)).toEqual([
      "/api/platform-admin/me",
      "/api/platform-admin/overview",
      "/api/platform-admin/support-case-assignees",
      "/api/platform-admin/support-cases",
      "/api/platform-admin/tenant-support-requests"
    ]);
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
    await expect(page.getByRole("cell", { name: "Review tenant activation" })).toBeVisible();
    expect(calls.map(call => call.path)).toEqual([
      "/api/platform-admin/me",
      "/api/platform-admin/overview",
      "/api/platform-admin/support-case-assignees",
      "/api/platform-admin/support-cases",
      "/api/platform-admin/tenant-support-requests"
    ]);
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

  test("case detail renders operational controls and uses split mutation endpoints", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-support.html", ({ request, url }) => {
      if (url.pathname === "/api/platform-admin/support-cases/9/assignment") {
        return success({ ...supportCaseDetail, case: { ...supportCase, assigned_platform_admin_user_id: null } });
      }
      if (url.pathname === "/api/platform-admin/support-cases/9/status") {
        return success({ ...supportCaseDetail, case: { ...supportCase, status: "in_progress" } });
      }
      if (url.pathname === "/api/platform-admin/support-cases/9/priority") {
        return success({ ...supportCaseDetail, case: { ...supportCase, priority: "high" } });
      }
      if (url.pathname === "/api/platform-admin/support-cases/9/notes") {
        return success(supportCaseDetail);
      }
      return defaultHandler({ request, url });
    });

    await page.getByRole("button", { name: "Open case" }).click();
    await expect(page.getByRole("heading", { name: "Internal support case detail" })).toBeVisible();
    await expect(page.getByText("Tenant request #31")).toBeVisible();
    await expect(page.getByText("Case activity timeline")).toBeVisible();
    await expect(page.getByText("Safe note <img src=x onerror=window.__noteXss=true>")).toBeVisible();
    await expect(page.getByLabel("Next status")).not.toContainText("Closed");
    await expect(page.getByLabel("Next status")).toContainText("Waiting for tenant");
    await expect(page.getByRole("button", { name: "Update assignee" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Update priority" })).toBeDisabled();

    await page.getByLabel("Assignee").selectOption("");
    await expect(page.getByRole("button", { name: "Update assignee" })).toBeEnabled();
    await page.getByRole("button", { name: "Update assignee" }).click();
    await page.getByLabel("Next status").selectOption("in_progress");
    await page.getByRole("button", { name: "Update status" }).click();
    await page.getByLabel("Priority").selectOption("high");
    await expect(page.getByRole("button", { name: "Update priority" })).toBeEnabled();
    await page.getByRole("button", { name: "Update priority" }).click();
    await page.getByLabel("Redacted internal note").fill("Follow-up note");
    await page.getByRole("button", { name: "Add internal note" }).click();
    await expect(page.getByRole("heading", { name: "Tenant-visible conversation" })).toBeVisible();
    await expect(page.getByText("Visible update <img src=x onerror=window.__replyXss=true>")).toBeVisible();
    await expect(page.getByRole("button", { name: "Send reply to tenant" })).toBeVisible();

    await expect.poll(() => page.evaluate(() => window.__caseXss || window.__noteXss || window.__replyXss || false)).toBe(false);
    expect(calls.some(call => call.method === "PATCH" && call.path.endsWith("/assignment"))).toBe(true);
    expect(calls.some(call => call.method === "PATCH" && call.path.endsWith("/status"))).toBe(true);
    expect(calls.some(call => call.method === "PATCH" && call.path.endsWith("/priority"))).toBe(true);
    expect(calls.some(call => call.method === "POST" && call.path.endsWith("/notes"))).toBe(true);
  });

  test("reply composer prevents duplicate submits and recovers after refresh failure", async ({ page }) => {
    let releaseReply;
    let replyRequests = 0;
    let failRefresh = false;
    page.on("dialog", dialog => dialog.accept());
    await openPlatformPage(page, "/platform-admin-support.html", async ({ request, url }) => {
      if (url.pathname === "/api/platform-admin/support-cases/9/replies" && request.method() === "POST") {
        replyRequests += 1;
        await new Promise(resolve => {
          releaseReply = resolve;
        });
        failRefresh = true;
        return success({
          case: supportCase,
          event: { event_id: 4, case_id: 9, event_type: "tenant_reply_created" },
          reply: {
            reply_id: 45,
            request_id: 31,
            case_id: 9,
            company_id: 42,
            author_type: "platform_admin",
            redacted_body: "Safe tenant update",
            visibility_status: "visible",
            created_at: "2026-07-30T00:05:00+00:00"
          },
          notification: {
            notification_id: 51,
            reply_id: 45,
            channel: "in_app",
            status: "pending",
            attempt_count: 0
          }
        });
      }
      if (url.pathname === "/api/platform-admin/support-cases/9" && failRefresh) {
        return failure(503, "temporarily_unavailable", "Temporarily unavailable.");
      }
      return defaultHandler({ request, url });
    });

    await page.getByRole("button", { name: "Open case" }).click();
    await page.getByLabel("Tenant-visible redacted reply").fill("Safe tenant update");
    const sendButton = page.getByRole("button", { name: "Send reply to tenant" });
    await sendButton.click();
    await expect(sendButton).toBeDisabled();
    await sendButton.click({ force: true });
    expect(replyRequests).toBe(1);
    releaseReply();

    await expect(sendButton).toBeEnabled();
    await page.getByLabel("Tenant-visible redacted reply").fill("Another safe update");
    await expect(sendButton).toBeEnabled();
    await expect(page.getByText("raw")).toHaveCount(0);
    await expect(page.getByText("stack")).toHaveCount(0);
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

test.describe("platform-admin audit log viewer", () => {
  test("audit nav and data appear only after platform authorization", async ({ page }) => {
    let releaseMe;
    const meGate = new Promise(resolve => {
      releaseMe = resolve;
    });
    const calls = await openPlatformPage(page, "/platform-admin-audit-events.html", async ({ url }) => {
      if (url.pathname === "/api/platform-admin/me") {
        await meGate;
        return success(identity);
      }
      return defaultHandler({ url });
    });

    await expect(page.getByRole("heading", { name: "Checking access" })).toBeVisible();
    expect(calls.map(call => call.path)).toEqual(["/api/platform-admin/me"]);
    releaseMe();
    await expect(page.getByRole("heading", { name: "Audit Logs" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Audit Logs" })).toHaveAttribute("href", "platform-admin-audit-events.html");
    expect(calls.map(call => call.path)).toEqual(["/api/platform-admin/me", "/api/platform-admin/audit-events"]);
    expect(calls.every(call => call.method === "GET")).toBe(true);
  });

  test("renders safe audit rows and allowlisted metadata only", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-audit-events.html", ({ url }) => defaultHandler({ url }));

    await expect(page.getByRole("heading", { name: "Audit Logs" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "platform_admin.company.read<script>window.__auditActionXss=true</script>" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "company<img src=x onerror=window.__auditResourceXss=true>" })).toBeVisible();
    await expect(page.getByText("platform_admin_user_id")).toHaveCount(0);
    await expect(page.getByText("must-not-render")).toHaveCount(0);
    await expect(page.getByText("raw_payload")).toHaveCount(0);
    await expect(page.getByText("token")).toHaveCount(0);
    await expect(page.getByRole("table").getByText("outcome")).toBeVisible();
    await expect(page.getByRole("table").getByText("endpoint")).toBeVisible();
    await expect(page.getByRole("table").getByText("http_method")).toBeVisible();
    expect(await page.evaluate(() => window.__auditActionXss || window.__auditResourceXss || false)).toBe(false);
    expect(calls.filter(call => call.path === "/api/platform-admin/audit-events")).toHaveLength(1);
  });

  test("pagination and approved filters produce expected query parameters", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-audit-events.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/audit-events" && url.searchParams.get("action")) {
        return success(filteredAuditEvents);
      }
      return defaultHandler({ url });
    });

    await page.getByRole("button", { name: "Next" }).click();
    await page.locator("#platform-audit-action").selectOption("platform_admin.audit_events.list");
    await page.locator("#platform-audit-resource-type").selectOption("platform_admin_audit_events");
    await page.locator("#platform-audit-actor-user-id").fill("32");
    await page.locator("#platform-audit-resource-id").fill("42");
    await page.locator("#platform-audit-created-after").fill("2026-07-31T00:00:00+00:00");
    await page.locator("#platform-audit-created-before").fill("2026-08-01T00:00:00+00:00");
    await page.locator("#platform-audit-limit").selectOption("50");
    await page.getByRole("button", { name: "Apply filters" }).click();
    await expect(page.getByRole("cell", { name: "platform_admin.audit_events.list" })).toBeVisible();

    await page.getByRole("button", { name: "Previous" }).click();
    const urls = calls
      .filter(call => call.path === "/api/platform-admin/audit-events")
      .map(call => new URL("http://test" + call.search));
    expect(urls.some(url => url.searchParams.get("limit") === "50")).toBe(true);
    expect(urls.some(url => url.searchParams.get("offset") === "25")).toBe(true);
    expect(urls.some(url => url.searchParams.get("offset") === "0")).toBe(true);
    expect(urls.some(url => url.searchParams.get("action") === "platform_admin.audit_events.list")).toBe(true);
    expect(urls.some(url => url.searchParams.get("resource_type") === "platform_admin_audit_events")).toBe(true);
    expect(urls.some(url => url.searchParams.get("actor_user_id") === "32")).toBe(true);
    expect(urls.some(url => url.searchParams.get("resource_id") === "42")).toBe(true);
    expect(urls.every(url => !url.searchParams.has("metadata"))).toBe(true);
    expect(urls.every(url => !url.searchParams.has("sort_by"))).toBe(true);

    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.locator("#platform-audit-action")).toHaveValue("");
    await expect(page.locator("#platform-audit-resource-id")).toHaveValue("");
  });

  test("empty validation unavailable and access failure states are sanitized", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-audit-events.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/audit-events") {
        return success({
          ...auditEvents,
          audit_events: [],
          pagination: { limit: 25, offset: 0, returned: 0, total: 0, has_more: false }
        });
      }
      return defaultHandler({ url });
    });
    await expect(page.getByText("No audit events found.")).toBeVisible();

    await openPlatformPage(page, "/platform-admin-audit-events.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/audit-events") {
        return failure(400, "invalid_action", "raw validation detail");
      }
      return defaultHandler({ url });
    });
    await expect(page.getByText("Audit log filters could not be validated.")).toBeVisible();
    await expect(page.getByText("raw validation detail")).toHaveCount(0);

    await openPlatformPage(page, "/platform-admin-audit-events.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/audit-events") {
        return failure(503, "platform_admin_data_unavailable", "raw Supabase details");
      }
      return defaultHandler({ url });
    });
    await expect(page.getByRole("heading", { name: "Temporarily Unavailable" })).toBeVisible();
    await expect(page.getByText("raw Supabase details")).toHaveCount(0);
    await expect(page.getByText("platform_admin.company.read")).toHaveCount(0);

    await openPlatformPage(page, "/platform-admin-audit-events.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/me") {
        return failure(403, "platform_admin_access_denied");
      }
      return defaultHandler({ url });
    });
    await expect(page.getByRole("heading", { name: "Access Denied" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Audit Logs" })).toHaveCount(0);
  });

  test("late audit response cannot restore obsolete rows", async ({ page }) => {
    let releaseOld;
    const oldRequest = new Promise(resolve => {
      releaseOld = () => resolve(success({
        ...auditEvents,
        audit_events: [{
          ...auditEvents.audit_events[0],
          action: "platform_admin.company.list<script>window.__oldAuditXss=true</script>"
        }]
      }));
    });
    await openPlatformPage(page, "/platform-admin-audit-events.html", ({ url }) => {
      if (url.pathname === "/api/platform-admin/audit-events") {
        if (!url.searchParams.get("action")) return oldRequest;
        return success(filteredAuditEvents);
      }
      return defaultHandler({ url });
    });

    await expect(page.getByText("Loading audit events...")).toBeVisible();
    await page.locator("#platform-audit-action").selectOption("platform_admin.audit_events.list");
    await page.getByRole("button", { name: "Apply filters" }).click();
    await expect(page.getByRole("cell", { name: "platform_admin.audit_events.list" })).toBeVisible();
    releaseOld();
    await page.waitForTimeout(100);
    await expect(page.getByText("platform_admin.company.list<script>window.__oldAuditXss=true</script>")).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__oldAuditXss)).toBeUndefined();
  });

  test("audit log viewer has no write export controls and works on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openPlatformPage(page, "/platform-admin-audit-events.html", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "Audit Logs" })).toBeVisible();
    await expect(page.getByLabel("audit event cards")).toBeVisible();
    for (const label of ["Export", "Download", "Delete audit", "Edit audit", "Create Ticket", "Platform Admin Mapping"]) {
      await expect(page.getByRole("button", { name: label })).toHaveCount(0);
      await expect(page.getByRole("link", { name: label })).toHaveCount(0);
    }
  });
});

test.describe("platform-admin user management", () => {
  test("directory renders safe mapping fields and bounded lifecycle controls", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-users.html", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "Platform Admin Management" })).toBeVisible();
    await expect(page.getByText("Recent platform activity")).toBeVisible();
    await expect(page.getByText("Bootstrap/unknown")).toBeVisible();
    await expect(page.getByText("Second Operator <script>window.__adminUserXss=true</script>")).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__adminUserXss)).toBeUndefined();
    await expect(page.getByRole("button", { name: "Deactivate", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Activate", exact: true })).toBeEnabled();
    await expect(page.getByRole("textbox", { name: /company/i })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: /role|company/i })).toHaveCount(0);
    for (const label of ["Invite", "Reset password", "Impersonate", "Delete", "Billing"]) {
      await expect(page.getByRole("button", { name: label })).toHaveCount(0);
    }
    await page.getByRole("button", { name: "Activate", exact: true }).click();
    expect(calls.some(call => (
      call.method === "PATCH" && call.path === "/api/platform-admin/platform-admin-users/7002/active"
    ))).toBe(true);
  });

  test("add existing user uses numeric ID, prevents duplicate submits, and refreshes", async ({ page }) => {
    let releaseCreate;
    let createCount = 0;
    const createGate = new Promise(resolve => {
      releaseCreate = () => resolve(success({
        platform_admin_user: { platform_admin_user_id: 7003, user_id: 9003, is_active: true }
      }));
    });
    page.on("dialog", dialog => dialog.accept());
    await openPlatformPage(page, "/platform-admin-users.html", ({ request, url }) => {
      if (url.pathname === "/api/platform-admin/platform-admin-users" && request.method() === "POST") {
        createCount += 1;
        return createGate;
      }
      return defaultHandler({ url });
    });

    await page.getByLabel("Existing user ID").fill("9003");
    const addButton = page.getByRole("button", { name: "Add platform admin" });
    await addButton.click();
    await expect(addButton).toBeDisabled();
    await page.evaluate(() => document.querySelector("form button[type='submit']").click());
    expect(createCount).toBe(1);
    releaseCreate();
    await expect(page.getByRole("heading", { name: "Platform Admins" })).toBeVisible();
  });

  test("create failures are sanitized and do not expose raw provider detail", async ({ page }) => {
    page.on("dialog", dialog => dialog.accept());
    await openPlatformPage(page, "/platform-admin-users.html", ({ request, url }) => {
      if (url.pathname === "/api/platform-admin/platform-admin-users" && request.method() === "POST") {
        return failure(400, "target_user_not_protected", "raw Supabase protected-company detail");
      }
      return defaultHandler({ url });
    });

    await page.getByLabel("Existing user ID").fill("12345");
    await page.getByRole("button", { name: "Add platform admin" }).click();
    await expect(page.getByText("User is not eligible for platform-admin access.")).toBeVisible();
    await expect(page.getByText("raw Supabase protected-company detail")).toHaveCount(0);
  });

  test("successful add followed by refresh failure shows recoverable retry state", async ({ page }) => {
    let directoryRequests = 0;
    page.on("dialog", dialog => dialog.accept());
    await openPlatformPage(page, "/platform-admin-users.html", ({ request, url }) => {
      if (url.pathname === "/api/platform-admin/platform-admin-users" && request.method() === "GET") {
        directoryRequests += 1;
        if (directoryRequests === 1) return success(platformAdminUsers);
        return failure(503, "platform_admin_data_unavailable", "raw Supabase refresh detail");
      }
      if (url.pathname === "/api/platform-admin/platform-admin-users" && request.method() === "POST") {
        return success({
          platform_admin_user: { platform_admin_user_id: 7003, user_id: 9003, is_active: true }
        });
      }
      return defaultHandler({ url });
    });

    await page.getByLabel("Existing user ID").fill("9003");
    await page.getByRole("button", { name: "Add platform admin" }).click();
    await expect(page.getByText("Loading platform admins...")).toHaveCount(0);
    await expect(page.getByText("Platform-admin directory refresh failed. Retry to load the current state.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(page.getByText("raw Supabase refresh detail")).toHaveCount(0);
  });

  test("successful activation followed by refresh failure shows recoverable retry state", async ({ page }) => {
    let activeRequests = 0;
    let directoryRequests = 0;
    await openPlatformPage(page, "/platform-admin-users.html", ({ request, url }) => {
      if (url.pathname === "/api/platform-admin/platform-admin-users" && request.method() === "GET") {
        directoryRequests += 1;
        if (directoryRequests === 1) return success(platformAdminUsers);
        return failure(503, "platform_admin_data_unavailable", "raw provider refresh detail");
      }
      if (url.pathname === "/api/platform-admin/platform-admin-users/7002/active") {
        activeRequests += 1;
        return success({
          platform_admin_user: { platform_admin_user_id: 7002, user_id: 9002, is_active: true }
        });
      }
      return defaultHandler({ url });
    });

    await page.getByRole("button", { name: "Activate", exact: true }).click();
    expect(activeRequests).toBe(1);
    await expect(page.getByText("Loading platform admins...")).toHaveCount(0);
    await expect(page.getByText("Platform-admin directory refresh failed. Retry to load the current state.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(page.getByText("raw provider refresh detail")).toHaveCount(0);
  });

  test("authorization denial during post-mutation refresh clears protected state", async ({ page }) => {
    let directoryRequests = 0;
    await openPlatformPage(page, "/platform-admin-users.html", ({ request, url }) => {
      if (url.pathname === "/api/platform-admin/platform-admin-users" && request.method() === "GET") {
        directoryRequests += 1;
        if (directoryRequests === 1) return success(platformAdminUsers);
        return failure(403, "platform_admin_access_denied", "raw access denial detail");
      }
      if (url.pathname === "/api/platform-admin/platform-admin-users/7002/active") {
        return success({
          platform_admin_user: { platform_admin_user_id: 7002, user_id: 9002, is_active: true }
        });
      }
      return defaultHandler({ url });
    });

    await page.getByRole("button", { name: "Activate", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Access Denied" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Platform Admin Management" })).toHaveCount(0);
    await expect(page.getByText("raw access denial detail")).toHaveCount(0);
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
    expect(paths).not.toContain("/api/platform-admin/companies/42/billing-orders");
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

  test("lazy billing orders load with filters pagination sen amounts and safe rendering", async ({ page }) => {
    const calls = await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => defaultHandler({ url }));
    await expect(page.getByRole("heading", { name: "Billing orders" })).toBeVisible();
    expect(calls.map(call => call.path)).not.toContain("/api/platform-admin/companies/42/billing-orders");

    await page.getByRole("button", { name: "Load billing orders" }).click();
    const billingSection = page.locator("section.platform-panel")
      .filter({ has: page.getByRole("heading", { name: "Billing orders" }) });
    await expect(billingSection.getByRole("cell", { name: "credited<script>window.__billingStatusXss=true</script>" })).toBeVisible();
    await expect(billingSection.getByRole("cell", { name: "3900 sen" })).toBeVisible();
    await expect(billingSection.getByRole("cell", { name: "Pro <img src=x onerror=window.__billingPlanXss=true>" })).toBeVisible();
    await expect(billingSection.getByText("RM39.00")).toHaveCount(0);
    await expect(billingSection.getByText("MYR")).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__billingStatusXss)).toBeUndefined();
    await expect.poll(() => page.evaluate(() => window.__billingPlanXss)).toBeUndefined();

    await page.locator("#platform-billing-orders-status").fill("pending");
    await page.locator("#platform-billing-orders-created-after").fill("2026-07-01T00:00:00+00:00");
    await page.locator("#platform-billing-orders-created-before").fill("2026-08-01T00:00:00+00:00");
    await page.locator("#platform-billing-orders-limit").selectOption("50");
    await page.locator("section.platform-panel")
      .filter({ has: page.getByRole("heading", { name: "Billing orders" }) })
      .getByRole("button", { name: "Apply filters" })
      .click();
    await page.locator("section.platform-panel")
      .filter({ has: page.getByRole("heading", { name: "Billing orders" }) })
      .getByRole("button", { name: "Next" })
      .click();

    const orderUrls = calls
      .filter(call => call.path === "/api/platform-admin/companies/42/billing-orders")
      .map(call => new URL("http://test" + call.search));
    expect(orderUrls.length).toBeGreaterThanOrEqual(3);
    expect(orderUrls.some(url => url.searchParams.get("status") === "pending")).toBe(true);
    expect(orderUrls.some(url => url.searchParams.get("created_after") === "2026-07-01T00:00:00+00:00")).toBe(true);
    expect(orderUrls.some(url => url.searchParams.get("created_before") === "2026-08-01T00:00:00+00:00")).toBe(true);
    expect(orderUrls.some(url => url.searchParams.get("limit") === "50")).toBe(true);
    expect(orderUrls.every(url => !url.searchParams.has("sort_by"))).toBe(true);
    expect(orderUrls.every(url => !url.searchParams.has("search"))).toBe(true);
    expect(orderUrls.every(url => !url.searchParams.has("export"))).toBe(true);
    await assertReadOnlyBoundary(page);
  });

  test("billing orders empty unavailable validation and child 404 states are sanitized", async ({ page }) => {
    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/billing-orders") {
        return success({
          ...billingOrders,
          billing_orders: [],
          pagination: { limit: 25, offset: 0, returned: 0, total: 0, has_more: false }
        });
      }
      return defaultHandler({ url });
    });
    await page.getByRole("button", { name: "Load billing orders" }).click();
    await expect(page.getByText("No billing orders recorded.")).toBeVisible();

    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/billing-orders") {
        return failure(400, "invalid_status", "raw validation detail");
      }
      return defaultHandler({ url });
    });
    await page.getByRole("button", { name: "Load billing orders" }).click();
    await expect(page.getByText("Billing order filters could not be validated.")).toBeVisible();
    await expect(page.getByText("raw validation detail")).toHaveCount(0);

    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/billing-orders") {
        return failure(503, "platform_admin_data_unavailable", "raw Supabase details");
      }
      return defaultHandler({ url });
    });
    await page.getByRole("button", { name: "Load billing orders" }).click();
    await expect(page.getByText("Billing orders could not be loaded safely.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(page.getByText("raw Supabase details")).toHaveCount(0);

    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/billing-orders") {
        return failure(404, "company_not_found", "raw deleted company details");
      }
      return defaultHandler({ url });
    });
    await expect(page.getByRole("heading", { name: "AI-credit and usage" })).toBeVisible();
    await page.getByRole("button", { name: "Load billing orders" }).click();
    await expect(page.getByRole("heading", { name: "Company Not Found" })).toBeVisible();
    await expect(page.getByText("Example Tenant")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Billing orders" })).toHaveCount(0);
    await expect(page.getByText("Billing orders could not be loaded safely.")).toHaveCount(0);
    await expect(page.getByText("raw deleted company details")).toHaveCount(0);
  });

  test("billing order filter replaces pending request and suppresses late obsolete response", async ({ page }) => {
    let releasePending;
    const slowObsolete = new Promise(resolve => {
      releasePending = () => resolve(success({
        ...billingOrders,
        billing_orders: [{
          ...billingOrders.billing_orders[0],
          status: "obsolete<script>window.__obsoleteBillingXss=true</script>"
        }]
      }));
    });
    await openPlatformPage(page, "/platform-admin-company.html?company_id=42", ({ url }) => {
      if (url.pathname === "/api/platform-admin/companies/42/billing-orders") {
        if (url.searchParams.get("status") === "obsolete") return slowObsolete;
        if (url.searchParams.get("status") === "pending") return success(filteredBillingOrders);
        return success(billingOrders);
      }
      return defaultHandler({ url });
    });

    await page.getByRole("button", { name: "Load billing orders" }).click();
    await expect(page.getByRole("cell", { name: "credited<script>window.__billingStatusXss=true</script>" })).toBeVisible();
    await page.evaluate(() => {
      window.__obsoleteBillingRenderState = "pending";
      PlatformAdminShell.runRequest("company-billing-orders", signal => (
        PlatformAdminApi.listCompanyBillingOrders(42, {
          limit: 25,
          offset: 0,
          status: "obsolete",
          signal
        })
      )).then(data => {
        const marker = document.createElement("div");
        marker.id = "obsolete-billing-render";
        marker.textContent = data.billing_orders[0].status;
        document.body.append(marker);
        window.__obsoleteBillingRenderState = "rendered";
      }).catch(error => {
        window.__obsoleteBillingRenderState = error && error.category ? error.category : "rejected";
      });
    });
    await page.locator("#platform-billing-orders-status").fill("pending");
    await page.locator("section.platform-panel")
      .filter({ has: page.getByRole("heading", { name: "Billing orders" }) })
      .getByRole("button", { name: "Apply filters" })
      .click();

    await expect(page.getByRole("cell", { name: "pending<img src=x onerror=window.__lateBillingXss=true>" })).toBeVisible();
    await expect(page.getByText("Not available").first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__lateBillingXss)).toBeUndefined();

    releasePending();
    await page.waitForTimeout(100);
    await expect.poll(() => page.evaluate(() => window.__obsoleteBillingRenderState)).toBe("aborted");
    await expect(page.locator("#obsolete-billing-render")).toHaveCount(0);
    await expect(page.getByText("obsolete<script>window.__obsoleteBillingXss=true</script>")).toHaveCount(0);
    await expect(page.getByRole("cell", { name: "pending<img src=x onerror=window.__lateBillingXss=true>" })).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__obsoleteBillingXss)).toBeUndefined();
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
