// Run after the Astro build. Every request is answered from a fixture or a local asset.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");

async function visit(role, api = {}) {
    const page = await fs.readFile(path.join(root, "web/src/pages/superadmin.astro"), "utf8");
    const scripts = [...page.matchAll(/src="(assets\/js\/superadmin[^"]+\.js)"/g)].map(match => match[1]);
    const nodes = new Map(), calls = [], events = {}, timers = new Map();
    const node = selector => {
        if (!nodes.has(selector)) nodes.set(selector, {
            innerHTML: "", textContent: "", focus() {}, showModal() { this.open = true; }, close() { this.open = false; },
            append() {}, querySelectorAll: () => [], matches: selectors => selectors.split(",").includes(selector),
            addEventListener(event, listener) { this[event] = listener; },
            setAttribute(name, value) { this[name] = value; }, getAttribute(name) { return this[name]; },
            removeAttribute(name) { delete this[name]; }, id: selector.slice(1)
        });
        return nodes.get(selector);
    };
    const location = { hash: "#api-keys", replace: value => calls.push(value) };
    const window = { location, addEventListener() {}, PlatformAdminApi: {
        listOpenRouterKeys: async () => {
            calls.push("list");
            return { keys: [{ id: 8, clients: 3, max_clients: 2, status: "active", label: null }] };
        }, ...api
    }};
    let authorized;
    window.PlatformAdminShell = {
        start: ({ onAuthorized }) => { authorized = onAuthorized({ platform_role: role }); },
        runRequest: (_, factory) => factory(),
        clearPlatformState() {}, handleError: error => calls.push(error.category)
    };
    const document = {
        body: node("body"), querySelector: node, querySelectorAll: () => [], getElementById: id => node("#" + id),
        visibilityState: "visible", addEventListener: (event, listener) => { events[event] = listener; }
    };
    const context = vm.createContext({ window, location, URLSearchParams, document,
        setInterval(fn, ms) { timers.set(fn, ms); return fn; }, clearInterval(fn) { timers.delete(fn); },
        setTimeout() {}, clearTimeout() {}
    });
    for (const src of scripts) vm.runInContext(await fs.readFile(path.join(root, "frontend", src), "utf8"), context);
    await authorized;
    return { calls, html: [...nodes.values()].map(item => item.innerHTML).join(" "), nav: node("#navigation").innerHTML,
        node, document, location, tick: async () => {
            for (const [callback, delay] of timers) { assert.equal(delay, 30000); await callback(); }
        }, click: action => events.click({ target: { closest: () => ({ dataset: { action, id: "8" } }) } }),
        confirm: () => events.submit({ target: node("#confirm-form"), preventDefault() {} }) };
}

test("the hash route lists capacities for Super Admin and denies a staff deep link", async () => {
    const staff = await visit("admin");
    assert.deepEqual(staff.calls, ["access_denied"]);
    assert.doesNotMatch(staff.nav, /API keys/);
    const admin = await visit("super_admin");
    assert.deepEqual(admin.calls, ["list"]);
    assert.match(admin.nav, /href="#api-keys"/);
    assert.match(admin.html, /3 \/ 2/);
    assert.match(admin.html, />Full</);
    assert.match(admin.html, />Details</);
    assert.match(admin.html, />Replace key</);
});

test("the hash route shows company details, enforces the Client range and masks the replacement field", async () => {
    const { click, node } = await visit("super_admin", {
        getOpenRouterKeyCompanies: async id => {
            assert.equal(id, 8);
            return { key_id: 8, max_clients: 2, clients: 1,
                companies: [{ id: 31, name: "<Client>", assigned_at: "2026-10-01T00:00:00Z" }] };
        }
    });
    await click("key-details");
    const detail = node("#detail-content").innerHTML;
    assert.match(detail, /1 company connected/);
    assert.match(detail, /<td>&lt;Client&gt;<\/td><td>31<\/td>/);
    assert.match(detail, /type="number" min="1" max="20" step="1" inputmode="numeric" value="2"/);
    node("#client-limit").value = "21";
    node("#key-limit-form").submit({ preventDefault() {} });
    assert.match(node("#limit-error").textContent, /1 to 20/);
    assert.equal(node("#client-limit")["aria-invalid"], "true");
    await click("replace-key");
    assert.match(node("#detail-content").innerHTML, /id="replacement-key" type="password"/);
    const input = node("#replacement-key"), toggle = node("#show-key");
    input.type = "password";
    toggle.click();
    assert.equal(input.type, "text");
    assert.equal(toggle["aria-pressed"], "true");
    toggle.click();
    assert.equal(input.type, "password");
    assert.equal(toggle["aria-pressed"], "false");
    toggle.click();
    node("#replace-form").focusout({ relatedTarget: node("#confirm-submit") });
    assert.equal(input.type, "password");
    assert.equal(toggle["aria-pressed"], "false");
});

test("the hash route confirms a lower limit before saving and rereads the list and companies", async () => {
    const writes = [];
    let max = 20, lists = 0, reads = 0;
    const { click, node, confirm } = await visit("super_admin", {
        listOpenRouterKeys: async () => {
            lists++;
            return { keys: [{ id: 8, clients: 2, max_clients: max, status: "active" }] };
        },
        getOpenRouterKeyCompanies: async () => {
            reads++;
            return { key_id: 8, max_clients: max, clients: 2,
                companies: [{ id: 31, name: "Alpha" }, { id: 32, name: "Beta" }] };
        },
        setOpenRouterKeyMaxClients: async (id, value) => { writes.push([id, value]); max = value; }
    });
    await click("key-details");
    node("#client-limit").value = "1";
    node("#key-limit-form").submit({ preventDefault() {} });
    assert.deepEqual(writes, []);
    assert.equal(node("#confirm-dialog").open, true);
    assert.match(node("#confirm-description").textContent, /keeps its current Clients.*takes no new ones until it has fewer than 1/);
    await confirm();
    assert.deepEqual(writes, [[8, 1]]);
    assert.equal(lists, 2);
    assert.equal(reads, 2);
    assert.match(node("#detail-content").innerHTML, /value="1"/);
    assert.match(node("#key-list-content").innerHTML, /2 \/ 1/);
    assert.equal(node("#toast").textContent, "Client limit saved.");
    assert.equal(node("#confirm-dialog").open, false);
});

test("a pasted key is validated, confirmed and submitted with its Client limit", async () => {
    const fake = "sk-or-v1-" + "0".repeat(64);
    const writes = [];
    const { html, click, confirm, node } = await visit("super_admin", {
        addOpenRouterKey: async payload => { writes.push(JSON.parse(JSON.stringify(payload))); return { id: 9 }; }
    });
    assert.match(html, />\+ Add key</);
    await click("add-key");
    assert.match(node("#detail-content").innerHTML, /type="password" autocomplete="off"/);
    assert.match(node("#detail-content").innerHTML, /value="20"/);
    const input = node("#added-key"), limit = node("#added-limit");
    const submit = () => node("#add-key-form").submit({ preventDefault() {} });
    input.value = "invalid"; limit.value = "5";
    submit();
    assert.equal(input["aria-invalid"], "true");
    input.value = fake; limit.value = "21";
    submit();
    assert.equal(limit["aria-invalid"], "true");
    limit.value = "5"; submit();
    assert.equal(node("#confirm-dialog").open, true);
    assert.ok(!node("#confirm-summary").textContent.includes(fake));
    assert.deepEqual(writes, []);
    await confirm();
    assert.deepEqual(writes, [{ api_key: fake, max_clients: 5 }]);
    assert.equal(input.value, "");
    assert.equal(node("#toast").textContent, "Key added.");
});

test("live balances and reset-period spend refresh only on the active visible route without a dialog", async () => {
    let reads = 0;
    const view = await visit("super_admin", { listOpenRouterKeys: async () => ({
        account: ++reads === 1 ? { remaining: 19.5, total_usage: 5.5, total_credits: 25 } : null,
        keys: [{ id: 8, clients: 2, max_clients: 20, status: "active", limit: 30,
            usage: 42, usage_monthly: 2, limit_remaining: 28, limit_reset: "monthly" },
            { id: 9, clients: 0, max_clients: 20, status: "active", limit: 20,
                usage: 50, usage_monthly: 13, limit_remaining: 16, limit_reset: "weekly" }]
    }) });
    const balance = view.node("#key-account").innerHTML;
    assert.match(balance, /19\.5/);
    assert.match(balance, /5\.5/);
    assert.match(balance, /25/);
    assert.match(view.html, /<progress\b/);
    assert.match(view.html, /2 \/ 30/);
    assert.match(view.html, /28 remaining/);
    assert.match(view.html, /Resets monthly/);
    assert.match(view.html, /4 \/ 20/);
    assert.match(view.html, /Resets weekly/);
    await view.tick();
    assert.equal(reads, 2);
    assert.match(view.node("#key-account").innerHTML, /Balance unavailable/);
    view.node("#detail-dialog").open = true; await view.tick();
    view.node("#detail-dialog").open = false; view.node("#confirm-dialog").open = true; await view.tick();
    view.node("#confirm-dialog").open = false; view.document.visibilityState = "hidden"; await view.tick();
    view.document.visibilityState = "visible"; view.location.hash = "#settings"; await view.tick();
    assert.equal(reads, 2);
});

test("the rendered form masks, cancels and saves, and staff cannot open it", async () => {
    const { chromium } = require("@playwright/test");
    const browser = await chromium.launch({ executablePath: process.env.BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage();
        await page.addInitScript(() => sessionStorage.setItem("token", "test-session"));
        const url = "https://portal.test/superadmin.html#api-keys";
        const api = "/api/platform-admin/openrouter-keys";
        const fake = "sk-or-v1-" + "0".repeat(64);
        const requests = [], errors = [];
        let role = "super_admin", body, added, reads = 0, limit = 2, detailReads = 0;
        let account = { remaining: 19.5, total_usage: 5.5, total_credits: 25 };
        await page.clock.install();
        page.on("pageerror", error => errors.push(error.name));
        page.on("console", message => assert.ok(!message.text().includes(fake)));
        await page.route("**/*", async route => {
            const request = route.request(), resource = new URL(request.url()).pathname;
            requests.push(request.url());
            const ok = data => route.fulfill({ json: { status: "success", data } });
            if (resource === "/api/platform-admin/me") return ok({ platform_role: role, user: {} });
            if (resource === api) {
                if (request.method() === "POST") {
                    added = request.postDataJSON();
                    return ok({ id: 10, max_clients: added.max_clients, label: "sk-or-v1-000...0000" });
                }
                reads++;
                return ok({ account, keys: [{ id: 8, label: null, clients: 2, max_clients: limit, status: "active",
                    disabled_reason: null, limit: 30, usage: 42, usage_monthly: 2, limit_remaining: 28, limit_reset: "monthly" },
                    { id: 9, label: null, clients: 0, max_clients: 20, status: "disabled",
                      disabled_reason: "manual_replacement", limit: null, usage: null }] });
            }
            if (resource === api + "/8/companies") {
                detailReads++;
                return ok({ key_id: 8, max_clients: limit, clients: 2, companies: [
                    { id: 21, name: "Alpha", assigned_at: "2026-09-01T00:00:00Z" },
                    { id: 25, name: "Beta", assigned_at: "2026-10-01T00:00:00Z" }
                ] });
            }
            if (resource === api + "/9/companies") {
                return ok({ key_id: 9, max_clients: 20, clients: 0, companies: [] });
            }
            if (resource === api + "/8/max-clients") {
                assert.equal(request.method(), "PATCH");
                assert.deepEqual(request.postDataJSON(), { max_clients: 1 });
                limit = 1;
                return ok({ id: 8, max_clients: limit, previous_max_clients: 2, clients: 2 });
            }
            if (resource === api + "/8/replace") {
                assert.equal(request.method(), "POST");
                body = request.postDataJSON();
                return ok({ label: "sk-or-v1-000...0000", moved_count: 2, old_key_disabled: false });
            }
            if (resource === "/superadmin.html") {
                return route.fulfill({ contentType: "text/html", body: await fs.readFile(
                    path.join(root, "web/dist/superadmin.html")) });
            }
            if (/^\/assets\/(js|css)\/[\w.-]+$/.test(resource)) {
                // Built pages serve web/public first (theme-boot.js lives only there), then frontend/.
                const published = path.join(root, "web/public", resource);
                const served = await fs.access(published).then(() => published, () => path.join(root, "frontend", resource));
                return route.fulfill({ path: served });
            }
            return route.fulfill({ status: 204 });
        });
        await page.goto(url);
        await page.getByRole("link", { name: "API keys" }).waitFor();
        const row = page.getByRole("row").filter({ hasText: "Key #8" });
        const archived = page.getByRole("row").filter({ hasText: "Key #9" });
        const drawer = page.locator("#detail-dialog");
        const add = page.getByRole("button", { name: "+ Add key", exact: true });
        await add.waitFor({ timeout: 3000 });
        const bar = row.getByRole("progressbar");
        await bar.waitFor();
        const balance = page.getByRole("region", { name: "OpenRouter account balance" });
        assert.match(await balance.innerText(), /19\.5/);
        assert.match(await balance.innerText(), /5\.5/);
        assert.match(await balance.innerText(), /25/);
        assert.equal(await bar.getAttribute("value"), "2");
        assert.equal(await bar.getAttribute("max"), "30");
        assert.match(await row.innerText(), /28 remaining/);
        assert.match(await row.innerText(), /Resets monthly/);
        assert.match(await page.locator("#updated-at").innerText(), /^Updated \d\d:\d\d:\d\d$/);
        assert.equal(await page.locator("#updated-at").evaluate(el => !!el.closest("[aria-live], [role='status']")), false);
        await row.getByRole("button", { name: "Details" }).focus();
        account = null;
        let before = reads;
        await page.clock.fastForward(30000);
        await page.getByText("Balance unavailable", { exact: true }).waitFor();
        assert.equal(reads, before + 1);
        assert.equal(await row.getByRole("button", { name: "Details" }).evaluate(el => el === document.activeElement), true);
        const style = locator => locator.evaluate(el => {
            const s = getComputedStyle(el);
            return [s.fontFamily, s.fontSize, s.padding, s.borderWidth, s.borderRadius];
        });
        for (const theme of ["dark", "light"]) {
            await page.evaluate(mode => window.OmnexaAppPreferences.setTheme(mode, false), theme);
            assert.deepEqual(await style(add), await style(page.getByRole("button", { name: "Refresh", exact: true })));
            assert.ok((await page.locator(".page-header").screenshot()).length > 0);
        }
        await add.click();
        let key = drawer.getByLabel("OpenRouter key", { exact: true });
        assert.equal(await key.getAttribute("autocomplete"), "off");
        assert.equal(await key.getAttribute("type"), "password");
        assert.equal(await drawer.getByLabel("Client limit").inputValue(), "20");
        before = reads;
        await page.clock.fastForward(30000);
        assert.equal(reads, before);
        await key.fill(fake);
        await drawer.getByRole("button", { name: "Show" }).click();
        assert.equal(await key.getAttribute("type"), "text");
        const canceledInput = await key.elementHandle();
        await drawer.getByRole("button", { name: "Cancel", exact: true }).click();
        await key.waitFor({ state: "detached" });
        assert.equal(await canceledInput.evaluate(el => el.value), "");
        await add.click();
        key = drawer.getByLabel("OpenRouter key", { exact: true });
        await drawer.getByRole("button", { name: "Continue" }).click();
        await drawer.getByText("Paste a valid OpenRouter key.").waitFor();
        await key.fill(fake);
        await drawer.getByLabel("Client limit").fill("0");
        await drawer.getByRole("button", { name: "Continue" }).click();
        await drawer.getByText("Enter a whole number from 1 to 20.").waitFor();
        await drawer.getByLabel("Client limit").fill("7");
        await drawer.getByRole("button", { name: "Continue" }).click();
        assert.equal(added, undefined);
        const savedInput = await key.elementHandle();
        await page.locator("#confirm-dialog").getByRole("button", { name: "Add key" }).click();
        await page.getByText("Key added.", { exact: true }).waitFor();
        assert.equal(await savedInput.evaluate(el => el.value), "");
        assert.deepEqual(added, { api_key: fake, max_clients: 7 });
        // Hidden tabs and other routes must not poll, even after multiple ticks.
        await page.evaluate(() => Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" }));
        before = reads;
        await page.clock.fastForward(60000);
        assert.equal(reads, before);
        await page.evaluate(() => { delete document.visibilityState; location.hash = "#settings"; });
        await page.getByRole("link", { name: "Settings", exact: true }).and(page.locator("[aria-current=page]")).waitFor();
        await page.clock.fastForward(60000);
        assert.equal(reads, before);
        await page.getByRole("link", { name: "API keys" }).click();
        await row.waitFor();
        await archived.getByRole("button", { name: "Details" }).click();
        await drawer.getByText("0 companies connected").waitFor();
        assert.equal(await drawer.getByLabel("Client limit").isDisabled(), true);
        await drawer.getByRole("button", { name: "Close details" }).click();
        assert.equal(await archived.getByRole("button", { name: "Replace key" }).count(), 0);
        await row.getByRole("button", { name: "Details" }).click();
        await drawer.getByText("2 companies connected").waitFor();
        await drawer.getByRole("cell", { name: "Alpha" }).waitFor();
        await drawer.getByRole("cell", { name: "25", exact: true }).waitFor();
        const clientLimit = drawer.getByLabel("Client limit");
        for (const [name, value] of Object.entries({ min: "1", max: "20", step: "1", inputmode: "numeric" })) {
            assert.equal(await clientLimit.getAttribute(name), value);
        }
        await clientLimit.fill("21");
        await drawer.getByRole("button", { name: "Save", exact: true }).click();
        await drawer.getByText("Enter a whole number from 1 to 20.").waitFor();
        await clientLimit.fill("1");
        await drawer.getByRole("button", { name: "Save", exact: true }).click();
        const confirm = page.locator("#confirm-dialog");
        await confirm.getByText(/keeps its current Clients.*takes no new/i).waitFor();
        await confirm.getByRole("button", { name: "Save limit" }).click();
        await page.getByText("Client limit saved.", { exact: true }).waitFor();
        assert.equal(await clientLimit.inputValue(), "1");
        assert.equal(detailReads, 2);
        await drawer.getByRole("button", { name: "Close details" }).click();
        assert.match(await row.innerText(), /2 \/ 1/);
        const replace = row.getByRole("button", { name: "Replace key" });
        const input = page.getByLabel("New OpenRouter key");
        const toggle = page.locator("#show-key");
        await replace.click();
        assert.equal(await input.getAttribute("type"), "password");
        await input.fill(fake);
        await toggle.click();
        assert.equal(await input.getAttribute("type"), "text");
        assert.equal(await toggle.textContent(), "Hide");
        assert.equal(await toggle.getAttribute("aria-pressed"), "true");
        await toggle.click();
        assert.equal(await input.getAttribute("type"), "password");
        assert.equal(await toggle.getAttribute("aria-pressed"), "false");
        await drawer.getByRole("button", { name: "Cancel" }).click();
        await drawer.waitFor({ state: "hidden" });
        await replace.click();
        assert.equal(await input.inputValue(), "");
        assert.equal(await input.getAttribute("type"), "password");
        await input.fill(fake);
        await page.getByLabel("Reason for replacement").fill("Provider rejected the key.");
        await page.getByRole("button", { name: "Save" }).click();
        await page.getByText(/OpenRouter did not confirm/).waitFor();
        await input.waitFor({ state: "detached" });
        await replace.click();
        assert.equal(await input.inputValue(), "");
        assert.equal(await input.getAttribute("type"), "password");
        assert.deepEqual(body, { api_key: fake, reason: "Provider rejected the key." });
        assert.ok(!requests.join("").includes(fake));
        assert.ok(!(await page.locator("body").textContent()).includes(fake));
        assert.equal(await page.evaluate(() => localStorage.length), 0);
        await input.fill(fake);
        await toggle.click();
        await drawer.getByRole("button", { name: "Close details" }).click();
        await confirm.getByRole("button", { name: "Discard changes" }).waitFor();
        assert.equal(await input.getAttribute("type"), "password");
        assert.ok(!(await confirm.textContent()).includes(fake));
        await confirm.getByRole("button", { name: "Cancel" }).click();
        const previousReads = reads;
        role = "admin";
        await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
        await page.getByRole("heading", { name: "Access Denied" }).waitFor();
        await drawer.waitFor({ state: "hidden" });
        assert.equal(await input.count(), 0);
        await page.reload();
        await page.getByRole("heading", { name: "Access Denied" }).waitFor();
        assert.equal(reads, previousReads);
        assert.equal(await page.getByRole("link", { name: "API keys" }).count(), 0);
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
});
