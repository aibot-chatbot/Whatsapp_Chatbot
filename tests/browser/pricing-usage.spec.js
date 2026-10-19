/* Behaviour coverage for the usage-first console added to pricing.html.
 *
 * tests/browser/landing-pricing.spec.js already pins the plan-card DOM
 * contract (four cards, twelve feature rows, XSS-safe plan text) and is
 * left untouched. This file covers what the redesign adds on top: the
 * usage meters, the recommendation, and the upgrade diff.
 *
 * Everything asserted here is derived from a real endpoint. Per DESIGN.md's
 * Preserve-truth principle a dimension the backend cannot report must be
 * hidden rather than guessed at, and that is asserted too.
 */

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

/* Mirrors the seeded plan table. price is a STRING, as the API returns it. */
const PLANS = [
    {
        id: 1, code: "free", name: "Free", description: "Basic plan for trying the platform.",
        price: "0", currency: "MYR", billing_interval: "monthly",
        chatbot_limit: 1, team_member_limit: 1, channel_limit: 1,
        knowledge_file_limit: 3, knowledge_storage_limit_bytes: 52428800,
        model_access_tier: "economy", included_ai_credit_micro_myr: 1000000,
        feature_flags: {}
    },
    {
        id: 2, code: "essential", name: "Essential", description: "Essential plan.",
        price: "133.50", currency: "MYR", billing_interval: "monthly",
        billing_terms: [{ months: 1, amount_sen: 13350, monthly_equivalent_sen: 13350, discount_percent: 25 }, { months: 3, amount_sen: 37380, monthly_equivalent_sen: 12460, discount_percent: 30 }, { months: 6, amount_sen: 69420, monthly_equivalent_sen: 11570, discount_percent: 35 }, { months: 12, amount_sen: 106800, monthly_equivalent_sen: 8900, discount_percent: 50 }],
        chatbot_limit: 1, team_member_limit: 1, channel_limit: 1,
        knowledge_file_limit: 5, knowledge_storage_limit_bytes: 52428800,
        model_access_tier: "economy", included_ai_credit_micro_myr: 5000000,
        feature_flags: {}
    },
    {
        id: 3, code: "advanced", name: "Advanced", description: "Advanced plan.",
        price: "283.50", currency: "MYR", billing_interval: "monthly",
        billing_terms: [{ months: 1, amount_sen: 28350, monthly_equivalent_sen: 28350, discount_percent: 25 }, { months: 3, amount_sen: 79380, monthly_equivalent_sen: 26460, discount_percent: 30 }, { months: 6, amount_sen: 147420, monthly_equivalent_sen: 24570, discount_percent: 35 }, { months: 12, amount_sen: 226800, monthly_equivalent_sen: 18900, discount_percent: 50 }],
        chatbot_limit: 2, team_member_limit: 3, channel_limit: 2,
        knowledge_file_limit: 25, knowledge_storage_limit_bytes: 262144000,
        model_access_tier: "standard", included_ai_credit_micro_myr: 20000000,
        feature_flags: { single_website_scraping: true, crm_lead_assignment: true }
    },
    {
        id: 4, code: "pro", name: "Pro", description: "Premium plan.",
        price: "561.00", currency: "MYR", billing_interval: "monthly",
        billing_terms: [{ months: 1, amount_sen: 56100, monthly_equivalent_sen: 56100, discount_percent: 25 }, { months: 3, amount_sen: 157080, monthly_equivalent_sen: 52360, discount_percent: 30 }, { months: 6, amount_sen: 291720, monthly_equivalent_sen: 48620, discount_percent: 35 }, { months: 12, amount_sen: 448800, monthly_equivalent_sen: 37400, discount_percent: 50 }],
        chatbot_limit: 3, team_member_limit: 5, channel_limit: 4,
        knowledge_file_limit: 75, knowledge_storage_limit_bytes: 1073741824,
        model_access_tier: "premium", included_ai_credit_micro_myr: 60000000,
        feature_flags: {
            single_website_scraping: true, batch_website_scraping: true,
            ai_assisted_menu_generation: true, ai_generated_reports: true,
            crm_lead_assignment: true
        }
    }
];

function subscription(code = "essential", overrides = {}) {
    const plan = PLANS.find(p => p.code === code);
    return Object.assign({
        id: 10, company_id: 42, plan_id: plan.id, status: "active",
        current_period_start: "2026-08-01T00:00:00Z",
        current_period_end: "2026-09-01T00:00:00Z",
        trial_ends_at: null, cancellation_effective_at: null,
        pending_plan: null, plan_change_effective_at: null,
        can_renew: false, renewal_required: false, plan
    }, overrides);
}

function usage(overrides = {}) {
    const base = {
        chatbots: { used: 1, limit: 1 },
        team_members: { used: 1, limit: 1, pending_invitations: 0 },
        channels: { used: 0, limit: 1 },
        knowledge_files: { used: 2, limit: 5 },
        knowledge_storage_bytes: { used: 10485760, limit: 52428800 },
        ai_tokens: { input_tokens: 100, output_tokens: 50, total_tokens: 150 }
    };
    return {
        period: {
            start: "2026-08-01T00:00:00Z", end: "2026-09-01T00:00:00Z",
            end_source: "stored"
        },
        plan: { id: 2, name: "Essential", code: "essential", billing_interval: "monthly" },
        usage: Object.assign(base, overrides)
    };
}

const CREDIT = {
    initialised: true, subscription_id: 10,
    included_balance_micro_myr: 2000000,
    topup_balance_micro_myr: 0,
    total_balance_micro_myr: 2000000,
    period_start: "2026-08-01T00:00:00Z", period_end: "2026-09-01T00:00:00Z",
    currency: "MYR", unit: "micro_myr"
};

async function openPricing(page, options = {}) {
    const plans = options.plans || PLANS;
    const sub = options.subscription === undefined ? subscription() : options.subscription;
    const use = options.usage === undefined ? usage() : options.usage;
    const credit = options.credit === undefined ? CREDIT : options.credit;
    const onRoute = options.onRoute;

    await page.route("https://fonts.googleapis.com/**", route => route.abort());
    await page.route("https://fonts.gstatic.com/**", route => route.abort());
    await page.route("https://unpkg.com/**", route => route.fulfill({
        status: 200, contentType: "application/javascript",
        body: "window.lucide={createIcons:function(){}};"
    }));

    await page.addInitScript(() => {
        sessionStorage.setItem("token", "fake-tenant-token");
        sessionStorage.setItem("isLoggedIn", "true");
        sessionStorage.setItem("user", JSON.stringify({
            id: 1, company_id: 42, email: "owner@example.test", role: "owner"
        }));
    });

    await page.route("**/api/**", route => {
        const url = new URL(route.request().url());
        if (onRoute) {
            const handled = onRoute(route, url);
            if (handled) return handled;
        }
        if (url.pathname === "/api/billing/plans") {
            return route.fulfill(json(200, { status: "success", data: plans }));
        }
        if (url.pathname === "/api/billing/subscription") {
            return route.fulfill(json(200, { status: "success", data: sub }));
        }
        if (url.pathname === "/api/billing/usage") {
            return route.fulfill(json(200, { status: "success", data: use }));
        }
        if (url.pathname === "/api/billing/ai-credit/summary") {
            return route.fulfill(json(200, { status: "success", data: credit }));
        }
        if (url.pathname === "/api/platform-admin/me") {
            return route.fulfill(json(403, { status: "error" }));
        }
        return route.fulfill(json(200, { status: "success", data: [] }));
    });

    await page.goto("/pricing.html");
    await expect(page.locator(".plan-card")).toHaveCount(4);
}

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

async function openPricingWithDeferredUsageAndCredit(page, options = {}) {
    const plans = options.plans || PLANS;
    const sub = options.subscription === undefined ? subscription() : options.subscription;
    const use = options.usage === undefined ? usage() : options.usage;
    const credit = options.credit === undefined ? CREDIT : options.credit;
    const usageGate = deferred();
    const creditGate = deferred();
    const checkoutCalls = [];

    await page.route("https://fonts.googleapis.com/**", route => route.abort());
    await page.route("https://fonts.gstatic.com/**", route => route.abort());
    await page.route("https://unpkg.com/**", route => route.fulfill({
        status: 200, contentType: "application/javascript",
        body: "window.lucide={createIcons:function(){}};"
    }));

    await page.addInitScript(() => {
        sessionStorage.setItem("token", "fake-tenant-token");
        sessionStorage.setItem("isLoggedIn", "true");
        sessionStorage.setItem("user", JSON.stringify({
            id: 1, company_id: 42, email: "owner@example.test", role: "owner"
        }));
    });

    await page.route("**/api/**", route => {
        const url = new URL(route.request().url());
        if (url.pathname === "/api/billing/plans") {
            return route.fulfill(json(200, { status: "success", data: plans }));
        }
        if (url.pathname === "/api/billing/subscription") {
            return route.fulfill(json(200, { status: "success", data: sub }));
        }
        if (url.pathname === "/api/billing/usage") {
            return usageGate.promise.then(() => {
                if (use === "failure") {
                    return route.fulfill(json(500, { status: "error", message: "usage unavailable" }));
                }
                return route.fulfill(json(200, { status: "success", data: use }));
            });
        }
        if (url.pathname === "/api/billing/ai-credit/summary") {
            return creditGate.promise.then(() => {
                if (credit === "failure") {
                    return route.fulfill(json(500, { status: "error", message: "credit unavailable" }));
                }
                return route.fulfill(json(200, { status: "success", data: credit }));
            });
        }
        if (url.pathname === "/api/billing/subscription/checkout") {
            checkoutCalls.push({
                method: route.request().method(),
                body: JSON.parse(route.request().postData() || "{}")
            });
            return route.fulfill(json(200, {
                status: "success",
                data: {
                    checkout_url: "https://toyyibpay.example/checkout",
                    order_reference: "sub-order-1"
                }
            }));
        }
        if (url.pathname.startsWith("/api/billing/dev")) {
            throw new Error("renewal CTA must not call development billing completion routes");
        }
        if (url.pathname.includes("callback")) {
            throw new Error("checkout alone must not simulate a payment callback");
        }
        if (url.pathname === "/api/platform-admin/me") {
            return route.fulfill(json(403, { status: "error" }));
        }
        return route.fulfill(json(200, { status: "success", data: [] }));
    });

    await page.goto("/pricing.html");
    await expect(page.locator(".plan-card")).toHaveCount(4);
    return { usageGate, creditGate, checkoutCalls };
}

test.describe("current plan summary", () => {
    test("names the plan, its term and paid-through date", async ({ page }) => {
        await openPricing(page);
        const current = page.locator("#pri-current");
        await expect(current).toContainText("Essential");
        await expect(current).toContainText("1-month prepaid term");
        await expect(current).toContainText("Paid through");
    });

    test("a scheduled downgrade is stated instead of the paid-through date", async ({ page }) => {
        await openPricing(page, {
            subscription: subscription("advanced", {
                pending_plan: { id: 2, code: "essential", name: "Essential" },
                plan_change_effective_at: "2026-09-01T00:00:00Z"
            })
        });
        await expect(page.locator("#pri-current")).toContainText("Changes to Essential");
    });

    test("survives a tenant with no subscription at all", async ({ page }) => {
        /* Both endpoints answer 200 with data:null in this case. */
        await openPricing(page, { subscription: null, usage: null, credit: null });
        await expect(page.locator("#pri-current")).toContainText("No active plan");
        await expect(page.locator("#pri-usage-section")).toBeHidden();
    });

    test("expired current plan says expired instead of paid through", async ({ page }) => {
        await openPricing(page, {
            subscription: subscription("pro", {
                status: "active",
                effective_status: "expired",
                current_period_end: "2026-08-01T00:00:00Z",
                can_renew: true,
                renewal_required: true
            }),
            usage: null
        });
        await expect(page.locator("#pri-current")).toContainText("Expired on");
        await expect(page.locator("#pri-current")).not.toContainText("Paid through");
    });
});

test.describe("phased loading", () => {
    test("free user can click Essential before delayed usage and credit resolve", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page, {
            subscription: null,
            usage: null,
            credit: null
        });

        await page.locator('.plan-card[data-plan-code="essential"]')
            .getByRole("button", { name: /Upgrade to Essential/ })
            .click();

        expect(delayed.checkoutCalls).toEqual([
            { method: "POST", body: { plan_code: "essential", billing_term_months: 1 } }
        ]);
        delayed.usageGate.resolve();
        delayed.creditGate.resolve();
    });

    test("selected 12-month term updates price and checkout payload", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page, {
            subscription: null,
            usage: null,
            credit: null
        });

        await page.getByRole("radio", { name: "12 months" }).click();
        const essential = page.locator('.plan-card[data-plan-code="essential"]');
        await expect(essential.locator(".plan-price")).toContainText("RM 89.00 / month");
        await expect(essential.locator(".pri-upfront")).toContainText("RM 1068.00 charged upfront for 12 months");
        await essential.getByRole("button", { name: /Upgrade to Essential/ }).click();

        expect(delayed.checkoutCalls).toEqual([
            { method: "POST", body: { plan_code: "essential", billing_term_months: 12 } }
        ]);
        delayed.usageGate.resolve();
        delayed.creditGate.resolve();
    });

    test("active Essential can click Advanced before delayed usage and credit resolve", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page);

        await page.locator('.plan-card[data-plan-code="advanced"]')
            .getByRole("button", { name: /Upgrade to Advanced/ })
            .click();

        expect(delayed.checkoutCalls).toEqual([
            { method: "POST", body: { plan_code: "advanced", billing_term_months: 1 } }
        ]);
        delayed.usageGate.resolve();
        delayed.creditGate.resolve();
    });

    test("expired Pro shows Renew Pro before delayed usage and credit resolve", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page, {
            subscription: subscription("pro", {
                status: "active",
                effective_status: "expired",
                current_period_end: "2026-08-01T00:00:00Z",
                can_renew: true,
                renewal_required: true
            }),
            usage: null,
            credit: null
        });
        const pro = page.locator('.plan-card[data-plan-code="pro"]');
        await expect(pro.getByRole("button", { name: "Renew Pro" })).toBeVisible();
        await pro.getByRole("button", { name: "Renew Pro" }).click();

        expect(delayed.checkoutCalls).toEqual([
            { method: "POST", body: { plan_code: "pro", billing_term_months: 1 } }
        ]);
        delayed.usageGate.resolve();
        delayed.creditGate.resolve();
    });

    test("active Pro remains current before delayed usage and credit resolve", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page, {
            subscription: subscription("pro")
        });
        const pro = page.locator('.plan-card[data-plan-code="pro"]');
        await expect(pro).toContainText("Current plan");
        await expect(pro.locator("button")).toHaveCount(0);
        delayed.usageGate.resolve();
        delayed.creditGate.resolve();
    });

    test("delayed usage later updates the recommendation without blocking plan actions", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page, {
            usage: usage({
                knowledge_files: { used: 24, limit: 25 }
            })
        });

        await expect(page.locator(".plan-card.is-recommended")).toHaveAttribute(
            "data-plan-code", "advanced");
        delayed.usageGate.resolve();
        await expect(page.locator("#pri-advice")).toContainText("knowledge files");
        delayed.creditGate.resolve();
    });

    test("delayed credit later updates only the AI-credit usage row", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page);
        delayed.usageGate.resolve();
        await expect(page.locator("#pri-usage-section")).toBeVisible();
        await expect(page.locator(".pri-meter-row").filter({ hasText: "AI credit left" }))
            .toHaveCount(0);
        delayed.creditGate.resolve();
        await expect(page.locator(".pri-meter-row").filter({ hasText: "AI credit left" }))
            .toContainText("RM 2.00");
    });

    test("delayed usage and credit do not replace an already actionable button", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page);
        const button = page.locator('.plan-card[data-plan-code="advanced"]')
            .getByRole("button", { name: /Upgrade to Advanced/ });
        await button.evaluate(node => {
            node.dataset.stabilityProbe = "kept";
        });
        delayed.usageGate.resolve();
        delayed.creditGate.resolve();
        await expect(page.locator("#pri-usage-section")).toBeVisible();
        await expect(button).toHaveAttribute("data-stability-probe", "kept");
        await button.click();
        expect(delayed.checkoutCalls).toEqual([
            { method: "POST", body: { plan_code: "advanced", billing_term_months: 1 } }
        ]);
    });

    test("usage failure does not block plan actions", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page, {
            usage: "failure"
        });
        delayed.usageGate.resolve();
        delayed.creditGate.resolve();
        await page.locator('.plan-card[data-plan-code="advanced"]')
            .getByRole("button", { name: /Upgrade to Advanced/ })
            .click();
        expect(delayed.checkoutCalls).toEqual([
            { method: "POST", body: { plan_code: "advanced", billing_term_months: 1 } }
        ]);
    });

    test("credit failure does not block plan actions", async ({ page }) => {
        const delayed = await openPricingWithDeferredUsageAndCredit(page, {
            credit: "failure"
        });
        delayed.usageGate.resolve();
        delayed.creditGate.resolve();
        await page.locator('.plan-card[data-plan-code="advanced"]')
            .getByRole("button", { name: /Upgrade to Advanced/ })
            .click();
        expect(delayed.checkoutCalls).toEqual([
            { method: "POST", body: { plan_code: "advanced", billing_term_months: 1 } }
        ]);
    });
});

test.describe("usage meters", () => {
    test("renders one row per reportable dimension, with real figures", async ({ page }) => {
        await openPricing(page);
        const section = page.locator("#pri-usage-section");
        await expect(section).toBeVisible();

        await expect(section).toContainText("Chatbots");
        await expect(section).toContainText("Team members");
        await expect(section).toContainText("Channels");
        await expect(section).toContainText("Knowledge files");
        await expect(section).toContainText("Storage");

        /* Storage is reported in bytes and shown in binary units. */
        await expect(section).toContainText("10 MB");
        await expect(section).toContainText("50 MB");
    });

    test("a dimension at its limit is named in words, not just colour", async ({ page }) => {
        await openPricing(page);
        /* chatbots is 1 of 1 in the default fixture. */
        await expect(page.locator(".pri-meter-state.is-full").first()).toHaveText("At limit");
    });

    test("a dimension near its limit says so", async ({ page }) => {
        await openPricing(page, {
            usage: usage({ knowledge_files: { used: 4, limit: 5 } })
        });
        await expect(page.locator(".pri-meter-state.is-warn").first()).toHaveText("Nearly full");
    });

    test("an unlimited dimension shows no bar that could read as empty", async ({ page }) => {
        await openPricing(page, {
            usage: usage({ chatbots: { used: 7, limit: null } })
        });
        const row = page.locator(".pri-meter-row").filter({ hasText: "Chatbots" });
        await expect(row).toContainText("Unlimited");
        await expect(row.locator(".pri-meter-none")).toHaveCount(1);
        await expect(row.locator(".cr-meter")).toHaveCount(0);
    });

    test("AI credit is shown as money and never as tokens", async ({ page }) => {
        await openPricing(page);
        const row = page.locator(".pri-meter-row").filter({ hasText: "AI credit left" });
        await expect(row).toContainText("RM 2.00");
        await expect(row).toContainText("RM 5.00");
        /* usage.ai_tokens must never surface as a credit figure. */
        await expect(page.locator("#pri-usage-section")).not.toContainText("tokens");
    });

    test("the credit row is omitted when the balance is uninitialised", async ({ page }) => {
        await openPricing(page, {
            credit: { initialised: false, total_balance_micro_myr: null }
        });
        await expect(page.locator(".pri-meter-row").filter({ hasText: "AI credit left" }))
            .toHaveCount(0);
    });
});

test.describe("recommendation", () => {
    test("names the pressured limits and the plan that lifts them", async ({ page }) => {
        await openPricing(page);
        const advice = page.locator("#pri-advice");
        await expect(advice).toContainText("close to your limit");
        await expect(advice).toContainText("chatbots");
        /* Advanced is the cheapest tier that raises both chatbots and seats. */
        await expect(advice).toContainText("Advanced");
        await expect(page.locator(".plan-card.is-recommended")).toHaveAttribute(
            "data-plan-code", "advanced");
    });

    test("says so plainly when nothing is under pressure", async ({ page }) => {
        await openPricing(page, {
            usage: usage({
                chatbots: { used: 0, limit: 10 },
                team_members: { used: 1, limit: 20, pending_invitations: 0 },
                channels: { used: 0, limit: 5 },
                knowledge_files: { used: 1, limit: 50 },
                knowledge_storage_bytes: { used: 1024, limit: 1073741824 }
            })
        });
        await expect(page.locator("#pri-advice")).toContainText("room on every limit");
        await expect(page.locator(".plan-card.is-recommended")).toHaveCount(0);
        await expect(page.locator("#pri-diff-section")).toBeHidden();
    });
});

test.describe("tiers", () => {
    test("keeps lower tiers in the DOM but out of the way", async ({ page }) => {
        await openPricing(page);
        /* Four cards always exist: landing-pricing.spec.js counts them. */
        await expect(page.locator(".plan-card")).toHaveCount(4);
        const free = page.locator('.plan-card[data-plan-code="free"]');
        await expect(free).toHaveCount(1);
        await expect(free).toBeHidden();

        await page.locator("#pri-show-all").click();
        await expect(free).toBeVisible();
        await expect(page.locator("#pri-show-all")).toHaveAttribute("aria-expanded", "true");
    });

    test("the current plan is marked and offers no action", async ({ page }) => {
        await openPricing(page);
        const current = page.locator('.plan-card[data-plan-code="essential"]');
        await expect(current).toHaveClass(/is-current/);
        await expect(current).toContainText("Current plan");
        await expect(current.locator("button")).toHaveCount(0);
    });

    test("free is never offered as a downgrade target", async ({ page }) => {
        await openPricing(page);
        await page.locator("#pri-show-all").click();
        const free = page.locator('.plan-card[data-plan-code="free"]');
        await expect(free).toContainText("For new accounts only");
        await expect(free.locator("button")).toHaveCount(0);
    });

    test("offers every approved prepaid billing term",
        async ({ page }) => {
            await openPricing(page);
            await expect(page.getByRole("radio")).toHaveText([
                "1 month", "3 months", "6 months", "12 months"
            ]);
            await expect(page.locator("#pri-tiers-title")).toBeVisible();
        });
});

test.describe("upgrade diff", () => {
    test("states exactly what a move to the recommended plan changes",
        async ({ page }) => {
            await openPricing(page);
            const diff = page.locator("#pri-diff-section");
            await expect(diff).toBeVisible();
            await expect(page.locator("#pri-diff-title")).toContainText("Advanced");

            /* Essential -> Advanced: +1 bot, +2 seats, +1 channel, +20 files,
               +200 MB storage, +RM 15.00 credit, and two new capabilities. */
            const items = page.locator(".pri-diff-item");
            await expect(items.filter({ hasText: "chatbots" })).toContainText("+1");
            await expect(items.filter({ hasText: "team members" })).toContainText("+2");
            await expect(items.filter({ hasText: "AI credit" })).toContainText("RM 15.00");
            await expect(items.filter({ hasText: "Single Website Scraping" }))
                .toContainText("New");
        });
});

test.describe("downgrade", () => {
    test("blocked usage is explained without a browser alert", async ({ page }) => {
        await openPricing(page, {
            subscription: subscription("advanced"),
            onRoute: (route, url) => {
                if (url.pathname.startsWith("/api/billing/subscription/downgrade-check/")) {
                    return route.fulfill(json(200, {
                        status: "success",
                        data: {
                            eligible: false, target_plan: "essential",
                            effective_at: "2026-09-01T00:00:00Z",
                            blocking_items: [
                                { resource: "team_members", used: 3, limit: 1, excess: 2 },
                                /* The API can report the same cause twice. */
                                {
                                    resource: "team_members_including_pending",
                                    used: 3, limit: 1, excess: 2
                                }
                            ],
                            message: "Downgrade is blocked by usage."
                        }
                    }));
                }
                return null;
            }
        });

        // A lower tier is collapsed by default on an upgrade-oriented console,
        // so reaching a downgrade means opening the disclosure first.
        await page.locator("#pri-show-all").click();
        await page.locator('.plan-card[data-plan-code="essential"] button').click();
        const dialog = page.getByRole("dialog");
        await expect(dialog).toBeVisible();
        await expect(dialog).toContainText("more than Essential allows");
        /* De-duplicated: one line, not two, for the same underlying cause. */
        const body = await page.locator("#pri-confirm-body").textContent();
        expect(body.match(/team members/g)).toHaveLength(1);
    });
});

test.describe("layout", () => {
    test("stays inside the viewport at every supported width", async ({ page }) => {
        for (const width of [1440, 1280, 1024, 768, 390, 320]) {
            await page.setViewportSize({ width, height: width <= 390 ? 900 : 820 });
            await openPricing(page);
            const overflow = await page.evaluate(() =>
                document.documentElement.scrollWidth - document.documentElement.clientWidth);
            expect(overflow, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(0);
        }
    });
});
