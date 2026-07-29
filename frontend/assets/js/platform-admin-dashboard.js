(function () {
    "use strict";

    const ui = PlatformAdminShell;
    const STATUS_ORDER = ["trialing", "active", "past_due", "expired", "cancelled"];

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
