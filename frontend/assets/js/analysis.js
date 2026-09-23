(function () {
    "use strict";
    requireLogin();
    requireAdminOrOwner();
    try { if (!["owner", "admin"].includes(JSON.parse(sessionStorage.getItem("user") || "{}").role)) return; }
    catch (_) { return; }
    const botId = parsePositiveSafeInteger(new URLSearchParams(location.search).get("bot_id") || sessionStorage.getItem("selectedBotId"));
    if (!botId) { location.replace("bots.html"); return; }
    const $ = id => document.getElementById(id);
    const base = `/api/chatbots/${botId}/analysis`;
    const reports = new Map();
    let reportCursor = null, recordCursor = 0, timer = null, stopped = false, failures = 0, sending = false, requestKey = null;
    const labels = {queued: "Queued", running: "Generating", complete: "Report ready", partial: "Partially complete", failed: "Failed", needs_review: "Needs review", needs_input: "More information needed"};
    function el(tag, text, className) {
        const node = document.createElement(tag);
        if (text != null) node.textContent = String(text);
        if (className) node.className = className;
        return node;
    }
    const UPGRADE_MESSAGE = "This feature needs the Pro plan.";
    function status(message, error = false, upgrade = false) {
        const node = $("analysis-status");
        node.textContent = message; node.dataset.error = String(error);
        if (upgrade) { const link = el("a", "Upgrade in Billing"); link.href = "billing.html"; node.append(" ", link); }
    }
    function showError(error) { status(error.message, true, error.code === "feature_not_available"); }
    function requestError(response, body, fallback) {
        // Plan denials get a friendly upgrade prompt, never the raw server feature key.
        const upgrade = response.status === 403 && body?.code === "feature_not_available";
        const error = new Error(upgrade ? UPGRADE_MESSAGE : body?.message || fallback);
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
            return response.ok && body.status === "success" && flags && typeof flags === "object" && !Array.isArray(flags) ? flags : {};
        } catch (_) { return {}; }
    }
    function button(text, handler) { const b = el("button", text); b.type = "button"; b.addEventListener("click", handler); return b; }
    function date(value) { const d = new Date(value); return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(); }
    const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const HOURS = Array.from({length: 24}, (_, hour) => String(hour).padStart(2, "0"));
    function validMatrix(matrix) {
        return Array.isArray(matrix) && matrix.length === 7 && matrix.every(row => Array.isArray(row) && row.length === 24
            && row.every(value => Number.isInteger(value) && value >= 0));
    }
    function heatmap(item) {
        // Day x hour counts as a real table: numbers stay readable to screen readers and in any colour scheme.
        const label = String(item.label || item.key || "Activity");
        const section = el("section", null, "analysis-heatmap-block");
        section.append(el("h3", label), el("p", `${item.timezone || "Asia/Kuala_Lumpur"} · ${item.note || ""}`, "analysis-muted"));
        if (item.status === "unavailable" || !validMatrix(item.matrix)) {
            section.append(el("p", "Unavailable: this grid is unknown, not zero.", "analysis-muted"));
            return section;
        }
        if (item.status === "partial") section.append(el("p", `Limited coverage: ${item.unreadable_count || 0} record(s) could not be plotted or the source reached its limit.`, "analysis-muted"));
        const max = Math.max(1, ...item.matrix.flat());
        const scroll = el("div", null, "analysis-heatmap-scroll");
        scroll.tabIndex = 0; scroll.setAttribute("role", "region"); scroll.setAttribute("aria-label", `${label}, scrollable table`);
        const table = el("table", null, "analysis-heatmap");
        table.append(el("caption", `${label} · total ${item.total ?? 0}`));
        const head = el("tr"); head.append(Object.assign(el("th", "Day"), {scope: "col"}));
        for (const hour of HOURS) head.append(Object.assign(el("th", hour), {scope: "col"}));
        const thead = el("thead"); thead.append(head);
        const tbody = el("tbody");
        item.matrix.forEach((counts, day) => {
            const row = el("tr"); const name = (Array.isArray(item.days) && item.days[day]) || DAYS[day];
            row.append(Object.assign(el("th", name), {scope: "row"}));
            counts.forEach((count, hour) => {
                const cell = el("td", count);
                cell.dataset.level = String(count ? Math.ceil(count / max * 4) : 0);
                cell.title = `${name} ${HOURS[hour]}:00–${HOURS[hour]}:59 · ${count}`;
                row.append(cell);
            });
            tbody.append(row);
        });
        table.append(thead, tbody); scroll.append(table); section.append(scroll);
        return section;
    }
    function renderReports() {
        const thread = $("report-thread"); thread.replaceChildren();
        if (!reports.size) { thread.append(el("p", "No reports yet. Ask your agent for a period and business question.", "analysis-empty")); return; }
        [...reports.values()].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")).forEach(row => {
            const article = el("article", null, "analysis-message");
            article.append(el("time", date(row.created_at)), el("p", row.request_text));
            const badge = el("span", labels[row.status] || "Unavailable", "analysis-state"); badge.dataset.state = row.status; article.append(badge);
            if (["complete", "partial", "needs_input", "needs_review", "failed"].includes(row.status)) article.append(button("View details", () => openReport(row.id)));
            thread.append(article);
        });
    }
    function merge(rows) {
        for (const row of rows) {
            const previous = reports.get(row.id);
            if (previous && ["queued", "running"].includes(previous.status) && ["complete", "partial"].includes(row.status)) {
                status(row.status === "complete" ? "Your report is ready." : "Your report is partially complete. Review its limitations.");
                if (document.hidden) document.title = "(1) Analysis | Omnexa";
            }
            reports.set(row.id, row);
        }
        renderReports();
    }
    async function loadReports(earlier = false) {
        const body = await api("/messages" + (earlier && reportCursor ? `?before_id=${encodeURIComponent(reportCursor)}` : ""));
        merge(body.data || []);
        if (earlier || !reportCursor) reportCursor = body.next_cursor;
        $("more-reports").hidden = !reportCursor;
    }
    async function loadRecords(more = false) {
        const body = await api(`/records?after_id=${more ? recordCursor : 0}`);
        const container = $("business-records");
        if (!more) container.replaceChildren();
        for (const row of body.data || []) {
            const item = el("article", null, "analysis-record");
            item.append(el("strong", String(row.action_type || "Customer request").replaceAll("_", " ")));
            item.append(el("p", `${row.status} · ${date(row.created_at)}`));
            if (row.conversation_id) {
                const link = el("a", "Open conversation →");
                link.href = `conversations.html?bot_id=${botId}&conversation_id=${encodeURIComponent(row.conversation_id)}`;
                item.append(link);
            }
            container.append(item);
        }
        if (!container.children.length) container.append(el("p", "No recorded activity yet. Confirmed actions appear only after the business service confirms them.", "analysis-empty"));
        recordCursor = body.next_cursor;
        $("more-records").hidden = !recordCursor;
    }
    async function openReport(id) {
        try {
            const row = (await api(`/reports/${encodeURIComponent(id)}`)).data;
            $("report-title").textContent = labels[row.status] || "Report";
            const content = $("report-content"); content.replaceChildren();
            const result = row.result || {}, snapshot = row.snapshot || result.snapshot || {};
            content.append(el("p", row.request_text));
            if (row.status === "needs_input") content.append(el("p", result.clarification || result.question || "Specify the report period and what you want to analyze in a new request."));
            if (row.status === "needs_review") content.append(el("p", "The model result could not be confirmed. The operation is held for review to avoid duplicate charges."));
            if (row.status === "failed") content.append(el("p", "This report failed. No completed report is available."));
            const grid = el("div", null, "analysis-metrics");
            for (const metric of snapshot.metrics || []) {
                const card = el("div", metric.label || metric.key, "analysis-metric");
                card.append(el("strong", ["available", "partial"].includes(metric.status) && metric.value != null ? metric.value : "Not connected / unavailable"));
                if (metric.status === "partial") card.append(el("small", "Limited source coverage"));
                if (typeof metric.reason === "string") card.append(el("small", metric.reason));
                grid.append(card);
            }
            content.append(grid);
            const grids = Array.isArray(snapshot.distributions) ? snapshot.distributions : [];
            if (grids.length) { content.append(el("h3", "Activity by day and hour")); for (const item of grids) content.append(heatmap(item)); }
            if (typeof result.narrative === "string") content.append(el("p", result.narrative));
            for (const section of result.narrative ? [] : result.sections || []) {
                content.append(el("h3", section.title || section.heading || "Analysis"));
                if (typeof section.text === "string" || typeof section.content === "string" || typeof section.body === "string") content.append(el("p", section.text || section.content || section.body));
                for (const point of section.points || []) content.append(el("p", point));
            }
            const limitations = [...(snapshot.limitations || []), ...(result.limitations || [])];
            if (limitations.length) { content.append(el("h3", "Coverage and limitations")); for (const line of limitations) content.append(el("p", typeof line === "string" ? line : JSON.stringify(line))); }
            if ((snapshot.documents || []).length) { content.append(el("h3", "Document sources")); for (const doc of snapshot.documents) content.append(el("p", `${doc.name} · ${doc.status}${doc.truncated ? " · limited excerpts" : ""}`)); }
            if (snapshot.customer_questions?.excerpts?.length) {
                const samples = el("details"); samples.append(el("summary", "Customer question samples"));
                for (const sample of snapshot.customer_questions.excerpts) samples.append(el("p", `Message ${sample.message_id} · Conversation ${sample.conversation_id}: ${sample.text}`));
                content.append(samples);
            }
            const downloads = $("report-downloads"); downloads.replaceChildren();
            for (const format of row.formats || []) downloads.append(button(`Download ${format.toUpperCase()}`, () => download(id, format)));
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
        } catch (error) { showError(error); }
    }
    function schedulePoll() {
        clearTimeout(timer);
        if (stopped || failures >= 3) return;
        timer = setTimeout(async () => {
            try {
                const active = [...reports.values()].filter(row => ["queued", "running"].includes(row.status));
                for (const row of active) merge([(await api(`/reports/${encodeURIComponent(row.id)}`)).data]);
                await loadReports(); failures = 0;
            } catch (error) { failures++; status(error.message + (failures >= 3 ? " Updates paused. Refresh the page to reconnect." : " Reconnecting…"), true); }
            schedulePoll();
        }, document.hidden ? 30000 : 10000);
    }
    $("report-form").addEventListener("submit", async event => {
        event.preventDefault(); if (sending) return;
        const text = $("report-command").value.trim(); if (!text) return;
        sending = true; $("send-report").disabled = true;
        requestKey ||= crypto.randomUUID();
        try {
            const body = await api("/messages", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text, client_message_id: requestKey})});
            merge([body.data]); requestKey = null; $("report-command").value = ""; failures = 0;
            status("Request saved. You can leave this page while the report runs."); schedulePoll();
        } catch (error) { showError(error); }
        finally { sending = false; $("send-report").disabled = false; }
    });
    $("report-command").addEventListener("input", () => { if (!sending) requestKey = null; });
    document.querySelectorAll("[data-prompt]").forEach(node => node.addEventListener("click", () => { $("report-command").value = node.dataset.prompt; requestKey = null; $("report-command").focus(); }));
    let automationEnabled = false;
    function applyAutomation(enabled) {
        // Pro-only automation (schedules, request recording) stays visible but locked, with an upgrade note.
        automationEnabled = enabled;
        document.querySelectorAll("[data-plan-lock]").forEach(node => { node.hidden = enabled; });
        // The lock blocks turning automation ON only; a downgraded tenant must still be able to switch it OFF.
        document.querySelectorAll("[data-frequency], #recording-enabled").forEach(node => { node.disabled = !enabled && !node.checked; });
    }
    function automationError(node, error) {
        node.checked = !node.checked; showError(error);
        if (error.code === "feature_not_available") applyAutomation(false);
    }
    document.querySelectorAll("[data-frequency]").forEach(node => node.addEventListener("change", async () => {
        node.disabled = true;
        try { await api("/schedules", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({frequency: node.dataset.frequency, enabled: node.checked})}); status(node.checked ? "Schedule enabled." : "Schedule paused."); }
        catch (error) { automationError(node, error); }
        finally { node.disabled = !automationEnabled && !node.checked; }
    }));
    $("recording-enabled").addEventListener("change", async event => {
        const node = event.target; node.disabled = true;
        try { await api("/recording", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({enabled:node.checked})}); status(node.checked ? "New customer requests will be recorded. AI credit usage applies." : "Automatic request recording paused."); }
        catch (error) { automationError(node, error); }
        finally { node.disabled = !automationEnabled && !node.checked; }
    });
    $("close-report").addEventListener("click", () => $("report-dialog").close());
    $("refresh-records").addEventListener("click", () => loadRecords().catch(error => showError(error)));
    $("more-records").addEventListener("click", () => loadRecords(true).catch(error => showError(error)));
    $("more-reports").addEventListener("click", () => loadReports(true).catch(error => showError(error)));
    window.addEventListener("pagehide", () => { stopped = true; clearTimeout(timer); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = "Analysis | Omnexa"; schedulePoll(); });
    async function initialize() {
        document.querySelector('chatbot-sidebar a[aria-current="page"]')?.scrollIntoView({block:"nearest"});
        if (!await validateChatbotContext(botId)) return;
        try {
            const data = (await api("")).data;
            $("bot-context").textContent = data.bot.bot_name || `Bot #${botId}`;
            document.querySelector("chatbot-sidebar")?.setBotName(data.bot.bot_name);
            $("industry-label").textContent = data.industry.template_id && data.industry.confirmed_at ? data.industry.template_id.replaceAll("_", " ") : "Industry not confirmed";
            $("role-context").textContent = data.role.business_description || "Reports use this bot's role and authorized knowledge. Confirm its industry in Bot instructions for tailored analysis.";
            window.AnalysisTuition?.init(botId, data.industry);
            await loadReports(); await loadRecords();
            let automation = (await planFeatures()).automation_workflows === true;
            try {
                const recording = (await api("/recording")).data;
                $("recording-enabled").checked = recording.enabled === true;
                const schedules = (await api("/schedules")).data || [];
                document.querySelectorAll("[data-frequency]").forEach(node => { node.checked = schedules.some(row => row.frequency === node.dataset.frequency && row.enabled); });
            } catch (error) {
                // A plan denial on automation settings must not take the reports page down with it.
                if (error.code !== "feature_not_available") throw error;
                automation = false;
            }
            applyAutomation(automation);
            $("send-report").disabled = false; status("Connected to this bot's business records."); schedulePoll();
        } catch (error) { showError(error); $("business-records").replaceChildren(el("p", "Records are unavailable. This does not mean there are no requests.", "analysis-empty")); }
    }
    initialize();
})();
