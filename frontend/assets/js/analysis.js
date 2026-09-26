(function () {
    "use strict";
    // The <head> already redirects visitors who are not signed in as an owner or admin;
    // stop here too so a redirecting page never calls the analysis API.
    try { if (!["owner", "admin"].includes(JSON.parse(sessionStorage.getItem("user") || "{}").role)) return; }
    catch (_) { return; }
    const botId = parsePositiveSafeInteger(new URLSearchParams(location.search).get("bot_id") || sessionStorage.getItem("selectedBotId"));
    if (!botId) { location.replace("bots.html"); return; }

    const $ = id => document.getElementById(id);
    const base = `/api/chatbots/${botId}/analysis`;
    const POLL_MS = 10000, HIDDEN_POLL_MS = 30000, MAX_FAILURES = 3, MAX_TEXT = 2000;
    const TIME_ZONE = "Asia/Kuala_Lumpur";
    const CONNECTED = "Connected to this bot's business records.";
    const UPGRADE_MESSAGE = "This feature needs the Pro plan.";
    const REQUEST_HINT = "Say the time period and the topic.";
    const FINAL = new Set(["complete", "partial", "needs_input", "needs_review", "failed"]);
    const ACTIVE = new Set(["queued", "running"]);
    const STATES = {
        queued: {label: "Waiting to start", tone: "review"},
        running: {label: "Writing your report…", tone: "ready", busy: true},
        complete: {label: "Report ready", tone: "ready"},
        partial: {label: "Ready, with gaps", tone: "review", hint: "Some information was missing; see the report."},
        failed: {label: "Could not finish", tone: "off", hint: "Send a new request."},
        needs_review: {label: "On hold for checking", tone: "review", hint: "We check it first so you are never charged twice."},
        needs_input: {label: "Needs more detail", tone: "review", hint: "Send a new request with the period and topic."},
    };
    const UNKNOWN_STATE = {label: "Status unavailable", tone: "off"};
    const ANNOUNCE = {
        complete: "Your report is ready.",
        partial: "Your report is ready, with gaps. Open it to see what was missing.",
        failed: "A report could not finish. Send a new request.",
        needs_review: "A report is on hold for checking.",
        needs_input: "A report needs more detail. Send a new request with the period and topic.",
    };
    const INDUSTRIES = {restaurant: "Restaurant", clinic: "Clinic", tuition_center: "Tuition centre", general: "General business"};
    const ACTIONS = {booking: "Booking", registration: "Registration", order: "Order", service_request: "Service request"};
    const RECORD_STATES = {intent: "Interested", requested: "Requested", confirmed: "Confirmed", completed: "Done", failed: "Didn't go through", cancelled: "Cancelled", rescheduled: "Moved to a new time"};
    // Schedules: the owner picks the day and time (Malaysia time, 15-minute steps); periods roll back from each run.
    const FREQUENCIES = ["weekly", "monthly"];
    const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    const SCHEDULE_OFF = {weekly: "Off — covers the 7 days before each report", monthly: "Off — covers the month before each report"};
    const CHOOSE_FIRST = "Choose a day and time first.";
    const PICKER_SAVE_MS = 400;
    const NEXT_RUN = new Intl.DateTimeFormat("en-GB", {weekday: "long", day: "numeric", month: "numeric", hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kuala_Lumpur"});
    const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    // JSON stays an API format; owners get PDF and Excel.
    const DOWNLOADS = [["pdf", "Download PDF"], ["xlsx", "Download Excel"]];
    const SVG = "http://www.w3.org/2000/svg";

    const reports = new Map(), reportViews = new Map();
    let records = [];
    let reportCursor = null, recordCursor = null, timer = null, stopped = false, failures = 0;
    let sending = false, requestKey = null, ready = false, contextChecked = false, automationEnabled = false;
    let lastStatus = "", retryParked = false;

    function el(tag, text, className) {
        const node = document.createElement(tag);
        if (text != null) node.textContent = String(text);
        if (className) node.className = className;
        return node;
    }
    function button(text, handler, className = "kw-btn cr-press") {
        const node = el("button", text, className); node.type = "button"; node.addEventListener("click", handler); return node;
    }
    function hidden(text) { return el("span", text, "kw-visually-hidden"); }
    function setText(node, text) { if (node.textContent !== text) node.textContent = text; }
    function isObject(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
    function humanize(value) {
        const text = String(value || "").replaceAll("_", " ").trim();
        return text ? text[0].toUpperCase() + text.slice(1) : "";
    }
    function formatDate(value) {
        if (!value) return "";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short", timeZone: TIME_ZONE});
    }
    function chatLink(conversationId, context) {
        // Same destination as the rest of the app; the hidden text tells screen readers which chat.
        const link = el("a", "Open chat", "analysis-chat-link");
        link.href = `conversations.html?bot_id=${botId}&conversation_id=${encodeURIComponent(conversationId)}`;
        const arrow = el("span", " →"); arrow.setAttribute("aria-hidden", "true");
        link.append(hidden(` ${context}`), arrow);
        return link;
    }
    function chevron() {
        const svg = document.createElementNS(SVG, "svg");
        svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
        svg.setAttribute("class", "dashboard-icon kw-advanced-chevron");
        const path = document.createElementNS(SVG, "path"); path.setAttribute("d", "m6 9 6 6 6-6");
        svg.append(path);
        return svg;
    }
    function focusable(node) { return node && node.isConnected && !node.disabled && !node.closest("[hidden]"); }

    // ── Status line: the page's live region ────────────────────────────
    function status(message, {error = false, upgrade = false, retry = false, force = false} = {}) {
        const live = ready && !error && failures === 0;
        const key = [message, error, upgrade, retry, live].join("|");
        // An unchanged message is not re-announced, unless a new action produced it (force).
        if (key === lastStatus && !force) return;
        lastStatus = key;
        const node = $("analysis-status"), line = $("analysis-statusline"), retryButton = $("analysis-retry");
        node.textContent = message; node.dataset.error = String(error);
        if (upgrade) { const link = el("a", "See plans"); link.href = "pricing.html"; node.append(" ", link); }
        line.className = "analysis-statusline " + (upgrade ? "kw-banner" : error ? "kw-banner kw-banner-error" : "kw-help");
        line.querySelector(".cr-live-dot").className = `cr-live-dot ${live ? "is-live" : "is-idle"}`;
        // Hiding a focused Try again would drop keyboard focus to <body>: park it on the line, then give it back.
        const parking = !retry && document.activeElement === retryButton;
        retryButton.hidden = !retry;
        if (parking) { retryParked = true; line.focus(); }
        else if (retry && retryParked && document.activeElement === line) { retryParked = false; retryButton.focus(); }
    }
    function dialogStatus(message, error = false) {
        const node = $("report-dialog-status");
        node.textContent = message;
        node.className = `${error ? "kw-banner kw-banner-error" : "kw-help"} analysis-dialog-status`;
    }
    function notify(message, options = {}) {
        // While the report is open the rest of the page is inert, so its live region is silent: speak inside the dialog.
        status(message, options);
        if ($("report-dialog").open) dialogStatus(message, Boolean(options.error));
    }
    function showError(error, retry = false) {
        const upgrade = error.code === "feature_not_available";
        status(error.message, {error: true, upgrade, retry: retry && !upgrade});
    }
    function requestError(response, body, fallback) {
        // Plan denials get a friendly upgrade prompt, never the raw server feature key.
        const upgrade = response.status === 403 && body?.code === "feature_not_available";
        const error = new Error(upgrade ? UPGRADE_MESSAGE : (typeof body?.message === "string" && body.message) || fallback);
        error.code = upgrade ? "feature_not_available" : body?.code;
        return error;
    }
    async function api(path, options = {}) {
        const response = await authenticatedFetch(base + path, options);
        let body;
        try { body = await response.json(); } catch (_) { throw new Error("Analysis is temporarily unavailable."); }
        if (!response.ok) throw requestError(response, body, "Analysis request failed.");
        return body;
    }
    async function planFeatures() {
        // Fail closed: an unverifiable plan keeps Pro-only automation locked; the server still enforces it.
        try {
            const response = await authenticatedFetch("/api/billing/subscription");
            const body = await response.json();
            const flags = body?.data?.plan?.feature_flags;
            return response.ok && body.status === "success" && isObject(flags) ? flags : {};
        } catch (_) { return {}; }
    }
    function setGenerate(enabled, reason = "") {
        $("send-report").disabled = !enabled;
        setText($("send-reason"), enabled ? "" : reason);
    }

    // ── C. Your reports: rows are keyed by id and updated in place ─────
    function paintPill(node, key, state) {
        if (node.dataset.state === key) return;
        node.dataset.state = key;
        node.className = `kw-pill kw-pill-${state.tone}`;
        const mark = state.busy ? el("span", null, "kw-spinner") : el("span", null, `kw-dot kw-dot-${state.tone}`);
        mark.setAttribute("aria-hidden", "true");
        node.replaceChildren(mark, el("span", state.label));
    }
    function reportView(row) {
        const item = el("li", null, "analysis-report"); item.dataset.reportId = row.id;
        const main = el("div", null, "analysis-report-main");
        const text = el("p", null, "analysis-report-text"); text.id = `report-request-${row.id}`;
        const meta = el("p", null, "analysis-report-meta");
        const pill = el("span"), time = el("time", null, "kw-mono");
        meta.append(pill, time);
        const hint = el("p", null, "kw-help analysis-report-hint");
        main.append(text, meta, hint);
        const open = button("View details", () => openReport(row.id));
        open.setAttribute("aria-describedby", text.id);
        item.append(main, open);
        return {item, text, pill, time, hint, open};
    }
    function paintReport(view, row) {
        const state = STATES[row.status] || UNKNOWN_STATE;
        setText(view.text, row.request_text || "Report request");
        view.text.title = row.request_text || "";
        setText(view.time, formatDate(row.created_at)); view.time.dateTime = row.created_at || "";
        paintPill(view.pill, String(row.status), state);
        setText(view.hint, state.hint || ""); view.hint.hidden = !state.hint;
        view.open.hidden = !FINAL.has(row.status);
    }
    function newestFirst(a, b) {
        return String(b.created_at || "").localeCompare(String(a.created_at || "")) || String(b.id).localeCompare(String(a.id));
    }
    function renderReports() {
        const list = $("report-thread");
        list.querySelectorAll(".analysis-report-skeleton, .analysis-report-note").forEach(node => node.remove());
        list.removeAttribute("aria-busy");
        const rows = [...reports.values()].sort(newestFirst);
        list.hidden = !rows.length; $("reports-empty").hidden = rows.length > 0;
        rows.forEach((row, index) => {
            let view = reportViews.get(row.id);
            if (!view) { view = reportView(row); reportViews.set(row.id, view); }
            paintReport(view, row);
            // Only rows that are out of place move, so a focused "View details" is never detached.
            if (list.children[index] !== view.item) list.insertBefore(view.item, list.children[index] || null);
        });
    }
    function reportsUnavailable() {
        const list = $("report-thread");
        if (reports.size) return;  // keep the last good list
        list.querySelectorAll(".analysis-report-skeleton").forEach(node => node.remove());
        list.removeAttribute("aria-busy");
        if (!list.querySelector(".analysis-report-note")) list.append(el("li", "Your reports can't be shown right now.", "kw-help analysis-report-note"));
    }
    function merge(rows, {authoritative = false, announceNew = false} = {}) {
        for (const row of rows) {
            if (!isObject(row) || row.id == null) continue;
            const previous = reports.get(row.id);
            // A slower list response must never pull a finished report back to "waiting".
            if (!authoritative && previous && FINAL.has(previous.status) && !FINAL.has(row.status)) continue;
            if (previous && !FINAL.has(previous.status) && FINAL.has(row.status)) {
                notify(ANNOUNCE[row.status]);
                if (document.hidden) document.title = "(1) Analysis | Omnexa";
            } else if (!previous && announceNew && FINAL.has(row.status)) {
                // A scheduled report can arrive already finished; say so once.
                notify(`New report ready: ${row.request_text || "scheduled report"}`);
                if (document.hidden) document.title = "(1) Analysis | Omnexa";
            }
            reports.set(row.id, {...previous, ...row});
        }
        renderReports();
    }
    async function loadReports(earlier = false, options = {}) {
        const body = await api("/messages" + (earlier && reportCursor ? `?before_id=${encodeURIComponent(reportCursor)}` : ""));
        merge(Array.isArray(body.data) ? body.data : [], options);
        if (earlier || !reportCursor) reportCursor = body.next_cursor || null;
        $("more-reports").hidden = !reportCursor;
    }
    function focusReport(id) {
        const view = reportViews.get(id);
        if (!view) return false;
        if (view.open.hidden) { view.text.tabIndex = -1; view.text.focus(); } else view.open.focus();
        return true;
    }

    // ── D. What customers asked for ────────────────────────────────────
    function recordItem(row) {
        const item = el("li", null, "kw-log"); item.dataset.recordId = String(row.id);
        const head = el("div", null, "kw-log-head");
        const action = ACTIONS[row.action_type] || humanize(row.action_type) || "Customer request";
        const when = formatDate(row.created_at);
        const time = el("time", when, "kw-log-time"); time.dateTime = row.created_at || "";
        head.append(el("span", action, "kw-log-cat"), time);
        const line = el("div", null, "kw-log-action analysis-record-line");
        line.append(el("span", RECORD_STATES[row.status] || humanize(row.status) || "Status unavailable"));
        if (row.conversation_id) line.append(chatLink(row.conversation_id, `for ${action.toLowerCase()}${when ? ", " + when : ""}`));
        item.append(head, line);
        return item;
    }
    function recordGroup(title, rows, note) {
        const group = el("section", null, "analysis-record-group");
        group.append(el("h3", title, "kw-subhead"));
        if (note) group.append(el("p", note, "kw-help"));
        const list = el("ul", null, "analysis-record-list");
        list.append(...rows.map(recordItem));
        group.append(list);
        return group;
    }
    function renderRecords() {
        const container = $("business-records");
        container.removeAttribute("aria-busy");
        if (!records.length) {
            container.replaceChildren(el("p", "Nothing recorded yet. Requests your bot spots in chats, and bookings your system confirms, appear here.", "kw-help"));
            return;
        }
        // Only the business's own system can confirm; anything else is an observation, never a booking.
        const groups = [
            ["Confirmed by your system", records.filter(row => row.source === "business_service"), null],
            ["Noticed in chats — not confirmed yet", records.filter(row => row.source !== "business_service"), "A request does not reserve a place."],
        ];
        container.replaceChildren(...groups.filter(([, rows]) => rows.length).map(([title, rows, note]) => recordGroup(title, rows, note)));
    }
    async function loadRecords(more = false) {
        const body = await api(`/records?after_id=${more && recordCursor ? recordCursor : 0}`);
        const rows = Array.isArray(body.data) ? body.data.filter(isObject) : [];
        records = more ? [...records, ...rows] : rows;
        recordCursor = body.next_cursor || null;
        renderRecords();
        $("more-records").hidden = !recordCursor;
        return rows;
    }
    function recordsUnavailable() {
        if (records.length) return;  // keep the last good list
        $("business-records").removeAttribute("aria-busy");
        $("business-records").replaceChildren(el("p", "Customer requests could not be loaded. This does not mean there are no requests.", "kw-help"));
    }

    // ── Report dialog ──────────────────────────────────────────────────
    function section(title, ...children) {
        const node = el("section", null, "analysis-section");
        node.append(el("h3", title), ...children);
        return node;
    }
    function disclosure(title, lines) {
        const details = el("details", null, "kw-advanced analysis-disclosure");
        const summary = el("summary"); summary.append(el("span", title), chevron());
        const body = el("div", null, "analysis-disclosure-body");
        body.append(...lines.map(line => line instanceof Node ? line : el("p", line)));
        details.append(summary, body);
        return details;
    }
    function notice(row, result) {
        if (row.status === "needs_input") return section("What we need", el("p", result.clarification || result.question || "Say the report period and what you want to know in a new request.", "kw-banner"));
        if (row.status === "needs_review") return section("On hold", el("p", "The result could not be confirmed, so we are checking it first. You are never charged twice for one report.", "kw-banner"));
        if (row.status === "failed") return section("Could not finish", el("p", "This report could not finish and no completed report is available. Send a new request.", "kw-banner kw-banner-error"));
        return null;
    }
    function summary(result) {
        const prose = el("div", null, "analysis-prose");
        if (typeof result.narrative === "string" && result.narrative.trim()) prose.append(el("p", result.narrative));
        else for (const part of Array.isArray(result.sections) ? result.sections.filter(isObject) : []) {
            prose.append(el("h4", part.title || part.heading || "Analysis"));
            const text = [part.text, part.content, part.body].find(value => typeof value === "string");
            if (text) prose.append(el("p", text));
            for (const point of Array.isArray(part.points) ? part.points : []) prose.append(el("p", point));
        }
        return prose.children.length ? section("Summary", prose) : null;
    }
    function keyNumbers(snapshot) {
        const metrics = Array.isArray(snapshot.metrics) ? snapshot.metrics.filter(isObject) : [];
        if (!metrics.length) return null;
        const grid = el("div", null, "analysis-stats");
        for (const metric of metrics) {
            const tile = el("div", null, "kw-stat");
            const head = el("div", null, "kw-stat-head"); head.append(el("span", metric.label || humanize(metric.key) || "Figure", "kw-stat-label"));
            const known = ["available", "partial"].includes(metric.status) && metric.value != null;
            tile.append(head, el("p", known ? metric.value : "Not available yet", known ? "kw-stat-value" : "kw-stat-value analysis-stat-missing"));
            if (metric.status === "partial") tile.append(el("p", "Based on part of your data", "kw-stat-unit"));
            if (typeof metric.reason === "string") tile.append(el("p", metric.reason, "kw-stat-unit"));
            grid.append(tile);
        }
        return section("Key numbers", grid);
    }
    const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const HOURS = Array.from({length: 24}, (_, hour) => String(hour).padStart(2, "0"));
    function validMatrix(matrix) {
        return Array.isArray(matrix) && matrix.length === 7 && matrix.every(row => Array.isArray(row) && row.length === 24
            && row.every(value => Number.isInteger(value) && value >= 0));
    }
    function heatKey() {
        const key = el("p", null, "analysis-heatmap-key"); key.setAttribute("aria-hidden", "true");
        const ramp = el("span", null, "analysis-heatmap-ramp");
        for (let level = 0; level <= 4; level++) { const swatch = el("span"); swatch.dataset.level = String(level); ramp.append(swatch); }
        key.append(el("span", "Fewer"), ramp, el("span", "More"));
        return key;
    }
    function heatmap(item) {
        // Day x hour counts as a real table: numbers stay readable to screen readers and without colour.
        const label = String(item.label || item.key || "Activity");
        const block = el("div", null, "analysis-heatmap-block");
        const zone = !item.timezone || item.timezone === TIME_ZONE ? "Malaysia time" : String(item.timezone);
        const valid = item.status !== "unavailable" && validMatrix(item.matrix);
        block.append(el("h4", label), el("p", [zone, item.note, valid ? `Total ${item.total ?? 0}` : ""].filter(Boolean).join(" · "), "kw-help"));
        if (!valid) {
            block.append(el("p", "We couldn't read this data, so there's no chart. It doesn't mean there were none.", "kw-help"));
            return block;
        }
        if (item.status === "partial") block.append(el("p", `Some activity could not be counted (${item.unreadable_count || 0}), so real numbers may be higher.`, "kw-help"));
        const max = Math.max(1, ...item.matrix.flat());
        const scroll = el("div", null, "analysis-heatmap-scroll");
        scroll.tabIndex = 0; scroll.setAttribute("role", "region"); scroll.setAttribute("aria-label", `${label}, scrollable table`);
        const table = el("table", null, "analysis-heatmap");
        table.append(el("caption", label, "kw-visually-hidden"));
        const head = el("tr"); head.append(Object.assign(el("th", "Day"), {scope: "col"}));
        for (const hour of HOURS) {
            const cell = Object.assign(el("th"), {scope: "col"});
            const short = el("span", hour); short.setAttribute("aria-hidden", "true");
            cell.append(short, hidden(`${hour}:00`));
            head.append(cell);
        }
        const thead = el("thead"); thead.append(head);
        const tbody = el("tbody");
        item.matrix.forEach((counts, day) => {
            const row = el("tr"); const name = (Array.isArray(item.days) && item.days[day]) || DAYS[day];
            row.append(Object.assign(el("th", name), {scope: "row"}));
            counts.forEach((count, hour) => {
                // Zero cells stay quiet on screen but still read "0" to screen readers.
                const cell = count ? el("td", count) : el("td");
                if (!count) cell.append(hidden("0"));
                cell.dataset.level = String(count ? Math.ceil(count / max * 4) : 0);
                cell.title = `${name} ${HOURS[hour]}:00–${HOURS[hour]}:59 · ${count}`;
                row.append(cell);
            });
            tbody.append(row);
        });
        table.append(thead, tbody); scroll.append(table); block.append(heatKey(), scroll);
        return block;
    }
    function activity(snapshot) {
        const grids = Array.isArray(snapshot.distributions) ? snapshot.distributions.filter(isObject) : [];
        return grids.length ? section("When customers message you", ...grids.map(heatmap)) : null;
    }
    function questionSamples(snapshot) {
        const excerpts = Array.isArray(snapshot.customer_questions?.excerpts) ? snapshot.customer_questions.excerpts.filter(isObject) : [];
        if (!excerpts.length) return null;
        return disclosure("Customer question samples", excerpts.map(sample => {
            const line = el("p", `${sample.text ?? ""} `, "analysis-sample");
            if (sample.conversation_id) line.append(chatLink(sample.conversation_id, "about this question"));
            return line;
        }));
    }
    function documentsUsed(snapshot) {
        const documents = Array.isArray(snapshot.documents) ? snapshot.documents.filter(isObject) : [];
        return documents.length ? disclosure("Documents used", documents.map(doc => `${doc.name} · ${humanize(doc.status)}${doc.truncated ? " · only part of this document was read" : ""}`)) : null;
    }
    function limitations(snapshot, result) {
        const lines = [snapshot.limitations, result.limitations].flatMap(value => Array.isArray(value) ? value : [])
            .filter(line => typeof line === "string" && line.trim());
        return lines.length ? disclosure("What this report could not see", lines) : null;
    }
    function fillReport(row, id) {
        const state = STATES[row.status] || UNKNOWN_STATE;
        setText($("report-request"), row.request_text || "");
        delete $("report-state").dataset.state;
        paintPill($("report-state"), String(row.status), state);
        setText($("report-date"), formatDate(row.created_at)); $("report-date").dateTime = row.created_at || "";
        const result = isObject(row.result) ? row.result : {};
        const snapshot = isObject(row.snapshot) ? row.snapshot : isObject(result.snapshot) ? result.snapshot : {};
        const parts = [notice(row, result), summary(result), keyNumbers(snapshot), activity(snapshot),
            questionSamples(snapshot), documentsUsed(snapshot), limitations(snapshot, result)].filter(Boolean);
        $("report-content").replaceChildren(...(parts.length ? parts : [el("p", "This report has no content yet.", "kw-help")]));
        const formats = Array.isArray(row.formats) ? row.formats : [];
        dialogStatus("");
        $("report-downloads").replaceChildren($("report-dialog-status"), ...DOWNLOADS.filter(([format]) => formats.includes(format))
            .map(([format, label], index) => button(label, () => download(id, format), index ? "kw-btn cr-press" : "kw-btn kw-btn-primary cr-press")));
    }
    async function openReport(id) {
        try {
            const row = (await api(`/reports/${encodeURIComponent(id)}`)).data;
            fillReport(isObject(row) ? row : {}, id);
            $("report-dialog").showModal();
        } catch (error) { showError(error); }
    }
    async function download(id, format) {
        try {
            const response = await authenticatedFetch(`${base}/reports/${encodeURIComponent(id)}/download?format=${encodeURIComponent(format)}`);
            if (!response.ok) { let body = {}; try { body = await response.json(); } catch (_) { /* non-JSON error body */ } throw requestError(response, body, "Download is unavailable."); }
            const url = URL.createObjectURL(await response.blob());
            const link = el("a"); link.href = url; link.download = `report-${id}.${format}`; link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (error) {
            if ($("report-dialog").open) dialogStatus(error.message, true);
            else showError(error);
        }
    }

    // ── Polling ────────────────────────────────────────────────────────
    function schedulePoll() {
        clearTimeout(timer);
        if (!ready || stopped || failures >= MAX_FAILURES) return;
        timer = setTimeout(poll, document.hidden ? HIDDEN_POLL_MS : POLL_MS);
    }
    async function poll() {
        try {
            const active = [...reports.values()].filter(row => ACTIVE.has(row.status));
            for (const row of active) merge([(await api(`/reports/${encodeURIComponent(row.id)}`)).data]);
            const recovered = failures > 0;
            failures = 0;
            await loadReports(false, {announceNew: true});
            if (recovered) notify(CONNECTED);
        } catch (error) {
            failures++;
            if (failures >= MAX_FAILURES) notify("Updates paused. Refresh the page to reconnect.", {error: true, retry: true});
            else notify(`${error.message} Reconnecting…`, {error: true, retry: true});
        }
        schedulePoll();
    }
    async function retry() {
        if (!ready) return initialize();
        failures = 0;
        status("Reconnecting…");
        try { await loadReports(false, {announceNew: true}); await loadRecords(); status(CONNECTED); }
        catch (error) { showError(error, true); }
        schedulePoll();
    }

    // ── B. Ask for a report ────────────────────────────────────────────
    function updateCount() { setText($("report-count"), `${$("report-command").value.length} / ${MAX_TEXT}`); }
    function requestHint(message = REQUEST_HINT) {
        const invalid = message !== REQUEST_HINT;
        setText($("report-hint"), message);
        $("report-hint").classList.toggle("analysis-hint-error", invalid);
        if (invalid) $("report-command").setAttribute("aria-invalid", "true");
        else $("report-command").removeAttribute("aria-invalid");
    }
    $("report-form").addEventListener("submit", async event => {
        event.preventDefault();
        if (sending || !ready) return;
        const text = $("report-command").value.trim();
        if (!text) { requestHint("Type what you want to know first."); $("report-command").focus(); return; }
        const hadFocus = document.activeElement === $("send-report");
        sending = true; setGenerate(false, "Sending…");
        requestKey ||= crypto.randomUUID();
        try {
            const body = await api("/messages", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text, client_message_id: requestKey})});
            merge([body.data], {authoritative: true}); requestKey = null; $("report-command").value = ""; updateCount(); failures = 0;
            status("Request saved. You can leave this page while the report is written."); schedulePoll();
        } catch (error) { showError(error); }
        finally {
            sending = false; setGenerate(ready, "Loading this bot…");
            if (hadFocus && focusable($("send-report"))) $("send-report").focus();
        }
    });
    $("report-command").addEventListener("input", () => { if (!sending) requestKey = null; updateCount(); requestHint(); });
    document.querySelectorAll("[data-prompt]").forEach(node => node.addEventListener("click", () => {
        $("report-command").value = node.dataset.prompt; requestKey = null; updateCount(); requestHint(); $("report-command").focus();
    }));

    // ── D/E. Pro-only automation toggles ───────────────────────────────
    const scheduleToggles = () => [...document.querySelectorAll("[data-frequency]")];
    const automationToggles = () => [...scheduleToggles(), $("recording-enabled")];
    const picker = (frequency, part) => $(`schedule-${frequency}-${part}`);
    const pickers = () => FREQUENCIES.flatMap(frequency => [picker(frequency, "day"), picker(frequency, "time")]);
    const savedSchedules = {weekly: {frequency: "weekly", enabled: false}, monthly: {frequency: "monthly", enabled: false}};
    // One save queue per schedule, so switch and picker saves reach the server in the order the owner made them.
    // switchChanges counts switch flips: a save that returns after a newer flip must not repaint the switch.
    const pickerTimers = {}, scheduleSaves = {}, switchChanges = {weekly: 0, monthly: 0};
    function queueSave(frequency, task) {
        scheduleSaves[frequency] = (scheduleSaves[frequency] || Promise.resolve()).then(task).catch(() => undefined);
    }
    function ordinal(day) {
        const teen = day % 100 >= 11 && day % 100 <= 13;
        return `${day}${teen ? "th" : {1: "st", 2: "nd", 3: "rd"}[day % 10] || "th"}`;
    }
    function timeLabel(value) {
        const [hour, minute] = value.split(":").map(Number);
        return `${hour % 12 || 12}:${String(minute).padStart(2, "0")} ${hour < 12 ? "am" : "pm"}`;
    }
    function formatNextRun(value) {
        const date = value ? new Date(value) : null;
        if (!date || Number.isNaN(date.getTime())) return "";
        // Built from parts so the wording never depends on a browser's locale punctuation.
        const part = Object.fromEntries(NEXT_RUN.formatToParts(date).map(({type, value: text}) => [type, text]));
        return `${part.weekday} ${Number(part.day)} ${MONTHS[Number(part.month) - 1]}, ${Number(part.hour)}:${part.minute} ${String(part.dayPeriod).toLowerCase()}`;
    }
    function buildPickers() {
        const times = Array.from({length: 96}, (_, step) => `${String(Math.floor(step / 4)).padStart(2, "0")}:${String(step % 4 * 15).padStart(2, "0")}`);
        const days = {
            weekly: WEEKDAYS.map((name, index) => [String(index), name]),
            monthly: [...Array.from({length: 28}, (_, index) => [String(index + 1), ordinal(index + 1)]), ["last", "Last day of the month"]],
        };
        for (const frequency of FREQUENCIES) {
            picker(frequency, "day").append(...days[frequency].map(([value, label]) => new Option(label, value)));
            picker(frequency, "time").append(...times.map(value => new Option(timeLabel(value), value)));
        }
    }
    function setPicker(select, value) {
        // A stored value outside the list is shown as-is rather than silently replaced by the placeholder.
        if (value && ![...select.options].some(option => option.value === value)) {
            select.append(new Option(select.dataset.schedulePart === "time" ? timeLabel(value) : value, value));
        }
        select.value = value;
    }
    function scheduleSummary(frequency) {
        const day = picker(frequency, "day").value, time = picker(frequency, "time").value;
        if (!day || !time) return "On";
        const when = frequency === "weekly" ? `every ${WEEKDAYS[Number(day)]}`
            : day === "last" ? "on the last day of each month" : `on the ${ordinal(Number(day))} of each month`;
        return `On — ${when}, ${timeLabel(time)}`;
    }
    function paintSchedule(frequency, message = "", {error = true} = {}) {
        const help = $(`schedule-${frequency}-help`);
        const next = formatNextRun(savedSchedules[frequency].next_due_at);
        const text = message || (!$(`schedule-${frequency}`).checked ? SCHEDULE_OFF[frequency]
            : next ? `On — next report ${next}` : scheduleSummary(frequency));
        setText(help, text);
        help.classList.toggle("analysis-hint-error", Boolean(message) && error);
    }
    function rememberSchedule(frequency, row, {syncPickers = false} = {}) {
        savedSchedules[frequency] = {...savedSchedules[frequency], ...row, frequency};
        const saved = savedSchedules[frequency];
        $(`schedule-${frequency}`).checked = saved.enabled === true;
        if (syncPickers) {
            const day = frequency === "weekly" ? saved.run_weekday : saved.run_day;
            setPicker(picker(frequency, "day"), day == null ? "" : String(day));
            setPicker(picker(frequency, "time"), typeof saved.run_time === "string" ? saved.run_time : "");
        }
        paintSchedule(frequency);
    }
    function storeSchedule(frequency, row, change) {
        // A reply from before the owner's latest switch flip updates what is saved, never what the switch shows.
        if (change === switchChanges[frequency]) rememberSchedule(frequency, row);
        else savedSchedules[frequency] = {...savedSchedules[frequency], ...row, frequency};
    }
    const choicesMade = frequency => Boolean(picker(frequency, "day").value && picker(frequency, "time").value);
    function scheduleBody(frequency, enabled) {
        // Switching off sends no day or time: the server keeps the stored choice.
        if (!enabled) return {frequency, enabled};
        // An empty picker is never turned into a number: Number("") would silently mean Monday.
        const day = picker(frequency, "day").value, time = picker(frequency, "time").value;
        const dayValue = day === "" ? null : day === "last" ? "last" : Number(day);
        const dayField = frequency === "weekly" ? {run_weekday: dayValue} : {run_day: dayValue};
        return {frequency, enabled, ...dayField, run_time: time === "" ? null : time};
    }
    function matchesSaved(frequency, body) {
        const saved = savedSchedules[frequency];
        const dayKey = frequency === "weekly" ? "run_weekday" : "run_day";
        return saved.enabled === true && saved[dayKey] === body[dayKey] && saved.run_time === body.run_time;
    }
    function lockFocus(node) {
        // A control that just locked cannot hold focus; the upgrade link beside it is the next useful stop.
        const lockLink = $(node.dataset.lock || "schedule-plan-lock").querySelector("a");
        [node, lockLink, $("analysis-statusline")].find(focusable)?.focus();
    }
    function applyAutomation(enabled) {
        // Locked automation stays visible with an upgrade note that joins each control's description while it applies.
        automationEnabled = enabled;
        document.querySelectorAll("[data-plan-lock]").forEach(node => { node.hidden = enabled; });
        for (const node of automationToggles()) {
            // The lock blocks turning automation ON only; a downgraded tenant must still be able to switch it OFF.
            node.disabled = !enabled && !node.checked;
            node.setAttribute("aria-describedby", enabled ? `${node.id}-help` : `${node.id}-help ${node.dataset.lock}`);
        }
        for (const select of pickers()) {
            // Changing a day or time re-saves an active schedule, which the plan no longer allows.
            select.disabled = !enabled;
            const help = select.getAttribute("aria-describedby").split(" ")[0];
            select.setAttribute("aria-describedby", enabled ? help : `${help} schedule-plan-lock`);
        }
    }
    async function saveAutomation(node, path, body, message, onSaved) {
        const hadFocus = document.activeElement === node;
        const frequency = node.dataset.frequency;
        node.disabled = true;
        try {
            const response = await api(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
            onSaved?.(response.data);
            status(message, {force: true});
        } catch (error) {
            // Show what is actually saved, not the opposite of what was clicked.
            node.checked = frequency ? savedSchedules[frequency].enabled === true : !node.checked;
            showError(error);
            const planDenied = error.code === "feature_not_available";
            if (planDenied) applyAutomation(false);
            if (frequency) paintSchedule(frequency, planDenied ? "" : error.message);
        } finally {
            node.disabled = !automationEnabled && !node.checked;
            if (hadFocus) lockFocus(node);
        }
    }
    function toggleSchedule(node) {
        const frequency = node.dataset.frequency;
        // The switch supersedes a day/time change still waiting to save.
        clearTimeout(pickerTimers[frequency]);
        if (node.checked && !choicesMade(frequency)) {
            // Blocked here, before any request: the schedule needs both a day and a time.
            const missing = [picker(frequency, "day"), picker(frequency, "time")].find(select => !select.value);
            node.checked = false;
            paintSchedule(frequency, CHOOSE_FIRST);
            (focusable(missing) ? missing : node).focus();
            return;
        }
        const change = ++switchChanges[frequency];
        const body = scheduleBody(frequency, node.checked);
        const message = node.checked ? "Schedule enabled." : "Schedule paused.";
        // Queued behind any day/time save already in flight, so the server never sees off-then-on.
        queueSave(frequency, () => saveAutomation(node, "/schedules", body, message,
            data => storeSchedule(frequency, {...body, ...(isObject(data) ? data : {})}, change)));
    }
    async function savePickers(frequency) {
        // The owner may have switched the schedule off, or left a picker empty, since the change.
        if (!$(`schedule-${frequency}`).checked) return;
        if (!choicesMade(frequency)) { paintSchedule(frequency, CHOOSE_FIRST); return; }
        const body = scheduleBody(frequency, true);
        // Changed and changed back: re-saving would only risk dropping a due period.
        if (matchesSaved(frequency, body)) { paintSchedule(frequency); return; }
        const change = switchChanges[frequency];
        const focused = document.activeElement;
        try {
            const data = (await api("/schedules", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})).data;
            storeSchedule(frequency, {...body, ...(isObject(data) ? data : {})}, change);
            if (change !== switchChanges[frequency]) return;  // the switch changed meanwhile; its own save reports
            const next = formatNextRun(savedSchedules[frequency].next_due_at);
            status(next ? `Schedule updated. Next report ${next}.` : "Schedule updated.", {force: true});
        } catch (error) {
            if (change !== switchChanges[frequency]) return;
            // Put the pickers back to what is saved and say why in the row.
            rememberSchedule(frequency, {}, {syncPickers: true});
            showError(error);
            if (error.code === "feature_not_available") { applyAutomation(false); if (pickers().includes(focused)) lockFocus(focused); }
            else paintSchedule(frequency, error.message);
        }
    }
    function pickerChanged(frequency) {
        clearTimeout(pickerTimers[frequency]);
        if (!$(`schedule-${frequency}`).checked) { paintSchedule(frequency); return; }  // saved with the switch when it is turned on
        if (!choicesMade(frequency)) { paintSchedule(frequency, CHOOSE_FIRST); return; }
        paintSchedule(frequency, "Saving…", {error: false});
        // Arrow keys on a closed select fire one change per step: wait for the owner to settle, then save in order.
        pickerTimers[frequency] = setTimeout(() => queueSave(frequency, () => savePickers(frequency)), PICKER_SAVE_MS);
    }
    buildPickers();
    scheduleToggles().forEach(node => node.addEventListener("change", () => toggleSchedule(node)));
    for (const frequency of FREQUENCIES) {
        for (const select of [picker(frequency, "day"), picker(frequency, "time")]) select.addEventListener("change", () => pickerChanged(frequency));
    }
    $("recording-enabled").addEventListener("change", event => saveAutomation(event.target, "/recording", {enabled: event.target.checked},
        event.target.checked ? "Your bot will spot requests in new chats. AI credit usage applies." : "Spotting requests in new chats is off."));
    async function loadAutomation() {
        let automation = (await planFeatures()).automation_workflows === true;
        try {
            const recording = (await api("/recording")).data;
            $("recording-enabled").checked = isObject(recording) && recording.enabled === true;
            const schedules = (await api("/schedules")).data;
            for (const frequency of FREQUENCIES) {
                const row = Array.isArray(schedules) ? schedules.find(item => isObject(item) && item.frequency === frequency) : null;
                rememberSchedule(frequency, row || {enabled: false}, {syncPickers: true});
            }
        } catch (error) {
            // A plan denial on automation settings must not take the reports page down with it.
            if (error.code !== "feature_not_available") throw error;
            automation = false;
        }
        applyAutomation(automation);
    }

    // ── A. Bot context and page states ─────────────────────────────────
    function paintBot(data) {
        const bot = isObject(data.bot) ? data.bot : {};
        $("bot-context").textContent = bot.bot_name || `Bot #${botId}`;
        document.querySelector("chatbot-sidebar")?.setBotName?.(bot.bot_name);
        const industry = isObject(data.industry) ? data.industry : {};
        const confirmed = Boolean(industry.template_id && industry.confirmed_at);
        document.querySelector(".analysis-botcard").classList.toggle("is-confirmed", confirmed);
        const label = $("industry-label");
        label.textContent = confirmed ? INDUSTRIES[industry.template_id] || humanize(industry.template_id) : "Industry not set";
        label.className = confirmed ? "kw-pill kw-pill-ready" : "kw-pill kw-pill-review";
        const help = $("industry-help");
        if (confirmed) { help.textContent = "Industry confirmed"; return; }
        const link = el("a", "Bot instructions"); link.href = `new_prompt.html?bot_id=${botId}`;
        help.replaceChildren("Confirm the industry in ", link, " for better reports");
    }
    function lockPage() {
        // One upgrade call to action: the landing replaces the page, so the status banner stays out of the way.
        $("analysis-layout").hidden = true;
        $("bot-card").hidden = true;
        $("analysis-statusline").hidden = true;
        $("analysis-locked").hidden = false;
    }
    function initialFailure(error) {
        if (error.code === "feature_not_available") return lockPage();
        const off = error.code === "analysis_disabled";
        if (off) status(error.message);
        else showError(error, true);
        $("analysis-off").hidden = !off;
        $("report-form").hidden = off;
        setGenerate(false, off ? "" : "Reports can't be reached right now.");
        if ($("bot-context").querySelector(".cr-skeleton")) $("bot-card").hidden = true;
        reportsUnavailable();
        recordsUnavailable();
    }
    async function initialize() {
        status("Loading this bot…");
        setGenerate(false, "Loading this bot…");
        if (!contextChecked) {
            if (!await validateChatbotContext(botId)) return;
            contextChecked = true;
        }
        try {
            const data = (await api("")).data;
            paintBot(isObject(data) ? data : {});
            $("bot-card").hidden = false;
            window.AnalysisTuition?.init(botId, isObject(data) ? data.industry : null, formatDate);
            await loadReports();
            await loadRecords();
            await loadAutomation();
        } catch (error) { initialFailure(error); return; }
        ready = true;
        $("analysis-off").hidden = true; $("report-form").hidden = false;
        setGenerate(true);
        status(CONNECTED);
        schedulePoll();
    }

    $("analysis-retry").addEventListener("click", retry);
    $("close-report").addEventListener("click", () => $("report-dialog").close());
    $("report-dialog").addEventListener("click", event => { if (event.target === event.currentTarget) event.currentTarget.close(); });
    $("refresh-records").addEventListener("click", () => loadRecords().catch(error => { recordsUnavailable(); showError(error, true); }));
    $("more-records").addEventListener("click", async () => {
        try {
            const added = await loadRecords(true);
            // Move focus to the first record that just arrived, whether or not "Show more" is still there.
            const item = added.length && $("business-records").querySelector(`[data-record-id="${CSS.escape(String(added[0].id))}"]`);
            if (item) { const link = item.querySelector("a"); if (link) link.focus(); else { item.tabIndex = -1; item.focus(); } }
        } catch (error) { showError(error); }
    });
    $("more-reports").addEventListener("click", async () => {
        const before = new Set(reports.keys());
        try {
            await loadReports(true);
            const added = [...reports.values()].filter(row => !before.has(row.id)).sort(newestFirst);
            if (!(added.length && focusReport(added[0].id)) && $("more-reports").hidden) $("analysis-statusline").focus();
        } catch (error) { showError(error); }
    });
    window.addEventListener("pagehide", () => { stopped = true; clearTimeout(timer); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = "Analysis | Omnexa"; schedulePoll(); });
    document.querySelector('chatbot-sidebar a[aria-current="page"]')?.scrollIntoView({block: "nearest"});
    initialize();
})();
