(function () {
    "use strict";

    // Page-scoped client for the platform-admin help-article CRUD endpoints.
    //
    // This deliberately does NOT live in platform-admin-api.js. That module is a
    // read-mostly surface whose exported method list and mutation set are pinned
    // by tests/test_platform_admin_frontend.py, and it forbids DELETE outright.
    // Help-article authoring needs DELETE, so it gets its own bounded client with
    // its own error-code allowlist rather than widening the shared one.

    const ARTICLES_PATH = "/api/platform-admin/help/articles";

    const TITLE_MAX_LENGTH = 200;
    const BODY_MAX_LENGTH = 8000;
    const SLUG_MAX_LENGTH = 200;
    const SORT_ORDER_MAX = 1000000;
    const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

    // Mirrors the help_articles category check constraint in data/050_help_articles.sql
    // and ALLOWED_CATEGORIES in app/services/tenant_support_service.py.
    const CATEGORIES = Object.freeze([
        Object.freeze({ value: "technical", label: "Technical" }),
        Object.freeze({ value: "account", label: "Account" }),
        Object.freeze({ value: "chatbot", label: "Chatbot" }),
        Object.freeze({ value: "integration", label: "Integration" }),
        Object.freeze({ value: "billing_question", label: "Billing question" }),
        Object.freeze({ value: "ai_credits", label: "AI credits" }),
        Object.freeze({ value: "other", label: "Other" })
    ]);
    const CATEGORY_VALUES = new Set(CATEGORIES.map(function (item) { return item.value; }));

    const SAFE_ERROR_CODES = new Set([
        "help_article_not_found",
        "help_article_slug_exists",
        "invalid_article_id",
        "invalid_category",
        "invalid_title",
        "invalid_body",
        "invalid_slug",
        "invalid_sort_order",
        "invalid_is_published",
        "invalid_request",
        "no_change",
        "platform_admin_access_denied",
        "platform_admin_data_unavailable"
    ]);

    function makeError(category, status, code) {
        const error = new Error(category);
        error.name = "PlatformAdminHelpApiError";
        error.category = category;
        error.status = status;
        error.code = SAFE_ERROR_CODES.has(code) ? code : "help_article_request_failed";
        return error;
    }

    function categoryForStatus(status) {
        if (status === 400) return "validation";
        if (status === 401) return "unauthenticated";
        if (status === 403) return "access_denied";
        if (status === 404) return "not_found";
        if (status === 409) return "validation";
        return "unavailable";
    }

    async function helpFetch(path, signal, method, body, requireData) {
        let response;
        try {
            response = await authenticatedFetch(path, {
                method: method,
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
        if (requireData && !("data" in payload)) {
            throw makeError("unavailable", response.status, "platform_admin_data_unavailable");
        }
        return "data" in payload ? payload.data : null;
    }

    function requireArticleId(articleId) {
        if (!Number.isSafeInteger(articleId) || articleId <= 0) {
            throw makeError("validation", 400, "invalid_article_id");
        }
        return String(articleId);
    }

    function assignCategory(target, fields) {
        if (!("category" in fields)) return;
        if (typeof fields.category !== "string" || !CATEGORY_VALUES.has(fields.category)) {
            throw makeError("validation", 400, "invalid_category");
        }
        target.category = fields.category;
    }

    function assignText(target, fields, key, maxLength, code) {
        if (!(key in fields)) return;
        const value = typeof fields[key] === "string" ? fields[key].trim() : "";
        if (!value || value.length > maxLength) {
            throw makeError("validation", 400, code);
        }
        target[key] = value;
    }

    function assignSlug(target, fields) {
        if (!("slug" in fields)) return;
        const value = typeof fields.slug === "string" ? fields.slug.trim() : "";
        if (!value) return;
        if (value.length > SLUG_MAX_LENGTH || !SLUG_PATTERN.test(value)) {
            throw makeError("validation", 400, "invalid_slug");
        }
        target.slug = value;
    }

    function assignFlags(target, fields) {
        if ("is_published" in fields) {
            if (typeof fields.is_published !== "boolean") {
                throw makeError("validation", 400, "invalid_is_published");
            }
            target.is_published = fields.is_published;
        }
        if ("sort_order" in fields) {
            const order = fields.sort_order;
            if (!Number.isSafeInteger(order) || order < 0 || order > SORT_ORDER_MAX) {
                throw makeError("validation", 400, "invalid_sort_order");
            }
            target.sort_order = order;
        }
    }

    function buildPayload(fields) {
        const source = fields && typeof fields === "object" ? fields : {};
        const payload = {};
        assignCategory(payload, source);
        assignText(payload, source, "title", TITLE_MAX_LENGTH, "invalid_title");
        assignText(payload, source, "body", BODY_MAX_LENGTH, "invalid_body");
        assignSlug(payload, source);
        assignFlags(payload, source);
        return payload;
    }

    function listArticles(options) {
        const config = options || {};
        return helpFetch(ARTICLES_PATH, config.signal, "GET", null, true).then(function (data) {
            const articles = data && Array.isArray(data.articles) ? data.articles : null;
            if (!articles) {
                throw makeError("unavailable", 200, "platform_admin_data_unavailable");
            }
            return articles;
        });
    }

    function createArticle(fields, options) {
        const payload = buildPayload(fields);
        if (!payload.category) throw makeError("validation", 400, "invalid_category");
        if (!payload.title) throw makeError("validation", 400, "invalid_title");
        if (!payload.body) throw makeError("validation", 400, "invalid_body");
        return helpFetch(ARTICLES_PATH, (options || {}).signal, "POST", payload, false);
    }

    function updateArticle(articleId, fields, options) {
        const id = requireArticleId(articleId);
        const payload = buildPayload(fields);
        if (Object.keys(payload).length === 0) {
            throw makeError("validation", 400, "invalid_request");
        }
        return helpFetch(ARTICLES_PATH + "/" + id, (options || {}).signal, "PATCH", payload, false);
    }

    function removeArticle(articleId, options) {
        const id = requireArticleId(articleId);
        return helpFetch(ARTICLES_PATH + "/" + id, (options || {}).signal, "DELETE", null, false);
    }

    window.PlatformAdminHelpApi = Object.freeze({
        CATEGORIES: CATEGORIES,
        TITLE_MAX_LENGTH: TITLE_MAX_LENGTH,
        BODY_MAX_LENGTH: BODY_MAX_LENGTH,
        SLUG_MAX_LENGTH: SLUG_MAX_LENGTH,
        SLUG_PATTERN: SLUG_PATTERN,
        listArticles: listArticles,
        createArticle: createArticle,
        updateArticle: updateArticle,
        removeArticle: removeArticle
    });
}());
