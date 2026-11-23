const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = readFileSync(path.join(__dirname, "../web/public/assets/js/integration.js"), "utf8");
const labels = {
    coexistence: "I already use the WhatsApp Business app on this number",
    standard: "Connect a new number"
};

async function visit() {
    const nodes = new Map(), listeners = new Map(), posts = [], calls = {};
    const storage = new Map();
    const node = id => {
        if (!nodes.has(id)) nodes.set(id, {
            isConnected: true, textContent: "", value: "", dataset: {},
            setCustomValidity() {}, replaceChildren() {}, focus() {}, scrollIntoView() {},
            querySelectorAll: () => []
        });
        return nodes.get(id);
    };
    let click;
    const window = {
        location: new URL("https://portal.test/integration.html?bot_id=42"),
        history: { replaceState() {} }, matchMedia: () => ({ matches: true }),
        addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); },
        removeEventListener(name, fn) { listeners.get(name)?.delete(fn); },
        FB: { init(options) { calls.version = options.version; }, login(callback, options) { Object.assign(calls, { callback, options }); } }
    };
    const document = {
        getElementById: id => id === "pub-linked-pair" ? null : node(id),
        createElement: () => ({}), head: { appendChild: script => script.onload() },
        addEventListener: (name, fn) => { if (name === "click") click = fn; },
        querySelectorAll: () => []
    };
    const context = vm.createContext({ window, document, URL, URLSearchParams, navigator: {}, setTimeout, clearTimeout,
        sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
        authenticatedFetch: async (url, options) => {
            if (url.includes("/complete?")) {
                posts.push(JSON.parse(options.body));
                return new Promise(() => {}); // Capture completion at the HTTP boundary.
            }
            const data = url.endsWith("/config") ? { app_id: "111", config_id: "222", graph_api_version: "v99.0" }
                : { allowed: true, state: "passed" };
            return { ok: true, status: 200, json: async () => ({ status: "success", data }) };
        }
    });
    vm.runInContext(source, context);
    await vm.runInContext("loadMetaSignup()", context);
    vm.runInContext("openFlow('whatsapp')", context);
    const markup = vm.runInContext("metaFlow()", context);
    node("pub-meta-phone").value = "+60123456789";
    function message(event, data, origin = "https://www.facebook.com", type = "WA_EMBEDDED_SIGNUP") {
        for (const listener of listeners.get("message") || []) {
            listener({ origin, data: JSON.stringify({ type, event, data }) });
        }
    }
    async function launch(mode) {
        const buttons = [...markup.matchAll(/<button\b([^>]*)>([^<]+)<\/button>/g)];
        const button = buttons.find(match => match[2] === labels[mode]);
        assert.ok(button, "missing signup choice: " + labels[mode]);
        const id = /id="([^"]+)"/.exec(button[1])?.[1];
        const target = node(id || mode);
        target.dataset.metaSignup = /data-meta-signup="([^"]+)"/.exec(button[1])?.[1];
        target.textContent = labels[mode];
        target.closest = selector => selector === "#" + id || selector === "[data-meta-signup]" ? target : null;
        click({ target });
        await new Promise(resolve => setImmediate(resolve));
        assert.ok(calls.callback, "Meta login was launched");
    }
    return { launch, calls, message, posts, node, context };
}

test("both number choices launch v4 with the configured Graph version", async () => {
    for (const mode of ["standard", "coexistence"]) {
        const page = await visit();
        await page.launch(mode);
        assert.equal(page.calls.version, "v99.0");
        const extras = mode === "standard" ? { setup: {} } : { setup: {}, featureType: "whatsapp_business_app_onboarding" };
        assert.deepEqual(JSON.parse(JSON.stringify(page.calls.options)), {
            config_id: "222", response_type: "code", override_default_response_type: true, extras
        });
        page.message("CANCEL", { current_step: "START" });
        page.calls.callback({});
    }
});

test("finish event determines the onboarding type in either callback order", async () => {
    const ids = { waba_id: "10", phone_number_id: "20", business_id: "30" };
    for (const [mode, finish, expected] of [
        ["standard", "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING", "coexistence"],
        ["coexistence", "FINISH", "standard"]
    ]) {
        const page = await visit();
        await page.launch(mode);
        if (mode === "standard") {
            page.calls.callback({ authResponse: { code: "mock-code" } });
            await new Promise(resolve => setImmediate(resolve));
        }
        page.message(finish, ids);
        if (mode === "coexistence") {
            page.message("CANCEL", { current_step: "FINISH" }); // Closing the final screen.
            page.calls.callback({ authResponse: { code: "mock-code" } });
        }
        page.message(finish, ids);
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(page.posts, [{ ...ids, code: "mock-code", phone_number: "+60123456789", onboarding_type: expected }]);
    }
});

test("cancel and error show only the relevant step or code on the card", async () => {
    for (const [event, data, expected] of [
        ["CANCEL", { current_step: "VERIFY_PHONE_NUMBER" }, /cancelled.*VERIFY_PHONE_NUMBER/i],
        ["ERROR", { error_code: 133016 }, /error.*133016/i]
    ]) {
        const page = await visit();
        await page.launch("standard");
        page.calls.callback({});
        page.message(event, { ...data, error_message: "private detail", session_id: "sensitive-id" });
        await new Promise(resolve => setImmediate(resolve));
        const shown = page.node("pub-whatsapp-result").innerHTML || "";
        assert.match(shown, expected);
        assert.doesNotMatch(shown, /private detail|sensitive-id|session_id|error_message/);
        assert.deepEqual(page.posts, []);
    }
});

test("untrusted origins and other event types cannot contribute a signup", async () => {
    const page = await visit();
    await page.launch("standard");
    const ids = { waba_id: "10", phone_number_id: "20", business_id: "30" };
    for (const origin of ["https://notfacebook.com", "https://facebook.com.example", "http://www.facebook.com", "null"]) {
        page.message("FINISH", ids, origin);
    }
    page.message("FINISH", ids, "https://facebook.com", "OTHER_SIGNUP");
    page.calls.callback({ authResponse: { code: "mock-code" } });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(page.posts, []);
    page.message("FINISH", ids, "https://facebook.com");
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(page.posts.length, 1);
});

test("the registration-limit response tells the owner when to retry", async () => {
    const { context } = await visit();
    const message = vm.runInContext("providerError({status:429, body:{code:'registration_rate_limited', message:'private detail'}})", context);
    assert.equal(message, "Too many registration attempts. Try again in 72 hours.");
});
