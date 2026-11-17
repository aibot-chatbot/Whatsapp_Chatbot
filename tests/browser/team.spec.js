/* Behaviour coverage for frontend/team.html.
 *
 * This replaces the source-text assertions that used to live in
 * tests/test_team_member_limit_frontend.py. Those greps pinned exact JS
 * lines, indentation and function order inside the HTML file, which made
 * the seat rules impossible to refactor and never actually exercised them.
 * Everything they protected is asserted here by driving the real page.
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

function daysFromNow(days) {
    return new Date(Date.now() + days * 86400000).toISOString();
}

const MEMBERS = [
    {
        id: 1, company_id: 42, full_name: "Vincent Owner", email: "owner@example.test",
        role: "owner", status: "active", is_verified: true,
        created_at: "2026-01-04T09:00:00Z", updated_at: "2026-01-04T09:00:00Z"
    },
    {
        id: 2, company_id: 42, full_name: "Aisha Admin", email: "aisha@example.test",
        role: "admin", status: "active", is_verified: true,
        created_at: "2026-02-11T09:00:00Z", updated_at: "2026-02-11T09:00:00Z"
    },
    {
        id: 3, company_id: 42, full_name: "Kai Member", email: "kai@example.test",
        role: "member", status: "inactive", is_verified: false,
        created_at: "2026-03-02T09:00:00Z", updated_at: "2026-03-02T09:00:00Z"
    }
];

const INVITES = [
    {
        id: 91, email: "sam@example.test", role: "member", status: "pending",
        created_at: "2026-08-24T09:00:00Z", expires_at: daysFromNow(2)
    }
];

/* Defaults describe a workspace with room to spare: 3 active + 1 pending
   against a limit of 8. Individual tests override only what they need. */
function workspace(overrides = {}) {
    return Object.assign({
        company: { name: "Example Co", contact_email: "", contact_phone: "" },
        current_user_role: "owner",
        active_member_count: 3,
        pending_invitation_count: 1,
        plan_member_limit: 8,
        remaining_seats: 4,
        can_edit_company: true,
        can_manage_team: true
    }, overrides);
}

async function openTeam(page, options = {}) {
    const ws = options.workspace || workspace();
    const members = options.members || MEMBERS;
    const invites = options.invites || INVITES;
    const onRoute = options.onRoute;

    await page.route("https://fonts.googleapis.com/**", route => route.abort());
    await page.route("https://fonts.gstatic.com/**", route => route.abort());
    await page.route("https://unpkg.com/**", route => route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body: "window.lucide={createIcons:function(){}};"
    }));

    await page.addInitScript(() => {
        sessionStorage.setItem("token", "fake-tenant-token");
        sessionStorage.setItem("isLoggedIn", "true");
        sessionStorage.setItem("user", JSON.stringify({
            id: 1, company_id: 42, email: "owner@example.test",
            full_name: "Vincent Owner", role: "owner"
        }));
    });

    await page.route("**/api/**", route => {
        const url = new URL(route.request().url());
        if (onRoute) {
            const handled = onRoute(route, url);
            if (handled) return handled;
        }
        if (url.pathname === "/api/workspace") {
            return route.fulfill(json(200, { status: "success", data: ws }));
        }
        if (url.pathname === "/api/users") {
            return route.fulfill(json(200, { status: "success", data: members }));
        }
        if (url.pathname === "/api/invites") {
            return route.fulfill(json(200, { status: "success", data: invites }));
        }
        if (url.pathname === "/api/platform-admin/me") {
            return route.fulfill(json(403, {
                status: "error", code: "platform_admin_access_denied"
            }));
        }
        return route.fulfill(json(200, { status: "success", data: [] }));
    });

    await page.goto("/team.html");
    await expect(page.locator("#tm-table-wrap")).toBeVisible();
}

test.describe("team roster", () => {
    test("renders every member with role, status and verification", async ({ page }) => {
        await openTeam(page);

        const rows = page.locator("#tm-tbody tr");
        await expect(rows).toHaveCount(3);

        await expect(rows.nth(0)).toContainText("Vincent Owner");
        await expect(rows.nth(0)).toContainText("Owner");
        await expect(rows.nth(0)).toContainText("You");

        await expect(rows.nth(2)).toContainText("Kai Member");
        await expect(rows.nth(2)).toContainText("Inactive");
        /* Not-verified carries a word, never colour alone. */
        await expect(rows.nth(2)).toContainText("Not verified");

        await expect(page.locator("#tm-count")).toHaveText("3 members");
    });

    test("owner and self rows expose no destructive controls", async ({ page }) => {
        await openTeam(page);
        const rows = page.locator("#tm-tbody tr");

        /* Row 0 is both the owner and the signed-in user; the server refuses
           either change, so the UI must not offer it. */
        await expect(rows.nth(0).locator("select")).toHaveCount(0);
        await expect(rows.nth(0).locator("button")).toHaveCount(0);

        /* Row 1 is another admin, and is manageable. */
        await expect(rows.nth(1).locator("select")).toHaveCount(1);
        await expect(rows.nth(1).getByRole("button", { name: /Deactivate/i })).toBeVisible();
    });

    test("pending invitations show derived expiry, not a stored status", async ({ page }) => {
        await openTeam(page);
        const invite = page.locator(".team-invite-row");
        await expect(invite).toHaveCount(1);
        await expect(invite).toContainText("sam@example.test");
        await expect(invite).toContainText("2 days left");
    });

    test("an invitation past its expiry reads as Expired", async ({ page }) => {
        await openTeam(page, {
            invites: [Object.assign({}, INVITES[0], { expires_at: daysFromNow(-1) })]
        });
        await expect(page.locator(".team-invite-row")).toContainText("Expired");
    });
});

test.describe("seat entitlement", () => {
    test("shows seats in use including pending invitations", async ({ page }) => {
        await openTeam(page);
        /* 3 active + 1 pending = 4 of 8. */
        await expect(page.locator(".team-seats-used")).toHaveText("4");
        await expect(page.locator(".team-seats-limit")).toHaveText("of 8 seats");
        await expect(page.locator("#tm-seats")).toContainText("4 seats left");
    });

    test("invite stays enabled below the limit", async ({ page }) => {
        await openTeam(page);
        const invite = page.locator("#tm-invite");
        await expect(invite).toBeVisible();
        await expect(invite).toBeEnabled();
    });

    test("invite is disabled once active plus pending reaches the limit", async ({ page }) => {
        await openTeam(page, {
            workspace: workspace({
                active_member_count: 3,
                pending_invitation_count: 1,
                plan_member_limit: 4,
                remaining_seats: 0
            })
        });

        const invite = page.locator("#tm-invite");
        await expect(invite).toBeDisabled();
        await expect(invite).toHaveAttribute("title", /Team limit reached/);
        /* The reason is stated, and a way out is offered. */
        await expect(page.locator("#tm-seats")).toContainText("Team limit reached");
        await expect(page.locator("#tm-upgrade")).toBeVisible();
    });

    test("a pending invitation alone can exhaust the limit", async ({ page }) => {
        /* The rule is (active + pending) >= limit, not active >= limit. At 3
           active and 1 pending against 4, active alone would still look like
           there was a seat free. */
        await openTeam(page, {
            workspace: workspace({
                active_member_count: 3, pending_invitation_count: 1, plan_member_limit: 4
            })
        });
        await expect(page.locator("#tm-invite")).toBeDisabled();
    });

    test("an unlimited plan never blocks and shows no meter", async ({ page }) => {
        await openTeam(page, {
            workspace: workspace({ plan_member_limit: null, remaining_seats: null })
        });

        await expect(page.locator("#tm-invite")).toBeEnabled();
        await expect(page.locator("#tm-seats")).toContainText("no seat limit");
        await expect(page.locator(".team-seats-meter")).toHaveCount(0);
        await expect(page.locator("#tm-upgrade")).toBeHidden();
    });
});

test.describe("permissions", () => {
    test("a member sees the roster read-only", async ({ page }) => {
        await openTeam(page, {
            workspace: workspace({ current_user_role: "member", can_manage_team: false })
        });

        await expect(page.locator("#tm-readonly")).toBeVisible();
        await expect(page.locator("#tm-invite")).toBeHidden();
        /* No role selects and no deactivate buttons anywhere in the table. */
        await expect(page.locator("#tm-tbody select")).toHaveCount(0);
        await expect(page.locator("#tm-tbody button")).toHaveCount(0);
        /* And no resend or cancel on invitations either. */
        await expect(page.locator(".team-invite-actions")).toHaveCount(0);
    });
});

test.describe("invite dialog", () => {
    test("is a labelled modal that returns focus and closes on Escape", async ({ page }) => {
        await openTeam(page);
        await page.locator("#tm-invite").click();

        const dialog = page.getByRole("dialog", { name: "Invite someone" });
        await expect(dialog).toBeVisible();
        await expect(dialog).toHaveAttribute("aria-modal", "true");
        /* Focus lands in the first field, not on the page behind it. */
        await expect(page.locator("#tm-invite-email")).toBeFocused();

        await page.keyboard.press("Escape");
        await expect(dialog).toBeHidden();
        /* Focus returns to the control that opened it. */
        await expect(page.locator("#tm-invite")).toBeFocused();
    });

    test("rejects a malformed address before calling the API", async ({ page }) => {
        let invitePosts = 0;
        await openTeam(page, {
            onRoute: (route, url) => {
                if (url.pathname === "/api/invites" && route.request().method() === "POST") {
                    invitePosts += 1;
                    return route.fulfill(json(200, { status: "success" }));
                }
                return null;
            }
        });

        await page.locator("#tm-invite").click();
        await page.locator("#tm-invite-email").fill("not-an-email");
        await page.locator("#tm-invite-submit").click();

        await expect(page.locator("#tm-invite-error")).toBeVisible();
        await expect(page.locator("#tm-invite-error")).toContainText("email address");
        expect(invitePosts).toBe(0);
    });

    test("sends the address and role, then reports success", async ({ page }) => {
        let payload = null;
        await openTeam(page, {
            onRoute: (route, url) => {
                if (url.pathname === "/api/invites" && route.request().method() === "POST") {
                    payload = JSON.parse(route.request().postData() || "{}");
                    return route.fulfill(json(201, {
                        status: "success", message: "Invite created successfully"
                    }));
                }
                return null;
            }
        });

        await page.locator("#tm-invite").click();
        await page.locator("#tm-invite-email").fill("new@example.test");
        await page.locator("#tm-invite-role").selectOption("admin");
        await page.locator("#tm-invite-submit").click();

        await expect(page.locator("#tm-banner")).toBeVisible();
        await expect(page.locator("#tm-banner-text")).toContainText("new@example.test");
        expect(payload).toEqual({ email: "new@example.test", role: "admin" });
    });

    test("surfaces a server-side seat rejection as the limit message", async ({ page }) => {
        await openTeam(page, {
            onRoute: (route, url) => {
                if (url.pathname === "/api/invites" && route.request().method() === "POST") {
                    return route.fulfill(json(403, {
                        status: "error", code: "team_member_limit",
                        message: "Team member limit reached for the current plan."
                    }));
                }
                return null;
            }
        });

        await page.locator("#tm-invite").click();
        await page.locator("#tm-invite-email").fill("new@example.test");
        await page.locator("#tm-invite-submit").click();
        await expect(page.locator("#tm-invite-error")).toContainText("Team limit reached");
    });

    test("distinguishes a suspended workspace from a seat limit", async ({ page }) => {
        await openTeam(page, {
            onRoute: (route, url) => {
                if (url.pathname === "/api/invites" && route.request().method() === "POST") {
                    return route.fulfill(json(403, {
                        status: "error", code: "company_suspended",
                        message: "Company suspended."
                    }));
                }
                return null;
            }
        });

        await page.locator("#tm-invite").click();
        await page.locator("#tm-invite-email").fill("new@example.test");
        await page.locator("#tm-invite-submit").click();
        await expect(page.locator("#tm-invite-error")).toContainText("suspended");
        await expect(page.locator("#tm-invite-error")).not.toContainText("Team limit reached");
    });
});

test.describe("invitation actions", () => {
    test("resend posts invite_id and ignores a double click", async ({ page }) => {
        let resendCount = 0;
        let lastBody = null;

        await openTeam(page, {
            onRoute: (route, url) => {
                if (url.pathname === "/api/invites/resend") {
                    resendCount += 1;
                    lastBody = JSON.parse(route.request().postData() || "{}");
                    /* Held open briefly so the second click lands while the
                       first request is still in flight. */
                    return new Promise(resolve => {
                        setTimeout(() => resolve(route.fulfill(json(200, {
                            status: "success", message: "Invitation resent successfully."
                        }))), 400);
                    });
                }
                return null;
            }
        });

        const resend = page.getByRole("button", { name: /Resend invitation/i });
        await resend.click();
        await resend.click({ force: true }).catch(() => {});

        await expect(page.locator("#tm-banner")).toBeVisible();
        await expect(page.locator("#tm-banner-text")).toContainText("resent");
        expect(resendCount).toBe(1);
        expect(lastBody).toEqual({ invite_id: 91 });
        /* The id travels in the body, never as an email. */
        expect(lastBody.email).toBeUndefined();
    });

    test("cancel asks first and only deletes on confirmation", async ({ page }) => {
        let deletes = 0;
        await openTeam(page, {
            onRoute: (route, url) => {
                if (/^\/api\/invites\/\d+$/.test(url.pathname) &&
                    route.request().method() === "DELETE") {
                    deletes += 1;
                    return route.fulfill(json(200, {
                        status: "success", message: "Invitation cancelled successfully."
                    }));
                }
                return null;
            }
        });

        await page.getByRole("button", { name: /Cancel invitation/i }).click();
        const confirm = page.getByRole("dialog", { name: /Cancel this invitation/i });
        await expect(confirm).toBeVisible();

        /* Dismissing must not delete anything. */
        await page.locator("#tm-confirm-cancel").click();
        await expect(confirm).toBeHidden();
        expect(deletes).toBe(0);

        await page.getByRole("button", { name: /Cancel invitation/i }).click();
        await page.locator("#tm-confirm-ok").click();
        await expect(page.locator("#tm-banner")).toBeVisible();
        await expect(page.locator("#tm-banner-text")).toContainText("cancelled");
        expect(deletes).toBe(1);
    });

    test("a role change is confirmed before it is sent", async ({ page }) => {
        let roleBody = null;
        await openTeam(page, {
            onRoute: (route, url) => {
                if (/^\/api\/users\/\d+\/role$/.test(url.pathname)) {
                    roleBody = JSON.parse(route.request().postData() || "{}");
                    return route.fulfill(json(200, { status: "success", data: {} }));
                }
                return null;
            }
        });

        await page.locator("#tm-tbody tr").nth(1).locator("select").selectOption("member");
        await expect(page.getByRole("dialog", { name: /Change role/i })).toBeVisible();
        await page.locator("#tm-confirm-ok").click();

        await expect(page.locator("#tm-banner")).toBeVisible();
        await expect(page.locator("#tm-banner-text")).toContainText("Role updated");
        expect(roleBody).toEqual({ role: "member" });
    });
});

test.describe("layout", () => {
    test("stays inside the viewport at every supported width", async ({ page }) => {
        for (const width of [1440, 1280, 1024, 768, 390, 320]) {
            await page.setViewportSize({ width, height: width <= 390 ? 900 : 820 });
            await openTeam(page);

            const overflow = await page.evaluate(() =>
                document.documentElement.scrollWidth - document.documentElement.clientWidth);
            /* The roster table scrolls inside its own wrapper, so the page
               body itself must never scroll sideways. */
            expect(overflow, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(0);
        }
    });

    test("the seat rail moves above the roster once the columns collapse", async ({ page }) => {
        await page.setViewportSize({ width: 1440, height: 900 });
        await openTeam(page);
        const wide = await page.locator(".team-rail").boundingBox();
        const wideMain = await page.locator(".team-main").boundingBox();
        expect(wide.x).toBeGreaterThan(wideMain.x);

        await page.setViewportSize({ width: 900, height: 900 });
        const narrow = await page.locator(".team-rail").boundingBox();
        const narrowMain = await page.locator(".team-main").boundingBox();
        expect(narrow.y).toBeLessThan(narrowMain.y);
    });
});

test.describe("sign-in gate", () => {
    /* requireLogin() is AppLayout's assets/js/require-login.js now. Every API answers 200, so a 401
       logout cannot redirect in its place. Replaces the "requireLogin();" source pin of
       tests/test_team_member_limit_frontend.py. */
    test("a signed-out visitor is sent to the sign-in page", async ({ page }) => {
        await page.route(/^https:/, route => route.abort());
        await page.route("**/api/**", route => route.fulfill(json(200, { status: "success", data: [] })));
        await page.goto("/team.html");
        await expect(page).toHaveURL(/\/login\.html$/);
    });
});
