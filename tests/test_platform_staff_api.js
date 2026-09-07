/* Exercise transport boundaries without a browser, network or real credentials. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const calls = [];
let response = { status: 200, body: { status: "success", data: { saved: true } } };
const context = {
    window: {}, URLSearchParams,
    authenticatedFetch: async (url, options) => {
        calls.push({ url, options });
        return { ok: response.status < 400, status: response.status, json: async () => response.body };
    },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../frontend/assets/js/platform-admin-api.js"), "utf8"), context);
const api = context.window.PlatformAdminApi;

(async () => {
    const signal = { aborted: false };
    await api.listApprovalRequests({ status: "pending", offset: 25, limit: 25, signal });
    assert.equal(calls.at(-1).url, "/api/platform-admin/approval-requests?limit=25&offset=25&status=pending");
    assert.equal(calls.at(-1).options.signal, signal);

    const decision = { status: "rejected", reason: "Duplicate request" };
    await api.decideApprovalRequest(7, decision);
    assert.equal(calls.at(-1).url, "/api/platform-admin/approval-requests/7/decision");
    assert.equal(calls.at(-1).options.method, "POST");
    assert.deepEqual(JSON.parse(calls.at(-1).options.body), decision);

    const access = { platform_role: "admin", modules: { billing: false, support: true, customers: false }, reason: "Support assignment" };
    await api.updatePlatformAdminAccess(9, access);
    assert.equal(calls.at(-1).url, "/api/platform-admin/platform-admin-users/9/access");
    assert.equal(calls.at(-1).options.method, "PATCH");
    assert.deepEqual(JSON.parse(calls.at(-1).options.body), access);

    await api.recheckCompanyBillingOrder(4, 12);
    assert.equal(calls.at(-1).url, "/api/platform-admin/companies/4/billing-orders/12/recheck");
    assert.deepEqual(JSON.parse(calls.at(-1).options.body), {});
    const before = calls.length;
    for (const invalid of [0, -1, true, "1/decision", Number.MAX_SAFE_INTEGER + 1]) {
        assert.throws(() => api.getApprovalRequest(invalid), error => error.category === "validation");
        assert.throws(() => api.recheckCompanyBillingOrder(4, invalid), error => error.category === "validation");
        assert.throws(() => api.updatePlatformAdminAccess(invalid, access), error => error.category === "validation");
    }
    assert.equal(calls.length, before);

    response = { status: 409, body: { status: "error", code: "approval_already_decided", message: "Private upstream detail" } };
    await assert.rejects(api.decideApprovalRequest(7, decision), error =>
        error.category === "conflict" && error.code === "approval_already_decided" && !error.message.includes("Private"));
    response = { status: 409, body: { status: "error", code: "gateway_recheck_unavailable" } };
    await assert.rejects(api.recheckCompanyBillingOrder(4, 12), error => error.code === "gateway_recheck_unavailable");
    response = { status: 503, body: { status: "error", code: "secret-database-object" } };
    await assert.rejects(api.getMe(), error => error.code === "platform_admin_request_failed");
    console.log("platform staff API boundaries: passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
