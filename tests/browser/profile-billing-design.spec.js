/* Design validation for the redesigned frontend/profile.html and the new
 * frontend/billing.html.
 *
 * The Python suites assert source text. This spec drives the real pages in a
 * browser and checks the things source text cannot see: that nothing overflows
 * at any breakpoint, that focus is actually visible, that the keyboard reaches
 * every control, that reduced-motion is honoured, and that both pages render
 * in the same control-room design language as team.html and pricing.html.
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

const BREAKPOINTS = [
    { name: "mobile", width: 320, height: 720 },
    { name: "tablet", width: 768, height: 900 },
    { name: "laptop", width: 1024, height: 800 },
    { name: "desktop", width: 1440, height: 900 }
];

const ME = {
    id: 1, company_id: 42, full_name: "Vincent Owner", email: "owner@example.test",
    role: "owner", phone: "+60123456789", status: "active", is_verified: true,
    created_at: "2026-01-04T09:00:00Z", updated_at: "2026-08-20T09:00:00Z"
};

const ROSTER = [
    ME,
    {
        id: 2, company_id: 42, full_name: "Aisha Admin", email: "aisha@example.test",
        role: "admin", status: "active", is_verified: true,
        created_at: "2026-02-11T09:00:00Z", updated_at: "2026-02-11T09:00:00Z"
    },
    {
        id: 3, company_id: 42, full_name: "Kai Member", email: "kai@example.test",
        role: "member", status: "active", is_verified: false,
        created_at: "2026-03-02T09:00:00Z", updated_at: "2026-03-02T09:00:00Z"
    }
];

const WORKSPACE = {
    company: { name: "Example Co", contact_email: "ops@example.test", contact_phone: "" },
    current_user_role: "owner",
    active_member_count: 3,
    pending_invitation_count: 1,
    plan_member_limit: 8,
    remaining_seats: 4,
    can_edit_company: true,
    can_manage_team: true
};

const SUBSCRIPTION = {
    plan: { code: "growth", name: "Growth", billing_interval: "month", team_member_limit: 8 },
    status: "active", effective_status: "active",
    current_period_start: "2026-08-01T00:00:00Z",
    current_period_end: "2026-09-01T00:00:00Z"
};

async function stubExternals(page) {
    await page.route("https://fonts.googleapis.com/**", route => route.abort());
    await page.route("https://fonts.gstatic.com/**", route => route.abort());
    await page.route("https://unpkg.com/**", route => route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body: "window.lucide={createIcons:function(){}};"
    }));
}

async function installSession(page) {
    await page.addInitScript(() => {
        sessionStorage.setItem("token", "fake-tenant-token");
        sessionStorage.setItem("isLoggedIn", "true");
        sessionStorage.setItem("user", JSON.stringify({
            id: 1, company_id: 42, email: "owner@example.test",
            full_name: "Vincent Owner", role: "owner"
        }));
    });
}

async function stubApis(page) {
    await page.route("**/api/**", route => {
        const url = new URL(route.request().url());
        const p = url.pathname;

        if (p === "/api/user") return route.fulfill(json(200, { status: "success", data: ME }));
        if (p === "/api/users") return route.fulfill(json(200, { status: "success", data: ROSTER }));
        if (p === "/api/workspace") return route.fulfill(json(200, { status: "success", data: WORKSPACE }));
        if (p === "/api/invites") return route.fulfill(json(200, { status: "success", data: [] }));
        if (p === "/api/billing/subscription") {
            return route.fulfill(json(200, { status: "success", data: SUBSCRIPTION }));
        }
        if (p === "/api/billing/ai-credit/summary") {
            return route.fulfill(json(200, { status: "success", data: {
                total_balance_micro_myr: 12500000,
                included_balance_micro_myr: 10000000,
                topup_balance_micro_myr: 2500000,
                period_start: "2026-08-01T00:00:00Z",
                period_end: "2026-09-01T00:00:00Z"
            }}));
        }
        if (p === "/api/platform-admin/me") {
            return route.fulfill(json(403, { status: "error", code: "platform_admin_access_denied" }));
        }
        /* Everything else answers empty-but-successful so each panel resolves
           into its empty state rather than hanging on a skeleton. */
        return route.fulfill(json(200, { status: "success", data: [] }));
    });
}

async function openPage(page, path) {
    await stubExternals(page);
    await installSession(page);
    await stubApis(page);
    await page.goto(path);
    await expect(page.locator("main.kw-page")).toBeVisible();
}

async function openBillingWithSubscription(page, subscription, usage = null) {
    await stubExternals(page);
    await installSession(page);
    await page.route("**/api/**", route => {
        const url = new URL(route.request().url());
        const p = url.pathname;

        if (p === "/api/user") return route.fulfill(json(200, { status: "success", data: ME }));
        if (p === "/api/users") return route.fulfill(json(200, { status: "success", data: ROSTER }));
        if (p === "/api/workspace") return route.fulfill(json(200, { status: "success", data: WORKSPACE }));
        if (p === "/api/invites") return route.fulfill(json(200, { status: "success", data: [] }));
        if (p === "/api/billing/subscription") {
            return route.fulfill(json(200, { status: "success", data: subscription }));
        }
        if (p === "/api/billing/usage") {
            return route.fulfill(json(200, { status: "success", data: usage }));
        }
        if (p === "/api/billing/subscription/renewal-status") {
            return route.fulfill(json(200, { status: "success", data: {
                subscription_status: subscription.effective_status || subscription.status,
                renewal_required: subscription.renewal_required,
                renewal_allowed: subscription.can_renew
            }}));
        }
        if (p === "/api/billing/ai-credit/summary") {
            return route.fulfill(json(200, { status: "success", data: {
                initialised: true,
                total_balance_micro_myr: 12500000,
                included_balance_micro_myr: 10000000,
                topup_balance_micro_myr: 2500000,
                period_start: "2026-08-01T00:00:00Z",
                period_end: "2026-09-01T00:00:00Z"
            }}));
        }
        if (p === "/api/platform-admin/me") {
            return route.fulfill(json(403, { status: "error", code: "platform_admin_access_denied" }));
        }
        return route.fulfill(json(200, { status: "success", data: [] }));
    });

    await page.goto("/billing.html");
    await expect(page.locator("main.kw-page")).toBeVisible();
}

/* ------------------------------------------------------------------ */
/* Responsive layout                                                    */
/* ------------------------------------------------------------------ */

for (const path of ["/profile.html", "/billing.html"]) {
    test.describe(`responsive layout ${path}`, () => {
        for (const bp of BREAKPOINTS) {
            test(`${bp.name} (${bp.width}px) does not scroll horizontally`, async ({ page }) => {
                await page.setViewportSize({ width: bp.width, height: bp.height });
                await openPage(page, path);
                /* Let the reveal animations settle before measuring. */
                await page.waitForTimeout(400);

                const overflow = await page.evaluate(() => ({
                    scrollWidth: document.documentElement.scrollWidth,
                    clientWidth: document.documentElement.clientWidth
                }));
                /* 1px of slack absorbs sub-pixel rounding on fractional DPRs. */
                expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
            });

            test(`${bp.name} (${bp.width}px) keeps every panel inside the viewport`, async ({ page }) => {
                await page.setViewportSize({ width: bp.width, height: bp.height });
                await openPage(page, path);
                await page.waitForTimeout(400);

                const strays = await page.evaluate(() => {
                    const out = [];
                    /* A wide table inside kw-table-scroll (overflow-x: auto) is the
                       design system's own responsive pattern: the table scrolls in
                       its container while the page does not. Only unconstrained
                       overflow is a defect. */
                    const scrollable = (node) => {
                        let cur = node.parentElement;
                        while (cur && cur !== document.body) {
                            const o = getComputedStyle(cur).overflowX;
                            if (o === "auto" || o === "scroll") return true;
                            cur = cur.parentElement;
                        }
                        return false;
                    };
                    document.querySelectorAll("main.kw-page *").forEach(node => {
                        const rect = node.getBoundingClientRect();
                        if (rect.width === 0 && rect.height === 0) return;
                        const style = getComputedStyle(node);
                        if (style.visibility === "hidden" || style.display === "none") return;
                        if (scrollable(node)) return;
                        if (rect.right > document.documentElement.clientWidth + 1) {
                            out.push((node.id || node.className || node.tagName).toString().slice(0, 60));
                        }
                    });
                    return out.slice(0, 8);
                });
                expect(strays, `elements overflowing the viewport: ${strays.join(", ")}`).toEqual([]);
            });
        }
    });
}

/* ------------------------------------------------------------------ */
/* Design-system consistency                                            */
/* ------------------------------------------------------------------ */

test.describe("control-room design language", () => {
    test("profile and billing share the canvas and accent of team.html", async ({ page }) => {
        const read = async (path) => {
            await openPage(page, path);
            return page.evaluate(() => {
                const root = getComputedStyle(document.documentElement);
                return {
                    canvas: root.getPropertyValue("--control-canvas").trim(),
                    accent: root.getPropertyValue("--control-accent").trim(),
                    body: getComputedStyle(document.body).backgroundColor,
                    font: getComputedStyle(document.body).fontFamily
                };
            });
        };

        const team = await read("/team.html");
        const profile = await read("/profile.html");
        const billing = await read("/billing.html");

        for (const [name, target] of [["profile", profile], ["billing", billing]]) {
            expect(target.canvas, `${name} canvas token`).toBe(team.canvas);
            expect(target.accent, `${name} accent token`).toBe(team.accent);
            expect(target.body, `${name} body background`).toBe(team.body);
            expect(target.font, `${name} body font`).toContain("Geist");
        }
    });

    test("the retired blue accent is nowhere in the rendered pages", async ({ page }) => {
        for (const path of ["/profile.html", "/billing.html"]) {
            await openPage(page, path);
            const blues = await page.evaluate(() => {
                const hits = [];
                document.querySelectorAll("main.kw-page *").forEach(node => {
                    const s = getComputedStyle(node);
                    [s.color, s.backgroundColor, s.borderTopColor].forEach(v => {
                        if (v === "rgb(59, 130, 246)") hits.push(node.tagName);
                    });
                });
                return hits;
            });
            expect(blues, `${path} still paints #3b82f6`).toEqual([]);
        }
    });

    test("profile uses the control-room shell, not the retired glass system", async ({ page }) => {
        await openPage(page, "/profile.html");
        await expect(page.locator("body.dashboard-page")).toHaveCount(1);
        await expect(page.locator(".glass-card")).toHaveCount(0);
        await expect(page.locator(".tabs-nav")).toHaveCount(0);
    });
});

/* ------------------------------------------------------------------ */
/* Profile content and the security gauge                               */
/* ------------------------------------------------------------------ */

test.describe("profile page", () => {
    test("renders identity, gauge and workspace standing", async ({ page }) => {
        await openPage(page, "/profile.html");

        await expect(page.locator("#pro-hero-name")).toContainText("Vincent Owner");
        await expect(page.locator("#pro-hero-email")).toContainText("owner@example.test");
        await expect(page.locator("#pro-hero-gauge")).toBeVisible();
        await expect(page.locator("#pro-standing")).toBeVisible();
    });

    test("the gauge is perceivable to a screen reader", async ({ page }) => {
        await openPage(page, "/profile.html");
        const svg = page.locator("#pro-hero-gauge svg[role='img']");
        await expect(svg).toHaveCount(1);
        const label = await svg.getAttribute("aria-label");
        expect(label, "gauge needs a meaningful aria-label").toBeTruthy();
        expect(label).toMatch(/\d/);
    });

    test("a fully hardened account scores 100 percent", async ({ page }) => {
        await openPage(page, "/profile.html");
        /* ME has name, phone, verified email and active status. */
        await expect(page.locator("#pro-hero-gauge")).toContainText("100%");
    });

    test("carries no billing surface", async ({ page }) => {
        await openPage(page, "/profile.html");
        const text = await page.locator("main.kw-page").innerText();
        for (const word of ["Invoice", "Top Up", "Credit Transactions", "Billing History"]) {
            expect(text).not.toContain(word);
        }
    });
});

test.describe("billing renewal actions", () => {
    test("expired paid plan shows Renew Plan even when usage is unavailable", async ({ page }) => {
        await openBillingWithSubscription(page, Object.assign({}, SUBSCRIPTION, {
            plan: { code: "pro", name: "Pro", billing_interval: "month", team_member_limit: 5 },
            status: "active",
            effective_status: "expired",
            can_renew: true,
            renewal_required: true
        }), null);

        await expect(page.locator("#bl-plan-status")).toContainText("Expired");
        await expect(page.locator("#bl-plan-change")).toHaveText("Renew Plan");
    });

    test("past due paid plan shows Renew Plan", async ({ page }) => {
        await openBillingWithSubscription(page, Object.assign({}, SUBSCRIPTION, {
            plan: { code: "pro", name: "Pro", billing_interval: "month", team_member_limit: 5 },
            status: "active",
            effective_status: "past_due",
            can_renew: true,
            renewal_required: true
        }), null);

        await expect(page.locator("#bl-plan-status")).toContainText("Past Due");
        await expect(page.locator("#bl-plan-change")).toHaveText("Renew Plan");
    });

    test("active paid plan is not incorrectly rendered as renewable", async ({ page }) => {
        await openBillingWithSubscription(page, Object.assign({}, SUBSCRIPTION, {
            plan: { code: "pro", name: "Pro", billing_interval: "month", team_member_limit: 5 },
            status: "active",
            effective_status: "active",
            can_renew: false,
            renewal_required: false
        }), null);

        await expect(page.locator("#bl-plan-status")).toContainText("Active");
        await expect(page.locator("#bl-plan-change")).not.toHaveText("Renew Plan");
    });

    test("one click on Renew Plan navigates to pricing", async ({ page }) => {
        await openBillingWithSubscription(page, Object.assign({}, SUBSCRIPTION, {
            plan: { code: "pro", name: "Pro", billing_interval: "month", team_member_limit: 5 },
            status: "active",
            effective_status: "expired",
            can_renew: true,
            renewal_required: true
        }), null);

        await page.locator("#bl-plan-change").click();
        await expect(page).toHaveURL(/\/pricing\.html/);
    });
});

/* ------------------------------------------------------------------ */
/* Keyboard and focus                                                   */
/* ------------------------------------------------------------------ */

test.describe("keyboard and focus", () => {
    for (const path of ["/profile.html", "/billing.html"]) {
        test(`${path} shows a visible focus ring on every tab stop`, async ({ page }) => {
            await openPage(page, path);

            const seen = [];
            for (let i = 0; i < 15; i++) {
                await page.keyboard.press("Tab");
                const info = await page.evaluate(() => {
                    const node = document.activeElement;
                    if (!node || node === document.body) return null;
                    /* The shared sidebar account menu is not this page's markup;
                       its focus treatment is tracked separately. */
                    if (!node.closest("main.kw-page")) return null;
                    const s = getComputedStyle(node);
                    return {
                        tag: node.tagName,
                        id: node.id,
                        outlineWidth: s.outlineWidth,
                        outlineStyle: s.outlineStyle,
                        boxShadow: s.boxShadow
                    };
                });
                if (!info) continue;
                seen.push(info);
            }

            expect(seen.length, "keyboard reached no interactive control").toBeGreaterThan(0);

            const unfocusable = seen.filter(i =>
                (i.outlineStyle === "none" || parseFloat(i.outlineWidth) === 0) &&
                (!i.boxShadow || i.boxShadow === "none")
            );
            expect(
                unfocusable.map(i => i.id || i.tag),
                "these tab stops have no visible focus indicator"
            ).toEqual([]);
        });
    }

    test("profile form controls are reachable and labelled", async ({ page }) => {
        await openPage(page, "/profile.html");
        for (const id of ["profile-full-name", "profile-phone", "profile-current-password"]) {
            const field = page.locator(`#${id}`);
            await expect(field).toBeVisible();
            const labelled = await page.evaluate((elementId) => {
                const node = document.getElementById(elementId);
                if (node.getAttribute("aria-label")) return true;
                return !!document.querySelector(`label[for="${elementId}"]`);
            }, id);
            expect(labelled, `${id} has no accessible name`).toBe(true);
        }
    });
});

/* ------------------------------------------------------------------ */
/* Reduced motion                                                       */
/* ------------------------------------------------------------------ */

test.describe("reduced motion", () => {

    for (const path of ["/profile.html", "/billing.html"]) {
        test(`${path} honours prefers-reduced-motion`, async ({ page }) => {
            await page.emulateMedia({ reducedMotion: "reduce" });
            await openPage(page, path);
            expect(await page.evaluate(
                () => window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ), "reduced-motion emulation did not apply").toBe(true);
            await page.waitForTimeout(200);

            const moving = await page.evaluate(() => {
                const out = [];
                document.querySelectorAll("main.kw-page .cr-reveal, main.kw-page .cr-skeleton").forEach(node => {
                    const s = getComputedStyle(node);
                    const animated = s.animationName !== "none" && parseFloat(s.animationDuration) > 0.05;
                    const transitioned = parseFloat(s.transitionDuration) > 0.05;
                    if (animated || transitioned) {
                        out.push(node.className.toString().slice(0, 50));
                    }
                });
                return out.slice(0, 5);
            });
            expect(moving, `still animating under reduced motion: ${moving.join(", ")}`).toEqual([]);
        });

        test(`${path} still renders its content with motion disabled`, async ({ page }) => {
            await page.emulateMedia({ reducedMotion: "reduce" });
            await openPage(page, path);
            const revealed = await page.locator("main.kw-page .cr-reveal").count();
            if (revealed === 0) return;
            /* A reveal animation must never be the thing that makes content
               visible, or reduced-motion users see an empty page. */
            await expect(page.locator("main.kw-page .cr-reveal").first()).toBeVisible();
        });
    }
});

/* ------------------------------------------------------------------ */
/* Contrast                                                             */
/* ------------------------------------------------------------------ */

test.describe("text contrast", () => {
    for (const path of ["/profile.html", "/billing.html"]) {
        test(`${path} meets WCAG AA for body text`, async ({ page }) => {
            await openPage(page, path);
            await page.waitForTimeout(300);

            const failures = await page.evaluate(() => {
                function channel(v) {
                    const c = v / 255;
                    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
                }
                function luminance(rgb) {
                    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
                }
                function parse(value) {
                    const m = value.match(/rgba?\(([^)]+)\)/);
                    if (!m) return null;
                    const parts = m[1].split(",").map(n => parseFloat(n.trim()));
                    const alpha = parts.length > 3 ? parts[3] : 1;
                    return [parts[0], parts[1], parts[2], alpha];
                }
                function over(top, bottom) {
                    const a = top[3];
                    return [
                        top[0] * a + bottom[0] * (1 - a),
                        top[1] * a + bottom[1] * (1 - a),
                        top[2] * a + bottom[2] * (1 - a),
                        1
                    ];
                }
                /* Backgrounds in this design system are frequently 10% tints over
                   the panel. Treating a tint as opaque understates contrast badly,
                   so the stack is composited down to the canvas. */
                function effectiveBackground(node) {
                    const layers = [];
                    let current = node;
                    while (current && current !== document.documentElement) {
                        const bg = parse(getComputedStyle(current).backgroundColor);
                        if (bg && bg[3] > 0) {
                            layers.push(bg);
                            if (bg[3] >= 1) break;
                        }
                        current = current.parentElement;
                    }
                    let result = [14, 15, 17, 1];
                    for (let i = layers.length - 1; i >= 0; i--) {
                        result = over(layers[i], result);
                    }
                    return result;
                }

                const out = [];
                const selector = "main.kw-page p, main.kw-page h1, main.kw-page h2, "
                    + "main.kw-page label, main.kw-page td, main.kw-page span";
                document.querySelectorAll(selector).forEach(node => {
                    const text = (node.textContent || "").trim();
                    if (!text) return;
                    const style = getComputedStyle(node);
                    if (style.visibility === "hidden" || style.display === "none") return;
                    const rect = node.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return;

                    const rawFg = parse(style.color);
                    if (!rawFg || rawFg[3] === 0) return;
                    const bg = effectiveBackground(node);
                    const fg = rawFg[3] < 1 ? over(rawFg, bg) : rawFg;
                    const l1 = luminance(fg) + 0.05;
                    const l2 = luminance(bg) + 0.05;
                    const ratio = l1 > l2 ? l1 / l2 : l2 / l1;

                    const size = parseFloat(style.fontSize);
                    const bold = parseInt(style.fontWeight, 10) >= 700;
                    const large = size >= 24 || (size >= 18.66 && bold);
                    const required = large ? 3 : 4.5;

                    if (ratio < required) {
                        out.push(`${text.slice(0, 28)} :: ${ratio.toFixed(2)} < ${required}`);
                    }
                });
                return out.slice(0, 10);
            });

            expect(failures, `low-contrast text:\n${failures.join("\n")}`).toEqual([]);
        });
    }
});
