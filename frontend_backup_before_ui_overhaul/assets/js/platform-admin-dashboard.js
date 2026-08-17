(function () {
    "use strict";

    const ui = PlatformAdminShell;
    const STATUS_ORDER = ["trialing", "active", "past_due", "expired", "cancelled"];
    const SUPPORT_STATUS_ORDER = ["open", "in_progress", "waiting_for_tenant", "resolved", "closed"];
    const PRIORITY_ORDER = ["urgent", "high", "normal", "low"];
    const MESSAGE_STATUS_ORDER = ["received", "sent", "pending", "sending", "failed", "retrying", "permanent_failed"];
    const ORDER_STATUS_ORDER = ["pending", "created", "paid", "credited", "failed", "expired", "cancelled"];
    const AI_STATUS_ORDER = ["completed", "failed"];

    function safeValue(value) {
        return value === null || value === undefined || value === "" ? "Not available" : String(value);
    }

    function metric(label, value) {
        const card = ui.element("article", "platform-metric");
        card.append(
            ui.element("span", "platform-metric-label", label),
            ui.element("strong", "platform-metric-value", ui.formatInteger(value))
        );
        return card;
    }

    function companyLink(companyId, text) {
        if (!Number.isSafeInteger(companyId) || companyId <= 0) {
            return ui.element("span", "", safeValue(text));
        }
        const params = new URLSearchParams();
        params.set("company_id", String(companyId));
        const link = ui.element("a", "", safeValue(text));
        link.href = "platform-admin-company.html?" + params.toString();
        return link;
    }

    function renderTable(headers, rows, captionText) {
        const wrap = ui.element("div", "platform-table-wrap");
        const table = ui.element("table", "platform-table");
        const caption = ui.element("caption", "platform-skip-link", captionText);
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
        table.append(caption, head, body);
        wrap.append(table);
        return wrap;
    }

    function renderStatusPanel(byStatus) {
        const panel = ui.element("section", "platform-panel");
        panel.append(ui.element("h2", "", "Subscription status"));
        const rows = STATUS_ORDER.map(function (status) {
            return [ui.statusBadge(status), ui.formatInteger(byStatus[status] || 0)];
        });
        panel.append(renderTable(["Status", "Companies"], rows, "Subscription status counts"));
        return panel;
    }

    function renderBreakdown(title, values, order, captionText) {
        const panel = ui.element("section", "platform-panel");
        panel.append(ui.element("h2", "", title));
        const rows = order.map(function (key) {
            return [ui.statusBadge(key), ui.formatInteger((values || {})[key] || 0)];
        });
        panel.append(renderTable(["Status", "Count"], rows, captionText));
        return panel;
    }

    function renderSectionSummary(title, note, metrics) {
        const panel = ui.element("section", "platform-panel");
        panel.append(ui.element("h2", "", title));
        if (note) panel.append(ui.element("p", "platform-note", note));
        const grid = ui.element("section", "platform-grid");
        grid.setAttribute("aria-label", title + " summary");
        metrics.forEach(function (item) {
            grid.append(metric(item.label, item.value || 0));
        });
        panel.append(grid);
        return panel;
    }

    function renderSupportPanel(support) {
        const data = support || {};
        const panel = renderSectionSummary(
            "Support operations",
            "Read-only support backlog and tenant request counts.",
            [
                { label: "Open cases", value: data.open_case_count },
                { label: "Unresolved tenant requests", value: data.unresolved_tenant_request_count },
                { label: "Urgent cases", value: (data.cases_by_priority || {}).urgent },
                { label: "High priority cases", value: (data.cases_by_priority || {}).high }
            ]
        );
        const link = ui.element("a", "platform-link-button", "Open Support Workspace");
        link.href = "platform-admin-support.html";
        panel.append(link);
        panel.append(renderTable(
            ["Case status", "Cases"],
            SUPPORT_STATUS_ORDER.map(function (status) {
                return [ui.statusBadge(status), ui.formatInteger((data.cases_by_status || {})[status] || 0)];
            }),
            "Support case status counts"
        ));
        panel.append(renderTable(
            ["Tenant request status", "Requests"],
            ["new", "reviewed", "converted", "closed"].map(function (status) {
                return [ui.statusBadge(status), ui.formatInteger((data.tenant_requests_by_status || {})[status] || 0)];
            }),
            "Tenant support request status counts"
        ));
        return panel;
    }

    function renderMessagingPanel(messaging) {
        const data = messaging || {};
        const panel = renderSectionSummary(
            "Messaging & integrations",
            "Aggregated delivery and configured channel health. No message text, phone numbers, or provider errors are displayed.",
            [
                { label: "Retry backlog", value: data.retry_backlog_count },
                { label: "Failed messages", value: (data.messages_by_delivery_status || {}).failed },
                { label: "Retrying messages", value: (data.messages_by_delivery_status || {}).retrying },
                { label: "Permanent failures", value: (data.messages_by_delivery_status || {}).permanent_failed }
            ]
        );
        panel.append(renderTable(
            ["Delivery status", "Messages"],
            MESSAGE_STATUS_ORDER.map(function (status) {
                return [ui.statusBadge(status), ui.formatInteger((data.messages_by_delivery_status || {})[status] || 0)];
            }),
            "Message delivery status counts"
        ));
        const channels = data.channel_health || {};
        panel.append(renderTable(
            ["Provider", "Configured", "Active", "Inactive", "Connected", "Disconnected", "Pending", "Error"],
            ["telegram", "wasender", "meta_whatsapp"].map(function (provider) {
                const row = channels[provider] || {};
                const statuses = row.by_connection_status || {};
                return [
                    provider,
                    ui.formatInteger(row.total || 0),
                    ui.formatInteger(row.active || 0),
                    ui.formatInteger(row.inactive || 0),
                    ui.formatInteger(statuses.connected || 0),
                    ui.formatInteger(statuses.disconnected || 0),
                    ui.formatInteger(statuses.pending || 0),
                    ui.formatInteger(statuses.error || 0)
                ];
            }),
            "Integration channel health"
        ));
        panel.append(renderTable(
            ["Broadcast campaign status", "Campaigns"],
            ["draft", "sending", "completed", "failed"].map(function (status) {
                return [ui.statusBadge(status), ui.formatInteger((data.broadcast_campaigns_by_status || {})[status] || 0)];
            }),
            "Broadcast campaign status counts"
        ));
        return panel;
    }

    function renderBillingAttentionPanel(billing) {
        const data = billing || {};
        const panel = renderSectionSummary(
            "Billing attention",
            "Operational billing counts only. Activation status NULL is not treated as a failure.",
            [
                { label: "Pending orders", value: data.pending_order_count },
                { label: "Failed orders", value: data.failed_order_count },
                { label: "Reconciliation required", value: data.reconciliation_required_count }
            ]
        );
        panel.append(renderTable(
            ["Order status", "Orders"],
            ORDER_STATUS_ORDER.map(function (status) {
                return [ui.statusBadge(status), ui.formatInteger((data.orders_by_status || {})[status] || 0)];
            }),
            "Billing order status counts"
        ));
        return panel;
    }

    function renderAiUsagePanel(aiUsage) {
        const data = aiUsage || {};
        const windowData = data.window || {};
        const panel = renderSectionSummary(
            "AI usage & credits",
            "Read-only request and credit activity. No prompts, responses, provider payloads, or low-balance threshold are shown.",
            [
                { label: "Recent AI requests", value: data.recent_request_count },
                { label: "Recent tokens", value: data.recent_total_tokens },
                { label: "Completed requests", value: (data.requests_by_status || {}).completed },
                { label: "Depleted balances", value: data.depleted_balance_company_count }
            ]
        );
        panel.append(ui.element("p", "platform-note", "Window starts " + ui.formatDate(windowData.since) + "."));
        panel.append(renderTable(
            ["AI request status", "Requests"],
            AI_STATUS_ORDER.map(function (status) {
                return [ui.statusBadge(status), ui.formatInteger((data.requests_by_status || {})[status] || 0)];
            }),
            "AI request status counts"
        ));
        return panel;
    }

    function renderPlatformActivityPanel(activity) {
        const data = activity || {};
        const panel = renderSectionSummary(
            "Platform-admin activity",
            "Recent safe audit aggregates only. Raw audit metadata is available nowhere on this dashboard.",
            [
                { label: "Recent audit events", value: data.recent_event_count }
            ]
        );
        const link = ui.element("a", "platform-link-button", "Open Audit Logs");
        link.href = "platform-admin-audit-events.html";
        panel.append(link);
        const actions = Object.entries(data.events_by_action || {})
            .filter(function (entry) { return entry[1] > 0; })
            .slice(0, 12);
        if (actions.length === 0) {
            panel.append(ui.element("p", "platform-empty", "No recent platform-admin activity found."));
            return panel;
        }
        panel.append(renderTable(
            ["Action", "Events"],
            actions.map(function (entry) {
                return [entry[0], ui.formatInteger(entry[1])];
            }),
            "Recent platform-admin action counts"
        ));
        return panel;
    }

    function renderPlanPanel(plans) {
        const panel = ui.element("section", "platform-panel");
        panel.append(ui.element("h2", "", "Plan distribution"));
        if (!Array.isArray(plans) || plans.length === 0) {
            panel.append(ui.element("p", "platform-empty", "No active plan subscriptions found."));
            return panel;
        }
        panel.append(renderTable(
            ["Plan", "Companies"],
            plans.map(function (plan) {
                return [plan.name || plan.code, ui.formatInteger(plan.count)];
            }),
            "Subscription plan distribution"
        ));
        return panel;
    }

    function renderAttentionPanel(companies) {
        const panel = ui.element("section", "platform-panel");
        panel.append(ui.element("h2", "", "Companies requiring attention"));
        if (!Array.isArray(companies) || companies.length === 0) {
            panel.append(ui.element("p", "platform-empty", "No past-due or expired companies found."));
            return panel;
        }
        const rows = companies.map(function (company) {
            return [
                companyLink(company.company_id, company.company_name),
                ui.statusBadge(company.subscription_status),
                company.plan_name || company.plan_code,
                ui.formatDate(company.current_period_end || company.status_updated_at)
            ];
        });
        panel.append(renderTable(
            ["Company", "Status", "Plan", "Period end or status update"],
            rows,
            "Companies requiring attention"
        ));
        return panel;
    }

    function alertTypeFromSubscriptionStatus(status) {
        const normalized = typeof status === "string" ? status.trim().toLowerCase() : "";
        if (normalized === "past_due") {
            return {
                type: "subscription_past_due",
                severity: "warning",
                summary: "Subscription is past due"
            };
        }
        if (normalized === "expired") {
            return {
                type: "subscription_expired",
                severity: "critical",
                summary: "Subscription is expired"
            };
        }
        return null;
    }

    function alertLink(alert) {
        if (Number.isSafeInteger(alert.company_id) && alert.company_id > 0) {
            return companyLink(alert.company_id, "Investigate");
        }
        if (typeof alert.investigation_url === "string" && alert.investigation_url.trim()) {
            const link = ui.element("a", "", "Investigate");
            link.href = alert.investigation_url;
            return link;
        }
        return ui.element("span", "", "Not available");
    }

    function fallbackOperationalAlerts(attentionCompanies) {
        const alerts = [];
        if (!Array.isArray(attentionCompanies)) return alerts;
        attentionCompanies.slice(0, 10).forEach(function (company) {
            if (!Number.isSafeInteger(company.company_id) || company.company_id <= 0) return;
            const alertType = alertTypeFromSubscriptionStatus(company.subscription_status);
            if (!alertType) return;
            alerts.push({
                type: alertType.type,
                severity: alertType.severity,
                company_id: company.company_id,
                company_name: company.company_name,
                company_status: company.company_status,
                summary: alertType.summary,
                details: {
                    subscription_status: company.subscription_status,
                    plan_code: company.plan_code,
                    plan_name: company.plan_name,
                    current_period_end: company.current_period_end,
                    status_updated_at: company.status_updated_at
                },
                investigation_url: "platform-admin-company.html?company_id=" + String(company.company_id)
            });
        });
        return alerts;
    }

    function summarizeAlerts(alerts, providedSummary) {
        const summary = { total: alerts.length, critical: 0, warning: 0, info: 0 };
        alerts.forEach(function (alert) {
            if (alert.severity === "critical") summary.critical += 1;
            else if (alert.severity === "warning") summary.warning += 1;
            else if (alert.severity === "info") summary.info += 1;
        });
        if (providedSummary && typeof providedSummary === "object") {
            summary.total = Number.isSafeInteger(providedSummary.total) ? providedSummary.total : summary.total;
            summary.critical = Number.isSafeInteger(providedSummary.critical) ? providedSummary.critical : summary.critical;
            summary.warning = Number.isSafeInteger(providedSummary.warning) ? providedSummary.warning : summary.warning;
            summary.info = Number.isSafeInteger(providedSummary.info) ? providedSummary.info : summary.info;
        }
        return summary;
    }

    function renderOperationalAlertsPanel(overview) {
        const panel = ui.element("section", "platform-panel");
        panel.append(
            ui.element("h2", "", "Operational alerts"),
            ui.element("p", "platform-note", "Read-only platform operational alerts derived from safe aggregate monitoring data. Investigate before taking any external operational step.")
        );
        const operationalAlerts = overview && overview.operational_alerts ? overview.operational_alerts : {};
        const alerts = Array.isArray(operationalAlerts.alerts)
            ? operationalAlerts.alerts
            : fallbackOperationalAlerts(overview ? overview.attention_companies : []);
        const summary = summarizeAlerts(alerts, operationalAlerts.summary);
        const summaryGrid = ui.element("section", "platform-grid");
        summaryGrid.setAttribute("aria-label", "Operational alert summary");
        summaryGrid.append(
            metric("Total alerts", summary.total),
            metric("Critical alerts", summary.critical),
            metric("Warning alerts", summary.warning),
            metric("Info alerts", summary.info)
        );
        panel.append(summaryGrid);
        if (alerts.length === 0) {
            panel.append(ui.element("p", "platform-empty", "No operational alerts found."));
            return panel;
        }
        const companyAlerts = alerts.filter(function (alert) {
            return Number.isSafeInteger(alert.company_id) && alert.company_id > 0;
        });
        const aggregateAlerts = alerts.filter(function (alert) {
            return !Number.isSafeInteger(alert.company_id) || alert.company_id <= 0;
        });
        if (companyAlerts.length > 0) {
            const rows = companyAlerts.map(function (alert) {
                const details = alert && alert.details ? alert.details : {};
                return [
                    ui.statusBadge(alert.severity),
                    alert.summary || alert.type,
                    companyLink(alert.company_id, alert.company_name),
                    ui.statusBadge(alert.company_status),
                    ui.statusBadge(details.subscription_status || "n/a"),
                    details.plan_name || details.plan_code,
                    ui.formatDate(details.current_period_end || null),
                    ui.formatDate(details.status_updated_at || null),
                    alertLink(alert)
                ];
            });
            panel.append(renderTable(
                [
                    "Severity",
                    "Summary",
                    "Company",
                    "Company status",
                    "Subscription status",
                    "Plan",
                    "Current period end",
                    "Status updated",
                    "Investigate"
                ],
                rows,
                "Company-specific operational alerts"
            ));
        }
        if (aggregateAlerts.length > 0) {
            const rows = aggregateAlerts.map(function (alert) {
                const details = alert && alert.details ? alert.details : {};
                return [
                    ui.statusBadge(alert.severity),
                    alert.summary || alert.type,
                    ui.formatInteger(details.count || 0),
                    alertLink(alert)
                ];
            });
            panel.append(renderTable(
                ["Severity", "Summary", "Count", "Investigate"],
                rows,
                "Platform-wide operational alerts"
            ));
        }
        return panel;
    }

    function renderDashboardOverview(overview) {
        const root = document.getElementById("platform-page-content");
        root.replaceChildren();

        const companies = overview && overview.companies ? overview.companies : {};
        const subscriptions = overview && overview.subscriptions ? overview.subscriptions : {};
        const byStatus = subscriptions.by_status || {};

        const header = ui.element("header", "platform-page-header");
        const titleGroup = ui.element("div");
        titleGroup.append(
            ui.element("h1", "", "Platform operations"),
            ui.element("p", "", "Read-only overview of tenant and subscription health.")
        );
        const directoryLink = ui.element("a", "platform-link-button", "Open company directory");
        directoryLink.href = "platform-admin-companies.html";
        header.append(titleGroup, directoryLink);

        const metrics = ui.element("section", "platform-grid platform-grid-large");
        metrics.setAttribute("aria-label", "Platform operations summary");
        metrics.append(
            metric("Total companies", companies.total || 0),
            metric("Active companies", companies.active || 0),
            metric("Inactive companies", companies.inactive || 0),
            metric("Active users", companies.active_users || 0),
            metric("Trialing", byStatus.trialing || 0),
            metric("Active subscriptions", byStatus.active || 0),
            metric("Past due", byStatus.past_due || 0),
            metric("Expired", byStatus.expired || 0)
        );

        const refreshed = ui.element(
            "p",
            "platform-note",
            "Overview generated " + ui.formatDate(overview.generated_at) + "."
        );
        refreshed.setAttribute("aria-live", "polite");

        root.append(
            header,
            metrics,
            refreshed,
            renderStatusPanel(byStatus),
            renderPlanPanel(subscriptions.by_plan || []),
            renderSupportPanel(overview.support || {}),
            renderMessagingPanel(overview.messaging || {}),
            renderBillingAttentionPanel(overview.billing_attention || {}),
            renderAiUsagePanel(overview.ai_usage || {}),
            renderPlatformActivityPanel(overview.platform_admin_activity || {}),
            renderOperationalAlertsPanel(overview),
            renderAttentionPanel(overview.attention_companies || [])
        );
    }

    async function renderDashboard() {
        const root = document.getElementById("platform-page-content");
        root.replaceChildren(ui.element("div", "platform-loading", "Loading platform operations overview..."));
        try {
            const overview = await ui.runRequest("operations-overview", function (signal) {
                return PlatformAdminApi.getOverview({ signal: signal });
            });
            renderDashboardOverview(overview);
        } catch (error) {
            ui.handleError(error);
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        PlatformAdminShell.start({ onAuthorized: renderDashboard });
    });
}());
