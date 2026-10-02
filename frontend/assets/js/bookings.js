(function () {
    "use strict";

    /* pure:start - no DOM, no network; tests/test_bookings_frontend.py runs this block in Node. */
    const MYT_OFFSET_MS = 8 * 60 * 60 * 1000; // Malaysia has no daylight saving
    const PAGE_SIZE = 50;
    const STATUS_META = {
        requested: { label: "Needs confirming", tone: "review" },
        confirmed: { label: "Confirmed", tone: "ready" },
        completed: { label: "Completed", tone: "ready" },
        cancelled: { label: "Cancelled", tone: "off" }
    };
    const KIND_LABELS = { booking: "Booking", reservation: "Reservation", appointment: "Appointment", other: "Request" };
    const ACTIONS = {
        requested: ["confirm", "edit", "cancel"],
        confirmed: ["complete", "edit", "cancel"],
        completed: [],
        cancelled: []
    };
    const ACTION_CHANGES = {
        confirm: { status: "confirmed" },
        complete: { status: "completed" },
        cancel: { status: "cancelled" }
    };
    const WHEN_FORMAT = new Intl.DateTimeFormat("en-GB", {
        day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit",
        hour12: true, timeZone: "Asia/Kuala_Lumpur"
    });

    function statusMeta(status) {
        return STATUS_META[status] || { label: "Unknown", tone: "off" };
    }

    function kindLabel(kind) {
        return KIND_LABELS[kind] || KIND_LABELS.other;
    }

    function allowedActions(status) {
        return (ACTIONS[status] || []).slice();
    }

    function formatWhen(iso) {
        const time = Date.parse(iso);
        return Number.isNaN(time) ? "" : WHEN_FORMAT.format(new Date(time));
    }

    // "2026-10-05T11:00:00+00:00" -> "2026-10-05T19:00", the value a datetime-local input expects.
    function toLocalInput(iso) {
        const time = Date.parse(iso);
        return Number.isNaN(time) ? "" : new Date(time + MYT_OFFSET_MS).toISOString().slice(0, 16);
    }

    function clean(value) {
        return String(value == null ? "" : value).trim();
    }

    // Only the fields the person actually changed, so a save never overwrites a concurrent edit
    // to a field they did not touch. A cleared field becomes null.
    function buildChanges(booking, form) {
        const changes = {};
        const errors = {};
        ["customer_name", "service_name", "notes"].forEach(function (field) {
            const next = clean(form[field]) || null;
            const previous = clean(booking[field]) || null;
            if (next !== previous) changes[field] = next;
        });
        if (form.kind !== booking.kind) changes.kind = form.kind;
        const when = clean(form.scheduled_for);
        if (when !== toLocalInput(booking.scheduled_for)) changes.scheduled_for = when || null;
        const size = clean(form.party_size);
        if (size === "") {
            if (booking.party_size != null) changes.party_size = null;
        } else if (!/^[0-9]+$/.test(size) || Number(size) < 1 || Number(size) > 10000) {
            errors.party_size = "Enter a whole number from 1 to 10000.";
        } else if (Number(size) !== booking.party_size) {
            changes.party_size = Number(size);
        }
        return { changes: changes, errors: errors };
    }
    /* pure:end */

    const $ = function (id) { return document.getElementById(id); };
    const ACTION_LABELS = { confirm: "Confirm", complete: "Complete", edit: "Edit", cancel: "Cancel" };
    const DONE_MESSAGES = { confirm: "Booking confirmed.", complete: "Booking marked completed.", cancel: "Booking cancelled." };
    const CONFLICT_MESSAGE = "Someone else changed this booking. The list has been refreshed.";
    const state = {
        bookings: [], hasMore: false, generation: 0, intakeGeneration: 0, bots: [],
        isAdmin: false, editing: null, pendingCancel: null, busy: false
    };

    function el(tag, className, content) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (content != null) node.textContent = content;
        return node;
    }

    function currentRole() {
        try { return JSON.parse(sessionStorage.getItem("user") || "{}").role || ""; } catch (_) { return ""; }
    }

    function setStatus(message) {
        $("bk-status").textContent = message;
    }

    function showError(message, retryable) {
        $("bk-error-text").textContent = message;
        $("bk-retry").hidden = !retryable;
        $("bk-error").hidden = false;
    }

    function clearError() {
        $("bk-error").hidden = true;
    }

    function setIntakeNote(message) {
        const note = $("bk-intake-note");
        note.textContent = message || "";
        note.hidden = !message;
    }

    // Writes only. Reads go through resilientLoad, which would turn a PATCH into a retried GET.
    async function send(method, url, body) {
        let response;
        try {
            response = await authenticatedFetch(url, {
                method: method,
                headers: { "Content-Type": "application/json" },
                body: body === undefined ? undefined : JSON.stringify(body)
            });
        } catch (_) {
            return { ok: false, status: 0, message: "Could not reach the server. Check your connection and try again." };
        }
        let payload = null;
        try { payload = await response.json(); } catch (_) { payload = null; }
        const ok = response.ok && payload !== null && payload.status === "success";
        return { ok: ok, status: response.status, data: ok ? payload.data : null, message: payload && payload.message };
    }

    function failureMessage(result) {
        if (result.status === 0) return result.message;
        if (result.status === 409) return CONFLICT_MESSAGE;
        if (result.status === 403) return result.message || "You do not have permission to do that.";
        if (result.status === 400 || result.status === 404 || result.status === 413) {
            return result.message || "That change could not be saved.";
        }
        return "Something went wrong on our end. Please try again.";
    }

    function activeFilters() {
        return { status: $("bk-filter-status").value, chatbot: $("bk-filter-bot").value };
    }

    function matchesFilters(booking) {
        const filters = activeFilters();
        return (!filters.status || booking.status === filters.status)
            && (!filters.chatbot || String(booking.chatbot_id) === filters.chatbot);
    }

    function buildRow(booking) {
        const row = el("tr");
        const name = clean(booking.customer_name);

        row.appendChild(el("td", "bookings-nowrap", formatWhen(booking.created_at) || "—"));

        const customer = el("td");
        const customerStack = el("div", "kw-cell-stack");
        customerStack.appendChild(el("span", "bookings-primary", name || "Unknown customer"));
        const contact = [clean(booking.customer_phone) || clean(booking.customer_ref), clean(booking.channel)]
            .filter(Boolean).join(" · ");
        if (contact) customerStack.appendChild(el("span", "kw-help bookings-secondary kw-mono", contact));
        customer.appendChild(customerStack);
        row.appendChild(customer);

        const request = el("td");
        const requestStack = el("div", "kw-cell-stack");
        requestStack.appendChild(el("span", "bookings-primary", clean(booking.service_name) || "—"));
        const detail = [kindLabel(booking.kind), clean(booking.notes)].filter(Boolean).join(" · ");
        const detailNode = el("span", "kw-help bookings-secondary bookings-clamp", detail);
        detailNode.title = detail;
        requestStack.appendChild(detailNode);
        request.appendChild(requestStack);
        row.appendChild(request);

        row.appendChild(el("td", "bookings-nowrap", formatWhen(booking.scheduled_for) || "Not set"));
        row.appendChild(el("td", null, booking.party_size != null ? String(booking.party_size) : "—"));

        const meta = statusMeta(booking.status);
        const status = el("td");
        status.appendChild(el("span", "kw-pill kw-pill-" + meta.tone, meta.label));
        row.appendChild(status);

        const actions = el("td");
        const actionBar = el("div", "bookings-actions");
        allowedActions(booking.status).forEach(function (action) {
            const kind = action === "confirm" ? " kw-btn-primary" : action === "cancel" ? " kw-btn-danger" : "";
            const button = el("button", "kw-btn cr-press bookings-btn-sm" + kind, ACTION_LABELS[action]);
            button.type = "button";
            button.setAttribute("aria-label", ACTION_LABELS[action] + " booking for " + (name || "this customer"));
            button.addEventListener("click", function () { runAction(booking, action); });
            actionBar.appendChild(button);
        });
        actions.appendChild(actionBar);
        row.appendChild(actions);
        return row;
    }

    function render() {
        const rows = state.bookings;
        $("bk-loading").hidden = true;
        const tbody = $("bk-tbody");
        tbody.replaceChildren();
        const filtered = Boolean(activeFilters().status || activeFilters().chatbot);

        if (rows.length === 0) {
            $("bk-table-wrap").hidden = true;
            $("bk-empty-title").textContent = filtered ? "No bookings match these filters" : "No booking requests yet";
            $("bk-empty-body").textContent = filtered
                ? "Try a different status or chatbot."
                : "Switch on chat requests above and they will show up here as customers ask.";
            $("bk-empty").hidden = false;
            setStatus(filtered ? "No bookings match these filters." : "No booking requests yet.");
            return;
        }
        $("bk-empty").hidden = true;
        rows.forEach(function (booking) { tbody.appendChild(buildRow(booking)); });
        $("bk-table-wrap").hidden = false;
        $("bk-count").textContent = rows.length === 1 ? "1 request" : rows.length + " requests";
        $("bk-more").hidden = !state.hasMore;
        const waiting = rows.filter(function (booking) { return booking.status === "requested"; }).length;
        setStatus(waiting > 0 ? waiting + " need confirming." : "Nothing is waiting for you.");
    }

    async function loadBookings(append) {
        const generation = ++state.generation;
        clearError();
        if (!append) {
            $("bk-tbody").replaceChildren();
            $("bk-table-wrap").hidden = true;
            $("bk-empty").hidden = true;
            $("bk-loading").hidden = false;
            setStatus("Loading bookings…");
        } else {
            $("bk-more").disabled = true;
        }
        const filters = activeFilters();
        const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(append ? state.bookings.length : 0) });
        if (filters.status) params.set("status", filters.status);
        if (filters.chatbot) params.set("chatbot_id", filters.chatbot);

        const outcome = await resilientLoad.loadJson("/api/bookings?" + params.toString());
        if (generation !== state.generation) return;
        $("bk-more").disabled = false;

        if (!outcome.ok || !outcome.data || !Array.isArray(outcome.data.bookings)) {
            $("bk-loading").hidden = true;
            showError(outcome.status === 0
                ? "Could not reach the server. Check your connection and try again."
                : "Could not load bookings. Please try again.", true);
            setStatus("Could not load bookings.");
            if (append) render();
            return;
        }
        const rows = outcome.data.bookings;
        if (append) {
            const seen = new Set(state.bookings.map(function (booking) { return booking.id; }));
            state.bookings = state.bookings.concat(rows.filter(function (booking) { return !seen.has(booking.id); }));
        } else {
            state.bookings = rows;
        }
        state.hasMore = rows.length === PAGE_SIZE;
        render();
    }

    // Applies one staff change, then updates the list in place. Never throws.
    async function applyChanges(booking, changes, doneMessage) {
        if (state.busy) return { ok: false, message: "Please wait for the current change to finish." };
        state.busy = true;
        $("bk-tbody").querySelectorAll("button").forEach(function (button) { button.disabled = true; });
        const body = Object.assign({ expected_version: booking.version }, changes);
        const result = await send("PATCH", "/api/bookings/" + encodeURIComponent(booking.id), body);
        state.busy = false;
        if (result.ok && result.data && result.data.booking) {
            const updated = result.data.booking;
            state.bookings = state.bookings
                .map(function (item) { return item.id === updated.id ? updated : item; })
                .filter(matchesFilters);
            clearError();
            render();
            setStatus(doneMessage);
            return { ok: true };
        }
        const conflict = result.status === 409;
        if (conflict) await loadBookings(false);
        else render();
        return { ok: false, conflict: conflict, message: failureMessage(result) };
    }

    function reportFailure(outcome) {
        if (outcome.ok) return;
        showError(outcome.message, false);
        setStatus(outcome.message);
    }

    async function runAction(booking, action) {
        if (action === "edit") { openEdit(booking); return; }
        if (action === "cancel") { askCancel(booking); return; }
        reportFailure(await applyChanges(booking, ACTION_CHANGES[action], DONE_MESSAGES[action]));
    }

    function askCancel(booking) {
        state.pendingCancel = booking;
        const name = clean(booking.customer_name);
        $("bk-confirm-body").textContent = (name ? "The booking for " + name : "This booking")
            + " is marked cancelled and stays in your file. This can't be undone.";
        window.kwDialog.open($("bk-confirm-modal"), $("bk-confirm-keep"));
    }

    function closeConfirm() {
        state.pendingCancel = null;
        window.kwDialog.close($("bk-confirm-modal"));
    }

    async function confirmCancel() {
        const booking = state.pendingCancel;
        closeConfirm();
        if (booking) reportFailure(await applyChanges(booking, ACTION_CHANGES.cancel, DONE_MESSAGES.cancel));
    }

    function showEditError(message) {
        const node = $("bk-edit-error");
        node.textContent = message;
        node.hidden = !message;
    }

    function openEdit(booking) {
        state.editing = booking;
        $("bk-edit-name").value = booking.customer_name || "";
        $("bk-edit-service").value = booking.service_name || "";
        $("bk-edit-kind").value = booking.kind || "other";
        $("bk-edit-when").value = toLocalInput(booking.scheduled_for);
        $("bk-edit-size").value = booking.party_size != null ? String(booking.party_size) : "";
        $("bk-edit-notes").value = booking.notes || "";
        showEditError("");
        window.kwDialog.open($("bk-edit-modal"), $("bk-edit-name"));
    }

    function closeEdit() {
        state.editing = null;
        window.kwDialog.close($("bk-edit-modal"));
    }

    async function saveEdit(event) {
        event.preventDefault();
        const booking = state.editing;
        if (!booking) return;
        const built = buildChanges(booking, {
            customer_name: $("bk-edit-name").value,
            service_name: $("bk-edit-service").value,
            kind: $("bk-edit-kind").value,
            scheduled_for: $("bk-edit-when").value,
            party_size: $("bk-edit-size").value,
            notes: $("bk-edit-notes").value
        });
        if (built.errors.party_size) { showEditError(built.errors.party_size); return; }
        if (Object.keys(built.changes).length === 0) { closeEdit(); setStatus("No changes to save."); return; }
        $("bk-edit-save").disabled = true;
        const outcome = await applyChanges(booking, built.changes, "Booking updated.");
        $("bk-edit-save").disabled = false;
        if (outcome.ok || outcome.conflict) {
            closeEdit();
            if (outcome.conflict) reportFailure(outcome);
        } else {
            showEditError(outcome.message);
        }
    }

    async function downloadCsv() {
        const button = $("bk-download");
        button.disabled = true;
        setStatus("Preparing your file…");
        try {
            const response = await authenticatedFetch("/api/bookings/export.csv");
            if (!response.ok) throw new Error("export_failed");
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement("a");
            link.href = url;
            link.download = "bookings.csv";
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
            clearError();
            setStatus("Your bookings file is downloading.");
        } catch (_) {
            showError("Could not prepare the file. Please try again.", false);
            setStatus("Could not prepare the file.");
        } finally {
            button.disabled = false;
        }
    }

    function intakeBotId() {
        const value = $("bk-intake-bot").value;
        return /^[0-9]+$/.test(value) ? Number(value) : null;
    }

    async function loadIntake() {
        const box = $("bk-intake-enabled");
        const id = intakeBotId();
        box.disabled = true;
        const generation = ++state.intakeGeneration;
        if (!id) { box.checked = false; return; }
        const outcome = await resilientLoad.loadJson("/api/bookings/settings?chatbot_id=" + id);
        if (generation !== state.intakeGeneration) return;
        if (!outcome.ok || !outcome.data) {
            box.checked = false;
            setIntakeNote("Could not load this chatbot's setting. Choose it again to retry.");
            return;
        }
        box.checked = outcome.data.enabled === true;
        box.disabled = !state.isAdmin;
        setIntakeNote(state.isAdmin ? "" : "Only an owner or admin can change this.");
    }

    async function toggleIntake() {
        const box = $("bk-intake-enabled");
        const select = $("bk-intake-bot");
        const id = intakeBotId();
        const wanted = box.checked;
        if (!id) return;
        box.disabled = true;
        select.disabled = true;
        const result = await send("PUT", "/api/bookings/settings", { chatbot_id: id, enabled: wanted });
        if (result.ok) {
            setIntakeNote(wanted
                ? "This chatbot now collects booking requests. Customers still wait for your team to confirm."
                : "This chatbot no longer collects booking requests.");
        } else {
            box.checked = !wanted;
            setIntakeNote(failureMessage(result));
        }
        select.disabled = false;
        box.disabled = !state.isAdmin;
    }

    function fillBots(bots) {
        const filter = $("bk-filter-bot");
        const intake = $("bk-intake-bot");
        filter.replaceChildren(new Option("All chatbots", ""));
        intake.replaceChildren();
        bots.forEach(function (bot) {
            const label = clean(bot.bot_name) || "Chatbot " + bot.id;
            filter.appendChild(new Option(label, String(bot.id)));
            intake.appendChild(new Option(label, String(bot.id)));
        });
        if (bots.length === 0) {
            intake.appendChild(new Option("No chatbots yet", ""));
            intake.disabled = true;
            return;
        }
        const preferred = parsePositiveSafeInteger(
            new URLSearchParams(location.search).get("bot_id") || sessionStorage.getItem("selectedBotId"));
        if (preferred && bots.some(function (bot) { return bot.id === preferred; })) intake.value = String(preferred);
        intake.disabled = false;
    }

    async function loadBots() {
        const outcome = await resilientLoad.loadJson("/api/bots");
        if (!outcome.ok || !Array.isArray(outcome.data)) {
            $("bk-intake-bot").replaceChildren(new Option("Could not load chatbots", ""));
            setIntakeNote("Could not load your chatbots. Refresh the page to try again.");
            return;
        }
        state.bots = outcome.data.filter(function (bot) { return bot && Number.isInteger(bot.id); });
        fillBots(state.bots);
        await loadIntake();
    }

    function wire() {
        $("bk-filter-status").addEventListener("change", function () { loadBookings(false); });
        $("bk-filter-bot").addEventListener("change", function () { loadBookings(false); });
        $("bk-refresh").addEventListener("click", function () { loadBookings(false); });
        $("bk-retry").addEventListener("click", function () { loadBookings(false); });
        $("bk-more").addEventListener("click", function () { loadBookings(true); });
        $("bk-download").addEventListener("click", downloadCsv);
        $("bk-intake-bot").addEventListener("change", loadIntake);
        $("bk-intake-enabled").addEventListener("change", toggleIntake);
        $("bk-edit-form").addEventListener("submit", saveEdit);
        $("bk-edit-close").addEventListener("click", closeEdit);
        $("bk-edit-cancel").addEventListener("click", closeEdit);
        $("bk-confirm-ok").addEventListener("click", confirmCancel);
        $("bk-confirm-keep").addEventListener("click", closeConfirm);
        $("bk-confirm-close").addEventListener("click", closeConfirm);
        // kw-a11y supplies the focus trap and focus restore but not Escape. The topmost dialog closes first.
        document.addEventListener("keydown", function (event) {
            if (event.key !== "Escape") return;
            if (window.kwDialog.isOpen($("bk-confirm-modal"))) closeConfirm();
            else if (window.kwDialog.isOpen($("bk-edit-modal"))) closeEdit();
        });
    }

    function start() {
        const role = currentRole();
        state.isAdmin = role === "owner" || role === "admin";
        wire();
        loadBookings(false);
        loadBots();
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})();
