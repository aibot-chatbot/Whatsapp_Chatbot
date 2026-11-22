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
        "invalid_plan",
        "invalid_attention",
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
        "invalid_event_limit",
        "invalid_event_offset",
        "invalid_title",
        "invalid_redacted_summary",
        "invalid_redacted_note",
        "invalid_redacted_body",
        "invalid_assignee",
        "invalid_request",
        "no_change",
        "support_case_not_found",
        "support_case_linkage_invalid",
        "invalid_request_id",
        "invalid_category",
        "invalid_days",
        "tenant_support_request_not_found",
        "invalid_platform_admin_user_id",
        "invalid_user_id",
        "invalid_is_active",
        "target_user_not_found",
        "target_user_inactive",
        "target_user_not_protected",
        "platform_admin_mapping_exists",
        "platform_admin_user_not_found",
        "self_deactivation_not_allowed",
        "final_active_platform_admin",
        "protected_company",
        "platform_module_access_denied", "invalid_platform_role", "invalid_modules",
        "invalid_reason", "invalid_approval_id", "invalid_approval_type",
        "approval_request_not_found", "approval_already_decided",
        "self_demotion_not_allowed", "final_active_super_admin",
        "invalid_id", "invalid_order_id", "invalid_type", "invalid_summary",
        "invalid_pagination", "approval_not_found", "platform_record_not_found",
        "platform_change_denied", "self_demotion_denied", "platform_staff_data_unavailable",
        "billing_order_not_found", "gateway_recheck_unavailable"
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
        if (status === 409) return "conflict";
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

    function requirePlatformAdminUserId(mappingId) {
        if (!Number.isSafeInteger(mappingId) || mappingId <= 0) {
            throw makeError("validation", 400, "invalid_platform_admin_user_id");
        }
        return String(mappingId);
    }

    function requireUserId(userId) {
        if (!Number.isSafeInteger(userId) || userId <= 0) {
            throw makeError("validation", 400, "invalid_user_id");
        }
        return userId;
    }

    function getMe(options) {
        const config = options || {};
        return platformFetch("/me", config.signal);
    }

    function getOverview(options) {
        const config = options || {};
        return platformFetch("/overview", config.signal);
    }

    function getBillingOverview(options) {
        const config = options || {};
        return platformFetch("/billing/overview", config.signal);
    }

    function listBillingCompanies(options) {
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit || 25));
        params.set("offset", String(config.offset || 0));
        if (config.subscriptionStatus) params.set("subscription_status", config.subscriptionStatus);
        if (config.plan) params.set("plan", config.plan);
        if (typeof config.attention === "boolean") params.set("attention", String(config.attention));
        return platformFetch("/billing/companies?" + params.toString(), config.signal);
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

    function listSafetyFlags(options) {
        const config = options || {};
        const params = new URLSearchParams();
        params.set("days", String(config.days ?? 7));
        if (config.companyId !== undefined) params.set("company_id", String(config.companyId));
        if (config.category) params.set("category", config.category);
        return platformFetch("/safety-flags?" + params.toString(), config.signal);
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

    function listPlatformAdminUsers(options) {
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit || 100));
        params.set("offset", String(config.offset || 0));
        if (typeof config.isActive === "boolean") params.set("is_active", String(config.isActive));
        return platformFetch("/platform-admin-users?" + params.toString(), config.signal);
    }

    function getPlatformAdminUser(mappingId, options) {
        const id = requirePlatformAdminUserId(mappingId);
        return platformFetch("/platform-admin-users/" + id, (options || {}).signal);
    }

    function createPlatformAdminUser(userId, options) {
        const id = requireUserId(userId);
        return platformFetch("/platform-admin-users", (options || {}).signal, "POST", { user_id: id });
    }

    function setPlatformAdminUserActive(mappingId, isActive, options) {
        const id = requirePlatformAdminUserId(mappingId);
        if (typeof isActive !== "boolean") {
            throw makeError("validation", 400, "invalid_is_active");
        }
        return platformFetch("/platform-admin-users/" + id + "/active", (options || {}).signal, "PATCH", { is_active: isActive });
    }

    function getCompany(companyId, options) {
        const id = requireCompanyId(companyId);
        return platformFetch("/companies/" + id, (options || {}).signal);
    }

    function suspendCompany(companyId, options) {
        const id = requireCompanyId(companyId);
        return platformFetch("/companies/" + id + "/suspend", (options || {}).signal, "POST", {});
    }

    function restoreCompany(companyId, options) {
        const id = requireCompanyId(companyId);
        return platformFetch("/companies/" + id + "/restore", (options || {}).signal, "POST", {});
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
        const config = options || {};
        const params = new URLSearchParams();
        params.set("event_limit", String(config.eventLimit || 25));
        params.set("event_offset", String(config.eventOffset || 0));
        return platformFetch("/support-cases/" + id + "?" + params.toString(), config.signal);
    }

    function listSupportCaseAssignees(options) {
        return platformFetch("/support-case-assignees", (options || {}).signal);
    }

    function listTenantSupportRequests(options) {
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit || 25));
        params.set("offset", String(config.offset || 0));
        if (config.companyId) params.set("company_id", String(config.companyId));
        if (config.category) params.set("category", config.category);
        if (config.status) params.set("status", config.status);
        return platformFetch("/tenant-support-requests?" + params.toString(), config.signal);
    }

    function getTenantSupportRequest(requestId, options) {
        if (!Number.isSafeInteger(requestId) || requestId <= 0) {
            throw makeError("validation", 400, "invalid_request_id");
        }
        return platformFetch("/tenant-support-requests/" + String(requestId), (options || {}).signal);
    }

    function updateTenantSupportRequest(requestId, payload, options) {
        if (!Number.isSafeInteger(requestId) || requestId <= 0) {
            throw makeError("validation", 400, "invalid_request_id");
        }
        return platformFetch(
            "/tenant-support-requests/" + String(requestId),
            (options || {}).signal,
            "PATCH",
            payload
        );
    }

    function convertTenantSupportRequest(requestId, options) {
        if (!Number.isSafeInteger(requestId) || requestId <= 0) {
            throw makeError("validation", 400, "invalid_request_id");
        }
        return platformFetch(
            "/tenant-support-requests/" + String(requestId) + "/convert",
            (options || {}).signal,
            "POST",
            {}
        );
    }

    function addSupportCaseNote(caseId, payload, options) {
        const id = requireCaseId(caseId);
        return platformFetch("/support-cases/" + id + "/notes", (options || {}).signal, "POST", payload);
    }

    function listSupportCaseReplies(caseId, options) {
        const id = requireCaseId(caseId);
        const config = options || {};
        const params = new URLSearchParams();
        params.set("limit", String(config.limit || 25));
        params.set("offset", String(config.offset || 0));
        return platformFetch("/support-cases/" + id + "/replies?" + params.toString(), config.signal);
    }

    function createSupportCaseReply(caseId, payload, options) {
        const id = requireCaseId(caseId);
        return platformFetch("/support-cases/" + id + "/replies", (options || {}).signal, "POST", payload);
    }

    function assignSupportCase(caseId, payload, options) {
        const id = requireCaseId(caseId);
        return platformFetch("/support-cases/" + id + "/assignment", (options || {}).signal, "PATCH", payload);
    }

    function updateSupportCaseStatus(caseId, payload, options) {
        const id = requireCaseId(caseId);
        return platformFetch("/support-cases/" + id + "/status", (options || {}).signal, "PATCH", payload);
    }

    function updateSupportCasePriority(caseId, payload, options) {
        const id = requireCaseId(caseId);
        return platformFetch("/support-cases/" + id + "/priority", (options || {}).signal, "PATCH", payload);
    }

    function listApprovalRequests(options) {
        const config = options || {};
        const params = new URLSearchParams({limit: String(config.limit || 25), offset: String(config.offset || 0)});
        if (config.status) params.set("status", config.status);
        return platformFetch("/approval-requests?" + params.toString(), config.signal);
    }

    function approvalPath(approvalId) {
        if (!Number.isSafeInteger(approvalId) || approvalId <= 0) {
            throw makeError("validation", 400, "invalid_approval_id");
        }
        return "/approval-requests/" + String(approvalId);
    }

    function getApprovalRequest(approvalId, options) {
        return platformFetch(approvalPath(approvalId), (options || {}).signal);
    }

    function createApprovalRequest(payload, options) {
        return platformFetch("/approval-requests", (options || {}).signal, "POST", payload);
    }

    function decideApprovalRequest(approvalId, payload, options) {
        return platformFetch(approvalPath(approvalId) + "/decision", (options || {}).signal, "POST", payload);
    }

    function updatePlatformAdminAccess(mappingId, payload, options) {
        return platformFetch("/platform-admin-users/" + requirePlatformAdminUserId(mappingId) + "/access",
            (options || {}).signal, "PATCH", payload);
    }

    function recheckCompanyBillingOrder(companyId, orderId, options) {
        if (!Number.isSafeInteger(orderId) || orderId <= 0) {
            throw makeError("validation", 400, "invalid_order_id");
        }
        return platformFetch("/companies/" + requireCompanyId(companyId) + "/billing-orders/" + String(orderId) + "/recheck",
            (options || {}).signal, "POST", {});
    }

    function listOpenRouterKeys(signal) {
        return platformFetch("/openrouter-keys", signal);
    }

    function replaceOpenRouterKey(id, payload, signal) {
        if (!Number.isSafeInteger(id) || id <= 0) throw makeError("validation", 400, "invalid_id");
        return platformFetch("/openrouter-keys/" + id + "/replace", signal, "POST", payload);
    }

    window.PlatformAdminApi = Object.freeze({
        getMe: getMe,
        listOpenRouterKeys: listOpenRouterKeys,
        replaceOpenRouterKey: replaceOpenRouterKey,
        listApprovalRequests: listApprovalRequests,
        getApprovalRequest: getApprovalRequest,
        createApprovalRequest: createApprovalRequest,
        decideApprovalRequest: decideApprovalRequest,
        updatePlatformAdminAccess: updatePlatformAdminAccess,
        recheckCompanyBillingOrder: recheckCompanyBillingOrder,
        getOverview: getOverview,
        getBillingOverview: getBillingOverview,
        listBillingCompanies: listBillingCompanies,
        listCompanies: listCompanies,
        listSafetyFlags: listSafetyFlags,
        listAuditEvents: listAuditEvents,
        listPlatformAdminUsers: listPlatformAdminUsers,
        getPlatformAdminUser: getPlatformAdminUser,
        createPlatformAdminUser: createPlatformAdminUser,
        setPlatformAdminUserActive: setPlatformAdminUserActive,
        getCompany: getCompany,
        suspendCompany: suspendCompany,
        restoreCompany: restoreCompany,
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
        listSupportCaseAssignees: listSupportCaseAssignees,
        listTenantSupportRequests: listTenantSupportRequests,
        getTenantSupportRequest: getTenantSupportRequest,
        updateTenantSupportRequest: updateTenantSupportRequest,
        convertTenantSupportRequest: convertTenantSupportRequest,
        addSupportCaseNote: addSupportCaseNote,
        listSupportCaseReplies: listSupportCaseReplies,
        createSupportCaseReply: createSupportCaseReply,
        assignSupportCase: assignSupportCase,
        updateSupportCaseStatus: updateSupportCaseStatus,
        updateSupportCasePriority: updateSupportCasePriority
    });
}());
