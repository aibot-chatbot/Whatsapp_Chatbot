(function () {
    "use strict";
    const $ = id => document.getElementById(id);
    const time = value => new Date(value).toLocaleString("en-MY", {timeZone: "Asia/Kuala_Lumpur"});
    function el(tag, text) { const node = document.createElement(tag); if (text != null) node.textContent = text; return node; }
    window.AnalysisTuition = {init(botId, industry) {
        if (industry?.template_id !== "tuition_center" || !industry.confirmed_at) return;
        const entry = $("manage-trials"), dialog = $("tuition-dialog");
        if (entry.dataset.ready) return;
        entry.dataset.ready = "true";
        entry.hidden = false;
        const base = `/api/tuition/bots/${botId}`;
        let busy = false;
        function status(message, error = false) { $("tuition-status").textContent = message; $("tuition-status").dataset.error = String(error); }
        async function api(path, body) {
            const response = await authenticatedFetch(base + path, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
            const result = await response.json();
            if (!response.ok) throw new Error(result.message || "Trial management is unavailable.");
            return result.data;
        }
        function options(select, rows, empty) {
            const previous = select.value;
            select.replaceChildren(new Option(empty, ""));
            for (const row of rows) select.add(new Option(row.name, row.id));
            if (rows.some(row => row.id === previous)) select.value = previous;
        }
        async function load() {
            const data = await api("/catalog");
            options($("tuition-class-form").elements.course_id, data.courses, "Choose a course");
            options($("tuition-session-form").elements.class_id, data.classes, "Choose a class");
            $("tuition-sessions").replaceChildren();
            for (const session of data.sessions) {
                const form = el("form"); form.className = "tuition-session";
                form.append(el("h4", `${session.course_name} · ${session.class_name}`), el("p", `${time(session.starts_at)} – ${time(session.ends_at)} · ${session.available_trial_seats} trial places available`));
                const fields = el("div"); fields.className = "tuition-fields";
                for (const [name, label, minimum] of [["total_capacity", "Total capacity", 1], ["enrolled_seats", "Enrolled seats", 0], ["trial_limit", "Trial limit", 0]]) {
                    const wrapper = el("label", label), input = el("input");
                    Object.assign(input, {name, type: "number", min: minimum, max: 10000, step: 1, required: true, value: session[name]});
                    wrapper.append(input); fields.append(wrapper);
                }
                const save = el("button", "Save capacity"); save.type = "submit";
                form.append(fields, save);
                form.addEventListener("submit", event => {
                    event.preventDefault();
                    mutate(form, `/sessions/${encodeURIComponent(session.id)}/capacity`, {expected_version: session.version, ...capacities(form)}, "Capacity updated.");
                });
                $("tuition-sessions").append(form);
            }
            if (!data.sessions.length) $("tuition-sessions").append(el("p", "No upcoming sessions. Add a course, class and session to offer trials."));
            $("tuition-bookings").replaceChildren();
            for (const booking of data.bookings) {
                const article = el("article"); article.className = "analysis-record";
                const session = data.sessions.find(row => row.id === booking.session_id);
                article.append(el("strong", booking.participant_label || "Participant"), el("p", `${booking.status} · ${session ? time(session.starts_at) : "Session " + booking.session_id}`), el("p", "Booking " + booking.id));
                const link = el("a", "Open conversation →");
                link.href = `conversations.html?bot_id=${botId}&conversation_id=${encodeURIComponent(booking.conversation_id)}`;
                article.append(link); $("tuition-bookings").append(article);
            }
            if (!data.bookings.length) $("tuition-bookings").append(el("p", "No trial bookings recorded."));
        }
        function capacities(form) {
            return Object.fromEntries(["total_capacity", "enrolled_seats", "trial_limit"].map(name => [name, Number(form.elements[name].value)]));
        }
        async function mutate(form, path, body, message) {
            if (busy || !form.reportValidity()) return;
            busy = true; dialog.querySelectorAll("button[type=submit]").forEach(button => { button.disabled = true; });
            status("Saving…");
            try {
                await api(path, body);
                if (path === "/catalog") form.reset();
                status(message);
                try { await load(); } catch (_) { status(message + " Refresh to load the latest list."); }
            } catch (error) { status(error.message + " Nothing in the form was discarded. Refresh if another administrator changed this session.", true); }
            finally { busy = false; dialog.querySelectorAll("button[type=submit]").forEach(button => { button.disabled = false; }); }
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
        async function refresh() { status("Loading trials…"); try { await load(); status("Trial records are up to date."); } catch (error) { status(error.message, true); } }
        entry.addEventListener("click", () => { dialog.showModal(); refresh(); });
        $("close-tuition").addEventListener("click", () => dialog.close());
        $("refresh-trials").addEventListener("click", refresh);
    }};
})();
