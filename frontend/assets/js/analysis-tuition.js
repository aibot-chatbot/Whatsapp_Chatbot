(function () {
    "use strict";
    const $ = id => document.getElementById(id);
    const TIME_ZONE = "Asia/Kuala_Lumpur";
    const BOOKING_STATES = {confirmed: "Confirmed", cancelled: "Cancelled"};
    function el(tag, text, className) {
        const node = document.createElement(tag);
        if (text != null) node.textContent = text;
        if (className) node.className = className;
        return node;
    }
    function fallbackFormat(value) {
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short", timeZone: TIME_ZONE});
    }
    // init(botId, industry[, formatDate]): the Analysis page passes its own date formatter so both read the same.
    window.AnalysisTuition = {init(botId, industry, formatDate = fallbackFormat) {
        if (industry?.template_id !== "tuition_center" || !industry.confirmed_at) return;
        const entry = $("manage-trials"), dialog = $("tuition-dialog");
        if (entry.dataset.ready) return;
        entry.dataset.ready = "true";
        $("trials-panel").hidden = false;
        const base = `/api/tuition/bots/${botId}`;
        const time = value => formatDate(value) || "Time unknown";
        let busy = false;
        function status(message, error = false) {
            const node = $("tuition-status");
            node.textContent = message; node.dataset.error = String(error);
            node.className = error ? "kw-banner kw-banner-error tuition-status" : "kw-help tuition-status";
        }
        async function api(path, body) {
            const response = await authenticatedFetch(base + path, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
            const result = await response.json();
            if (!response.ok) throw new Error(result.message || "Trial lessons are unavailable.");
            return result.data;
        }
        function options(select, rows, empty) {
            const previous = select.value;
            select.replaceChildren(new Option(empty, ""));
            for (const row of rows) select.add(new Option(row.name, row.id));
            if (rows.some(row => row.id === previous)) select.value = previous;
        }
        function sessionForm(session) {
            const form = el("form", null, "tuition-session");
            form.dataset.sessionId = String(session.id);
            const title = el("h4", `${session.course_name} · ${session.class_name}`);
            title.id = `tuition-session-${session.id}`;
            form.setAttribute("aria-labelledby", title.id);
            const heading = el("div");
            heading.append(title, el("p", `${time(session.starts_at)} – ${time(session.ends_at)} · ${session.available_trial_seats} trial places available`, "kw-help"));
            const fields = el("div", null, "tuition-session-fields");
            for (const [name, label, minimum] of [["total_capacity", "Total capacity", 1], ["enrolled_seats", "Enrolled seats", 0], ["trial_limit", "Trial limit", 0]]) {
                const field = el("label", null, "kw-field"), input = el("input", null, "kw-input");
                Object.assign(input, {name, type: "number", min: minimum, max: 10000, step: 1, required: true, value: session[name]});
                field.append(el("span", label, "kw-label"), input); fields.append(field);
            }
            const save = el("button", "Save capacity", "kw-btn cr-press"); save.type = "submit";
            form.append(heading, fields, save);
            form.addEventListener("submit", event => {
                event.preventDefault();
                mutate(form, `/sessions/${encodeURIComponent(session.id)}/capacity`, {expected_version: session.version, ...capacities(form)}, "Capacity updated.");
            });
            return form;
        }
        function bookingItem(booking, sessions) {
            const item = el("li", null, "kw-log tuition-booking");
            const session = sessions.find(row => row.id === booking.session_id);
            const participant = booking.participant_label || "Participant";
            const head = el("div", null, "kw-log-head");
            head.append(el("span", participant, "kw-log-cat"),
                el("span", session ? time(session.starts_at) : "Session time unknown", "kw-log-time"));
            // The customer is told this reference in chat, so owners need it to match a booking.
            const line = el("p", `${BOOKING_STATES[booking.status] || booking.status} · Reference `, "kw-log-action");
            line.append(el("span", booking.id, "kw-mono"));
            const link = el("a", "Open chat", "analysis-chat-link");
            link.href = `conversations.html?bot_id=${botId}&conversation_id=${encodeURIComponent(booking.conversation_id)}`;
            const context = el("span", ` for ${participant}'s trial booking`, "kw-visually-hidden");
            const arrow = el("span", " →"); arrow.setAttribute("aria-hidden", "true");
            link.append(context, arrow);
            item.append(head, line, link);
            return item;
        }
        async function load() {
            const data = await api("/catalog");
            options($("tuition-class-form").elements.course_id, data.courses, "Choose a course");
            options($("tuition-session-form").elements.class_id, data.classes, "Choose a class");
            $("tuition-sessions").replaceChildren(...data.sessions.map(sessionForm));
            if (!data.sessions.length) $("tuition-sessions").append(el("p", "No upcoming sessions. Add a course, class and session to offer trial lessons.", "kw-help"));
            const bookings = el("ul", null, "tuition-list");
            bookings.append(...data.bookings.map(booking => bookingItem(booking, data.sessions)));
            $("tuition-bookings").replaceChildren(...(data.bookings.length ? [bookings] : [el("p", "No trial bookings recorded.", "kw-help")]));
        }
        function capacities(form) {
            return Object.fromEntries(["total_capacity", "enrolled_seats", "trial_limit"].map(name => [name, Number(form.elements[name].value)]));
        }
        function restoreFocus(active, sessionId, name) {
            // Saving disables the buttons and reloading replaces the session forms; keep focus inside the dialog.
            if (!dialog.open) return;
            if (active && active.isConnected && dialog.contains(active) && !active.disabled) { active.focus(); return; }
            const form = sessionId ? $("tuition-sessions").querySelector(`[data-session-id="${CSS.escape(sessionId)}"]`) : null;
            const target = form && (name && form.elements[name] instanceof HTMLElement ? form.elements[name] : form.querySelector("button[type=submit]"));
            (target || $("tuition-status")).focus();
        }
        async function mutate(form, path, body, message) {
            if (busy || !form.reportValidity()) return;
            const active = document.activeElement;
            const sessionId = active?.closest?.("[data-session-id]")?.dataset.sessionId;
            const name = active?.name;
            busy = true; dialog.querySelectorAll("button[type=submit]").forEach(button => { button.disabled = true; });
            status("Saving…");
            try {
                await api(path, body);
                if (path === "/catalog") form.reset();
                status(message);
                try { await load(); } catch (_) { status(message + " Refresh to load the latest list."); }
            } catch (error) { status(error.message + " Nothing in the form was discarded. Refresh if another administrator changed this session.", true); }
            finally {
                busy = false; dialog.querySelectorAll("button[type=submit]").forEach(button => { button.disabled = false; });
                restoreFocus(active, sessionId, name);
            }
        }
        for (const kind of ["course", "class", "session"]) {
            const form = $(`tuition-${kind}-form`);
            form.addEventListener("submit", event => {
                event.preventDefault();
                let body;
                if (kind === "session") body = {kind, class_id: form.elements.class_id.value, starts_at: form.elements.starts_at.value + ":00+08:00", ends_at: form.elements.ends_at.value + ":00+08:00", ...capacities(form)};
                else body = {kind, name: form.elements.name.value.trim(), ...(kind === "class" ? {course_id: form.elements.course_id.value} : {})};
                mutate(form, "/catalog", body, `${kind[0].toUpperCase() + kind.slice(1)} added.`);
            });
        }
        async function refresh() {
            const active = document.activeElement;
            const sessionId = active?.closest?.("[data-session-id]")?.dataset.sessionId;
            status("Loading trial lessons…");
            try { await load(); status("Trial lessons are up to date."); } catch (error) { status(error.message, true); }
            if (sessionId) restoreFocus(active, sessionId, active.name);
        }
        entry.addEventListener("click", () => { dialog.showModal(); refresh(); });
        $("close-tuition").addEventListener("click", () => dialog.close());
        $("refresh-trials").addEventListener("click", refresh);
    }};
})();
