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
        price: "39", currency: "MYR", billing_interval: "monthly",
        chatbot_limit: 1, team_member_limit: 1, channel_limit: 1,
        knowledge_file_limit: 5, knowledge_storage_limit_bytes: 52428800,
        model_access_tier: "economy", included_ai_credit_micro_myr: 5000000,
        feature_flags: {}
    },
    {
        id: 3, code: "advanced", name: "Advanced", description: "Advanced plan.",
        price: "89", currency: "MYR", billing_interval: "monthly",
        chatbot_limit: 2, team_member_limit: 3, channel_limit: 2,
        knowledge_file_limit: 25, knowledge_storage_limit_bytes: 262144000,
        model_access_tier: "standard", included_ai_credit_micro_myr: 20000000,
        feature_flags: { single_website_scraping: true, crm_lead_assignment: true }
    },
    {
        id: 4, code: "pro", name: "Pro", description: "Premium plan.",
        price: "169", currency: "MYR", billing_interval: "monthly",
        chatbot_limit: 3, team_member_limit: 5, channel_limit: 2,
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

test.describe("current plan summary", () => {
    test("names the plan, its price and the renewal date", async ({ page }) => {
        await openPricing(page);
        const current = page.locator("#pri-current");
        await expect(current).toContainText("Essential");
        await expect(current).toContainText("RM 39.00");
        await expect(current).toContainText("Renews on");
    });

    test("a scheduled downgrade is stated instead of the renewal date", async ({ page }) => {
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

    test("there is no annual billing control, because there is no annual plan",
        async ({ page }) => {
            await openPricing(page);
            const body = page.locator("body");
            await expect(body).not.toContainText("Annual");
            await expect(body).not.toContainText("Yearly");
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
