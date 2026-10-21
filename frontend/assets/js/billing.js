/* ══════════════════════════════════════════════════════════════════════
   BILLING — company-wide plan, credit and payment console

   Extracted wholesale from the old profile.html "Billing & Credits" tab.
   Every capability that page had survives here: plan management with its
   confirmations, credit analytics, top-up checkout and order polling,
   payment history with detail/retry/receipt, credit transactions,
   notifications, reports and all five CSV exports.

   Three deliberate repairs made during the move, each a dead control in
   the original rather than a change of behaviour:
     - the payment-history "Load More" button had no listener at all;
     - the order-detail modal had markup nowhere on the page, so every
       "View" click silently returned;
     - fetchAiCreditUsageSummary() targeted #ai-credit-usage-section, which
       likewise did not exist, so granted/spent/expired never rendered.

   Money is micro-MYR end to end (1 RM = 1_000_000). It is only divided at
   the moment of display, so no figure is ever rounded twice.

   Nothing is inferred: a dimension the backend cannot report is hidden
   rather than guessed at.
   ══════════════════════════════════════════════════════════════════════ */

(function () {
    "use strict";

    var SVG_NS = "http://www.w3.org/2000/svg";

    /* Inline paths, so the page owns its icons rather than waiting on a
       CDN. All use a 0 0 24 24 viewBox. */
    var ICON_PATHS = {
        bot: "M12 8V4H8M4 8h16v12H4zM2 14h2M20 14h2M9 13v2M15 13v2",
        users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM22 21v-2a4 4 0 0 0-3-3.87",
        plug: "M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4",
        file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
        database: "M12 3c4.97 0 9 1.34 9 3s-4.03 3-9 3-9-1.34-9-3 4.03-3 9-3zM3 6v12c0 1.66 4.03 3 9 3s9-1.34 9-3V6M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3",
        clock: "M12 8v4l3 3M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
        check: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm-4 9 3 3 5-5",
        cross: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM15 9l-6 6M9 9l6 6",
        alert: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
        octagon: "M7.9 2h8.2L22 7.9v8.2L16.1 22H7.9L2 16.1V7.9zM12 8v5m0 3h.01",
        info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v5M12 8h.01",
        timer: "M10 2h4M12 14l3-3M12 22a8 8 0 1 0 0-16 8 8 0 0 0 0 16z",
        slash: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM5.6 5.6l12.8 12.8",
        spinner: "M12 3a9 9 0 1 0 9 9"
    };

    var STATUS_LABELS = {
        active: "Active",
        trialing: "Trialing",
        trial_expired: "Trial Expired",
        past_due: "Past Due",
        cancelled: "Cancelled",
        expired: "Expired"
    };

    /* kw-pill has exactly three tones. Anything healthy is "ready", anything
       needing attention is "review", anything terminal is "off". */
    var STATUS_TONE = {
        active: "kw-pill-ready",
        trialing: "kw-pill-ready",
        trial_expired: "kw-pill-off",
        past_due: "kw-pill-review",
        cancelled: "kw-pill-off",
        expired: "kw-pill-off"
    };

    var PAYMENT_LABELS = {
        pending: "Pending",
        paid: "Paid",
        credited: "Completed",
        failed: "Failed",
        expired: "Expired"
    };

    var PAYMENT_TONE = {
        pending: "kw-pill-review",
        paid: "kw-pill-ready",
        credited: "kw-pill-ready",
        failed: "kw-pill-off",
        expired: "kw-pill-off"
    };

    var TXN_TYPE_LABELS = {
        usage_debit: "AI Usage",
        topup_purchase: "Credit Top-Up",
        subscription_included: "Subscription Credit",
        included_credit_grant: "Included Credit",
        expiry: "Credit Expired",
        adjustment: "Credit Adjustment",
        refund: "Credit Refund",
        reversal: "Credit Reversal"
    };

    var USAGE_LABELS = {
        knowledge_extraction: "Knowledge Training",
        knowledge_refinement_questions: "Refine Answers",
        knowledge_refinement_verification: "Refine Answers",
        test_scenario_generation: "Test Scenario Generation",
        persona_derivation: "Persona Derivation",
        profile_knowledge_match: "Profile / Knowledge Validation",
        website_knowledge_extraction: "Website Knowledge Training",
        knowledge_graph_extraction: "Knowledge Graph Training",
        chat_reply: "Chat Reply",
        message_reply: "Chat Reply",
        customer_reply: "Chat Reply",
        test_bot: "Test Bot",
        test_chat: "Test Bot"
    };

    /* The usage dimensions /api/billing/usage can actually report, in
       reading order. */
    var METERS = [
        { key: "chatbots", label: "Chatbots", icon: "bot" },
        { key: "team_members", label: "Team Members", icon: "users" },
        { key: "channels", label: "Connected Channels", icon: "plug" },
        { key: "knowledge_files", label: "Knowledge Files", icon: "file" },
        { key: "knowledge_storage_bytes", label: "Knowledge Storage", icon: "database", bytes: true }
    ];

    var POLL_MAX = 5;
    var POLL_INTERVAL_MS = 3000;
    var PAGE_SIZE = 20;
    var GAUGE_CIRCUMFERENCE = 207.35;

    var state = {
        subscription: null,
        usage: null,
        credit: null,
        analytics: null,
        metric: "spend",
        days: "30",
        orderOffset: 0,
        orderHasMore: true,
        orderLoading: false,
        orderTotal: 0,
        txnOffset: 0,
        txnHasMore: true,
        txnLoading: false,
        txnTotal: 0,
        pollTimer: null,
        pollCount: 0,
        pollRef: null,
        pollMode: null,
        subMgmtBusy: false,
        exporting: {},
        confirmResolve: null,
        activeOrderRef: null
    };

    /* ── tiny DOM helpers ──────────────────────────────────────────── */

    function $(id) { return document.getElementById(id); }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function svgEl(tag, className) {
        var node = document.createElementNS(SVG_NS, tag);
        if (className) node.setAttribute("class", className);
        return node;
    }

    function icon(name, size) {
        var svg = svgEl("svg", "dashboard-icon");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("aria-hidden", "true");
        if (size) {
            svg.setAttribute("width", String(size));
            svg.setAttribute("height", String(size));
        }
        var path = svgEl("path");
        path.setAttribute("d", ICON_PATHS[name] || ICON_PATHS.info);
        svg.appendChild(path);
        return svg;
    }

    function show(node, visible) {
        if (node) node.hidden = !visible;
    }

    function clear(node) {
        while (node && node.firstChild) node.removeChild(node.firstChild);
    }

    function announce(message) {
        var node = $("bl-announce");
        if (node) node.textContent = message;
    }

    /* Replaces the alert() calls the old page used. A banner is styleable,
       announced to screen readers, and does not block the main thread. */
    function showError(message) {
        var banner = $("bl-error");
        var text = $("bl-error-text");
        if (!banner || !text) return;
        text.textContent = message;
        banner.hidden = false;
        announce(message);
    }

    function clearError() {
        show($("bl-error"), false);
    }

    /* ── formatters ────────────────────────────────────────────────── */

    /* Micro-MYR. Anything non-zero but below RM0.01 reports as "<0.01"
       rather than rounding to zero, which would read as "free". */
    function formatMicroMyr(microMyr) {
        if (microMyr === null || microMyr === undefined) return "—";
        var value = Number(microMyr);
        if (!Number.isFinite(value)) return "—";
        var absVal = Math.abs(value);
        if (absVal === 0) return "RM 0.00";
        if (absVal < 10000) return value < 0 ? "-RM <0.01" : "RM <0.01";
        return (value < 0 ? "-RM " : "RM ") + (absVal / 1000000).toFixed(2);
    }

    function signedMicroMyr(microMyr) {
        var value = Number(microMyr);
        if (!Number.isFinite(value)) return "";
        var formatted = formatMicroMyr(value);
        if (formatted === "—") return "";
        return (value < 0 ? "" : "+") + formatted;
    }

    function formatMyr(amount) {
        return "RM " + Number(amount || 0).toFixed(2);
    }

    function formatNumber(value) {
        var n = Number(value);
        if (!Number.isFinite(n)) n = 0;
        return n.toLocaleString();
    }

    function formatCompact(value) {
        var n = Number(value || 0);
        if (!Number.isFinite(n)) return "0";
        var abs = Math.abs(n);
        if (abs >= 1e9) return (n / 1e9).toFixed(abs >= 1e10 ? 0 : 2).replace(/\.?0+$/, "") + "B";
        if (abs >= 1e6) return (n / 1e6).toFixed(abs >= 1e7 ? 0 : 2).replace(/\.?0+$/, "") + "M";
        if (abs >= 1e3) return (n / 1e3).toFixed(abs >= 1e4 ? 0 : 1).replace(/\.?0+$/, "") + "K";
        return formatNumber(Math.round(n));
    }

    function formatBytes(value) {
        var n = Number(value);
        if (!Number.isFinite(n) || n < 0) return "0 B";
        if (n === 0) return "0 B";
        if (n < 1024) return n + " B";
        var kb = n / 1024;
        if (kb < 1024) return kb.toFixed(1) + " KB";
        var mb = kb / 1024;
        if (mb < 1024) return mb.toFixed(1) + " MB";
        return (mb / 1024).toFixed(1) + " GB";
    }

    function formatLimit(value, isBytes) {
        if (value === null || value === undefined) return "Unlimited";
        return isBytes ? formatBytes(value) : String(value);
    }

    /* Dates follow the viewer's locale rather than a hardcoded en-US. */
    function formatDate(value) {
        if (!value) return "—";
        var d = new Date(value);
        if (isNaN(d.getTime())) return "—";
        try {
            return new Intl.DateTimeFormat(undefined, {
                year: "numeric", month: "short", day: "numeric"
            }).format(d);
        } catch (_) {
            return d.toDateString();
        }
    }

    function formatDateTime(value) {
        if (!value) return "—";
        var d = new Date(value);
        if (isNaN(d.getTime())) return "—";
        return d.toLocaleString();
    }

    /* Notification timestamps arrive without a zone from some writers; a
       naive "YYYY-MM-DD HH:MM:SS" is read as UTC rather than local, which is
       what the server means. */
    function formatNotificationTime(value) {
        if (!value || typeof value !== "string") return "";
        var text = value.trim();
        if (!text) return "";
        var parsed = new Date(text);
        if (isNaN(parsed.getTime()) && !/[zZ]$|[+-]\d{2}:?\d{2}$/.test(text)) {
            parsed = new Date(text.replace(" ", "T") + "Z");
        }
        if (isNaN(parsed.getTime())) return "";
        return parsed.toLocaleString();
    }

    function formatShortDate(value) {
        if (!value) return "";
        var d = new Date(value + "T00:00:00Z");
        if (isNaN(d.getTime())) return String(value);
        return d.toLocaleDateString([], { day: "numeric", month: "short" });
    }

    function formatInterval(interval) {
        if (!interval) return "—";
        if (interval === "monthly") return "Monthly";
        if (interval === "yearly") return "Yearly";
        return interval;
    }

    function formatStatus(status) {
        if (!status) return "Unknown";
        return STATUS_LABELS[status] || "Unknown";
    }

    function titleFromSlug(value) {
        if (!value) return "";
        return String(value).replace(/[-_]+/g, " ").replace(/\b([a-z])/g, function (m) {
            return m.toUpperCase();
        });
    }

    function formatModelName(model) {
        if (!model || model === "Unknown / Legacy") return model || "";
        var clean = String(model).split("/").pop().replace(/[-_]+/g, " ").trim();
        return clean.replace(/\b([a-z])/g, function (m) { return m.toUpperCase(); });
    }

    function usageLabel(usageType) {
        var key = (usageType || "").toLowerCase();
        return USAGE_LABELS[key] || titleFromSlug(key) || "AI Usage";
    }

    /* Both /api/billing/usage and /api/billing/subscription answer 200 with
       data:null for a company with no subscription; an unmocked route
       answers with data:[]. Neither is a readable object. */
    function asObject(value) {
        if (!value || typeof value !== "object" || Array.isArray(value)) return null;
        return value;
    }

    async function getJson(url) {
        try {
            var res = await authenticatedFetch(url);
            var body = await res.json();
            if (!res.ok || !body || body.status !== "success") return null;
            return body.data;
        } catch (_) {
            return null;
        }
    }

    /* ── pills and badges ──────────────────────────────────────────── */

    function pill(label, tone) {
        var node = el("span", "kw-pill " + (tone || "kw-pill-review"));
        var dot = el("span", "kw-dot " + (
            tone === "kw-pill-ready" ? "kw-dot-ready"
                : tone === "kw-pill-off" ? "kw-dot-off" : "kw-dot-review"
        ));
        dot.setAttribute("aria-hidden", "true");
        node.appendChild(dot);
        node.appendChild(el("span", null, label));
        return node;
    }

    function paymentPill(status) {
        var key = (status || "").toLowerCase();
        return pill(PAYMENT_LABELS[key] || "Unknown", PAYMENT_TONE[key] || "kw-pill-review");
    }

    function activationPill(activationStatus, reconciliationRequired) {
        var s = (activationStatus || "").toLowerCase();
        if (s === "completed") return pill("Completed", "kw-pill-ready");
        if (s === "credit_pending" || s === "activated" || s === "claimed" || s === "not_started") {
            return pill("Activating", "kw-pill-review");
        }
        if (s === "conflict" || s === "failed") return pill("Needs Attention", "kw-pill-off");
        if (reconciliationRequired) return pill("Needs Attention", "kw-pill-review");
        return pill("Unknown", "kw-pill-review");
    }

    /* ── confirmation dialog ───────────────────────────────────────── */

    function confirmAction(title, body, confirmLabel) {
        return new Promise(function (resolve) {
            $("bl-confirm-title").textContent = title;
            $("bl-confirm-body").textContent = body;
            $("bl-confirm-ok").textContent = confirmLabel;
            state.confirmResolve = resolve;
            window.kwDialog.open($("bl-confirm"), $("bl-confirm-ok"));
        });
    }

    function settleConfirm(result) {
        var resolve = state.confirmResolve;
        state.confirmResolve = null;
        window.kwDialog.close($("bl-confirm"));
        if (resolve) resolve(result);
    }

    /* ══════════════════════════════════════════════════════════════════
       1. COMPANY PLAN
       ══════════════════════════════════════════════════════════════════ */

    /* The Free plan's real state lives across several fields that can
       disagree with one another; this collapses them into one answer so the
       badge, the label and the trial line can never contradict. */
    function resolveFreeState(sub) {
        var status = ((sub && sub.status) || "").toLowerCase();
        var effective = ((sub && sub.effective_status) || "").toLowerCase();
        var trialStatus = ((sub && sub.trial_status) || "").toLowerCase();
        var hasTrialEnd = !!(sub && sub.trial_ends_at);
        var trialMissing = !!(sub && sub.trial_missing) || trialStatus === "missing" || !hasTrialEnd;
        var trialExpired = !!(sub && sub.trial_expired)
            || effective === "expired"
            || trialStatus === "expired"
            || trialStatus === "missing"
            || status === "expired";
        var trialActive = !trialExpired && (
            !!(sub && sub.trial_active)
            || effective === "trialing"
            || trialStatus === "active"
            || status === "trialing"
        );
        if (!trialActive) trialExpired = true;

        return {
            badgeStatus: trialActive ? "trialing" : "trial_expired",
            trialActive: trialActive,
            trialExpired: trialExpired,
            trialMissing: trialExpired && trialMissing,
            trialLabel: trialExpired ? (trialMissing ? "Trial End" : "Trial Ended") : "Trial Ends"
        };
    }

    function factRow(list, term, value) {
        list.appendChild(el("dt", null, term));
        if (value instanceof Node) {
            var dd = el("dd");
            dd.appendChild(value);
            list.appendChild(dd);
        } else {
            list.appendChild(el("dd", null, value));
        }
    }

    function renderTrialValue(sub, free) {
        if (free.trialMissing) return document.createTextNode("unavailable - upgrade to continue");

        var dateStr = formatDate(sub.trial_ends_at);
        if (free.trialExpired) return document.createTextNode(dateStr + " - upgrade to continue");

        var trialEnd = new Date(sub.trial_ends_at);
        var daysLeft = Math.max(0, Math.ceil((trialEnd - new Date()) / 86400000));
        var frag = document.createDocumentFragment();
        frag.appendChild(document.createTextNode(
            dateStr + " (" + daysLeft + " day" + (daysLeft !== 1 ? "s" : "") + " remaining) - uses "
        ));
        frag.appendChild(el("strong", null, "the entry AI model"));
        frag.appendChild(document.createTextNode(" only"));
        return frag;
    }

    function planActionLabel(sub, plan) {
        var status = (sub.effective_status || sub.status || "").toLowerCase();
        var code = (plan.code || "").toLowerCase();
        var cancelScheduled = sub.cancellation_effective_at != null;
        var downgradeScheduled = sub.pending_plan != null;

        if (status === "active" && (cancelScheduled || downgradeScheduled)) return "Manage Plan";
        if (status === "trialing" || status === "" || code === "free") return "Upgrade Plan";
        if (status === "past_due" || status === "expired") return "Renew Plan";
        if (code === "pro") return "Manage Plan";
        return "Change Plan";
    }

    function setPlanError(message) {
        var node = $("bl-plan-error");
        if (!node) return;
        node.textContent = message || "";
        node.hidden = !message;
    }

    function renderPlan() {
        var sub = state.usageSubscription;
        var section = $("bl-plan-section");
        show(section, true);
        setPlanError("");

        if (!sub) {
            show($("bl-plan-hero"), false);
            show($("bl-plan-empty"), true);
            show($("bl-plan-actions"), false);
            return;
        }

        show($("bl-plan-hero"), true);
        show($("bl-plan-empty"), false);

        var plan = sub.plan || {};
        var code = (plan.code || "").toLowerCase();
        var isFree = code === "free";
        var free = isFree ? resolveFreeState(sub) : null;
        var displayStatus = isFree ? free.badgeStatus : (sub.effective_status || sub.status);

        $("bl-plan-name").textContent = plan.name || "—";

        var statusHost = $("bl-plan-status");
        clear(statusHost);
        statusHost.className = "";
        statusHost.appendChild(pill(
            formatStatus(displayStatus),
            STATUS_TONE[displayStatus] || "kw-pill-review"
        ));

        /* Facts. A Free trial has no billing period, so those rows are
           omitted rather than shown empty. */
        var facts = $("bl-plan-facts");
        clear(facts);
        var termMonths = Number(sub.billing_term_months || 1);
        factRow(
            facts,
            "Billing",
            isFree ? "7-day trial" : termMonths + "-month prepaid term"
        );
        if (isFree) {
            factRow(facts, free.trialLabel, renderTrialValue(sub, free));
        } else {
            factRow(facts, "Period Start", formatDate(sub.current_period_start));
            factRow(facts, "Paid Through", formatDate(sub.current_period_end));
            if (state.usage && state.usage.period && state.usage.period.end) {
                factRow(facts, "Allowance Resets", formatDate(state.usage.period.end));
            }
        }

        /* Change-plan link keeps the bot context so pricing.html opens in the
           same chatbot the user arrived from. */
        var change = $("bl-plan-change");
        change.textContent = planActionLabel(sub, plan);
        change.href = "pricing.html" + botQuery();

        renderScheduleNotices(sub);
        renderPlanActions(sub, isFree);
        updateTopupAccess(isFree || !code);
    }

    function renderScheduleNotices(sub) {
        var cancelAt = sub.cancellation_effective_at;
        var pending = sub.pending_plan;
        var changeAt = sub.plan_change_effective_at;
        var status = (sub.status || "").toLowerCase();
        var code = (sub.plan && sub.plan.code || "").toLowerCase();
        var eligible = status === "active" && code !== "free" && code !== "";

        var cancelNode = $("bl-cancel-scheduled");
        if (eligible && cancelAt) {
            $("bl-cancel-date").textContent = "Effective: " + new Date(cancelAt).toLocaleDateString();
            show(cancelNode, true);
        } else {
            show(cancelNode, false);
        }

        var downNode = $("bl-downgrade-scheduled");
        if (eligible && pending && pending.name && changeAt) {
            var target = $("bl-downgrade-target");
            clear(target);
            target.appendChild(document.createTextNode("Target: "));
            target.appendChild(el("strong", null, pending.name));
            target.appendChild(document.createTextNode(
                " — effective " + new Date(changeAt).toLocaleDateString()
            ));
            show(downNode, true);
        } else {
            show(downNode, false);
        }
    }

    function renderPlanActions(sub, isFree) {
        var host = $("bl-plan-actions");
        clear(host);

        var status = (sub.status || "").toLowerCase();
        if (status !== "active" || isFree) {
            show(host, false);
            return;
        }

        var actions = [];

        if (sub.cancellation_effective_at) {
            actions.push({
                label: "Undo Cancellation",
                cls: "kw-btn kw-btn-primary cr-press",
                run: doUndoCancel
            });
        } else {
            actions.push({
                label: "Cancel Subscription",
                cls: "kw-btn kw-btn-danger cr-press",
                run: doCancelSubscription
            });
        }

        if (sub.pending_plan && sub.pending_plan.name && sub.plan_change_effective_at) {
            actions.push({
                label: "Cancel Scheduled Downgrade",
                cls: "kw-btn cr-press",
                run: doClearDowngrade
            });
        }

        actions.forEach(function (action) {
            var button = el("button", action.cls, action.label);
            button.type = "button";
            button.addEventListener("click", action.run);
            host.appendChild(button);
        });

        show(host, true);
    }

    /* One request path for all three plan mutations: they differ only in
       endpoint, method, confirmation copy and failure message. */
    async function mutateSubscription(config) {
        if (state.subMgmtBusy) return;

        var ok = await confirmAction(config.title, config.body, config.confirmLabel);
        if (!ok) return;

        state.subMgmtBusy = true;
        setPlanError("");
        try {
            var res = await authenticatedFetch(config.url, { method: config.method });
            var body = await res.json();
            if (res.ok && body && body.status === "success") {
                announce(config.done);
                await loadPlan();
            } else {
                setPlanError((body && body.message) || config.failure);
            }
        } catch (_) {
            setPlanError("Network error. Please try again.");
        }
        state.subMgmtBusy = false;
    }

    function doCancelSubscription() {
        return mutateSubscription({
            title: "Cancel Subscription",
            body: "Cancel your subscription? Your plan will remain active until the end of the current billing period.",
            confirmLabel: "Confirm Cancellation",
            url: "/api/billing/subscription/cancel",
            method: "POST",
            failure: "Failed to schedule cancellation.",
            done: "Cancellation scheduled."
        });
    }

    function doUndoCancel() {
        return mutateSubscription({
            title: "Undo Cancellation",
            body: "Your subscription will remain active and will not be cancelled at the end of the billing period.",
            confirmLabel: "Undo Cancellation",
            url: "/api/billing/subscription/undo-cancel",
            method: "POST",
            failure: "Failed to undo cancellation.",
            done: "Cancellation removed."
        });
    }

    function doClearDowngrade() {
        return mutateSubscription({
            title: "Cancel Scheduled Downgrade",
            body: "Your current plan will remain active and the scheduled downgrade will be removed.",
            confirmLabel: "Cancel Downgrade",
            url: "/api/billing/subscription/downgrade",
            method: "DELETE",
            failure: "Failed to clear downgrade.",
            done: "Scheduled downgrade removed."
        });
    }

    function botQuery() {
        var botId = new URLSearchParams(window.location.search).get("bot_id")
            || sessionStorage.getItem("selectedBotId");
        var parsed = parsePositiveSafeInteger(String(botId || ""));
        return parsed ? "?bot_id=" + encodeURIComponent(String(parsed)) : "";
    }

    /* ══════════════════════════════════════════════════════════════════
       3. USAGE METERS
       ══════════════════════════════════════════════════════════════════ */

    function meterRow(spec, used, limit, pending) {
        var row = el("div", "bl-meter-row");

        var label = el("div", "bl-meter-label");
        label.appendChild(icon(spec.icon, 16));
        label.appendChild(el("span", null, spec.label));
        row.appendChild(label);

        var track = el("div");
        var figures = el("div", "bl-meter-figures");

        var usedVal = (used === null || used === undefined) ? 0 : Number(used);
        var pendingVal = Number(pending || 0);
        var effective = usedVal + pendingVal;
        var unlimited = limit === null || limit === undefined;
        var usedText = spec.bytes ? formatBytes(usedVal) : String(usedVal);

        if (unlimited) {
            track.appendChild(el("div", "bl-meter-none"));
            figures.appendChild(el("span", null, usedText));
            figures.appendChild(el("span", "bl-meter-limit", "/ Unlimited"));
        } else {
            var ratio = limit > 0 ? Math.min(effective / limit, 1) : (effective > 0 ? 1 : 0);
            var meter = el("div", "cr-meter");
            var fill = el("div", "cr-meter-fill");
            fill.style.setProperty("--cr-meter-value", String(ratio));

            /* Thresholds carry a word as well as a colour. */
            var over = effective > limit;
            var stateWord = null;
            if (over) {
                fill.classList.add("is-full");
                stateWord = "Over limit";
            } else if (effective === limit) {
                fill.classList.add("is-full");
                stateWord = "At limit";
            } else if (ratio >= 0.8) {
                fill.classList.add("is-warn");
                stateWord = "Nearly full";
            }

            meter.appendChild(fill);
            meter.setAttribute("aria-hidden", "true");
            track.appendChild(meter);

            figures.appendChild(el("span", null, usedText));
            figures.appendChild(el("span", "bl-meter-limit",
                "/ " + formatLimit(limit, spec.bytes)));
            if (stateWord) {
                figures.appendChild(el("span",
                    "bl-meter-state " + (over || effective === limit ? "is-full" : "is-warn"),
                    stateWord));
            }
        }

        if (pendingVal > 0) {
            figures.appendChild(el("span", "bl-meter-state is-warn",
                "Pending invitations: " + pendingVal));
        }

        row.appendChild(track);
        row.appendChild(figures);
        return row;
    }

    function renderUsage() {
        var usage = state.usage && state.usage.usage;
        if (!usage) {
            show($("bl-usage-section"), false);
            return;
        }

        var host = $("bl-meters");
        clear(host);

        METERS.forEach(function (spec) {
            var dimension = usage[spec.key];
            if (!dimension) return;
            host.appendChild(meterRow(
                spec,
                dimension.used,
                dimension.limit,
                spec.key === "team_members" ? dimension.pending_invitations : 0
            ));
        });

        /* Token totals have no limit to meter against, so they read as
           figures rather than as bars. */
        var tokens = usage.ai_tokens || {};
        var figures = $("bl-token-usage");
        clear(figures);
        [
            ["Input Tokens Used", tokens.input_tokens],
            ["Output Tokens Used", tokens.output_tokens],
            ["Total Tokens Used", tokens.total_tokens]
        ].forEach(function (pair) {
            var group = el("div", "kw-legend-figure");
            group.appendChild(el("b", null, formatNumber(pair[1] || 0)));
            group.appendChild(el("span", null, pair[0]));
            figures.appendChild(group);
        });

        show($("bl-usage-section"), true);
    }

    /* ══════════════════════════════════════════════════════════════════
       PLAN + USAGE LOAD
       ══════════════════════════════════════════════════════════════════ */

    async function loadPlan() {
        var results = await Promise.allSettled([
            getJson("/api/billing/subscription"),
            getJson("/api/billing/usage"),
            getJson("/api/billing/subscription/renewal-status")
        ]);

        var sub = results[0].status === "fulfilled" ? asObject(results[0].value) : null;
        var usage = results[1].status === "fulfilled" ? asObject(results[1].value) : null;
        var renewal = results[2].status === "fulfilled" ? asObject(results[2].value) : null;

        show($("bl-skeleton"), false);

        state.usageSubscription = sub;
        state.usage = usage;

        if (!sub && !usage) {
            showError("Unable to load company plan and usage information. Please try again later.");
            show($("bl-plan-section"), true);
            show($("bl-plan-hero"), false);
            show($("bl-plan-empty"), true);
            return;
        }

        if (!sub) showError("Unable to load plan information.");

        var renewalNode = $("bl-renewal");
        var renewalText = renewal && renewal.message;
        if (renewalText) {
            $("bl-renewal-text").textContent = renewalText;
            show(renewalNode, true);
        } else {
            show(renewalNode, false);
        }

        renderPlan();
        renderUsage();
    }

    /* ══════════════════════════════════════════════════════════════════
       2. AI CREDITS
       ══════════════════════════════════════════════════════════════════ */

    function setBalanceFigures(total, included, topup) {
        $("bl-credit-total").textContent = formatMicroMyr(total);
        $("bl-credit-included").textContent = formatMicroMyr(included);
        $("bl-credit-topup").textContent = formatMicroMyr(topup);
    }

    /* The gauge reads included-remaining against included-granted. Both come
       from real endpoints; when the grant figure is unavailable the gauge is
       hidden rather than drawn against a guess. */
    function renderGauge(remainingMicro, grantedMicro) {
        var gauge = $("bl-balance-gauge");
        var granted = Number(grantedMicro || 0);
        if (!Number.isFinite(granted) || granted <= 0) {
            show(gauge, false);
            return;
        }
        var remaining = Math.max(0, Number(remainingMicro || 0));
        var pct = Math.max(0, Math.min(100, Math.round((remaining / granted) * 100)));
        var filled = (pct / 100) * GAUGE_CIRCUMFERENCE;

        $("bl-gauge-fill").setAttribute("stroke-dasharray",
            filled.toFixed(2) + " " + GAUGE_CIRCUMFERENCE);
        $("bl-gauge-value").textContent = pct + "%";
        $("bl-gauge-a11y").textContent =
            pct + " percent of this period's included AI credit remaining";
        show(gauge, true);
    }

    async function loadCredit() {
        show($("bl-credit-loading"), true);
        show($("bl-credit-error"), false);

        var data = await getJson("/api/billing/ai-credit/summary");
        show($("bl-credit-loading"), false);

        if (!data || !data.initialised) {
            $("bl-credit-error-text").textContent = data
                ? "AI credit has not been initialized yet."
                : "Unable to load AI credit information.";
            show($("bl-credit-error"), true);
            show($("bl-balance"), false);
            return false;
        }

        state.credit = data;
        setBalanceFigures(
            data.total_balance_micro_myr,
            data.included_balance_micro_myr,
            data.topup_balance_micro_myr
        );

        if (data.period_start && data.period_end) {
            $("bl-credit-period").textContent =
                new Date(data.period_start).toLocaleDateString()
                + " - " + new Date(data.period_end).toLocaleDateString();
        }

        show($("bl-balance"), true);
        loadCreditActivity();
        return true;
    }

    /* granted / spent / expired for the current period. The old page fetched
       this and wrote it into elements that were never in the document. */
    async function loadCreditActivity() {
        var data = await getJson("/api/billing/ai-credit/usage-summary");
        var host = $("bl-credit-activity");
        var activity = data && data.activity;
        if (!activity) {
            show(host, false);
            show($("bl-balance-gauge"), false);
            return;
        }

        $("bl-acu-granted").textContent = formatMicroMyr(activity.included_granted_myr || 0);
        $("bl-acu-spent").textContent = formatMicroMyr(activity.usage_spent_myr || 0);
        $("bl-acu-expired").textContent = formatMicroMyr(activity.included_expired_myr || 0);
        show(host, true);

        renderGauge(
            state.credit && state.credit.included_balance_micro_myr,
            activity.included_granted_myr
        );
    }

    /* ── analytics ─────────────────────────────────────────────────── */

    var FILTER_FIELDS = [
        ["chatbot_id", "bl-filter-chatbot"],
        ["model", "bl-filter-model"],
        ["operation_type", "bl-filter-feature"]
    ];

    function hasActiveFilters() {
        return FILTER_FIELDS.some(function (pair) {
            var node = $(pair[1]);
            return !!(node && node.value);
        });
    }

    function analyticsParams() {
        var params = new URLSearchParams();
        params.set("days", state.days || "30");
        FILTER_FIELDS.forEach(function (pair) {
            var node = $(pair[1]);
            if (node && node.value) params.set(pair[0], node.value);
        });
        return params;
    }

    /* Returns true when a previously selected option has vanished from the
       server's filter list, which means the current request was answered for
       a filter the user can no longer see and must be reissued. */
    function populateFilter(id, allLabel, options) {
        var select = $(id);
        if (!select) return false;
        var previous = select.value || "";

        clear(select);
        select.appendChild(new Option(allLabel, ""));
        (options || []).forEach(function (option) {
            if (!option.value) return;
            var node = new Option(option.label || option.value, option.value);
            if (option.disabled) node.disabled = true;
            select.appendChild(node);
        });

        var available = (options || [])
            .filter(function (o) { return !o.disabled; })
            .map(function (o) { return o.value; });

        if (previous && available.indexOf(previous) === -1) {
            select.value = "";
            return true;
        }
        select.value = previous;
        return false;
    }

    function renderFilters(filters) {
        var changed = false;
        changed = populateFilter("bl-filter-chatbot", "All Chatbots",
            (filters.chatbots || []).map(function (bot) {
                return {
                    value: String(bot.id),
                    label: bot.name || "Deleted / unavailable chatbot",
                    disabled: bot.available === false
                };
            })) || changed;
        changed = populateFilter("bl-filter-model", "All Models",
            (filters.models || []).map(function (m) {
                return { value: m.value || "", label: formatModelName(m.value) || m.value || "Unknown" };
            })) || changed;
        changed = populateFilter("bl-filter-feature", "All Features",
            (filters.operations || []).map(function (o) {
                return { value: o.value || "", label: usageLabel(o.value) };
            })) || changed;
        return changed;
    }

    function statCard(label, value, unit) {
        var card = el("div", "kw-stat");
        var head = el("div", "kw-stat-head");
        head.appendChild(el("span", "kw-stat-label", label));
        card.appendChild(head);
        card.appendChild(el("div", "kw-stat-value", value));
        if (unit) card.appendChild(el("div", "kw-stat-unit", unit));
        return card;
    }

    async function loadAnalytics() {
        show($("bl-analytics-loading"), true);
        show($("bl-analytics-error"), false);
        show($("bl-analytics-empty"), false);
        show($("bl-analytics"), false);

        var data = await getJson("/api/billing/ai-credit/analytics?" + analyticsParams().toString());
        show($("bl-analytics-loading"), false);

        if (!data) {
            show($("bl-analytics-error"), true);
            return;
        }

        /* The analytics payload carries the balance too, so a credit summary
           that failed on its own still resolves here. */
        var summary = data.summary || {};
        if (summary.ai_credit_balance_micro_myr !== undefined) {
            setBalanceFigures(
                summary.ai_credit_balance_micro_myr,
                summary.included_balance_micro_myr,
                summary.topup_balance_micro_myr
            );
            show($("bl-credit-error"), false);
            show($("bl-balance"), true);
        }

        if (renderFilters(data.available_filters || {})) {
            loadAnalytics();
            return;
        }

        state.analytics = data;
        renderAnalytics(data);
    }

    function renderAnalytics(data) {
        var summary = data.summary || {};
        var period = data.period || {};
        var legacy = data.legacy || {};

        $("bl-analytics-period").textContent = period.label || "Last 30 days";

        var hasUsage = (summary.usage_count || 0) > 0 || (summary.ai_spend_micro_myr || 0) > 0;
        if (!hasUsage) {
            $("bl-analytics-empty-text").textContent = hasActiveFilters()
                ? "No AI usage matches these filters for the selected period."
                : "No AI usage recorded for this period.";
            show($("bl-analytics-empty"), true);
            show($("bl-analytics"), false);
            return;
        }

        show($("bl-analytics-empty"), false);
        show($("bl-analytics"), true);

        var stats = $("bl-analytics-stats");
        clear(stats);
        stats.appendChild(statCard("AI Credit Balance",
            formatMicroMyr(summary.ai_credit_balance_micro_myr)));
        stats.appendChild(statCard("AI Spend",
            formatMicroMyr(summary.ai_spend_micro_myr || 0)));
        stats.appendChild(statCard("Requests",
            formatCompact(summary.request_count || summary.usage_count || 0)));
        stats.appendChild(statCard("Token Volume",
            formatCompact(summary.total_tokens || 0)));
        stats.appendChild(statCard("Top Model by Tokens",
            formatModelName(summary.most_used_model) || "Unknown"));
        stats.appendChild(statCard("Avg / 1M Tokens",
            summary.average_cost_per_million_tokens_micro_myr === null
                || summary.average_cost_per_million_tokens_micro_myr === undefined
                ? "—"
                : formatMicroMyr(summary.average_cost_per_million_tokens_micro_myr)));

        renderMainChart();
        renderModelChart(data.model_daily_usage || []);
        renderRankedBars("bl-feature-chart", data.operations || [], {
            name: function (row) { return usageLabel(row.operation_type); },
            sub: function (row) { return row.operation_type || "Unknown"; },
            metric: function (row) {
                return formatCompact(row.total_tokens || 0) + " tok · "
                    + formatCompact(row.request_count || 0) + " req · "
                    + formatMicroMyr(row.customer_charge_micro_myr || 0);
            },
            empty: "No feature usage recorded for this period."
        });
        renderModelTable(data.models || []);
        renderTokenComposition(summary);

        var note = $("bl-legacy-note");
        var hasLegacy = (legacy.legacy_spend_micro_myr || 0) > 0
            || (legacy.usage_logs_without_model_count || 0) > 0;
        var excluded = Number(legacy.legacy_spend_excluded_due_to_filters_micro_myr || 0);
        if (excluded > 0) {
            note.textContent = "Unattributed legacy charges are excluded from filtered results.";
            show(note, true);
        } else if (hasLegacy) {
            note.textContent = "Model information unavailable for some legacy usage.";
            show(note, true);
        } else {
            show(note, false);
        }
    }

    /* ── chart engine ──────────────────────────────────────────────── */

    /* One stacked-bar renderer serves every chart on the page: single-series
       spend and requests, two-series token split, five-series model usage,
       and the report's monthly trend. Built with real SVG nodes rather than
       an innerHTML string, so no value ever needs escaping. */
    function drawChart(host, points, series, options) {
        clear(host);
        if (!points || !points.length) {
            host.appendChild(el("p", "bl-chart-note", options.empty));
            return;
        }

        var W = 900, H = 260, left = 62, right = 16, top = 18, bottom = 40;
        var innerW = W - left - right;
        var innerH = H - top - bottom;
        var step = innerW / points.length;
        var gap = Math.min(10, Math.max(3, step * 0.18));
        var barW = Math.max(3, step - gap);
        var formatter = options.formatter || formatCompact;

        var totals = points.map(function (point) {
            return series.reduce(function (sum, s) {
                return sum + Math.max(0, Number(point.values[s.index] || 0));
            }, 0);
        });
        var maxValue = Math.max.apply(null, totals) || 1;

        var svg = svgEl("svg");
        svg.setAttribute("viewBox", "0 0 " + W + " " + H);
        svg.setAttribute("preserveAspectRatio", "none");
        svg.setAttribute("role", "img");
        svg.setAttribute("aria-label", options.ariaLabel || options.yLabel);

        var yTitle = svgEl("text", "bl-axis-label");
        yTitle.setAttribute("x", "8");
        yTitle.setAttribute("y", "12");
        yTitle.textContent = options.yLabel;
        svg.appendChild(yTitle);

        for (var i = 0; i <= 4; i++) {
            var y = top + (innerH / 4) * i;
            var line = svgEl("line", "bl-grid-line");
            line.setAttribute("x1", String(left));
            line.setAttribute("y1", y.toFixed(2));
            line.setAttribute("x2", String(W - right));
            line.setAttribute("y2", y.toFixed(2));
            svg.appendChild(line);

            var tick = svgEl("text", "bl-axis-label");
            tick.setAttribute("x", String(left - 8));
            tick.setAttribute("y", (y + 4).toFixed(2));
            tick.setAttribute("text-anchor", "end");
            tick.textContent = formatter(maxValue - (maxValue / 4) * i);
            svg.appendChild(tick);
        }

        points.forEach(function (point, idx) {
            var x = left + idx * step + gap / 2;
            var cursor = top + innerH;
            series.forEach(function (s) {
                var value = Math.max(0, Number(point.values[s.index] || 0));
                if (value <= 0) return;
                var h = Math.max(2, (value / maxValue) * innerH);
                cursor -= h;
                var rect = svgEl("rect", s.cls);
                rect.setAttribute("x", x.toFixed(2));
                rect.setAttribute("y", cursor.toFixed(2));
                rect.setAttribute("width", barW.toFixed(2));
                rect.setAttribute("height", h.toFixed(2));
                rect.setAttribute("rx", "4");
                var title = svgEl("title");
                title.textContent = options.tooltip(point, s);
                rect.appendChild(title);
                svg.appendChild(rect);
            });
        });

        var labelEvery = Math.max(1, Math.ceil(points.length / 6));
        points.forEach(function (point, idx) {
            if (idx % labelEvery !== 0 && idx !== points.length - 1) return;
            var text = svgEl("text", "bl-axis-label");
            text.setAttribute("x", (left + idx * step + step / 2).toFixed(2));
            text.setAttribute("y", String(H - 12));
            text.setAttribute("text-anchor", "middle");
            text.textContent = point.label;
            svg.appendChild(text);
        });

        host.appendChild(svg);
    }

    function renderKeys(hostId, items) {
        var host = $(hostId);
        if (!host) return;
        clear(host);
        (items || []).forEach(function (item, idx) {
            var key = el("span", "bl-key");
            var swatch = el("span", "bl-key-swatch bl-key-" + (idx % 5));
            swatch.setAttribute("aria-hidden", "true");
            key.appendChild(swatch);
            key.appendChild(el("span", null, item));
            host.appendChild(key);
        });
    }

    function renderMainChart() {
        var data = state.analytics || {};
        var host = $("bl-main-chart");
        var metric = state.metric;

        if (metric === "tokens") {
            var tokenDays = data.token_trend || [];
            drawChart(host, tokenDays.map(function (day) {
                return {
                    label: formatShortDate(day.date),
                    raw: day,
                    values: [day.input_tokens || 0, day.output_tokens || 0]
                };
            }), [
                { index: 0, cls: "bl-series-0" },
                { index: 1, cls: "bl-series-2" }
            ], {
                yLabel: "Tokens",
                formatter: formatCompact,
                empty: "No AI usage recorded for this period.",
                ariaLabel: "Daily input and output tokens",
                tooltip: function (point) {
                    var d = point.raw;
                    return d.date + " - Input " + formatNumber(d.input_tokens || 0)
                        + " + Output " + formatNumber(d.output_tokens || 0)
                        + " = " + formatNumber(d.total_tokens || 0);
                }
            });
            renderKeys("bl-main-keys", ["Input Tokens", "Output Tokens"]);
            return;
        }

        var isRequests = metric === "requests";
        var days = isRequests ? (data.request_trend || []) : (data.spend_trend || []);
        drawChart(host, days.map(function (day) {
            return {
                label: formatShortDate(day.date),
                raw: day,
                values: [isRequests ? (day.request_count || 0) : (day.spent_micro_myr || 0)]
            };
        }), [{ index: 0, cls: "bl-series-0" }], {
            yLabel: isRequests ? "Requests" : "RM",
            formatter: isRequests ? formatCompact : function (v) {
                return formatMicroMyr(v).replace("RM ", "");
            },
            empty: "No AI usage recorded for this period.",
            ariaLabel: isRequests ? "Daily AI requests" : "Daily AI spend",
            tooltip: function (point) {
                var d = point.raw;
                return isRequests
                    ? d.date + " - " + formatNumber(d.request_count || 0) + " requests"
                    : d.date + " - " + formatMicroMyr(d.spent_micro_myr || 0);
            }
        });
        renderKeys("bl-main-keys", [isRequests ? "Requests" : "AI Spend"]);
    }

    function renderModelChart(series) {
        var host = $("bl-model-chart");
        var top5 = (series || []).slice(0, 5);
        var dates = ((top5[0] || {}).days || []).map(function (day) { return day.date; });

        if (!top5.length || !dates.length) {
            clear(host);
            host.appendChild(el("p", "bl-chart-note",
                "No model-level historical information for this period."));
            renderKeys("bl-model-keys", []);
            return;
        }

        drawChart(host, dates.map(function (date, idx) {
            return {
                label: formatShortDate(date),
                raw: { date: date, idx: idx },
                values: top5.map(function (row) {
                    return ((row.days || [])[idx] || {}).total_tokens || 0;
                })
            };
        }), top5.map(function (row, idx) {
            return { index: idx, cls: "bl-series-" + (idx % 5), model: row.model };
        }), {
            yLabel: "Tokens",
            formatter: formatCompact,
            empty: "No model-level historical information for this period.",
            ariaLabel: "Token volume by model over time",
            tooltip: function (point, s) {
                return point.raw.date + " - " + (formatModelName(s.model) || "Unknown")
                    + ": " + formatNumber(point.values[s.index] || 0) + " tokens";
            }
        });

        renderKeys("bl-model-keys", top5.map(function (row) {
            return formatModelName(row.model) || "Unknown";
        }));
    }

    /* Ranked horizontal bars. The fill is a kw-progress driven by scaleX,
       never by width, as the design system requires. */
    function renderRankedBars(hostId, rows, options) {
        var host = $(hostId);
        clear(host);

        if (!rows || !rows.length) {
            host.appendChild(el("p", "bl-chart-note", options.empty));
            return;
        }

        var maxTokens = Math.max.apply(null, rows.map(function (row) {
            return Number(row.total_tokens || 0);
        })) || 0;

        rows.slice(0, 8).forEach(function (row) {
            var total = Number(row.total_tokens || 0);
            var ratio = maxTokens > 0 ? Math.max(0.03, total / maxTokens) : 0.03;

            var item = el("div", "bl-bar-row");
            var head = el("div", "bl-bar-head");

            var name = el("div", "bl-bar-name", options.name(row) || "Unknown");
            var sub = options.sub(row);
            if (sub) name.appendChild(el("span", "bl-bar-sub", sub));
            head.appendChild(name);
            head.appendChild(el("span", "bl-bar-metric", options.metric(row)));
            item.appendChild(head);

            var track = el("div", "kw-progress");
            track.setAttribute("aria-hidden", "true");
            var fill = el("div", "kw-progress-fill");
            fill.style.transform = "scaleX(" + ratio.toFixed(4) + ")";
            track.appendChild(fill);
            item.appendChild(track);

            host.appendChild(item);
        });
    }

    function renderModelTable(models) {
        var tbody = $("bl-model-table");
        clear(tbody);

        if (!models || !models.length) {
            var row = el("tr");
            var cell = el("td", null, "No model-level historical information for this period.");
            cell.colSpan = 4;
            row.appendChild(cell);
            tbody.appendChild(row);
            return;
        }

        models.slice(0, 12).forEach(function (model) {
            var tr = el("tr");
            var nameCell = el("td");
            nameCell.title = formatModelName(model.model) || "";
            nameCell.appendChild(el("strong", null, formatModelName(model.model) || "Unknown"));
            tr.appendChild(nameCell);
            tr.appendChild(el("td", "bl-num", formatNumber(model.request_count || 0)));
            tr.appendChild(el("td", "bl-num", formatCompact(model.total_tokens || 0)));
            tr.appendChild(el("td", "bl-num", formatMicroMyr(model.customer_charge_micro_myr || 0)));
            tbody.appendChild(tr);
        });
    }

    function renderTokenComposition(summary) {
        var input = Number(summary.input_tokens || 0);
        var output = Number(summary.output_tokens || 0);
        var total = input + output;

        $("bl-token-input").textContent = formatCompact(input);
        $("bl-token-output").textContent = formatCompact(output);

        var inputPct = total > 0 ? Math.round((input / total) * 100) : 0;
        $("bl-token-input-seg").style.width = total > 0 ? inputPct + "%" : "0%";
        $("bl-token-output-seg").style.width = total > 0 ? Math.max(0, 100 - inputPct) + "%" : "0%";
    }

    /* ══════════════════════════════════════════════════════════════════
       TOP-UP
       ══════════════════════════════════════════════════════════════════ */

    var selectedTopup = null;

    function setTopupError(message) {
        var node = $("bl-topup-error");
        node.textContent = message || "";
        node.hidden = !message;
        if (message) announce(message);
    }

    function selectTopup(button) {
        Array.prototype.forEach.call(
            $("bl-topup-amounts").querySelectorAll("[data-amount]"),
            function (b) { b.setAttribute("aria-pressed", String(b === button)); }
        );
        selectedTopup = button ? parseInt(button.getAttribute("data-amount"), 10) : null;
        var custom = $("bl-topup-custom");
        if (custom) custom.value = "";
        setTopupError("");
    }

    /* Parses to micro-MYR without ever touching a float: a string like
       "10.50" becomes 10500000 by integer arithmetic. */
    function parseMyrToMicro(value) {
        if (typeof value !== "string") return null;
        var s = value.trim();
        if (s === "") return null;
        if (!/^\d+(?:\.\d{1,2})?$/.test(s)) return null;
        var parts = s.split(".");
        var ringgit = parseInt(parts[0], 10);
        if (ringgit <= 0) return null;
        var sen = parts.length === 2 ? parseInt((parts[1] + "00").substring(0, 2), 10) : 0;
        var micro = ringgit * 1000000 + sen * 10000;
        return Number.isSafeInteger(micro) ? micro : null;
    }

    function resolveTopupAmount() {
        setTopupError("");
        if (selectedTopup) return selectedTopup;

        var custom = $("bl-topup-custom");
        var raw = custom ? custom.value.trim() : "";
        if (raw === "") {
            setTopupError("Please select an amount or enter a custom amount.");
            return null;
        }

        var micro = parseMyrToMicro(raw);
        if (micro === null) {
            setTopupError("Enter a valid positive amount (e.g. 10.50).");
            return null;
        }
        if (micro < 1010000) {
            setTopupError("Minimum is RM1.01.");
            return null;
        }
        if (micro % 10000 !== 0) {
            setTopupError("Amount must be in increments of RM0.01.");
            return null;
        }
        return micro;
    }

    function updateTopupAccess(isFree) {
        show($("bl-topup"), !isFree);
        show($("bl-topup-locked"), isFree);
        if (isFree) $("bl-topup-upgrade").href = "pricing.html" + botQuery();
    }

    async function createTopupCheckout() {
        var button = $("bl-topup-submit");
        if (!button || button.disabled) return;

        var amount = resolveTopupAmount();
        if (amount === null) return;

        button.disabled = true;
        button.textContent = "Creating Checkout…";

        function restore() {
            button.disabled = false;
            button.textContent = "Top Up Credit";
        }

        try {
            var attemptKey = sessionStorage.getItem("chip_topup_attempt_key");
            if (!attemptKey) {
                attemptKey = crypto.randomUUID();
                sessionStorage.setItem("chip_topup_attempt_key", attemptKey);
            }
            var res = await authenticatedFetch("/api/billing/chip/checkout", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Idempotency-Key": attemptKey },
                body: JSON.stringify({ amount_micro_myr: amount })
            });

            var body = {};
            try { body = await res.json(); } catch (_) { body = {}; }

            if (body.code === "checkout_restart_required") {
                sessionStorage.removeItem("chip_topup_attempt_key");
            }

            if (res.status === 401 || res.status === 403) {
                showError(body.message || "AI credit top-up is not available on your current plan.");
                restore();
                return;
            }

            if (!body || body.status !== "success" || !body.data || !body.data.checkout_url) {
                showError((body && body.message) || "Checkout creation failed.");
                restore();
                return;
            }

            var ref = body.data.order_reference;
            if (typeof ref !== "string" || !ref.length) {
                showError("Checkout response missing order reference.");
                restore();
                return;
            }

            /* Stored before navigating away: the gateway's return URL is not
               guaranteed to carry the reference back. */
            sessionStorage.setItem("chip_pending_order_reference", ref);

            var url = body.data.checkout_url;
            if (url.indexOf("http://") === 0 || url.indexOf("https://") === 0) {
                window.location.assign(url);
            } else {
                showError("Invalid checkout URL returned.");
                restore();
            }
        } catch (_) {
            showError("Could not connect to server.");
            restore();
        }
    }

    /* ══════════════════════════════════════════════════════════════════
       PAYMENT RETURN + POLLING
       ══════════════════════════════════════════════════════════════════ */

    function normalizeUuid(value) {
        if (typeof value !== "string") return null;
        var s = value.trim().toLowerCase();
        if (/^[0-9a-f]{32}$/.test(s)) {
            s = s.replace(
                /^([0-9a-f]{8})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{12})$/,
                "$1-$2-$3-$4-$5"
            );
        }
        return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(s) ? s : null;
    }

    var RETURN_ICONS = {
        checking: "spinner",
        success: "check",
        processing: "clock",
        failed: "cross",
        cancelled: "slash",
        expired: "timer",
        error: "alert"
    };

    var RETURN_TONE = {
        checking: "is-checking",
        success: "is-success",
        processing: "is-warn",
        failed: "is-error",
        cancelled: "is-warn",
        expired: "is-warn",
        error: "is-error"
    };

    function showReturn(mode, title, detail) {
        var panel = $("bl-return");
        panel.className = "kw-panel bl-return " + (RETURN_TONE[mode] || "");
        panel.hidden = false;

        var host = $("bl-return-icon");
        clear(host);
        host.appendChild(icon(RETURN_ICONS[mode] || "alert", 18));

        $("bl-return-title").textContent = title || "";
        $("bl-return-detail").textContent = detail || "";
        announce(title + (detail ? ". " + detail : ""));
    }

    function showReturnRef(ref) {
        var node = $("bl-return-ref");
        if (ref) {
            node.textContent = "Order reference: " + ref;
            node.hidden = false;
        } else {
            node.hidden = true;
        }
    }

    function showRetryActivation(visible, ref) {
        var button = $("bl-return-activate");
        button.hidden = !visible;
        button.disabled = false;
        if (visible) showReturnRef(ref);
    }

    function stopPolling() {
        if (state.pollTimer) {
            clearTimeout(state.pollTimer);
            state.pollTimer = null;
        }
    }

    function resolveTopupRef() {
        var storedNorm = normalizeUuid(sessionStorage.getItem("chip_pending_order_reference"));
        var urlNorm = normalizeUuid(new URLSearchParams(window.location.search).get("order_id"));
        if (storedNorm && urlNorm && storedNorm !== urlNorm) {
            console.warn("Payment return: stored reference differs from URL reference; using stored.");
        }
        return storedNorm || urlNorm || null;
    }

    async function fetchTopupOrder(ref) {
        try {
            var res = await authenticatedFetch(
                "/api/billing/chip/orders/" + encodeURIComponent(ref));
            if (!res.ok) {
                if (res.status === 401 || res.status === 403) return { authError: true };
                return null;
            }
            var body = await res.json();
            if (!body || body.status !== "success" || !body.data) return null;

            /* A response describing a different order must never be shown as
               this one's outcome. */
            var returned = normalizeUuid(body.data.order_reference);
            if (!returned || returned !== ref) {
                console.warn("Payment return: response order_reference mismatch");
                return null;
            }
            return body.data;
        } catch (_) {
            return null;
        }
    }

    function clearTopupPending() {
        sessionStorage.removeItem("chip_pending_order_reference");
        sessionStorage.removeItem("chip_topup_attempt_key");
        state.pollRef = null;
    }

    function handleTopupResult(data) {
        if (!data) {
            showReturn("error", "Verification error",
                "We could not confirm the payment status. Your credit will only be added after payment is verified.");
            state.pollRef = state.pollRef || resolveTopupRef();
            return { terminal: false, showRetry: true };
        }

        var status = data.status || "";
        if (data.is_test === true && data.test_paid === true) {
            showReturn("success", "CHIP test payment completed.", "Test mode: no paid credit was added.");
            clearTopupPending();
            return { terminal: true, showRetry: false };
        }


        if (status === "credited" && data.credited === true) {
            showReturn("success", "Payment completed.", "Your AI credit has been added.");
            clearTopupPending();
            (async function () {
                var ok = await loadCredit();
                loadAnalytics();
                reloadTransactions();
                if (!ok) {
                    showReturn("success", "Payment completed.",
                        "Payment completed, but the latest balance could not be loaded. Refresh the page to view it.");
                }
            })();
            return { terminal: true, showRetry: false };
        }
        if (status === "credited") {
            showReturn("error", "Verification error",
                "We could not confirm the payment status. Your credit will only be added after payment is verified.");
            return { terminal: true, showRetry: true };
        }
        if (status === "paid") {
            showReturn("processing", "Payment received.",
                "Your payment was received and your AI credit is being applied.");
            return { terminal: false, showRetry: false };
        }
        if (status === "pending" || status === "claimed") {
            showReturn("processing", "Still processing.",
                "Your payment is still being processed. We are checking again automatically.");
            return { terminal: false, showRetry: false };
        }
        if (status === "failed") {
            showReturn("failed", "Payment not completed.",
                "The payment was not completed. No AI credit was added.");
            clearTopupPending();
            return { terminal: true, showRetry: false };
        }
        if (status === "cancelled") {
            showReturn("cancelled", "Payment cancelled.",
                "The payment was cancelled. No AI credit was added.");
            clearTopupPending();
            return { terminal: true, showRetry: false };
        }
        if (status === "expired") {
            showReturn("expired", "Payment session expired.",
                "The payment session expired. No AI credit was added.");
            clearTopupPending();
            return { terminal: true, showRetry: false };
        }

        showReturn("error", "Verification error",
            "We could not confirm the payment status. Your credit will only be added after payment is verified.");
        return { terminal: true, showRetry: true };
    }

    async function fetchSubscriptionOrder(ref) {
        try {
            var res = await authenticatedFetch(
                "/api/billing/subscription/orders/" + encodeURIComponent(ref));
            if (!res.ok) {
                if (res.status === 401 || res.status === 403) return { authError: true };
                return null;
            }
            var body = await res.json();
            if (!body || body.status !== "success" || !body.data) return null;
            return body.data;
        } catch (_) {
            return null;
        }
    }

    function handleSubscriptionResult(data) {
        if (!data) {
            showReturn("error", "Verification error",
                "We could not confirm the subscription payment status. Please check your subscription after a moment.");
            return { terminal: false, showRetry: true };
        }

        if (data.is_test === true && data.test_paid === true) {
            showReturn("success", "CHIP test payment completed.", "Test mode: your paid plan was not changed.");
            sessionStorage.removeItem("pending_subscription_order_reference");
            return { terminal: true, showRetry: false };
        }
        var status = data.status || "";
        var activation = data.activation_status || "";
        var retryAllowed = data.retry_allowed === true;
        var ref = data.order_reference || state.pollRef || "";

        if (status === "credited" && (activation === "completed" || activation === "")) {
            showReturn("success", "Subscription activated!",
                "Your plan is now active. AI credits and subscription information have been updated.");
            sessionStorage.removeItem("pending_subscription_order_reference");
            state.pollRef = null;
            showRetryActivation(false);
            loadPlan();
            loadCredit();
            loadAnalytics();
            return { terminal: true, showRetry: false };
        }

        if (status === "paid"
            && (activation === "not_started" || activation === "claimed" || activation === "")) {
            showReturn("processing", "Payment confirmed.",
                "Your payment was received. Activating your subscription...");
            showRetryActivation(false);
            return { terminal: false, showRetry: false };
        }

        if (activation === "activated" || activation === "credit_pending") {
            showReturn("processing", "Subscription activated.", "Completing AI credit allocation...");
            showRetryActivation(retryAllowed, ref);
            return { terminal: false, showRetry: retryAllowed };
        }

        if (data.reconciliation_required === true && retryAllowed) {
            showReturn("processing", "Activation needs retry.",
                "Payment confirmed, but activation needs another attempt.");
            showRetryActivation(true, ref);
            return { terminal: true, showRetry: true };
        }

        /* Flagged for reconciliation but not retryable from here - the order is
           stuck between us and the gateway. Saying "still processing" would be
           a lie by omission: nothing on this page will move it, the 15-minute
           reconcile job is what resolves it. Never assert the payment failed -
           an order reaches this state with the money already taken. */
        if (data.reconciliation_required === true) {
            showReturn("processing", "We are confirming this payment.",
                "We are checking this payment with the payment provider and will "
                + "apply it automatically once confirmed. If money left your account "
                + "it is not lost. Quote your order reference to support if this is "
                + "still unresolved after 24 hours.");
            showReturnRef(ref);
            showRetryActivation(false);
            return { terminal: true, showRetry: true };
        }

        if (activation === "conflict"
            || data.activation_error_code === "activation_already_claimed"
            || data.activation_error_code === "source_subscription_changed") {
            showReturn("error", "Support required.",
                "This payment needs support review. Please contact support with your order reference: "
                + (ref || "(unknown)"));
            showReturnRef(ref);
            sessionStorage.removeItem("pending_subscription_order_reference");
            return { terminal: true, showRetry: false };
        }

        if (status === "failed") {
            showReturn("failed", "Payment not completed.",
                "The payment was not completed and you have not been charged. No changes "
                + "were made to your subscription. You can start the upgrade again from "
                + "the Plans page.");
            sessionStorage.removeItem("pending_subscription_order_reference");
            state.pollRef = null;
            showRetryActivation(false);
            return { terminal: true, showRetry: false };
        }
        if (status === "cancelled") {
            showReturn("cancelled", "Payment cancelled.",
                "The subscription upgrade was cancelled. Your plan remains unchanged.");
            sessionStorage.removeItem("pending_subscription_order_reference");
            state.pollRef = null;
            showRetryActivation(false);
            return { terminal: true, showRetry: false };
        }
        if (status === "expired") {
            showReturn("expired", "Payment session expired.",
                "The payment session expired. No changes were made to your subscription.");
            sessionStorage.removeItem("pending_subscription_order_reference");
            state.pollRef = null;
            showRetryActivation(false);
            return { terminal: true, showRetry: false };
        }
        if (status === "pending") {
            showReturn("processing", "Still processing.",
                "Your subscription payment is still being processed.");
            showRetryActivation(false);
            return { terminal: false, showRetry: false };
        }

        showReturn("error", "Verification error",
            "We could not confirm the subscription payment status.");
        return { terminal: true, showRetry: true };
    }

    async function pollOnce() {
        if (!state.pollRef) return { terminal: true, showRetry: false };
        var isTopup = state.pollMode === "topup";
        var data = isTopup
            ? await fetchTopupOrder(state.pollRef)
            : await fetchSubscriptionOrder(state.pollRef);
        if (data && data.authError === true) return { terminal: true, showRetry: true };
        return isTopup ? handleTopupResult(data) : handleSubscriptionResult(data);
    }

    /* Bounded polling: five attempts three seconds apart, then it hands the
       user a manual re-check rather than looping forever. */
    function startPolling(mode) {
        stopPolling();
        state.pollMode = mode;
        state.pollCount = 0;
        show($("bl-return-check"), false);

        showReturn("checking", mode === "topup"
            ? "Checking your payment status..."
            : "Checking your subscription payment status...", "");

        function settle(result) {
            if (result.terminal) {
                stopPolling();
                if (result.showRetry) show($("bl-return-check"), true);
                return;
            }
            if (state.pollCount >= POLL_MAX) {
                showReturn("processing", "Still processing.", mode === "topup"
                    ? "Please wait - your balance will update once payment is verified. You can also check again below."
                    : "Please wait - your subscription will update once payment is verified. You can also check again below.");
                show($("bl-return-check"), true);
                return;
            }
            state.pollCount++;
            state.pollTimer = setTimeout(function () {
                pollOnce().then(settle);
            }, POLL_INTERVAL_MS);
        }

        pollOnce().then(settle);
    }

    function manualRecheck() {
        var button = $("bl-return-check");
        if (button && button.disabled) return;
        if (button) button.disabled = true;
        startPolling(state.pollMode || "topup");
        if (button) setTimeout(function () { button.disabled = false; }, 2000);
    }

    async function retryActivationFromReturn() {
        var button = $("bl-return-activate");
        var ref = state.pollRef;
        if (!ref) {
            showReturn("error", "Retry failed.", "Could not identify the order to retry.");
            return;
        }
        if (button) { button.disabled = true; button.textContent = "Retrying…"; }

        function restore() {
            if (button) { button.disabled = false; button.textContent = "Retry Activation"; }
        }

        try {
            var res = await authenticatedFetch(
                "/api/billing/subscription/orders/" + encodeURIComponent(ref) + "/retry",
                { method: "POST" });
            var body = {};
            try { body = await res.json(); } catch (_) { body = {}; }

            if (!res.ok) {
                if (res.status === 409) {
                    showReturn("error", "Support required.",
                        body.message || "This payment needs support review. Please contact support.");
                } else {
                    showReturn("error", "Retry failed.",
                        "The retry attempt failed. Please try again or contact support.");
                }
                restore();
                return;
            }

            if (body.status === "success") {
                showRetryActivation(false);
                state.pollRef = ref;
                startPolling("subscription");
            } else {
                showReturn("error", "Retry had an issue.",
                    body.message || "Please try again or contact support.");
                restore();
            }
        } catch (_) {
            showReturn("error", "Network error.", "Could not reach the server. Please try again.");
            restore();
        }
    }

    function cleanupReturnParams() {
        var params = new URLSearchParams(window.location.search);
        var changed = false;
        ["status_id", "billcode", "order_id"].forEach(function (key) {
            if (params.has(key)) { params.delete(key); changed = true; }
        });
        if (!changed) return;
        var qs = params.toString();
        var url = window.location.pathname + (qs ? "?" + qs : "") + (window.location.hash || "");
        window.history.replaceState(null, "", url);
    }

    function handleChipReturn() {
        /* A pending subscription return owns this page load. Neither an
           order_id query parameter nor a leftover top-up reference says which
           flow the customer came back from, and the top-up status endpoint
           answers 404 for a subscription order - handleTopupResult() then tells
           a customer whose money was taken that the payment is unverified. */
        if (sessionStorage.getItem("pending_subscription_order_reference")) {
            cleanupReturnParams();
            return;
        }

        var params = new URLSearchParams(window.location.search);
        if (!params.has("order_id") && !sessionStorage.getItem("chip_pending_order_reference")) return;

        var ref = resolveTopupRef();
        if (!ref) {
            showReturn("error", "Could not identify order.",
                "We could not identify the returned top-up order. Please check your credit balance or try again.");
            cleanupReturnParams();
            return;
        }
        state.pollRef = ref;
        startPolling("topup");
        cleanupReturnParams();
    }

    function handleSubscriptionReturn() {
        var stored = sessionStorage.getItem("pending_subscription_order_reference");
        if (!stored) return;
        var norm = normalizeUuid(stored);
        if (!norm) {
            console.warn("Subscription return: invalid stored reference");
            sessionStorage.removeItem("pending_subscription_order_reference");
            return;
        }
        state.pollRef = norm;
        startPolling("subscription");
    }

    /* ══════════════════════════════════════════════════════════════════
       4. BILLING HISTORY
       ══════════════════════════════════════════════════════════════════ */

    function orderRow(order) {
        var ref = order.order_reference || "";
        var tr = el("tr");

        tr.appendChild(el("td", null, formatDate(order.created_at)));
        tr.appendChild(el("td", null, (order.plan && order.plan.name) || "—"));

        var amount = order.amount_myr !== undefined && order.amount_myr !== null
            ? order.amount_myr
            : (order.amount_sen || 0) / 100;
        tr.appendChild(el("td", "bl-num", formatMyr(amount)));

        var payCell = el("td");
        payCell.appendChild(paymentPill(order.payment_status));
        tr.appendChild(payCell);

        var actCell = el("td");
        actCell.appendChild(activationPill(order.activation_status, order.reconciliation_required));
        tr.appendChild(actCell);

        var refCell = el("td", "bl-ref", ref.length > 8 ? ref.substring(0, 8) + "…" : ref);
        refCell.title = ref;
        tr.appendChild(refCell);

        var actions = el("div", "bl-row-actions");

        var view = el("button", "kw-btn cr-press", "View");
        view.type = "button";
        view.addEventListener("click", function () { openOrderDetail(ref); });
        actions.appendChild(view);

        if (order.retry_allowed) {
            var retry = el("button", "kw-btn cr-press", "Retry");
            retry.type = "button";
            retry.addEventListener("click", function () { retryOrder(ref, retry); });
            actions.appendChild(retry);
        }

        /* A receipt only exists once money has actually landed and the order
           has finished activating. */
        var settled = (order.payment_status === "paid" || order.payment_status === "credited")
            && (order.activation_status === "completed" || order.activation_status === "credited");
        var receipt = el("button", "kw-btn cr-press", "Receipt");
        receipt.type = "button";
        receipt.disabled = !settled;
        if (!settled) receipt.title = "Available once the payment has been completed";
        receipt.addEventListener("click", function () { openReceipt(ref); });
        actions.appendChild(receipt);

        var actionCell = el("td");
        actionCell.appendChild(actions);
        tr.appendChild(actionCell);

        return tr;
    }

    async function loadOrders(append) {
        if (state.orderLoading) return;
        state.orderLoading = true;

        if (!append) {
            state.orderOffset = 0;
            state.orderTotal = 0;
            show($("bl-orders-loading"), true);
            show($("bl-orders-wrap"), false);
            show($("bl-orders-empty"), false);
            show($("bl-orders-error"), false);
        }

        try {
            var res = await authenticatedFetch(
                "/api/billing/subscription/orders?limit=" + PAGE_SIZE + "&offset=" + state.orderOffset);
            var body = null;
            try { body = await res.json(); } catch (_) { body = null; }

            if (!res.ok || !body || body.status !== "success") {
                show($("bl-orders-loading"), false);
                if (!append) {
                    $("bl-orders-error-text").textContent =
                        (body && body.message) || "Unable to load payment history.";
                    show($("bl-orders-error"), true);
                }
                state.orderLoading = false;
                return false;
            }

            var orders = (body.data && body.data.orders) || [];
            var pagination = (body.data && body.data.pagination) || {};
            state.orderHasMore = pagination.has_more === true;

            show($("bl-orders-loading"), false);

            if (!append && orders.length === 0) {
                show($("bl-orders-empty"), true);
                state.orderLoading = false;
                return true;
            }

            var tbody = $("bl-orders-tbody");
            if (!append) clear(tbody);
            orders.forEach(function (order) { tbody.appendChild(orderRow(order)); });

            state.orderOffset += orders.length;
            state.orderTotal += orders.length;

            $("bl-orders-count").textContent = state.orderTotal + " shown";
            show($("bl-orders-more"), state.orderHasMore);
            show($("bl-orders-nomore"), !state.orderHasMore && state.orderTotal > 0);
            show($("bl-orders-wrap"), true);
            return true;
        } catch (_) {
            show($("bl-orders-loading"), false);
            if (!append) {
                $("bl-orders-error-text").textContent = "Network error loading payment history.";
                show($("bl-orders-error"), true);
            }
            return false;
        } finally {
            state.orderLoading = false;
        }
    }

    async function loadMoreOrders() {
        var button = $("bl-orders-more");
        button.disabled = true;
        button.textContent = "Loading…";
        var ok = await loadOrders(true);
        button.disabled = false;
        button.textContent = "Load More";
        if (!ok) state.orderOffset = Math.max(0, state.orderOffset);
    }

    function detailRow(list, term, value) {
        if (value === null || value === undefined || value === "") return;
        list.appendChild(el("dt", null, term));
        if (value instanceof Node) {
            var dd = el("dd");
            dd.appendChild(value);
            list.appendChild(dd);
        } else {
            list.appendChild(el("dd", "kw-mono", value));
        }
    }

    async function openOrderDetail(ref) {
        var body = $("bl-order-body");
        clear(body);
        body.appendChild(el("p", "bl-chart-note", "Loading…"));
        state.activeOrderRef = ref;
        show($("bl-order-retry"), false);
        show($("bl-order-receipt"), false);
        window.kwDialog.open($("bl-order-modal"), $("bl-order-dismiss"));

        var data = await getJson("/api/billing/subscription/orders/" + encodeURIComponent(ref));
        clear(body);

        if (!data) {
            body.appendChild(el("p", "bl-chart-note", "Failed to load order details."));
            return;
        }

        var plan = data.plan || {};
        var amount = data.amount_myr !== undefined && data.amount_myr !== null
            ? data.amount_myr
            : (data.amount_sen || 0) / 100;

        var list = el("dl", "kw-deflist");
        detailRow(list, "Plan", el("strong", null, plan.name || "—"));
        detailRow(list, "Amount", formatMyr(amount));
        detailRow(list, "Order Ref", data.order_reference);
        detailRow(list, "Payment Ref", data.payment_reference);
        detailRow(list, "Gateway Ref", data.gateway_order_id);
        detailRow(list, "Payment Status", paymentPill(data.status));
        detailRow(list, "Activation Status",
            activationPill(data.activation_status, data.reconciliation_required));
        detailRow(list, "Created", formatDateTime(data.created_at));
        if (data.paid_at) detailRow(list, "Paid At", formatDateTime(data.paid_at));
        if (data.credited_at) detailRow(list, "Credited At", formatDateTime(data.credited_at));
        body.appendChild(list);

        if (data.message) body.appendChild(el("p", "bl-order-note", data.message));

        if (data.reconciliation_required && !data.retry_allowed) {
            body.appendChild(el("p", "bl-order-note is-error",
                "Please contact support with your order reference."));
        }

        show($("bl-order-retry"), data.retry_allowed === true);

        var settled = (data.status === "paid" || data.status === "credited")
            && (data.activation_status === "completed" || data.activation_status === "credited");
        show($("bl-order-receipt"), settled);
    }

    async function retryOrder(ref, button) {
        if (!ref) return;
        var original = button ? button.textContent : "";
        if (button) { button.disabled = true; button.textContent = "Retrying…"; }

        function restore() {
            if (button) { button.disabled = false; button.textContent = original || "Retry"; }
        }

        try {
            var res = await authenticatedFetch(
                "/api/billing/subscription/orders/" + encodeURIComponent(ref) + "/retry",
                { method: "POST" });
            var body = {};
            try { body = await res.json(); } catch (_) { body = {}; }

            if (!res.ok) {
                restore();
                showError(res.status === 409
                    ? (body.message || "This payment needs support review.")
                    : "Retry failed. Please try again or contact support.");
                return;
            }

            if (body.status === "success") {
                window.kwDialog.close($("bl-order-modal"));
                announce("Payment rechecked.");
                clearError();
                state.orderOffset = 0;
                state.orderHasMore = true;
                loadOrders(false);
                state.pollRef = ref;
                startPolling("subscription");
            } else {
                restore();
                showError(body.message || "Retry had an issue.");
            }
        } catch (_) {
            restore();
            showError("Network error. Please try again.");
        }
    }

    /* The receipt is a server-rendered HTML document. It needs an
       authenticated fetch, so the tab is opened first (a popup blocker only
       trusts a direct click) and written into once the body arrives. */
    async function openReceipt(ref) {
        if (!ref) return;
        var tab = window.open("", "_blank");
        if (!tab) {
            showError("Please allow popups to view the receipt.");
            return;
        }
        tab.document.write("<!doctype html><title>Loading…</title><p>Loading receipt…</p>");
        tab.document.close();

        try {
            var res = await authenticatedFetch(
                "/api/billing/subscription/orders/" + encodeURIComponent(ref) + "/receipt/print");
            if (!res.ok) {
                tab.close();
                if (res.status === 401 || res.status === 403) {
                    showError("Session expired. Please refresh the page.");
                } else if (res.status === 404) {
                    showError("Receipt not found.");
                } else {
                    showError("Unable to load receipt. Please try again.");
                }
                return;
            }
            var html = await res.text();
            tab.document.open();
            tab.document.write(html);
            tab.document.close();
        } catch (_) {
            tab.close();
            showError("Network error loading receipt. Please try again.");
        }
    }

    /* ══════════════════════════════════════════════════════════════════
       5. CREDIT TRANSACTIONS
       ══════════════════════════════════════════════════════════════════ */

    function transactionRow(txn) {
        var type = txn.transaction_type || "";
        var label = type === "usage_debit"
            ? usageLabel(txn.ai_usage_type || txn.operation_type)
            : (TXN_TYPE_LABELS[type] || "Credit Activity");

        var tr = el("tr");
        tr.appendChild(el("td", null, label));

        /* Detail: free-text description plus whatever usage metadata the row
           carries. A legacy usage row with neither is labelled as such rather
           than left blank. */
        var detail = el("div", "bl-txn-detail");
        if (txn.description) detail.appendChild(el("div", "bl-txn-desc", txn.description));

        var meta = [];
        // Customers see the model name only, never the platform that served it.
        if (txn.model) meta.push("Model: " + formatModelName(txn.model));
        var prompt = Number(txn.prompt_tokens || 0);
        var completion = Number(txn.completion_tokens || 0);
        var total = Number(txn.total_tokens || 0) || (prompt + completion);
        if (total > 0) {
            meta.push("Input " + formatNumber(prompt));
            meta.push("Output " + formatNumber(completion));
            meta.push("Total " + formatNumber(total));
        } else if (type === "usage_debit" && txn.ai_usage_log_id && !txn.model && !txn.provider) {
            meta.push("Legacy usage metadata unavailable");
        }
        if (meta.length) {
            var metaNode = el("div", "bl-txn-meta");
            meta.slice(0, 5).forEach(function (text) {
                metaNode.appendChild(el("span", null, text));
            });
            detail.appendChild(metaNode);
        }
        var detailCell = el("td");
        detailCell.appendChild(detail);
        tr.appendChild(detailCell);

        var included = Number(txn.included_delta_micro_myr || 0);
        var topup = Number(txn.topup_delta_micro_myr || 0);
        var net = included + topup;
        var amountCell = el("td", "bl-num " + (net < 0 ? "bl-amount-debit" : "bl-amount-credit"),
            net === 0 ? "" : signedMicroMyr(net));
        tr.appendChild(amountCell);

        var incAfter = txn.included_balance_after_micro_myr;
        var topAfter = txn.topup_balance_after_micro_myr;
        var balance = (incAfter !== null && incAfter !== undefined
            && topAfter !== null && topAfter !== undefined)
            ? formatMicroMyr(Number(incAfter) + Number(topAfter))
            : "";
        tr.appendChild(el("td", "bl-num", balance));

        var when = "";
        if (txn.created_at) {
            var d = new Date(txn.created_at);
            if (!isNaN(d.getTime())) {
                when = d.toLocaleDateString() + " "
                    + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
            }
        }
        tr.appendChild(el("td", "bl-num", when));

        return tr;
    }

    async function loadTransactions(append) {
        if (state.txnLoading) return false;
        state.txnLoading = true;

        if (!append) {
            state.txnOffset = 0;
            state.txnTotal = 0;
            show($("bl-txn-loading"), true);
            show($("bl-txn-wrap"), false);
            show($("bl-txn-empty"), false);
        }
        show($("bl-txn-error"), false);

        try {
            var res = await authenticatedFetch(
                "/api/billing/ai-credit/transactions?limit=" + PAGE_SIZE + "&offset=" + state.txnOffset);
            var body = null;
            try { body = await res.json(); } catch (_) { body = null; }

            if (!res.ok || !body || body.status !== "success"
                || !body.data || !Array.isArray(body.data.transactions)) {
                show($("bl-txn-loading"), false);
                show($("bl-txn-error"), true);
                return false;
            }

            var txns = body.data.transactions;
            show($("bl-txn-loading"), false);

            if (!append && txns.length === 0) {
                show($("bl-txn-empty"), true);
                return true;
            }

            var tbody = $("bl-txn-tbody");
            if (!append) clear(tbody);

            /* One malformed row must not take the whole table down. */
            var rendered = 0;
            txns.forEach(function (txn) {
                try {
                    tbody.appendChild(transactionRow(txn));
                    rendered++;
                } catch (e) {
                    console.warn("Skipping invalid transaction row", e);
                }
            });

            if (rendered === 0 && txns.length > 0) {
                clear(tbody);
                show($("bl-txn-error"), true);
                return false;
            }

            state.txnOffset += txns.length;
            state.txnTotal += rendered;

            var hasMore = body.data.pagination
                && typeof body.data.pagination.has_more === "boolean"
                ? body.data.pagination.has_more
                : txns.length >= PAGE_SIZE;
            state.txnHasMore = hasMore;

            $("bl-txn-count").textContent = state.txnTotal + " shown";
            show($("bl-txn-more"), hasMore);
            show($("bl-txn-nomore"), !hasMore && state.txnTotal > 0);
            show($("bl-txn-wrap"), true);
            return true;
        } catch (_) {
            show($("bl-txn-loading"), false);
            show($("bl-txn-error"), true);
            return false;
        } finally {
            state.txnLoading = false;
        }
    }

    function reloadTransactions() {
        state.txnOffset = 0;
        state.txnHasMore = true;
        return loadTransactions(false);
    }

    async function loadMoreTransactions() {
        var button = $("bl-txn-more");
        button.disabled = true;
        button.textContent = "Loading…";
        var before = state.txnOffset;
        var ok = await loadTransactions(true);
        button.disabled = false;
        button.textContent = "Load More";
        if (!ok) state.txnOffset = before;
    }

    /* ══════════════════════════════════════════════════════════════════
       EXPORTS
       ══════════════════════════════════════════════════════════════════ */

    async function downloadCsv(config) {
        if (state.exporting[config.key]) return;
        state.exporting[config.key] = true;

        var button = $(config.buttonId);
        var original = button ? button.textContent : "";
        if (button) { button.disabled = true; button.textContent = "Exporting…"; }

        try {
            var res = await authenticatedFetch(config.url);
            if (!res.ok) {
                showError(config.failure);
                return;
            }
            var blob = await res.blob();
            var url = URL.createObjectURL(blob);
            var link = el("a");
            link.href = url;
            link.download = config.filename + "-" + new Date().toISOString().slice(0, 10) + ".csv";
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
            announce("Export downloaded.");
        } catch (_) {
            showError(config.networkFailure || config.failure);
        } finally {
            state.exporting[config.key] = false;
            if (button) { button.disabled = false; button.textContent = original; }
        }
    }

    function exportOrders() {
        return downloadCsv({
            key: "orders",
            buttonId: "bl-orders-export",
            url: "/api/billing/subscription/orders/export.csv?limit=2000",
            filename: "subscription-payment-history",
            failure: "Unable to export data. Please try again later.",
            networkFailure: "Export failed. Please try again."
        });
    }

    function exportTransactions() {
        return downloadCsv({
            key: "transactions",
            buttonId: "bl-txn-export",
            url: "/api/billing/ai-credit/transactions/export.csv?limit=2000",
            filename: "ai-credit-activity",
            failure: "Unable to export data. Please try again later.",
            networkFailure: "Export failed. Please try again."
        });
    }

    var REPORT_MONTHS = {
        last_12_months: 12,
        last_6_months: 6,
        last_3_months: 3,
        current_month: 1
    };

    function reportMonths() {
        var select = $("bl-report-period");
        var value = select ? select.value : "last_6_months";
        return REPORT_MONTHS[value] || 3;
    }

    function exportReport() {
        return downloadCsv({
            key: "report",
            buttonId: "bl-report-export",
            url: "/api/billing/reports/export.csv?months=" + reportMonths(),
            filename: "billing-report",
            failure: "Unable to export report. Please try again.",
            networkFailure: "Network error exporting report. Please try again."
        });
    }

    /* ══════════════════════════════════════════════════════════════════
       6. NOTIFICATIONS
       ══════════════════════════════════════════════════════════════════ */

    var SEVERITY = {
        warning: { cls: "is-warning", icon: "alert" },
        critical: { cls: "is-critical", icon: "octagon" }
    };

    function notificationItem(notification) {
        var severity = SEVERITY[notification.severity] || { cls: "is-info", icon: "info" };
        var isRead = notification.is_read === true;

        var item = el("li", "bl-notif-item " + severity.cls + (isRead ? "" : " is-unread"));
        item.setAttribute("data-notification-id", notification.id);

        var iconWrap = el("span", "bl-notif-icon");
        iconWrap.setAttribute("aria-hidden", "true");
        iconWrap.appendChild(icon(severity.icon, 16));
        item.appendChild(iconWrap);

        var body = el("div");
        body.appendChild(el("div", "bl-notif-title", notification.title || ""));
        body.appendChild(el("div", "bl-notif-message", notification.message || ""));

        var meta = el("div", "bl-notif-meta");
        if (notification.severity) {
            meta.appendChild(el("span", "bl-notif-severity", notification.severity));
        }
        var when = formatNotificationTime(notification.created_at);
        if (when) meta.appendChild(el("span", null, when));
        if (!isRead) meta.appendChild(el("span", null, "Unread"));
        body.appendChild(meta);
        item.appendChild(body);

        if (!isRead) {
            var button = el("button", "kw-btn cr-press", "Mark read");
            button.type = "button";
            button.addEventListener("click", function () {
                markNotificationRead(notification.id, item, button);
            });
            item.appendChild(button);
        } else {
            item.appendChild(el("span"));
        }

        return item;
    }

    async function loadNotifications() {
        show($("bl-notif-loading"), true);
        show($("bl-notif-list"), false);
        show($("bl-notif-empty"), false);
        show($("bl-notif-error"), false);

        try {
            var res = await authenticatedFetch("/api/billing/notifications?limit=50");
            var body = await res.json();
            show($("bl-notif-loading"), false);

            if (!res.ok || !body || body.status !== "success") {
                show($("bl-notif-error"), true);
                return;
            }

            var notifications = body.data || [];
            if (!notifications.length) {
                show($("bl-notif-empty"), true);
                show($("bl-notif-readall"), false);
                return;
            }

            var list = $("bl-notif-list");
            clear(list);
            var hasUnread = false;
            notifications.forEach(function (notification) {
                if (notification.is_read !== true) hasUnread = true;
                list.appendChild(notificationItem(notification));
            });

            show(list, true);
            show($("bl-notif-readall"), hasUnread);
        } catch (_) {
            show($("bl-notif-loading"), false);
            show($("bl-notif-error"), true);
        }
    }

    async function markNotificationRead(id, item, button) {
        try {
            var res = await authenticatedFetch(
                "/api/billing/notifications/" + encodeURIComponent(id) + "/read",
                { method: "POST" });
            var body = await res.json();
            if (res.ok && body && body.status === "success") {
                if (item) item.classList.remove("is-unread");
                if (button) button.hidden = true;
                announce("Notification marked as read.");
                loadUnreadCount();
            }
        } catch (_) {
            /* Silently ignored, as before: the row stays unread and the user
               can click again. */
        }
    }

    async function markAllNotificationsRead() {
        try {
            var res = await authenticatedFetch("/api/billing/notifications/read-all",
                { method: "POST" });
            var body = await res.json();
            if (res.ok && body && body.status === "success") {
                announce("All notifications marked as read.");
                loadNotifications();
                loadUnreadCount();
            }
        } catch (_) { /* Silently ignored, as before. */ }
    }

    async function loadUnreadCount() {
        try {
            var res = await authenticatedFetch("/api/billing/notifications/unread-count");
            var body = await res.json();
            if (!res.ok || !body || body.status !== "success") return;
            var count = body.data && body.data.unread_count;
            var badge = $("bl-notif-unread");
            if (count > 0) {
                badge.textContent = count > 99 ? "99+" : String(count);
                badge.hidden = false;
            } else {
                badge.hidden = true;
            }
        } catch (_) { /* Silently ignored, as before. */ }
    }

    /* ══════════════════════════════════════════════════════════════════
       7. REPORTS
       ══════════════════════════════════════════════════════════════════ */

    function renderTrend(months) {
        var tbody = $("bl-trend-tbody");
        clear(tbody);

        if (!months || !months.length) {
            var row = el("tr");
            var cell = el("td", null, "No monthly data available.");
            cell.colSpan = 6;
            row.appendChild(cell);
            tbody.appendChild(row);
            drawChart($("bl-trend-chart"), [], [], {
                yLabel: "RM", empty: "No monthly data available.", tooltip: function () { return ""; }
            });
            renderKeys("bl-trend-keys", []);
            return;
        }

        months.forEach(function (month) {
            var tr = el("tr");
            tr.appendChild(el("td", null, month.month || ""));
            tr.appendChild(el("td", "bl-num", formatMyr(month.subscription_payments_myr || 0)));
            tr.appendChild(el("td", "bl-num", formatMyr(month.credit_spent_myr || 0)));
            /* The API spells this field with a capitalised prefix. */
            tr.appendChild(el("td", "bl-num", formatNumber(month.AI_requests || 0)));
            tr.appendChild(el("td", "bl-num", formatNumber(month.total_tokens || 0)));
            tr.appendChild(el("td", "bl-num", formatMyr(month.customer_charge_myr || 0)));
            tbody.appendChild(tr);
        });

        drawChart($("bl-trend-chart"), months.map(function (month) {
            return {
                label: month.month || "",
                raw: month,
                values: [
                    Number(month.subscription_payments_myr || 0),
                    Number(month.credit_spent_myr || 0)
                ]
            };
        }), [
            { index: 0, cls: "bl-series-0" },
            { index: 1, cls: "bl-series-2" }
        ], {
            yLabel: "RM",
            formatter: function (v) { return Number(v).toFixed(0); },
            empty: "No monthly data available.",
            ariaLabel: "Subscription payments and credit spend by month",
            tooltip: function (point, s) {
                return point.label + " - " + (s.index === 0 ? "Payments " : "Credit spent ")
                    + formatMyr(point.values[s.index]);
            }
        });
        renderKeys("bl-trend-keys", ["Subscription payments", "AI credit spent"]);
    }

    async function loadReport() {
        show($("bl-report-loading"), true);
        show($("bl-report-content"), false);
        show($("bl-report-empty"), false);
        show($("bl-report-error"), false);

        var period = $("bl-report-period").value;

        try {
            var res = await authenticatedFetch(
                "/api/billing/reports/summary?period=" + encodeURIComponent(period));
            var body = await res.json();
            show($("bl-report-loading"), false);

            if (!res.ok || !body || body.status !== "success") {
                show($("bl-report-error"), true);
                return;
            }

            var report = body.data;
            if (!report) {
                show($("bl-report-empty"), true);
                return;
            }

            var subscription = report.subscription || {};
            var credit = report.ai_credit || {};
            var usage = report.ai_usage || {};

            var stats = $("bl-report-stats");
            clear(stats);
            stats.appendChild(statCard("Payments",
                formatMyr(subscription.gross_paid_myr || 0),
                (subscription.payments_completed || 0) + " paid"));
            stats.appendChild(statCard("Credit Spent", formatMyr(credit.usage_spent_myr || 0)));
            stats.appendChild(statCard("AI Requests", formatNumber(usage.requests || 0)));
            stats.appendChild(statCard("Tokens", formatNumber(usage.total_tokens || 0)));

            show($("bl-report-content"), true);

            var trend = await getJson("/api/billing/reports/monthly?months=6");
            if (trend) {
                renderTrend(trend);
            } else {
                var tbody = $("bl-trend-tbody");
                clear(tbody);
                var row = el("tr");
                var cell = el("td", null, "Unable to load trend data.");
                cell.colSpan = 6;
                row.appendChild(cell);
                tbody.appendChild(row);
            }
        } catch (_) {
            show($("bl-report-loading"), false);
            show($("bl-report-error"), true);
        }
    }

    /* ══════════════════════════════════════════════════════════════════
       WIRING
       ══════════════════════════════════════════════════════════════════ */

    /* A kw-segment is a radiogroup: kw-a11y moves focus with the arrow keys,
       this carries the selection and fires the change. */
    function wireSegment(id, attribute, onChange) {
        var group = $(id);
        if (!group) return;
        group.addEventListener("click", function (event) {
            var button = event.target.closest("[role=radio]");
            if (!button || button.getAttribute("aria-checked") === "true") return;
            Array.prototype.forEach.call(group.querySelectorAll("[role=radio]"), function (b) {
                var selected = b === button;
                b.setAttribute("aria-checked", String(selected));
                b.tabIndex = selected ? 0 : -1;
            });
            onChange(button.getAttribute(attribute));
        });
    }

    function wire() {
        $("bl-retry").addEventListener("click", function () {
            clearError();
            loadAll();
        });

        /* Plan */
        $("bl-credit-retry").addEventListener("click", function () { loadCredit(); });
        $("bl-analytics-retry").addEventListener("click", function () { loadAnalytics(); });

        /* Credits */
        wireSegment("bl-range", "data-days", function (days) {
            state.days = days;
            loadAnalytics();
        });
        wireSegment("bl-metric", "data-metric", function (metric) {
            state.metric = metric;
            renderMainChart();
        });

        FILTER_FIELDS.forEach(function (pair) {
            var node = $(pair[1]);
            if (node) node.addEventListener("change", function () { loadAnalytics(); });
        });
        $("bl-filter-reset").addEventListener("click", function () {
            FILTER_FIELDS.forEach(function (pair) {
                var node = $(pair[1]);
                if (node) node.value = "";
            });
            loadAnalytics();
        });

        /* Top-up */
        Array.prototype.forEach.call(
            $("bl-topup-amounts").querySelectorAll("[data-amount]"),
            function (button) {
                button.addEventListener("click", function () { selectTopup(button); });
            }
        );
        $("bl-topup-custom").addEventListener("input", function () {
            Array.prototype.forEach.call(
                $("bl-topup-amounts").querySelectorAll("[data-amount]"),
                function (b) { b.setAttribute("aria-pressed", "false"); }
            );
            selectedTopup = null;
            setTopupError("");
        });
        $("bl-topup-submit").addEventListener("click", createTopupCheckout);

        /* Payment return */
        $("bl-return-check").addEventListener("click", manualRecheck);
        $("bl-return-activate").addEventListener("click", retryActivationFromReturn);

        /* Orders — the old page rendered this button but never bound it. */
        $("bl-orders-more").addEventListener("click", loadMoreOrders);
        $("bl-orders-retry").addEventListener("click", function () { loadOrders(false); });
        $("bl-orders-export").addEventListener("click", exportOrders);

        /* Transactions */
        $("bl-txn-more").addEventListener("click", loadMoreTransactions);
        $("bl-txn-retry").addEventListener("click", reloadTransactions);
        $("bl-txn-export").addEventListener("click", exportTransactions);

        /* Notifications */
        $("bl-notif-retry").addEventListener("click", function () { loadNotifications(); });
        $("bl-notif-readall").addEventListener("click", markAllNotificationsRead);

        /* Reports */
        $("bl-report-load").addEventListener("click", loadReport);
        $("bl-report-retry").addEventListener("click", loadReport);
        $("bl-report-export").addEventListener("click", exportReport);

        /* Modals */
        $("bl-confirm-ok").addEventListener("click", function () { settleConfirm(true); });
        $("bl-confirm-cancel").addEventListener("click", function () { settleConfirm(false); });
        $("bl-confirm-close").addEventListener("click", function () { settleConfirm(false); });
        $("bl-confirm").addEventListener("click", function (event) {
            if (event.target === event.currentTarget) settleConfirm(false);
        });

        function closeOrderModal() { window.kwDialog.close($("bl-order-modal")); }
        $("bl-order-close").addEventListener("click", closeOrderModal);
        $("bl-order-dismiss").addEventListener("click", closeOrderModal);
        $("bl-order-modal").addEventListener("click", function (event) {
            if (event.target === event.currentTarget) closeOrderModal();
        });
        $("bl-order-retry").addEventListener("click", function () {
            retryOrder(state.activeOrderRef, $("bl-order-retry"));
        });
        $("bl-order-receipt").addEventListener("click", function () {
            openReceipt(state.activeOrderRef);
        });

        /* kw-a11y supplies the focus trap and focus restore but not Escape,
           which every page wires for itself. Topmost dialog closes first. */
        document.addEventListener("keydown", function (event) {
            if (event.key !== "Escape") return;
            if (window.kwDialog.isOpen($("bl-confirm"))) { settleConfirm(false); return; }
            if (window.kwDialog.isOpen($("bl-order-modal"))) closeOrderModal();
        });

        if (typeof window.kwRadioGroup === "function") window.kwRadioGroup(document);
    }

    function loadAll() {
        loadPlan();
        loadCredit();
        loadAnalytics();
        loadOrders(false);
        loadTransactions(false);
        loadNotifications();
        loadUnreadCount();
        loadReport();
    }

    function start() {
        wire();
        loadAll();
        /* Both return paths are checked: a top-up comes back with query
           params, a subscription upgrade with a stored reference. */
        handleChipReturn();
        handleSubscriptionReturn();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
