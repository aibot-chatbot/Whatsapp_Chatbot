(function () {
    "use strict";

    const lifecycle = {
        epoch: 0,
        requests: new Map(),
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
        document.querySelectorAll("[data-platform-sensitive]").forEach(function (node) {
            node.replaceChildren();
        });
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

    window.addEventListener("pagehide", clearPlatformState);

    window.PlatformAdminShell = Object.freeze({
        start: start,
        runRequest: runRequest,
        handleError: handleError,
        clearPlatformState: clearPlatformState
    });
}());
