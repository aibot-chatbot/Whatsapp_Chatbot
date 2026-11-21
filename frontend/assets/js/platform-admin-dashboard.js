(function () {
    "use strict";

    const ui = PlatformAdminShell;
    const SUPPORT_STATUS_ORDER = ["open", "in_progress", "waiting_for_tenant", "resolved", "closed"];
    const AI_STATUS_ORDER = ["completed", "failed"];
    const PROVIDER_ORDER = ["telegram", "whatsapp_link", "meta_whatsapp"];

    function safeValue(value) {
        return value === null || value === undefined || value === "" ? "Not available" : String(value);
    }

    function count(value) {
        return Number.isSafeInteger(value) && value >= 0 ? value : 0;
    }

    function valueFrom(map, key) {
        return map && Number.isSafeInteger(map[key]) && map[key] >= 0 ? map[key] : 0;
    }

    function humanize(value) {
        return safeValue(value).replaceAll("_", " ");
    }

    function percent(value, total) {
        if (!Number.isFinite(total) || total <= 0) return 0;
        return Math.max(0, Math.min(100, Math.round((value / total) * 100)));
    }

    function companyLink(companyId, text, label) {
        if (!Number.isSafeInteger(companyId) || companyId <= 0) {
            return ui.element("span", "", safeValue(text));
        }
        const params = new URLSearchParams();
        params.set("company_id", String(companyId));
        const link = ui.element("a", "", label || safeValue(text));
        link.href = "platform-admin-company.html?" + params.toString();
        return link;
    }

    function actionLink(href, text) {
        const link = ui.element("a", "platform-link-button", text);
        link.href = href;
        return link;
    }

    function metric(label, value, note, tone) {
        const card = ui.element("article", "platform-metric platform-dashboard-metric");
        if (tone) card.classList.add("platform-metric-" + tone);
        card.append(
            ui.element("span", "platform-metric-label", label),
            ui.element("strong", "platform-metric-value", ui.formatInteger(count(value)))
        );
        if (note) card.append(ui.element("span", "platform-metric-note", note));
        return card;
    }

    function panel(title, note, action) {
        const section = ui.element("section", "platform-panel platform-dashboard-panel");
        const header = ui.element("div", "platform-panel-header");
        const titleGroup = ui.element("div");
        titleGroup.append(ui.element("h2", "", title));
        if (note) titleGroup.append(ui.element("p", "platform-note", note));
        header.append(titleGroup);
        if (action) header.append(action);
        section.append(header);
        return section;
    }

    function renderTable(headers, rows, captionText) {
        const wrap = ui.element("div", "platform-table-wrap");
        const table = ui.element("table", "platform-table");
        table.append(ui.element("caption", "platform-skip-link", captionText));
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
        table.append(head, body);
        wrap.append(table);
        return wrap;
    }

    function chartRowsFromMap(map, order, labels, tones) {
        return order.map(function (key) {
            return {
                key: key,
                label: labels && labels[key] ? labels[key] : humanize(key),
                value: valueFrom(map, key),
                tone: tones && tones[key] ? tones[key] : "neutral"
            };
        });
    }

    function totalRows(rows) {
        return rows.reduce(function (sum, row) {
            return sum + count(row.value);
        }, 0);
    }

    function renderDistribution(title, rows, emptyText) {
        const card = ui.element("article", "platform-chart");
        const total = totalRows(rows);
        const heading = ui.element("div", "platform-chart-heading");
        heading.append(
            ui.element("h3", "", title),
            ui.element("span", "", ui.formatInteger(total) + " total")
        );
        card.append(heading);
        const stack = ui.element("div", "platform-segmented-meter");
        stack.setAttribute("aria-label", title + " distribution");
        if (total === 0) {
            const zero = ui.element("span", "platform-segment platform-segment-empty");
            zero.style.width = "100%";
            zero.textContent = "0";
            stack.append(zero);
        } else {
            rows.forEach(function (row) {
                if (count(row.value) <= 0) return;
                const segment = ui.element("span", "platform-segment platform-segment-" + row.tone);
                segment.style.width = String(percent(row.value, total)) + "%";
                segment.title = row.label + ": " + ui.formatInteger(row.value);
                stack.append(segment);
            });
        }
        card.append(stack);
        const list = ui.element("div", "platform-bar-list");
        rows.forEach(function (row) {
            const value = count(row.value);
            const item = ui.element("div", "platform-bar-row");
            const label = ui.element("span", "platform-bar-label");
            label.append(ui.element("span", "platform-dot platform-dot-" + row.tone), document.createTextNode(row.label));
            const valueNode = ui.element("strong", "", ui.formatInteger(value));
            const bar = ui.element("div", "platform-bar-track");
            const fill = ui.element("span", "platform-bar-fill platform-bar-fill-" + row.tone);
            fill.style.width = String(percent(value, total)) + "%";
            bar.append(fill);
            item.append(label, valueNode, bar);
            list.append(item);
        });
        card.append(list);
        if (total === 0) card.append(ui.element("p", "platform-empty platform-chart-empty", emptyText || "No records found."));
        return card;
    }

    function compactMetricList(items) {
        const list = ui.element("div", "platform-compact-metric-list");
        items.forEach(function (item) {
            const row = ui.element("div", "platform-compact-metric-row");
            if (item.tone) row.classList.add("platform-compact-metric-" + item.tone);
            row.append(
                ui.element("span", "", item.label),
                ui.element("strong", "", ui.formatInteger(count(item.value)))
            );
            list.append(row);
        });
        return list;
    }

    function renderOverviewCards(overview) {
        const companies = overview && overview.companies ? overview.companies : {};
        const support = overview && overview.support ? overview.support : {};
        const section = ui.element("section", "platform-kpi-grid");
        section.setAttribute("aria-label", "Platform operations overview");
        section.append(
            metric("Total companies", companies.total, "All tenant companies"),
            metric("Active companies", companies.active, "Operational tenants", "good"),
            metric("Active users", companies.active_users, "Current active accounts"),
            metric("Open support cases", support.open_case_count, "Open, in progress, or waiting", count(support.open_case_count) > 0 ? "attention" : "good")
        );
        return section;
    }

    function renderNeedsAttention(overview) {
        const section = panel(
            "Needs Attention",
            "Operational alerts and read-only signals that may warrant review. These are aggregate signals, not automated incident declarations."
        );
        const operationalAlerts = overview && overview.operational_alerts ? overview.operational_alerts : {};
        const alerts = Array.isArray(operationalAlerts.alerts)
            ? operationalAlerts.alerts
            : fallbackOperationalAlerts(overview ? overview.attention_companies : []);
        const summary = summarizeAlerts(alerts, operationalAlerts.summary);
        const summaryGrid = ui.element("section", "platform-alert-summary");
        summaryGrid.setAttribute("aria-label", "Operational attention summary");
        summaryGrid.append(
            metric("Total alerts", summary.total),
            metric("Critical alerts", summary.critical, null, summary.critical > 0 ? "danger" : null),
            metric("Warning alerts", summary.warning, null, summary.warning > 0 ? "attention" : null),
            metric("Info alerts", summary.info)
        );
        section.append(summaryGrid);
        if (!alerts.length) {
            section.append(ui.element("p", "platform-empty", "No operational alerts found."));
            return section;
        }
        const list = ui.element("div", "platform-alert-list");
        alerts.slice(0, 10).forEach(function (alert) {
            const details = alert && alert.details ? alert.details : {};
            const item = ui.element("article", "platform-alert-card");
            const title = ui.element("div", "platform-alert-title");
            title.append(
                ui.statusBadge(alert.severity || "info"),
                ui.element("strong", "", alert.summary || humanize(alert.type))
            );
            const meta = ui.element("p", "platform-note");
            if (Number.isSafeInteger(alert.company_id) && alert.company_id > 0) {
                meta.textContent = "Company-specific review";
            } else {
                meta.textContent = "Platform-wide aggregate count: " + ui.formatInteger(details.count || 0);
            }
            item.append(title, meta, alertLink(alert));
            list.append(item);
        });
        section.append(list);
        return section;
    }

    function fallbackOperationalAlerts(attentionCompanies) {
        const alerts = [];
        if (!Array.isArray(attentionCompanies)) return alerts;
        attentionCompanies.slice(0, 10).forEach(function (company) {
            if (!Number.isSafeInteger(company.company_id) || company.company_id <= 0) return;
            const status = typeof company.subscription_status === "string" ? company.subscription_status.trim().toLowerCase() : "";
            if (!["past_due", "expired"].includes(status)) return;
            alerts.push({
                type: status === "expired" ? "subscription_expired" : "subscription_past_due",
                severity: status === "expired" ? "critical" : "warning",
                company_id: company.company_id,
                company_name: company.company_name,
                company_status: company.company_status,
                summary: status === "expired" ? "Subscription is expired" : "Subscription is past due",
                details: {
                    subscription_status: status,
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
            else summary.info += 1;
        });
        if (providedSummary && typeof providedSummary === "object") {
            summary.total = count(providedSummary.total);
            summary.critical = count(providedSummary.critical);
            summary.warning = count(providedSummary.warning);
            summary.info = count(providedSummary.info);
        }
        return summary;
    }

    function alertLink(alert) {
        if (Number.isSafeInteger(alert.company_id) && alert.company_id > 0) {
            return companyLink(alert.company_id, alert.company_name, "View Company");
        }
        if (typeof alert.investigation_url === "string" && alert.investigation_url.trim()) {
            const link = ui.element("a", "", "Investigate");
            link.href = alert.investigation_url;
            return link;
        }
        return ui.element("span", "", "No action");
    }

    function renderSupportPanel(support) {
        const data = support || {};
        const section = panel(
            "Support Operations",
            "Workload distribution from support cases and tenant support requests. No SLA or overdue status is inferred.",
            actionLink("platform-admin-support.html", "Open Support Workspace")
        );
        const grid = ui.element("section", "platform-grid platform-dashboard-small-grid");
        grid.setAttribute("aria-label", "Support operations metrics");
        grid.append(
            metric("Open cases", data.open_case_count),
            metric("Urgent cases", valueFrom(data.cases_by_priority, "urgent"), null, valueFrom(data.cases_by_priority, "urgent") > 0 ? "danger" : null),
            metric("High priority cases", valueFrom(data.cases_by_priority, "high"), null, valueFrom(data.cases_by_priority, "high") > 0 ? "attention" : null),
            metric("Unresolved tenant requests", data.unresolved_tenant_request_count)
        );
        section.append(grid);
        section.append(renderDistribution(
            "Case status",
            chartRowsFromMap(
                data.cases_by_status,
                SUPPORT_STATUS_ORDER,
                {
                    open: "Open",
                    in_progress: "In progress",
                    waiting_for_tenant: "Waiting for tenant",
                    resolved: "Resolved",
                    closed: "Closed"
                },
                { open: "attention", in_progress: "info", waiting_for_tenant: "attention", resolved: "good", closed: "neutral" }
            ),
            "No support cases found."
        ));
        return section;
    }

    function deliveryAttentionCount(messaging) {
        const rows = deliveryHealthRows(messaging);
        return rows.reduce(function (sum, row) {
            return row.tone === "good" ? sum : sum + count(row.value);
        }, 0);
    }

    function channelAttentionCount(channels) {
        return PROVIDER_ORDER.reduce(function (sum, provider) {
            const row = channels && channels[provider] ? channels[provider] : {};
            return sum + count(row.attention_required);
        }, 0);
    }

    function channelConfiguredCount(channels) {
        return PROVIDER_ORDER.reduce(function (sum, provider) {
            const row = channels && channels[provider] ? channels[provider] : {};
            return sum + count(row.total);
        }, 0);
    }

    function renderMessagingPanel(messaging) {
        const data = messaging || {};
        const statuses = data.messages_by_delivery_status || {};
        const section = panel(
            "Messaging Health",
            "Coarse aggregate delivery and configured channel health. No message text, phone numbers, provider payloads, or raw provider errors are shown."
        );
        const channelHealth = data.channel_health || {};
        const grid = ui.element("section", "platform-grid platform-dashboard-small-grid");
        grid.setAttribute("aria-label", "Messaging health metrics");
        grid.append(
            metric("Retry backlog", data.retry_backlog_count, null, count(data.retry_backlog_count) > 0 ? "attention" : "good"),
            metric("Failed messages", valueFrom(statuses, "failed"), null, valueFrom(statuses, "failed") > 0 ? "danger" : null),
            metric("Delivery attention", deliveryAttentionCount(data), null, deliveryAttentionCount(data) > 0 ? "attention" : "good"),
            metric("Channel attention", channelAttentionCount(channelHealth), ui.formatInteger(channelConfiguredCount(channelHealth)) + " configured", channelAttentionCount(channelHealth) > 0 ? "attention" : "good")
        );
        section.append(grid);
        section.append(renderDistribution("Delivery health", deliveryHealthRows(data), "No message delivery rows found."));
        section.append(renderChannelHealth(channelHealth));
        return section;
    }

    function deliveryHealthRows(messaging) {
        const statuses = messaging && messaging.messages_by_delivery_status ? messaging.messages_by_delivery_status : {};
        return [
            {
                key: "successful",
                label: "Successful or received",
                value: valueFrom(statuses, "received") + valueFrom(statuses, "sent"),
                tone: "good"
            },
            {
                key: "pending",
                label: "Pending or retrying",
                value: valueFrom(statuses, "pending") + valueFrom(statuses, "sending") + valueFrom(statuses, "retrying"),
                tone: "attention"
            },
            {
                key: "failed",
                label: "Failed",
                value: valueFrom(statuses, "failed") + valueFrom(statuses, "permanent_failed"),
                tone: "danger"
            }
        ];
    }

    function renderChannelHealth(channels) {
        const wrap = ui.element("div", "platform-channel-grid");
        wrap.append(ui.element("h3", "platform-channel-heading", "Channel Health"));
        PROVIDER_ORDER.forEach(function (provider) {
            const row = channels[provider] || {};
            const statuses = row.by_connection_status || {};
            const card = ui.element("article", "platform-channel-card");
            card.append(
                ui.element("h3", "", provider === "meta_whatsapp" ? "Meta WhatsApp" : provider === "whatsapp_link" ? "WhatsApp (linked device)" : humanize(provider)),
                ui.element("p", "platform-note", count(row.total) === 0 ? "No configured channels" : ui.formatInteger(row.total) + " configured")
            );
            const metrics = ui.element("div", "platform-channel-metrics");
            [
                ["Connected", valueFrom(statuses, "connected"), "good"],
                ["Disconnected", valueFrom(statuses, "disconnected"), "danger"],
                ["Pending", valueFrom(statuses, "pending"), "attention"],
                ["Error", valueFrom(statuses, "error"), "danger"],
                ["Attention", row.attention_required, count(row.attention_required) > 0 ? "attention" : "neutral"]
            ].forEach(function (item) {
                const node = ui.element("span", "platform-channel-pill platform-channel-pill-" + item[2]);
                node.append(ui.element("strong", "", ui.formatInteger(count(item[1]))), document.createTextNode(" " + item[0]));
                metrics.append(node);
            });
            card.append(metrics);
            wrap.append(card);
        });
        return wrap;
    }

    function renderAiUsagePanel(aiUsage) {
        const data = aiUsage || {};
        const windowData = data.window || {};
        const section = panel(
            "AI Usage",
            "Safe aggregate request, token, and credit activity only. Prompts, responses, provider payloads, and provider costs are excluded."
        );
        const windowNote = count(windowData.days) ? "Last " + ui.formatInteger(windowData.days) + " days" : "Reporting window";
        const grid = ui.element("section", "platform-grid platform-dashboard-small-grid");
        grid.setAttribute("aria-label", "AI usage metrics");
        grid.append(
            metric("Recent AI requests", data.recent_request_count, windowNote),
            metric("Recent tokens", data.recent_total_tokens, windowNote),
            metric("Completed requests", valueFrom(data.requests_by_status, "completed")),
            metric("Depleted balances", data.depleted_balance_company_count, null, count(data.depleted_balance_company_count) > 0 ? "attention" : null)
        );
        section.append(grid);
        if (windowData.since) {
            section.append(ui.element("p", "platform-note", windowNote + " window starts " + ui.formatDate(windowData.since) + "."));
        }
        section.append(renderDistribution(
            "Request status",
            chartRowsFromMap(data.requests_by_status, AI_STATUS_ORDER, null, { completed: "good", failed: "danger" }),
            "No AI request rows found."
        ));
        return section;
    }

    function renderBillingPanel(billing) {
        const data = billing || {};
        const section = panel(
            "Billing Health",
            "Operational order attention only. Financial writes, refunds, plan changes, credit changes, and reconciliation mutations are not available here.",
            actionLink("platform-admin-billing.html", "View Billing Details")
        );
        const grid = ui.element("section", "platform-grid platform-dashboard-small-grid");
        grid.setAttribute("aria-label", "Billing health metrics");
        grid.append(
            metric("Pending orders", data.pending_order_count, null, count(data.pending_order_count) > 0 ? "attention" : null),
            metric("Failed orders", data.failed_order_count, null, count(data.failed_order_count) > 0 ? "danger" : null),
            metric("Reconciliation required", data.reconciliation_required_count, null, count(data.reconciliation_required_count) > 0 ? "danger" : null),
            metric("Activation status unset", data.activation_status_unset_count)
        );
        section.append(grid);
        section.append(compactMetricList([
            { label: "Pending orders", value: data.pending_order_count, tone: count(data.pending_order_count) > 0 ? "attention" : "good" },
            { label: "Failed orders", value: data.failed_order_count, tone: count(data.failed_order_count) > 0 ? "danger" : "good" },
            { label: "Reconciliation required", value: data.reconciliation_required_count, tone: count(data.reconciliation_required_count) > 0 ? "danger" : "good" }
        ]));
        return section;
    }

    function renderAttentionCompanies(companies) {
        const section = panel(
            "Companies requiring attention",
            "Compact company-specific subscription attention using safe overview fields only."
        );
        if (!Array.isArray(companies) || companies.length === 0) {
            section.append(ui.element("p", "platform-empty", "No past-due or expired companies found."));
            return section;
        }
        const rows = companies.map(function (company) {
            const supportAttention = "Review workspace";
            const billingAttention = humanize(company.subscription_status);
            return [
                companyLink(company.company_id, company.company_name),
                ui.statusBadge(company.company_status || "unknown"),
                ui.statusBadge(company.subscription_status || "unknown"),
                supportAttention,
                billingAttention,
                companyLink(company.company_id, company.company_name, "View Company")
            ];
        });
        section.append(renderTable(
            ["Company", "Company status", "Subscription", "Support attention", "Billing attention", "Action"],
            rows,
            "Companies requiring attention"
        ));
        section.append(renderAttentionCompanyCards(companies));
        return section;
    }

    function renderAttentionCompanyCards(companies) {
        const wrap = ui.element("div", "platform-attention-company-cards");
        wrap.setAttribute("aria-label", "Companies requiring attention mobile cards");
        companies.forEach(function (company) {
            const card = ui.element("article", "platform-attention-company-card");
            const header = ui.element("div", "platform-attention-company-card-header");
            header.append(
                companyLink(company.company_id, company.company_name),
                companyLink(company.company_id, company.company_name, "View Company")
            );
            const details = ui.element("dl", "platform-attention-company-details");
            [
                ["Company status", ui.statusBadge(company.company_status || "unknown")],
                ["Subscription", ui.statusBadge(company.subscription_status || "unknown")],
                ["Support attention", "Review workspace"],
                ["Billing attention", humanize(company.subscription_status)]
            ].forEach(function (item) {
                details.append(ui.element("dt", "", item[0]));
                const dd = ui.element("dd");
                if (item[1] && item[1].nodeType) dd.append(item[1]);
                else dd.textContent = safeValue(item[1]);
                details.append(dd);
            });
            card.append(header, details);
            wrap.append(card);
        });
        return wrap;
    }

    function renderActivityPanel(activity) {
        const data = activity || {};
        const section = panel(
            "Platform Admin Activity",
            "Aggregate action counts only. Raw audit metadata is not shown on this dashboard.",
            actionLink("platform-admin-audit-events.html", "View Audit Logs")
        );
        const windowData = data.window || {};
        section.append(metric(
            "Recent audit events",
            data.recent_event_count,
            count(windowData.days) ? "Last " + ui.formatInteger(windowData.days) + " days" : null
        ));
        const actions = Object.entries(data.events_by_action || {})
            .filter(function (entry) { return count(entry[1]) > 0; })
            .sort(function (left, right) { return count(right[1]) - count(left[1]); })
            .slice(0, 3);
        if (!actions.length) {
            section.append(ui.element("p", "platform-empty", "No recent platform-admin activity found."));
            return section;
        }
        section.append(compactMetricList(actions.map(function (entry) {
            return { label: entry[0], value: count(entry[1]), tone: "info" };
        })));
        return section;
    }

    function renderDashboardOverview(overview) {
        const root = document.getElementById("platform-page-content");
        root.replaceChildren();

        const header = ui.element("header", "platform-page-header platform-dashboard-header");
        const titleGroup = ui.element("div");
        titleGroup.append(
            ui.element("p", "platform-eyebrow", "Read-only operations console"),
            ui.element("h1", "", "Platform operations"),
            ui.element("p", "", "Read-only overview of tenant and subscription health, support workload, messaging health, AI usage, billing attention, and Platform Admin activity.")
        );
        header.append(titleGroup, actionLink("platform-admin-companies.html", "Open Company Directory"));

        const refreshed = ui.element("p", "platform-note", "Overview generated " + ui.formatDate(overview && overview.generated_at) + ".");
        refreshed.setAttribute("aria-live", "polite");
        const healthGrid = ui.element("div", "platform-dashboard-health-grid");
        healthGrid.append(
            renderSupportPanel((overview || {}).support || {}),
            renderMessagingPanel((overview || {}).messaging || {}),
            renderAiUsagePanel((overview || {}).ai_usage || {}),
            renderBillingPanel((overview || {}).billing_attention || {})
        );

        const stack = ui.element("div", "platform-dashboard-stack");
        stack.append(
            header,
            renderOverviewCards(overview || {}),
            refreshed,
            renderNeedsAttention(overview || {}),
            healthGrid,
            renderAttentionCompanies((overview || {}).attention_companies || []),
            renderActivityPanel((overview || {}).platform_admin_activity || {})
        );
        root.append(stack);
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

    window.PlatformAdminDashboard = Object.freeze({
        renderDashboardOverview: renderDashboardOverview,
        deliveryHealthRows: deliveryHealthRows
    });

    document.addEventListener("DOMContentLoaded", function () {
        PlatformAdminShell.start({ onAuthorized: renderDashboard });
    });
}());
