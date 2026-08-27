/* meta-templates.js - the template library and the guided builder.
 *
 * The old page opened straight into a 700-line form, with your existing
 * templates hidden behind a second tab. That is backwards: you cannot
 * decide whether to write a new template until you have seen the ones you
 * already have. So the library is the landing screen, and every card shows
 * the message itself rather than a truncated slug -- recognition instead of
 * recall.
 *
 * Both the cards and the builder render through renderPreview(), from the
 * same model shape, so a template can never look one way in the list and a
 * different way while you are editing it.
 */

(function () {
    "use strict";

    /* ── Constants ─────────────────────────────────────────────────── */

    var MAX_BUTTONS = 3;
    var NAME_RE = /^[a-z0-9_]+$/;

    var STATUS_COPY = {
        APPROVED: { label: "Ready to use", pill: "kw-pill-ready" },
        PENDING: { label: "Waiting on Meta", pill: "kw-pill-review" },
        IN_APPEAL: { label: "Under appeal", pill: "kw-pill-review" },
        PENDING_DELETION: { label: "Being deleted", pill: "kw-pill-review" },
        REJECTED: { label: "Rejected", pill: "kw-pill-off" },
        DISABLED: { label: "Disabled", pill: "kw-pill-off" },
        PAUSED: { label: "Paused", pill: "kw-pill-off" }
    };

    var CATEGORY_HELP = {
        MARKETING: "Anything promotional. Meta is strictest here, and customers can opt out of these.",
        UTILITY: "Follows up on something the customer already did, like an order or a booking.",
        AUTHENTICATION: "One-time passcodes only. Meta rejects anything else filed under this."
    };

    var BUTTON_TYPES = [
        { value: "QUICK_REPLY", label: "Send a reply", needsValue: false, placeholder: "" },
        { value: "URL", label: "Open a website", needsValue: true, placeholder: "https://example.com/offer" },
        { value: "PHONE_NUMBER", label: "Call a number", needsValue: true, placeholder: "+60123456789" },
        { value: "COPY_CODE", label: "Copy a code", needsValue: true, placeholder: "SUMMER20" }
    ];

    var MEDIA_ACCEPT = {
        IMAGE: "image/jpeg,image/png",
        VIDEO: "video/mp4",
        DOCUMENT: "application/pdf"
    };

    var MEDIA_HINT = {
        IMAGE: "A JPG or PNG. Meta needs a sample so a reviewer can see the header.",
        VIDEO: "An MP4. Meta needs a sample so a reviewer can see the header.",
        DOCUMENT: "A PDF. Meta needs a sample so a reviewer can see the header."
    };

    var QUICK_INSERTS = [
        { kind: "variable", text: "{{1}}", title: "a value that changes per person" },
        { kind: "variable", text: "{{2}}", title: "a second changing value" },
        { kind: "emoji", text: "👋" }, { kind: "emoji", text: "🎉" },
        { kind: "emoji", text: "🔥" }, { kind: "emoji", text: "✅" },
        { kind: "emoji", text: "📦" }, { kind: "emoji", text: "📅" },
        { kind: "emoji", text: "💳" }, { kind: "emoji", text: "🎁" },
        { kind: "emoji", text: "⚡" }, { kind: "emoji", text: "🙏" }
    ];

    var STARTERS = [
        {
            title: "Promotional offer",
            blurb: "A discount with an image header, a coupon code that changes per person, and an opt-out line.",
            name: "promo_offer_v1",
            category: "MARKETING",
            headerType: "IMAGE",
            headerText: "",
            body: "Hi {{1}}, we are running a promotion this week.\n\nUse code {{2}} at checkout for {{3}}% off. Offer ends soon.",
            footer: "Reply STOP to unsubscribe",
            buttons: [{ type: "URL", text: "Shop now", value: "https://example.com/shop" }]
        },
        {
            title: "Order confirmed",
            blurb: "A utility message with the customer's name, order number, delivery date, and a PDF invoice header.",
            name: "order_confirmed_v1",
            category: "UTILITY",
            headerType: "DOCUMENT",
            headerText: "",
            body: "Hi {{1}}, your order #{{2}} is confirmed.\n\nEstimated delivery: {{3}}. Your invoice is attached.",
            footer: "Questions? Just reply here.",
            buttons: []
        },
        {
            title: "Appointment reminder",
            blurb: "A plain-text reminder with date and time, and two buttons to confirm or reschedule.",
            name: "appointment_reminder_v1",
            category: "UTILITY",
            headerType: "TEXT",
            headerText: "Appointment reminder",
            body: "Hi {{1}}, this is a reminder about your appointment on {{2}} at {{3}}.\n\nSee you then.",
            footer: "",
            buttons: [
                { type: "QUICK_REPLY", text: "Confirm", value: "" },
                { type: "QUICK_REPLY", text: "Reschedule", value: "" }
            ]
        },
        {
            title: "Welcome message",
            blurb: "Greets a new contact with a short video and your business name.",
            name: "welcome_video_v1",
            category: "MARKETING",
            headerType: "VIDEO",
            headerText: "",
            body: "Welcome to {{1}}.\n\nWe are glad you are here. This short video covers everything you need to get started.\n\nReply any time with a question.",
            footer: "Reply STOP to unsubscribe",
            buttons: []
        }
    ];

    /* ── State ─────────────────────────────────────────────────────── */

    var botId = resolveBotId();

    var state = {
        templates: [],
        statusFilter: "",
        step: 1,
        confirmAction: null,
        busy: false,
        builder: null
    };

    function blankBuilder() {
        return {
            name: "",
            language: "en_US",
            category: "MARKETING",
            headerType: "none",
            headerText: "",
            mediaUrl: "",
            body: "",
            footer: "",
            buttons: []
        };
    }

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

    function announce(message) {
        $("mt-announce").textContent = message;
    }

    function plural(count, one, many) {
        return count === 1 ? one : many;
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

    /* ── Banners ───────────────────────────────────────────────────── */

    function pageError(message, offerConnect) {
        $("mt-error-text").textContent = message;
        show($("mt-error-action"), !!offerConnect);
        show($("mt-error"), true);
    }

    function clearPageError() {
        show($("mt-error"), false);
    }

    function notice(message) {
        $("mt-notice-text").textContent = message;
        show($("mt-notice"), true);
        announce(message);
    }

    function clearNotice() {
        show($("mt-notice"), false);
    }

    function builderError(message) {
        $("mt-builder-error-text").textContent = message || "";
        show($("mt-builder-error"), !!message);
        if (message) announce(message);
    }

    function showScreen(name) {
        show($("mt-library"), name === "library");
        show($("mt-builder"), name === "builder");
    }

    /* ══════════════════════════ PREVIEW ══════════════════════════ */

    /* One model shape, two producers. A library card and the builder must
       agree about what a template looks like, so neither renders its own. */

    function previewFromComponents(components) {
        var model = { headerFormat: "", headerText: "", mediaUrl: "", body: "", footer: "", buttons: [] };

        (components || []).forEach(function (component) {
            var type = String(component.type || "").toUpperCase();
            if (type === "HEADER") {
                model.headerFormat = String(component.format || "TEXT").toUpperCase();
                model.headerText = component.text || "";
                var example = component.example || {};
                var urls = example.header_url || example.header_handle || [];
                model.mediaUrl = urls.length ? urls[0] : "";
            } else if (type === "BODY") {
                model.body = component.text || "";
            } else if (type === "FOOTER") {
                model.footer = component.text || "";
            } else if (type === "BUTTONS") {
                model.buttons = (component.buttons || []).map(function (button) {
                    return button.text || "";
                }).filter(Boolean);
            }
        });

        return model;
    }

    function previewFromBuilder() {
        var builder = state.builder;
        return {
            headerFormat: builder.headerType === "none" ? "" : builder.headerType,
            headerText: builder.headerType === "TEXT" ? builder.headerText : "",
            mediaUrl: builder.mediaUrl,
            body: builder.body,
            footer: builder.footer,
            buttons: builder.buttons.map(function (button) { return button.text; }).filter(Boolean)
        };
    }

    function mediaBlock(model) {
        var format = model.headerFormat;
        if (!format || format === "TEXT") return "";
        if (format === "IMAGE" && model.mediaUrl) {
            return '<div class="wa-media"><img src="' + esc(model.mediaUrl) + '" alt=""></div>';
        }
        var label = format === "VIDEO" ? "Video header"
            : format === "DOCUMENT" ? "File header" : "Image header";
        return '<div class="wa-media">' + esc(label) + "</div>";
    }

    function renderPreview(container, model) {
        var body = model.body ? esc(model.body) : "<em>Your message will appear here.</em>";
        var time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

        var inner = mediaBlock(model)
            + (model.headerText ? '<div class="wa-head">' + esc(model.headerText) + "</div>" : "")
            + '<div class="wa-body">' + body + "</div>"
            + (model.footer ? '<div class="wa-foot">' + esc(model.footer) + "</div>" : "")
            + '<div class="wa-meta">' + esc(time) + "</div>";

        var buttons = model.buttons.map(function (label) {
            return '<div class="wa-btn">' + esc(label) + "</div>";
        }).join("");

        container.innerHTML = '<div class="wa-bubble">' + inner + "</div>"
            + (buttons ? '<div class="wa-btns">' + buttons + "</div>" : "");
    }

    /* ══════════════════════════ LIBRARY ══════════════════════════ */

    async function loadTemplates() {
        clearPageError();
        show($("mt-loading"), true);
        show($("mt-grid"), false);
        show($("mt-empty"), false);

        var result = await api(withBot("/api/meta-templates"));
        show($("mt-loading"), false);

        if (!result.ok) {
            var message = result.body.message || "We could not load your templates.";
            var noChannel = message.indexOf("No active Meta WhatsApp integration") !== -1;
            pageError(
                noChannel
                    ? "This bot is not connected to WhatsApp yet, so it has no templates. Connect it first."
                    : message,
                noChannel
            );
            return;
        }

        state.templates = result.body.data || [];
        renderStats();
        renderGrid();
    }

    function statusOf(template) {
        return String(template.status || "PENDING").toUpperCase();
    }

    function isRejectedLike(status) {
        return status === "REJECTED" || status === "DISABLED" || status === "PAUSED";
    }

    function renderStats() {
        var approved = 0;
        var rejected = 0;
        var pending = 0;

        state.templates.forEach(function (template) {
            var status = statusOf(template);
            if (status === "APPROVED") approved += 1;
            else if (isRejectedLike(status)) rejected += 1;
            else pending += 1;
        });

        $("mt-stat-total").textContent = state.templates.length;
        $("mt-stat-approved").textContent = approved;
        $("mt-stat-pending").textContent = pending;
        $("mt-stat-rejected").textContent = rejected;
    }

    function matchesStatusFilter(template) {
        if (!state.statusFilter) return true;
        var status = statusOf(template);
        if (state.statusFilter === "APPROVED") return status === "APPROVED";
        if (state.statusFilter === "REJECTED") return isRejectedLike(status);
        return status !== "APPROVED" && !isRejectedLike(status);
    }

    function visibleTemplates() {
        var term = ($("mt-search").value || "").trim().toLowerCase();
        var category = $("mt-filter-category").value;

        return state.templates.filter(function (template) {
            if (!matchesStatusFilter(template)) return false;
            if (category && String(template.category || "").toUpperCase() !== category) return false;
            if (!term) return true;
            var model = previewFromComponents(template.components);
            var haystack = (template.name + " " + model.body + " " + model.headerText).toLowerCase();
            return haystack.indexOf(term) !== -1;
        });
    }

    function rejectionReason(template) {
        var reason = template.rejected_reason || template.rejection_reason || "";
        if (!reason || String(reason).toUpperCase() === "NONE") return "";
        return String(reason).replace(/_/g, " ").toLowerCase();
    }

    function templateCard(template) {
        var status = statusOf(template);
        var copy = STATUS_COPY[status] || { label: status, pill: "kw-pill-review" };
        var model = previewFromComponents(template.components);
        var name = template.name;

        var actions = [];
        if (status === "APPROVED") {
            actions.push('<button type="button" class="kw-action" data-act="use" data-name="' + esc(name)
                + '">Use in a broadcast</button>');
        }
        actions.push('<button type="button" class="kw-action" data-act="duplicate" data-name="' + esc(name)
            + '">Duplicate</button>');
        actions.push('<button type="button" class="kw-action kw-action-danger" data-act="delete" data-name="'
            + esc(name) + '">Delete</button>');

        var reason = isRejectedLike(status) ? rejectionReason(template) : "";

        return '<article class="mt-card">'
            + '<div class="mt-card-head">'
            + '<h3 class="mt-card-name">' + esc(name) + "</h3>"
            + '<span class="kw-pill ' + copy.pill + '">' + esc(copy.label) + "</span>"
            + "</div>"
            + '<div class="mt-card-tags">'
            + '<span class="mt-card-tag">' + esc(String(template.category || "uncategorised").toLowerCase()) + "</span>"
            + '<span class="mt-card-tag">' + esc(template.language || "") + "</span>"
            + (model.headerFormat
                ? '<span class="mt-card-tag">' + esc(model.headerFormat.toLowerCase()) + " header</span>"
                : "")
            + "</div>"
            + (reason ? '<p class="mt-card-reason">Meta rejected this: ' + esc(reason) + ".</p>" : "")
            + '<div class="wa-preview" role="group" aria-label="Preview of ' + esc(name) + '"></div>'
            + '<div class="mt-card-foot">' + actions.join("") + "</div>"
            + "</article>";
    }

    function renderGrid() {
        var rows = visibleTemplates();
        var filtering = !!($("mt-search").value || $("mt-filter-category").value || state.statusFilter);

        if (!rows.length) {
            show($("mt-grid"), false);
            show($("mt-empty"), true);
            $("mt-empty-title").textContent = filtering ? "Nothing matches" : "No templates yet";
            $("mt-empty-body").textContent = filtering
                ? "Try a different word, or clear the category and status filters."
                : "A template is a message Meta has approved in advance, so you can reach a customer who has not "
                    + "written to you recently. Build one, or start from an example.";
            show($("mt-empty-action"), !filtering);
            show($("mt-empty-starters"), !filtering);
            return;
        }

        show($("mt-empty"), false);
        show($("mt-grid"), true);
        $("mt-grid").innerHTML = rows.map(templateCard).join("");

        // The bubbles are filled in after the cards exist, so the card and the
        // builder can share one renderPreview instead of the card growing a
        // second copy of it as string concatenation.
        var previews = $("mt-grid").querySelectorAll(".wa-preview");
        Array.prototype.forEach.call(previews, function (container, index) {
            renderPreview(container, previewFromComponents(rows[index].components));
        });

        announce(rows.length + " " + plural(rows.length, "template", "templates") + " shown.");
    }

    function templateByName(name) {
        return state.templates.filter(function (t) { return t.name === name; })[0] || null;
    }

    /* ══════════════════════════ BUILDER ══════════════════════════ */

    function setSegment(groupId, attribute, value) {
        var buttons = $(groupId).querySelectorAll("button");
        Array.prototype.forEach.call(buttons, function (button) {
            var selected = button.getAttribute(attribute) === value;
            button.setAttribute("aria-checked", selected ? "true" : "false");
            button.tabIndex = selected ? 0 : -1;
        });
    }

    function sanitizeName(raw) {
        return String(raw || "").toLowerCase().replace(/[^a-z0-9_]/g, "_");
    }

    function setHeaderType(type) {
        state.builder.headerType = type;
        setSegment("mt-header-type", "data-header", type);
        show($("mt-header-text-field"), type === "TEXT");
        show($("mt-header-media-field"), !!MEDIA_ACCEPT[type]);

        if (MEDIA_ACCEPT[type]) {
            $("mt-media-input").accept = MEDIA_ACCEPT[type];
            $("mt-media-hint").textContent = MEDIA_HINT[type];
        }
        refreshPreview();
    }

    function renderButtons() {
        $("mt-buttons").innerHTML = state.builder.buttons.map(function (button, index) {
            var spec = BUTTON_TYPES.filter(function (t) { return t.value === button.type; })[0] || BUTTON_TYPES[0];
            var options = BUTTON_TYPES.map(function (type) {
                return '<option value="' + type.value + '"' + (type.value === button.type ? " selected" : "")
                    + ">" + esc(type.label) + "</option>";
            }).join("");

            return '<div class="mt-button-row" data-index="' + index + '" data-needs-value="'
                + (spec.needsValue ? "true" : "false") + '">'
                + '<label class="kw-visually-hidden" for="mt-btn-type-' + index + '">What button '
                + (index + 1) + " does</label>"
                + '<select class="kw-select" id="mt-btn-type-' + index + '" data-part="type">' + options + "</select>"
                + '<label class="kw-visually-hidden" for="mt-btn-text-' + index + '">Button '
                + (index + 1) + " label</label>"
                + '<input class="kw-input" id="mt-btn-text-' + index + '" data-part="text" type="text" maxlength="25"'
                + ' placeholder="Button label" value="' + esc(button.text) + '">'
                + (spec.needsValue
                    ? '<label class="kw-visually-hidden" for="mt-btn-value-' + index + '">Button '
                        + (index + 1) + " destination</label>"
                        + '<input class="kw-input" id="mt-btn-value-' + index + '" data-part="value" type="text"'
                        + ' placeholder="' + esc(spec.placeholder) + '" value="' + esc(button.value) + '">'
                    : "")
                + '<button type="button" class="kw-action kw-action-danger" data-part="remove"'
                + ' aria-label="Remove button ' + (index + 1) + '">Remove</button>'
                + "</div>";
        }).join("");

        var count = state.builder.buttons.length;
        $("mt-add-button").disabled = count >= MAX_BUTTONS;
        $("mt-buttons-help").textContent = count >= MAX_BUTTONS
            ? "That is the maximum of three. Remove one to add a different button."
            : "Up to three. They appear under the message.";
    }

    function renderInserts() {
        $("mt-body-inserts").innerHTML = QUICK_INSERTS.map(function (insert) {
            var description = insert.title || insert.text;
            return '<button type="button" class="mt-insert" data-kind="' + insert.kind + '" data-text="'
                + esc(insert.text) + '" aria-label="Insert ' + esc(description) + '">'
                + esc(insert.text) + "</button>";
        }).join("");
    }

    function insertIntoBody(text) {
        var field = $("mt-body");
        var start = field.selectionStart || 0;
        var end = field.selectionEnd || 0;
        field.value = field.value.slice(0, start) + text + field.value.slice(end);
        field.focus();
        field.selectionStart = field.selectionEnd = start + text.length;
        state.builder.body = field.value;
        refreshPreview();
    }

    function countVariables(text) {
        var matches = String(text || "").match(/\{\{\d+\}\}/g) || [];
        var unique = [];
        matches.forEach(function (token) {
            if (unique.indexOf(token) === -1) unique.push(token);
        });
        return unique.length;
    }

    function refreshPreview() {
        renderPreview($("mt-preview"), previewFromBuilder());

        $("mt-body-count").textContent = state.builder.body.length
            ? state.builder.body.length + " / 1024" : "";
        $("mt-header-count").textContent = state.builder.headerText.length
            ? state.builder.headerText.length + " / 60" : "";
        $("mt-footer-count").textContent = state.builder.footer.length
            ? state.builder.footer.length + " / 60" : "";

        var variables = countVariables(state.builder.body);
        $("mt-preview-note").textContent = variables
            ? "The " + variables + " " + plural(variables, "placeholder", "placeholders")
                + " stay as-is here, because that is what Meta reviews. They are filled in when the message is sent."
            : "This is the wording Meta reviews. Approval usually takes minutes.";

        updateBottombar();
    }

    /* ── Steps ─────────────────────────────────────────────────────── */

    function setStep(step) {
        state.step = step;
        [1, 2, 3].forEach(function (n) {
            show($("mt-step-" + n), n === step);
            var marker = document.querySelector('.kw-step[data-step="' + n + '"]');
            if (!marker) return;
            marker.classList.toggle("is-current", n === step);
            marker.classList.toggle("is-done", n < step);
        });

        if (step === 3) buildReview();
        updateBottombar();

        var heading = $("mt-step-" + step + "-heading");
        if (heading) heading.focus();
    }

    function nameIsTaken(name) {
        return state.templates.some(function (template) { return template.name === name; });
    }

    function stepBlocker() {
        var builder = state.builder;

        if (state.step === 1) {
            if (!builder.name) return "Give the template a name to continue.";
            if (!NAME_RE.test(builder.name)) return "The name can only use lowercase letters, numbers and underscores.";
            if (nameIsTaken(builder.name)) return "You already have a template called " + builder.name + ".";
            return null;
        }

        if (state.step === 2) {
            if (!builder.body.trim()) return "Write the message before continuing.";
            if (builder.headerType === "TEXT" && !builder.headerText.trim()) {
                return "Add the headline, or switch back to just text.";
            }
            var badButton = builder.buttons.filter(function (button) {
                if (!button.text.trim()) return true;
                var spec = BUTTON_TYPES.filter(function (t) { return t.value === button.type; })[0];
                return !!(spec && spec.needsValue && !button.value.trim());
            })[0];
            if (badButton) return "Every button needs a label, and a destination if it opens or calls something.";
            return null;
        }

        return null;
    }

    function updateBottombar() {
        var blocker = stepBlocker();
        $("mt-bottombar-title").textContent = "Step " + state.step + " of 3";

        show($("mt-prev"), state.step > 1);
        show($("mt-next"), state.step < 3);
        show($("mt-submit"), state.step === 3);

        $("mt-next").disabled = !!blocker;
        $("mt-bottombar-note").textContent = state.step === 3
            ? "Meta reviews the wording. You cannot edit it afterwards, only delete and rebuild."
            : blocker || "Looks good. Move on when you are ready.";
    }

    /* ── Review ────────────────────────────────────────────────────── */

    function reviewChecks() {
        var builder = state.builder;
        var checks = [];

        if (builder.category === "MARKETING" && !builder.footer.trim()) {
            checks.push("Marketing templates are approved more often when the small print offers a way to opt out.");
        }
        if (builder.category === "AUTHENTICATION" && !/\{\{\d+\}\}/.test(builder.body)) {
            checks.push("An authentication template normally carries the passcode in a placeholder like {{1}}.");
        }
        if (MEDIA_ACCEPT[builder.headerType] && !builder.mediaUrl.trim()) {
            checks.push("No example file given, so a stand-in is sent to Meta's reviewer. Uploading your own real "
                + "header makes approval more likely.");
        }
        if (/\b(free|guarantee|winner|urgent|click here)\b/i.test(builder.body)) {
            checks.push("Wording like \"free\", \"guarantee\" or \"click here\" is a common reason Meta rejects a "
                + "template. Consider rephrasing.");
        }
        return checks;
    }

    function buildReview() {
        var builder = state.builder;
        renderPreview($("mt-review-preview"), previewFromBuilder());

        var headerLabel = builder.headerType === "none" ? "None"
            : builder.headerType === "TEXT" ? "Headline text"
                : builder.headerType.charAt(0) + builder.headerType.slice(1).toLowerCase();

        var variables = countVariables(builder.body);
        var rows = [
            ["Name", builder.name],
            ["Language", builder.language],
            ["Category", builder.category.charAt(0) + builder.category.slice(1).toLowerCase()],
            ["Header", headerLabel],
            ["Placeholders", variables
                ? variables + " " + plural(variables, "placeholder", "placeholders")
                : "None"],
            ["Buttons", builder.buttons.length
                ? builder.buttons.map(function (b) { return b.text; }).join(", ")
                : "None"],
            ["Can be edited later", "No. Delete and rebuild to change the wording."]
        ];

        $("mt-review-summary").innerHTML = rows.map(function (row) {
            return "<dt>" + esc(row[0]) + "</dt><dd>" + esc(row[1]) + "</dd>";
        }).join("");

        var checks = reviewChecks();
        $("mt-review-checks").innerHTML = checks.length
            ? checks.map(function (check) { return '<p class="kw-help">' + esc(check) + "</p>"; }).join("")
            : '<p class="kw-help">Nothing here looks likely to trip Meta\'s review.</p>';
    }

    /* ── Open and prefill ──────────────────────────────────────────── */

    function openBuilder(preset) {
        clearNotice();
        builderError("");

        state.builder = Object.assign(blankBuilder(), preset || {});
        state.builder.buttons = (state.builder.buttons || []).map(function (button) {
            return { type: button.type, text: button.text || "", value: button.value || "" };
        });

        $("mt-name").value = state.builder.name;
        $("mt-language").value = state.builder.language;
        $("mt-category").value = state.builder.category;
        $("mt-header-text").value = state.builder.headerText;
        $("mt-media-url").value = state.builder.mediaUrl;
        $("mt-body").value = state.builder.body;
        $("mt-footer").value = state.builder.footer;
        $("mt-category-help").textContent = CATEGORY_HELP[state.builder.category];

        setHeaderType(state.builder.headerType);
        renderButtons();
        showScreen("builder");
        setStep(1);
        refreshPreview();
    }

    function duplicateOf(template) {
        var model = previewFromComponents(template.components);
        var buttonsComponent = (template.components || []).filter(function (component) {
            return String(component.type || "").toUpperCase() === "BUTTONS";
        })[0];

        return {
            name: sanitizeName(template.name + "_copy"),
            language: template.language || "en_US",
            category: String(template.category || "MARKETING").toUpperCase(),
            headerType: model.headerFormat || "none",
            headerText: model.headerText,
            mediaUrl: model.mediaUrl,
            body: model.body,
            footer: model.footer,
            buttons: ((buttonsComponent && buttonsComponent.buttons) || []).map(function (button) {
                return {
                    type: String(button.type || "QUICK_REPLY").toUpperCase(),
                    text: button.text || "",
                    value: button.url || button.phone_number || (button.example && button.example[0]) || ""
                };
            })
        };
    }

    /* ── Media upload ──────────────────────────────────────────────── */

    async function uploadMedia(file) {
        if (!file) return;
        builderError("");

        var title = $("mt-media-drop-title");
        var original = title.textContent;
        title.textContent = "Uploading " + file.name + "...";
        $("mt-media-drop").disabled = true;

        try {
            var form = new FormData();
            form.append("media_file", file);
            var result = await api("/api/media-attachments/upload?chatbot_id=" + encodeURIComponent(botId), {
                method: "POST",
                body: form
            });
            if (!result.ok) {
                builderError(result.body.message || "That file could not be uploaded.");
                return;
            }
            state.builder.mediaUrl = (result.body.data && result.body.data.public_url) || "";
            $("mt-media-url").value = state.builder.mediaUrl;
            announce("File uploaded.");
            refreshPreview();
        } finally {
            title.textContent = original;
            $("mt-media-drop").disabled = false;
            $("mt-media-input").value = "";
        }
    }

    /* ── Submit ────────────────────────────────────────────────────── */

    function buildComponents() {
        var builder = state.builder;
        var components = [];

        if (builder.headerType === "TEXT" && builder.headerText.trim()) {
            components.push({ type: "HEADER", format: "TEXT", text: builder.headerText.trim() });
        } else if (MEDIA_ACCEPT[builder.headerType]) {
            var header = { type: "HEADER", format: builder.headerType };
            if (builder.mediaUrl.trim()) header.example = { header_url: [builder.mediaUrl.trim()] };
            components.push(header);
        }

        var body = { type: "BODY", text: builder.body.trim() };
        var tokens = builder.body.match(/\{\{(\d+)\}\}/g);
        if (tokens) {
            var unique = [];
            tokens.forEach(function (token) {
                if (unique.indexOf(token) === -1) unique.push(token);
            });
            body.example = {
                body_text: [unique.map(function (token) {
                    return "Sample_" + token.replace(/[{}]/g, "");
                })]
            };
        }
        components.push(body);

        if (builder.footer.trim()) {
            components.push({ type: "FOOTER", text: builder.footer.trim() });
        }

        var buttons = builder.buttons.filter(function (button) {
            return button.text.trim();
        }).map(function (button) {
            var payload = { type: button.type, text: button.text.trim() };
            if (button.type === "URL") payload.url = button.value.trim();
            else if (button.type === "PHONE_NUMBER") payload.phone_number = button.value.trim();
            else if (button.type === "COPY_CODE") payload.example = [button.value.trim()];
            return payload;
        });
        if (buttons.length) components.push({ type: "BUTTONS", buttons: buttons });

        return components;
    }

    async function submitTemplate() {
        if (state.busy) return;
        state.busy = true;
        $("mt-submit").disabled = true;
        $("mt-submit").textContent = "Sending...";
        builderError("");

        var result = await api(withBot("/api/meta-templates"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: state.builder.name,
                language: state.builder.language,
                category: state.builder.category,
                components: buildComponents()
            })
        });

        state.busy = false;
        $("mt-submit").disabled = false;
        $("mt-submit").textContent = "Send to Meta for approval";

        if (!result.ok) {
            builderError(result.body.message || "Meta would not accept this template.");
            return;
        }

        notice("Sent to Meta. It shows as waiting until they answer, usually within minutes.");
        showScreen("library");
        await loadTemplates();
    }

    /* ══════════════════════════ CONFIRM ══════════════════════════ */

    function askConfirm(title, body, action) {
        $("mt-confirm-title").textContent = title;
        $("mt-confirm-body").textContent = body;
        state.confirmAction = action;
        kwDialog.open($("mt-confirm"), $("mt-confirm-cancel"));
    }

    function closeConfirm() {
        kwDialog.close($("mt-confirm"));
        state.confirmAction = null;
    }

    async function deleteTemplate(name) {
        var result = await api(withBot("/api/meta-templates/" + encodeURIComponent(name)), { method: "DELETE" });
        if (!result.ok) {
            pageError(result.body.message || "We could not delete that template.");
            return;
        }
        notice("Deleted " + name + ".");
        await loadTemplates();
    }

    /* ══════════════════════════ STARTERS ══════════════════════════ */

    function renderStarters() {
        $("mt-starters-list").innerHTML = STARTERS.map(function (starter, index) {
            return '<button type="button" class="mt-starter" data-index="' + index + '">'
                + "<strong>" + esc(starter.title) + "</strong>"
                + "<span>" + esc(starter.blurb) + "</span>"
                + "</button>";
        }).join("");
    }

    function openStarters() {
        kwDialog.open($("mt-starters"), $("mt-starters-close"));
    }

    function closeStarters() {
        kwDialog.close($("mt-starters"));
    }

    function useStarter(index) {
        var starter = STARTERS[index];
        if (!starter) return;
        closeStarters();
        openBuilder({
            name: nameIsTaken(starter.name) ? sanitizeName(starter.name + "_2") : starter.name,
            category: starter.category,
            headerType: starter.headerType,
            headerText: starter.headerText,
            body: starter.body,
            footer: starter.footer,
            buttons: starter.buttons.map(function (button) {
                return { type: button.type, text: button.text, value: button.value };
            })
        });
        announce("Loaded the " + starter.title + " example. Change the wording, then submit.");
    }

    /* ══════════════════════════ WIRING ══════════════════════════ */

    function wireLibrary() {
        $("mt-new").addEventListener("click", function () { openBuilder(null); });
        $("mt-empty-action").addEventListener("click", function () { openBuilder(null); });
        $("mt-empty-starters").addEventListener("click", function () {
            openBuilder(null);
            openStarters();
        });
        $("mt-search").addEventListener("input", renderGrid);
        $("mt-filter-category").addEventListener("change", renderGrid);

        $("mt-toolbar").addEventListener("click", function (event) {
            var chip = event.target.closest(".kw-chip[data-status]");
            if (!chip) return;
            var status = chip.getAttribute("data-status");
            state.statusFilter = state.statusFilter === status ? "" : status;
            Array.prototype.forEach.call($("mt-toolbar").querySelectorAll(".kw-chip[data-status]"), function (other) {
                other.setAttribute("aria-pressed",
                    other.getAttribute("data-status") === state.statusFilter ? "true" : "false");
            });
            renderGrid();
        });

        $("mt-grid").addEventListener("click", function (event) {
            var button = event.target.closest("button[data-act]");
            if (!button) return;
            var name = button.getAttribute("data-name");
            var template = templateByName(name);
            if (!template) return;

            var act = button.getAttribute("data-act");
            if (act === "use") {
                window.location.href = "broadcast.html?bot_id=" + encodeURIComponent(botId);
                return;
            }
            if (act === "duplicate") {
                openBuilder(duplicateOf(template));
                announce("Copied " + name + ". Give it a new name, then submit.");
                return;
            }
            if (act === "delete") {
                askConfirm(
                    "Delete this template?",
                    name + " is removed from Meta permanently. Any campaign still naming it will stop working.",
                    function () { deleteTemplate(name); }
                );
            }
        });
    }

    function wireBuilder() {
        $("mt-builder-back").addEventListener("click", function () {
            showScreen("library");
            loadTemplates();
        });
        $("mt-next").addEventListener("click", function () {
            var blocker = stepBlocker();
            if (blocker) {
                builderError(blocker);
                return;
            }
            builderError("");
            setStep(state.step + 1);
        });
        $("mt-prev").addEventListener("click", function () { setStep(state.step - 1); });
        $("mt-submit").addEventListener("click", submitTemplate);

        $("mt-name").addEventListener("input", function (event) {
            var caret = event.target.selectionStart;
            event.target.value = sanitizeName(event.target.value);
            event.target.selectionStart = event.target.selectionEnd = caret;
            state.builder.name = event.target.value;
            updateBottombar();
        });
        $("mt-language").addEventListener("change", function (event) {
            state.builder.language = event.target.value;
        });
        $("mt-category").addEventListener("change", function (event) {
            state.builder.category = event.target.value;
            $("mt-category-help").textContent = CATEGORY_HELP[event.target.value];
        });

        $("mt-header-type").addEventListener("click", function (event) {
            var button = event.target.closest("button[data-header]");
            if (button) setHeaderType(button.getAttribute("data-header"));
        });
        $("mt-header-text").addEventListener("input", function (event) {
            state.builder.headerText = event.target.value;
            refreshPreview();
        });
        $("mt-media-url").addEventListener("input", function (event) {
            state.builder.mediaUrl = event.target.value;
            refreshPreview();
        });
        $("mt-media-drop").addEventListener("click", function () { $("mt-media-input").click(); });
        $("mt-media-input").addEventListener("change", function (event) { uploadMedia(event.target.files[0]); });
        ["dragenter", "dragover", "dragleave", "drop"].forEach(function (name) {
            $("mt-media-drop").addEventListener(name, function (event) {
                event.preventDefault();
                event.stopPropagation();
            });
        });
        $("mt-media-drop").addEventListener("drop", function (event) {
            uploadMedia(event.dataTransfer.files[0]);
        });

        $("mt-body").addEventListener("input", function (event) {
            state.builder.body = event.target.value;
            refreshPreview();
        });
        $("mt-footer").addEventListener("input", function (event) {
            state.builder.footer = event.target.value;
            refreshPreview();
        });
        $("mt-body-inserts").addEventListener("click", function (event) {
            var button = event.target.closest(".mt-insert");
            if (button) insertIntoBody(button.getAttribute("data-text"));
        });

        $("mt-add-button").addEventListener("click", function () {
            if (state.builder.buttons.length >= MAX_BUTTONS) return;
            state.builder.buttons.push({ type: "QUICK_REPLY", text: "", value: "" });
            renderButtons();
            refreshPreview();
            var last = $("mt-buttons").querySelector('.mt-button-row:last-child [data-part="text"]');
            if (last) last.focus();
        });

        $("mt-buttons").addEventListener("input", onButtonFieldChange);
        $("mt-buttons").addEventListener("change", onButtonFieldChange);
        $("mt-buttons").addEventListener("click", function (event) {
            var remove = event.target.closest('[data-part="remove"]');
            if (!remove) return;
            var row = remove.closest(".mt-button-row");
            state.builder.buttons.splice(Number(row.getAttribute("data-index")), 1);
            renderButtons();
            refreshPreview();
        });
    }

    function onButtonFieldChange(event) {
        var field = event.target.closest("[data-part]");
        if (!field) return;
        var row = field.closest(".mt-button-row");
        if (!row) return;

        var button = state.builder.buttons[Number(row.getAttribute("data-index"))];
        if (!button) return;

        var part = field.getAttribute("data-part");
        if (part === "type") {
            button.type = field.value;
            // A destination only means something for the type that asked for
            // it, so switching type clears it rather than carrying a URL into
            // a phone-number field.
            button.value = "";
            renderButtons();
        } else if (part === "text") {
            button.text = field.value;
        } else if (part === "value") {
            button.value = field.value;
        }
        refreshPreview();
    }

    function wireModals() {
        $("mt-starters-open").addEventListener("click", openStarters);
        $("mt-starters-close").addEventListener("click", closeStarters);
        $("mt-starters").addEventListener("click", function (event) {
            if (event.target === event.currentTarget) closeStarters();
        });
        $("mt-starters-list").addEventListener("click", function (event) {
            var starter = event.target.closest(".mt-starter");
            if (starter) useStarter(Number(starter.getAttribute("data-index")));
        });

        $("mt-confirm-cancel").addEventListener("click", closeConfirm);
        $("mt-confirm-ok").addEventListener("click", function () {
            var action = state.confirmAction;
            closeConfirm();
            if (action) action();
        });
        $("mt-confirm").addEventListener("click", function (event) {
            if (event.target === event.currentTarget) closeConfirm();
        });

        document.addEventListener("keydown", function (event) {
            if (event.key !== "Escape") return;
            if (kwDialog.isOpen($("mt-starters"))) {
                closeStarters();
                return;
            }
            if (kwDialog.isOpen($("mt-confirm"))) closeConfirm();
        });
    }

    /* ══════════════════════════ BOOT ══════════════════════════ */

    (async function boot() {
        showScreen("library");
        state.builder = blankBuilder();

        if (!botId) {
            show($("mt-loading"), false);
            pageError("Pick a bot first. Open this page from the bot whose templates you want to manage.");
            show($("mt-new"), false);
            return;
        }

        // Arrow keys for every .kw-segment on the page. Without this the
        // roving tabindex leaves a keyboard user stuck on one option.
        kwRadioGroup(document);

        renderStarters();
        renderInserts();
        wireLibrary();
        wireBuilder();
        wireModals();

        await loadTemplates();
    })();
})();
