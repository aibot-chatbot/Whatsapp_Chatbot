(function () {
    "use strict";

    const ui = window.PlatformAdminShell;
    const state = { identity: null, rows: [], pending: false };

    function el(tag, className, text) {
        return ui.element(tag, className, text);
    }

    function safeName(row) {
        return row.user_full_name || row.user_email || "User #" + row.user_id;
    }

    function creator(row) {
        if (!row.creator_user_id) return "Bootstrap/unknown";
        return row.creator_full_name || row.creator_email || "User #" + row.creator_user_id;
    }

    function messageFor(error) {
        const code = error && error.code;
        const messages = {
            self_deactivation_not_allowed: "You cannot deactivate yourself.",
            final_active_platform_admin: "The final active platform admin cannot be deactivated.",
            platform_admin_mapping_exists: "That user already has a platform-admin mapping.",
            target_user_not_protected: "User is not eligible for platform-admin access.",
            target_user_inactive: "Target user must be active.",
            target_user_not_found: "Target user not found.",
            no_change: "No change required.",
            invalid_user_id: "Enter a positive numeric user ID.",
            invalid_is_active: "Choose a valid active state."
        };
        return messages[code] || "Platform-admin user management is temporarily unavailable.";
    }

    function isAuthorizationFailure(error) {
        const category = error && error.category;
        return category === "unauthenticated" || category === "access_denied";
    }

    function renderRecoverableRefreshError() {
        const root = document.getElementById("platform-page-content");
        if (!root) return;
        const retry = el("button", "platform-button platform-button-primary", "Retry");
        retry.type = "button";
        retry.addEventListener("click", async function () {
            retry.disabled = true;
            try {
                await load({ recoverableOnFailure: true });
            } catch (error) {
                if (!ui.handleError(error)) renderRecoverableRefreshError();
            }
        });
        const panel = el("section", "platform-panel");
        panel.append(
            el("h1", "", "Platform Admin Management"),
            el("p", "platform-error", "Platform-admin directory refresh failed. Retry to load the current state."),
            retry
        );
        root.replaceChildren(panel);
    }

    function summary(rows) {
        const wrap = el("div", "platform-summary-grid");
        const active = rows.filter((row) => row.is_active === true).length;
        const inactive = rows.filter((row) => row.is_active === false).length;
        [["Active", active], ["Inactive", inactive], ["Total", rows.length]].forEach(function (item) {
            const card = el("section", "platform-card");
            card.append(el("span", "platform-card-label", item[0]), el("strong", "platform-card-value", String(item[1])));
            wrap.append(card);
        });
        return wrap;
    }

    function pageHeader() {
        const header = el("header", "platform-page-header");
        const copy = el("div");
        copy.append(
            el("p", "platform-eyebrow", "Controlled access"),
            el("h1", "", "Platform Admin Management"),
            el("p", "platform-muted", "Manage dedicated platform-admin mappings only. Tenant role management, invitations, password resets, impersonation, deletion, billing actions, and company suspension are excluded.")
        );
        header.append(copy);
        return header;
    }

    function addForm() {
        const section = el("section", "platform-panel");
        section.append(
            el("h2", "", "Add existing platform admin"),
            el("p", "platform-muted", "The user account must already exist and belong to the protected internal company. Invitations and new-account creation are not supported here.")
        );
        const form = el("form", "platform-inline-form");
        const label = el("label", "", "Existing user ID");
        const input = el("input");
        input.type = "number";
        input.min = "1";
        input.step = "1";
        input.required = true;
        input.inputMode = "numeric";
        label.append(input);
        const button = el("button", "platform-button platform-button-primary", "Add platform admin");
        button.type = "submit";
        const status = el("p", "platform-form-status");
        form.append(label, button);
        form.addEventListener("submit", async function (event) {
            event.preventDefault();
            if (state.pending) return;
            const userId = Number(input.value);
            if (!Number.isSafeInteger(userId) || userId <= 0) {
                status.textContent = "Enter a positive numeric user ID.";
                return;
            }
            if (!window.confirm("Add this existing protected-company user as a platform admin?")) return;
            state.pending = true;
            button.disabled = true;
            status.textContent = "Adding platform admin...";
            try {
                await ui.runRequest("platform-admin-user-create", (signal) => PlatformAdminApi.createPlatformAdminUser(userId, { signal }));
                status.textContent = "Platform admin added.";
                await load({ recoverableOnFailure: true });
            } catch (error) {
                if (!ui.handleError(error)) status.textContent = messageFor(error);
            } finally {
                state.pending = false;
                if (button.isConnected) button.disabled = false;
            }
        });
        section.append(form, status);
        return section;
    }

    function table(rows) {
        const section = el("section", "platform-panel");
        section.append(el("h2", "", "Platform Admins"));
        const tableNode = el("table", "platform-table");
        const thead = el("thead");
        const header = el("tr");
        ["Name", "State", "Mapping ID", "User ID", "Created", "Updated", "Creator", "Recent platform activity", "Action"].forEach((label) => header.append(el("th", "", label)));
        thead.append(header);
        const tbody = el("tbody");
        const activeCount = rows.filter((row) => row.is_active === true).length;
        const selfId = state.identity && state.identity.platform_admin ? state.identity.platform_admin.id : null;
        rows.forEach(function (row) {
            const tr = el("tr");
            tr.append(
                el("td", "", safeName(row)),
                el("td", "", row.is_active ? "Active" : "Inactive"),
                el("td", "", row.platform_admin_user_id),
                el("td", "", row.user_id),
                el("td", "", ui.formatDate(row.created_at)),
                el("td", "", ui.formatDate(row.updated_at)),
                el("td", "", creator(row)),
                el("td", "", ui.formatDate(row.recent_platform_admin_activity_at))
            );
            const actionCell = el("td");
            const nextActive = !row.is_active;
            const button = el("button", "platform-button", nextActive ? "Activate" : "Deactivate");
            button.type = "button";
            if (row.platform_admin_user_id === selfId && !nextActive) {
                button.disabled = true;
                button.title = "Self-deactivation is rejected by policy.";
            }
            if (activeCount <= 1 && row.is_active) {
                button.disabled = true;
                button.title = "The final active platform admin cannot be deactivated.";
            }
            button.addEventListener("click", async function () {
                if (state.pending) return;
                if (!nextActive && !window.confirm("Deactivate this platform-admin mapping?")) return;
                state.pending = true;
                button.disabled = true;
                try {
                    await ui.runRequest("platform-admin-user-active-" + row.platform_admin_user_id, (signal) => (
                        PlatformAdminApi.setPlatformAdminUserActive(row.platform_admin_user_id, nextActive, { signal })
                    ));
                    await load({ recoverableOnFailure: true });
                } catch (error) {
                    if (!ui.handleError(error)) {
                        const status = document.getElementById("platform-admin-user-status");
                        if (status) status.textContent = messageFor(error);
                    }
                } finally {
                    state.pending = false;
                    if (button.isConnected) button.disabled = false;
                }
            });
            actionCell.append(button);
            tr.append(actionCell);
            tbody.append(tr);
        });
        tableNode.append(thead, tbody);
        section.append(tableNode);
        return section;
    }

    async function load(options) {
        const config = options || {};
        const root = document.getElementById("platform-page-content");
        root.replaceChildren(el("p", "platform-muted", "Loading platform admins..."));
        let data;
        try {
            data = await ui.runRequest("platform-admin-users", (signal) => PlatformAdminApi.listPlatformAdminUsers({ limit: 100, offset: 0, signal }));
        } catch (error) {
            if (config.recoverableOnFailure && !isAuthorizationFailure(error)) {
                renderRecoverableRefreshError();
                return false;
            }
            throw error;
        }
        state.rows = data.platform_admin_users || [];
        const status = el("p", "platform-form-status");
        status.id = "platform-admin-user-status";
        root.replaceChildren(
            pageHeader(),
            summary(state.rows),
            addForm(),
            status,
            table(state.rows)
        );
        return true;
    }

    async function initialize(identity) {
        state.identity = identity;
        try {
            await load();
        } catch (error) {
            if (!ui.handleError(error)) {
                document.getElementById("platform-page-content").replaceChildren(
                    el("p", "platform-error", "Platform-admin user management is temporarily unavailable.")
                );
            }
        }
    }

    PlatformAdminShell.start({ onAuthorized: initialize });
}());
