"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function createStorage(initialValues) {
    const values = new Map(Object.entries(initialValues || {}));
    return {
        getItem(key) {
            return values.has(key) ? values.get(key) : null;
        },
        setItem(key, value) {
            values.set(key, String(value));
        },
        removeItem(key) {
            values.delete(key);
        },
    };
}

function loadAuth(initialSession, initialLocal) {
    const context = {
        sessionStorage: createStorage(initialSession),
        localStorage: createStorage(initialLocal),
        window: {
            location: {
                href: "",
                replacedWith: null,
                replace(value) {
                    this.replacedWith = value;
                },
            },
        },
        fetch: async () => {
            throw new Error("fetch must not run in session-switch tests");
        },
        URLSearchParams,
        Number,
        JSON,
    };
    vm.createContext(context);
    const authPath = path.join(__dirname, "..", "frontend", "assets", "js", "auth.js");
    vm.runInContext(fs.readFileSync(authPath, "utf8"), context, { filename: authPath });
    return context;
}

const oldSession = {
    token: "old-token",
    user: JSON.stringify({ id: 3, company_id: 1 }),
    isLoggedIn: "true",
    selectedBotId: "29",
};
const oldLocal = {};

{
    const context = loadAuth(oldSession, oldLocal);
    const created = context.establishAuthenticatedSession(
        { id: 31, company_id: 28 },
        "new-token"
    );

    assert.strictEqual(created, true);
    assert.strictEqual(context.sessionStorage.getItem("token"), "new-token");
    assert.deepStrictEqual(
        JSON.parse(context.sessionStorage.getItem("user")),
        { id: 31, company_id: 28 }
    );
    assert.strictEqual(context.sessionStorage.getItem("selectedBotId"), null);
}

for (const invalidToken of [null, undefined, "", "   ", 123]) {
    const context = loadAuth(oldSession, oldLocal);
    const created = context.establishAuthenticatedSession(
        { id: 31, company_id: 28 },
        invalidToken
    );

    assert.strictEqual(created, false);
    assert.strictEqual(context.sessionStorage.getItem("token"), null);
    assert.strictEqual(context.sessionStorage.getItem("user"), null);
    assert.strictEqual(context.sessionStorage.getItem("isLoggedIn"), null);
    assert.strictEqual(context.sessionStorage.getItem("selectedBotId"), null);
}

(async () => {
    const context = loadAuth(oldSession, oldLocal);
    context.fetch = async () => ({ ok: false, status: 404 });

    const authorized = await context.validateChatbotContext("29");
    assert.strictEqual(authorized, false);
    assert.strictEqual(context.window.location.replacedWith, "bots.html");
    assert.strictEqual(context.sessionStorage.getItem("selectedBotId"), null);
    console.log("auth session-switch behavior: passed");
})().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
