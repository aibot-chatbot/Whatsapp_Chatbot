(function () {
    "use strict";

    const ui = PlatformAdminShell;
    const SUBSCRIPTION_STATUSES = ["trialing", "active", "past_due", "expired", "cancelled"];
    const ORDER_STATUSES = ["pending", "created", "paid", "credited", "failed", "expired", "cancelled"];
    const TOPUP_STATUSES = ["pending", "claimed", "paid", "credited", "failed", "expired", "cancelled"];
    const ACTIVATION_STATUSES = ["not_started", "claimed", "activated", "credit_pending", "completed", "conflict", "failed"];
    const ACTIVATION_TYPES = ["initial_purchase", "renewal", "upgrade"];
    const TRANSACTION_TYPES = ["included_credit_grant", "trial_credit_grant", "usage_debit", "topup_purchase", "refund", "manual_adjustment", "expiry", "reversal"];
    const AI_STATUSES = ["completed", "failed"];

    const state = {
        limit: 25,
        offset: 0,
        subscriptionStatus: "",
        plan: "",
        attention: ""
    };

    function safeValue(value) {
        return value === null || value === undefined || value === "" ? "Not available" : String(value);
    }

    function metric(label, value) {
        const card = ui.element("article", "platform-metric");
        card.append(
            ui.element("span", "platform-metric-label", label),
            ui.element("strong", "platform-metric-value", ui.formatInteger(value || 0))
        );
        return card;
    }

    function moneyMetric(label, value) {
        const card = ui.element("article", "platform-metric");
        card.append(
            ui.element("span", "platform-metric-label", label),
            ui.element("strong", "platform-metric-value", ui.formatMicroMyr(value || 0))
        );
        return card;
    }

    function formatSen(value) {
        if (!Number.isFinite(value)) return "Not available";
        return "MYR " + (value / 100).toFixed(2);
    }

    function panel(title, note) {
        const node = ui.element("section", "platform-panel");
        node.append(ui.element("h2", "", title));
        if (note) node.append(ui.element("p", "platform-note", note));
        return node;
    }

    function metricsGrid(items, label) {
        const grid = ui.element("section", "platform-grid");
        grid.setAttribute("aria-label", label);
        items.forEach(function (item) { grid.append(metric(item.label, item.value)); });
        return grid;
    }

    function table(headers, rows, captionText) {
        const wrap = ui.element("div", "platform-table-wrap");
        const node = ui.element("table", "platform-table");
        node.append(ui.element("caption", "platform-skip-link", captionText));
        const head = ui.element("thead");
        const headerRow = ui.element("tr");
        headers.forEach(function (label) {
            const th = ui.element("th", "", label);
            th.scope = "col";
            headerRow.append(th);
        });
        head.append(headerRow);
        const body = ui.element("tbody");
        rows.forEach(function (cells) {
            const row = ui.element("tr");
            cells.forEach(function (cell) {
                const td = ui.element("td");
                if (cell && cell.nodeType) td.append(cell);
                else td.textContent = safeValue(cell);
                row.append(td);
            });
            body.append(row);
        });
        node.append(head, body);
        wrap.append(node);
        return wrap;
    }

    function statusRows(source, order) {
        const values = source || {};
        return order.map(function (status) {
            return [ui.statusBadge(status), ui.formatInteger(values[status] || 0)];
        });
    }

    function renderOverview(overview) {
        const root = ui.element("div", "platform-stack");
        const header = ui.element("header", "platform-page-header");
        header.append(
            ui.element("p", "platform-eyebrow", "Read-only oversight"),
            ui.element("h1", "", "Platform Billing & Subscriptions"),
            ui.element("p", "platform-page-intro", "Cross-tenant billing, subscription, AI-credit, and notification aggregates. Financial mutations, reconciliation, refunds, manual credit changes, and plan overrides are not available here.")
        );
        root.append(header);

        const subscriptions = overview.subscriptions || {};
        const subPanel = panel("Subscription status", "Current latest subscription rows only.");
        subPanel.append(table(["Status", "Companies"], statusRows(subscriptions.by_status, SUBSCRIPTION_STATUSES), "Subscription status counts"));
        subPanel.append(table(
            ["Plan", "Companies"],
            Object.keys(subscriptions.by_plan || {}).sort().map(function (code) {
                return [code, ui.formatInteger(subscriptions.by_plan[code] || 0)];
            }),
            "Plan distribution"
        ));
        subPanel.append(table(
            ["Plan", "Interval", "Currency", "Price", "Included AI credit"],
            (subscriptions.active_plan_catalogue || []).map(function (plan) {
                return [
                    safeValue(plan.code) + " - " + safeValue(plan.name),
                    plan.billing_interval,
                    plan.currency,
                    formatSen(plan.price_sen),
                    ui.formatMicroMyr(plan.included_ai_credit_micro_myr)
                ];
            }),
            "Active plan catalogue"
        ));
        root.append(subPanel);

        const orders = overview.subscription_orders || {};
        const orderPanel = panel("Subscription order attention", "Subscription orders are separate from AI-credit top-up orders. Activation status unset is preserved separately and is not treated as failed.");
        orderPanel.append(metricsGrid([
            { label: "Pending orders", value: orders.pending_count },
            { label: "Failed orders", value: orders.failed_count },
            { label: "Reconciliation required", value: orders.reconciliation_required_count },
            { label: "Activation status unset", value: orders.activation_status_unset_count }
        ], "Subscription order attention"));
        orderPanel.append(table(["Order status", "Orders"], statusRows(orders.orders_by_status, ORDER_STATUSES), "Subscription order status counts"));
        orderPanel.append(table(["Activation status", "Orders"], statusRows(orders.activation_statuses, ACTIVATION_STATUSES), "Subscription activation status counts"));
        orderPanel.append(table(["Activation type", "Orders"], statusRows(orders.activation_types, ACTIVATION_TYPES), "Subscription activation type counts"));
        root.append(orderPanel);

        const topups = overview.topup_orders || {};
        const topupPanel = panel("AI-credit top-up attention", "Top-up orders are monitored separately from subscription orders.");
        topupPanel.append(metricsGrid([
            { label: "Pending top-ups", value: topups.pending_count },
            { label: "Failed top-ups", value: topups.failed_count },
            { label: "Credited top-ups", value: topups.credited_count }
        ], "Top-up order attention"));
        topupPanel.append(table(["Top-up status", "Orders"], statusRows(topups.orders_by_status, TOPUP_STATUSES), "Top-up order status counts"));
        root.append(topupPanel);

        const credit = overview.ai_credit || {};
        const creditPanel = panel("AI Credit Overview", "Safe aggregate balances and approved ledger type counts only.");
        const creditGrid = ui.element("section", "platform-grid");
        creditGrid.setAttribute("aria-label", "AI credit aggregate metrics");
        creditGrid.append(
            metric("Balance rows", credit.balance_row_count),
            metric("Depleted companies", credit.depleted_company_count),
            moneyMetric("Included balance", credit.total_included_balance_micro_myr),
            moneyMetric("Top-up balance", credit.total_topup_balance_micro_myr)
        );
        creditPanel.append(creditGrid);
        creditPanel.append(table(["Transaction type", "Transactions"], statusRows(credit.transactions_by_type, TRANSACTION_TYPES), "AI-credit transaction type counts"));
        root.append(creditPanel);

        const usage = overview.ai_usage || {};
        const usagePanel = panel("AI Usage", "Bounded request and token counts. Prompts, responses, provider payloads, and provider cost are not displayed.");
        usagePanel.append(metricsGrid([
            { label: "Recent requests", value: usage.recent_request_count },
            { label: "Recent tokens", value: usage.recent_total_tokens }
        ], "AI usage metrics"));
        usagePanel.append(table(["Request status", "Requests"], statusRows(usage.requests_by_status, AI_STATUSES), "AI request status counts"));
        root.append(usagePanel);

        const notifications = overview.billing_notifications || {};
        const noticeRows = (notifications.by_type_severity_read_state || []).map(function (item) {
            return [item.notification_type, ui.statusBadge(item.severity), item.is_read ? "Read" : "Unread", ui.formatInteger(item.count)];
        });
        const noticePanel = panel("Billing Notifications", "Counts by notification type, severity, and read state. Titles and message bodies are not shown.");
        noticePanel.append(noticeRows.length ? table(["Type", "Severity", "State", "Count"], noticeRows, "Billing notification counts") : ui.element("p", "platform-empty", "No billing notification rows."));
        root.append(noticePanel);

        const lifecycle = overview.subscription_lifecycle || {};
        const lifecyclePanel = panel("Subscription lifecycle", "Pending plan changes and scheduled cancellations only.");
        lifecyclePanel.append(metricsGrid([
            { label: "Pending plan changes", value: lifecycle.pending_plan_change_count },
            { label: "Scheduled cancellations", value: lifecycle.scheduled_cancellation_count },
            { label: "Both pending and cancellation", value: lifecycle.pending_plan_and_cancellation_count }
        ], "Subscription lifecycle metrics"));
        root.append(lifecyclePanel);

        root.append(renderDirectorySection());
        return root;
    }

    function companyLink(row) {
        const link = ui.element("a", "", safeValue(row.company_name || ("Company " + row.company_id)));
        link.href = "platform-admin-company.html?company_id=" + encodeURIComponent(String(row.company_id));
        return link;
    }

    function renderDirectoryRows(rows) {
        return (rows || []).map(function (row) {
            const plan = row.current_plan || {};
            const subscriptionAttention = row.subscription_order_attention || {};
            const topupAttention = row.topup_order_attention || {};
            return [
                companyLink(row),
                row.company_id,
                ui.statusBadge(row.subscription_status),
                safeValue(plan.code),
                row.pending_plan_change ? "Yes" : "No",
                row.cancellation_scheduled ? "Yes" : "No",
                ui.formatMicroMyr(row.ai_credit_total_balance_micro_myr),
                ui.formatInteger((subscriptionAttention.pending_count || 0) + (subscriptionAttention.failed_count || 0) + (subscriptionAttention.reconciliation_required_count || 0)),
                ui.formatInteger((topupAttention.pending_count || 0) + (topupAttention.failed_count || 0)),
                ui.formatDate(row.current_period_end)
            ];
        });
    }

    function renderDirectorySection() {
        const section = panel("Tenant Billing Directory", "Server-paginated read-only billing summary. Use company investigation for detailed histories.");
        const controls = ui.element("form", "platform-toolbar");
        const status = ui.element("select");
        [["", "All statuses"]].concat(SUBSCRIPTION_STATUSES.map(function (item) { return [item, item]; })).forEach(function (item) {
            const option = ui.element("option", "", item[1]);
            option.value = item[0];
            status.append(option);
        });
        status.value = state.subscriptionStatus;
        const plan = ui.element("input");
        plan.type = "text";
        plan.placeholder = "Plan code";
        plan.maxLength = 50;
        plan.value = state.plan;
        const attention = ui.element("select");
        [["", "All"], ["true", "Attention only"], ["false", "No attention"]].forEach(function (item) {
            const option = ui.element("option", "", item[1]);
            option.value = item[0];
            attention.append(option);
        });
        attention.value = state.attention;
        const apply = ui.element("button", "platform-button platform-button-primary", "Apply");
        apply.type = "submit";
        controls.append(status, plan, attention, apply);
        controls.addEventListener("submit", function (event) {
            event.preventDefault();
            state.subscriptionStatus = status.value;
            state.plan = plan.value.trim();
            state.attention = attention.value;
            state.offset = 0;
            loadDirectory(section);
        });
        section.append(controls);
        const body = ui.element("div");
        body.dataset.billingDirectoryBody = "true";
        section.append(body);
        loadDirectory(section);
        return section;
    }

    async function loadDirectory(section) {
        const body = section.querySelector("[data-billing-directory-body]");
        if (!body) return;
        body.replaceChildren(ui.element("div", "platform-loading", "Loading tenant billing directory..."));
        try {
            const data = await ui.runRequest("billing-companies", function (signal) {
                return PlatformAdminApi.listBillingCompanies({
                    signal: signal,
                    limit: state.limit,
                    offset: state.offset,
                    subscriptionStatus: state.subscriptionStatus || undefined,
                    plan: state.plan || undefined,
                    attention: state.attention === "" ? undefined : state.attention === "true"
                });
            });
            const rows = data.companies || [];
            const pagination = data.pagination || {};
            body.replaceChildren();
            if (!rows.length) {
                body.append(ui.element("p", "platform-empty", "No tenant billing rows match the current filters."));
            } else {
                body.append(table(
                    ["Company", "ID", "Subscription", "Plan", "Pending plan", "Cancellation", "AI-credit balance", "Sub order attention", "Top-up attention", "Period end"],
                    renderDirectoryRows(rows),
                    "Tenant billing directory"
                ));
            }
            const pager = ui.element("nav", "platform-pagination");
            pager.setAttribute("aria-label", "Tenant billing directory pagination");
            const previous = ui.element("button", "platform-button", "Previous");
            previous.type = "button";
            previous.disabled = state.offset <= 0;
            previous.addEventListener("click", function () {
                state.offset = Math.max(0, state.offset - state.limit);
                loadDirectory(section);
            });
            const next = ui.element("button", "platform-button", "Next");
            next.type = "button";
            next.disabled = !pagination.has_more;
            next.addEventListener("click", function () {
                state.offset += state.limit;
                loadDirectory(section);
            });
            pager.append(previous, ui.element("span", "platform-muted", "Showing " + ui.formatInteger(pagination.returned || 0) + " of " + ui.formatInteger(pagination.total || 0)), next);
            body.append(pager);
        } catch (error) {
            if (ui.handleError(error)) return;
            body.replaceChildren(ui.element("p", "platform-empty", "Tenant billing directory is temporarily unavailable."));
        }
    }

    async function initializeBillingPage() {
        const root = document.getElementById("platform-page-content");
        if (!root) return;
        root.replaceChildren(ui.element("div", "platform-loading", "Loading platform billing oversight..."));
        try {
            const overview = await ui.runRequest("billing-overview", function (signal) {
                return PlatformAdminApi.getBillingOverview({ signal: signal });
            });
            root.replaceChildren(renderOverview(overview));
        } catch (error) {
            if (ui.handleError(error)) return;
            root.replaceChildren(ui.element("p", "platform-empty", "Platform billing oversight is temporarily unavailable."));
        }
    }

    PlatformAdminShell.start({ onAuthorized: initializeBillingPage });
}());
