(function () {
    "use strict";

    requireLogin();

    const validViews = ["today", "leads", "performance", "signals"];
    const params = new URLSearchParams(window.location.search);
    const urlBotId = params.get("bot_id");
    const storedBotId = sessionStorage.getItem("selectedBotId");
    const selectedBotId = urlBotId || storedBotId;
    const state = {
        bot: null,
        leads: [],
        analytics: null,
        signals: null,
        signalsLoaded: false,
        currentView: normalizeView(params.get("view") || (params.get("tab") === "ai-signals" ? "signals" : "today")),
        selectedLead: null,
        reportHtml: "",
        featureFlags: {},
    };

    if (!selectedBotId) {
        window.location.replace("bots.html");
        return;
    }
    sessionStorage.setItem("selectedBotId", selectedBotId);

    function $(id) {
        return document.getElementById(id);
    }

    function normalizeView(view) {
        if (view === "signals" && !canViewSignals()) return "today";
        return validViews.includes(view) ? view : "today";
    }

    function canViewSignals() {
        try {
            const user = JSON.parse(sessionStorage.getItem("user") || "null");
            const role = String(user && user.role || "").toLowerCase();
            return role === "owner" || role === "admin";
        } catch (_) {
            return false;
        }
    }

    function setText(id, value) {
        const element = $(id);
        if (element) element.textContent = String(value ?? "-");
    }

    function setStatus(message, isError) {
        const element = $("ia-status");
        if (!element) return;
        element.textContent = message || "";
        element.classList.toggle("is-error", Boolean(isError));
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function formatLabel(value) {
        const text = String(value || "").replace(/_/g, " ").trim();
        return text ? text.replace(/\b\w/g, char => char.toUpperCase()) : "-";
    }

    function formatDate(value) {
        if (!value) return "-";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
    }

    function normalizeDateValue(value) {
        return String(value || "").slice(0, 10);
    }

    function getTodayDateString() {
        const date = new Date();
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    }

    function normalizeStatus(status) {
        const normalized = String(status || "").toLowerCase().replace(/\s+/g, "_");
        return { in_progress: "contacted", closed: "lost" }[normalized] || normalized;
    }

    function isTerminalStatus(status) {
        const normalized = normalizeStatus(status);
        return normalized === "won" || normalized === "lost";
    }

    function getFollowUpState(lead) {
        if (isTerminalStatus(lead.status)) return "closed";
        const date = normalizeDateValue(lead.follow_up_date);
        if (!date) return "none";
        const today = getTodayDateString();
        if (date < today) return "overdue";
        if (date === today) return "today";
        return "upcoming";
    }

    function updateUrl(view, mode) {
        const url = new URL(window.location.href);
        url.searchParams.set("bot_id", selectedBotId);
        url.searchParams.set("view", view);
        url.searchParams.delete("tab");
        if (mode === "replace") window.history.replaceState({ view }, "", url);
        else window.history.pushState({ view }, "", url);
    }

    function setView(view, mode) {
        state.currentView = normalizeView(view);
        document.querySelectorAll("[data-view-tab]").forEach(button => {
            const active = button.dataset.viewTab === state.currentView;
            button.setAttribute("aria-selected", String(active));
        });
        document.querySelectorAll("[data-view-panel]").forEach(panel => {
            panel.hidden = panel.dataset.viewPanel !== state.currentView;
        });
        if (mode) updateUrl(state.currentView, mode);
        if (state.currentView === "signals") loadSignals();
        if (state.currentView === "performance") renderPerformance();
    }

    function wireViewNavigation() {
        document.querySelectorAll("[data-view-tab]").forEach(button => {
            button.addEventListener("click", () => setView(button.dataset.viewTab, "push"));
        });
        window.addEventListener("popstate", () => {
            const next = new URLSearchParams(window.location.search).get("view");
            setView(next || "today");
        });
        $("open-action-queue").addEventListener("click", () => setView("leads", "push"));
        $("view-performance").addEventListener("click", () => setView("performance", "push"));
    }

    async function readJson(response) {
        try { return await response.json(); } catch (_) { return {}; }
    }

    async function loadBot() {
        try {
            const response = await authenticatedFetch(`/api/bots/${encodeURIComponent(selectedBotId)}`);
            const result = await readJson(response);
            if (!response.ok || result.status !== "success" || !result.data) throw new Error("You do not have access to this bot.");
            state.bot = result.data;
            const botName = state.bot.bot_name || "Selected bot";
            setText("bot-name", botName);
            setText("page-title", `${botName} insights`);
            setText("bot-status-copy", "Selected bot");
        } catch (error) {
            setStatus(error.message || "Unable to load this bot.", true);
            window.setTimeout(() => window.location.replace("bots.html"), 900);
        }
    }

    function hasPlanFeature(key) {
        return state.featureFlags[key] === true;
    }

    async function loadSubscription() {
        try {
            const response = await authenticatedFetch("/api/billing/subscription");
            const result = await readJson(response);
            const flags = result.data && result.data.plan && result.data.plan.feature_flags;
            if (response.ok && result.status === "success" && flags && typeof flags === "object" && !Array.isArray(flags)) {
                state.featureFlags = flags;
            }
        } catch (_) {
            setStatus("Plan access could not be verified. Reload to try again.", true);
        }
        const reportButton = $("generate-report");
        reportButton.disabled = !hasPlanFeature("ai_generated_reports");
        reportButton.textContent = reportButton.disabled ? "Plan access required" : "Generate report";
        reportButton.title = reportButton.disabled ? "AI reports require an enabled Pro subscription feature." : "";
        renderLeads();
    }

    async function loadLeads() {
        setTableMessage("Loading leads…", "Checking customer follow-up records.");
        try {
            const response = await authenticatedFetch(`/api/crm/leads?chatbot_id=${encodeURIComponent(selectedBotId)}`);
            const result = await readJson(response);
            if (!response.ok || result.status !== "success") throw new Error(result.message || "Unable to load leads.");
            state.leads = Array.isArray(result.data && result.data.leads) ? result.data.leads : [];
            renderLeadSummary();
            renderDailyBrief();
            renderLeads();
        } catch (error) {
            state.leads = [];
            renderLeadSummary();
            setTableMessage("Unable to load leads.", "Try refreshing this page.", true);
            setStatus(error.message || "Lead data is unavailable.", true);
        }
    }

    async function loadAnalytics() {
        try {
            const response = await authenticatedFetch(`/api/analytics?chatbot_id=${encodeURIComponent(selectedBotId)}`);
            const result = await readJson(response);
            if (!response.ok || result.status !== "success") throw new Error(result.message || "Unable to load performance data.");
            state.analytics = result.data || {};
            renderDailyBrief();
            renderPerformance();
        } catch (error) {
            setStatus(error.message || "Performance data is unavailable.", true);
            $("performance-chart").innerHTML = `<div class="ia-error">${escapeHtml(error.message || "Unable to load performance data.")}</div>`;
        }
    }

    async function loadSignals() {
        if (!canViewSignals() || state.signalsLoaded) return;
        state.signalsLoaded = true;
        setStatus("Loading customer signals…");
        try {
            const response = await authenticatedFetch(`/api/agent/insights?chatbot_id=${encodeURIComponent(selectedBotId)}`);
            const result = await readJson(response);
            if (!response.ok || result.status !== "success") throw new Error(result.message || "Unable to load signals.");
            state.signals = result.data || {};
            renderSignals();
        } catch (error) {
            state.signals = null;
            setStatus(error.message || "Unable to load signals.", true);
            $("signals-list").innerHTML = "";
        }
    }

    function setTableMessage(title, detail, isError) {
        $("leads-table-body").innerHTML = `<tr><td colspan="7"><div class="${isError ? "ia-error" : "ia-empty"}"><strong>${escapeHtml(title)}</strong><span class="ia-subtle">${escapeHtml(detail || "")}</span></div></td></tr>`;
    }

    function getSummary() {
        const counts = { new: 0, contacted: 0, qualified: 0, won: 0, lost: 0 };
        const followUps = { overdue: 0, today: 0, upcoming: 0, none: 0 };
        state.leads.forEach(lead => {
            const status = normalizeStatus(lead.status);
            if (Object.prototype.hasOwnProperty.call(counts, status)) counts[status] += 1;
            const followUp = getFollowUpState(lead);
            if (Object.prototype.hasOwnProperty.call(followUps, followUp)) followUps[followUp] += 1;
        });
        return { counts, followUps, active: counts.new + counts.contacted + counts.qualified, outcomes: counts.won + counts.lost };
    }

    function renderLeadSummary() {
        const summary = getSummary();
        ["new", "contacted", "qualified", "won", "lost"].forEach(status => setText(`stage-${status}`, summary.counts[status]));
        setText("lead-total", state.leads.length);
        setText("today-leads", state.leads.length);
        setText("lead-active", summary.active);
        setText("lead-overdue", summary.followUps.overdue);
        setText("lead-today", summary.followUps.today);
    }

    function renderDailyBrief() {
        const summary = getSummary();
        const actions = [];
        if (summary.followUps.overdue) {
            actions.push({ title: `${summary.followUps.overdue} overdue follow-up${summary.followUps.overdue === 1 ? "" : "s"}`, helper: "Customers are waiting for a response.", value: summary.followUps.overdue, warning: true, view: "leads", filter: "overdue" });
        }
        if (summary.counts.new) {
            actions.push({ title: `Review ${summary.counts.new} new lead${summary.counts.new === 1 ? "" : "s"}`, helper: "New customer interest is ready for review.", value: summary.counts.new, view: "leads", filter: "new" });
        }
        if (summary.followUps.today) {
            actions.push({ title: `${summary.followUps.today} follow-up${summary.followUps.today === 1 ? "" : "s"} due today`, helper: "Keep today's commitments visible.", value: summary.followUps.today, view: "leads", filter: "today" });
        }
        const chartValues = state.analytics && state.analytics.chart && Array.isArray(state.analytics.chart.data) ? state.analytics.chart.data : [];
        if (actions.length < 3 && chartValues.length) {
            const peakIndex = chartValues.indexOf(Math.max(...chartValues));
            const peakLabel = state.analytics.chart.labels && state.analytics.chart.labels[peakIndex] || "the latest period";
            actions.push({ title: `Activity peaked on ${peakLabel}`, helper: "Open Performance to review the busiest day.", value: chartValues[peakIndex], view: "performance" });
        }
        if (!actions.length) {
            const messages = state.analytics && state.analytics.total_messages;
            actions.push({ title: "Your action queue is clear", helper: messages ? `${messages} messages are recorded in the current workspace.` : "New activity will appear here as customers interact.", value: "OK", view: "performance" });
        }
        const list = $("daily-actions");
        list.replaceChildren();
        actions.slice(0, 3).forEach((action, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `ia-action-row${action.warning ? " is-warning" : ""}`;
            button.innerHTML = `<span class="ia-action-index">${index + 1}</span><span><span class="ia-action-title"></span><span class="ia-action-helper"></span></span><span class="ia-action-value"></span><span class="ia-action-arrow" aria-hidden="true">›</span>`;
            button.querySelector(".ia-action-title").textContent = action.title;
            button.querySelector(".ia-action-helper").textContent = action.helper;
            button.querySelector(".ia-action-value").textContent = action.value;
            button.addEventListener("click", () => {
                setView(action.view, "push");
                if (action.filter) {
                    const statusFilters = ["new", "contacted", "qualified", "won", "lost"];
                    $(statusFilters.includes(action.filter) ? "lead-status-filter" : "lead-follow-up-filter").value = action.filter;
                    renderLeads();
                }
            });
            list.appendChild(button);
        });
        setText("brief-count", actions.length);
    }

    function renderPipeline() {
        const summary = getSummary();
        ["new", "contacted", "qualified", "won", "lost"].forEach(status => {
            const button = document.querySelector(`[data-status-card="${status}"]`);
            if (button) button.setAttribute("aria-label", `${formatLabel(status)}: ${summary.counts[status]} leads`);
        });
    }

    function getFilteredLeads() {
        const status = $("lead-status-filter").value;
        const priority = $("lead-priority-filter").value;
        const type = $("lead-type-filter").value;
        const assignment = $("lead-assignment-filter").value;
        const followUp = $("lead-follow-up-filter").value;
        const query = $("lead-search").value.trim().toLowerCase();
        return state.leads.filter(lead => {
            const normalizedStatus = normalizeStatus(lead.status);
            const normalizedPriority = normalizeStatus(lead.priority);
            const normalizedType = normalizeStatus(lead.lead_type);
            const hasAssignee = Boolean(String(lead.assigned_to || "").trim());
            const haystack = [lead.customer_name, lead.customer_phone, lead.summary, lead.notes, lead.assigned_to, lead.source_channel, lead.lead_type].map(value => String(value || "").toLowerCase()).join(" ");
            const followUpState = getFollowUpState(lead);
            return (!status || normalizedStatus === status)
                && (!priority || normalizedPriority === priority)
                && (!type || normalizedType === type)
                && (!assignment || (assignment === "assigned" ? hasAssignee : !hasAssignee && !isTerminalStatus(lead.status)))
                && (!followUp || followUpState === followUp)
                && (!query || haystack.includes(query));
        });
    }

    function statusSelect(current) {
        const select = document.createElement("select");
        select.className = "ia-select";
        [["new", "New"], ["contacted", "Contacted"], ["qualified", "Qualified"], ["won", "Won"], ["lost", "Lost"]].forEach(([value, label]) => {
            const option = new Option(label, value, normalizeStatus(current) === value, normalizeStatus(current) === value);
            select.appendChild(option);
        });
        return select;
    }

    function renderLeads() {
        const rows = getFilteredLeads();
        const body = $("leads-table-body");
        body.replaceChildren();
        if (!rows.length) {
            setTableMessage(state.leads.length ? "No leads match these filters." : "No leads yet.", state.leads.length ? "Clear a filter to see more customer records." : "Leads will appear here when conversations show business interest.");
            return;
        }
        rows.forEach(lead => {
            const row = document.createElement("tr");
            const customer = document.createElement("td");
            customer.innerHTML = `<span class="ia-customer"></span><span class="ia-subtle"></span>`;
            customer.querySelector(".ia-customer").textContent = lead.customer_name || lead.customer_phone || "Unknown customer";
            customer.querySelector(".ia-subtle").textContent = formatLabel(lead.source_channel);
            row.appendChild(customer);

            const controls = document.createElement("td");
            const status = statusSelect(lead.status);
            controls.appendChild(status);
            row.appendChild(controls);

            const priority = document.createElement("td");
            const priorityBadge = document.createElement("span");
            priorityBadge.className = `ia-status-badge${String(lead.priority).toLowerCase() === "high" ? " is-warning" : ""}`;
            priorityBadge.textContent = formatLabel(lead.priority);
            priority.appendChild(priorityBadge);
            row.appendChild(priority);

            const followUp = document.createElement("td");
            const followUpBadge = document.createElement("span");
            const followUpState = getFollowUpState(lead);
            followUpBadge.className = `ia-status-badge${followUpState === "overdue" ? " is-danger" : followUpState === "today" ? " is-warning" : ""}`;
            followUpBadge.textContent = followUpState === "closed" ? "Closed" : followUpState === "none" ? "No date" : followUpState === "today" ? "Due today" : followUpState === "overdue" ? "Overdue" : "Upcoming";
            followUp.appendChild(followUpBadge);
            followUp.appendChild(document.createElement("br"));
            const dateInput = document.createElement("input");
            dateInput.type = "date";
            dateInput.className = "ia-input";
            dateInput.value = normalizeDateValue(lead.follow_up_date);
            dateInput.setAttribute("aria-label", "Follow-up date");
            followUp.appendChild(dateInput);
            row.appendChild(followUp);

            const assignment = document.createElement("td");
            const assignedInput = document.createElement("input");
            assignedInput.className = "ia-input";
            assignedInput.value = lead.assigned_to || "";
            assignedInput.maxLength = 100;
            assignedInput.disabled = !hasPlanFeature("crm_lead_assignment");
            assignedInput.placeholder = assignedInput.disabled ? "Plan access required" : "Staff name";
            assignedInput.title = assignedInput.disabled ? "Lead assignment requires an enabled Advanced or Pro feature." : "";
            assignedInput.setAttribute("aria-label", "Assigned staff member");
            assignment.appendChild(assignedInput);
            row.appendChild(assignment);

            const updated = document.createElement("td");
            updated.textContent = formatDate(lead.updated_at || lead.created_at);
            row.appendChild(updated);

            const actions = document.createElement("td");
            const wrap = document.createElement("div");
            wrap.className = "ia-inline-controls";
            const save = document.createElement("button");
            save.type = "button";
            save.className = "ia-btn";
            save.textContent = "Save";
            save.addEventListener("click", () => saveLead(lead, status, assignedInput, dateInput, save));
            const details = document.createElement("button");
            details.type = "button";
            details.className = "ia-btn";
            details.textContent = "Details";
            details.addEventListener("click", () => openLeadDetails(lead));
            wrap.append(save, details);
            actions.appendChild(wrap);
            row.appendChild(actions);
            body.appendChild(row);
        });
    }

    async function saveLead(lead, status, assigned, followUp, button) {
        button.disabled = true;
        const original = button.textContent;
        button.textContent = "Saving…";
        try {
            const response = await authenticatedFetch(`/api/crm/leads/${encodeURIComponent(lead.id)}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ chatbot_id: Number(selectedBotId), status: status.value, notes: lead.notes || "", ...(hasPlanFeature("crm_lead_assignment") ? { assigned_to: assigned.value } : {}), follow_up_date: followUp.value || null }),
            });
            const result = await readJson(response);
            if (!response.ok || result.status !== "success") throw new Error(result.message || "Unable to save this lead.");
            const updated = result.data && result.data.lead;
            state.leads = state.leads.map(item => item.id === lead.id ? updated : item);
            renderLeadSummary();
            renderDailyBrief();
            renderLeads();
            setStatus("Lead saved.");
        } catch (error) {
            setStatus(error.message || "Unable to save this lead.", true);
        } finally {
            button.disabled = false;
            button.textContent = original;
        }
    }

    function openLeadDetails(lead) {
        state.selectedLead = lead;
        setText("lead-dialog-title", lead.customer_name || lead.customer_phone || "Lead details");
        const detailGrid = $("lead-detail-grid");
        detailGrid.replaceChildren();
        [["Stage", formatLabel(normalizeStatus(lead.status))], ["Priority", formatLabel(lead.priority)], ["Type", formatLabel(lead.lead_type)], ["Reason", lead.summary || "-"], ["Source", formatLabel(lead.source_channel)], ["Follow-up", lead.follow_up_date || "No date"], ["Assigned to", lead.assigned_to || "Unassigned"], ["Created", formatDate(lead.created_at)], ["Updated", formatDate(lead.updated_at || lead.created_at)]].forEach(([label, value]) => {
            const wrapper = document.createElement("div");
            wrapper.innerHTML = `<div class="ia-detail-label"></div><div class="ia-detail-value"></div>`;
            wrapper.querySelector(".ia-detail-label").textContent = label;
            wrapper.querySelector(".ia-detail-value").textContent = value;
            detailGrid.appendChild(wrapper);
        });
        $("lead-notes").value = lead.notes || "";
        $("lead-conversation-link").href = lead.conversation_id ? `conversations.html?bot_id=${encodeURIComponent(selectedBotId)}&conversation_id=${encodeURIComponent(lead.conversation_id)}` : `conversations.html?bot_id=${encodeURIComponent(selectedBotId)}`;
        const dialog = $("lead-details-modal");
        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "open");
    }

    function closeLeadDetails() {
        const dialog = $("lead-details-modal");
        if (typeof dialog.close === "function") dialog.close();
        else dialog.removeAttribute("open");
        state.selectedLead = null;
    }

    async function saveLeadNotes() {
        if (!state.selectedLead) return;
        const button = $("save-lead-notes");
        button.disabled = true;
        try {
            const lead = state.selectedLead;
            const response = await authenticatedFetch(`/api/crm/leads/${encodeURIComponent(lead.id)}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ chatbot_id: Number(selectedBotId), status: lead.status, notes: $("lead-notes").value, ...(hasPlanFeature("crm_lead_assignment") ? { assigned_to: lead.assigned_to || "" } : {}), follow_up_date: lead.follow_up_date || null }),
            });
            const result = await readJson(response);
            if (!response.ok || result.status !== "success") throw new Error(result.message || "Unable to save notes.");
            state.leads = state.leads.map(item => item.id === lead.id ? result.data.lead : item);
            state.selectedLead = result.data.lead;
            renderLeadSummary();
            renderDailyBrief();
            renderLeads();
            setText("lead-dialog-feedback", "Saved");
        } catch (error) {
            setText("lead-dialog-feedback", error.message || "Unable to save notes.");
        } finally {
            button.disabled = false;
        }
    }

    function renderPerformance() {
        const analytics = state.analytics;
        if (!analytics) return;
        setText("performance-messages", analytics.total_messages ?? "-");
        setText("performance-users", analytics.total_users ?? "-");
        setText("today-messages", analytics.total_messages ?? "-");
        setText("today-users", analytics.total_users ?? "-");
        setText("today-leads", state.leads.length);
        const chart = analytics.chart || {};
        const labels = Array.isArray(chart.labels) ? chart.labels : [];
        const values = Array.isArray(chart.data) ? chart.data : [];
        renderChart("performance-chart", labels, values);
        renderChart("today-chart", labels, values);
    }

    function renderChart(containerId, labels, values) {
        const max = Math.max(...values, 1);
        const container = $(containerId);
        container.replaceChildren();
        if (!values.length) {
            container.innerHTML = '<div class="ia-empty">No message activity has been recorded yet.</div>';
            return;
        }
        values.forEach((value, index) => {
            const column = document.createElement("div");
            column.className = "ia-chart-col";
            column.tabIndex = 0;
            column.innerHTML = '<span class="ia-chart-value"></span><span class="ia-chart-bar"></span><span class="ia-chart-label"></span>';
            column.querySelector(".ia-chart-value").textContent = value;
            column.querySelector(".ia-chart-bar").style.height = `${Math.max((Number(value) / max) * 100, 5)}%`;
            column.querySelector(".ia-chart-bar").style.animationDelay = `${index * 30}ms`;
            column.querySelector(".ia-chart-label").textContent = labels[index] || "";
            container.appendChild(column);
        });
    }

    function renderSignals() {
        if (!state.signals) return;
        setStatus("");
        const summary = state.signals.summary || {};
        const keys = ["follow_up_opportunities", "needs_staff_attention", "negative_feedback", "missing_answers"];
        keys.forEach(key => setText(`signal-${key}`, summary[key] || 0));
        const recent = Array.isArray(state.signals.recent) ? state.signals.recent : [];
        const list = $("signals-list");
        list.replaceChildren();
        if (!recent.length) {
            list.innerHTML = '<div class="ia-empty">No customer signals detected yet.</div>';
            return;
        }
        recent.forEach(item => {
            const row = document.createElement("div");
            row.className = "ia-signal-row";
            row.innerHTML = '<div><div class="ia-signal-title"></div><div class="ia-signal-next"></div></div><time class="ia-signal-time"></time>';
            row.querySelector(".ia-signal-title").textContent = item.label || "Customer signal detected";
            row.querySelector(".ia-signal-next").textContent = `Suggested next step: ${item.suggested_next_step || "Review this conversation"}`;
            row.querySelector(".ia-signal-time").textContent = formatDate(item.created_at);
            list.appendChild(row);
        });
    }

    function inlineMarkdown(value) {
        return value.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    }

    function renderMarkdown(text) {
        const lines = escapeHtml(text).split("\n");
        const blocks = [];
        let paragraph = [];
        let table = null;
        const flushParagraph = () => {
            if (paragraph.length) blocks.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
            paragraph = [];
        };
        const flushTable = () => {
            if (!table) return;
            const [headers, ...rows] = table;
            blocks.push(`<table><thead><tr>${headers.map(cell => `<th>${cell}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${headers.map((_, index) => `<td>${row[index] || ""}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
            table = null;
        };
        lines.forEach(raw => {
            const line = raw.trim();
            if (line.startsWith("|") && line.endsWith("|")) {
                if (/^[|\s:-]+$/.test(line)) return;
                flushParagraph();
                const cells = line.split("|").slice(1, -1).map(cell => cell.trim());
                if (!table) table = [cells]; else table.push(cells);
                return;
            }
            flushTable();
            if (!line) return flushParagraph();
            if (line.startsWith("#")) {
                flushParagraph();
                const match = line.match(/^(#{1,3})\s*(.*)$/);
                const tag = match[1].length === 1 ? "h3" : "h4";
                blocks.push(`<${tag}>${inlineMarkdown(match[2])}</${tag}>`);
            } else if (/^[-*•]\s+/.test(line)) {
                flushParagraph();
                blocks.push(`<ul><li>${inlineMarkdown(line.replace(/^[-*•]\s+/, ""))}</li></ul>`);
            } else {
                paragraph.push(line);
            }
        });
        flushTable();
        flushParagraph();
        return blocks.join("");
    }

    async function generateReport() {
        if (!hasPlanFeature("ai_generated_reports")) return;
        const button = $("generate-report");
        const output = $("report-output");
        button.disabled = true;
        output.classList.remove("is-ready");
        output.innerHTML = '<div class="ia-loading">Preparing a plain-language report…</div>';
        try {
            const days = $("report-days").value;
            const response = await authenticatedFetch(`/api/analytics/report?chatbot_id=${encodeURIComponent(selectedBotId)}&days=${encodeURIComponent(days)}`);
            const result = await readJson(response);
            if (!response.ok || result.status !== "success" || !result.data || !result.data.report) throw new Error(result.message || "Unable to generate the report.");
            state.reportHtml = renderMarkdown(result.data.report);
            output.innerHTML = state.reportHtml;
            output.classList.add("is-ready");
            $("download-report").hidden = false;
            setStatus("Report ready.");
        } catch (error) {
            output.innerHTML = `<div class="ia-error">${escapeHtml(error.message || "Unable to generate the report.")}</div>`;
            $("download-report").hidden = true;
            setStatus(error.message || "Report generation failed.", true);
        } finally {
            button.disabled = false;
        }
    }

    async function downloadReport() {
        if (!state.reportHtml) return;
        const button = $("download-report");
        button.disabled = true;
        try {
            if (typeof window.html2pdf === "undefined") {
                await new Promise((resolve, reject) => {
                    const script = document.createElement("script");
                    script.src = "https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js";
                    // cdnjs's published hash for this exact file.
                    script.integrity = "sha512-GsLlZN/3F2ErC5ifS5QtgpiJtWd43JWSuIgh7mbzZ8zBps+dvLusV+eNQATqgA/HdeKFVgA5v3S/cIrLF7QnIg==";
                    script.crossOrigin = "anonymous";
                    script.onload = resolve;
                    script.onerror = reject;
                    document.head.appendChild(script);
                });
            }
            const title = escapeHtml(state.bot && state.bot.bot_name || "Chatbot");
            const wrapper = document.createElement("div");
            wrapper.style.cssText = "width:710px;padding:24px;background:#fff;color:#1e293b;font-family:Arial,sans-serif;line-height:1.6";
            wrapper.innerHTML = `<h1>Chatbot performance report</h1><p>${title}</p><hr>${state.reportHtml}`;
            await window.html2pdf().from(wrapper).set({ margin: 8, filename: `chatbot-report-${selectedBotId}.pdf`, html2canvas: { scale: 2 }, jsPDF: { unit: "mm", format: "a4", orientation: "portrait" } }).save();
        } catch (error) {
            setStatus("The PDF could not be prepared. Try again when the connection is available.", true);
        } finally {
            button.disabled = false;
        }
    }

    function wireFilters() {
        ["lead-status-filter", "lead-priority-filter", "lead-type-filter", "lead-assignment-filter", "lead-follow-up-filter", "lead-search"].forEach(id => {
            $(id).addEventListener("input", renderLeads);
            $(id).addEventListener("change", renderLeads);
        });
        $("clear-lead-filters").addEventListener("click", () => {
            ["lead-status-filter", "lead-priority-filter", "lead-type-filter", "lead-assignment-filter", "lead-follow-up-filter", "lead-search"].forEach(id => { $(id).value = ""; });
            renderLeads();
        });
        document.querySelectorAll("[data-status-card]").forEach(button => button.addEventListener("click", () => {
            $("lead-status-filter").value = button.dataset.statusCard;
            setView("leads", "push");
            renderLeads();
        }));
    }

    function wireDialog() {
        $("close-lead-details").addEventListener("click", closeLeadDetails);
        $("save-lead-notes").addEventListener("click", saveLeadNotes);
        $("lead-details-modal").addEventListener("click", event => {
            if (event.target === $("lead-details-modal")) closeLeadDetails();
        });
    }

    async function init() {
        if (!canViewSignals()) $("signals-tab").hidden = true;
        wireViewNavigation();
        wireFilters();
        wireDialog();
        $("generate-report").disabled = true;
        $("generate-report").addEventListener("click", generateReport);
        $("download-report").addEventListener("click", downloadReport);
        setView(state.currentView, "replace");
        await Promise.all([loadBot(), loadLeads(), loadAnalytics(), loadSubscription()]);
        renderPipeline();
    }

    document.addEventListener("DOMContentLoaded", init);
}());
