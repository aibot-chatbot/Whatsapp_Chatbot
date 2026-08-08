(function () {
    "use strict";

    const lifecycle = {
        epoch: 0,
        requests: new Map(),
        identity: null,
        onAuthorized: null
    };

    function element(tag, className, textValue) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (textValue !== undefined && textValue !== null) node.textContent = String(textValue);
        return node;
    }

    function fixedStateCard(title, message) {
        const card = element("div", "platform-state-card");
        const heading = element("h1", "", title);
        heading.tabIndex = -1;
        card.append(heading, element("p", "", message));
        return { card: card, heading: heading };
    }

    function showCheckingState() {
        const state = document.getElementById("platform-access-state");
        if (!state) return;
        state.replaceChildren();
        state.hidden = false;
        state.setAttribute("aria-busy", "true");
        const card = element("div", "platform-state-card");
        const spinner = element("div", "platform-spinner");
        spinner.setAttribute("aria-hidden", "true");
        card.append(
            spinner,
            element("h1", "", "Checking access"),
            element("p", "", "Confirming your current platform authorization.")
        );
        state.append(card);
    }

    function showBlockingState(kind) {
        const state = document.getElementById("platform-access-state");
        if (!state) return;
        const config = kind === "access_denied"
            ? {
                title: "Access Denied",
                message: "Your current account is not authorized for Platform Administration."
            }
            : {
                title: "Temporarily Unavailable",
                message: "Platform Administration cannot be loaded safely right now."
            };
        const built = fixedStateCard(config.title, config.message);
        const actions = element("div", "platform-state-actions");
        const tenantLink = element("a", "platform-link-button", "Return to Tenant App");
        tenantLink.href = "bots.html";
        actions.append(tenantLink);
        if (kind === "unavailable") {
            const retry = element("button", "platform-button platform-button-primary", "Retry");
            retry.type = "button";
            retry.addEventListener("click", authorizeCurrentPage);
            actions.prepend(retry);
        }
        built.card.append(actions);
        state.replaceChildren(built.card);
        state.hidden = false;
        state.setAttribute("aria-busy", "false");
        built.heading.focus();
    }

    function abortAllRequests() {
        lifecycle.requests.forEach(function (entry) {
            entry.controller.abort();
        });
        lifecycle.requests.clear();
    }

    function invalidatePage() {
        lifecycle.epoch += 1;
        abortAllRequests();
    }

    function clearPlatformState() {
        invalidatePage();
        lifecycle.identity = null;
        document.querySelectorAll("[data-platform-sensitive]").forEach(function (node) {
            node.replaceChildren();
        });
        const shell = document.querySelector("platform-admin-shell");
        if (shell && typeof shell.clearIdentity === "function") shell.clearIdentity();
        const app = document.getElementById("platform-app");
        if (app) app.hidden = true;
    }

    async function runRequest(operationKey, requestFactory) {
        const previous = lifecycle.requests.get(operationKey);
        if (previous) previous.controller.abort();

        const controller = new AbortController();
        const requestEpoch = lifecycle.epoch;
        const entry = { controller: controller, epoch: requestEpoch };
        lifecycle.requests.set(operationKey, entry);
        try {
            const result = await requestFactory(controller.signal);
            if (requestEpoch !== lifecycle.epoch) {
                const stale = new Error("stale");
                stale.name = "AbortError";
                stale.category = "aborted";
                throw stale;
            }
            return result;
        } finally {
            if (lifecycle.requests.get(operationKey) === entry) {
                lifecycle.requests.delete(operationKey);
            }
        }
    }

    function handleError(error) {
        const category = error && error.category;
        if (category === "aborted") return true;
        if (category === "unauthenticated") {
            clearPlatformState();
            logout();
            return true;
        }
        if (category === "access_denied") {
            clearPlatformState();
            showBlockingState("access_denied");
            return true;
        }
        if (category === "unavailable") {
            clearPlatformState();
            showBlockingState("unavailable");
            return true;
        }
        return false;
    }

    async function authorizeCurrentPage() {
        clearPlatformState();
        showCheckingState();
        if (!sessionStorage.getItem("token")) {
            logout();
            return;
        }

        try {
            const identity = await runRequest("authorization", function (signal) {
                return PlatformAdminApi.getMe({ signal: signal });
            });
            lifecycle.identity = identity;
            const shell = document.querySelector("platform-admin-shell");
            if (shell && typeof shell.setIdentity === "function") shell.setIdentity(identity);
            const accessState = document.getElementById("platform-access-state");
            const app = document.getElementById("platform-app");
            if (accessState) accessState.hidden = true;
            if (app) app.hidden = false;
            if (typeof lifecycle.onAuthorized === "function") {
                await lifecycle.onAuthorized(identity);
            }
        } catch (error) {
            if (!handleError(error)) {
                clearPlatformState();
                showBlockingState("unavailable");
            }
        }
    }

    function start(options) {
        lifecycle.onAuthorized = options && options.onAuthorized;
        authorizeCurrentPage();
    }

    function formatDate(value) {
        if (!value) return "Not available";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "Not available";
        return new Intl.DateTimeFormat(undefined, {
            dateStyle: "medium",
            timeStyle: "short"
        }).format(date);
    }

    function formatInteger(value) {
        return Number.isSafeInteger(value) ? new Intl.NumberFormat().format(value) : "Not available";
    }

    function formatMicroAmount(value, currency) {
        if (!Number.isSafeInteger(value)) return "Not available";
        return new Intl.NumberFormat(undefined, {
            style: "currency",
            currency: currency,
            minimumFractionDigits: 2,
            maximumFractionDigits: 6
        }).format(value / 1000000);
    }

    function statusBadge(value) {
        const normalized = typeof value === "string" ? value.trim().toLowerCase() : "unknown";
        const label = normalized ? normalized.replaceAll("_", " ") : "unknown";
        const badge = element("span", "platform-status", label);
        const classSuffix = normalized.replaceAll("_", "-").replaceAll(" ", "-");
        if (["active", "trialing", "past-due", "inactive", "expired", "cancelled"].includes(classSuffix)) {
            badge.classList.add("platform-status-" + classSuffix);
        }
        return badge;
    }

    class PlatformAdminShellElement extends HTMLElement {
        connectedCallback() {
            if (this.hasChildNodes()) return;
            const aside = element("aside", "platform-sidebar");
            aside.setAttribute("aria-label", "Platform Administration navigation");

            const brand = element("div", "platform-brand");
            const mark = element("div", "platform-brand-mark", "PA");
            mark.setAttribute("aria-hidden", "true");
            const brandText = element("div");
            brandText.append(
                element("p", "platform-brand-title", "Platform Administration"),
                element("span", "platform-readonly-badge", "Internal / Controlled Access")
            );
            brand.append(mark, brandText);

            const nav = element("nav", "platform-nav");
            nav.setAttribute("aria-label", "Platform sections");
            const dashboard = element("a", "", "Dashboard");
            dashboard.href = "platform-admin.html";
            const companies = element("a", "", "Companies");
            companies.href = "platform-admin-companies.html";
            const support = element("a", "", "Support");
            support.href = "platform-admin-support.html";
            const platformAdmins = element("a", "", "Platform Admins");
            platformAdmins.href = "platform-admin-users.html";
            const auditEvents = element("a", "", "Audit Logs");
            auditEvents.href = "platform-admin-audit-events.html";
            const active = this.getAttribute("active-page");
            if (active === "dashboard") dashboard.setAttribute("aria-current", "page");
            if (active === "companies") companies.setAttribute("aria-current", "page");
            if (active === "support") support.setAttribute("aria-current", "page");
            if (active === "platform-admin-users") platformAdmins.setAttribute("aria-current", "page");
            if (active === "audit-events") auditEvents.setAttribute("aria-current", "page");
            nav.append(dashboard, companies, support, platformAdmins, auditEvents);

            const footer = element("div", "platform-shell-footer");
            this.operator = element("div", "platform-operator");
            this.operator.append(
                element("strong", "", "Authorized operator"),
                element("span", "", "Checking current authorization")
            );
            const tenant = element("a", "platform-shell-action", "Return to Tenant App");
            tenant.href = "bots.html";
            const logoutButton = element("button", "platform-shell-action", "Logout");
            logoutButton.type = "button";
            logoutButton.addEventListener("click", function () {
                clearPlatformState();
                logout();
            });
            footer.append(this.operator, tenant, logoutButton);
            aside.append(brand, nav, footer);
            this.append(aside);
        }

        setIdentity(identity) {
            if (!this.operator) return;
            const user = identity && identity.user ? identity.user : {};
            const display = user.full_name || user.email || "Authorized operator";
            this.operator.replaceChildren(
                element("strong", "", "Authorized operator"),
                element("span", "", display)
            );
        }

        clearIdentity() {
            if (!this.operator) return;
            this.operator.replaceChildren(
                element("strong", "", "Authorized operator"),
                element("span", "", "Authorization cleared")
            );
        }
    }

    customElements.define("platform-admin-shell", PlatformAdminShellElement);
    window.addEventListener("pagehide", clearPlatformState);

    window.PlatformAdminShell = Object.freeze({
        start: start,
        runRequest: runRequest,
        handleError: handleError,
        clearPlatformState: clearPlatformState,
        element: element,
        formatDate: formatDate,
        formatInteger: formatInteger,
        formatMicroMyr: function (value) { return formatMicroAmount(value, "MYR"); },
        formatMicroUsd: function (value) { return formatMicroAmount(value, "USD"); },
        statusBadge: statusBadge
    });
}());
