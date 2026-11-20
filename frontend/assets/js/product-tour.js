/* ══════════════════════════════════════════════════════════════════════
   PRODUCT TOUR - teaches a new user the dashboard one step at a time

   Each step points at one thing on one page. Next and Back walk the steps
   in order and open the right page themselves; the only step the user
   must do is choosing a bot, because every page after My bots belongs to
   one. The tour also follows the user: guided setup moves people with its
   own buttons ("Continue to instructions"), so on every page the tour
   shows the first step there that the user has not seen yet.

   Clicking the page or pressing Escape puts the card away without leaving
   anything on screen; it never sits over a button the user needs. Skip
   ends the tour for good, and Help on My bots starts it again.

   Progress is kept per user in localStorage. Copy is plain English;
   app-preferences.js translates it like any other text, so every sentence
   below needs a matching entry there.

   Pages that cannot know when their content is ready (bots.html renders
   its list after a fetch) load this script with data-resume="manual" and
   call omnexaTour.offer() themselves.
   ══════════════════════════════════════════════════════════════════════ */

(function () {
    "use strict";

    // Recommended order. Targets are tried in order; the first one on screen is highlighted.
    const STEPS = [
        {
            id: "welcome", page: "bots.html", primary: "Start tour",
            title: "Welcome to Omnexa",
            text: "This tour shows you how to set up your bot, one step at a time. It takes about two minutes."
        },
        {
            id: "bot", page: "bots.html", action: true,
            options: [
                {
                    target: [".open-bot-link"], title: "Open a bot",
                    text: "Open the bot you want to set up. The tour carries on inside it."
                },
                {
                    target: [".empty-state [data-create-bot-trigger]", "[data-create-bot-trigger]"],
                    title: "Create your first bot",
                    text: "Create a bot and give it a name. The tour carries on as soon as it is saved."
                }
            ]
        },
        {
            id: "next", page: "index.html",
            target: [".dash-nextstep"],
            title: "Your next step",
            text: "The Overview page always shows the one thing to do next. Choose its button to go straight there."
        },
        {
            // The details element, not its list: the list is collapsed while setup is guided.
            id: "checks", page: "index.html",
            target: ["#dash-readiness", ".dash-setup"],
            title: "Check your setup",
            text: "Setup checks lists every setup step. Each one turns green when it is done."
        },
        {
            id: "knowledge", page: "new_linkdocs.html?setup=1", manageOnly: true,
            target: [".kw-guided-upload", ".kw-page .kw-panel"],
            title: "Add knowledge",
            text: "Upload a PDF about your business, such as your services, prices and opening hours. Your bot answers customers from this document."
        },
        {
            id: "instructions", page: "new_prompt.html?setup=1", manageOnly: true,
            target: ["[aria-labelledby='bc-library-title']", ".bc-wizard"],
            title: "Review the instructions",
            text: "Omnexa writes instructions from your PDF. They tell the bot how to talk to customers. Check them, fix anything wrong, then apply them."
        },
        {
            id: "test", page: "behaviour.html?tab=test&setup=1", manageOnly: true,
            target: ["#bh-composer", "#bh-panel-test"],
            title: "Test a reply",
            text: "Type a question the way a customer would. If the answer is wrong, update the PDF or the instructions and test again."
        },
        {
            id: "publish", page: "integration.html?setup=1",
            target: ["#pub-options"],
            title: "Publish your bot",
            text: "Choose where customers can reach your bot: WhatsApp, Telegram, a share link or your website. Nothing goes live until you connect a channel."
        },
        {
            id: "inbox", page: "conversations.html",
            target: ["#conv-pipeline"],
            title: "Read customer chats",
            text: "Customer conversations appear here. Open one to read it, or reply yourself when a customer needs a person."
        },
        {
            id: "menu", page: "conversations.html",
            target: ["#bot-sidebar-navigation", ".sidebar-toggle"],   // phones fold the menu behind its toggle
            title: "Find everything in the menu",
            text: "Use this menu to move between your bot's pages. To see this tour again, choose Help on the My bots page."
        }
    ];

    const FALLBACK_MS = 4000;   // a target this late is drawn centered, then anchored if it appears
    const GIVE_UP_MS = 20000;
    const POLL_MS = 150;
    const GAP = 12;
    const MARGIN = 12;
    const RING_PAD = 6;

    const user = readUser();
    const canManage = user.role === "owner" || user.role === "admin";
    const steps = STEPS.filter(step => canManage || !step.manageOnly);
    const botStep = steps.find(step => step.action);
    const storeKey = "omnexa-tour:" + (user.id || "anonymous");
    const manualResume = Boolean(document.currentScript && document.currentScript.dataset.resume === "manual");

    let state = loadState();    // { status, seen: [ids in the order first shown], current, parked }
    let ui = null;              // { ring, card, index, target } while a step is on screen
    let renderToken = 0;
    let returnFocus = null;

    function readUser() {
        try { return JSON.parse(sessionStorage.getItem("user")) || {}; } catch (_) { return {}; }
    }

    function indexOfId(id) {
        return steps.findIndex(step => step.id === id);
    }

    function loadState() {
        try {
            const raw = JSON.parse(localStorage.getItem(storeKey));
            if (!raw || typeof raw.status !== "string") return null;
            return {
                status: raw.status,
                seen: Array.isArray(raw.seen) ? raw.seen.filter(id => indexOfId(id) >= 0) : [],
                current: indexOfId(raw.current) >= 0 ? raw.current : null,
                parked: raw.parked === true
            };
        } catch (_) { return null; }
    }

    function update(changes) {
        state = { ...state, ...changes };
        try { localStorage.setItem(storeKey, JSON.stringify(state)); } catch (_) { /* storage disabled: works for this page view */ }
    }

    function botId() {
        const candidate = new URLSearchParams(location.search).get("bot_id") || sessionStorage.getItem("selectedBotId");
        return /^[1-9][0-9]*$/.test(candidate || "") ? candidate : "";
    }

    function isOnPage(step) {
        const want = new URL(step.page, location.href);
        if (want.pathname.replace(/\.html$/, "") !== location.pathname.replace(/\.html$/, "")) return false;
        const here = new URLSearchParams(location.search);
        // setup=1 only changes a page's guidance, not which page it is.
        return [...want.searchParams].every(([key, value]) => key === "setup" || here.get(key) === value);
    }

    function isInsideBot() {
        return Boolean(botId()) && !isOnPage(steps[0]);
    }

    function hrefFor(step) {
        const url = new URL(step.page, location.href);
        const bot = botId();
        if (bot && step.page !== steps[0].page) url.searchParams.set("bot_id", bot);
        return url.href;
    }

    function optionsOf(step) {
        return step.options || [{ target: step.target, title: step.title, text: step.text }];
    }

    // checkVisibility() also sees content inside a closed <details>, which still has a layout box.
    function isShown(node) {
        if (!node.isConnected) return false;
        if (typeof node.checkVisibility === "function" && !node.checkVisibility()) return false;
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function findOption(step) {
        for (const option of optionsOf(step)) {
            for (const selector of option.target || []) {
                const target = [...document.querySelectorAll(selector)].find(isShown);
                if (target) return { option, target };
            }
        }
        return null;
    }

    // Next walks forward through what was already seen, then to the next unseen step in the
    // recommended order, wrapping round. -1 means every step has been seen: this one is the last.
    function nextIndex(index) {
        const position = state.seen.indexOf(steps[index].id);
        if (position >= 0 && position < state.seen.length - 1) return indexOfId(state.seen[position + 1]);
        for (let offset = 1; offset < steps.length; offset++) {
            const candidate = (index + offset) % steps.length;
            if (!state.seen.includes(steps[candidate].id)) return candidate;
        }
        return -1;
    }

    function previousIndex(index) {
        const position = state.seen.indexOf(steps[index].id);
        return position > 0 ? indexOfId(state.seen[position - 1]) : -1;
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text) node.textContent = text;
        return node;
    }

    function button(label, className, onClick) {
        const node = el("button", `product-tour-btn ${className}`.trim(), label);
        node.type = "button";
        node.addEventListener("click", onClick);
        return node;
    }

    /* ── showing one step ─────────────────────────────────────────────── */

    function go(index) {
        update({ status: "active", current: steps[index].id, parked: false });
        if (isOnPage(steps[index])) show(index);
        else location.assign(hrefFor(steps[index]));
    }

    function show(index) {
        const token = ++renderToken;
        const step = steps[index];
        const first = optionsOf(step)[0];
        const started = Date.now();
        if (!first.target) return render(index, first, null);

        let drawnWithoutTarget = false;
        (function poll() {
            if (token !== renderToken) return;
            const found = findOption(step);
            if (found) return render(index, found.option, found.target);
            const waited = Date.now() - started;
            // A card already on screen means the page has loaded: waiting would just freeze the old step.
            if (!drawnWithoutTarget && (ui || waited >= FALLBACK_MS)) {
                drawnWithoutTarget = true;
                render(index, first, null);
            }
            if (waited < GIVE_UP_MS) setTimeout(poll, POLL_MS);
        })();
    }

    function render(index, option, target) {
        const step = steps[index];
        const seen = state.seen.includes(step.id) ? state.seen : [...state.seen, step.id];
        update({ seen, current: step.id, parked: false });

        if (!ui) {
            returnFocus = document.activeElement;
            ui = { ring: el("div", "product-tour-ring"), card: el("div", "product-tour") };
            ui.ring.setAttribute("aria-hidden", "true");
            ui.card.setAttribute("role", "dialog");
            ui.card.setAttribute("aria-labelledby", "product-tour-title");
            ui.card.setAttribute("aria-describedby", "product-tour-text");
            ui.card.tabIndex = -1;
            document.body.append(ui.ring, ui.card);
            listen(true);
        }
        ui.index = index;
        ui.target = target;

        const position = seen.indexOf(step.id) + 1;
        const count = el("span", "product-tour-count", `${position} / ${steps.length}`);
        const progress = el("span", "product-tour-progress");
        progress.setAttribute("aria-hidden", "true");
        progress.style.setProperty("--product-tour-done", `${(position / steps.length) * 100}%`);
        const head = el("div", "product-tour-head");
        head.append(count, progress);

        const title = el("h2", "product-tour-title", option.title);
        title.id = "product-tour-title";
        const text = el("p", "product-tour-text", option.text);
        text.id = "product-tour-text";

        const actions = el("div", "product-tour-actions");
        actions.append(button("Skip tour", "is-quiet", () => end("skipped")), el("span", "product-tour-spacer"));
        const back = previousIndex(index);
        if (back >= 0) actions.append(button("Back", "", () => go(back)));
        if (!step.action) {
            const next = nextIndex(index);
            actions.append(button(step.primary || (next < 0 ? "Finish" : "Next"), "is-primary",
                () => (next < 0 ? end("done") : go(next))));
        }

        ui.card.replaceChildren(head, title, text);
        if (step.action) ui.card.append(el("p", "product-tour-hint", "Do this step to continue."));
        ui.card.append(actions);
        ui.card.classList.toggle("is-centered", !target);
        ui.ring.classList.toggle("is-empty", !target);

        if (target) {
            if (resizeObserver) resizeObserver.observe(target);   // panels grow as their data arrives
            target.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
        }
        place();
        ui.card.focus({ preventScroll: true });
    }

    function place() {
        if (!ui) return;
        const { ring, card } = ui;
        if (ui.target && !isShown(ui.target)) {
            // A re-render replaced or hid the node: follow what replaced it, else teach from the centre.
            const found = findOption(steps[ui.index]);
            ui.target = found ? found.target : null;
            card.classList.toggle("is-centered", !ui.target);
            ring.classList.toggle("is-empty", !ui.target);
        }
        if (!ui.target) {
            Object.assign(ring.style, { left: "50%", top: "50%", width: "0px", height: "0px" });
            card.style.left = card.style.top = "";
            return;
        }

        const rect = ui.target.getBoundingClientRect();
        Object.assign(ring.style, {
            left: `${rect.left - RING_PAD}px`, top: `${rect.top - RING_PAD}px`,
            width: `${rect.width + RING_PAD * 2}px`, height: `${rect.height + RING_PAD * 2}px`
        });

        const vw = document.documentElement.clientWidth;
        const vh = window.innerHeight;
        const w = card.offsetWidth;
        const h = card.offsetHeight;
        const clampX = x => Math.min(Math.max(x, MARGIN), vw - w - MARGIN);
        const clampY = y => Math.min(Math.max(y, MARGIN), vh - h - MARGIN);
        let spot;
        if (vh - rect.bottom >= h + GAP + MARGIN) spot = [clampX(rect.left), rect.bottom + GAP];
        else if (rect.top >= h + GAP + MARGIN) spot = [clampX(rect.left), rect.top - GAP - h];
        else if (vw - rect.right >= w + GAP + MARGIN) spot = [rect.right + GAP, clampY(rect.top)];
        else if (rect.left >= w + GAP + MARGIN) spot = [rect.left - GAP - w, clampY(rect.top)];
        else spot = [clampX(rect.left), vh - h - MARGIN];   // the target fills the screen
        card.style.left = `${spot[0]}px`;
        card.style.top = `${spot[1]}px`;
    }

    let placeQueued = false;
    function queuePlace() {
        if (placeQueued) return;
        placeQueued = true;
        requestAnimationFrame(() => { placeQueued = false; place(); });
    }

    const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(queuePlace) : null;

    // On click, not pointerdown: the card must not vanish from under a finger that has not lifted yet.
    function onPageClick(event) {
        if (ui && !ui.card.contains(event.target)) park();
    }

    function onKeyDown(event) {
        if (event.key !== "Escape" || !ui) return;
        park();
        restoreFocus();
    }

    function listen(on) {
        const method = on ? "addEventListener" : "removeEventListener";
        window[method]("resize", queuePlace);
        window[method]("scroll", queuePlace, true);
        document[method]("click", onPageClick, true);
        document[method]("keydown", onKeyDown);
        if (!resizeObserver) return;
        if (on) resizeObserver.observe(document.body);
        else resizeObserver.disconnect();
    }

    function hide() {
        renderToken++;
        if (!ui) return;
        listen(false);
        ui.ring.remove();
        ui.card.remove();
        ui = null;
    }

    function restoreFocus() {
        if (returnFocus && returnFocus.isConnected && typeof returnFocus.focus === "function") returnFocus.focus();
        returnFocus = null;
    }

    function reducedMotion() {
        return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    }

    // The user is working: put the card away. The next tour page they open shows its own step.
    function park() {
        hide();
        update({ parked: true });
    }

    function end(status) {
        update({ status, parked: true });
        hide();
        restoreFocus();
    }

    /* ── entry points ─────────────────────────────────────────────────── */

    function resume() {
        if (!state || state.status !== "active") return;
        // Inside a bot, the bot step is done whether or not the tour showed it.
        if (botStep && isInsideBot() && !state.seen.includes(botStep.id)) update({ seen: [...state.seen, botStep.id] });
        const current = indexOfId(state.current);
        if (current >= 0 && !state.parked && isOnPage(steps[current])) return show(current);
        const fresh = steps.findIndex(step => isOnPage(step) && !state.seen.includes(step.id));
        if (fresh >= 0) show(fresh);
    }

    function start() {
        hide();
        state = { status: "active", seen: [], current: null, parked: false };
        go(0);
    }

    /* Called by bots.html once its list has rendered. Auto-starts only for an
       owner or admin with no bots yet, so existing customers are never
       interrupted; everyone else starts it from Help. */
    function offer(activeBotCount) {
        if (ui) return;
        if (state) return resume();
        if (canManage && activeBotCount === 0) start();
    }

    window.omnexaTour = { start, offer };

    if (!manualResume) {
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", resume);
        else resume();
    }
})();
