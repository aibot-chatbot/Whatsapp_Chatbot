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
        "invalid_sort_by",
        "invalid_sort_order"
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

    async function platformFetch(path, signal) {
        let response;
        try {
            response = await authenticatedFetch(API_ROOT + path, {
                method: "GET",
                signal: signal,
                headers: { "Accept": "application/json" }
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

    function getMe(options) {
        const config = options || {};
        return platformFetch("/me", config.signal);
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

    function getCompany(companyId, options) {
        const id = requireCompanyId(companyId);
        return platformFetch("/companies/" + id, (options || {}).signal);
    }

    function getCompanySubscription(companyId, options) {
        const id = requireCompanyId(companyId);
        return platformFetch("/companies/" + id + "/subscription", (options || {}).signal);
    }

    function getCompanyAiCreditUsage(companyId, options) {
        const id = requireCompanyId(companyId);
        return platformFetch("/companies/" + id + "/ai-credit-usage", (options || {}).signal);
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

    window.PlatformAdminApi = Object.freeze({
        getMe: getMe,
        listCompanies: listCompanies,
        getCompany: getCompany,
        getCompanySubscription: getCompanySubscription,
        getCompanyAiCreditUsage: getCompanyAiCreditUsage,
        listCompanyUsers: listCompanyUsers,
        listCompanyChatbots: listCompanyChatbots
    });
}());
