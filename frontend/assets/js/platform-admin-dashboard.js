(function () {
    "use strict";

    const ui = PlatformAdminShell;

    function definitionItem(label, value) {
        const wrapper = ui.element("div");
        wrapper.append(
            ui.element("dt", "", label),
            ui.element("dd", "", value === null || value === undefined || value === "" ? "Not available" : value)
        );
        return wrapper;
    }

    function metric(label) {
        const card = ui.element("article", "platform-metric");
        const value = ui.element("strong", "platform-metric-value", "Loading");
        card.append(ui.element("span", "platform-metric-label", label), value);
        return { card: card, value: value };
    }

    function exactTotal(result) {
        const total = result && result.pagination ? result.pagination.total : null;
        if (!Number.isSafeInteger(total) || total < 0) {
            const error = new Error("unavailable");
            error.category = "unavailable";
            throw error;
        }
        return total;
    }

    async function renderDashboard(identity) {
        const root = document.getElementById("platform-page-content");
        root.replaceChildren();

        const header = ui.element("header", "platform-page-header");
        const titleGroup = ui.element("div");
        titleGroup.append(
            ui.element("h1", "", "Platform dashboard"),
            ui.element("p", "", "Read-only visibility across tenant companies.")
        );
        const directoryLink = ui.element("a", "platform-link-button", "Open company directory");
        directoryLink.href = "platform-admin-companies.html";
        header.append(titleGroup, directoryLink);

        const metrics = ui.element("section", "platform-grid");
        metrics.setAttribute("aria-label", "Company status summary");
        const totalMetric = metric("Total companies");
        const activeMetric = metric("Active companies");
        const inactiveMetric = metric("Inactive companies");
        metrics.append(totalMetric.card, activeMetric.card, inactiveMetric.card);

        const user = identity && identity.user ? identity.user : {};
        const platformAdmin = identity && identity.platform_admin ? identity.platform_admin : {};
        const identityPanel = ui.element("section", "platform-panel");
        identityPanel.append(ui.element("h2", "", "Current platform administrator"));
        const identityList = ui.element("dl", "platform-definition-grid");
        identityList.append(
            definitionItem("Application user ID", user.id),
            definitionItem("Name", user.full_name),
            definitionItem("Email", user.email),
            definitionItem("Application status", user.status),
            definitionItem("Platform-admin mapping ID", platformAdmin.id),
            definitionItem("Mapping active", platformAdmin.is_active === true ? "Yes" : "No"),
            definitionItem("Mapping created", ui.formatDate(platformAdmin.created_at)),
            definitionItem("Mapping updated", ui.formatDate(platformAdmin.updated_at))
        );
        identityPanel.append(identityList);

        const auditNote = ui.element(
            "p",
            "platform-note",
            "These three exact count requests each create a platform-admin audit event."
        );
        auditNote.id = "platform-dashboard-audit-note";
        const refreshed = ui.element("p", "platform-note", "Counts are loading.");
        refreshed.setAttribute("aria-live", "polite");
        root.append(header, metrics, auditNote, refreshed, identityPanel);

        try {
            const results = await Promise.all([
                ui.runRequest("dashboard-count-total", function (signal) {
                    return PlatformAdminApi.listCompanies({
                        limit: 1, offset: 0, sortBy: "id", sortOrder: "asc", signal: signal
                    });
                }),
                ui.runRequest("dashboard-count-active", function (signal) {
                    return PlatformAdminApi.listCompanies({
                        limit: 1, offset: 0, status: "active", sortBy: "id", sortOrder: "asc", signal: signal
                    });
                }),
                ui.runRequest("dashboard-count-inactive", function (signal) {
                    return PlatformAdminApi.listCompanies({
                        limit: 1, offset: 0, status: "inactive", sortBy: "id", sortOrder: "asc", signal: signal
                    });
                })
            ]);
            totalMetric.value.textContent = ui.formatInteger(exactTotal(results[0]));
            activeMetric.value.textContent = ui.formatInteger(exactTotal(results[1]));
            inactiveMetric.value.textContent = ui.formatInteger(exactTotal(results[2]));
            refreshed.textContent = "Counts refreshed " + ui.formatDate(new Date().toISOString()) + ".";
        } catch (error) {
            ui.handleError(error);
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        PlatformAdminShell.start({ onAuthorized: renderDashboard });
    });
}());
