(function () {
    "use strict";

    const ui = PlatformAdminShell;
    const ACTIONS = [
        "platform_admin.identity.read",
        "platform_admin.operations.overview.read",
        "platform_admin.company.list",
        "platform_admin.company.read",
        "platform_admin.company.subscription.read",
        "platform_admin.company.subscription_history.read",
        "platform_admin.company.ai_credit_usage.read",
        "platform_admin.company.ai_credit_transactions.read",
        "platform_admin.company.billing_orders.read",
        "platform_admin.company.users.read",
        "platform_admin.company.chatbots.read",
        "platform_admin.audit_events.list"
    ];
    const RESOURCE_TYPES = [
        "platform_admin",
        "platform_operations_overview",
        "company",
        "company_subscription",
        "company_subscription_history",
        "company_ai_credit_usage",
        "company_ai_credit_transactions",
        "company_billing_orders",
        "company_users",
        "company_chatbots",
        "platform_admin_audit_events"
    ];
    const METADATA_KEYS = [
        "outcome",
        "endpoint",
        "http_method",
        "limit",
        "offset",
        "sort_by",
        "sort_order",
        "search_applied",
        "status_filter",
        "state_filter",
        "transaction_type_filter",
        "returned_count",
        "attention_company_count",
        "generated_at",
        "period_start",
        "period_end",
        "action_filter_applied",
        "resource_type_filter_applied",
        "actor_user_id_filter_applied",
        "resource_id_filter_applied",
        "created_after_filter_applied",
        "created_before_filter_applied"
    ];

    const state = {
        limit: 25,
        offset: 0,
        filters: {
            action: "",
            resourceType: "",
            actorUserId: "",
            resourceId: "",
            createdAfter: "",
            createdBefore: ""
        },
        controls: {},
        results: null,
        error: null
    };

    function safeValue(value) {
        return value === null || value === undefined || value === "" ? "Not available" : String(value);
    }

    function panel(title, description) {
        const section = ui.element("section", "platform-panel");
        section.append(ui.element("h2", "", title));
        if (description) section.append(ui.element("p", "platform-note", description));
        return section;
    }

    function option(value, label) {
        const node = document.createElement("option");
        node.value = value;
        node.textContent = label;
        return node;
    }

    function field(labelText, control) {
        const wrapper = ui.element("div", "platform-field");
        const label = ui.element("label", "", labelText);
        label.htmlFor = control.id;
        wrapper.append(label, control);
        return wrapper;
    }

    function metadataSummary(metadata) {
        const summary = ui.element("dl", "platform-audit-metadata");
        const safeMetadata = metadata && typeof metadata === "object" && !Array.isArray(metadata) ? metadata : {};
        let rendered = 0;
        METADATA_KEYS.forEach(function (key) {
            if (!Object.prototype.hasOwnProperty.call(safeMetadata, key)) return;
            const value = safeMetadata[key];
            if (value && typeof value === "object") return;
            const row = ui.element("div");
            row.append(ui.element("dt", "", key), ui.element("dd", "", safeValue(value)));
            summary.append(row);
            rendered += 1;
        });
        if (!rendered) summary.append(ui.element("p", "platform-note", "No safe metadata fields."));
        return summary;
    }

    function cardLine(label, value) {
        const line = ui.element("div");
        line.append(ui.element("dt", "", label));
        const dd = ui.element("dd");
        if (value && value.nodeType) dd.append(value);
        else dd.textContent = safeValue(value);
        line.append(dd);
        return line;
    }

    function renderCards(events) {
        const cards = ui.element("div", "platform-company-cards");
        cards.setAttribute("aria-label", "audit event cards");
        events.forEach(function (event) {
            const article = ui.element("article", "platform-company-card");
            article.append(ui.element("h3", "", safeValue(event.action)));
            const actor = event.actor && event.actor.platform_admin_user_id;
            const details = ui.element("dl", "platform-definition-grid");
            details.append(
                cardLine("Created", ui.formatDate(event.created_at)),
                cardLine("Actor mapping ID", actor),
                cardLine("Resource type", event.resource_type),
                cardLine("Resource ID", event.resource_id),
                cardLine("Safe metadata summary", metadataSummary(event.metadata))
            );
            article.append(details);
            cards.append(article);
        });
        return cards;
    }

    function renderTable(events) {
        const wrap = ui.element("div", "platform-table-wrap");
        const table = ui.element("table", "platform-table");
        const caption = ui.element("caption", "platform-skip-link", "Safe platform-admin audit events");
        const head = ui.element("thead");
        const header = ui.element("tr");
        ["Created", "Actor mapping ID", "Action", "Resource type", "Resource ID", "Safe metadata summary"].forEach(function (label) {
            const th = ui.element("th", "", label);
            th.scope = "col";
            header.append(th);
        });
        head.append(header);
        const body = ui.element("tbody");
        events.forEach(function (event) {
            const row = ui.element("tr");
            const actor = event.actor && event.actor.platform_admin_user_id;
            [
                ui.formatDate(event.created_at),
                actor,
                event.action,
                event.resource_type,
                event.resource_id
            ].forEach(function (value) {
                row.append(ui.element("td", "", safeValue(value)));
            });
            const metadataCell = ui.element("td");
            metadataCell.append(metadataSummary(event.metadata));
            row.append(metadataCell);
            body.append(row);
        });
        table.append(caption, head, body);
        wrap.append(table);
        return wrap;
    }

    function renderPagination(pagination) {
        const nav = ui.element("nav", "platform-pagination");
        nav.setAttribute("aria-label", "Audit event pagination");
        nav.append(ui.element(
            "span",
            "",
            "Showing " + safeValue(pagination.returned) + " of " + safeValue(pagination.total) + " audit events"
        ));
        const actions = ui.element("div", "platform-pagination-actions");
        const previous = ui.element("button", "platform-button", "Previous");
        previous.type = "button";
        previous.disabled = !pagination.offset;
        previous.addEventListener("click", function () {
            state.offset = Math.max(0, pagination.offset - pagination.limit);
            loadAuditEvents();
        });
        const next = ui.element("button", "platform-button", "Next");
        next.type = "button";
        next.disabled = !pagination.has_more;
        next.addEventListener("click", function () {
            state.offset = pagination.offset + pagination.limit;
            loadAuditEvents();
        });
        actions.append(previous, next);
        nav.append(actions);
        return nav;
    }

    function renderResults(data) {
        const events = data && Array.isArray(data.audit_events) ? data.audit_events : [];
        const pagination = data && data.pagination ? data.pagination : {
            limit: state.limit,
            offset: state.offset,
            returned: 0,
            total: 0,
            has_more: false
        };
        if (events.length === 0) {
            state.results.replaceChildren(ui.element("p", "platform-empty", "No audit events found."));
            state.results.setAttribute("aria-busy", "false");
            return;
        }
        const fragment = document.createDocumentFragment();
        fragment.append(renderTable(events), renderCards(events), renderPagination(pagination));
        state.results.replaceChildren(fragment);
        state.results.setAttribute("aria-busy", "false");
    }

    function collectFilters() {
        const actorValue = state.controls.actorUserId.value.trim();
        state.limit = Number.parseInt(state.controls.limit.value, 10);
        state.filters = {
            action: state.controls.action.value,
            resourceType: state.controls.resourceType.value,
            actorUserId: actorValue,
            resourceId: state.controls.resourceId.value.trim(),
            createdAfter: state.controls.createdAfter.value.trim(),
            createdBefore: state.controls.createdBefore.value.trim()
        };
    }

    async function loadAuditEvents() {
        if (state.error) state.error.textContent = "";
        state.results.replaceChildren(ui.element("div", "platform-loading", "Loading audit events..."));
        state.results.setAttribute("aria-busy", "true");
        try {
            const data = await ui.runRequest("audit-events", function (signal) {
                return PlatformAdminApi.listAuditEvents({
                    limit: state.limit,
                    offset: state.offset,
                    action: state.filters.action || undefined,
                    resourceType: state.filters.resourceType || undefined,
                    actorUserId: state.filters.actorUserId || undefined,
                    resourceId: state.filters.resourceId || undefined,
                    createdAfter: state.filters.createdAfter || undefined,
                    createdBefore: state.filters.createdBefore || undefined,
                    signal: signal
                });
            });
            renderResults(data);
        } catch (error) {
            if (error && error.category === "validation") {
                state.results.replaceChildren();
                state.results.setAttribute("aria-busy", "false");
                if (state.error) state.error.textContent = "Audit log filters could not be validated.";
            } else if (!ui.handleError(error) && (!error || error.category !== "aborted")) {
                state.results.replaceChildren(ui.element("p", "platform-empty", "Audit events are temporarily unavailable."));
                state.results.setAttribute("aria-busy", "false");
            }
        }
    }

    function renderFilters() {
        const form = ui.element("form", "platform-audit-filters");
        form.setAttribute("aria-label", "Audit log filters");

        state.controls.action = ui.element("select", "platform-select");
        state.controls.action.id = "platform-audit-action";
        state.controls.action.append(option("", "All actions"));
        ACTIONS.forEach(function (value) { state.controls.action.append(option(value, value)); });

        state.controls.resourceType = ui.element("select", "platform-select");
        state.controls.resourceType.id = "platform-audit-resource-type";
        state.controls.resourceType.append(option("", "All resource types"));
        RESOURCE_TYPES.forEach(function (value) { state.controls.resourceType.append(option(value, value)); });

        state.controls.actorUserId = ui.element("input", "platform-input");
        state.controls.actorUserId.id = "platform-audit-actor-user-id";
        state.controls.actorUserId.type = "number";
        state.controls.actorUserId.min = "1";
        state.controls.actorUserId.inputMode = "numeric";

        state.controls.resourceId = ui.element("input", "platform-input");
        state.controls.resourceId.id = "platform-audit-resource-id";
        state.controls.resourceId.type = "text";
        state.controls.resourceId.maxLength = 255;

        state.controls.createdAfter = ui.element("input", "platform-input");
        state.controls.createdAfter.id = "platform-audit-created-after";
        state.controls.createdAfter.type = "text";
        state.controls.createdAfter.placeholder = "2026-07-31T00:00:00+00:00";

        state.controls.createdBefore = ui.element("input", "platform-input");
        state.controls.createdBefore.id = "platform-audit-created-before";
        state.controls.createdBefore.type = "text";
        state.controls.createdBefore.placeholder = "2026-08-01T00:00:00+00:00";

        state.controls.limit = ui.element("select", "platform-select");
        state.controls.limit.id = "platform-audit-limit";
        [25, 50, 100].forEach(function (value) { state.controls.limit.append(option(String(value), String(value))); });

        form.append(
            field("Action", state.controls.action),
            field("Resource type", state.controls.resourceType),
            field("Actor user ID", state.controls.actorUserId),
            field("Resource ID", state.controls.resourceId),
            field("Created after", state.controls.createdAfter),
            field("Created before", state.controls.createdBefore),
            field("Page size", state.controls.limit)
        );
        const actions = ui.element("div", "platform-support-actions");
        const apply = ui.element("button", "platform-button platform-button-primary", "Apply filters");
        apply.type = "submit";
        const clear = ui.element("button", "platform-button", "Clear filters");
        clear.type = "button";
        clear.addEventListener("click", function () {
            Object.keys(state.controls).forEach(function (key) {
                if (key !== "limit") state.controls[key].value = "";
            });
            state.controls.limit.value = "25";
            state.offset = 0;
            collectFilters();
            loadAuditEvents();
        });
        actions.append(apply, clear);
        form.append(actions);
        form.addEventListener("submit", function (event) {
            event.preventDefault();
            state.offset = 0;
            collectFilters();
            loadAuditEvents();
        });
        return form;
    }

    function initializeAuditLogViewer() {
        const mount = document.getElementById("platform-page-content");
        if (!mount) return;
        mount.replaceChildren();
        const header = ui.element("header", "platform-page-header");
        header.append(
            ui.element("p", "platform-eyebrow", "Read-only activity history"),
            ui.element("h1", "", "Audit Logs"),
            ui.element(
                "p",
                "platform-page-description",
                "Read-only platform-admin activity history. This viewer shows safe audit event summaries only and does not expose raw metadata or tenant records."
            )
        );
        const filterPanel = panel("Filters", "Use exact allowlisted filters. Metadata search, exports, editing, and deletion are not available.");
        state.error = ui.element("p", "platform-inline-error");
        state.error.setAttribute("aria-live", "polite");
        filterPanel.append(renderFilters(), state.error);
        const resultsPanel = panel("Audit events", "Newest events are shown first using created_at descending with ID as the tie-breaker.");
        state.results = ui.element("div", "platform-audit-results");
        state.results.setAttribute("aria-live", "polite");
        resultsPanel.append(state.results);
        mount.append(header, filterPanel, resultsPanel);
        collectFilters();
        loadAuditEvents();
    }

    document.addEventListener("DOMContentLoaded", function () {
        PlatformAdminShell.start({ onAuthorized: initializeAuditLogViewer });
    });
}());
