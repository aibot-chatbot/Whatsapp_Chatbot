const { test, expect } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");
const { execFileSync } = require("child_process");
const path = require("path");

let server;
test.beforeAll(async () => { server = await startServer(); });
test.afterAll(async () => { await new Promise(resolve => server.close(resolve)); });

const root = path.resolve(__dirname, "..", "..");
// Read pure catalog definitions without importing Flask or external clients.
const catalog = JSON.parse(execFileSync(process.env.E2E_PYTHON || path.join(root, ".venv", "Scripts", "python.exe"), [
    "-c", 'import json, runpy; m=runpy.run_path("app/services/model_catalog.py"); print(json.dumps(m["get_models_with_tiers"]()))'
], { cwd: root, encoding: "utf8" }));
const [qwen, oss, llama] = catalog.cloudflare.models;

async function setup(page, { plan = "essential", legacy = false, unavailable = false, activeFree = false, savedProvider = "openai" } = {}) {
    const writes = [];
    await page.addInitScript(() => {
        sessionStorage.setItem("token", "test-token");
        sessionStorage.setItem("user", JSON.stringify({ id: 31, company_id: 42, role: "owner", status: "active" }));
    });
    await page.route("https://fonts.googleapis.com/**", route => route.abort());
    await page.route("https://fonts.gstatic.com/**", route => route.abort());
    await page.route("https://unpkg.com/**", route => route.abort());
    await page.route("**/api/**", async route => {
        const path = new URL(route.request().url()).pathname;
        const respond = data => route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
        if (path === "/api/ai-models") {
            if (unavailable) return respond({ status: "error" });
            return respond({ status: "success", read_only: plan === "free", access_allowed: true,
                access_state: plan === "free" ? "active_trial" : plan, data: catalog });
        }
        if (path === "/api/billing/subscription") return respond({ status: "success", data: {
            status: plan === "free" && !activeFree ? "trialing" : "active",
            plan: { code: plan, model_access_tier: plan === "essential" ? "economy" : plan === "advanced" ? "standard" : "premium", feature_flags: {} }
        } });
        if (path === "/api/bots/7") {
            if (route.request().method() === "PUT") {
                writes.push(route.request().postDataJSON());
                return respond({ status: "success" });
            }
            return respond({ status: "success", data: { id: 7, bot_name: "Test assistant", ai_provider: legacy ? "openrouter" : (plan === "pro" ? savedProvider : "cloudflare"), model_name: legacy ? "legacy/model" : (plan === "pro" ? catalog[savedProvider].models[0].value : qwen.value) } });
        }
        return respond({ status: "success", data: {} });
    });
    await page.goto("/behaviour.html?bot_id=7&tab=model");
    await expect(page.locator("#bh-bot-name")).toHaveText("Test assistant");
    return writes;
}

for (const [plan, labels] of [["free", [qwen.label]], ["essential", [qwen.label, oss.label]], ["advanced", [qwen.label, oss.label, llama.label]]]) {
    test(`${plan} offers exactly its authorized models`, async ({ page }) => {
        const writes = await setup(page, { plan });
        await expect(page.locator("#bh-provider")).toHaveValue("cloudflare");
        await expect(page.locator("#bh-provider option")).toHaveCount(1);
        await expect(page.locator("#bh-model option")).toHaveText(labels);
        if (plan === "free") await expect(page.locator("#bh-model")).toBeDisabled();
        else await expect(page.locator("#bh-model")).toBeEnabled();
        expect(writes).toEqual([]);
    });
}

for (const provider of ["openai", "anthropic", "google"]) {
    test(`Pro preserves saved ${provider} model and hides Cloudflare`, async ({ page }) => {
        const writes = await setup(page, { plan: "pro", savedProvider: provider });
        await expect(page.locator("#bh-provider option")).toHaveCount(3);
        await expect(page.locator('#bh-provider option[value="cloudflare"]')).toHaveCount(0);
        await expect(page.locator("#bh-provider")).toHaveValue(provider);
        await expect(page.locator("#bh-savestate-text")).toHaveText("All changes saved");
        await page.locator("#bh-advanced summary").click();
        for (const choice of ["openai", "anthropic", "google"]) {
            await page.locator("#bh-provider").selectOption(choice);
            await expect(page.locator("#bh-model option")).toHaveText([catalog[choice].models[0].label]);
        }
        expect(writes).toEqual([]);
        if (provider !== "google") {
            await page.locator("#bh-save").click();
            await expect(page.locator("#bh-savestate-text")).toHaveText("All changes saved");
            expect(writes[0]).toMatchObject({ ai_provider: "google", model_name: catalog.google.models[0].value });
        }
    });
}

test("legacy model replacement stays unsaved until explicitly saved", async ({ page }) => {
    const writes = await setup(page, { legacy: true });
    await expect(page.locator("#bh-plan-note")).toContainText("Review the selected replacement");
    await expect(page.locator("#bh-savestate-text")).toHaveText("Unsaved changes");
    expect(writes).toEqual([]);
    await page.locator("#bh-save").click();
    await expect(page.locator("#bh-savestate-text")).toHaveText("All changes saved");
    expect(writes[0]).toMatchObject({ ai_provider: "cloudflare", model_name: qwen.value });
    await expect(page.locator("#bh-plan-note")).not.toContainText("Review the selected replacement");
});

test("catalog failure does not overwrite a saved model when style is edited", async ({ page }) => {
    const writes = await setup(page, { legacy: true, unavailable: true });
    await expect(page.locator("#bh-model")).toBeDisabled();
    await page.locator('.bh-style[data-style="precise"]').click();
    await page.locator("#bh-save").click();
    await expect(page.locator("#bh-savestate-text")).toHaveText("All changes saved");
    expect(writes[0]).not.toHaveProperty("ai_provider");
    expect(writes[0]).not.toHaveProperty("model_name");
});

test("denied or missing subscription access cannot expose Cloudflare models", async ({ page }) => {
    await setup(page);
    const result = await page.evaluate(model => {
        const state = { options: { cloudflare: { models: [model] } }, accessAllowed: false, readOnly: true,
            access: { status: "trialing", plan: { code: "free" } } };
        return [window.modelCatalog.allowedProviders(state).length, window.modelCatalog.hasAnyAccess(state),
            window.modelCatalog.isModelAllowed(model, { access: null, accessAllowed: true })];
    }, qwen);
    expect(result).toEqual([0, false, false]);
});

test("legacy active Free subscription displays its fixed trial model", async ({ page }) => {
    await setup(page, { plan: "free", activeFree: true });
    await expect(page.locator("#bh-model option")).toHaveText([qwen.label]);
    await expect(page.locator("#bh-model")).toBeDisabled();
    await expect(page.locator("#bh-plan-note")).toContainText("Your trial runs on a fixed model");
});

test("pricing displays the same model counts as the public plan catalog", async ({ page }) => {
    await setup(page);
    await page.addScriptTag({ path: path.join(root, "frontend/assets/js/plan-catalog.js") });
    const plans = await page.evaluate(() => window.SubscriptionPlanCatalog.plans);
    await page.route("**/api/billing/plans", route => route.fulfill({ contentType: "application/json",
        body: JSON.stringify({ status: "success", data: plans }) }));
    await page.goto("/pricing.html");
    for (const plan of plans) {
        await expect(page.locator(`.plan-card[data-plan-code="${plan.code}"] [data-feature-key="model_access_tier"]`))
            .toContainText(plan.model_access_label);
    }
    await expect(page.locator("#plans-grid")).not.toContainText("DeepSeek");
});
