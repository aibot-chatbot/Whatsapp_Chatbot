/* ══════════════════════════════════════════════════════════════════════
   PRICING — usage-first upgrade console

   Reading order mirrors the question a paying tenant actually asks:
   "am I running out of anything?" -> "which plan fixes that?" -> "what
   exactly changes if I move?". Plans come last, not first.

   Every figure here is produced by an API. Per DESIGN.md's Preserve-truth
   principle nothing is inferred, and a dimension the backend cannot report
   is hidden rather than guessed at.

   DOM contract: tests/browser/landing-pricing.spec.js pins .plan-card
   (exactly four), .plan-name, .plan-price, .plan-desc, and twelve
   [data-feature-key] rows per card whose final five are the approved
   customer-facing flags in order. Collapsed tiers stay in the DOM.
   ══════════════════════════════════════════════════════════════════════ */

(function () {
    "use strict";

    var PLAN_RANK = { free: 0, essential: 1, advanced: 2, pro: 3 };

    /* Order is asserted by the spec: these five must be the last five
       [data-feature-key] rows in every card. */
    var CUSTOMER_FEATURE_FLAGS = [
        "ai_assisted_menu_generation",
        "ai_generated_reports",
        "crm_lead_assignment",
        "single_website_scraping",
        "batch_website_scraping"
    ];

    var FLAG_LABELS = {
        ai_assisted_menu_generation: "AI-Assisted Menu Generation",
        ai_generated_reports: "AI-Generated Reports",
        crm_lead_assignment: "CRM Lead Assignment",
        single_website_scraping: "Single Website Scraping",
        batch_website_scraping: "Batch Website Scraping"
    };

    /* The usage dimensions /api/billing/usage can actually report, in
       reading order. `plan` names the matching field on a plan object, used
       to compute the upgrade diff. */
    var METERS = [
        { key: "chatbots", label: "Chatbots", plan: "chatbot_limit", icon: "bot" },
        { key: "team_members", label: "Team members", plan: "team_member_limit", icon: "users" },
        { key: "channels", label: "Channels", plan: "channel_limit", icon: "plug" },
        { key: "knowledge_files", label: "Knowledge files", plan: "knowledge_file_limit", icon: "file" },
        {
            key: "knowledge_storage_bytes",
            label: "Storage",
            plan: "knowledge_storage_limit_bytes",
            icon: "database",
            bytes: true
        }
    ];

    /* Inline paths, so the page owns its own icons rather than waiting on a
       CDN. All use a 0 0 24 24 viewBox. */
    var ICON_PATHS = {
        bot: "M12 8V4H8M4 8h16v12H4zM2 14h2M20 14h2M9 13v2M15 13v2",
        users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM22 21v-2a4 4 0 0 0-3-3.87",
        plug: "M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4",
        file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
        database: "M12 3c4.97 0 9 1.34 9 3s-4.03 3-9 3-9-1.34-9-3 4.03-3 9-3zM3 6v12c0 1.66 4.03 3 9 3s9-1.34 9-3V6M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3",
        coin: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v10M9.5 9.5h5M9.5 14.5h5",
        check: "m20 6-11 11-5-5",
        cross: "M18 6 6 18M6 6l12 12",
        arrow: "M5 12h14m-6-6 6 6-6 6",
        spark: "m12 3 2.1 6.5H21l-5.5 4 2.1 6.5-5.6-4-5.6 4 2.1-6.5-5.5-4h6.9z",
        alert: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
        chevron: "m6 9 6 6 6-6"
    };

    var state = {
        plans: [],
        subscription: null,
        usage: null,
        credit: null,
        currentCode: null
    };

    /* ── small helpers ─────────────────────────────────────────────── */

    function $(id) { return document.getElementById(id); }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function icon(name, size) {
        var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", "dashboard-icon");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("aria-hidden", "true");
        if (size) {
            svg.setAttribute("width", String(size));
            svg.setAttribute("height", String(size));
        }
        var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", ICON_PATHS[name] || ICON_PATHS.check);
        svg.appendChild(path);
        return svg;
    }

    /* Dates follow the viewer's locale rather than the hardcoded en-US the
       old page used. */
    function formatDate(value) {
        if (!value) return null;
        var d = new Date(value);
        if (isNaN(d.getTime())) return null;
        try {
            return new Intl.DateTimeFormat(undefined, {
                year: "numeric", month: "short", day: "numeric"
            }).format(d);
        } catch (_) {
            return d.toDateString();
        }
    }

    /* Money stays hand-formatted rather than using Intl currency style: the
       published contract (and the pricing spec) expects the literal
       "RM 39.00" form, whereas Intl renders MYR as "MYR 39.00" in most
       locales. A non-MYR plan falls back to its own code so the symbol is
       never a lie — the old page read plan.currency and then ignored it. */
    function formatMoney(amount, currency) {
        var code = (currency || "MYR").toUpperCase();
        var symbol = code === "MYR" ? "RM" : code;
        return symbol + " " + Number(amount).toFixed(2);
    }

    function microToMyr(micro) {
        return Number(micro || 0) / 1000000;
    }

    /* Binary units, matching what the backend stores: 1 GB here means
       1073741824 bytes, which is what knowledge_storage_limit_bytes uses. */
    function formatBytes(value) {
        var n = Number(value || 0);
        if (n >= 1073741824) return (n / 1073741824).toFixed(n % 1073741824 === 0 ? 0 : 1) + " GB";
        if (n >= 1048576) return (n / 1048576).toFixed(n % 1048576 === 0 ? 0 : 1) + " MB";
        if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
        return n + " B";
    }

    function pluralize(value, singular, plural) {
        return value === 1 ? singular : plural;
    }

    /* /api/billing/usage and /api/billing/subscription both answer 200 with
       data:null for a company with no subscription, and an unmocked route in
       the test harness answers with data:[]. Neither is a readable object,
       so both collapse to null here. */
    function asObject(value) {
        if (!value || typeof value !== "object" || Array.isArray(value)) return null;
        return value;
    }

    async function getJson(url) {
        try {
            var res = await authenticatedFetch(url);
            var body = await res.json();
            if (!body || body.status !== "success") return null;
            return body.data;
        } catch (_) {
            return null;
        }
    }

    function titleCase(value) {
        var s = String(value || "");
        return s.charAt(0).toUpperCase() + s.slice(1);
    }

    /* ── announcements and errors ──────────────────────────────────── */

    function announce(message) {
        var node = $("pri-announce");
        if (node) node.textContent = message;
    }

    /* Replaces the four alert() calls the old page used. A banner is
       dismissible, styleable, announced to screen readers, and does not
       block the main thread. */
    function showError(message) {
        var banner = $("pricing-error");
        var text = $("pricing-error-text");
        if (!banner || !text) return;
        text.textContent = message;
        banner.hidden = false;
        announce(message);
    }

    function clearError() {
        var banner = $("pricing-error");
        if (banner) banner.hidden = true;
    }

    /* ── usage meters ──────────────────────────────────────────────── */

    function meterRow(spec, used, limit) {
        var row = el("div", "pri-meter-row");

        var label = el("div", "pri-meter-label");
        label.appendChild(icon(spec.icon, 16));
        label.appendChild(el("span", null, spec.label));
        row.appendChild(label);

        var track = el("div", "pri-meter-track");
        var figures = el("div", "pri-meter-figures");

        var unlimited = limit === null || limit === undefined;
        var usedText = spec.bytes ? formatBytes(used) : String(used);

        if (unlimited) {
            track.appendChild(el("div", "pri-meter-none"));
            figures.appendChild(el("span", null, usedText + " "));
            figures.appendChild(el("span", "pri-meter-limit", "/ Unlimited"));
        } else {
            var ratio = limit > 0 ? Math.min(used / limit, 1) : (used > 0 ? 1 : 0);
            var meter = el("div", "cr-meter");
            var fill = el("div", "cr-meter-fill");
            fill.style.setProperty("--cr-meter-value", String(ratio));

            /* Thresholds carry a word as well as a colour: DESIGN.md forbids
               a state signalled by colour alone. */
            var atLimit = used >= limit;
            var stateWord = null;
            if (atLimit) {
                fill.classList.add("is-full");
                stateWord = "At limit";
            } else if (ratio >= 0.8) {
                fill.classList.add("is-warn");
                stateWord = "Nearly full";
            }

            meter.appendChild(fill);
            meter.setAttribute("aria-hidden", "true");
            track.appendChild(meter);

            figures.appendChild(el("span", null, usedText + " "));
            figures.appendChild(
                el("span", "pri-meter-limit", "/ " + (spec.bytes ? formatBytes(limit) : limit))
            );
            if (stateWord) {
                figures.appendChild(
                    el("span", "pri-meter-state " + (atLimit ? "is-full" : "is-warn"), stateWord)
                );
            }
        }

        row.appendChild(track);
        row.appendChild(figures);
        return row;
    }

    /* The meter specs whose limit is under pressure, so the advice line and
       the recommended tier are driven by the same evidence. */
    function pressuredDimensions(usage) {
        var out = [];
        METERS.forEach(function (spec) {
            var entry = asObject(usage[spec.key]);
            if (!entry) return;
            var limit = entry.limit;
            if (limit === null || limit === undefined || limit <= 0) return;
            if (Number(entry.used || 0) / limit >= 0.8) out.push(spec);
        });
        return out;
    }

    function creditRow() {
        var credit = asObject(state.credit);
        if (!credit || !credit.initialised) return null;
        if (credit.total_balance_micro_myr === null ||
            credit.total_balance_micro_myr === undefined) return null;

        var plan = planFor(state.currentCode);
        var included = microToMyr(credit.included_balance_micro_myr);
        var topup = microToMyr(credit.topup_balance_micro_myr);
        var granted = plan ? microToMyr(plan.included_ai_credit_micro_myr) : 0;

        var row = el("div", "pri-meter-row");
        var label = el("div", "pri-meter-label");
        label.appendChild(icon("coin", 16));
        label.appendChild(el("span", null, "AI credit left"));
        row.appendChild(label);

        var track = el("div", "pri-meter-track");
        if (granted > 0) {
            var meter = el("div", "cr-meter");
            var fill = el("div", "cr-meter-fill");
            var ratio = Math.min(included / granted, 1);
            fill.style.setProperty("--cr-meter-value", String(ratio));
            if (ratio <= 0.2) fill.classList.add("is-warn");
            meter.appendChild(fill);
            meter.setAttribute("aria-hidden", "true");
            track.appendChild(meter);
        } else {
            track.appendChild(el("div", "pri-meter-none"));
        }
        row.appendChild(track);

        var figures = el("div", "pri-meter-figures");
        figures.appendChild(el("span", null, formatMoney(included, "MYR") + " "));
        figures.appendChild(el("span", "pri-meter-limit",
            granted > 0 ? "/ " + formatMoney(granted, "MYR") : "included"));
        if (topup > 0) {
            figures.appendChild(el("span", "pri-meter-state",
                "plus " + formatMoney(topup, "MYR") + " topped up"));
        }
        row.appendChild(figures);
        return row;
    }

    function renderMeters() {
        var host = $("pri-meters");
        var section = $("pri-usage-section");
        if (!host || !section) return;

        var usage = state.usage && asObject(state.usage.usage);
        host.replaceChildren();

        if (!usage) {
            /* No subscription, or usage unavailable. Hiding the section is
               more honest than drawing five empty bars. */
            section.hidden = true;
            return;
        }
        section.hidden = false;

        METERS.forEach(function (spec) {
            var entry = asObject(usage[spec.key]);
            if (!entry) return;
            host.appendChild(meterRow(spec, Number(entry.used || 0), entry.limit));
        });

        /* AI credit is money and comes from a different endpoint. It is
           never merged with usage.ai_tokens, which counts tokens. */
        var credit = creditRow();
        if (credit) host.appendChild(credit);

        renderAdvice(usage);
    }

    function renderAdvice(usage) {
        var host = $("pri-advice");
        if (!host) return;
        host.replaceChildren();

        var pressured = pressuredDimensions(usage);
        var target = recommendedPlan();

        if (!pressured.length) {
            host.appendChild(icon("check", 16));
            var ok = el("span");
            ok.appendChild(el("strong", null, "You have room on every limit."));
            ok.appendChild(document.createTextNode(
                " Nothing here needs a bigger plan right now."));
            host.appendChild(ok);
            return;
        }

        host.appendChild(icon("alert", 16));
        var names = pressured.map(function (s) { return s.label.toLowerCase(); });
        var joined = names.length === 1
            ? names[0]
            : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];

        var msg = el("span");
        msg.appendChild(el("strong", null,
            "You are close to your limit on " + joined + "."));
        if (target) {
            msg.appendChild(document.createTextNode(
                " " + (target.name || titleCase(target.code)) + " raises " +
                (pressured.length === 1 ? "it" : "them") + "."));
        }
        host.appendChild(msg);
    }

    /* ── plans ─────────────────────────────────────────────────────── */

    function planFor(code) {
        if (!code) return null;
        for (var i = 0; i < state.plans.length; i += 1) {
            if (String(state.plans[i].code || "").toLowerCase() === code) return state.plans[i];
        }
        return null;
    }

    function rankOf(code) {
        var r = PLAN_RANK[String(code || "").toLowerCase()];
        return r === undefined ? -1 : r;
    }

    function subscriptionStatus(sub) {
        return sub ? String(sub.effective_status || sub.status || "").toLowerCase() : "";
    }

    function isRenewableCurrentPlan(code) {
        var sub = asObject(state.subscription);
        var status = subscriptionStatus(sub);
        return code !== "free" && (status === "past_due" || status === "expired" ||
            (sub && (sub.can_renew === true || sub.renewal_required === true)));
    }

    /* The cheapest plan strictly above the current one that lifts every
       pressured limit. Falls back to the next tier up when usage is
       unknown, and to null when nothing is under pressure or the tenant is
       already on the top plan. */
    function recommendedPlan() {
        var usage = state.usage && asObject(state.usage.usage);
        var currentRank = rankOf(state.currentCode);
        var higher = state.plans.filter(function (p) {
            return rankOf(p.code) > currentRank;
        }).sort(function (a, b) { return rankOf(a.code) - rankOf(b.code); });

        if (!higher.length) return null;
        if (!usage) return higher[0];

        var pressured = pressuredDimensions(usage);
        if (!pressured.length) return null;

        for (var i = 0; i < higher.length; i += 1) {
            var plan = higher[i];
            var lifts = pressured.every(function (spec) {
                var entry = asObject(usage[spec.key]);
                var next = plan[spec.plan];
                if (next === null || next === undefined) return true;
                return Number(next) > Number(entry.limit);
            });
            if (lifts) return plan;
        }
        return higher[higher.length - 1];
    }

    /* ---- the twelve feature rows. The text formats below are asserted by
       the spec with toContain, so this wording is a contract. */

    function featureRow(key, enabled) {
        var li = el("li");
        li.dataset.featureKey = key;
        li.dataset.enabled = enabled ? "true" : "false";
        li.appendChild(icon(enabled ? "check" : "cross", 14));
        return li;
    }

    function limitRow(key, value, singular, plural, isStorage) {
        var display = (value === null || value === undefined)
            ? "Unlimited"
            : (isStorage ? formatBytes(value) : value);
        var label = isStorage ? singular : pluralize(value, singular, plural);
        var enabled = value === null || value === undefined || value > 0;
        var li = featureRow(key, enabled);
        li.appendChild(document.createTextNode(" " + display + " "));
        li.appendChild(el("span", "label", label));
        return li;
    }

    function featureList(plan) {
        var code = String(plan.code || "").toLowerCase();
        var list = el("ul", "pri-feature-list");

        list.appendChild(limitRow("chatbot_limit", plan.chatbot_limit, "Chatbot", "Chatbots", false));
        list.appendChild(limitRow("team_member_limit", plan.team_member_limit, "Team Member", "Team Members", false));
        list.appendChild(limitRow("channel_limit", plan.channel_limit, "Channel", "Channels", false));
        list.appendChild(limitRow("knowledge_file_limit", plan.knowledge_file_limit, "Knowledge File", "Knowledge Files", false));
        list.appendChild(limitRow("knowledge_storage_limit_bytes", plan.knowledge_storage_limit_bytes, "Storage", "Storage", true));

        /* Model tier. Free is described by the model it actually gets. */
        var tier = plan.model_access_tier || "economy";
        var model = featureRow("model_access_tier", true);
        if (code === "free") {
            model.appendChild(document.createTextNode(" AI Models: "));
            model.appendChild(el("span", "label", "DeepSeek Only"));
        } else {
            model.appendChild(document.createTextNode(" " + titleCase(tier) + " Model Tier"));
        }
        list.appendChild(model);

        var credit = featureRow("included_ai_credit_micro_myr", true);
        credit.appendChild(document.createTextNode(" AI Credit: "));
        credit.appendChild(el("span", "label",
            formatMoney(microToMyr(plan.included_ai_credit_micro_myr), plan.currency)));
        list.appendChild(credit);

        /* The five approved flags, last and in order.

           An absent key renders as not-included, matching both the old page
           and the spec. That differs from backend enforcement, which treats
           an absent key as granted; the divergence is logged as an open
           question in DESIGN.md rather than papered over here. */
        var flags = (plan.feature_flags && typeof plan.feature_flags === "object")
            ? plan.feature_flags : {};
        CUSTOMER_FEATURE_FLAGS.forEach(function (key) {
            var row = featureRow(key, flags[key] === true);
            row.appendChild(document.createTextNode(" " + FLAG_LABELS[key]));
            list.appendChild(row);
        });

        return list;
    }

    function priceNode(plan) {
        var node = el("div", "plan-price");
        var amount = parseFloat(plan.price);
        if (!plan.price || isNaN(amount) || amount <= 0) {
            node.textContent = "Free";
            return node;
        }
        node.appendChild(document.createTextNode(formatMoney(amount, plan.currency) + " "));
        var interval = plan.billing_interval || "monthly";
        node.appendChild(el("span", "pri-interval", "/ " + titleCase(interval)));
        return node;
    }

    function syncCardFooter(foot, plan, isCurrent, recommended) {
        var code = String(plan.code || "").toLowerCase();
        var sub = asObject(state.subscription);
        var status = subscriptionStatus(sub);
        var thisRank = rankOf(code);
        var currentRank = rankOf(state.currentCode);
        var action = null;

        if (isCurrent) {
            if (isRenewableCurrentPlan(code)) {
                action = {
                    kind: "upgrade",
                    className: "kw-btn kw-btn-primary cr-press",
                    icon: "arrow",
                    text: "Renew " + (plan.name || titleCase(code)),
                    aria: "Renew " + (plan.name || code)
                };
            } else {
                var label = "Current plan";
                if (code === "free" && status === "trialing") label = "Current trial";
                else if (sub && sub.pending_plan) label = "Changing at period end";
                else if (sub && sub.cancellation_effective_at) label = "Cancelling at period end";
                action = { kind: "static", text: label };
            }
        } else if (code === "free") {
            /* Free is a trial state for new accounts, not something an
               existing tenant can select. */
            action = { kind: "static", text: "For new accounts only" };
        } else if (thisRank > currentRank) {
            var upgradeText = (status === "past_due" || status === "expired")
                ? "Renew and upgrade"
                : "Upgrade";
            action = {
                kind: "upgrade",
                className: "kw-btn kw-btn-primary cr-press",
                icon: recommended ? "spark" : "arrow",
                text: upgradeText,
                aria: upgradeText + " to " + (plan.name || code)
            };
        } else {
            action = {
                kind: "downgrade",
                className: "kw-btn cr-press",
                text: "Switch at period end",
                aria: "Switch at period end to " + (plan.name || code)
            };
        }

        var actionState = [
            action.kind,
            action.text,
            action.className || "",
            action.icon || "",
            action.aria || "",
            code
        ].join("|");
        if (foot.dataset.actionState === actionState) return foot;

        foot.replaceChildren();
        foot.dataset.actionState = actionState;

        if (action.kind === "static") {
            foot.appendChild(el("div", "pri-static", action.text));
            return foot;
        }

        var btn = el("button");
        btn.type = "button";
        btn.className = action.className;
        if (action.icon) btn.appendChild(icon(action.icon, 16));
        btn.appendChild(document.createTextNode(action.icon ? " " + action.text : action.text));
        btn.setAttribute("aria-label", action.aria);
        btn.addEventListener("click", function () {
            if (action.kind === "downgrade") startDowngrade(code);
            else startUpgrade(code);
        });
        foot.appendChild(btn);
        return foot;
    }

    function cardFooter(plan, isCurrent, recommended) {
        return syncCardFooter(el("div", "pri-card-foot"), plan, isCurrent, recommended);
    }

    function syncPlanCardState(card, plan, recommendedCode) {
        var code = String(plan.code || "").toLowerCase();
        var isCurrent = code === state.currentCode;
        var isRenewableCurrent = isCurrent && isRenewableCurrentPlan(code);
        var isRecommended = code === recommendedCode && !isCurrent;
        var flag = card.querySelector(".pri-card-flag");

        card.classList.toggle("is-current", isCurrent && !isRenewableCurrent);
        card.classList.toggle("is-recommended", isRecommended);
        card.classList.toggle(
            "is-collapsed",
            !isCurrent && !isRecommended && rankOf(code) < rankOf(state.currentCode)
        );

        if (isRecommended || (isCurrent && !isRenewableCurrent)) {
            var flagText = isRecommended ? "Recommended" : "Current";
            var flagClass = isRecommended ? "pri-card-flag" : "pri-card-flag is-neutral";
            if (!flag) {
                flag = el("div", flagClass, flagText);
                card.insertBefore(flag, card.firstChild);
            } else {
                flag.className = flagClass;
                flag.textContent = flagText;
            }
        } else if (flag) {
            flag.remove();
        }

        var foot = card.querySelector(".pri-card-foot");
        if (foot) syncCardFooter(foot, plan, isCurrent, isRecommended);
    }

    function planCard(plan, recommendedCode) {
        var code = String(plan.code || "").toLowerCase();
        var isCurrent = code === state.currentCode;
        var isRenewableCurrent = isCurrent && isRenewableCurrentPlan(code);
        var isRecommended = code === recommendedCode && !isCurrent;

        var card = el("div", "plan-card");
        card.dataset.planCode = code;
        if (isCurrent && !isRenewableCurrent) card.classList.add("is-current");
        if (isRecommended) card.classList.add("is-recommended");

        /* A tier below the current one is collapsed but still rendered: the
           spec counts four cards and a hidden element still counts. */
        if (!isCurrent && !isRecommended && rankOf(code) < rankOf(state.currentCode)) {
            card.classList.add("is-collapsed");
        }

        if (isRecommended) {
            card.appendChild(el("div", "pri-card-flag", "Recommended"));
        } else if (isCurrent && !isRenewableCurrent) {
            card.appendChild(el("div", "pri-card-flag is-neutral", "Current"));
        }

        /* textContent, never innerHTML: plan name and description come from
           the API, and the spec injects markup to prove they render as
           text. */
        card.appendChild(el("div", "plan-name", plan.name || code));
        card.appendChild(priceNode(plan));
        card.appendChild(el("div", "plan-desc", plan.description || ""));

        var details = el("details", "pri-features");
        var summary = el("summary");
        summary.appendChild(document.createTextNode("What is included"));
        var chev = icon("chevron", 14);
        chev.setAttribute("class", "dashboard-icon pri-features-chevron");
        summary.appendChild(chev);
        details.appendChild(summary);
        details.appendChild(featureList(plan));
        card.appendChild(details);

        card.appendChild(cardFooter(plan, isCurrent, isRecommended));
        return card;
    }

    function renderTiers() {
        var host = $("plans-grid");
        if (!host) return;

        var recommended = recommendedPlan();
        var recommendedCode = recommended
            ? String(recommended.code || "").toLowerCase() : null;
        var activeCodes = {};

        state.plans.forEach(function (plan) {
            var code = String(plan.code || "").toLowerCase();
            activeCodes[code] = true;
            var card = host.querySelector('.plan-card[data-plan-code="' + code + '"]');
            if (card) {
                syncPlanCardState(card, plan, recommendedCode);
            } else {
                host.appendChild(planCard(plan, recommendedCode));
            }
        });
        Array.prototype.slice.call(host.querySelectorAll(".plan-card")).forEach(function (card) {
            if (!activeCodes[card.dataset.planCode]) card.remove();
        });

        var collapsed = host.querySelectorAll(".plan-card.is-collapsed").length;
        var toggle = $("pri-show-all");
        if (toggle) {
            toggle.hidden = collapsed === 0;
            toggle.textContent = "Show " + collapsed + " lower " +
                pluralize(collapsed, "plan", "plans");
            toggle.setAttribute("aria-expanded", "false");
            host.classList.remove("is-expanded");
        }
        renderDiff(recommended);
    }

    function renderDiff(target) {
        var section = $("pri-diff-section");
        var host = $("pri-diff");
        var title = $("pri-diff-title");
        if (!section || !host || !title) return;

        var current = planFor(state.currentCode);
        if (!target || !current) {
            section.hidden = true;
            return;
        }

        var items = [];
        METERS.forEach(function (spec) {
            var from = current[spec.plan];
            var to = target[spec.plan];
            if (to === null || to === undefined) {
                items.push({ plus: "Unlimited", label: spec.label.toLowerCase() });
                return;
            }
            if (from === null || from === undefined) return;
            var delta = Number(to) - Number(from);
            if (delta <= 0) return;
            items.push({
                plus: "+" + (spec.bytes ? formatBytes(delta) : delta),
                label: spec.label.toLowerCase()
            });
        });

        var currentFlags = current.feature_flags || {};
        var targetFlags = target.feature_flags || {};
        CUSTOMER_FEATURE_FLAGS.forEach(function (key) {
            if (targetFlags[key] === true && currentFlags[key] !== true) {
                items.push({ plus: "New", label: FLAG_LABELS[key] });
            }
        });

        var creditDelta = microToMyr(target.included_ai_credit_micro_myr) -
            microToMyr(current.included_ai_credit_micro_myr);
        if (creditDelta > 0) {
            items.push({ plus: "+" + formatMoney(creditDelta, "MYR"), label: "AI credit" });
        }

        if (!items.length) {
            section.hidden = true;
            return;
        }

        section.hidden = false;
        title.textContent = "What changes on " + (target.name || titleCase(target.code));
        host.replaceChildren();
        items.forEach(function (item) {
            var chip = el("div", "pri-diff-item");
            chip.appendChild(el("span", "pri-diff-plus", item.plus));
            chip.appendChild(el("span", null, item.label));
            host.appendChild(chip);
        });
    }

    /* ── actions ───────────────────────────────────────────────────── */

    var upgradeInFlight = false;

    async function startUpgrade(code) {
        if (upgradeInFlight) return;
        upgradeInFlight = true;
        clearError();
        announce("Preparing checkout.");
        try {
            var res = await authenticatedFetch("/api/billing/subscription/checkout", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ plan_code: code })
            });
            var body = await res.json();
            var url = body && body.data && body.data.checkout_url;
            if (body && body.status === "success" && typeof url === "string" &&
                /^https?:\/\//.test(url)) {
                var ref = body.data.order_reference;
                if (typeof ref === "string" && ref.length > 0) {
                    sessionStorage.setItem("pending_subscription_order_reference", ref);
                }
                window.location.assign(url);
                return;
            }
            showError((body && body.message) ||
                "We could not start checkout. Please try again.");
        } catch (_) {
            showError("We could not reach the server. Check your connection and try again.");
        }
        upgradeInFlight = false;
    }

    var downgradeInFlight = false;

    async function startDowngrade(code) {
        clearError();
        try {
            var res = await authenticatedFetch(
                "/api/billing/subscription/downgrade-check/" + encodeURIComponent(code));
            var body = await res.json();
            var data = body && asObject(body.data);
            if (!data) {
                showError((body && body.message) ||
                    "We could not check whether this change is possible.");
                return;
            }

            if (data.eligible) {
                var when = formatDate(data.effective_at);
                openConfirm(
                    "Switch to " + titleCase(data.target_plan) + "?",
                    "Your current plan stays active" + (when ? " until " + when : "") +
                    ". After that the new limits apply. Nothing is deleted, and there is no refund.",
                    "Confirm change",
                    function () { commitDowngrade(code); }
                );
                return;
            }

            /* Blocked. team_members and team_members_including_pending can
               both describe a single cause, so they collapse to one line. */
            var seen = Object.create(null);
            var lines = [];
            (data.blocking_items || []).forEach(function (item) {
                var name = String(item.resource || "").replace(/_including_pending$/, "");
                if (seen[name]) return;
                seen[name] = true;
                lines.push(name.replace(/_/g, " ") + ": " + item.used +
                    " in use, " + item.limit + " allowed");
            });
            openConfirm(
                "You are using more than " + titleCase(data.target_plan) + " allows",
                lines.join("\n") +
                "\n\nNothing is deleted automatically. Reduce these first, then try again.",
                null,
                null
            );
        } catch (_) {
            showError("We could not reach the server. Check your connection and try again.");
        }
    }

    async function commitDowngrade(code) {
        if (downgradeInFlight) return;
        downgradeInFlight = true;
        try {
            var res = await authenticatedFetch("/api/billing/subscription/downgrade", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ target_plan_code: code })
            });
            var body = await res.json();
            if (body && body.status === "success") {
                announce("Plan change scheduled.");
                await load();
            } else {
                showError((body && body.message) || "We could not schedule that change.");
            }
        } catch (_) {
            showError("We could not reach the server. Check your connection and try again.");
        }
        downgradeInFlight = false;
    }

    /* ── confirm dialog ────────────────────────────────────────────── */

    var confirmAction = null;

    function openConfirm(title, body, confirmLabel, onConfirm) {
        var backdrop = $("pri-confirm");
        if (!backdrop) return;
        $("pri-confirm-title").textContent = title;
        $("pri-confirm-body").textContent = body;

        var ok = $("pri-confirm-ok");
        var cancel = $("pri-confirm-cancel");
        confirmAction = onConfirm || null;

        ok.hidden = !onConfirm;
        if (onConfirm) ok.textContent = confirmLabel || "Confirm";
        cancel.textContent = onConfirm ? "Keep current plan" : "Close";

        /* Focus lands on the non-destructive control, so Enter never commits
           a plan change the reader has not taken in. */
        window.kwDialog.open(backdrop, cancel);
    }

    function closeConfirm() {
        var backdrop = $("pri-confirm");
        if (backdrop && window.kwDialog.isOpen(backdrop)) {
            window.kwDialog.close(backdrop);
        }
        confirmAction = null;
    }

    /* ── render + boot ─────────────────────────────────────────────── */

    function renderCurrent() {
        var host = $("pri-current");
        if (!host) return;
        host.replaceChildren();

        var plan = planFor(state.currentCode);
        var sub = asObject(state.subscription);

        if (!plan) {
            host.appendChild(el("span", "pri-current-name", "No active plan"));
            host.appendChild(el("span", "pri-current-note",
                "Choose a plan below to get started."));
            return;
        }

        host.appendChild(el("span", "pri-current-name", plan.name || state.currentCode));

        var amount = parseFloat(plan.price);
        var priceText = (!plan.price || isNaN(amount) || amount <= 0)
            ? "Free"
            : formatMoney(amount, plan.currency) + " / month";
        host.appendChild(el("span", "pri-current-price", priceText));

        var note = null;
        if (sub && sub.cancellation_effective_at) {
            note = "Cancels on " + (formatDate(sub.cancellation_effective_at) || "period end");
        } else if (sub && sub.pending_plan && sub.pending_plan.name) {
            note = "Changes to " + sub.pending_plan.name + " on " +
                (formatDate(sub.plan_change_effective_at) || "period end");
        } else if (sub && sub.trial_days_remaining) {
            note = sub.trial_days_remaining + " " +
                pluralize(sub.trial_days_remaining, "day", "days") + " left in trial";
        } else if (sub && sub.current_period_end) {
            var status = subscriptionStatus(sub);
            var periodEnd = formatDate(sub.current_period_end) || "period end";
            if (status === "expired") {
                note = "Expired on " + periodEnd;
            } else if (status === "past_due") {
                note = "Renewal required since " + periodEnd;
            } else {
                note = "Renews on " + periodEnd;
            }
        }
        if (note) host.appendChild(el("span", "pri-current-note", note));
    }

    function setLoading(isLoading) {
        var skeleton = $("pri-skeleton");
        if (skeleton) skeleton.hidden = !isLoading;
    }

    var loadSequence = 0;

    function refreshPricingRender() {
        renderCurrent();
        renderTiers();
        renderMeters();

        if (window.controlRoomMotion) window.controlRoomMotion.countUpAll(document);
        if (typeof refreshIcons === "function") refreshIcons();
    }

    async function load() {
        var sequence = loadSequence + 1;
        loadSequence = sequence;
        setLoading(true);
        clearError();

        /* Plans and subscription are the safe gate for plan actions. Usage
           and credit load beside them, but do not block the card buttons. */
        var usagePromise = getJson("/api/billing/usage");
        var creditPromise = getJson("/api/billing/ai-credit/summary");
        var criticalResults;
        try {
            criticalResults = await Promise.all([
                getJson("/api/billing/plans"),
                getJson("/api/billing/subscription")
            ]);
        } catch (_) {
            if (sequence !== loadSequence) return;
            setLoading(false);
            showError("Unable to load subscription plans. Please try again in a moment.");
            return;
        }

        if (sequence !== loadSequence) return;

        state.plans = Array.isArray(criticalResults[0]) ? criticalResults[0].slice() : [];
        state.subscription = asObject(criticalResults[1]);
        state.usage = null;
        state.credit = null;

        state.plans.sort(function (a, b) {
            return rankOf(a.code) - rankOf(b.code);
        });

        /* subscription.plan is absent entirely when the plan row cannot be
           resolved, so it is read defensively rather than assumed. */
        var plan = state.subscription && asObject(state.subscription.plan);
        state.currentCode = plan ? String(plan.code || "").toLowerCase() : null;

        setLoading(false);

        if (!state.plans.length) {
            showError("No plans are available right now. Please try again in a moment.");
            return;
        }

        refreshPricingRender();

        usagePromise.then(function (usage) {
            if (sequence !== loadSequence) return;
            state.usage = asObject(usage);
            refreshPricingRender();
        }).catch(function () {
            if (sequence !== loadSequence) return;
            state.usage = null;
            renderMeters();
        });

        creditPromise.then(function (credit) {
            if (sequence !== loadSequence) return;
            state.credit = asObject(credit);
            renderMeters();
            if (window.controlRoomMotion) window.controlRoomMotion.countUpAll(document);
            if (typeof refreshIcons === "function") refreshIcons();
        }).catch(function () {
            if (sequence !== loadSequence) return;
            state.credit = null;
            renderMeters();
        });
    }

    function wire() {
        var toggle = $("pri-show-all");
        if (toggle) {
            toggle.addEventListener("click", function () {
                var tiers = $("plans-grid");
                var expanded = tiers.classList.toggle("is-expanded");
                toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
                var count = tiers.querySelectorAll(".plan-card.is-collapsed").length;
                toggle.textContent = expanded
                    ? "Hide lower plans"
                    : "Show " + count + " lower " + pluralize(count, "plan", "plans");
            });
        }

        var retry = $("pricing-retry");
        if (retry) retry.addEventListener("click", function () { load(); });

        var backdrop = $("pri-confirm");
        if (backdrop) {
            $("pri-confirm-cancel").addEventListener("click", closeConfirm);
            $("pri-confirm-close").addEventListener("click", closeConfirm);
            $("pri-confirm-ok").addEventListener("click", function () {
                var action = confirmAction;
                closeConfirm();
                if (action) action();
            });
            /* A click on the backdrop dismisses; a click inside the card
               does not. */
            backdrop.addEventListener("click", function (event) {
                if (event.target === event.currentTarget) closeConfirm();
            });
        }

        /* kw-a11y supplies the focus trap and focus restore but not Escape,
           which every page wires for itself. */
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") closeConfirm();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { wire(); load(); });
    } else {
        wire();
        load();
    }
})();
