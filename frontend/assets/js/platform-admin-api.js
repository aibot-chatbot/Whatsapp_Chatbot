(function () {
    "use strict";

    const API_ROOT = "/api/platform-admin";
    const SAFE_ERROR_CODES = new Set([
        "authentication_backend_unavailable",
        "platform_admin_access_denied",
        "platform_admin_authorization_unavailable",
        "platform_admin_data_unavailable",
        "platform_admin_audit_unavailable",
        "company_not_found",
        "invalid_limit",
        "invalid_offset",
        "invalid_search",
        "invalid_status",
        "invalid_state",
        "invalid_transaction_type",
        "invalid_action",
        "invalid_resource_type",
        "invalid_actor_user_id",
        "invalid_resource_id",
        "invalid_created_after",
        "invalid_created_before",
        "invalid_sort_by",
        "invalid_sort_order",
        "invalid_company_id",
        "invalid_priority",
        "invalid_case_id",
        "invalid_title",
        "invalid_redacted_summary",
        "invalid_redacted_note",
        "invalid_request",
        "no_change",
        "support_case_not_found"
    ]);

    function makeError(category, status, code) {
        const error = new Error(category);
        error.name = "PlatformAdminApiError";
        error.category = category;
        error.status = status;
        error.code = SAFE_ERROR_CODES.has(code) ? code : "platform_admin_request_failed";
        return error;
    }

    function categoryForStatus(status) {
        if (status === 400) return "validation";
        if (status === 401) return "unauthenticated";
        if (status === 403) return "access_denied";
        if (status === 404) return "not_found";
        if (status === 503) return "unavailable";
        return "unavailable";
    }

    async function platformFetch(path, signal, method, body) {
        const requestMethod = method || "GET";
        let response;
        try {
            response = await authenticatedFetch(API_ROOT + path, {
                method: requestMethod,
                signal: signal,
                headers: {
                    "Accept": "application/json",
                    ...(body ? { "Content-Type": "application/json" } : {})
                },
                ...(body ? { body: JSON.stringify(body) } : {})
            });
        } catch (error) {
            if ((signal && signal.aborted) || (error && error.name === "AbortError")) {
                throw makeError("aborted", 0, "request_aborted");
            }
            throw makeError("unavailable", 0, "platform_admin_data_unavailable");
        }

        let payload = null;
        try {
            payload = await response.json();
        } catch (_) {
            throw makeError("unavailable", response.status, "platform_admin_data_unavailable");
        }

        if (!response.ok || !payload || payload.status !== "success") {
            const code = payload && typeof payload.code === "string" ? payload.code : null;
            throw makeError(categoryForStatus(response.status), response.status, code);
        }
        if (!("data" in payload)) {
            throw makeError("unavailable", response.status, "platform_admin_data_unavailable");
        }
        return payload.data;
    }

    function requireCompanyId(companyId) {
        if (!Number.isSafeInteger(companyId) || companyId <= 0) {
            throw makeError("validation", 400, "invalid_company_id");
        }
        return String(companyId);
    }

    function requireCaseId(caseId) {
        if (!Number.isSafeInteger(caseId) || caseId <= 0) {
            throw makeError("validation", 400, "invalid_case_id");
        }
        return String(caseId);
    }

    function getMe(options) {
        const config = options || {};
        return platformFetch("/me", config.signal);
    }

    function getOverview(options) {
        const config = options || {};
        return platformFetch("/overview", config.signal);
    }

    function listCompanies(options) {
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit));
        params.set("offset", String(config.offset));
        params.set("sort_by", config.sortBy);
        params.set("sort_order", config.sortOrder);
        if (config.status) params.set("status", config.status);
        if (config.search) params.set("search", config.search);
        return platformFetch("/companies?" + params.toString(), config.signal);
    }

    function listAuditEvents(options) {
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit));
        params.set("offset", String(config.offset));
        if (config.action) params.set("action", config.action);
        if (config.resourceType) params.set("resource_type", config.resourceType);
        if (config.actorUserId) params.set("actor_user_id", String(config.actorUserId));
        if (config.resourceId) params.set("resource_id", config.resourceId);
        if (config.createdAfter) params.set("created_after", config.createdAfter);
        if (config.createdBefore) params.set("created_before", config.createdBefore);
        return platformFetch("/audit-events?" + params.toString(), config.signal);
    }

    function getCompany(companyId, options) {
        const id = requireCompanyId(companyId);
        return platformFetch("/companies/" + id, (options || {}).signal);
    }

    function getCompanySubscription(companyId, options) {
        const id = requireCompanyId(companyId);
        return platformFetch("/companies/" + id + "/subscription", (options || {}).signal);
    }

    function listCompanySubscriptionHistory(companyId, options) {
        const id = requireCompanyId(companyId);
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit));
        params.set("offset", String(config.offset));
        if (config.status) params.set("status", config.status);
        return platformFetch("/companies/" + id + "/subscription-history?" + params.toString(), config.signal);
    }

    function getCompanyAiCreditUsage(companyId, options) {
        const id = requireCompanyId(companyId);
        return platformFetch("/companies/" + id + "/ai-credit-usage", (options || {}).signal);
    }

    function listCompanyAiCreditTransactions(companyId, options) {
        const id = requireCompanyId(companyId);
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit));
        params.set("offset", String(config.offset));
        if (config.transactionType) params.set("transaction_type", config.transactionType);
        return platformFetch("/companies/" + id + "/ai-credit-transactions?" + params.toString(), config.signal);
    }

    function listCompanyBillingOrders(companyId, options) {
        const id = requireCompanyId(companyId);
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit));
        params.set("offset", String(config.offset));
        if (config.status) params.set("status", config.status);
        if (config.createdAfter) params.set("created_after", config.createdAfter);
        if (config.createdBefore) params.set("created_before", config.createdBefore);
        return platformFetch("/companies/" + id + "/billing-orders?" + params.toString(), config.signal);
    }

    function listCompanyUsers(companyId, options) {
        const id = requireCompanyId(companyId);
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit));
        params.set("offset", String(config.offset));
        params.set("sort_by", config.sortBy);
        params.set("sort_order", config.sortOrder);
        if (config.search) params.set("search", config.search);
        return platformFetch("/companies/" + id + "/users?" + params.toString(), config.signal);
    }

    function listCompanyChatbots(companyId, options) {
        const id = requireCompanyId(companyId);
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit));
        params.set("offset", String(config.offset));
        params.set("sort_by", config.sortBy);
        params.set("sort_order", config.sortOrder);
        params.set("state", config.state);
        if (config.search) params.set("search", config.search);
        return platformFetch("/companies/" + id + "/chatbots?" + params.toString(), config.signal);
    }

    function listSupportCases(options) {
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit || 25));
        params.set("offset", String(config.offset || 0));
        if (config.companyId) params.set("company_id", String(config.companyId));
        if (config.status) params.set("status", config.status);
        if (config.priority) params.set("priority", config.priority);
        return platformFetch("/support-cases?" + params.toString(), config.signal);
    }

    function createSupportCase(payload, options) {
        return platformFetch("/support-cases", (options || {}).signal, "POST", payload);
    }

    function getSupportCase(caseId, options) {
        const id = requireCaseId(caseId);
        return platformFetch("/support-cases/" + id, (options || {}).signal);
    }

    function addSupportCaseNote(caseId, payload, options) {
        const id = requireCaseId(caseId);
        return platformFetch("/support-cases/" + id + "/notes", (options || {}).signal, "POST", payload);
    }

    function updateSupportCase(caseId, payload, options) {
        const id = requireCaseId(caseId);
        return platformFetch("/support-cases/" + id, (options || {}).signal, "PATCH", payload);
    }

    window.PlatformAdminApi = Object.freeze({
        getMe: getMe,
        getOverview: getOverview,
        listCompanies: listCompanies,
        listAuditEvents: listAuditEvents,
        getCompany: getCompany,
        getCompanySubscription: getCompanySubscription,
        listCompanySubscriptionHistory: listCompanySubscriptionHistory,
        getCompanyAiCreditUsage: getCompanyAiCreditUsage,
        listCompanyAiCreditTransactions: listCompanyAiCreditTransactions,
        listCompanyBillingOrders: listCompanyBillingOrders,
        listCompanyUsers: listCompanyUsers,
        listCompanyChatbots: listCompanyChatbots,
        listSupportCases: listSupportCases,
        createSupportCase: createSupportCase,
        getSupportCase: getSupportCase,
        addSupportCaseNote: addSupportCaseNote,
        updateSupportCase: updateSupportCase
    });
}());
