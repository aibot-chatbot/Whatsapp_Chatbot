(function () {
    "use strict";

    const ui = PlatformAdminShell;
    const api = PlatformAdminApi;
    const usd = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });
    const reasons = { ours: "Disabled for a Client", openrouter: "Disabled by OpenRouter",
        manual_replacement: "Replaced manually" };

    async function showPage() {
        const root = document.getElementById("platform-page-content");
        root.replaceChildren(document.getElementById("key-page").content.cloneNode(true));
        const get = id => root.querySelector("#" + id);
        const form = get("replace-form"), panel = get("replace-panel");
        const input = get("replacement-key"), reason = get("replacement-reason"), toggle = get("show-key");
        const result = get("key-result"), error = get("key-error");
        let selected = null, opener = null, saving = false;

        function showInput(visible) {
            input.type = visible ? "text" : "password";
            toggle.setAttribute("aria-pressed", String(visible));
            toggle.textContent = visible ? "Hide" : "Show";
        }
        function clearForm() {
            showInput(false);
            input.value = "";
            reason.value = "";
            error.textContent = "";
        }
        function closeForm() {
            clearForm();
            panel.hidden = true;
            selected = null;
        }
        toggle.addEventListener("click", () => showInput(input.type === "password"));
        get("cancel-key").addEventListener("click", () => {
            closeForm();
            if (opener && opener.isConnected) opener.focus();
        });

        async function refresh() {
            const status = get("key-list-status"), body = get("key-rows");
            status.textContent = "Loading keys.";
            try {
                const data = await ui.runRequest("key-list", signal => api.listOpenRouterKeys(signal));
                body.replaceChildren();
                for (const key of data.keys) {
                    const row = ui.element("tr");
                    const label = key.label || ("Key #" + key.id + " (ending unavailable)");
                    const money = value => Number.isFinite(value) ? usd.format(value) : "Unknown";
                    for (const value of [label, key.status, reasons[key.disabled_reason] || "—", key.clients,
                        money(key.usage), money(key.limit)]) row.append(ui.element("td", "", value));
                    const action = ui.element("td"), button = ui.element("button", "platform-button", "Replace");
                    button.type = "button";
                    button.disabled = key.disabled_reason === "manual_replacement";
                    button.setAttribute("aria-label", "Replace " + label);
                    button.addEventListener("click", () => {
                        if (saving) return;
                        clearForm();
                        selected = key.id;
                        opener = button;
                        get("replace-heading").textContent = "Replace " + label;
                        panel.hidden = false;
                        input.focus();
                    });
                    action.append(button);
                    row.append(action);
                    body.append(row);
                }
                status.textContent = data.keys.length ? "" : "No Client keys have been assigned yet.";
            } catch (failure) {
                if (failure.category === "aborted" || !root.contains(status)) return;
                if (["unauthenticated", "access_denied"].includes(failure.category)) {
                    ui.handleError(failure);
                    return;
                }
                body.replaceChildren();
                status.textContent = "The list could not be loaded. Select Refresh to try again.";
            }
        }

        form.addEventListener("submit", async event => {
            event.preventDefault();
            if (saving || selected === null) return;
            saving = true;
            error.textContent = "";
            showInput(false);
            for (const field of form.elements) field.disabled = true;
            try {
                const pending = ui.runRequest("replace-key", signal => api.replaceOpenRouterKey(
                    selected, { api_key: input.value, reason: reason.value }, signal));
                input.value = "";
                const saved = await pending;
                closeForm();
                result.textContent = "Saved " + saved.label + ". Clients moved: " + saved.moved_count + "." +
                    (saved.old_key_disabled ? "" : " OpenRouter did not confirm that the old key was disabled. Check it in OpenRouter.");
                result.focus();
                await refresh();
            } catch (failure) {
                if (failure.category === "aborted" || !root.contains(form)) return;
                if (["unauthenticated", "access_denied"].includes(failure.category)) {
                    ui.handleError(failure);
                    return;
                }
                error.textContent = failure.status === 429 ? "Too many attempts. Wait a minute before trying again."
                    : failure.status === 400 ? "Check the key and the reason. Use an active, capped key from this account."
                    : "The change could not be confirmed. Refresh the list before trying again.";
            } finally {
                saving = false;
                for (const field of form.elements) field.disabled = false;
            }
        });
        get("refresh-keys").addEventListener("click", refresh);
        await refresh();
    }
    ui.start({ onAuthorized: showPage });
}());
