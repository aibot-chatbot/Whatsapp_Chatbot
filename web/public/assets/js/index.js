
        requireLogin();

        const urlParams = new URLSearchParams(window.location.search);
        const urlBotId = urlParams.get("bot_id");
        const storedBotId = sessionStorage.getItem("selectedBotId");
        if (urlParams.get('setup') === '1') {
            document.getElementById('dash-monitoring').open = false;
            document.getElementById('dash-readiness').open = false;
            document.body.classList.add('is-guided-setup');
        }
        let setupViewInitialized = false;

        let selectedBotId = urlBotId;

        if (!urlBotId && storedBotId) {
            window.location.href = `index.html?bot_id=${encodeURIComponent(storedBotId)}`;
            selectedBotId = storedBotId;
        }

        if (!selectedBotId) {
            window.location.href = "bots.html";
        }

        if (selectedBotId) {
            sessionStorage.setItem("selectedBotId", selectedBotId);
        }

        // Latest chart series, kept so the mobile day stepper can read a day
        // without refetching.
        let trendSeries = { labels: [], data: [] };
        let trendIndex = 0;

        document.addEventListener('DOMContentLoaded', () => {
            if (!selectedBotId) {
                return;
            }

            updateDate();
            updateDashboardLinks();
            initSettingsMenu();
            initDayStepper();

            window.addEventListener('resize', () => {
                updateDate();
            });

            fetchSelectedBot();
            fetchBotHealth();
            fetchDashboardData();

            setInterval(fetchLiveWorkflow, 1500);
        });

        function $(id) {
            return document.getElementById(id);
        }

        function setText(id, value) {
            const el = $(id);
            if (el) el.textContent = value;
        }

        /* -- Header ------------------------------------------------- */

        function updateDate() {
            const dateEl = $('date-display');
            if (!dateEl) return;

            const now = new Date();
            const isNarrow = window.matchMedia('(max-width: 420px)').matches;
            // Intl rather than a hardcoded format, so the reading matches the
            // viewer's locale and timezone.
            const options = isNarrow
                ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
                : { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
            dateEl.textContent = new Intl.DateTimeFormat(undefined, options).format(now);
            dateEl.setAttribute('datetime', now.toISOString());
        }

        // POST /api/match/check is @role_required("admin", "owner"), so the
        // auto-check must know the role before firing — a member would get 403.
        let canManage = false;

        function updateDashboardLinks() {
            let role = "";
            try {
                const user = JSON.parse(sessionStorage.getItem("user") || "null");
                role = String(user?.role || "").toLowerCase();
            } catch (_) {
                role = "";
            }

            canManage = role === "owner" || role === "admin";
            document.querySelectorAll('[data-dashboard-link]').forEach(link => {
                const url = new URL(link.getAttribute('href'), window.location.href);
                url.searchParams.set('bot_id', selectedBotId);
                if (urlParams.get('setup') === '1') url.searchParams.set('setup', '1');
                link.href = `${url.pathname.split('/').pop()}${url.search}`;

                if (link.dataset.manageOnly === "true" && !canManage) {
                    link.hidden = true;
                }
            });
        }

        // Disclosure, not a link list masquerading as a button: the trigger
        // owns aria-expanded, Escape closes, and focus returns to the trigger.
        function initSettingsMenu() {
            const trigger = $('dash-menu-trigger');
            const list = $('dash-menu-list');
            const wrap = $('dash-menu');
            if (!trigger || !list || !wrap) return;

            const close = (refocus) => {
                list.hidden = true;
                trigger.setAttribute('aria-expanded', 'false');
                if (refocus) trigger.focus();
            };

            trigger.addEventListener('click', () => {
                const open = trigger.getAttribute('aria-expanded') === 'true';
                list.hidden = open;
                trigger.setAttribute('aria-expanded', String(!open));
            });

            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape' && !list.hidden) close(true);
            });

            document.addEventListener('click', (event) => {
                if (list.hidden) return;
                if (!wrap.contains(event.target)) close(false);
            });
        }

        /* -- Data --------------------------------------------------- */

        /**
         * A dropped packet and a deleted bot are not the same event and must
         * not get the same response. Ejecting the user back to the picker is
         * correct only for a terminal answer - the bot is gone, or is not
         * theirs. Anything the server might still answer differently is
         * retried behind the loading state, so a blip costs a few seconds
         * instead of the page they were on.
         */
        async function fetchSelectedBot() {
            const outcome = await resilientLoad.loadJson(`/api/bots/${selectedBotId}`, {
                onRetry: () => setText('dash-live-label', "Reconnecting…")
            });

            if (outcome.ok && outcome.data) {
                const botName = outcome.data.bot_name || "Selected bot";
                setText('dashboard-title', botName);
                document.querySelector('chatbot-sidebar')?.setBotName(botName);
                document.title = `${botName} - Dashboard | Omnexa`;
                return;
            }

            if (outcome.terminal) {
                window.location.href = "bots.html";
                return;
            }

            setText('dash-live-label', "Offline");
            setText('dash-systems', "We cannot reach the server. Still trying…");
            scheduleDashboardRecovery();
        }

        /**
         * Last line of defence. resilientLoad has already spent its attempts;
         * this keeps the page trying quietly afterwards so an outage that ends
         * on its own resolves without the user touching anything. One timer is
         * shared by every loader, so three failed loads schedule one recovery,
         * not three.
         */
        let dashboardRecoveryTimer = null;
        const DASHBOARD_RECOVERY_DELAY = 15000;
        // Mirrors the server's page size for /api/agent/escalations
        // (get_pending_escalations, limit=50). A full page means "at least
        // this many", so the card must not present it as an exact count.
        const ESCALATION_PAGE_SIZE = 50;
        // Captured before anything can prefix a count onto it, so the title
        // never accumulates "(3) (2) Dashboard".
        const BASE_TITLE = document.title;

        function scheduleDashboardRecovery() {
            if (dashboardRecoveryTimer) return;
            dashboardRecoveryTimer = setTimeout(() => {
                dashboardRecoveryTimer = null;
                fetchSelectedBot();
                fetchBotHealth();
                fetchDashboardData();
            }, DASHBOARD_RECOVERY_DELAY);
        }

        /**
         * The three reads here are independent and are now kept that way. They
         * used to share one try/catch, so a failure fetching the active
         * knowledge file blanked the message trend that had already rendered
         * successfully - the page lost data it was holding. Each read now owns
         * its own outcome and only writes its own cells.
         */
        async function fetchDashboardData() {
            const analytics = await resilientLoad.loadJson(`/api/analytics?chatbot_id=${selectedBotId}`);

            if (analytics.ok && analytics.data) {
                setText('stat-total-users', formatCount(analytics.data.total_users));
                setText('stat-total-msgs', formatCount(analytics.data.total_messages));

                renderChart(analytics.data.chart?.labels, analytics.data.chart?.data);
                renderHistory(analytics.data.recent_history);
            } else {
                // Terminal is the server's considered answer and is worth
                // stating. Transient is not an answer yet, so say we are still
                // working and keep trying rather than parking on an error.
                showDashboardError(analytics.terminal
                    ? (analytics.message || "Unable to load dashboard data.")
                    : "Still reconnecting to the server…");
                if (!analytics.terminal) scheduleDashboardRecovery();
            }

            const settings = await resilientLoad.loadJson(`/api/settings?chatbot_id=${selectedBotId}`);
            setText('stat-active-profile', settings.ok
                ? (settings.data?.active_profile || "Not selected")
                : "Unavailable");

            const knowledge = await resilientLoad.loadJson(`/api/knowledge/active?chatbot_id=${selectedBotId}`);
            setText('stat-active-pdf', knowledge.ok
                ? (knowledge.data?.file_name || "Not selected")
                : "Unavailable");

            const waiting = await resilientLoad.loadJson(`/api/agent/escalations?chatbot_id=${selectedBotId}`);
            renderWaitingForHuman(waiting);
        }

        /**
         * Show how many customers asked for a person and are still unanswered.
         *
         * A failed read renders an em dash, never 0. "Nobody is waiting" is a
         * claim this page cannot make when it could not reach the server, and
         * a customer waiting unseen is the single failure this card exists to
         * prevent -- so an unknown count has to look unknown.
         *
         * The endpoint pages at ESCALATION_PAGE_SIZE rows, so a full page is
         * shown as "50+" rather than as an exact figure it is not.
         *
         * ponytail: this counts what the queue endpoint already returns, so it
         * needs no new endpoint and no schema change. It tells staff someone
         * is waiting; it cannot tell them whether a colleague is already
         * replying, because no assignee column exists yet. That is HO-2.
         */
        function renderWaitingForHuman(outcome) {
            const link = $('stat-waiting-link');

            if (!outcome.ok || !Array.isArray(outcome.data)) {
                setText('stat-waiting-human', "—");
                setText('stat-waiting-note', "Unavailable — open the queue to check");
                // Keep the link on show: a failed read is exactly when staff
                // need the manual way in. The badge and tab title are left at
                // their last known value on purpose -- clearing them would
                // announce "nobody waiting", which is the one thing an
                // unreachable server cannot tell us.
                if (link) link.hidden = false;
                return;
            }

            const count = outcome.data.length;
            const display = count >= ESCALATION_PAGE_SIZE
                ? `${ESCALATION_PAGE_SIZE}+`
                : String(count);

            setText('stat-waiting-human', display);
            setText('stat-waiting-note', count ? "Needs a reply" : "Nobody waiting");
            if (link) link.hidden = count === 0;
            setWaitingAlert(count ? display : "");
        }

        /**
         * Mirror the waiting count into the two places staff see without
         * looking at this card: the button they click through on, and the
         * browser tab itself. The tab is the one that earns its keep -- an
         * agent working in another tab still sees "(3) Dashboard" in the tab
         * strip, which is as close to a notification as this phase gets
         * without a persistence layer behind it.
         */
        function setWaitingAlert(display) {
            const badge = $('dash-waiting-badge');
            if (badge) {
                badge.hidden = !display;
                badge.textContent = display;
            }
            document.title = display ? `(${display}) ${BASE_TITLE}` : BASE_TITLE;
        }

        function formatCount(value) {
            const n = Number(value);
            return Number.isFinite(n) ? new Intl.NumberFormat().format(n) : "\u2014";
        }

        function showDashboardError(message) {
            setText('stat-total-users', "\u2014");
            setText('stat-total-msgs', "\u2014");
            setText('stat-active-profile', "Unavailable");
            setText('stat-active-pdf', "Unavailable");
            setText('dash-trend-total', "\u2014");
            setText('dash-trend-peak', "\u2014");

            const chart = $('chart-container');
            if (chart) chart.replaceChildren(emptyNote(message));
            const labels = $('chart-labels');
            if (labels) labels.replaceChildren();

            renderActivityMessage(message);
        }

        function emptyNote(message) {
            const p = document.createElement('p');
            p.className = 'kw-muted';
            p.style.textAlign = 'center';
            p.textContent = message;
            return p;
        }

        /* -- Setup progress ----------------------------------------- */

        async function fetchBotHealth() {
            const outcome = await resilientLoad.loadJson(`/api/dashboard/health?chatbot_id=${selectedBotId}`);

            if (!outcome.ok || !outcome.data) {
                // "Unavailable" is a verdict and should only be shown once the
                // server has actually given one. Until then the four setup
                // steps keep reading "Checking…", which is the truth.
                setText('dash-systems', outcome.terminal
                    ? "Bot health is unavailable."
                    : "Checking this bot's setup…");
                if (!outcome.terminal) scheduleDashboardRecovery();
                return;
            }

            renderSetup(outcome.data);
            maybeAutoValidate(outcome.data);
        }

        // True only while an automatic check is in flight, so step 3 can show
        // "Checking…" instead of briefly claiming the setup is unvalidated.
        let autoValidating = false;
        let autoValidateAttempted = false;

        /**
         * Runs the profile/knowledge match check without the user asking.
         *
         * Every run bills AI credits through ai_router, so this fires only when
         * there is genuinely nothing stored to read: both inputs present and
         * `match_result === null`, which the backend sets on upload, on active
         * knowledge change and on set_active_profile. At most once per load, and
         * never for members, who cannot call the endpoint.
         *
         * A false or unavailable result is left for the user to act on — it is
         * never retried automatically, or a failing provider would bill on loop.
         */
        async function maybeAutoValidate(health) {
            if (autoValidateAttempted || !canManage) return;

            const knowledge = health.knowledge || {};
            const profile = health.profile || {};
            if (!profile.active || !knowledge.active) return;
            if (knowledge.match_result !== null && knowledge.match_result !== undefined) return;

            autoValidateAttempted = true;
            autoValidating = true;
            renderSetup(health);

            try {
                const response = await authenticatedFetch(
                    `/api/match/check?chatbot_id=${encodeURIComponent(selectedBotId)}`,
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ profile_name: profile.name || "" })
                    }
                );
                const result = await response.json();
                // Cleared before rendering, not in a finally, or the success
                // render would still read "Checking…".
                autoValidating = false;

                if (result.status === "success" && result.data) {
                    // Re-render from the check's own result rather than refetching
                    // health, which would cost a second round trip for the same facts.
                    renderSetup({
                        ...health,
                        knowledge: {
                            ...knowledge,
                            match_result: result.data.validation_status === "completed"
                                ? Boolean(result.data.match)
                                : null,
                            match_reason: result.data.reason || ""
                        }
                    });
                    return;
                }

                renderSetup(health);
            } catch (err) {
                console.error("Automatic validation failed", err);
                autoValidating = false;
                renderSetup(health);
            }
        }

        /**
         * Turns /api/dashboard/health into the four setup steps and the single
         * next action. Nothing is invented: every state below is read straight
         * off a field the endpoint already returns.
         */
        function renderSetup(data) {
            const profile = data.profile || {};
            const knowledge = data.knowledge || {};
            const channels = data.channels || {};
            const warnings = Array.isArray(data.warnings) ? data.warnings : [];

            // `match_result` is the real tri-state (true / false / null) read
            // straight off chatbots.last_match_result. `validation_status` is a
            // display label ("Profile validated", "Validation not checked"), so
            // comparing it to machine values pinned this step to "needs
            // attention" forever. null means never run, or invalidated by a
            // profile/knowledge change — which is what arms the auto-check.
            const matchResult = knowledge.match_result;
            const validated = matchResult === true;
            const channelCount = Number(channels.connected_count || 0);

            const steps = [
                {
                    key: "profile",
                    done: Boolean(profile.active),
                    state: profile.active ? "Ready" : "Needs attention",
                    hint: profile.active
                        ? `Applied instructions: ${profile.name || "unnamed"}`
                        : "Review and apply the instructions your bot will use.",
                    href: "new_prompt.html",
                    cta: "Review instructions",
                    title: "Tell your bot how to help",
                    copy: "Choose your bot's instructions, check them against your PDF, and apply them before testing."
                },
                {
                    key: "knowledge",
                    done: Boolean(knowledge.active),
                    state: knowledge.active ? "Ready" : "Needs attention",
                    hint: knowledge.active
                        ? `Primary knowledge: ${knowledge.file_name || "active"}`
                        : "Add primary knowledge to get accurate answers.",
                    href: "new_linkdocs.html",
                    cta: "Add knowledge",
                    title: "Add a PDF for your bot to learn from",
                    copy: "Upload a PDF about your business, products, or services. You can add more knowledge later."
                },
                {
                    key: "validate",
                    done: validated,
                    state: autoValidating ? "Checking…"
                        : matchResult === true ? "Passed"
                        : matchResult === false ? "Needs attention"
                        : "Not checked",
                    hint: autoValidating
                        ? "Checking the profile against the primary knowledge…"
                        : matchResult === false
                            ? (knowledge.match_reason || "The profile and the primary knowledge describe different things.")
                            : "Checks the profile matches the primary knowledge.",
                    href: "new_prompt.html",
                    cta: matchResult === false ? "Review instructions" : "Check instructions",
                    title: matchResult === false ? "Profile and knowledge do not match" : "Validate your setup",
                    // The dashboard has no profile or knowledge controls, so a
                    // failure routes to bot configuration rather than trying to
                    // offer the fix here.
                    copy: matchResult === false
                        ? (knowledge.match_reason || "Open bot configuration to change the profile or the primary knowledge.")
                        : "Check the active profile against the active primary knowledge before going live."
                },
                {
                    key: "channel",
                    done: channelCount > 0,
                    state: channelCount > 0 ? "Connected" : "Not connected",
                    hint: channelCount > 0
                        ? channelSummary(channels)
                        : "Connect a channel to reach customers.",
                    href: "integration.html",
                    cta: "Open channels",
                    title: "Connect a channel",
                    copy: "Choose WhatsApp, Telegram, a share link, or a website embed. Nothing is published until you choose."
                }
            ];
            // Knowledge comes first for a new bot; profile.active reflects
            // applied runtime instructions, not an unreviewed draft.
            [steps[0], steps[1]] = [steps[1], steps[0]];

            steps.forEach((step, index) => {
                const el = document.querySelector(`.dash-step[data-step="${step.key}"]`);
                if (!el) return;

                el.classList.toggle('is-done', step.done);
                el.classList.toggle('is-attention', !step.done);

                const mark = el.querySelector('.kw-step-mark');
                if (mark) mark.replaceChildren(step.done ? checkIcon() : stepNumber(index + 1));

                const state = el.querySelector('.dash-step-state');
                if (state) state.textContent = step.state;

                const hint = el.querySelector('.dash-step-hint');
                if (hint) hint.textContent = step.hint;
            });

            const next = steps.find(step => !step.done);
            const guided = canManage && (urlParams.get('setup') === '1' || channelCount === 0);
            document.body.classList.toggle('is-guided-setup', guided);
            const journey = $('dashboard-setup-journey');
            journey.hidden = !guided;
            journey.setAttribute('bot-id', selectedBotId);
            journey.setAttribute('current', next?.key === 'knowledge' ? 'knowledge'
                : next?.key === 'channel' ? 'test' : next ? 'instructions' : 'publish');
            if (!setupViewInitialized) {
                $('dash-monitoring').open = !guided;
                $('dash-readiness').open = !guided;
                setupViewInitialized = true;
            }
            renderNextStep(next?.key === 'channel' ? {
                ...next,
                title: 'Check a reply before publishing',
                copy: 'Ask your bot a customer question. When the reply looks right, choose where to publish it.',
                cta: 'Test replies',
                href: 'testbot.html'
            } : next);

            const ready = Boolean(data.ready);
            const live = $('dash-live');
            const dot = $('dash-live-dot');
            if (live) live.classList.toggle('is-idle', !ready);
            if (dot) {
                dot.classList.toggle('is-live', ready);
                dot.classList.toggle('is-idle', !ready);
            }
            setText('dash-live-label', ready ? "Live" : "Setup incomplete");
            setText('dash-systems', ready
                ? (warnings.length
                    ? `${warnings.length} warning${warnings.length > 1 ? "s" : ""} to review`
                    : "All systems operational")
                : "Finish setup before customers arrive");

            const warningsEl = $('bot-health-warnings');
            if (warningsEl) {
                warningsEl.replaceChildren();
                warnings.forEach(message => {
                    const chip = document.createElement('span');
                    chip.className = 'health-warning';
                    chip.textContent = message;
                    warningsEl.appendChild(chip);
                });
            }
        }

        function channelSummary(channels) {
            const items = Array.isArray(channels.items) ? channels.items : [];
            const labels = items.filter(i => i.connected).map(i => i.label || i.type).filter(Boolean);
            return labels.length ? labels.join(", ") : `${channels.connected_count} connected`;
        }

        function renderNextStep(step) {
            const cta = $('dash-next-cta');

            if (!step) {
                setText('dash-next-title', "Setup complete");
                setText('dash-next-copy', "This bot is ready to serve customers. Review conversations in the inbox.");
                if (cta) {
                    cta.hidden = false;
                    setText('dash-next-cta-label', "Open inbox");
                    setLinkHref(cta, "conversations.html");
                }
                return;
            }

            setText('dash-next-title', step.title);
            setText('dash-next-copy', step.copy);
            if (cta) {
                cta.hidden = false;
                setText('dash-next-cta-label', step.cta);
                setLinkHref(cta, step.href);
            }
        }

        function setLinkHref(link, page) {
            link.href = `${page}?bot_id=${encodeURIComponent(selectedBotId)}${urlParams.get('setup') === '1' ? '&setup=1' : ''}`;
        }

        function svgEl(name, attrs) {
            const el = document.createElementNS('http://www.w3.org/2000/svg', name);
            Object.keys(attrs || {}).forEach(key => el.setAttribute(key, attrs[key]));
            return el;
        }

        function checkIcon() {
            const svg = svgEl('svg', { viewBox: '0 0 24 24', class: 'dashboard-icon', 'aria-hidden': 'true' });
            svg.appendChild(svgEl('path', { d: 'm5 13 4 4L19 7' }));
            return svg;
        }

        function stepNumber(n) {
            const span = document.createElement('span');
            span.className = 'kw-mono';
            span.style.fontSize = '12px';
            span.textContent = String(n);
            return span;
        }

        /* -- Message trend ------------------------------------------ */

        const CHART_W = 560;
        const CHART_H = 210;
        const PAD_L = 34;
        const PAD_R = 12;
        const PAD_T = 22;
        const PAD_B = 10;

        /**
         * Gridline spacing: the nearest 1/2/2.5/5 x 10^n at or above max/4.
         * The axis is NOT rounded up to a multiple of this — doing that pushes
         * a 1010 peak onto a 2000 axis and wastes half the plot. Instead the
         * line scales to the real max and gridlines are drawn beneath it, so
         * the labels stay readable (0, 250, 500, 750, 1000) and the shape of
         * the series is preserved.
         */
        function niceStep(value) {
            const rough = Math.max(value, 1) / 4;
            const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
            const n = rough / magnitude;

            // Nearest nice multiple, not the next one up: rounding 2.53 up to 5
            // halves the number of gridlines and leaves the axis unreadable.
            // 2.5 is only offered once it cannot produce a fractional label.
            const m = magnitude >= 10
                ? (n < 1.5 ? 1 : n < 2.25 ? 2 : n < 3.5 ? 2.5 : n < 7.5 ? 5 : 10)
                : (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10);

            return Math.max(m * magnitude, 1);
        }

        /**
         * Inline-SVG line chart. A line is the right mark here because the
         * x-axis is time and the reader's question is "which way is it going",
         * which bars answer worse than a slope does.
         */
        function renderChart(labels, data) {
            const container = $('chart-container');
            const labelsEl = $('chart-labels');
            if (!container || !labelsEl) return;

            const series = Array.isArray(data) ? data.map(Number) : [];
            const names = Array.isArray(labels) ? labels : [];
            trendSeries = { labels: names, data: series };
            trendIndex = Math.max(0, series.length - 1);

            container.replaceChildren();
            labelsEl.replaceChildren();

            if (!series.length) {
                container.appendChild(emptyNote("No messages in this range yet."));
                setText('dash-trend-total', "0");
                setText('dash-trend-peak', "\u2014");
                return;
            }

            // 8% headroom so the printed value above the tallest point has
            // somewhere to sit instead of clipping at the panel edge.
            const max = Math.max(...series, 10) * 1.08;
            const peak = Math.max(...series);
            const peakIndex = peak > 0 ? series.indexOf(peak) : -1;
            const total = series.reduce((sum, n) => sum + n, 0);

            const stepX = (CHART_W - PAD_L - PAD_R) / Math.max(series.length - 1, 1);
            const scaleY = (v) => PAD_T + (1 - v / max) * (CHART_H - PAD_T - PAD_B);
            const pointX = (i) => PAD_L + i * stepX;

            const svg = svgEl('svg', {
                class: 'dash-chart',
                viewBox: `0 0 ${CHART_W} ${CHART_H}`,
                role: 'img'
            });
            svg.setAttribute('aria-label',
                `Messages per day. ${total} in total` +
                (peakIndex >= 0 ? `, busiest on ${names[peakIndex]} with ${peak}` : '') + '.');

            const grid = svgEl('g', { class: 'dash-chart-grid' });
            // Derived from the same floor the scale uses, so a flat/empty
            // series draws a handful of gridlines rather than eleven.
            const step = niceStep(Math.max(peak, 10));
            for (let value = 0; value <= max; value += step) {
                const y = scaleY(value);
                grid.appendChild(svgEl('line', { x1: PAD_L, x2: CHART_W - PAD_R, y1: y, y2: y }));
                const text = svgEl('text', { class: 'dash-chart-axis', x: 0, y: y + 3 });
                text.textContent = new Intl.NumberFormat().format(value);
                grid.appendChild(text);
            }
            svg.appendChild(grid);

            const line = series.map((v, i) => `${pointX(i)},${scaleY(v)}`).join(' ');
            svg.appendChild(svgEl('polyline', { class: 'dash-chart-line', points: line }));

            series.forEach((v, i) => {
                const isPeak = i === peakIndex && peak > 0;
                svg.appendChild(svgEl('circle', {
                    class: i === series.length - 1 ? 'dash-chart-dot is-last' : 'dash-chart-dot',
                    cx: pointX(i), cy: scaleY(v), r: 4
                }));
                const value = svgEl('text', {
                    class: isPeak ? 'dash-chart-value is-peak' : 'dash-chart-value',
                    x: pointX(i), y: scaleY(v) - 11
                });
                value.textContent = String(v);
                svg.appendChild(value);
            });

            container.appendChild(svg);

            labelsEl.style.gridTemplateColumns = `repeat(${series.length}, minmax(0, 1fr))`;
            names.forEach(name => {
                const cell = document.createElement('span');
                const parts = String(name).split(' ');
                cell.textContent = parts.slice(0, 2).join(' ');
                if (parts.length > 2) {
                    const sub = document.createElement('b');
                    sub.textContent = parts.slice(2).join(' ');
                    cell.appendChild(sub);
                }
                labelsEl.appendChild(cell);
            });

            setText('dash-trend-total', new Intl.NumberFormat().format(total));
            setText('dash-trend-peak', peakIndex >= 0
                ? new Intl.NumberFormat().format(peak)
                : "\u2014");
            const peakEl = $('dash-trend-peak');
            if (peakEl && peakIndex >= 0) {
                const small = document.createElement('small');
                small.textContent = ` (${names[peakIndex]})`;
                peakEl.appendChild(small);
            }

            renderDay();
        }

        // On the phone the seven printed values would be unreadable, so the
        // series is stepped through one day at a time instead of shrunk.
        function initDayStepper() {
            const prev = $('dash-day-prev');
            const next = $('dash-day-next');
            if (prev) prev.addEventListener('click', () => {
                trendIndex = Math.max(0, trendIndex - 1);
                renderDay();
            });
            if (next) next.addEventListener('click', () => {
                trendIndex = Math.min(trendSeries.data.length - 1, trendIndex + 1);
                renderDay();
            });
        }

        function renderDay() {
            const labels = trendSeries.labels;
            const data = trendSeries.data;
            if (!data.length) return;

            setText('dash-day-label', labels[trendIndex] || "\u2014");
            setText('dash-day-value', new Intl.NumberFormat().format(data[trendIndex] || 0));

            const prev = $('dash-day-prev');
            const next = $('dash-day-next');
            if (prev) prev.disabled = trendIndex <= 0;
            if (next) next.disabled = trendIndex >= data.length - 1;
        }

        /* -- Recent activity ---------------------------------------- */

        const CHANNEL_LABELS = {
            whatsapp: "WhatsApp",
            telegram: "Telegram",
            webchat: "Web chat",
            web: "Web chat",
            messenger: "Messenger"
        };

        function renderActivityMessage(message) {
            const tbody = $('recent-history-body');
            if (!tbody) return;

            const tr = document.createElement('tr');
            tr.className = 'dash-activity-empty';
            const td = document.createElement('td');
            td.colSpan = 5;
            td.textContent = message;
            tr.appendChild(td);
            tbody.replaceChildren(tr);
        }

        function renderHistory(historyItems) {
            const tbody = $('recent-history-body');
            if (!tbody) return;

            if (!historyItems || !historyItems.length) {
                renderActivityMessage("No conversations yet.");
                return;
            }

            const rows = historyItems.map(item => {
                const stamp = new Date(item.timestamp);
                const valid = !Number.isNaN(stamp.getTime());
                const isRecent = valid && (Date.now() - stamp.getTime() < 86400000);

                const tr = document.createElement('tr');

                const time = document.createElement('td');
                time.className = 'dash-cell-time';
                if (valid) {
                    const t = document.createElement('time');
                    t.dateTime = stamp.toISOString();
                    t.textContent = new Intl.DateTimeFormat(undefined,
                        { hour: '2-digit', minute: '2-digit' }).format(stamp);
                    time.appendChild(t);
                } else {
                    time.textContent = "\u2014";
                }

                const user = document.createElement('td');
                user.className = 'dash-cell-user';
                user.textContent = item.user ? `user_${item.user}` : "unknown";

                const channelKey = String(item.channel || "").toLowerCase();
                const channel = document.createElement('td');
                channel.className = 'dash-cell-channel';
                const channelInner = document.createElement('span');
                channelInner.textContent = CHANNEL_LABELS[channelKey] || (item.channel || "\u2014");
                channel.appendChild(channelInner);

                const msg = document.createElement('td');
                msg.className = 'dash-cell-msg';
                msg.textContent = item.last_content || "\u2014";
                // The full text does not fit at this width; expose it to
                // pointer users without hiding anything the row needs.
                if (item.last_content) msg.title = item.last_content;

                const status = document.createElement('td');
                const badge = document.createElement('span');
                badge.className = isRecent ? 'kw-pill kw-pill-ready' : 'kw-pill';
                badge.textContent = isRecent ? "Active" : "Completed";
                status.appendChild(badge);

                tr.append(time, user, channel, msg, status);
                return tr;
            });

            tbody.replaceChildren(...rows);
        }

        /* -- Live AI workflow --------------------------------------- */

        const FLOW_NODES = ['RECEIVING', 'RAG_SEARCH', 'AI_GENERATING', 'SENDING'];

        async function fetchLiveWorkflow() {
            if (!selectedBotId) return;
            try {
                const response = await authenticatedFetch(`/api/dashboard/live-workflow?chatbot_id=${selectedBotId}`);
                if (!response.ok) return;
                const result = await response.json();
                if (result.status === "success") updateWorkflowUI(result.data);
            } catch (err) {
                // Polling errors are transient; the last good state stays on screen.
            }
        }

        function updateWorkflowUI(workflowData) {
            const message = $('workflow-message-display');
            const aiBlock = $('workflow-ai-response-container');
            const progress = $('workflow-progress-bar');
            const dot = $('dash-flow-dot');

            const state = workflowData && workflowData.state;
            const index = FLOW_NODES.indexOf(state);
            const completed = state === "COMPLETED";

            if (dot) {
                dot.classList.toggle('is-live', Boolean(state));
                dot.classList.toggle('is-idle', !state);
            }
            setText('dash-flow-state', state ? (completed ? "Completed" : "Live") : "Idle");

            if (!state) {
                if (message) message.hidden = true;
                if (progress) progress.style.width = '0%';
                FLOW_NODES.forEach(name => {
                    const node = $(`node-${name}`);
                    if (node) node.classList.remove('is-active', 'is-done');
                });
                return;
            }

            if (message) message.hidden = false;

            const reached = completed ? FLOW_NODES.length - 1 : Math.max(index, 0);
            FLOW_NODES.forEach((name, i) => {
                const node = $(`node-${name}`);
                if (!node) return;
                node.classList.toggle('is-done', i < reached || completed);
                node.classList.toggle('is-active', i === reached && !completed);
            });

            if (progress) {
                const ratio = reached / (FLOW_NODES.length - 1);
                progress.style.width = `${Math.max(0, Math.min(1, ratio)) * 76}%`;
            }

            if (workflowData.message) {
                setText('workflow-user-text', workflowData.message.user_text || workflowData.message.text || "");
                const reply = workflowData.message.ai_text || workflowData.message.response || "";
                if (aiBlock) aiBlock.hidden = !reply;
                if (reply) setText('workflow-ai-text', reply);
            }
        }
    