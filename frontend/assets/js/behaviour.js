/**
 * Behaviour Studio.
 *
 * Merges the former Tune AI, Message Style and Test Bot pages into one screen
 * with three tabs. Model and Message experience both write `PUT /api/bots/{id}`,
 * which is why they belong together; Test lab only reads.
 *
 * `bot_service.edit_bot` is key-presence based, so each tab could send only its
 * own fields and the other tab's values would survive. The save here sends both
 * tabs' fields at once anyway: the studio has one commit point, so what the
 * operator sees on screen is exactly what gets written.
 */
(function () {
    "use strict";

    /* ── Bot scope ───────────────────────────────────────────────── */

    var params = new URLSearchParams(window.location.search);
    var isSetup = params.get("setup") === "1";
    var setupSuffix = isSetup ? "&setup=1" : "";
    var urlBotId = params.get("bot_id");
    var storedBotId = sessionStorage.getItem("selectedBotId");

    if (!urlBotId && storedBotId) {
        window.location.href = "behaviour.html?bot_id=" + encodeURIComponent(storedBotId)
            + "&tab=" + encodeURIComponent(params.get("tab") || "model") + setupSuffix;
        return;
    }
    if (!urlBotId) {
        window.location.href = "bots.html";
        return;
    }

    var botId = urlBotId;
    sessionStorage.setItem("selectedBotId", botId);

    var TABS = ["model", "message", "test"];
    var MAX_MENU_BUTTONS = 3;

    /**
     * The three named styles. The number is an implementation detail of the
     * model API; the name is what the operator chooses. Kept in one place so
     * the cards, the slider and the save can never disagree.
     */
    var STYLES = [
        { key: "precise", value: 0.2, label: "Precise" },
        { key: "balanced", value: 0.7, label: "Balanced" },
        { key: "creative", value: 0.9, label: "Creative" }
    ];

    /**
     * Icons by slot, not by business.
     *
     * The scenarios themselves come from `GET /api/testbot/scenarios`, derived
     * from this bot's own document: "move my appointment to Friday" is a real
     * test for a clinic and a meaningless one for a shop, and a fixed list
     * teaches an operator nothing about the bot they are about to deploy.
     *
     * The server assigns the slot key by position, so a model that invents a
     * key of its own cannot leave a row without an icon.
     */
    var SCENARIO_ICONS = {
        common: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z",
        fact: "M6 3h9l5 5v13H6ZM14 3v6h6M9 13h6M9 17h4",
        outofscope: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM5.6 5.6l12.8 12.8",
        vague: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM9.5 9.2a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 2.2-2.4 3.7M12 17h.01",
        handoff: "M3 18v-1a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v1M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8ZM19 8v6M22 11h-6"
    };

    /** Cached per bot for the tab's lifetime: each rebuild costs AI credit. */
    var SCENARIO_CACHE_KEY = "bh-scenarios:" + botId;

    /** Server truth, and the working copy the operator is editing. */
    var saved = null;
    var draft = null;
    var catalogue = { options: {}, readOnly: false, accessAllowed: true, denialReason: null, access: null };
    var context = null;
    var scenarios = null;
    var activeKnowledge = {};
    var activeTab = "model";
    var busy = false;
    /** Set when the bot could not be loaded: nothing may be written after that. */
    var botLoadFailed = false;

    function $(id) { return document.getElementById(id); }

    function svgEl(name, attrs) {
        var el = document.createElementNS("http://www.w3.org/2000/svg", name);
        Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
        return el;
    }

    function icon(path) {
        var svg = svgEl("svg", { viewBox: "0 0 24 24", class: "dashboard-icon", "aria-hidden": "true" });
        svg.appendChild(svgEl("path", { d: path }));
        return svg;
    }

    function banner(id, kind, text) {
        var el = $(id);
        el.className = "bh-banner" + (kind ? " bh-banner-" + kind : "");
        el.textContent = text || "";
    }

    /* ── Draft model ─────────────────────────────────────────────── */

    function blankDraft() {
        return {
            ai_provider: "",
            model_name: "",
            temperature: 0.7,
            quickReplies: true,
            markdown: true,
            menu: []
        };
    }

    function fromBot(bot) {
        var labels = Array.isArray(bot.welcome_menu_labels) ? bot.welcome_menu_labels : [];
        return {
            ai_provider: bot.ai_provider || "",
            model_name: bot.model_name || "",
            // The column may be absent on older rows; 0.7 matches the previous
            // page's default rather than inventing a new one.
            temperature: typeof bot.temperature === "number" ? bot.temperature : 0.7,
            // Telegram is read as the source of truth because the two channels
            // are always written together — the same rule the old page used.
            quickReplies: bot.telegram_buttons_enabled !== false,
            markdown: bot.telegram_markdown_enabled !== false,
            menu: labels.slice(0, MAX_MENU_BUTTONS).map(String)
        };
    }

    function clone(value) { return JSON.parse(JSON.stringify(value)); }

    function isDirty() {
        return JSON.stringify(saved) !== JSON.stringify(draft);
    }

    function styleForValue(value) {
        for (var i = 0; i < STYLES.length; i++) {
            // Tolerant compare: a float does not always survive a JSON round
            // trip exactly, and 0.7000000000000001 is still Balanced.
            if (Math.abs(STYLES[i].value - value) < 0.001) return STYLES[i];
        }
        return null;
    }

    /* ── Tabs ────────────────────────────────────────────────────── */

    function readTab() {
        var requested = new URLSearchParams(window.location.search).get("tab");
        return TABS.indexOf(requested) >= 0 ? requested : "model";
    }

    function showTab(tab, pushState) {
        activeTab = tab;

        TABS.forEach(function (name) {
            var trigger = $("bh-tab-" + name);
            var panel = $("bh-panel-" + name);
            var selected = name === tab;
            trigger.setAttribute("aria-selected", String(selected));
            trigger.href = "?bot_id=" + encodeURIComponent(botId) + "&tab=" + name + setupSuffix;
            panel.hidden = !selected;
        });

        // The footer commits tabs 1 and 2. Test lab writes nothing, so a save
        // button there would imply the conversation is a saveable document.
        $("bh-footer").hidden = tab === "test";

        if (isSetup) {
            var guidedTest = tab === "test";
            var setupQuery = "?bot_id=" + encodeURIComponent(botId) + setupSuffix;
            document.querySelector(".bh-page").classList.toggle("bh-guided", guidedTest);
            document.querySelector(".bh-title").textContent = guidedTest ? "Test your bot" : "Behaviour Studio";
            document.querySelector(".bh-subtitle").firstChild.textContent = guidedTest ? "See how " : "Decide how ";
            document.querySelector(".bh-subtitle").lastChild.textContent = guidedTest ? " answers a customer question." : " thinks, speaks, and replies.";
            $("bh-setup-journey").setAttribute("bot-id", botId);
            ["bh-setup-journey", "bh-guided-help", "bh-guided-next", "bh-guided-settings"].forEach(function (id) {
                $(id).hidden = !guidedTest;
            });
            $("bh-choose-channel").href = "integration.html" + setupQuery;
            $("bh-guided-model").href = "behaviour.html" + setupQuery + "&tab=model";
            $("bh-guided-message").href = "behaviour.html" + setupQuery + "&tab=message";
        }

        if (pushState) {
            window.history.pushState({ tab: tab }, "",
                "?bot_id=" + encodeURIComponent(botId) + "&tab=" + tab + setupSuffix);
        }

        if (tab === "test") {
            renderChatEmpty();
            loadTestContext().then(function () {
                return loadScenarios(false);
            });
        }
    }

    /* ── Model tab ───────────────────────────────────────────────── */

    function renderStyles() {
        var match = styleForValue(draft.temperature);
        var customCard = $("bh-style-custom");

        // The custom card appears only while the value is off-preset, so the
        // common case shows three choices and no arithmetic.
        customCard.hidden = Boolean(match);
        if (!match) $("bh-custom-value").textContent = String(draft.temperature);

        document.querySelectorAll(".bh-style").forEach(function (card) {
            var selected = match
                ? card.dataset.style === match.key
                : card.dataset.style === "custom";
            card.classList.toggle("is-selected", selected);
            card.querySelector("input").checked = selected;
        });

        $("bh-temp").value = String(draft.temperature);
        $("bh-temp-out").textContent = String(draft.temperature);
    }

    function renderProviders() {
        var providerSelect = $("bh-provider");
        var providers = window.modelCatalog.allowedProviders(catalogue);

        providerSelect.replaceChildren();

        if (!providers.length) {
            var none = document.createElement("option");
            none.value = "";
            none.textContent = "No models available on your plan";
            providerSelect.appendChild(none);
            providerSelect.disabled = true;
            $("bh-model").disabled = true;
            return;
        }

        providerSelect.disabled = false;
        $("bh-model").disabled = false;

        providers.forEach(function (provider) {
            var option = document.createElement("option");
            option.value = provider.key;
            option.textContent = provider.label;
            providerSelect.appendChild(option);
        });

        // Keep the stored provider while the plan still allows it; otherwise fall
        // to the first allowed one rather than showing a value that cannot save.
        var known = providers.some(function (p) { return p.key === draft.ai_provider; });
        if (!known) draft.ai_provider = providers[0].key;
        providerSelect.value = draft.ai_provider;

        renderModels();
    }

    function modelId(model) {
        return model.value || model.id || model.name || "";
    }

    function renderModels() {
        var modelSelect = $("bh-model");
        var providers = window.modelCatalog.allowedProviders(catalogue);
        var current = providers.filter(function (p) { return p.key === draft.ai_provider; })[0];

        modelSelect.replaceChildren();
        if (!current) return;

        current.models.forEach(function (model) {
            var option = document.createElement("option");
            option.value = modelId(model);
            option.textContent = model.label || option.value;
            modelSelect.appendChild(option);
        });

        var known = current.models.some(function (m) { return modelId(m) === draft.model_name; });
        if (!known && current.models.length) {
            draft.model_name = modelId(current.models[0]);
        }
        modelSelect.value = draft.model_name;
    }

    function renderPlanNote() {
        var note = $("bh-plan-note");
        if (!catalogue.accessAllowed) {
            note.textContent = catalogue.denialReason || "AI access is not available on your current plan.";
            return;
        }
        if (catalogue.readOnly) {
            note.textContent = "Your trial runs on a fixed model. Upgrade to choose a different one.";
            return;
        }
        note.textContent = "Your plan decides which models you can choose.";
    }

    function hasEntitledFeature(featureKey) {
        if (!catalogue || !window.modelCatalog || !window.modelCatalog.hasAnyAccess(catalogue)) {
            return false;
        }
        var flags = catalogue.access
            && catalogue.access.plan
            && catalogue.access.plan.feature_flags;
        return Boolean(flags && typeof flags === "object" && flags[featureKey] === true);
    }

    function readyRow(iconPath, name, value, tone, label) {
        var li = document.createElement("li");
        li.className = "bh-ready-row";

        var iconWrap = document.createElement("span");
        iconWrap.className = "bh-ready-icon";
        iconWrap.setAttribute("aria-hidden", "true");
        iconWrap.appendChild(icon(iconPath));

        var body = document.createElement("span");
        body.className = "bh-ready-body";
        var nameEl = document.createElement("span");
        nameEl.className = "bh-ready-name";
        nameEl.textContent = name;
        var valueEl = document.createElement("span");
        valueEl.className = "bh-ready-value";
        valueEl.textContent = value;
        valueEl.title = value;
        body.append(nameEl, valueEl);

        var pill = document.createElement("span");
        pill.className = tone ? "kw-pill kw-pill-" + tone : "kw-pill";
        pill.textContent = label;

        li.append(iconWrap, body, pill);
        return li;
    }

    function renderCurrent() {
        var match = styleForValue(draft.temperature);
        var providers = window.modelCatalog.allowedProviders(catalogue);
        var provider = providers.filter(function (p) { return p.key === draft.ai_provider; })[0];
        var model = provider && provider.models.filter(function (m) {
            return modelId(m) === draft.model_name;
        })[0];

        $("bh-current").replaceChildren(
            readyRow("M12 4v16M5 8h14M7 8l-3 6h6ZM17 8l-3 6h6Z", "Answer style",
                match ? match.label : "Custom (" + draft.temperature + ")",
                match ? "ready" : "", match ? "Set" : "Custom"),
            readyRow("M4 7h16M4 12h16M4 17h10", "AI provider",
                provider ? provider.label : (draft.ai_provider || "Not selected"),
                provider ? "ready" : "review", provider ? "Ready" : "Check plan"),
            readyRow("M12 2 3 7v10l9 5 9-5V7Z", "Model",
                model ? (model.label || draft.model_name) : (draft.model_name || "Not selected"),
                model ? "ready" : "review", model ? "Ready" : "Check plan"),
            readyRow("M4 5h16v11H8l-4 4V5Z", "Welcome menu",
                draft.menu.length ? draft.menu.length + " button" + (draft.menu.length > 1 ? "s" : "") : "None",
                "", draft.menu.length ? "Set" : "Optional")
        );
    }

    /* ── Message tab ─────────────────────────────────────────────── */

    function iconButton(path, label) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "kw-btn kw-btn-icon cr-press";
        button.setAttribute("aria-label", label);
        button.appendChild(icon(path));
        return button;
    }

    function renderMenu() {
        var list = $("bh-menu");
        list.replaceChildren();

        $("bh-menu-empty").hidden = draft.menu.length > 0;

        draft.menu.forEach(function (label, index) {
            var row = document.createElement("li");
            row.className = "bh-menu-row";

            var input = document.createElement("input");
            input.className = "kw-input";
            input.value = label;
            input.maxLength = 40;
            input.setAttribute("aria-label", "Menu button " + (index + 1));
            input.addEventListener("input", function () {
                draft.menu[index] = input.value;
                renderPreview();
                syncDirty();
            });

            var actions = document.createElement("div");
            actions.className = "bh-menu-actions";

            var up = iconButton("m18 15-6-6-6 6", "Move up");
            up.disabled = index === 0;
            up.addEventListener("click", function () { moveMenu(index, -1); });

            var down = iconButton("m6 9 6 6 6-6", "Move down");
            down.disabled = index === draft.menu.length - 1;
            down.addEventListener("click", function () { moveMenu(index, 1); });

            var remove = iconButton("M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6", "Remove");
            remove.classList.add("kw-btn-danger");
            remove.addEventListener("click", function () {
                draft.menu.splice(index, 1);
                renderMenu();
                renderPreview();
                renderCurrent();
                syncDirty();
            });

            actions.append(up, down, remove);
            row.append(input, actions);
            list.appendChild(row);
        });

        $("bh-menu-add").disabled = draft.menu.length >= MAX_MENU_BUTTONS;
        $("bh-menu-note").textContent = draft.menu.length + " of " + MAX_MENU_BUTTONS + " buttons";
    }

    function moveMenu(index, delta) {
        var target = index + delta;
        if (target < 0 || target >= draft.menu.length) return;
        var moved = draft.menu.splice(index, 1)[0];
        draft.menu.splice(target, 0, moved);
        renderMenu();
        renderPreview();
        syncDirty();
    }

    function bubble(text, who) {
        var el = document.createElement("div");
        el.className = "bh-bubble bh-bubble-" + who;
        el.textContent = text;
        return el;
    }

    function renderPreview() {
        var preview = $("bh-preview");
        var name = (context && context.bot_name) || $("bh-bot-name").textContent || "your bot";

        preview.replaceChildren();
        preview.appendChild(bubble("Hi there. Welcome to " + name + ". How can we help you today?", "bot"));

        var labels = draft.menu.map(function (l) { return l.trim(); }).filter(Boolean);
        if (labels.length) {
            var quick = document.createElement("div");
            quick.className = "bh-quick";
            labels.forEach(function (label) {
                var item = document.createElement("span");
                item.textContent = label;
                quick.appendChild(item);
            });
            preview.appendChild(quick);
        }

        preview.appendChild(bubble("I can help with that. Would you like to see available times, or speak with our team?", "bot"));

        if (draft.quickReplies) {
            var replies = document.createElement("div");
            replies.className = "bh-quick";
            ["See available times", "Speak to our team"].forEach(function (label) {
                var item = document.createElement("span");
                item.textContent = label;
                replies.appendChild(item);
            });
            preview.appendChild(replies);
        } else {
            // What actually happens with buttons off: every channel runs
            // parse_buttons_tag, which strips the tag whether or not it sends
            // buttons, and nothing renumbers the options. The customer keeps
            // the same sentence and has to type the answer out.
            var note = document.createElement("p");
            note.className = "bh-reply-note";
            note.textContent = "No buttons. The customer types their answer instead.";
            preview.appendChild(note);
        }
    }

    /* ── Test tab ────────────────────────────────────────────────── */

    function setupItem(label, value, ready, iconPath) {
        var li = document.createElement("li");
        li.className = "bh-setup-item " + (ready ? "is-ready" : "is-missing");

        var iconWrap = document.createElement("span");
        iconWrap.className = "bh-setup-icon";
        iconWrap.setAttribute("aria-hidden", "true");
        iconWrap.appendChild(icon(iconPath));

        var body = document.createElement("span");
        var labelEl = document.createElement("span");
        labelEl.className = "bh-setup-label";
        labelEl.textContent = label;
        var valueEl = document.createElement("span");
        valueEl.className = "bh-setup-value";
        valueEl.textContent = value;
        valueEl.title = value;
        body.append(labelEl, valueEl);

        li.append(iconWrap, body);
        return li;
    }

    function sourceDisplayName(item, fallback) {
        return (item && (item.display_name || item.original_file_name || item.file_name))
            || fallback
            || "";
    }

    async function loadActiveKnowledge() {
        try {
            var response = await authenticatedFetch(
                "/api/knowledge/active?chatbot_id=" + encodeURIComponent(botId));
            var body = await response.json();
            activeKnowledge = body.status === "success" ? Object.assign({ _loaded: true }, body.data || {}) : {};
        } catch (_) {
            activeKnowledge = {};
        }
    }

    async function loadTestContext() {
        var reachable = true;

        try {
            // `chatbot_id`, not `bot_id`: testbot_routes reads chatbot_id and
            // answers 400 for anything else, which is what put "chatbot_id is
            // required" in the transcript where a reply belonged.
            var response = await authenticatedFetch(
                "/api/testbot/context?chatbot_id=" + encodeURIComponent(botId));
            var body = await response.json();
            reachable = body.status === "success";
            context = reachable ? (body.data || {}) : {};
        } catch (_) {
            reachable = false;
            context = {};
        }

        await loadActiveKnowledge();
        if (scenarios && !scenarios.loading) {
            renderScenarios();
        }

        // A failed lookup is not evidence that nothing is deployed. Claiming it
        // is sends the operator to redeploy a bot that was fine.
        if (!reachable) {
            $("bh-setup").replaceChildren(
                setupItem("Setup", "Could not be checked", false,
                    "M12 8v5M12 16h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z")
            );
            var offline = $("bh-test-warning");
            offline.hidden = false;
            offline.textContent = "Could not read what this bot has deployed, so the replies below "
                + "may not reflect your live setup. Reload to try again.";
            return;
        }

        var profile = context.active_profile || "";
        var legacyKnowledge = context.active_pdf || "";
        var knowledge = activeKnowledge._loaded
            ? sourceDisplayName(activeKnowledge, "")
            : sourceDisplayName(activeKnowledge, legacyKnowledge);
        var hasProfile = Boolean(profile) && profile !== "No active profile";
        var hasKnowledge = activeKnowledge._loaded
            ? Boolean(activeKnowledge.file_name)
            : Boolean(knowledge) && knowledge !== "No active PDF";

        $("bh-setup").replaceChildren(
            setupItem("Profile", hasProfile ? profile : "Not deployed", hasProfile,
                "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z"),
            setupItem("Knowledge", hasKnowledge ? knowledge : "None active", hasKnowledge,
                "M6 3h9l5 5v13H6ZM14 3v6h6"),
            setupItem("Model", saved.model_name || "Default", Boolean(saved.model_name),
                "M12 2 3 7v10l9 5 9-5V7Z"),
            setupItem("Welcome menu", saved.menu.length ? saved.menu.length + " buttons" : "None", true,
                "M4 5h16v11H8l-4 4V5Z")
        );

        // The trap this closes: with nothing deployed the bot still answers, from
        // defaults, and reads exactly like a configured bot. Saying so up front is
        // the difference between a useful test and a misleading one.
        var warning = $("bh-test-warning");
        if (!hasProfile) {
            warning.hidden = false;
            warning.textContent = "Nothing is deployed yet, so replies below come from default settings, not your profile. "
                + "Deploy from Bot configuration to test the real thing.";
        } else {
            warning.hidden = true;
        }
    }

    function renderScenarios() {
        var list = $("bh-scenarios");
        var note = $("bh-scenarios-note");
        var refresh = $("bh-scenarios-refresh");

        refresh.disabled = !scenarios || scenarios.loading;

        if (!scenarios || scenarios.loading) {
            list.replaceChildren();
            note.textContent = scenarios
                ? "Reading your documents to match these to your business…"
                : "";
            return;
        }

        // Naming the document is what makes "matched" checkable rather than a
        // claim: the operator can see which file these came out of.
        var scenarioSourceName = sourceDisplayName(activeKnowledge, scenarios.source_document);
        note.textContent = scenarios.matched
            ? "Matched to " + scenarioSourceName + "."
            : (scenarios.note || "");

        list.replaceChildren.apply(list, (scenarios.items || []).map(function (scenario) {
            var li = document.createElement("li");
            var button = document.createElement("button");
            button.type = "button";
            button.className = "bh-scenario";

            var iconWrap = document.createElement("span");
            iconWrap.className = "bh-scenario-icon";
            iconWrap.setAttribute("aria-hidden", "true");
            iconWrap.appendChild(icon(SCENARIO_ICONS[scenario.key] || SCENARIO_ICONS.common));

            var body = document.createElement("span");
            var name = document.createElement("span");
            name.className = "bh-scenario-name";
            name.textContent = scenario.name;
            var goal = document.createElement("span");
            goal.className = "bh-scenario-goal";
            goal.textContent = scenario.goal || scenario.message;
            body.append(name, goal);

            button.append(iconWrap, body, icon("m9 18 6-6-6-6"));
            // Loading the composer rather than sending: the operator reads the
            // question, and can edit it into the one they actually get asked.
            button.addEventListener("click", function () {
                $("bh-input").value = scenario.message;
                $("bh-input").focus();
            });

            li.appendChild(button);
            return li;
        }));
    }

    /**
     * Load the scenarios for this bot, from cache unless asked to rebuild.
     *
     * Cached because building them costs AI credit, and an operator who
     * switches tabs three times should not pay three times. `refresh` is the
     * explicit way to pay again — after uploading a new document, say.
     */
    async function loadScenarios(refresh) {
        if (scenarios && scenarios.loading) return;

        if (!refresh) {
            // Already built during this page load — switching tabs is free.
            if (scenarios && scenarios.items.length) {
                renderScenarios();
                return;
            }
            // Or built on an earlier visit in this browser tab.
            try {
                var cached = JSON.parse(sessionStorage.getItem(SCENARIO_CACHE_KEY) || "null");
                if (cached && cached.items && cached.items.length) {
                    scenarios = cached;
                    renderScenarios();
                    return;
                }
            } catch (_) { /* a corrupt cache just means fetching again */ }
        }

        scenarios = { loading: true, items: [] };
        renderScenarios();

        var loaded = { loading: false, matched: false, source_document: "", note: "", items: [] };

        try {
            var response = await authenticatedFetch(
                "/api/testbot/scenarios?chatbot_id=" + encodeURIComponent(botId));
            var body = await response.json();

            if (body.status === "success" && body.data) {
                loaded.matched = Boolean(body.data.matched);
                loaded.source_document = body.data.source_document || "";
                loaded.note = body.data.note || "";
                loaded.items = Array.isArray(body.data.scenarios) ? body.data.scenarios : [];
            } else {
                loaded.note = body.message || "Could not load suggested questions. Type your own below.";
            }
        } catch (_) {
            loaded.note = "Could not reach the server for suggested questions. Type your own below.";
        }

        scenarios = loaded;
        renderScenarios();

        try {
            sessionStorage.setItem(SCENARIO_CACHE_KEY, JSON.stringify(loaded));
        } catch (_) { /* a full or blocked store costs a rebuild, nothing more */ }
    }

    /** An empty transcript is an invitation, not a void. */
    function renderChatEmpty() {
        var chat = $("bh-chat");
        if (chat.querySelector(".bh-bubble")) return;
        var hint = document.createElement("p");
        hint.className = "bh-preview-empty";
        // Naming the greeting matters: the welcome menu saved on the Message
        // experience tab only reaches a reply through handle_greeting, so an
        // operator who never says hello never sees the buttons they configured.
        hint.textContent = saved && saved.menu.length
            ? "Nothing tested yet. Say hello to see your welcome menu, pick a scenario, "
              + "or type the question you get asked most."
            : "Nothing tested yet. Pick a scenario, or type the question you get asked most.";
        chat.replaceChildren(hint);
    }

    function appendChat(text, who) {
        var chat = $("bh-chat");
        var hint = chat.querySelector(".bh-preview-empty");
        if (hint) hint.remove();
        var el = bubble(text, who);
        chat.appendChild(el);
        chat.scrollTop = chat.scrollHeight;
        return el;
    }

    /**
     * Split a reply into its text and its reply buttons.
     *
     * The port of `message_style_utils.parse_buttons_tag`, which every channel
     * runs before sending. Two things append `[BUTTONS: A | B | C]`: the
     * greeting, from the welcome menu saved on the Message experience tab
     * (`chat_logic_service.handle_greeting`), and the model itself, which
     * rag_service's prompt asks for on broad questions. Without this the Test
     * lab printed the raw tag in the transcript — the one place it must not
     * appear, since no customer ever sees it.
     *
     * Limits match the Python: tag at the very end, `|`-separated, labels
     * capped at 20 characters and 3 buttons, which is what the channels accept.
     */
    function parseButtonsTag(text) {
        var match = /\[BUTTONS?:\s*([\s\S]*?)\]\s*$/i.exec(text || "");
        if (!match) return { text: text, labels: [] };

        var labels = match[1].split("|")
            .map(function (label) { return label.trim(); })
            .filter(Boolean)
            .map(function (label) { return label.slice(0, 20); })
            .slice(0, 3);

        return { text: text.slice(0, match.index).replace(/\s+$/, ""), labels: labels };
    }

    /**
     * Render one bot reply the way the customer's channel would.
     *
     * `saved`, never `draft`: the reply came back from the server, which read
     * the saved row. Showing buttons for an unsaved edit would credit the bot
     * with a setting it is not running.
     */
    function appendBotReply(text) {
        var parsed = parseButtonsTag(text);
        var chat = $("bh-chat");

        appendChat(parsed.text || "No reply received.", "bot");
        if (!parsed.labels.length) return;

        if (saved && saved.quickReplies) {
            var row = document.createElement("div");
            row.className = "bh-replies";
            parsed.labels.forEach(function (label) {
                var button = document.createElement("button");
                button.type = "button";
                button.className = "bh-reply cr-press";
                button.textContent = label;
                // Telegram sends the label back as `callback_data`, WhatsApp as
                // `button_reply.title`. Both are the label, so a tap here is
                // the same message the backend would receive from a channel.
                button.addEventListener("click", function () { sendMessage(label); });
                row.appendChild(button);
            });
            chat.appendChild(row);
        } else {
            // The tag is stripped either way, so with quick replies off the
            // choice survives only in the sentence. Saying so is the honest
            // cost of the toggle, and it is invisible otherwise.
            var note = document.createElement("p");
            note.className = "bh-reply-note";
            note.textContent = "Quick replies are off, so the customer sees this as text only — "
                + parsed.labels.length + " button" + (parsed.labels.length === 1 ? "" : "s")
                + " were not sent.";
            chat.appendChild(note);
        }

        chat.scrollTop = chat.scrollHeight;
    }

    async function sendMessage(text) {
        var message = (text || "").trim();
        if (!message || $("bh-send").disabled) return;

        appendChat(message, "user");
        setRepliesDisabled(true);

        var send = $("bh-send");
        send.disabled = true;
        var pending = appendChat("Typing…", "bot");

        try {
            var response = await authenticatedFetch(
                "/api/testbot/chat?chatbot_id=" + encodeURIComponent(botId), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: message })
            });
            var body = await response.json();
            pending.remove();

            if (body.status === "success") {
                appendBotReply((body.data && body.data.reply) || "");
            } else {
                appendChat(body.message || "The bot could not answer. Try again.", "bot");
            }
        } catch (_) {
            pending.remove();
            appendChat("Could not reach the server. Try again.", "bot");
        } finally {
            send.disabled = false;
            setRepliesDisabled(false);
            $("bh-input").focus();
        }
    }

    /** Older keyboards stay on screen, as they do in a real chat, but a
     *  second tap while one request is in flight would interleave replies. */
    function setRepliesDisabled(disabled) {
        $("bh-chat").querySelectorAll(".bh-reply").forEach(function (button) {
            button.disabled = disabled;
        });
    }

    function sendTestMessage(event) {
        event.preventDefault();
        var input = $("bh-input");
        var text = input.value;
        input.value = "";
        sendMessage(text);
    }

    /* ── Save ────────────────────────────────────────────────────── */

    function syncDirty() {
        var dirty = isDirty();
        var state = $("bh-savestate");
        state.classList.toggle("is-dirty", dirty);
        state.classList.toggle("is-saved", !dirty);
        $("bh-savestate-text").textContent = dirty ? "Unsaved changes" : "All changes saved";
        // A tick beside "Unsaved changes" says the opposite of the words.
        $("bh-savestate-glyph").setAttribute("d", dirty
            ? "M12 8v5M12 16h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z"
            : "m5 13 4 4L19 7");
        $("bh-save").disabled = !dirty || busy;
        $("bh-reset").disabled = !dirty || busy;
        $("bh-footer-note").textContent = dirty
            ? "Changes apply to every connected channel once saved."
            : "";
    }

    async function save() {
        if (botLoadFailed || !isDirty() || busy) return;

        busy = true;
        syncDirty();
        $("bh-save-label").textContent = "Saving…";
        banner("bh-banner", "", "");

        var labels = draft.menu.map(function (l) { return l.trim(); }).filter(Boolean);

        try {
            var response = await authenticatedFetch("/api/bots/" + botId, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    ai_provider: draft.ai_provider,
                    model_name: draft.model_name,
                    temperature: draft.temperature,
                    // Both channels are written together, as the previous page
                    // did, so they can never drift apart.
                    telegram_buttons_enabled: draft.quickReplies,
                    whatsapp_buttons_enabled: draft.quickReplies,
                    telegram_markdown_enabled: draft.markdown,
                    whatsapp_markdown_enabled: draft.markdown,
                    welcome_menu_labels: labels
                })
            });
            var body = await response.json();

            if (body.status === "success") {
                draft.menu = labels;
                saved = clone(draft);
                banner("bh-banner", "success", "Saved. Connected channels are using these settings now.");
                window.dispatchEvent(new CustomEvent("recheckBotStatus"));
            } else {
                banner("bh-banner", "error", body.message || "Could not save. Your changes are still here.");
            }
        } catch (_) {
            banner("bh-banner", "error", "Could not reach the server. Your changes are still here.");
        } finally {
            busy = false;
            $("bh-save-label").textContent = "Save changes";
            renderAll();
            syncDirty();
        }
    }

    function resetChanges() {
        draft = clone(saved);
        $("bh-quick-replies").checked = draft.quickReplies;
        $("bh-markdown").checked = draft.markdown;
        renderAll();
        syncDirty();
        banner("bh-banner", "", "");
    }

    async function generateMenu() {
        var button = $("bh-menu-generate");
        button.disabled = true;
        banner("bh-banner", "", "");

        try {
            var response = await authenticatedFetch("/api/bots/" + botId + "/generate-welcome-menu", { method: "POST" });
            var body = await response.json();

            if (body.status === "success" && Array.isArray(body.data) && body.data.length) {
                // Suggestions fill the menu but are not committed — the operator
                // still has to read them and press Save.
                draft.menu = body.data
                    .map(function (item) { return typeof item === "string" ? item : (item && item.label) || ""; })
                    .map(function (l) { return String(l).trim(); })
                    .filter(Boolean)
                    .slice(0, MAX_MENU_BUTTONS);
                renderMenu();
                renderPreview();
                renderCurrent();
                syncDirty();
                banner("bh-banner", "success", "Suggested from your knowledge. Edit anything, then save.");
            } else {
                banner("bh-banner", "error", body.message || "Could not suggest buttons. Add primary knowledge first.");
            }
        } catch (_) {
            banner("bh-banner", "error", "Could not reach the server. Try again.");
        } finally {
            button.disabled = false;
        }
    }

    /* ── Boot ────────────────────────────────────────────────────── */

    /**
     * Stop the studio and say why, without moving the operator anywhere.
     *
     * Every tab is hidden rather than disabled: there is nothing behind them
     * to read, and an empty form invites an edit that could never be saved.
     * `botLoadFailed` then keeps `save()` from firing a PUT for a bot this
     * session was just told it cannot touch.
     */
    function showBotAccessDeniedState() {
        botLoadFailed = true;

        $("bh-tabs").hidden = true;
        $("bh-footer").hidden = true;
        TABS.forEach(function (name) { $("bh-panel-" + name).hidden = true; });

        $("bh-bot-name").textContent = "this bot";
        banner("bh-banner", "error", "Chatbot not found or you do not have access.");
    }

    function renderAll() {
        renderStyles();
        renderProviders();
        renderPlanNote();
        renderCurrent();
        renderMenu();
        renderPreview();
    }

    function wire() {
        TABS.forEach(function (name) {
            $("bh-tab-" + name).addEventListener("click", function (event) {
                event.preventDefault();
                showTab(name, true);
            });
        });

        window.addEventListener("popstate", function () { showTab(readTab(), false); });

        document.querySelectorAll(".bh-style input").forEach(function (input) {
            input.addEventListener("change", function () {
                if (input.value === "custom") return;   // custom is display-only
                draft.temperature = parseFloat(input.value);
                renderStyles();
                renderCurrent();
                syncDirty();
            });
        });

        $("bh-temp").addEventListener("input", function () {
            // Moving the number is what creates a Custom value; the cards follow
            // it rather than fighting it, so the two can never disagree.
            draft.temperature = Math.round(parseFloat($("bh-temp").value) * 100) / 100;
            renderStyles();
            renderCurrent();
            syncDirty();
        });

        $("bh-provider").addEventListener("change", function () {
            draft.ai_provider = $("bh-provider").value;
            draft.model_name = "";
            renderModels();
            renderCurrent();
            syncDirty();
        });

        $("bh-model").addEventListener("change", function () {
            draft.model_name = $("bh-model").value;
            renderCurrent();
            syncDirty();
        });

        $("bh-menu-add").addEventListener("click", function () {
            if (draft.menu.length >= MAX_MENU_BUTTONS) return;
            draft.menu.push("");
            renderMenu();
            renderCurrent();
            syncDirty();
            var inputs = $("bh-menu").querySelectorAll("input");
            if (inputs.length) inputs[inputs.length - 1].focus();
        });

        $("bh-menu-generate").addEventListener("click", generateMenu);

        ["bh-quick-replies", "bh-markdown"].forEach(function (id) {
            $(id).addEventListener("change", function () {
                draft.quickReplies = $("bh-quick-replies").checked;
                draft.markdown = $("bh-markdown").checked;
                renderPreview();
                syncDirty();
            });
        });

        $("bh-save").addEventListener("click", save);
        $("bh-reset").addEventListener("click", resetChanges);
        $("bh-composer").addEventListener("submit", sendTestMessage);
        $("bh-chat-clear").addEventListener("click", function () {
            $("bh-chat").replaceChildren();
            renderChatEmpty();
        });

        $("bh-scenarios-refresh").addEventListener("click", function () {
            loadScenarios(true);
        });

        // Losing edits to a stray back button or tab close is the one failure
        // this screen cannot recover from, so it is the one worth interrupting.
        window.addEventListener("beforeunload", function (event) {
            if (!isDirty()) return;
            event.preventDefault();
            event.returnValue = "";
        });
    }

    async function boot() {
        wire();

        catalogue = await window.modelCatalog.load();

        try {
            var response = await authenticatedFetch("/api/bots/" + botId);
            var body = await response.json();

            // A stale link or a bot in another company must say so and stay
            // put. Bouncing to bots.html leaves the operator on a list with no
            // idea why, which is the regression this branch exists to prevent.
            if (response.status === 403 || response.status === 404) {
                showBotAccessDeniedState();
                return;
            }

            if (!response.ok || body.status !== "success" || !body.data) {
                window.location.href = "bots.html";
                return;
            }

            botLoadFailed = false;
            var bot = body.data;
            $("bh-bot-name").textContent = bot.bot_name || "your bot";
            document.querySelector("chatbot-sidebar")?.setBotName?.(bot.bot_name);
            document.title = (bot.bot_name || "Bot") + (isSetup && readTab() === "test" ? " - Test your bot | Aveon" : " - Behaviour Studio | AI CHATBOT");

            draft = fromBot(bot);
            saved = clone(draft);
        } catch (_) {
            draft = blankDraft();
            saved = clone(draft);
            banner("bh-banner", "error", "Could not load this bot's settings. Reload to try again.");
        }

        $("bh-quick-replies").checked = draft.quickReplies;
        $("bh-markdown").checked = draft.markdown;

        if (!hasEntitledFeature("ai_assisted_menu_generation")) {
            var menuGenerateBtn = $("bh-menu-generate");
            if (menuGenerateBtn) {
                menuGenerateBtn.disabled = true;
                menuGenerateBtn.title = "Upgrade to use";
                menuGenerateBtn.style.opacity = "0.5";
                menuGenerateBtn.style.cursor = "not-allowed";
            }
        }

        renderAll();
        showTab(readTab(), false);
        syncDirty();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})();
