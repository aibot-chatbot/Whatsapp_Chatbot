// Run after the Astro build. Every request is answered from a fixture or a local asset.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");

test("the rendered form masks, cancels and saves, and staff cannot open it", async () => {
    const root = path.resolve(__dirname, "..");
    const browser = await chromium.launch({ executablePath: process.env.BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage();
        await page.addInitScript(() => sessionStorage.setItem("token", "test-session"));
        const url = "https://portal.test/platform-admin-api-keys.html";
        const api = "/api/platform-admin/openrouter-keys";
        const fake = "sk-or-v1-" + "0".repeat(64);
        const requests = [], errors = [];
        let role = "super_admin", body, reads = 0;
        page.on("pageerror", error => errors.push(error.name));
        page.on("console", message => assert.ok(!message.text().includes(fake)));
        await page.route("**/*", async route => {
            const request = route.request(), resource = new URL(request.url()).pathname;
            requests.push(request.url());
            const ok = data => route.fulfill({ json: { status: "success", data } });
            if (resource === "/api/platform-admin/me") return ok({ platform_role: role, user: {} });
            if (resource === api) {
                reads++;
                return ok({ keys: [{ id: 8, label: null, clients: 2, status: "disabled",
                    disabled_reason: "ours", limit: 30, usage: 2 }] });
            }
            if (resource === api + "/8/replace") {
                assert.equal(request.method(), "POST");
                body = request.postDataJSON();
                return ok({ label: "sk-or-v1-000...0000", moved_count: 2, old_key_disabled: false });
            }
            if (resource === "/platform-admin-api-keys.html") {
                return route.fulfill({ contentType: "text/html", body: await fs.readFile(
                    path.join(root, "web/dist/platform-admin-api-keys.html")) });
            }
            if (/^\/assets\/(js|css)\/[\w.-]+$/.test(resource)) {
                return route.fulfill({ path: path.join(root, "frontend", resource) });
            }
            return route.fulfill({ status: 204 });
        });
        await page.goto(url);
        const replace = page.getByRole("button", { name: /^Replace/ });
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
        await page.getByRole("button", { name: "Cancel" }).click();
        assert.equal(await input.inputValue(), "");
        await replace.click();
        await input.fill(fake);
        await page.getByLabel("Reason for replacement").fill("Provider rejected the key.");
        await page.getByRole("button", { name: "Save" }).click();
        await page.getByText(/OpenRouter did not confirm/).waitFor();
        assert.equal(await input.inputValue(), "");
        assert.equal(await input.getAttribute("type"), "password");
        assert.deepEqual(body, { api_key: fake, reason: "Provider rejected the key." });
        assert.ok(!requests.join("").includes(fake));
        assert.ok(!(await page.locator("body").textContent()).includes(fake));
        assert.equal(await page.evaluate(() => localStorage.length), 0);
        const previousReads = reads;
        role = "admin";
        await page.reload();
        await page.getByRole("heading", { name: "Access Denied" }).waitFor();
        assert.equal(reads, previousReads);
        assert.equal(await page.getByRole("link", { name: "API Key Management" }).count(), 0);
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
});
