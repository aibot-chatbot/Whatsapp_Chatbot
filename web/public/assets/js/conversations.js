
        /* ── Bot context: this page shows one bot's conversations ── */
        /* The sidebar and every deep link carry ?bot_id=; without it, this
           tab's last pick. With neither there is no bot to show, so go back
           to My bots, like every other bot page. */
        const BOT_ID = (function resolveBotContext() {
            const urlBotId = new URLSearchParams(window.location.search).get('bot_id');
            const botId = parsePositiveSafeInteger(urlBotId || sessionStorage.getItem('selectedBotId'));
            if (botId) sessionStorage.setItem('selectedBotId', String(botId));
            else window.location.replace('bots.html');
            return botId;
        })();

        // The dashboard's "Waiting for human" card links here with ?awaiting=1
        // so the queue opens already filtered. Without it the agent lands on
        // every conversation and has to find the waiting ones again, which is
        // the work the alert was meant to save them.
        const ARRIVED_AWAITING = new URLSearchParams(window.location.search).get('awaiting') === '1';

        // Captured before anything can prefix a count onto it, so the title
        // never accumulates "(3) (2) Conversations".
        const BASE_TITLE = document.title;

        const STAGES = ['new', 'contacted', 'qualified', 'won', 'lost'];
        const STAGE_LABEL = { new: 'New', contacted: 'Contacted', qualified: 'Qualified', won: 'Won', lost: 'Lost' };
        const STAGE_ALIASES = { in_progress: 'contacted', closed: 'lost' };

        const CHANNEL_LABEL = { whatsapp: 'WhatsApp', wasender: 'WhatsApp', whatchimp: 'WhatsApp', telegram: 'Telegram', web: 'Share link' };
        const CHANNEL_ICON = { whatsapp: 'chat', wasender: 'chat', whatchimp: 'chat', telegram: 'send', web: 'globe' };

        const INTENT_LABEL = {
            lead_interest: 'Interested in buying',
            handoff_request: 'Asked for a human',
            general_question: 'General question'
        };
        const ACTION_LABEL = {
            answer: 'Answered',
            ask_follow_up: 'Asked a follow-up',
            request_handoff: 'Escalated',
            create_lead: 'Logged as a lead',
            log_knowledge_gap: 'Flagged a knowledge gap'
        };
        const LEAD_TYPE_LABEL = {
            staff_attention: 'Flagged for staff attention',
            follow_up: 'Flagged for follow-up'
        };

        const ICON = {
            search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
            chat: '<path d="M4 5h16v11H8l-4 4V5Z"/><path d="M8 9h8M8 12h5"/>',
            send: '<path d="m21 3-9 18-2-7-7-2Z"/>',
            globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18Z"/>',
            lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
            alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
            check: '<path d="m5 13 4 4L19 7"/>',
            refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 4v5h-5"/>'
        };

        function icon(name, extraClass, title) {
            const t = title ? ` title="${escapeHtml(title)}"` : '';
            return `<svg class="dashboard-icon${extraClass ? ' ' + extraClass : ''}" aria-hidden="true" `
                + `viewBox="0 0 24 24"${t}>${ICON[name] || ''}</svg>`;
        }

        function channelGlyph(ch) {
            return icon(CHANNEL_ICON[ch] || 'chat', null, channelLabel(ch))
                + `<span class="kw-visually-hidden">${escapeHtml(channelLabel(ch))}</span>`;
        }

        function channelLabel(ch) {
            return CHANNEL_LABEL[ch] || (ch ? ch.charAt(0).toUpperCase() + ch.slice(1) : 'Unknown channel');
        }

        function escapeHtml(value) {
            if (value === null || value === undefined) return '';
            return String(value)
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#039;');
        }

        /* Bot replies are stored with a trailing [BUTTONS: A | B] tag so each channel
           can rebuild its own buttons; staff see the text and the offered options. */
        function splitButtonsTag(text) {
            const match = /\[BUTTONS?:\s*([\s\S]*?)\]\s*$/i.exec(text);
            if (!match) return { text: text, labels: [] };
            // Same caps as parse_buttons_tag, so staff see exactly what the customer got
            const labels = match[1].split('|').map(label => label.trim().slice(0, 20)).filter(Boolean).slice(0, 3);
            return { text: text.slice(0, match.index).trimEnd(), labels: labels };
        }

        function announce(scope, message) {
            const el = document.getElementById(scope === 'workspace' ? 'conv-announce-workspace' : 'conv-announce-pipeline');
            if (el) el.textContent = message;
        }

        async function getJson(url, options) {
            const response = await authenticatedFetch(url, options);
            let body = {};
            try { body = await response.json(); } catch (e) { body = {}; }
            return { ok: response.ok && body.status === 'success', status: response.status, body };
        }

        /* customer_phone comes back RAW from /api/conversations (select("*")).
           Every place that renders a phone number, including one already
           masked by crm_leads, passes through here. Masking an already
           masked "***1234" is idempotent: 4 digits in, same string out. */
        function maskPhone(phone) {
            if (!phone) return '';
            const digits = String(phone).replace(/\D/g, '');
            if (digits.length >= 4) return '***' + digits.slice(-4);
            return '***';
        }

        function normalizeStage(status) {
            const s = String(status || '').trim().toLowerCase();
            const mapped = STAGE_ALIASES[s] || s;
            return STAGES.includes(mapped) ? mapped : 'new';
        }

        function todayIso() {
            return new Date().toISOString().slice(0, 10);
        }

        function isOverdue(lead) {
            if (!lead || !lead.follow_up_date) return false;
            return lead.follow_up_date < todayIso();
        }

        function formatRelativeTime(iso) {
            if (!iso) return '';
            const then = new Date(iso).getTime();
            if (Number.isNaN(then)) return '';
            const diffMs = Date.now() - then;
            const minutes = Math.floor(diffMs / 60000);
            if (minutes < 1) return 'just now';
            if (minutes < 60) return `${minutes}m ago`;
            const hours = Math.floor(minutes / 60);
            if (hours < 24) return `${hours}h ago`;
            const days = Math.floor(hours / 24);
            if (days < 7) return `${days}d ago`;
            return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        }

        function formatDateShort(dateStr) {
            if (!dateStr) return '';
            const parsed = new Date(dateStr + 'T00:00:00');
            if (Number.isNaN(parsed.getTime())) return dateStr;
            return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        }

        function formatClockTime(iso) {
            if (!iso) return '';
            const parsed = new Date(iso);
            if (Number.isNaN(parsed.getTime())) return '';
            return parsed.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
        }

        function initials(text) {
            const parts = String(text || '').trim().split(/\s+/).filter(Boolean);
            if (!parts.length) return '?';
            if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
            return (parts[0][0] + parts[1][0]).toUpperCase();
        }

        function confidenceBand(confidence) {
            if (confidence === null || confidence === undefined) return null;
            if (confidence >= 0.8) return { text: 'High confidence', level: 'high' };
            if (confidence >= 0.6) return { text: 'Medium confidence', level: 'medium' };
            return { text: 'Low confidence', level: 'low' };
        }

        /* Suppressed entirely for action_type "none" -- the normal quiet case,
           not an empty state. Intent gets a dedicated label for the three
           sales-relevant intents; everything else (including "unknown") falls
           back to what the bot actually did. */
        function buildSignal(action) {
            if (!action || !action.action_type || action.action_type === 'none') return null;
            const label = INTENT_LABEL[action.intent] || ACTION_LABEL[action.action_type];
            if (!label) return null;
            const band = confidenceBand(action.confidence);
            return { text: band ? `${label}, ${band.text}` : label, level: band ? band.level : null };
        }

        /* ── State ─────────────────────────────────────────────────────── */

        const state = {
            loaded: false,
            stale: false,
            conversations: [],
            chatbotIds: [],
            members: [],
            leadsByConv: new Map(),
            escalationsByConv: new Map(),
            intentsCache: new Map(),
            transcriptMessages: [],
            transcriptSearch: '',
            filters: { search: '', channel: '', awaitingHuman: ARRIVED_AWAITING, overdue: false },
            selectedConversationId: null,
            editingHeldId: null,
            heldRequest: 0,
            ownerLocked: false,
            pollTimer: null,
            lastMessageCount: 0
        };

        const els = {};
        document.querySelectorAll('#conv-groups .conv-group').forEach(details => {
            const stage = details.dataset.stage;
            els['group_' + stage] = {
                details,
                count: details.querySelector('[data-part="count"]'),
                listbox: details.querySelector('[role="listbox"]')
            };
        });

        /* ── Generic DOM-diffing list reconciler ──────────────────────────
           Patches existing rows in place, moves/creates/removes only what
           changed, and never touches an element the loop does not need to.
           This is what keeps a poll tick from resetting scroll position or
           collapsing an open <details>. */
        function reconcileChildren(container, items, keyFn, buildFn, patchFn) {
            const existing = new Map();
            Array.from(container.children).forEach(el => {
                if (el.dataset && el.dataset.conversationId) existing.set(el.dataset.conversationId, el);
            });
            let prevEl = null;
            items.forEach(item => {
                const key = String(keyFn(item));
                let el = existing.get(key);
                if (el) {
                    existing.delete(key);
                    patchFn(el, item);
                } else {
                    el = buildFn(item);
                }
                const wantedNext = prevEl ? prevEl.nextElementSibling : container.firstElementChild;
                if (wantedNext !== el) container.insertBefore(el, wantedNext);
                prevEl = el;
            });
            existing.forEach(el => el.remove());
        }

        function applyRovingTabindex(container) {
            const items = Array.from(container.children).filter(el => el.matches('.conv-row, .conv-mini-row'));
            if (!items.length) return;
            if (items.some(el => el.tabIndex === 0)) return;
            items.forEach((el, i) => { el.tabIndex = i === 0 ? 0 : -1; });
        }

        function findMemberById(id) {
            if (!id) return null;
            return state.members.find(m => String(m.id) === String(id)) || null;
        }

        function computeRowData(conv) {
            const lead = state.leadsByConv.get(conv.id) || null;
            const escalation = state.escalationsByConv.has(conv.id);
            const stage = normalizeStage(lead ? lead.status : 'new');
            const priority = lead ? String(lead.priority || '').toLowerCase() : '';
            const cachedSignal = state.intentsCache.get(conv.id) || null;
            const followUp = lead ? lead.follow_up_date : null;
            const overdue = isOverdue(lead);
            const owner = lead ? findMemberById(lead.assigned_to) : null;
            return { lead, escalation, stage, priority, cachedSignal, followUp, overdue, owner };
        }

        function buildChipsHtml(d) {
            const parts = [];
            if (d.escalation) parts.push('<span class="kw-pill kw-pill-review">Awaiting human</span>');
            if (d.priority === 'high') parts.push('<span data-part="priority" data-priority="high">High priority</span>');
            else if (d.priority === 'low') parts.push('<span data-part="priority" data-priority="low">Low priority</span>');
            if (d.cachedSignal) {
                parts.push(`<span data-part="signal" data-signal="${escapeHtml(d.cachedSignal.level || '')}">${escapeHtml(d.cachedSignal.text)}</span>`);
            }
            if (d.followUp) {
                if (d.overdue) parts.push('<span class="kw-pill kw-pill-review">Overdue</span>');
                else parts.push(`<span class="kw-badge">Follow up ${escapeHtml(formatDateShort(d.followUp))}</span>`);
            }
            if (d.owner) {
                const label = d.owner.name || d.owner.email || 'Assigned';
                parts.push(`<span class="conv-avatar" title="Assigned to ${escapeHtml(label)}">${escapeHtml(initials(label))}</span>`);
            } else {
                parts.push('<span class="kw-muted">Unassigned</span>');
            }
            return parts.join('');
        }

        function buildConvRow(conv) {
            const el = document.createElement('div');
            el.className = 'conv-row';
            el.setAttribute('role', 'option');
            el.tabIndex = -1;
            el.dataset.conversationId = String(conv.id);
            patchConvRow(el, conv);
            return el;
        }

        function patchConvRow(el, conv) {
            const d = computeRowData(conv);
            el.setAttribute('aria-selected', String(state.selectedConversationId === conv.id));
            const chips = buildChipsHtml(d);
            el.innerHTML = `
                <span data-part="name">${escapeHtml(conv.customer_name || 'Anonymous visitor')}</span>
                <div data-part="meta">
                    ${channelGlyph(conv.source_channel)}
                    <span class="kw-badge kw-badge-support">${escapeHtml(conv.bot_name || 'Unknown bot')}</span>
                    <span>${escapeHtml(formatRelativeTime(conv.updated_at))}</span>
                    <span data-part="count" class="kw-mono">${Number(conv.message_count || 0)} msg${Number(conv.message_count) === 1 ? '' : 's'}</span>
                </div>
                ${chips ? `<div class="conv-row-chips">${chips}</div>` : ''}
            `;
        }

        function buildMiniRow(conv) {
            const el = document.createElement('div');
            el.className = 'conv-mini-row';
            el.setAttribute('role', 'option');
            el.tabIndex = -1;
            el.dataset.conversationId = String(conv.id);
            patchMiniRow(el, conv);
            return el;
        }

        function patchMiniRow(el, conv) {
            const d = computeRowData(conv);
            const subParts = [];
            if (d.escalation) subParts.push('Awaiting human');
            subParts.push(STAGE_LABEL[d.stage]);
            el.innerHTML = `
                <div data-part="top">
                    ${channelGlyph(conv.source_channel)}
                    <span data-part="name">${escapeHtml(conv.customer_name || 'Anonymous visitor')}</span>
                </div>
                <span data-part="sub">${escapeHtml(subParts.join(', '))}</span>
            `;
        }

        /* ── Filtering ─────────────────────────────────────────────────── */

        function getFilteredConversations() {
            const f = state.filters;
            return state.conversations.filter(conv => {
                if (f.channel && conv.source_channel !== f.channel) return false;
                if (f.awaitingHuman && !state.escalationsByConv.has(conv.id)) return false;
                if (f.overdue && !isOverdue(state.leadsByConv.get(conv.id))) return false;
                if (f.search) {
                    const name = (conv.customer_name || 'Anonymous visitor').toLowerCase();
                    if (!name.includes(f.search)) return false;
                }
                return true;
            });
        }

        function hasActiveFilters() {
            const f = state.filters;
            return Boolean(f.search || f.channel || f.awaitingHuman || f.overdue);
        }

        /* ── Pipeline rendering ────────────────────────────────────────── */

        function updateStats() {
            const counts = { new: 0, contacted: 0, qualified: 0, won: 0, lost: 0 };
            state.conversations.forEach(conv => {
                const lead = state.leadsByConv.get(conv.id);
                counts[normalizeStage(lead ? lead.status : 'new')]++;
            });
            STAGES.forEach(stage => {
                const el = document.querySelector(`#conv-stats [data-stage="${stage}"] [data-part="value"]`);
                if (el) el.textContent = String(counts[stage]);
            });
        }

        function reconcileGroup(stage, items) {
            const group = els['group_' + stage];
            group.count.textContent = String(items.length);
            const placeholder = group.listbox.querySelector('[data-part="group-empty"]');
            if (!items.length) {
                if (!placeholder) {
                    const p = document.createElement('p');
                    p.dataset.part = 'group-empty';
                    p.textContent = 'No conversations in this stage.';
                    group.listbox.innerHTML = '';
                    group.listbox.appendChild(p);
                }
                return;
            }
            if (placeholder) placeholder.remove();
            reconcileChildren(group.listbox, items, c => c.id, buildConvRow, patchConvRow);
            applyRovingTabindex(group.listbox);
        }

        function renderPipeline() {
            const total = state.conversations.length;
            const filtered = getFilteredConversations();
            const grouped = { new: [], contacted: [], qualified: [], won: [], lost: [] };
            filtered.forEach(conv => {
                const lead = state.leadsByConv.get(conv.id);
                grouped[normalizeStage(lead ? lead.status : 'new')].push(conv);
            });
            STAGES.forEach(stage => reconcileGroup(stage, grouped[stage]));
            updateStats();

            const showEmpty = total === 0 || filtered.length === 0;
            document.getElementById('conv-groups').hidden = showEmpty;
            const emptyEl = document.getElementById('conv-pipeline-empty');
            emptyEl.hidden = !showEmpty;

            if (showEmpty) {
                const title = document.getElementById('conv-pipeline-empty-title');
                const body = document.getElementById('conv-pipeline-empty-body');
                const clearBtn = document.getElementById('conv-clear-filters');
                if (total === 0) {
                    title.textContent = 'No conversations yet';
                    body.textContent = 'When a customer starts chatting with this bot, it will show up here.';
                    clearBtn.hidden = true;
                } else {
                    title.textContent = 'No conversations match these filters';
                    body.textContent = 'Try a different search, or clear the filters to see everything.';
                    clearBtn.hidden = !hasActiveFilters();
                }
            }
        }

        function renderMiniRail() {
            const items = getFilteredConversations().filter(c => c.id !== state.selectedConversationId);
            const list = document.getElementById('conv-mini-list');
            reconcileChildren(list, items, c => c.id, buildMiniRow, patchMiniRow);
            applyRovingTabindex(list);
            document.getElementById('conv-mini-count').textContent = String(items.length);
        }

        /* ── Channel filter options ────────────────────────────────────── */

        function rebuildFilterOptions() {
            const chanSel = document.getElementById('conv-filter-channel');
            const channels = new Set();
            state.conversations.forEach(conv => {
                if (conv.source_channel) channels.add(conv.source_channel);
            });
            const prevChan = state.filters.channel || chanSel.value;
            chanSel.innerHTML = '<option value="">All channels</option>' + Array.from(channels)
                .map(ch => `<option value="${escapeHtml(ch)}">${escapeHtml(channelLabel(ch))}</option>`).join('');
            if (channels.has(prevChan)) chanSel.value = prevChan;
        }

        /* ── Data loading ──────────────────────────────────────────────── */

        async function loadBotData() {
            const result = await getJson(`/api/conversations?chatbot_id=${BOT_ID}`);
            // The remembered bot was deleted, archived or belongs to another workspace.
            if (result.status === 403) { clearChatbotContext(); window.location.replace('bots.html'); return; }
            if (!result.ok) throw new Error((result.body && result.body.message) || 'Could not load conversations.');
            const conversations = result.body.data || [];

            const chatbotIds = Array.from(new Set(conversations.map(c => c.chatbot_id).filter(Boolean)));

            const [membersResult, ...fanout] = await Promise.all([
                state.members.length ? Promise.resolve(null) : getJson('/api/company/members'),
                ...chatbotIds.map(id => getJson(`/api/crm/leads?chatbot_id=${id}&limit=100`)),
                ...chatbotIds.map(id => getJson(`/api/agent/escalations?chatbot_id=${id}`))
            ]);

            const leadResults = fanout.slice(0, chatbotIds.length);
            const escalationResults = fanout.slice(chatbotIds.length);

            const leadsByConv = new Map();
            chatbotIds.forEach((chatbotId, i) => {
                const r = leadResults[i];
                if (r && r.ok) {
                    (r.body.data.leads || []).forEach(lead => {
                        leadsByConv.set(lead.conversation_id, Object.assign({ chatbot_id: chatbotId }, lead));
                    });
                }
            });

            const escalationsByConv = new Map();
            chatbotIds.forEach((chatbotId, i) => {
                const r = escalationResults[i];
                if (r && r.ok) {
                    (r.body.data || []).forEach(action => {
                        if (action.conversation_id) {
                            escalationsByConv.set(action.conversation_id, Object.assign({ chatbot_id: chatbotId }, action));
                        }
                    });
                }
            });

            if (membersResult && membersResult.ok) state.members = membersResult.body.data || [];

            state.conversations = conversations;
            state.chatbotIds = chatbotIds;
            state.leadsByConv = leadsByConv;
            state.escalationsByConv = escalationsByConv;
            setWaitingTitle(escalationsByConv.size);
        }

        /**
         * Put the waiting count in the browser tab, the same way the dashboard
         * does. This page polls every 10s, so it is the freshest source in the
         * app -- an agent who leaves this tab open in the background still
         * sees the count climb without switching to it.
         */
        function setWaitingTitle(count) {
            document.title = count > 0 ? `(${count}) ${BASE_TITLE}` : BASE_TITLE;
        }

        async function refresh(isPoll) {
            try {
                await loadBotData();
                state.loaded = true;
                setStale(false);
                document.getElementById('conv-load-error').hidden = true;
                document.getElementById('conv-pipeline-loading').hidden = true;
                rebuildFilterOptions();
                renderPipeline();
                if (state.selectedConversationId) {
                    renderMiniRail();
                    renderWorkspaceHeader();
                    syncComposebarVisibility();
                    /* The lead rail (stage/priority/notes/etc.) and the reply
                       box are only ever repainted from server data when the
                       reader opens the conversation, or right after their own
                       save/send confirms -- never on a background poll tick.
                       Doing it here would blow away notes they are mid-typing
                       or a stage pick they have not yet committed. */
                    if (!isPoll) renderLeadRailFromState();
                    const conv = currentConversation();
                    if (conv) await Promise.all([refreshOpenTranscript(isPoll), loadHeldReplies(conv)]);
                    else resetHeldPanel();
                }
            } catch (error) {
                if (isPoll && state.loaded) {
                    setStale(true);
                    return;
                }
                document.getElementById('conv-pipeline-loading').hidden = true;
                document.getElementById('conv-groups').hidden = true;
                document.getElementById('conv-pipeline-empty').hidden = true;
                const bannerEl = document.getElementById('conv-load-error');
                bannerEl.hidden = false;
                document.getElementById('conv-load-error-text').textContent = error.message || 'We could not load your conversations.';
            }
        }

        function setStale(isStale) {
            state.stale = isStale;
            document.getElementById('conv-stale').classList.toggle('is-visible', isStale);
        }

        function startPolling() {
            if (state.pollTimer) clearInterval(state.pollTimer);
            state.pollTimer = setInterval(() => refresh(true), 10000);
        }

        /* ── Workspace: open / close ───────────────────────────────────── */

        function currentConversation() {
            return state.conversations.find(c => c.id === state.selectedConversationId) || null;
        }

        function setUrlConversationId(id) {
            const url = new URL(window.location.href);
            if (id) url.searchParams.set('conversation_id', String(id));
            else url.searchParams.delete('conversation_id');
            window.history.replaceState({}, '', url);
        }

        async function openConversation(id) {
            const conv = state.conversations.find(c => c.id === id);
            if (!conv) return;

            state.selectedConversationId = id;
            resetHeldPanel();
            state.ownerLocked = false;
            setUrlConversationId(id);

            document.getElementById('conv-pipeline').hidden = true;
            const workspace = document.getElementById('conv-workspace');
            workspace.hidden = false;

            renderPipeline();
            renderMiniRail();
            renderLeadRailFromState();
            renderWorkspaceHeader();
            renderComposebar();

            document.getElementById('conv-transcript').innerHTML = '';
            const heading = document.getElementById('conv-transcript-heading');
            heading.focus({ preventScroll: true });

            await Promise.all([
                loadTranscript(conv),
                loadIntents(conv),
                loadHeldReplies(conv)
            ]);

            announce('workspace', `Opened the conversation with ${conv.customer_name || 'this visitor'}.`);
        }

        function closeWorkspace() {
            const lastId = state.selectedConversationId;
            state.selectedConversationId = null;
            resetHeldPanel();
            setUrlConversationId(null);
            document.getElementById('conv-workspace').hidden = true;
            document.getElementById('conv-pipeline').hidden = false;
            renderPipeline();
            const row = lastId ? document.querySelector(`#conv-groups .conv-row[data-conversation-id="${lastId}"]`) : null;
            if (row) row.focus({ preventScroll: true });
        }

        /* ── Workspace header / rail identity ─────────────────────────── */

        function renderWorkspaceHeader() {
            const conv = currentConversation();
            if (!conv) return;
            const name = conv.customer_name || 'Anonymous visitor';
            document.getElementById('conv-transcript-heading').textContent = name;
            document.getElementById('conv-transcript-sub').textContent =
                `${channelLabel(conv.source_channel)} - ${conv.bot_name || 'Unknown bot'}`;
            document.getElementById('conv-escalated-pill').hidden = !state.escalationsByConv.has(conv.id);
            document.getElementById('conv-mobile-summary').textContent =
                `${name}. ${channelLabel(conv.source_channel)}, ${conv.bot_name || 'Unknown bot'}.`;
        }

        /* ── Lead rail ─────────────────────────────────────────────────── */

        function ownerFieldHtml() {
            if (state.ownerLocked) {
                return `<div class="kw-locked">
                    <span class="kw-locked-icon" aria-hidden="true">${icon('lock')}</span>
                    <div>
                        <h4>Assigning an owner needs a plan upgrade</h4>
                        <p>Your current plan does not include lead assignment. Upgrade to give this conversation an owner.</p>
                    </div>
                </div>`;
            }
            const options = ['<option value="">Unassigned</option>']
                .concat(state.members.map(m => `<option value="${m.id}">${escapeHtml(m.name || m.email || ('Member ' + m.id))}</option>`));
            return `<label class="kw-label" for="conv-owner">Owner</label>
                <select class="kw-select" id="conv-owner">${options.join('')}</select>
                <span class="kw-help" role="status" aria-live="polite" id="conv-owner-status"></span>`;
        }

        function renderLeadRailFromState() {
            const conv = currentConversation();
            if (!conv) return;
            const lead = state.leadsByConv.get(conv.id) || null;
            const name = conv.customer_name || 'Anonymous visitor';

            /* A save on one field (say, Stage) re-renders the whole rail, which
               would otherwise stomp an unsaved draft the reader is mid-typing
               into Notes. Capture that draft here and restore it below instead
               of the freshly-fetched server value. */
            const notesBefore = document.getElementById('conv-notes');
            const hasPendingNotes = notesBefore && notesBefore.value !== notesBefore.dataset.savedValue;
            const pendingNotesValue = hasPendingNotes ? notesBefore.value : null;
            const notesHadFocus = document.activeElement === notesBefore;

            document.getElementById('conv-rail-avatar').textContent = initials(name === 'Anonymous visitor' ? '?' : name);
            document.getElementById('conv-rail-name').textContent = name;
            document.getElementById('conv-rail-badges').innerHTML =
                `<span class="kw-badge kw-badge-support">${escapeHtml(conv.bot_name || 'Unknown bot')}</span>
                 <span class="kw-badge">${escapeHtml(channelLabel(conv.source_channel))}</span>`;

            document.getElementById('conv-field-phone').textContent = maskPhone(lead ? lead.customer_phone : conv.customer_phone) || 'Not provided';
            document.getElementById('conv-field-bot').textContent = conv.bot_name || 'Unknown bot';
            document.getElementById('conv-field-channel').textContent = channelLabel(conv.source_channel);
            const leadType = lead ? lead.lead_type : '';
            document.getElementById('conv-field-type').textContent = LEAD_TYPE_LABEL[leadType] || 'Not yet flagged';
            document.getElementById('conv-field-summary').textContent = (lead && lead.summary) ? lead.summary : 'No summary yet.';

            const stage = normalizeStage(lead ? lead.status : 'new');
            document.querySelectorAll('#conv-stage-group [role="radio"]').forEach(btn => {
                const checked = btn.dataset.stage === stage;
                btn.setAttribute('aria-checked', String(checked));
                btn.tabIndex = checked ? 0 : -1;
            });

            const priority = lead ? String(lead.priority || 'medium').toLowerCase() : 'medium';
            document.querySelectorAll('#conv-priority-group [role="radio"]').forEach(btn => {
                const checked = btn.dataset.priority === priority;
                btn.setAttribute('aria-checked', String(checked));
                btn.tabIndex = checked ? 0 : -1;
            });

            document.getElementById('conv-followup').value = (lead && lead.follow_up_date) ? lead.follow_up_date : '';

            document.getElementById('conv-owner-field').innerHTML = ownerFieldHtml();
            if (!state.ownerLocked) {
                const ownerSelect = document.getElementById('conv-owner');
                const assigned = lead ? String(lead.assigned_to || '') : '';
                if (assigned && !findMemberById(assigned)) {
                    const opt = document.createElement('option');
                    opt.value = assigned;
                    opt.textContent = `${assigned} (not on this team anymore)`;
                    ownerSelect.appendChild(opt);
                }
                ownerSelect.value = assigned;
            }

            const notesEl = document.getElementById('conv-notes');
            notesEl.value = (lead && lead.notes) ? lead.notes : '';
            notesEl.dataset.savedValue = notesEl.value;
            if (pendingNotesValue !== null) {
                notesEl.value = pendingNotesValue;
                if (notesHadFocus) notesEl.focus();
            }
        }

        /* ── Saving lead fields ────────────────────────────────────────── */

        async function ensureLeadOrPatch(conv, lead, fields) {
            if (lead && lead.id) {
                const body = Object.assign({ chatbot_id: conv.chatbot_id }, fields);
                return getJson(`/api/crm/leads/${lead.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
            }
            const body = Object.assign({ chatbot_id: conv.chatbot_id, conversation_id: conv.id }, fields);
            return getJson('/api/crm/leads/upsert', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
        }

        function flashStatus(el, message, ms) {
            el.textContent = message;
            if (ms) setTimeout(() => { if (el.textContent === message) el.textContent = ''; }, ms);
        }

        /* Never shows "Saved" until the server actually confirms it, and never
           changes the visible control ahead of that confirmation either -- so
           a failed save (the 5-stage vocabulary is not migrated on the server
           yet for some plans) has nothing to revert. The control is simply
           still showing the last confirmed value, with the real server
           message next to it. */
        async function saveLeadField(fields, statusEl, opts) {
            const conv = currentConversation();
            if (!conv) return null;
            const lead = state.leadsByConv.get(conv.id) || null;
            flashStatus(statusEl, 'Saving...', 0);

            const result = await ensureLeadOrPatch(conv, lead, fields);

            if (!result.ok) {
                if (result.status === 403 && 'assigned_to' in fields && result.body && result.body.code) {
                    state.ownerLocked = true;
                    renderLeadRailFromState();
                    return result;
                }
                flashStatus(statusEl, (result.body && result.body.message) || 'Could not save. Try again.', 6000);
                if (opts && opts.onError) opts.onError();
                return result;
            }

            const saved = result.body.data.lead;
            state.leadsByConv.set(conv.id, Object.assign({ chatbot_id: conv.chatbot_id }, saved));
            flashStatus(statusEl, 'Saved.', 4000);
            renderLeadRailFromState();
            renderPipeline();
            renderMiniRail();
            return result;
        }

        /* ── Transcript ────────────────────────────────────────────────── */

        function messageSignalMap(actions) {
            const map = new Map();
            (actions || []).forEach(action => {
                if (action.message_id === null || action.message_id === undefined) return;
                const signal = buildSignal(action);
                if (signal) map.set(action.message_id, signal);
            });
            return map;
        }

        function buildBubble(message, signalMap) {
            const el = document.createElement('div');
            el.className = 'conv-bubble';
            el.dataset.sender = message.sender_type === 'customer' ? 'customer' : 'bot';
            el.dataset.messageId = String(message.id);
            el.dataset.searchText = String(message.message_text || '').toLowerCase();
            const signal = signalMap.get(message.id);
            const delivery = message.sender_type === 'customer' ? '' : deliveryStatusLabel(message);
            const body = message.sender_type === 'bot'
                ? splitButtonsTag(message.message_text || '')
                : { text: message.message_text || '', labels: [] };
            const buttons = body.labels.length
                ? `<ul data-part="buttons" aria-label="Buttons offered">${body.labels.map(label => `<li>${escapeHtml(label)}</li>`).join('')}</ul>`
                : '';
            el.innerHTML = `
                ${message.sender_type === 'human' ? '<strong data-part="sender">Support team</strong>' : ''}
                <span data-part="text">${escapeHtml(body.text)}</span>
                ${buttons}
                <time data-part="meta" datetime="${escapeHtml(message.created_at || '')}">${escapeHtml(formatClockTime(message.created_at))}</time>
                ${delivery ? `<span data-part="delivery">${escapeHtml(delivery)}</span>` : ''}
                ${signal ? `<p data-part="signal" data-confidence="${escapeHtml(signal.level || '')}">${escapeHtml(signal.text)}</p>` : ''}
            `;
            return el;
        }

        function deliveryStatusLabel(message) {
            const status = String(message.delivery_status || '').toLowerCase();
            if (message.sender_type === 'human' && currentConversation()?.source_channel === 'web' && status === 'sent') return 'Saved';
            const retries = Number(message.retry_count || 0);
            if (status === 'failed') return 'Failed to send - Auto retrying';
            if (status === 'retrying') return 'Retrying now...';
            if (status === 'permanent_failed') return 'Failed permanently';
            if (status === 'sent' && retries > 0) return 'Sent after retry';
            return '';
        }

        function renderTranscriptMessages() {
            const container = document.getElementById('conv-transcript');
            const query = state.transcriptSearch;
            const signalMap = state.lastIntentMap || new Map();
            container.replaceChildren();
            let matches = 0;
            state.transcriptMessages.forEach(message => {
                const bubble = buildBubble(message, signalMap);
                const matched = !query || bubble.dataset.searchText.includes(query);
                bubble.hidden = !matched;
                if (matched) matches += 1;
                container.appendChild(bubble);
            });
            document.getElementById('conv-message-search-count').textContent = query
                ? `${matches} result${matches === 1 ? '' : 's'}`
                : '';
        }

        function isTranscriptNearBottom(container) {
            return container.scrollHeight - container.scrollTop - container.clientHeight < 80;
        }

        async function loadTranscript(conv) {
            const result = await getJson(`/api/conversations/${conv.id}/messages?chatbot_id=${conv.chatbot_id}`);
            const container = document.getElementById('conv-transcript');
            if (!result.ok) {
                container.innerHTML = '<p class="kw-help">We could not load this transcript. Try again in a minute.</p>';
                return;
            }
            const messages = result.body.data || [];
            state.transcriptMessages = messages;
            state.lastMessageCount = messages.length;
            renderTranscriptMessages();
            container.scrollTop = container.scrollHeight;
        }

        async function refreshOpenTranscript(isPoll) {
            const conv = currentConversation();
            if (!conv) return;
            const result = await getJson(`/api/conversations/${conv.id}/messages?chatbot_id=${conv.chatbot_id}`);
            if (!result.ok) return;
            const messages = result.body.data || [];
            if (messages.length <= state.lastMessageCount) return;

            const container = document.getElementById('conv-transcript');
            const wasNearBottom = isTranscriptNearBottom(container);
            state.transcriptMessages = messages;
            renderTranscriptMessages();
            state.lastMessageCount = messages.length;
            if (wasNearBottom) container.scrollTop = container.scrollHeight;
        }

        async function loadIntents(conv) {
            const result = await getJson(`/api/conversations/${conv.id}/intents?chatbot_id=${conv.chatbot_id}`);
            if (!result.ok) return;
            const actions = result.body.data || [];
            state.lastIntentMap = messageSignalMap(actions);

            // Re-annotate already-rendered bubbles now that intents arrived.
            document.querySelectorAll('#conv-transcript .conv-bubble').forEach(bubbleEl => {
                const id = Number(bubbleEl.dataset.messageId);
                const signal = state.lastIntentMap.get(id);
                const existing = bubbleEl.querySelector('[data-part="signal"]');
                if (existing) existing.remove();
                if (signal) {
                    const p = document.createElement('p');
                    p.dataset.part = 'signal';
                    p.dataset.confidence = signal.level || '';
                    p.textContent = signal.text;
                    bubbleEl.appendChild(p);
                }
            });

            // Opportunistic cache for the pipeline/mini-row chip: the latest
            // actionable signal for this conversation, remembered only
            // because the reader opened it -- never fetched proactively for
            // rows that were never opened.
            let latest = null;
            actions.forEach(action => { const s = buildSignal(action); if (s) latest = s; });
            if (latest) state.intentsCache.set(conv.id, latest);
            else state.intentsCache.delete(conv.id);
            renderPipeline();
            renderMiniRail();
        }

        /* ── Compose bar ───────────────────────────────────────────────── */

        /* Safe to call on every poll tick: only toggles which elements are
           visible, never touches the textarea value a reader may be
           mid-typing. */
        function syncComposebarVisibility() {
            const conv = currentConversation();
            if (!conv) return;
            const canReply = ['whatsapp', 'wasender', 'whatchimp', 'telegram'].includes(conv.source_channel)
                || (conv.source_channel === 'web' && /^web_[0-9a-zA-Z_-]{16,64}$/.test(conv.platform_user_id || ''));
            document.getElementById('conv-web-notice').hidden = canReply;
            document.getElementById('conv-reply-row').hidden = !canReply;
            document.getElementById('conv-resolve-btn').hidden = !state.escalationsByConv.has(conv.id);
        }

        /* Full reset -- only called when a (possibly different) conversation
           is opened, where clearing the reply box is correct, not data loss. */
        function renderComposebar() {
            syncComposebarVisibility();
            document.getElementById('conv-reply-text').value = '';
            document.getElementById('conv-compose-status').textContent = '';
        }

        function endHeldEdit() {
            if (state.editingHeldId === null) return;
            state.editingHeldId = null;
            document.getElementById('conv-reply-text').value = '';
            document.getElementById('conv-reply-send').textContent = 'Send';
            document.getElementById('conv-reply-send').hidden = false;
            document.getElementById('conv-held-cancel').hidden = true;
        }

        function resetHeldPanel() {
            state.heldRequest++;
            endHeldEdit();
            const list = document.getElementById('conv-held-list');
            list.replaceChildren();
            list.disabled = false;
            document.getElementById('conv-reply-text').readOnly = false;
            document.getElementById('conv-held-cancel').disabled = false;
            document.getElementById('conv-held-panel').hidden = true;
            document.getElementById('conv-held-load-error').textContent = '';
        }

        function heldReplyItem(conv, row) {
            const item = document.createElement('article');
            item.dataset.heldId = String(row.id);
            item.dataset.deliveryPending = String(row.delivery_pending === true);
            const reason = document.createElement('strong');
            reason.textContent = row.reason_label;
            const draft = document.createElement('p');
            draft.setAttribute('data-platform-sensitive', '');
            draft.setAttribute('data-sentry-mask', '');
            draft.textContent = row.draft;
            item.append(reason, draft);
            if (row.delivery_pending) {
                const notice = document.createElement('p');
                notice.textContent = 'Delivery is awaiting confirmation. Check the conversation before sending again.';
                item.appendChild(notice);
                return item;
            }
            const actions = document.createElement('div');
            actions.dataset.part = 'actions';
            for (const [action, label] of [['send', 'Send as is'], ['edit', 'Edit before sending'], ['discard', 'Discard']]) {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'kw-btn cr-press';
                button.textContent = label;
                button.disabled = action !== 'discard' && document.getElementById('conv-reply-row').hidden;
                button.addEventListener('click', () => {
                    if (action !== 'edit') return resolveHeldReply(conv, row.id, action);
                    state.editingHeldId = row.id;
                    const composer = document.getElementById('conv-reply-text');
                    composer.value = row.draft;
                    document.getElementById('conv-reply-send').textContent = 'Send edited reply';
                    document.getElementById('conv-reply-send').hidden = false;
                    document.getElementById('conv-held-cancel').hidden = false;
                    composer.focus();
                });
                actions.appendChild(button);
            }
            item.appendChild(actions);
            return item;
        }

        async function loadHeldReplies(conv) {
            const request = ++state.heldRequest;
            let result;
            try {
                result = await getJson(`/api/conversations/${conv.id}/held-replies`);
            } catch (_) {
                result = { ok: false };
            }
            if (state.heldRequest !== request || state.selectedConversationId !== conv.id) return;
            const loadError = document.getElementById('conv-held-load-error');
            if (!result.ok) {
                if ([401, 403, 404].includes(result.status)) resetHeldPanel();
                else if (!loadError.textContent) loadError.textContent = 'Could not load held replies.';
                return;
            }
            if (loadError.textContent) loadError.textContent = '';
            const rows = result.body.held_replies || [];
            const list = document.getElementById('conv-held-list');
            // Preserve focus across polls unless a draft was added, removed or claimed by staff.
            if (list.children.length === rows.length &&
                rows.every((row, i) => list.children[i].dataset.heldId === String(row.id) &&
                    list.children[i].dataset.deliveryPending === String(row.delivery_pending === true))) return;
            if (state.editingHeldId !== null) {
                const edited = rows.find(row => row.id === state.editingHeldId);
                if (edited) document.getElementById('conv-reply-send').hidden = edited.delivery_pending === true;
                else endHeldEdit();
            }
            list.replaceChildren(...rows.map(row => heldReplyItem(conv, row)));
            document.getElementById('conv-held-panel').hidden = rows.length === 0;
        }

        async function resolveHeldReply(conv, id, action, text) {
            const list = document.getElementById('conv-held-list');
            if (list.disabled || state.selectedConversationId !== conv.id) return;
            list.disabled = true;
            const status = document.getElementById('conv-compose-status');
            const composer = document.getElementById('conv-reply-text');
            const cancel = document.getElementById('conv-held-cancel');
            const unconfirmed = 'The result is unconfirmed. Check the conversation before taking another action.';
            composer.readOnly = action === 'edit';
            cancel.disabled = true;
            try {
                const result = await getJson(`/api/conversations/${conv.id}/held-replies/${id}/resolve`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(action === 'edit' ? { action, text } : { action })
                });
                if (state.selectedConversationId !== conv.id) return;
                if (result.ok) {
                    if (state.editingHeldId === id) endHeldEdit();
                    list.querySelector(`[data-held-id="${id}"]`)?.remove();
                    document.getElementById('conv-held-panel').hidden = !list.children.length;
                    status.textContent = action === 'discard' ? 'Held reply discarded.' : 'Held reply sent.';
                } else {
                    status.textContent = result.status === 409 || result.status >= 500
                        ? unconfirmed : 'Could not resolve the held reply. Check the draft and try again.';
                }
            } catch (_) {
                if (state.selectedConversationId === conv.id) status.textContent = unconfirmed;
            } finally {
                if (state.selectedConversationId === conv.id) {
                    await Promise.allSettled([loadHeldReplies(conv), refreshOpenTranscript(false)]);
                }
                if (state.selectedConversationId === conv.id) {
                    list.disabled = false;
                    composer.readOnly = false;
                    cancel.disabled = false;
                }
            }
        }

        document.getElementById('conv-held-cancel').addEventListener('click', () => {
            endHeldEdit();
            document.getElementById('conv-reply-text').focus();
        });

        async function sendReply() {
            const conv = currentConversation();
            if (!conv) return;
            const textarea = document.getElementById('conv-reply-text');
            const draft = textarea.value;
            const text = draft.trim();
            if (!text) return;
            const sendBtn = document.getElementById('conv-reply-send');
            if (sendBtn.disabled || sendBtn.hidden || document.getElementById('conv-reply-row').hidden) return;
            if (state.editingHeldId !== null) return resolveHeldReply(conv, state.editingHeldId, 'edit', text);
            const statusEl = document.getElementById('conv-compose-status');
            sendBtn.disabled = true;
            flashStatus(statusEl, 'Sending...', 0);

            let result;
            try {
                result = await getJson(`/api/conversations/${conv.id}/agent-reply`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ chatbot_id: conv.chatbot_id, text })
                });
            } catch (_) {
                if (state.selectedConversationId === conv.id) flashStatus(statusEl, 'Could not send. Your draft is still here. Try again.', 6000);
                return;
            } finally {
                sendBtn.disabled = false;
            }
            if (state.selectedConversationId !== conv.id) return;
            if (result.ok) {
                if (textarea.value === draft) textarea.value = '';
                const notice = conv.source_channel === 'web'
                    ? 'Reply saved. The visitor will receive it in this chat.' : 'Sent.';
                flashStatus(statusEl, notice, conv.source_channel === 'web' ? 8000 : 4000);
                announce('workspace', conv.source_channel === 'web' ? notice : 'Reply sent.');
                await refreshOpenTranscript(false);
            } else {
                flashStatus(statusEl, (result.body && result.body.message) || 'Could not send. Try again.', 6000);
            }
        }

        async function resolveEscalation() {
            const conv = currentConversation();
            if (!conv) return;
            const escalation = state.escalationsByConv.get(conv.id);
            if (!escalation) return;
            const btn = document.getElementById('conv-resolve-btn');
            btn.disabled = true;
            try {
            const result = await getJson(`/api/agent/escalations/${escalation.id}/resolve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chatbot_id: conv.chatbot_id })
            });

            if (result.ok) {
                const pending = await getJson(`/api/agent/escalations?chatbot_id=${conv.chatbot_id}&conversation_id=${conv.id}`);
                if (!pending.ok) {
                    const notice = 'Request resolved, but remaining handoffs could not be checked. Try again to refresh.';
                    announce('workspace', notice);
                    flashStatus(document.getElementById('conv-compose-status'), notice, 8000);
                    return;
                }
                const remaining = (pending.body.data || []).find(action => action.conversation_id === conv.id);
                if (remaining) state.escalationsByConv.set(conv.id, remaining);
                else state.escalationsByConv.delete(conv.id);
                let notice = remaining || result.body.data && result.body.data.ai_resumed === false
                    ? 'Request resolved. Another handoff still needs attention; AI replies remain paused.'
                    : 'Marked resolved. AI replies resume with the next customer message. This does not change the CRM stage.';
                if (result.body.data && result.body.data.notification_status === 'failed') {
                    const channelName = { telegram: 'Telegram', whatsapp: 'WhatsApp Business', wasender: 'WASender', whatchimp: 'WhatChimp' }[conv.source_channel] || 'the original channel';
                    notice += ` The end-of-service message could not be delivered to ${channelName}.`;
                }
                announce('workspace', notice);
                renderWorkspaceHeader();
                syncComposebarVisibility();
                renderPipeline();
                renderMiniRail();
                flashStatus(document.getElementById('conv-compose-status'), notice, 8000);
            } else {
                announce('workspace', 'Could not resolve. Try again.');
            }
            } catch (_) {
                const notice = 'Could not confirm the handoff status. Try again to refresh.';
                announce('workspace', notice);
                flashStatus(document.getElementById('conv-compose-status'), notice, 8000);
            } finally {
                btn.disabled = false;
            }
        }

        /* ── Roving tabindex + open/close wiring ──────────────────────── */

        function rowsInSameContainer(row) {
            return Array.from(row.parentElement.children).filter(el => el.matches('.conv-row, .conv-mini-row'));
        }

        function focusRow(items, idx) {
            items.forEach((el, i) => { el.tabIndex = i === idx ? 0 : -1; });
            items[idx].focus();
        }

        document.addEventListener('keydown', event => {
            const row = event.target.closest('.conv-row, .conv-mini-row');
            if (row) {
                const items = rowsInSameContainer(row);
                const idx = items.indexOf(row);
                if (event.key === 'ArrowDown') { event.preventDefault(); focusRow(items, Math.min(idx + 1, items.length - 1)); return; }
                if (event.key === 'ArrowUp') { event.preventDefault(); focusRow(items, Math.max(idx - 1, 0)); return; }
                if (event.key === 'Home') { event.preventDefault(); focusRow(items, 0); return; }
                if (event.key === 'End') { event.preventDefault(); focusRow(items, items.length - 1); return; }
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); row.click(); return; }
                return;
            }

            const radio = event.target.closest('[role="radio"]');
            if (radio) {
                const group = Array.from(radio.parentElement.children).filter(el => el.getAttribute('role') === 'radio');
                const idx = group.indexOf(radio);
                if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
                    event.preventDefault();
                    const next = group[Math.min(idx + 1, group.length - 1)];
                    group.forEach(b => { b.tabIndex = -1; });
                    next.tabIndex = 0;
                    next.focus();
                } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
                    event.preventDefault();
                    const prev = group[Math.max(idx - 1, 0)];
                    group.forEach(b => { b.tabIndex = -1; });
                    prev.tabIndex = 0;
                    prev.focus();
                }
            }
        });

        document.addEventListener('click', async event => {
            const row = event.target.closest('.conv-row, .conv-mini-row');
            if (row && row.dataset.conversationId) {
                await openConversation(Number(row.dataset.conversationId));
                return;
            }

            if (event.target.closest('#conv-back-link')) {
                event.preventDefault();
                closeWorkspace();
                return;
            }

            if (event.target.closest('#conv-retry')) { await refresh(false); return; }
            if (event.target.closest('#conv-clear-filters')) { clearFilters(); return; }

            const filterChip = event.target.closest('[data-filter]');
            if (filterChip) {
                const key = filterChip.dataset.filter === 'awaiting' ? 'awaitingHuman' : 'overdue';
                state.filters[key] = !state.filters[key];
                filterChip.setAttribute('aria-pressed', String(state.filters[key]));
                renderPipeline();
                if (state.selectedConversationId) renderMiniRail();
                return;
            }

            const mobileTab = event.target.closest('#conv-mobile-segment [role="radio"]');
            if (mobileTab) {
                document.querySelectorAll('#conv-mobile-segment [role="radio"]').forEach(btn => {
                    const checked = btn === mobileTab;
                    btn.setAttribute('aria-checked', String(checked));
                    btn.tabIndex = checked ? 0 : -1;
                });
                document.getElementById('conv-workspace').dataset.mobileTab = mobileTab.dataset.tab;
                return;
            }

            const stageBtn = event.target.closest('#conv-stage-group [role="radio"]');
            if (stageBtn) {
                await saveLeadField({ status: stageBtn.dataset.stage }, document.getElementById('conv-stage-status'));
                return;
            }

            const priorityBtn = event.target.closest('#conv-priority-group [role="radio"]');
            if (priorityBtn) {
                await saveLeadField({ priority: priorityBtn.dataset.priority }, document.getElementById('conv-priority-status'));
                return;
            }

            if (event.target.closest('#conv-notes-save')) {
                const notesEl = document.getElementById('conv-notes');
                await saveLeadField({ notes: notesEl.value }, document.getElementById('conv-notes-status'));
                return;
            }

            if (event.target.closest('#conv-reply-send')) { await sendReply(); return; }
            if (event.target.closest('#conv-resolve-btn')) { await resolveEscalation(); return; }
        });

        document.addEventListener('change', async event => {
            if (event.target.id === 'conv-followup') {
                const value = event.target.value || null;
                await saveLeadField({ follow_up_date: value }, document.getElementById('conv-followup-status'));
                return;
            }
            if (event.target.id === 'conv-owner') {
                await saveLeadField({ assigned_to: event.target.value || null }, document.getElementById('conv-owner-status'), {
                    onError: () => { event.target.value = event.target.dataset.previousValue || ''; }
                });
                return;
            }
            if (event.target.id === 'conv-filter-channel') { state.filters.channel = event.target.value; renderPipeline(); if (state.selectedConversationId) renderMiniRail(); return; }
        });

        document.addEventListener('focusin', event => {
            if (event.target.id === 'conv-owner') event.target.dataset.previousValue = event.target.value;
        });

        document.addEventListener('focusout', async event => {
            if (event.target.id !== 'conv-notes') return;
            const notesEl = event.target;
            if (notesEl.value === notesEl.dataset.savedValue) return;
            await saveLeadField({ notes: notesEl.value }, document.getElementById('conv-notes-status'));
        });

        let searchDebounce = null;
        document.getElementById('conv-search').addEventListener('input', event => {
            clearTimeout(searchDebounce);
            const value = event.target.value;
            searchDebounce = setTimeout(() => {
                state.filters.search = value.trim().toLowerCase();
                renderPipeline();
                if (state.selectedConversationId) renderMiniRail();
            }, 150);
        });

        function clearFilters() {
            state.filters = { search: '', channel: '', awaitingHuman: false, overdue: false };
            document.getElementById('conv-search').value = '';
            document.getElementById('conv-filter-channel').value = '';
            document.querySelectorAll('#conv-toolbar [data-filter]').forEach(chip => chip.setAttribute('aria-pressed', 'false'));
            renderPipeline();
            if (state.selectedConversationId) renderMiniRail();
        }

        document.getElementById('conv-reply-text').addEventListener('keydown', event => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                sendReply();
            }
        });

        function transcriptText() {
            return state.transcriptMessages.map(message => {
                const sender = message.sender_type === 'customer' ? 'Customer' : message.sender_type === 'human' ? 'Support team' : 'Bot';
                return `[${formatClockTime(message.created_at)}] ${sender}: ${message.message_text || ''}`;
            }).join('\n');
        }

        async function copyText(value, successMessage) {
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(value);
                } else {
                    const textarea = document.createElement('textarea');
                    textarea.value = value;
                    textarea.setAttribute('readonly', '');
                    textarea.style.position = 'fixed';
                    textarea.style.left = '-9999px';
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    textarea.remove();
                }
                flashStatus(document.getElementById('conv-compose-status'), successMessage, 3000);
            } catch (error) {
                flashStatus(document.getElementById('conv-compose-status'), 'Copy failed.', 3000);
            }
        }

        function conversationLink() {
            const conv = currentConversation();
            if (!conv) return window.location.href;
            const url = new URL(window.location.href);
            url.searchParams.set('conversation_id', String(conv.id));
            if (conv.chatbot_id) url.searchParams.set('bot_id', String(conv.chatbot_id));
            return url.toString();
        }

        function downloadTranscript() {
            const blob = new Blob([transcriptText()], { type: 'text/plain;charset=utf-8' });
            const href = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = href;
            link.download = `conversation-${currentConversation()?.id || 'transcript'}.txt`;
            link.click();
            URL.revokeObjectURL(href);
        }

        document.getElementById('conv-copy-link').addEventListener('click', () => copyText(conversationLink(), 'Link copied.'));
        document.getElementById('conv-copy-transcript').addEventListener('click', () => copyText(transcriptText(), 'Transcript copied.'));
        document.getElementById('conv-download-transcript').addEventListener('click', downloadTranscript);
        document.getElementById('conv-message-search').addEventListener('input', event => {
            state.transcriptSearch = event.target.value.trim().toLowerCase();
            renderTranscriptMessages();
        });

        /* ── Boot ──────────────────────────────────────────────────────── */

        (async function boot() {
            if (!BOT_ID) return; // already on the way to My bots

            // The chip has to show the filter that is already applied, or the
            // agent sees a short list with no visible reason for it and clears
            // a filter they never knowingly set.
            if (ARRIVED_AWAITING) {
                const awaitingChip = document.getElementById('conv-chip-awaiting');
                if (awaitingChip) awaitingChip.setAttribute('aria-pressed', 'true');
            }

            await refresh(false);
            startPolling();

            const deepLinkId = new URLSearchParams(window.location.search).get('conversation_id');
            if (deepLinkId && state.conversations.some(c => String(c.id) === String(deepLinkId))) {
                await openConversation(Number(deepLinkId));
            }
        })();
