/* broadcast.js - campaign list, three-step composer, and dispatch console.
 *
 * Replaces the React-via-CDN page that compiled JSX in the browser with
 * Babel standalone. Nothing here needs a framework: the page shows one
 * screen at a time and renders from a single `state` object, the same way
 * conversations.html does.
 *
 * The shape of the flow follows the one irreversible thing this page can
 * do. A broadcast cannot be recalled, so the composer never lets you send
 * from the screen you typed on: step 3 shows the real message and the real
 * count, asks you to type the campaign name, and even then holds the
 * request for ten seconds behind an Undo.
 */

(function () {
    "use strict";

    /* ── Constants ─────────────────────────────────────────────────── */

    // Matches time.sleep(3) in process_broadcast_dispatch. Used only to
    // estimate time remaining; if the worker's pacing changes, this makes
    // the estimate wrong, not the send.
    var SEND_INTERVAL_MS = 3000;
    var UNDO_SECONDS = 10;
    var POLL_MS = 2000;
    var MAX_BUTTONS = 3;
    var WELCOME_SENTINEL = "__use_bot_welcome_flow__";
    var PHONE_RE = /^\+?[1-9]\d{6,14}$/;
    var BUTTON_RE = /\[BUTTON:\s*(.*?)\]/gi;

    // One request per campaign is enough for the handful a company runs.
    // ponytail: N+1 against /progress, capped so a long list cannot open
    // fifty sockets at once. A batched counts endpoint is the upgrade if
    // anyone ever accumulates hundreds of campaigns.
    var PROGRESS_FETCH_LIMIT = 30;
    var PROGRESS_CONCURRENCY = 6;

    var STATUS_COPY = {
        draft: { label: "Draft", pill: "kw-pill-review" },
        sending: { label: "Sending", pill: "kw-pill-review" },
        cancelling: { label: "Stopping", pill: "kw-pill-review" },
        completed: { label: "Sent", pill: "kw-pill-ready" },
        failed: { label: "Failed", pill: "kw-pill-off" },
        cancelled: { label: "Cancelled", pill: "kw-pill-off" }
    };

    var CHANNEL_COPY = {
        whatsapp: "WhatsApp (official)",
        wasender: "WasenderAPI"
    };

    /* ── State ─────────────────────────────────────────────────────── */

    var botId = resolveBotId();

    var state = {
        campaigns: [],
        progress: {},          // campaign id -> progress payload
        media: [],
        logs: [],
        crmContacts: [],
        step: 1,
        draftId: null,         // set when the composer is editing a saved draft
        source: "csv",
        recipients: [],        // [{ phone, name }]
        channel: "whatsapp",
        bodyMode: "custom",
        consoleId: null,
        pollTimer: null,
        countdownTimer: null,
        confirmAction: null,
        busy: false
    };

    /* ── Tiny helpers ──────────────────────────────────────────────── */

    function $(id) {
        return document.getElementById(id);
    }

    function esc(value) {
        return String(value === null || value === undefined ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function show(el, visible) {
        if (el) el.hidden = !visible;
    }

    function announce(message, urgent) {
        var el = $(urgent ? "bc-console-announce" : "bc-announce");
        if (el) el.textContent = message;
    }

    function plural(count, one, many) {
        return count === 1 ? one : many;
    }

    function formatDate(iso) {
        if (!iso) return "-";
        var date = new Date(iso);
        return isNaN(date.getTime()) ? "-" : date.toLocaleString();
    }

    function formatDuration(ms) {
        if (!isFinite(ms) || ms <= 0) return "less than a minute";
        var minutes = Math.ceil(ms / 60000);
        if (minutes < 60) return minutes + " " + plural(minutes, "minute", "minutes");
        var hours = Math.floor(minutes / 60);
        return hours + "h " + (minutes % 60) + "m";
    }

    /* The fetch itself is inside the try, not just the json() parse. It used
       to sit outside, so an offline/DNS/connection-reset throw escaped as an
       unhandled rejection: the caller never received a result, never cleared
       its skeleton, and the page spun forever with no error and no way back
       except a reload. status 0 means "never reached the server", which is
       what the callers already render as a retryable failure. */
    async function api(url, options) {
        var response;
        try {
            response = await authenticatedFetch(url, options);
        } catch (e) {
            return { ok: false, status: 0, body: {}, offline: true };
        }
        var body = {};
        try {
            body = await response.json();
        } catch (e) {
            body = {};
        }
        return { ok: response.ok && body.status === "success", status: response.status, body: body };
    }

    function withBot(path) {
        return path + (path.indexOf("?") === -1 ? "?" : "&") + "chatbot_id=" + encodeURIComponent(botId);
    }

    function jsonRequest(method, payload) {
        return {
            method: method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        };
    }

    /* ── Banners ───────────────────────────────────────────────────── */

    function pageError(message) {
        $("bc-error-text").textContent = message;
        show($("bc-error"), true);
    }

    function clearPageError() {
        show($("bc-error"), false);
    }

    function notice(message) {
        $("bc-notice-text").textContent = message;
        show($("bc-notice"), true);
        announce(message);
    }

    function clearNotice() {
        show($("bc-notice"), false);
    }

    function wizardError(message) {
        $("bc-wizard-error-text").textContent = message || "";
        show($("bc-wizard-error"), !!message);
        if (message) announce(message);
    }

    /* ── Screens ───────────────────────────────────────────────────── */

    function showScreen(name) {
        show($("bc-list"), name === "list");
        show($("bc-wizard"), name === "wizard");
        show($("bc-console"), name === "console");
    }

    /* ══════════════════════════ CAMPAIGN LIST ══════════════════════════ */

    async function loadCampaigns() {
        clearPageError();
        show($("bc-list-loading"), true);
        show($("bc-table-wrap"), false);
        show($("bc-empty"), false);

        var result = await api(withBot("/api/broadcast/campaigns"));
        show($("bc-list-loading"), false);

        if (!result.ok) {
            pageError(result.body.message || "We could not load your campaigns.");
            return;
        }

        state.campaigns = result.body.campaigns || [];
        await loadProgressForCampaigns(state.campaigns.slice(0, PROGRESS_FETCH_LIMIT));
        renderStats();
        renderTable();
    }

    async function loadProgressForCampaigns(campaigns) {
        var queue = campaigns.slice();

        async function worker() {
            while (queue.length) {
                var campaign = queue.shift();
                var result = await api(withBot("/api/broadcast/campaign/" + campaign.id + "/progress"));
                if (result.ok) state.progress[campaign.id] = result.body;
            }
        }

        var workers = [];
        for (var i = 0; i < Math.min(PROGRESS_CONCURRENCY, queue.length); i++) {
            workers.push(worker());
        }
        await Promise.all(workers);
    }

    function renderStats() {
        var delivered = 0;
        var active = 0;
        state.campaigns.forEach(function (campaign) {
            var progress = state.progress[campaign.id];
            if (progress) delivered += progress.sent || 0;
            if (campaign.status === "sending" || campaign.status === "cancelling") active += 1;
        });
        $("bc-stat-total").textContent = state.campaigns.length;
        $("bc-stat-done").textContent = delivered;
        $("bc-stat-active").textContent = active;
    }

    function visibleCampaigns() {
        var term = ($("bc-search").value || "").trim().toLowerCase();
        var status = $("bc-filter-status").value;
        return state.campaigns.filter(function (campaign) {
            if (status && campaign.status !== status) return false;
            if (term && String(campaign.name || "").toLowerCase().indexOf(term) === -1) return false;
            return true;
        });
    }

    function statusPill(status) {
        var copy = STATUS_COPY[status] || { label: status, pill: "" };
        return '<span class="kw-pill ' + copy.pill + '">' + esc(copy.label) + "</span>";
    }

    function rowActions(campaign) {
        var buttons = [];
        var inFlight = campaign.status === "sending" || campaign.status === "cancelling";

        if (campaign.status === "draft") {
            buttons.push('<button type="button" class="kw-action" data-act="edit" data-id="' + esc(campaign.id) + '">Edit</button>');
            buttons.push('<button type="button" class="kw-action" data-act="send" data-id="' + esc(campaign.id) + '">Review and send</button>');
        }
        if (inFlight) {
            buttons.push('<button type="button" class="kw-action" data-act="watch" data-id="' + esc(campaign.id) + '">Watch</button>');
        }
        buttons.push('<button type="button" class="kw-action" data-act="logs" data-id="' + esc(campaign.id) + '">Recipients</button>');
        if (!inFlight) {
            buttons.push('<button type="button" class="kw-action kw-action-danger" data-act="delete" data-id="' + esc(campaign.id) + '">Delete</button>');
        }
        return '<div class="kw-actions">' + buttons.join("") + "</div>";
    }

    function renderTable() {
        var rows = visibleCampaigns();
        var filtering = !!($("bc-search").value || $("bc-filter-status").value);

        if (!rows.length) {
            show($("bc-table-wrap"), false);
            show($("bc-empty"), true);
            $("bc-empty-title").textContent = filtering ? "Nothing matches" : "No campaigns yet";
            $("bc-empty-body").textContent = filtering
                ? "Try a different name, or clear the status filter."
                : "A campaign is one message sent to a list of people. Build your first one to get started.";
            show($("bc-empty-action"), !filtering);
            return;
        }

        show($("bc-empty"), false);
        show($("bc-table-wrap"), true);

        $("bc-table-body").innerHTML = rows.map(function (campaign) {
            var progress = state.progress[campaign.id];
            var recipients = "-";
            if (progress) {
                recipients = campaign.status === "draft"
                    ? String(progress.total)
                    : progress.sent + " / " + progress.total;
            }
            return "<tr>"
                + '<td data-col="name">' + esc(campaign.name) + "</td>"
                + "<td>" + esc(CHANNEL_COPY[campaign.channel_type] || campaign.channel_type) + "</td>"
                + '<td data-col="recipients">' + esc(recipients) + "</td>"
                + '<td data-col="created">' + esc(formatDate(campaign.created_at)) + "</td>"
                + "<td>" + statusPill(campaign.status) + "</td>"
                + '<td data-col="actions">' + rowActions(campaign) + "</td>"
                + "</tr>";
        }).join("");
    }

    function campaignById(id) {
        return state.campaigns.filter(function (c) { return String(c.id) === String(id); })[0] || null;
    }

    /* ══════════════════════════ RECIPIENTS ══════════════════════════ */

    function normalizePhone(raw) {
        return String(raw || "").replace(/[\s\-().]/g, "");
    }

    function addRecipients(list) {
        var seen = {};
        state.recipients.forEach(function (r) { seen[r.phone] = true; });
        var added = 0;
        list.forEach(function (entry) {
            if (seen[entry.phone]) return;
            seen[entry.phone] = true;
            state.recipients.push(entry);
            added += 1;
        });
        return added;
    }

    function renderRecipients(note) {
        var count = state.recipients.length;
        $("bc-audience-counter").textContent = count;
        show($("bc-recipients-field"), count > 0);

        $("bc-recipients").innerHTML = state.recipients.map(function (r, index) {
            return '<div class="bc-recipient" role="listitem">'
                + '<span class="bc-recipient-phone">' + esc(r.phone) + "</span>"
                + '<span class="bc-recipient-name">' + esc(r.name || "") + "</span>"
                + '<button type="button" class="kw-action kw-action-danger" data-part="remove" data-index="'
                + index + '" aria-label="Remove ' + esc(r.phone) + '">Remove</button>'
                + "</div>";
        }).join("");

        $("bc-recipients-note").textContent = note
            || (count + " " + plural(count, "person", "people") + " on the list.");
        updateBottombar();
    }

    function parseCsv(text) {
        var lines = text.split(/\r?\n/);
        var list = [];
        var skipped = [];
        var headerRe = /phone|mobile|number|tel|recipient|contact/i;

        lines.forEach(function (line, index) {
            var trimmed = line.trim();
            if (!trimmed) return;

            var delimiter = trimmed.indexOf(";") !== -1 && trimmed.indexOf(",") === -1 ? ";" : ",";
            var parts = trimmed.split(delimiter).map(function (part) {
                return part.replace(/["']/g, "").trim();
            });

            var phone = normalizePhone(parts[0]);
            var name = parts[1] || "";

            // A first row only counts as a header if it does not itself parse
            // as a phone number: "contact" is a header, "+60123456789" is not,
            // and the old page dropped a real number whose name column said
            // "Contact".
            if (index === 0 && headerRe.test(parts[0] || "") && !PHONE_RE.test(phone)) return;

            if (PHONE_RE.test(phone)) {
                list.push({ phone: phone, name: name });
            } else if (parts[0]) {
                skipped.push('row ' + (index + 1) + ' ("' + parts[0] + '")');
            }
        });

        return { list: list, skipped: skipped };
    }

    function handleCsvFile(file) {
        if (!file) return;
        wizardError("");
        var reader = new FileReader();
        reader.onerror = function () {
            wizardError("We could not read that file. Save it as a plain CSV and try again.");
        };
        reader.onload = function (event) {
            var parsed = parseCsv(String(event.target.result || ""));
            var added = addRecipients(parsed.list);
            var note = "Added " + added + " " + plural(added, "number", "numbers") + " from " + file.name + ".";
            if (parsed.skipped.length) {
                note += " Skipped " + parsed.skipped.length + " that did not look like phone numbers: "
                    + parsed.skipped.slice(0, 3).join(", ")
                    + (parsed.skipped.length > 3 ? ", and more." : ".");
            }
            if (!added && !parsed.skipped.length) {
                wizardError("That file had no phone numbers in the first column.");
            }
            renderRecipients(note);
            announce(note);
        };
        reader.readAsText(file);
    }

    async function loadCrmContacts() {
        wizardError("");
        var button = $("bc-crm-load");
        button.disabled = true;
        button.textContent = "Loading...";

        var result = await api(withBot("/api/conversations"));

        button.disabled = false;
        button.textContent = "Load these contacts";

        if (!result.ok) {
            wizardError(result.body.message || "We could not reach your contacts.");
            return;
        }

        state.crmContacts = result.body.data || [];
        applyRecency();
    }

    function applyRecency() {
        var windowChoice = $("bc-crm-recency").value;
        var cutoff = null;
        if (windowChoice === "week") cutoff = Date.now() - 7 * 86400000;
        if (windowChoice === "month") cutoff = Date.now() - 30 * 86400000;

        var mapped = [];
        state.crmContacts.forEach(function (contact) {
            if (cutoff) {
                var updated = new Date(contact.updated_at).getTime();
                if (isNaN(updated) || updated < cutoff) return;
            }
            var phone = normalizePhone(contact.customer_phone);
            if (PHONE_RE.test(phone)) {
                mapped.push({ phone: phone, name: contact.customer_name || "" });
            }
        });

        var added = addRecipients(mapped);
        if (!added && !state.recipients.length) {
            wizardError("No contact matched that time window. Try widening it.");
            renderRecipients("");
            return;
        }
        renderRecipients("Added " + added + " " + plural(added, "contact", "contacts") + " from your conversations.");
    }

    function addManualRecipient() {
        wizardError("");
        var phone = normalizePhone($("bc-manual-phone").value);
        var name = $("bc-manual-name").value.trim();

        if (!phone) {
            wizardError("Enter a phone number first.");
            $("bc-manual-phone").focus();
            return;
        }
        if (!PHONE_RE.test(phone)) {
            wizardError("That number needs a country code, like +60123456789.");
            $("bc-manual-phone").focus();
            return;
        }
        if (!addRecipients([{ phone: phone, name: name }])) {
            wizardError(phone + " is already on the list.");
            return;
        }

        $("bc-manual-phone").value = "";
        $("bc-manual-name").value = "";
        $("bc-manual-phone").focus();
        renderRecipients("Added " + phone + ".");
    }

    /* ══════════════════════════ MESSAGE PREVIEW ══════════════════════════ */

    function selectedMedia() {
        var id = $("bc-media").value;
        if (!id) return null;
        return state.media.filter(function (m) { return String(m.id) === String(id); })[0] || null;
    }

    function metaTemplateName() {
        return $("bc-meta-template").value.trim();
    }

    /* Splits the composed text the way process_broadcast_dispatch does, so
       the preview shows the buttons it will actually strip out of the body. */
    function splitButtons(text) {
        var labels = [];
        var match;
        BUTTON_RE.lastIndex = 0;
        while ((match = BUTTON_RE.exec(text)) !== null) {
            if (match[1].trim()) labels.push(match[1].trim());
        }
        return {
            body: text.replace(BUTTON_RE, "").trim(),
            buttons: labels.slice(0, MAX_BUTTONS)
        };
    }

    function previewModel() {
        var template = metaTemplateName();

        // The dispatch worker sends the Meta template and ignores
        // message_template entirely when a template name is set. The preview
        // has to say so, or the page lies about what it will send.
        if (state.channel === "whatsapp" && template) {
            return {
                kind: "template",
                template: template,
                language: $("bc-meta-language").value.trim() || "en_US",
                media: selectedMedia()
            };
        }
        if (state.bodyMode === "welcome") {
            return { kind: "welcome", media: selectedMedia() };
        }
        var split = splitButtons($("bc-body").value);
        return { kind: "custom", body: split.body, buttons: split.buttons, media: selectedMedia() };
    }

    function mediaBlock(media) {
        if (!media) return "";
        var type = String(media.media_type || "file").toLowerCase();
        if (type === "image" && media.media_url) {
            return '<div class="wa-media"><img src="' + esc(media.media_url) + '" alt=""></div>';
        }
        var label = type === "video" ? "Video attachment"
            : type === "image" ? "Image attachment" : "File attachment";
        return '<div class="wa-media">' + esc(label) + " &middot; " + esc(media.label || "") + "</div>";
    }

    function renderPreview(container, model) {
        var time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        var inner;

        if (model.kind === "template") {
            inner = mediaBlock(model.media)
                + '<div class="wa-head">' + esc(model.template) + "</div>"
                + '<div class="wa-body"><em>Whatever Meta approved for this template, in '
                + esc(model.language) + ".</em></div>";
        } else if (model.kind === "welcome") {
            inner = mediaBlock(model.media)
                + '<div class="wa-body"><em>This bot\'s welcome message, as it reads right now.</em></div>';
        } else {
            var body = model.body
                ? esc(model.body).replace(/\{\{phone\}\}/g, "+60123456789")
                : "<em>Your message will appear here.</em>";
            inner = mediaBlock(model.media) + '<div class="wa-body">' + body + "</div>";
        }

        var buttons = (model.buttons || []).map(function (label) {
            return '<div class="wa-btn">' + esc(label) + "</div>";
        }).join("");

        container.innerHTML = '<div class="wa-bubble">' + inner
            + '<div class="wa-meta">' + esc(time) + "</div></div>"
            + (buttons ? '<div class="wa-btns">' + buttons + "</div>" : "");
    }

    function previewNote(model) {
        if (model.kind === "template") {
            return "You named an approved template, so WhatsApp sends that template. Your own message text is "
                + "not used. Clear the template name to send your own words.";
        }
        if (model.kind === "welcome") {
            return "Every recipient gets the bot's current welcome message, not a fixed copy of it.";
        }
        if (state.channel === "whatsapp") {
            return "Without an approved template, WhatsApp only delivers this to people who messaged you in the "
                + "last 24 hours.";
        }
        return "WasenderAPI sends from your connected WhatsApp session, so no template approval is needed.";
    }

    function refreshMessageStep() {
        var model = previewModel();
        renderPreview($("bc-preview"), model);
        $("bc-preview-note").textContent = previewNote(model);

        var length = $("bc-body").value.length;
        $("bc-body-count").textContent = length ? length + " / 1024" : "";
        updateBottombar();
    }

    /* ══════════════════════════ WIZARD ══════════════════════════ */

    function setSegment(groupId, attribute, value) {
        var buttons = $(groupId).querySelectorAll("button");
        Array.prototype.forEach.call(buttons, function (button) {
            var selected = button.getAttribute(attribute) === value;
            button.setAttribute("aria-checked", selected ? "true" : "false");
            button.tabIndex = selected ? 0 : -1;
        });
    }

    function setSource(source) {
        state.source = source;
        setSegment("bc-source", "data-source", source);
        ["csv", "crm", "manual"].forEach(function (name) {
            show(document.querySelector('[data-source-panel="' + name + '"]'), name === source);
        });
        wizardError("");
    }

    function setChannel(channel) {
        state.channel = channel;
        setSegment("bc-channel", "data-channel", channel);
        show($("bc-meta-advanced"), channel === "whatsapp");
        $("bc-channel-help").textContent = channel === "whatsapp"
            ? "Meta's official API. Reliable and supported, but reaching someone outside a 24-hour window needs an approved template."
            : "Your connected WhatsApp session. No template approval needed, and no 24-hour window.";
        refreshMessageStep();
    }

    function setBodyMode(mode) {
        state.bodyMode = mode;
        setSegment("bc-body-mode", "data-mode", mode);
        show($("bc-body-field"), mode === "custom");
        show($("bc-welcome-note"), mode === "welcome");
        refreshMessageStep();
    }

    function setStep(step) {
        state.step = step;
        [1, 2, 3].forEach(function (n) {
            show($("bc-step-" + n), n === step);
            var marker = document.querySelector('.kw-step[data-step="' + n + '"]');
            if (!marker) return;
            marker.classList.toggle("is-current", n === step);
            marker.classList.toggle("is-done", n < step);
        });

        if (step === 3) buildReview();
        updateBottombar();

        var heading = $("bc-step-" + step + "-heading");
        if (heading) heading.focus();
    }

    function stepBlocker() {
        if (state.step === 1) {
            return state.recipients.length ? null : "Add at least one recipient to continue.";
        }
        if (state.step === 2) {
            if (!$("bc-name").value.trim()) return "Give the campaign a name so you can find it later.";
            if (state.bodyMode === "custom" && !metaTemplateName() && !$("bc-body").value.trim()) {
                return "Write the message, or pick an approved template.";
            }
            return null;
        }
        return null;
    }

    function updateBottombar() {
        var blocker = stepBlocker();
        $("bc-bottombar-title").textContent = "Step " + state.step + " of 3";

        show($("bc-prev"), state.step > 1);
        show($("bc-next"), state.step < 3);
        show($("bc-send"), state.step === 3);
        show($("bc-save-draft"), state.step > 1);

        $("bc-next").disabled = !!blocker;

        if (state.step === 3) {
            var armed = isArmed();
            $("bc-send").disabled = !armed;
            $("bc-bottombar-note").textContent = armed
                ? "Ready. You will still get ten seconds to stop it."
                : "Type the campaign name in the box above to unlock sending.";
            return;
        }

        $("bc-bottombar-note").textContent = blocker || "Looks good. Move on when you are ready.";
    }

    function openWizard(campaign) {
        clearNotice();
        wizardError("");
        state.draftId = campaign ? campaign.id : null;
        state.recipients = [];
        state.crmContacts = [];

        $("bc-name").value = campaign ? campaign.name || "" : "";
        $("bc-meta-template").value = campaign ? campaign.meta_template_name || "" : "";
        $("bc-meta-language").value = (campaign && campaign.meta_language_code) || "en_US";
        $("bc-media").value = campaign && campaign.media_attachment_id ? String(campaign.media_attachment_id) : "";
        $("bc-arm").value = "";
        $("bc-csv-input").value = "";

        var template = campaign ? campaign.message_template || "" : "";
        if (!campaign || template === WELCOME_SENTINEL) {
            $("bc-body").value = "";
            setBodyMode(campaign ? "welcome" : "custom");
        } else {
            $("bc-body").value = template;
            setBodyMode("custom");
        }

        setChannel(campaign ? campaign.channel_type || "whatsapp" : "whatsapp");
        setSource("csv");
        renderRecipients("");
        showScreen("wizard");
        setStep(1);

        // Returned so a caller that wants to land on a later step can wait for
        // the recipients instead of guessing how long the fetch takes.
        return campaign ? loadDraftRecipients(campaign.id) : Promise.resolve();
    }

    async function loadDraftRecipients(campaignId) {
        var result = await api(withBot("/api/broadcast/campaign/" + campaignId + "/logs"));
        if (!result.ok) return;
        var list = (result.body.logs || []).map(function (log) {
            return { phone: log.recipient_phone, name: "" };
        });
        addRecipients(list);
        renderRecipients("Loaded " + list.length + " " + plural(list.length, "recipient", "recipients")
            + " from this draft.");
    }

    function messageTemplateValue() {
        if (state.bodyMode === "welcome") return WELCOME_SENTINEL;
        var text = $("bc-body").value.trim();
        // The backend rejects an empty message_template, but a template-only
        // send legitimately has no body of its own.
        return text || (metaTemplateName() ? "[template] " + metaTemplateName() : "");
    }

    function campaignPayload() {
        return {
            name: $("bc-name").value.trim(),
            channel_type: state.channel,
            message_template: messageTemplateValue(),
            meta_template_name: state.channel === "whatsapp" ? metaTemplateName() : "",
            meta_language_code: $("bc-meta-language").value.trim() || "en_US",
            media_attachment_id: $("bc-media").value || null,
            recipients: state.recipients
        };
    }

    async function persistDraft() {
        var payload = campaignPayload();
        if (!payload.name) return { ok: false, body: { message: "Give the campaign a name first." } };
        if (!payload.recipients.length) return { ok: false, body: { message: "Add at least one recipient." } };

        if (state.draftId) {
            return api(withBot("/api/broadcast/campaign/" + state.draftId), jsonRequest("PATCH", payload));
        }

        var created = await api(withBot("/api/broadcast/campaign"), jsonRequest("POST", payload));
        if (created.ok && created.body.campaign) state.draftId = created.body.campaign.id;
        return created;
    }

    async function saveDraft() {
        if (state.busy) return;
        state.busy = true;
        $("bc-save-draft").disabled = true;
        wizardError("");

        var result = await persistDraft();

        $("bc-save-draft").disabled = false;
        state.busy = false;

        if (!result.ok) {
            wizardError(result.body.message || "We could not save this draft.");
            return;
        }

        notice("Saved as a draft. Nothing has been sent.");
        showScreen("list");
        await loadCampaigns();
    }

    /* ── Review step ───────────────────────────────────────────────── */

    function buildReview() {
        var count = state.recipients.length;
        $("bc-review-count").textContent = count;
        $("bc-review-count-note").textContent = "At one message every 3 seconds, this takes about "
            + formatDuration(count * SEND_INTERVAL_MS) + ".";

        var model = previewModel();
        renderPreview($("bc-review-preview"), model);

        var media = selectedMedia();
        var rows = [
            ["Campaign name", $("bc-name").value.trim() || "-"],
            ["Sent through", CHANNEL_COPY[state.channel] || state.channel],
            ["Message", model.kind === "template"
                ? "Approved template: " + metaTemplateName()
                : model.kind === "welcome"
                    ? "The bot's welcome message"
                    : "Your own text"],
            ["Attachment", media ? (media.label || "Attached") : "None"],
            ["Can be undone", "No. Delivered messages cannot be recalled."]
        ];

        $("bc-review-summary").innerHTML = rows.map(function (row) {
            return "<dt>" + esc(row[0]) + "</dt><dd>" + esc(row[1]) + "</dd>";
        }).join("");

        $("bc-arm").placeholder = $("bc-name").value.trim();
    }

    function isArmed() {
        var name = $("bc-name").value.trim();
        return !!name && $("bc-arm").value.trim() === name;
    }

    /* ══════════════════════════ DISPATCH CONSOLE ══════════════════════════ */

    function clearTimers() {
        if (state.pollTimer) {
            clearInterval(state.pollTimer);
            state.pollTimer = null;
        }
        if (state.countdownTimer) {
            clearInterval(state.countdownTimer);
            state.countdownTimer = null;
        }
    }

    async function beginSend() {
        if (!isArmed() || state.busy) return;
        state.busy = true;
        $("bc-send").disabled = true;
        wizardError("");

        var saved = await persistDraft();

        state.busy = false;
        $("bc-send").disabled = false;

        if (!saved.ok) {
            wizardError(saved.body.message || "We could not prepare this campaign.");
            return;
        }

        startCountdown(saved.body.campaign);
    }

    /* The ten seconds between arming and dispatch. No send request has been
       made yet, so Undo here means nobody is messaged at all -- which is why
       the copy says exactly that instead of promising a recall. */
    function startCountdown(campaign) {
        clearTimers();
        state.consoleId = (campaign && campaign.id) || state.draftId;

        showScreen("console");
        show($("bc-countdown"), true);
        show($("bc-console-panel"), false);
        show($("bc-console-back"), false);

        var remaining = UNDO_SECONDS;
        var count = state.recipients.length;
        $("bc-countdown-value").textContent = remaining;
        $("bc-countdown-title").textContent = "Sending to " + count + " "
            + plural(count, "person", "people") + " in a moment";
        announce("Sending in " + remaining + " seconds. Choose stop to cancel.", true);
        $("bc-undo").focus();

        state.countdownTimer = setInterval(function () {
            remaining -= 1;
            $("bc-countdown-value").textContent = Math.max(remaining, 0);
            if (remaining <= 0) {
                clearTimers();
                dispatch();
            }
        }, 1000);
    }

    function abortCountdown() {
        clearTimers();
        show($("bc-countdown"), false);
        showScreen("wizard");
        setStep(3);
        notice("Stopped. Nobody was messaged, and your draft is saved.");
        loadCampaigns();
    }

    async function dispatch() {
        show($("bc-countdown"), false);
        show($("bc-console-panel"), true);
        show($("bc-stop"), true);
        show($("bc-console-done"), false);
        $("bc-console-title").textContent = $("bc-name").value.trim() || "Sending";
        $("bc-console-sub").textContent = "Messages go out one at a time, about one every three seconds.";
        setConsolePill("sending");
        announce("Sending has started.", true);

        var result = await api(withBot("/api/broadcast/campaign/" + state.consoleId + "/start"), { method: "POST" });
        if (!result.ok) {
            $("bc-console-sub").textContent = result.body.message || "We could not start this campaign.";
            setConsolePill("failed");
            finishConsole();
            return;
        }

        await pollProgress();
        if (!state.pollTimer) state.pollTimer = setInterval(pollProgress, POLL_MS);
    }

    function setConsolePill(status) {
        var copy = STATUS_COPY[status] || { label: status, pill: "" };
        var pill = $("bc-console-pill");
        pill.className = "kw-pill " + copy.pill;
        pill.textContent = copy.label;
    }

    async function pollProgress() {
        if (!state.consoleId) return;
        var result = await api(withBot("/api/broadcast/campaign/" + state.consoleId + "/progress"));
        if (!result.ok) return;

        var progress = result.body;
        state.progress[state.consoleId] = progress;

        var total = progress.total || 0;
        var done = progress.done || 0;
        var bar = $("bc-console-progress");

        $("bc-console-progress-fill").style.transform = "scaleX(" + (total ? done / total : 0) + ")";
        bar.setAttribute("role", "progressbar");
        bar.setAttribute("aria-valuenow", String(done));
        bar.setAttribute("aria-valuemin", "0");
        bar.setAttribute("aria-valuemax", String(total));
        bar.setAttribute("aria-valuetext", done + " of " + total + " done");

        $("bc-tally-sent").textContent = progress.sent || 0;
        $("bc-tally-failed").textContent = progress.failed || 0;
        $("bc-tally-pending").textContent = progress.pending || 0;
        $("bc-tally-eta").textContent = progress.pending
            ? formatDuration(progress.pending * SEND_INTERVAL_MS)
            : "-";

        setConsolePill(progress.campaign_status);

        if (progress.campaign_status === "sending" || progress.campaign_status === "cancelling") return;

        clearTimers();
        var summary = progress.sent + " delivered, " + progress.failed + " failed"
            + (progress.cancelled ? ", " + progress.cancelled + " cancelled" : "") + ".";
        $("bc-console-sub").textContent = summary;
        announce("Finished. " + summary, true);
        finishConsole();
    }

    function finishConsole() {
        show($("bc-stop"), false);
        show($("bc-console-done"), true);
        show($("bc-console-back"), true);
        $("bc-console-done").focus();
    }

    async function stopSending() {
        $("bc-stop").disabled = true;
        var result = await api(withBot("/api/broadcast/campaign/" + state.consoleId + "/cancel"), { method: "POST" });
        $("bc-stop").disabled = false;

        if (!result.ok) {
            $("bc-console-sub").textContent = result.body.message || "We could not stop this campaign.";
            return;
        }
        $("bc-console-sub").textContent = result.body.message + " Messages already delivered stay delivered.";
        announce(result.body.message, true);
        pollProgress();
    }

    async function watchCampaign(campaign) {
        clearTimers();
        state.consoleId = campaign.id;
        showScreen("console");
        show($("bc-countdown"), false);
        show($("bc-console-panel"), true);
        show($("bc-stop"), true);
        show($("bc-console-done"), false);
        show($("bc-console-back"), true);
        $("bc-console-title").textContent = campaign.name;
        $("bc-console-sub").textContent = "Messages go out one at a time, about one every three seconds.";

        await pollProgress();
        if (!state.pollTimer && (campaign.status === "sending" || campaign.status === "cancelling")) {
            state.pollTimer = setInterval(pollProgress, POLL_MS);
        }
    }

    /* ══════════════════════════ LOGS MODAL ══════════════════════════ */

    async function openLogs(campaign) {
        $("bc-logs-title").textContent = campaign.name;
        $("bc-logs-sub").textContent = "Loading...";
        $("bc-logs-list").innerHTML = "";
        kwDialog.open($("bc-logs-modal"), $("bc-logs-close"));

        var result = await api(withBot("/api/broadcast/campaign/" + campaign.id + "/logs"));
        if (!result.ok) {
            $("bc-logs-sub").textContent = result.body.message || "We could not load the recipients.";
            return;
        }
        state.logs = result.body.logs || [];
        $("bc-logs-sub").textContent = state.logs.length + " "
            + plural(state.logs.length, "recipient", "recipients") + ".";
        renderLogs();
    }

    function logLabel(status) {
        if (status === "sent") return { text: "Delivered", pill: "kw-pill-ready" };
        if (status === "failed") return { text: "Failed", pill: "kw-pill-off" };
        if (status === "cancelled") return { text: "Cancelled", pill: "kw-pill-off" };
        if (status === "sending") return { text: "Sending", pill: "kw-pill-review" };
        return { text: "Not sent yet", pill: "kw-pill-review" };
    }

    function renderLogs() {
        var filter = $("bc-logs-filter").value;
        var rows = state.logs.filter(function (log) { return !filter || log.status === filter; });

        show($("bc-logs-empty"), !rows.length);
        $("bc-logs-list").innerHTML = rows.map(function (log) {
            var label = logLabel(log.status);
            return '<div class="bc-log-row">'
                + '<span data-part="phone">' + esc(log.recipient_phone) + "</span>"
                + '<span class="kw-pill ' + label.pill + '">' + esc(label.text) + "</span>"
                + '<span data-part="time">' + esc(log.sent_at ? formatDate(log.sent_at) : "") + "</span>"
                + (log.error_message ? '<span class="bc-log-error">' + esc(log.error_message) + "</span>" : "")
                + "</div>";
        }).join("");
    }

    function copyFailedNumbers() {
        var failed = state.logs.filter(function (log) { return log.status === "failed"; });
        if (!failed.length) {
            $("bc-logs-sub").textContent = "No failed numbers to copy.";
            return;
        }
        var text = failed.map(function (log) { return log.recipient_phone; }).join("\n");
        if (!navigator.clipboard) {
            $("bc-logs-sub").textContent = "Your browser blocked the clipboard. Select the numbers and copy them.";
            return;
        }
        navigator.clipboard.writeText(text).then(function () {
            $("bc-logs-sub").textContent = "Copied " + failed.length + " failed "
                + plural(failed.length, "number", "numbers") + " to your clipboard.";
        }, function () {
            $("bc-logs-sub").textContent = "Your browser blocked the clipboard. Select the numbers and copy them.";
        });
    }

    /* ══════════════════════════ CONFIRM MODAL ══════════════════════════ */

    function askConfirm(title, body, confirmLabel, action) {
        $("bc-confirm-title").textContent = title;
        $("bc-confirm-body").textContent = body;
        $("bc-confirm-ok").textContent = confirmLabel;
        state.confirmAction = action;
        kwDialog.open($("bc-confirm"), $("bc-confirm-cancel"));
    }

    function closeConfirm() {
        kwDialog.close($("bc-confirm"));
        state.confirmAction = null;
    }

    async function deleteCampaign(campaign) {
        var result = await api(withBot("/api/broadcast/campaign/" + campaign.id), { method: "DELETE" });
        if (!result.ok) {
            pageError(result.body.message || "We could not delete that campaign.");
            return;
        }
        delete state.progress[campaign.id];
        notice('Deleted "' + campaign.name + '".');
        await loadCampaigns();
    }

    /* ══════════════════════════ LOOKUPS ══════════════════════════ */

    async function loadMedia() {
        var result = await api("/api/media-attachments?chatbot_id=" + encodeURIComponent(botId));
        if (!result.ok) return;
        state.media = result.body.data || [];
        $("bc-media").innerHTML = '<option value="">No attachment</option>'
            + state.media.map(function (media) {
                return '<option value="' + esc(media.id) + '">' + esc(media.label)
                    + " (" + esc(media.media_type) + ")</option>";
            }).join("");
    }

    /* Suggestions only. A failed lookup means this bot has no Meta channel
       connected yet, which is not an error worth showing on this page. */
    async function loadMetaTemplates() {
        var result = await api(withBot("/api/meta-templates"));
        if (!result.ok) return;
        var approved = (result.body.data || []).filter(function (template) {
            return String(template.status || "").toUpperCase() === "APPROVED";
        });
        $("bc-meta-template-options").innerHTML = approved.map(function (template) {
            return '<option value="' + esc(template.name) + '"></option>';
        }).join("");
    }

    /* ══════════════════════════ WIRING ══════════════════════════ */

    function onSegmentClick(groupId, attribute, handler) {
        $(groupId).addEventListener("click", function (event) {
            var button = event.target.closest("button[" + attribute + "]");
            if (button) handler(button.getAttribute(attribute));
        });
    }

    function wireList() {
        $("bc-new").addEventListener("click", function () { openWizard(null); });
        $("bc-empty-action").addEventListener("click", function () { openWizard(null); });
        $("bc-retry").addEventListener("click", loadCampaigns);
        $("bc-search").addEventListener("input", renderTable);
        $("bc-filter-status").addEventListener("change", renderTable);

        $("bc-table-body").addEventListener("click", function (event) {
            var button = event.target.closest("button[data-act]");
            if (!button) return;
            var campaign = campaignById(button.getAttribute("data-id"));
            if (!campaign) return;

            var act = button.getAttribute("data-act");
            if (act === "logs") return openLogs(campaign);
            if (act === "watch") return watchCampaign(campaign);
            if (act === "edit" || act === "send") {
                var ready = openWizard(campaign);
                // The draft's recipients arrive asynchronously; jumping to
                // review before they land would show a count of zero.
                if (act === "send") {
                    ready.then(function () {
                        if (state.recipients.length) setStep(3);
                    });
                }
                return;
            }
            if (act === "delete") {
                askConfirm(
                    "Delete this campaign?",
                    '"' + campaign.name + '" and its recipient list will be removed. '
                        + "Messages already delivered are not affected.",
                    "Delete",
                    function () { deleteCampaign(campaign); }
                );
            }
        });
    }

    function wireWizard() {
        $("bc-wizard-back").addEventListener("click", function () {
            showScreen("list");
            loadCampaigns();
        });
        $("bc-next").addEventListener("click", function () {
            var blocker = stepBlocker();
            if (blocker) {
                wizardError(blocker);
                return;
            }
            wizardError("");
            setStep(state.step + 1);
        });
        $("bc-prev").addEventListener("click", function () { setStep(state.step - 1); });
        $("bc-save-draft").addEventListener("click", saveDraft);
        $("bc-send").addEventListener("click", beginSend);

        onSegmentClick("bc-source", "data-source", setSource);
        $("bc-csv-drop").addEventListener("click", function () { $("bc-csv-input").click(); });
        $("bc-csv-input").addEventListener("change", function (event) { handleCsvFile(event.target.files[0]); });
        ["dragenter", "dragover", "dragleave", "drop"].forEach(function (name) {
            $("bc-csv-drop").addEventListener(name, function (event) {
                event.preventDefault();
                event.stopPropagation();
            });
        });
        $("bc-csv-drop").addEventListener("drop", function (event) {
            handleCsvFile(event.dataTransfer.files[0]);
        });
        $("bc-crm-load").addEventListener("click", loadCrmContacts);
        $("bc-crm-recency").addEventListener("change", function () {
            if (state.crmContacts.length) applyRecency();
        });
        $("bc-manual-add").addEventListener("click", addManualRecipient);
        $("bc-manual-phone").addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
                addManualRecipient();
            }
        });
        $("bc-recipients").addEventListener("click", function (event) {
            var button = event.target.closest('[data-part="remove"]');
            if (!button) return;
            state.recipients.splice(Number(button.getAttribute("data-index")), 1);
            renderRecipients("");
        });
        $("bc-clear-recipients").addEventListener("click", function () {
            state.recipients = [];
            state.crmContacts = [];
            renderRecipients("");
        });

        onSegmentClick("bc-channel", "data-channel", setChannel);
        onSegmentClick("bc-body-mode", "data-mode", setBodyMode);
        ["bc-body", "bc-meta-template", "bc-meta-language"].forEach(function (id) {
            $(id).addEventListener("input", refreshMessageStep);
        });
        $("bc-media").addEventListener("change", refreshMessageStep);
        $("bc-name").addEventListener("input", updateBottombar);
        $("bc-arm").addEventListener("input", updateBottombar);
    }

    function wireConsole() {
        $("bc-undo").addEventListener("click", abortCountdown);
        $("bc-stop").addEventListener("click", stopSending);
        $("bc-console-logs").addEventListener("click", function () {
            openLogs(campaignById(state.consoleId)
                || { id: state.consoleId, name: $("bc-console-title").textContent });
        });
        ["bc-console-done", "bc-console-back"].forEach(function (id) {
            $(id).addEventListener("click", function () {
                clearTimers();
                showScreen("list");
                loadCampaigns();
            });
        });
    }

    function wireModals() {
        $("bc-logs-close").addEventListener("click", function () {
            kwDialog.close($("bc-logs-modal"));
        });
        $("bc-logs-modal").addEventListener("click", function (event) {
            if (event.target === event.currentTarget) kwDialog.close(event.currentTarget);
        });
        $("bc-logs-filter").addEventListener("change", renderLogs);
        $("bc-logs-copy-failed").addEventListener("click", copyFailedNumbers);

        $("bc-confirm-cancel").addEventListener("click", closeConfirm);
        $("bc-confirm-ok").addEventListener("click", function () {
            var action = state.confirmAction;
            closeConfirm();
            if (action) action();
        });
        $("bc-confirm").addEventListener("click", function (event) {
            if (event.target === event.currentTarget) closeConfirm();
        });

        document.addEventListener("keydown", function (event) {
            if (event.key !== "Escape") return;
            if (kwDialog.isOpen($("bc-logs-modal"))) {
                kwDialog.close($("bc-logs-modal"));
                return;
            }
            if (kwDialog.isOpen($("bc-confirm"))) closeConfirm();
        });

        // A running countdown is the one thing on this page that must not be
        // lost to an accidental tab close, because its expiry sends real
        // messages.
        window.addEventListener("beforeunload", function (event) {
            if (!state.countdownTimer) return;
            event.preventDefault();
            event.returnValue = "";
        });
    }

    /* ══════════════════════════ BOOT ══════════════════════════ */

    (async function boot() {
        showScreen("list");

        if (!botId) {
            show($("bc-list-loading"), false);
            pageError("Pick a bot first. Open this page from the bot you want to broadcast from.");
            show($("bc-retry"), false);
            show($("bc-new"), false);
            return;
        }

        // Arrow keys for every .kw-segment on the page. Without this the
        // roving tabindex leaves a keyboard user stuck on one option.
        kwRadioGroup(document);

        wireList();
        wireWizard();
        wireConsole();
        wireModals();

        await Promise.all([loadCampaigns(), loadMedia(), loadMetaTemplates()]);
    })();
})();
