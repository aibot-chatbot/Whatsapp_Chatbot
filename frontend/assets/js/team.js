/* ══════════════════════════════════════════════════════════════════════
   TEAM — roster and seat entitlement

   Seat rules mirror the server exactly, because the server is what
   actually enforces them:
     - a null plan_member_limit means unlimited and never blocks;
     - a pending invitation holds a seat, so the check is
       (active + pending) >= limit, not active >= limit;
     - the check is skipped entirely until entitlement has loaded, so a
       slow /api/workspace never produces a false "limit reached".

   Reads are open to every role; every mutation is admin/owner only. The UI
   mirrors that rather than hiding the page from members.

   All seat figures come from /api/workspace. /api/billing/usage also
   reports team_members, but the two count pending invitations differently
   (workspace excludes invites with an unparseable expiry, billing includes
   them), so this screen picks one source and stays with it.
   ══════════════════════════════════════════════════════════════════════ */

(function () {
    "use strict";

    var LIMIT_MESSAGE =
        "Team limit reached. Remove a member, cancel an invitation, or upgrade your plan.";

    var ICON_PATHS = {
        check: "m20 6-11 11-5-5",
        alert: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
        resend: "M17 2.1 21 6l-4 3.9M3 11v-1a4 4 0 0 1 4-4h14M7 21.9 3 18l4-3.9M21 13v1a4 4 0 0 1-4 4H3",
        cancel: "M18 6 6 18M6 6l12 12",
        userOff: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM17 8l5 5m0-5-5 5",
        userOn: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM16 11l2 2 4-4",
        mail: "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM22 7l-10 6L2 7",
        plus: "M12 5v14M5 12h14"
    };

    var state = {
        users: [],
        invites: [],
        role: null,
        userId: null,
        canManage: false,
        canEditCompany: false,
        entitlement: { loaded: false, used: 0, pending: 0, limit: null }
    };

    var resendInFlight = Object.create(null);

    /* ── helpers ───────────────────────────────────────────────────── */

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

    function titleCase(value) {
        var s = String(value || "");
        return s.charAt(0).toUpperCase() + s.slice(1);
    }

    /* Locale-aware, rather than the hardcoded en-US the old page used. */
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

    /* Whole days from now, negative once past. Invite expiry is derived
       from expires_at because the backend only ever writes the statuses
       "pending" and "accepted" — there is no stored "expired" state. */
    function daysUntil(value) {
        if (!value) return null;
        var d = new Date(value);
        if (isNaN(d.getTime())) return null;
        return Math.ceil((d.getTime() - Date.now()) / 86400000);
    }

    function initialsOf(name, email) {
        var source = String(name || email || "?").trim();
        var parts = source.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) return parts[0][0] + parts[1][0];
        return source.slice(0, 2);
    }

    function asObject(value) {
        if (!value || typeof value !== "object" || Array.isArray(value)) return null;
        return value;
    }

    function announce(message) {
        var node = $("tm-announce");
        if (node) node.textContent = message;
    }

    function showBanner(message, kind) {
        var banner = $("tm-banner");
        var text = $("tm-banner-text");
        if (!banner || !text) return;
        banner.className = "kw-banner " +
            (kind === "success" ? "kw-banner-success" : "kw-banner-error");
        text.textContent = message;
        banner.hidden = false;
        announce(message);
    }

    function clearBanner() {
        var banner = $("tm-banner");
        if (banner) banner.hidden = true;
    }

    /* The three 403 shapes the API returns are genuinely different
       problems, and telling them apart is the difference between "ask an
       admin", "contact support" and "upgrade". */
    function messageFor(body, fallback) {
        if (!body) return fallback;
        if (body.code === "company_suspended") {
            return "This workspace is suspended. Contact support to reactivate it.";
        }
        if (body.code === "team_member_limit") return LIMIT_MESSAGE;
        if (body.code === "no_subscription" || body.code === "usage_unavailable") {
            return "Your subscription is not active, so team changes are paused.";
        }
        return body.message || fallback;
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

    /* ── entitlement ───────────────────────────────────────────────── */

    function isLimitReached() {
        var e = state.entitlement;
        /* Unknown entitlement and unlimited plans both mean "do not block".
           Guessing here would lock an owner out of their own team. */
        if (!e.loaded || e.limit === null) return false;
        return (e.used + e.pending) >= e.limit;
    }

    function applyInviteLimitState() {
        var btn = $("tm-invite");
        if (!btn) return;
        var reached = isLimitReached();
        btn.hidden = !state.canManage;
        btn.disabled = !state.canManage || !state.entitlement.loaded || reached;
        btn.title = reached
            ? LIMIT_MESSAGE
            : (state.entitlement.loaded
                ? "Invite someone to this workspace"
                : "Checking your plan");
    }

    /* ── seat rail ─────────────────────────────────────────────────── */

    function renderSeats() {
        var host = $("tm-seats");
        if (!host) return;
        var e = state.entitlement;
        host.replaceChildren();

        if (!e.loaded) {
            host.appendChild(el("div", "cr-skeleton team-skeleton-row"));
            return;
        }

        var taken = e.used + e.pending;
        var unlimited = e.limit === null;

        var figure = el("div", "team-seats-figure");
        var used = el("span", "team-seats-used cr-countup", String(taken));
        used.setAttribute("data-countup", String(taken));
        figure.appendChild(used);
        figure.appendChild(el("span", "team-seats-limit",
            unlimited ? "seats in use" : "of " + e.limit + " seats"));
        host.appendChild(figure);

        if (!unlimited) {
            var wrap = el("div", "team-seats-meter cr-meter");
            wrap.setAttribute("aria-hidden", "true");
            var fill = el("div", "cr-meter-fill");
            var ratio = e.limit > 0 ? Math.min(taken / e.limit, 1) : 1;
            fill.style.setProperty("--cr-meter-value", String(ratio));
            if (taken >= e.limit) fill.classList.add("is-full");
            else if (ratio >= 0.8) fill.classList.add("is-warn");
            wrap.appendChild(fill);
            host.appendChild(wrap);
        }

        var remaining = unlimited ? null : Math.max(e.limit - taken, 0);
        var note = el("p", "team-seats-note");
        if (unlimited) {
            note.textContent = "Your plan has no seat limit.";
        } else if (remaining === 0) {
            note.className = "team-seats-note is-warn";
            note.textContent = LIMIT_MESSAGE;
        } else {
            note.textContent = remaining + " " + (remaining === 1 ? "seat" : "seats") +
                " left. A pending invitation holds a seat until it is accepted or cancelled.";
        }
        host.appendChild(note);

        var list = el("dl", "team-breakdown");
        [
            ["Active members", e.used],
            ["Pending invitations", e.pending],
            ["Plan limit", unlimited ? "Unlimited" : e.limit]
        ].forEach(function (pair) {
            var row = el("div", "team-breakdown-row");
            row.appendChild(el("dt", null, pair[0]));
            row.appendChild(el("dd", null, String(pair[1])));
            list.appendChild(row);
        });
        host.appendChild(list);

        var upgrade = $("tm-upgrade");
        if (upgrade) upgrade.hidden = unlimited || remaining > 0;
    }

    /* ── roster ────────────────────────────────────────────────────── */

    function roleBadge(role) {
        var normalized = String(role || "").trim().toLowerCase();
        var pill = el("span", "kw-pill" +
            ((normalized === "owner" || normalized === "admin") ? " kw-pill-ready" : ""));
        pill.appendChild(document.createTextNode(titleCase(normalized || "member")));
        return pill;
    }

    function memberRow(user) {
        var normalizedRole = String(user.role || "").trim().toLowerCase();
        var isSelf = state.userId !== null && user.id === state.userId;
        var isOwner = normalizedRole === "owner";

        var tr = document.createElement("tr");

        var tdPerson = document.createElement("td");
        var person = el("div", "team-person");
        var initials = el("span", "team-initials" + (isSelf ? " is-you" : ""),
            initialsOf(user.full_name, user.email));
        initials.setAttribute("aria-hidden", "true");
        person.appendChild(initials);
        var text = el("div", "team-person-text");
        var nameLine = el("span", "team-name");
        nameLine.appendChild(document.createTextNode(user.full_name || "Unknown"));
        if (isSelf) nameLine.appendChild(el("span", "team-you", "You"));
        /* Verification is only worth a word when it is MISSING. Printing
           "Verified" on every normal row cost a whole column and pushed the
           row actions into horizontal scroll. */
        if (!user.is_verified) {
            var warn = el("span", "team-verify is-no");
            warn.appendChild(icon("alert", 12));
            warn.appendChild(document.createTextNode("Not verified"));
            nameLine.appendChild(warn);
        }
        text.appendChild(nameLine);
        text.appendChild(el("span", "team-email", user.email || "—"));
        person.appendChild(text);
        tdPerson.appendChild(person);
        tr.appendChild(tdPerson);

        var tdRole = document.createElement("td");
        tdRole.appendChild(roleBadge(user.role));
        tr.appendChild(tdRole);

        var tdStatus = document.createElement("td");
        var active = user.status === "active";
        var pill = el("span", "kw-pill " + (active ? "kw-pill-ready" : "kw-pill-off"));
        var dot = el("span", "kw-dot " + (active ? "kw-dot-ready" : "kw-dot-off"));
        dot.setAttribute("aria-hidden", "true");
        pill.appendChild(dot);
        pill.appendChild(document.createTextNode(titleCase(user.status || "unknown")));
        tdStatus.appendChild(pill);
        tr.appendChild(tdStatus);

        var tdJoined = document.createElement("td");
        tdJoined.appendChild(el("span", "team-date", formatDate(user.created_at)));
        tr.appendChild(tdJoined);

        /* The server refuses to change an owner, yourself, or the last
           remaining admin. The first two are hidden outright; the third
           surfaces as an error if it happens. */
        var tdActions = document.createElement("td");
        if (state.canManage && !isSelf && !isOwner) {
            var actions = el("div", "kw-actions");

            var select = el("select", "kw-select team-role-select");
            select.setAttribute("aria-label",
                "Role for " + (user.full_name || "this member"));
            [["member", "Member"], ["admin", "Admin"]].forEach(function (pair) {
                var option = el("option", null, pair[1]);
                option.value = pair[0];
                if (normalizedRole === pair[0]) option.selected = true;
                select.appendChild(option);
            });
            select.addEventListener("change", function () { changeRole(user, select); });
            actions.appendChild(select);

            var toggle = el("button",
                "kw-action cr-press" + (active ? " kw-action-danger" : ""));
            toggle.type = "button";
            toggle.appendChild(icon(active ? "userOff" : "userOn", 14));
            toggle.appendChild(document.createTextNode(active ? " Deactivate" : " Reactivate"));
            toggle.setAttribute("aria-label",
                (active ? "Deactivate " : "Reactivate ") + (user.full_name || "member"));
            toggle.addEventListener("click", function () {
                changeStatus(user, active ? "inactive" : "active");
            });
            actions.appendChild(toggle);

            tdActions.appendChild(actions);
        }
        tr.appendChild(tdActions);

        return tr;
    }

    function renderRoster() {
        var body = $("tm-tbody");
        var empty = $("tm-empty");
        var wrap = $("tm-table-wrap");
        var loading = $("tm-loading");
        if (!body) return;

        if (loading) loading.hidden = true;
        body.replaceChildren();

        if (!state.users.length) {
            if (wrap) wrap.hidden = true;
            if (empty) empty.hidden = false;
            return;
        }

        if (empty) empty.hidden = true;
        if (wrap) wrap.hidden = false;
        state.users.forEach(function (user) { body.appendChild(memberRow(user)); });

        var count = $("tm-count");
        if (count) {
            count.textContent = state.users.length + " " +
                (state.users.length === 1 ? "member" : "members");
        }
    }

    /* ── invitations ───────────────────────────────────────────────── */

    function inviteRow(invite) {
        var id = Number(invite.id);
        var row = el("div", "team-invite-row");

        var email = el("div", "team-invite-email");
        email.appendChild(icon("mail", 14));
        email.appendChild(document.createTextNode(" " + (invite.email || "—")));
        row.appendChild(email);

        row.appendChild(roleBadge(invite.role));

        var left = daysUntil(invite.expires_at);
        var meta = el("div", "team-invite-meta");
        if (left === null) meta.textContent = "No expiry set";
        else if (left <= 0) meta.textContent = "Expired";
        else meta.textContent = left + (left === 1 ? " day left" : " days left");
        row.appendChild(meta);

        if (state.canManage && Number.isInteger(id) && id > 0) {
            var actions = el("div", "team-invite-actions");

            var resend = el("button", "kw-action cr-press");
            resend.type = "button";
            resend.dataset.inviteId = String(id);
            resend.appendChild(icon("resend", 13));
            resend.appendChild(document.createTextNode(" Resend"));
            resend.setAttribute("aria-label",
                "Resend invitation to " + (invite.email || ""));
            resend.addEventListener("click", function () { resendInvite(id, resend); });
            actions.appendChild(resend);

            var cancel = el("button", "kw-action kw-action-danger cr-press");
            cancel.type = "button";
            cancel.appendChild(icon("cancel", 13));
            cancel.appendChild(document.createTextNode(" Cancel"));
            cancel.setAttribute("aria-label",
                "Cancel invitation to " + (invite.email || ""));
            cancel.addEventListener("click", function () { cancelInvite(id); });
            actions.appendChild(cancel);

            row.appendChild(actions);
        }

        return row;
    }

    function renderInvites() {
        var host = $("tm-invites");
        var empty = $("tm-invites-empty");
        var loading = $("tm-invites-loading");
        if (!host) return;

        if (loading) loading.hidden = true;
        host.replaceChildren();

        if (!state.invites.length) {
            if (empty) empty.hidden = false;
            return;
        }
        if (empty) empty.hidden = true;
        state.invites.forEach(function (invite) { host.appendChild(inviteRow(invite)); });
    }

    /* ── company information ───────────────────────────────────────────

       Moved off the profile page, which is personal-only now. It costs no
       extra request: loadAll() already reads /api/workspace, and that payload
       carries the company record and can_edit_company together.

       The three states are the panel's own. The skeleton is the markup's
       starting state rather than something re-applied on every reload, so a
       roster mutation does not flash this panel back to loading — exactly how
       #tm-loading behaves for the roster. */

    var COMPANY_FIELDS = [
        ["tm-company-name", "name"],
        ["tm-company-email", "contact_email"],
        ["tm-company-phone", "contact_phone"]
    ];

    function setCompanyPhase(phase) {
        var nodes = {
            loading: $("tm-company-loading"),
            error: $("tm-company-error"),
            ready: $("tm-company-form")
        };
        Object.keys(nodes).forEach(function (key) {
            if (nodes[key]) nodes[key].hidden = key !== phase;
        });
    }

    /* One message node shared by the two validated fields, mirroring the
       invite dialog. aria-invalid marks only the field at fault. */
    function setCompanyError(message, fieldId) {
        var node = $("tm-company-note");
        if (node) {
            node.textContent = message || "";
            node.hidden = !message;
        }
        COMPANY_FIELDS.forEach(function (pair) {
            var input = $(pair[0]);
            if (input) {
                input.setAttribute("aria-invalid",
                    (message && pair[0] === fieldId) ? "true" : "false");
            }
        });
        if (message && fieldId && $(fieldId)) $(fieldId).focus();
    }

    function renderCompany(workspace) {
        var company = asObject(workspace && workspace.company) || {};
        /* can_edit_company, not can_manage_team: the server computes them the
           same way today, but this endpoint is guarded by the former. */
        state.canEditCompany = !!(workspace && workspace.can_edit_company === true);

        COMPANY_FIELDS.forEach(function (pair) {
            var input = $(pair[0]);
            if (!input) return;
            input.value = company[pair[1]] || "";
            /* readonly, not disabled. A disabled input leaves the tab order
               and goes unread, so a member could not review the value they
               are being shown; readonly stays focusable and is announced as
               read-only. Neither is a control — see saveCompany(). */
            input.readOnly = !state.canEditCompany;
            input.setAttribute("aria-readonly", state.canEditCompany ? "false" : "true");
        });

        var note = $("tm-company-readonly-note");
        if (note) note.hidden = state.canEditCompany;

        var save = $("tm-company-save");
        if (save) {
            save.hidden = !state.canEditCompany;
            save.disabled = !state.canEditCompany;
        }

        setCompanyError("");
        setCompanyPhase("ready");
    }

    async function saveCompany() {
        /* The disabled button and the readonly inputs are affordances, not
           the control. This guard stops a re-enabled DOM, and the server
           answers a non-admin PUT with 403 whatever the DOM says. */
        if (!state.canEditCompany) return;

        var name = String($("tm-company-name").value || "").trim();
        var email = String($("tm-company-email").value || "").trim().toLowerCase();
        var phone = String($("tm-company-phone").value || "").trim();

        /* Mirrors app/services/workspace_service.py so the reader is told
           before the round trip, never instead of it. */
        if (!name) {
            setCompanyError("Company name is required.", "tm-company-name");
            return;
        }
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            setCompanyError("Please enter a valid company contact email.", "tm-company-email");
            return;
        }
        setCompanyError("");

        var button = $("tm-company-save");
        if (button) button.disabled = true;

        try {
            var res = await authenticatedFetch("/api/workspace", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    company_name: name,
                    contact_email: email,
                    contact_phone: phone
                })
            });
            var body = await res.json();
            if (body && body.status === "success") {
                /* Reload first, announce after, like every other mutation
                   here: loadAll() opens with clearBanner(). It also re-reads
                   the stored record, so the fields end up showing what the
                   server actually kept after trimming and lowercasing, not
                   what was typed. */
                var message = body.message || "Company information updated successfully.";
                await loadAll();
                showBanner(message, "success");
            } else {
                showBanner(messageFor(body, "Unable to update company information."), "error");
            }
        } catch (_) {
            showBanner("We could not reach the server. Check your connection and try again.", "error");
        }

        if (button) button.disabled = !state.canEditCompany;
    }

    /* ── mutations ─────────────────────────────────────────────────────

       Every success path reloads FIRST and raises the banner afterwards.
       loadAll() opens with clearBanner(), so a message raised before the
       reload is wiped before anyone can read it. */

    async function changeRole(user, select) {
        var next = select.value;
        var confirmed = await confirmAction({
            title: "Change role to " + titleCase(next) + "?",
            body: (user.full_name || "This member") + " will have " +
                (next === "admin"
                    ? "full access to the team, billing and bot settings."
                    : "standard access and can no longer manage the team."),
            confirm: "Change role"
        });
        if (!confirmed) {
            /* Restore the control: a select left showing an unconfirmed
               value is lying about server state. */
            renderRoster();
            return;
        }

        try {
            var res = await authenticatedFetch("/api/users/" + user.id + "/role", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ role: next })
            });
            var body = await res.json();
            if (body && body.status === "success") {
                await loadAll();
                showBanner("Role updated to " + titleCase(next) + ".", "success");
            } else {
                showBanner(messageFor(body, "We could not update that role."), "error");
                renderRoster();
            }
        } catch (_) {
            showBanner("We could not reach the server. Check your connection and try again.", "error");
            renderRoster();
        }
    }

    async function changeStatus(user, next) {
        var deactivating = next === "inactive";
        var confirmed = await confirmAction({
            title: (deactivating ? "Deactivate " : "Reactivate ") +
                (user.full_name || "this member") + "?",
            body: deactivating
                ? "They will be signed out and cannot log in until reactivated. Nothing they created is deleted."
                : "They will be able to log in again. This takes up a seat on your plan.",
            confirm: deactivating ? "Deactivate" : "Reactivate",
            danger: deactivating
        });
        if (!confirmed) return;

        try {
            var res = await authenticatedFetch("/api/users/" + user.id + "/status", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: next })
            });
            var body = await res.json();
            if (body && body.status === "success") {
                await loadAll();
                showBanner(
                    deactivating ? "Member deactivated." : "Member reactivated.", "success");
            } else {
                showBanner(messageFor(body, "We could not update that member."), "error");
            }
        } catch (_) {
            showBanner("We could not reach the server. Check your connection and try again.", "error");
        }
    }

    async function resendInvite(inviteId, button) {
        var id = Number(inviteId);
        if (!Number.isInteger(id) || id <= 0) {
            showBanner("We could not resend that invitation.", "error");
            return;
        }
        /* Double-submit guard: the endpoint rotates the token, so a second
           in-flight resend would invalidate the link the first one sent. */
        var key = String(id);
        if (resendInFlight[key]) return;
        resendInFlight[key] = true;
        if (button) button.disabled = true;

        try {
            var res = await authenticatedFetch("/api/invites/resend", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ invite_id: id })
            });
            var body = await res.json();
            if (body && body.status === "success") {
                await loadAll();
                showBanner("Invitation resent. The previous link no longer works.", "success");
            } else {
                showBanner(messageFor(body, "We could not resend that invitation."), "error");
            }
        } catch (_) {
            showBanner("We could not reach the server. Check your connection and try again.", "error");
        } finally {
            delete resendInFlight[key];
            if (button && button.isConnected) button.disabled = false;
        }
    }

    async function cancelInvite(inviteId) {
        var confirmed = await confirmAction({
            title: "Cancel this invitation?",
            body: "The invite link stops working immediately and the seat is released.",
            confirm: "Cancel invitation",
            danger: true
        });
        if (!confirmed) return;

        try {
            var res = await authenticatedFetch("/api/invites/" + inviteId, { method: "DELETE" });
            var body = await res.json();
            if (body && body.status === "success") {
                await loadAll();
                showBanner("Invitation cancelled.", "success");
            } else {
                showBanner(messageFor(body, "We could not cancel that invitation."), "error");
            }
        } catch (_) {
            showBanner("We could not reach the server. Check your connection and try again.", "error");
        }
    }

    /* ── invite dialog ─────────────────────────────────────────────── */

    function openInvite() {
        if (!state.canManage) {
            showBanner("Only admins and owners can invite people.", "error");
            return;
        }
        if (!state.entitlement.loaded) {
            showBanner("Still checking your plan. Try again in a moment.", "error");
            return;
        }
        if (isLimitReached()) {
            showBanner(LIMIT_MESSAGE, "error");
            applyInviteLimitState();
            return;
        }
        $("tm-invite-email").value = "";
        $("tm-invite-role").value = "member";
        setFieldError("");
        window.kwDialog.open($("tm-invite-modal"), $("tm-invite-email"));
    }

    function closeInvite() {
        var backdrop = $("tm-invite-modal");
        if (backdrop && window.kwDialog.isOpen(backdrop)) window.kwDialog.close(backdrop);
    }

    function setFieldError(message) {
        var node = $("tm-invite-error");
        if (!node) return;
        node.textContent = message || "";
        node.hidden = !message;
        var input = $("tm-invite-email");
        if (input) input.setAttribute("aria-invalid", message ? "true" : "false");
    }

    async function submitInvite() {
        if (!state.canManage) {
            setFieldError("Only admins and owners can invite people.");
            return;
        }
        if (!state.entitlement.loaded) {
            setFieldError("Still checking your plan. Try again in a moment.");
            return;
        }
        if (isLimitReached()) {
            setFieldError(LIMIT_MESSAGE);
            applyInviteLimitState();
            return;
        }

        var email = String($("tm-invite-email").value || "").trim();
        var role = $("tm-invite-role").value;

        /* The server enforces non-empty only, so format validation genuinely
           has to happen here rather than being assumed. */
        if (!email) {
            setFieldError("Enter an email address.");
            $("tm-invite-email").focus();
            return;
        }
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            setFieldError("That does not look like an email address.");
            $("tm-invite-email").focus();
            return;
        }

        var submit = $("tm-invite-submit");
        submit.disabled = true;
        setFieldError("");

        try {
            var res = await authenticatedFetch("/api/invites", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: email, role: role })
            });
            var body = await res.json();
            if (body && body.status === "success") {
                closeInvite();
                await loadAll();
                showBanner("Invitation sent to " + email + ".", "success");
            } else {
                setFieldError(messageFor(body, "We could not send that invitation."));
            }
        } catch (_) {
            setFieldError("We could not reach the server. Check your connection and try again.");
        }
        submit.disabled = false;
    }

    /* ── confirm dialog ────────────────────────────────────────────── */

    var confirmResolve = null;

    function confirmAction(options) {
        return new Promise(function (resolve) {
            confirmResolve = resolve;
            $("tm-confirm-title").textContent = options.title;
            $("tm-confirm-body").textContent = options.body;
            var ok = $("tm-confirm-ok");
            ok.textContent = options.confirm || "Confirm";
            ok.className = options.danger
                ? "kw-btn kw-btn-danger cr-press"
                : "kw-btn kw-btn-primary cr-press";
            /* Focus starts on Cancel, so Enter never commits a destructive
               change the reader has not taken in. */
            window.kwDialog.open($("tm-confirm"), $("tm-confirm-cancel"));
        });
    }

    function settleConfirm(result) {
        var backdrop = $("tm-confirm");
        if (backdrop && window.kwDialog.isOpen(backdrop)) window.kwDialog.close(backdrop);
        if (confirmResolve) {
            var resolve = confirmResolve;
            confirmResolve = null;
            resolve(result);
        }
    }

    /* ── boot ──────────────────────────────────────────────────────── */

    async function loadAll() {
        clearBanner();

        /* Three independent reads, issued together. /api/workspace already
           carries current_user_role and can_manage_team, so the separate
           /api/user round trip the old page made is not needed. */
        var results = await Promise.all([
            getJson("/api/workspace"),
            getJson("/api/users"),
            getJson("/api/invites?status=pending")
        ]);

        var workspace = asObject(results[0]);
        state.users = Array.isArray(results[1]) ? results[1] : [];
        state.invites = Array.isArray(results[2]) ? results[2] : [];

        if (workspace) {
            state.role = String(workspace.current_user_role || "").toLowerCase();
            state.canManage = workspace.can_manage_team === true;

            var limit = workspace.plan_member_limit;
            var numericLimit = (limit === null || limit === undefined) ? null : Number(limit);
            state.entitlement = {
                loaded: true,
                used: Number(workspace.active_member_count) || 0,
                pending: Number(workspace.pending_invitation_count) || 0,
                limit: (numericLimit !== null && isFinite(numericLimit)) ? numericLimit : null
            };
            renderCompany(workspace);
        } else {
            showBanner(
                "We could not load your workspace details. Some actions are unavailable.",
                "error"
            );
            setCompanyPhase("error");
        }

        var session = null;
        try { session = JSON.parse(sessionStorage.getItem("user") || "null"); } catch (_) {}
        state.userId = (session && session.id !== undefined) ? session.id : null;

        renderSeats();
        renderRoster();
        renderInvites();
        applyInviteLimitState();

        var readOnly = $("tm-readonly");
        if (readOnly) readOnly.hidden = state.canManage;

        if (window.controlRoomMotion) window.controlRoomMotion.countUpAll(document);
        if (typeof refreshIcons === "function") refreshIcons();
    }

    function wire() {
        $("tm-invite").addEventListener("click", openInvite);
        $("tm-invite-cancel").addEventListener("click", closeInvite);
        $("tm-invite-close").addEventListener("click", closeInvite);
        $("tm-invite-submit").addEventListener("click", submitInvite);
        $("tm-invite-form").addEventListener("submit", function (event) {
            event.preventDefault();
            submitInvite();
        });

        $("tm-company-form").addEventListener("submit", function (event) {
            event.preventDefault();
            saveCompany();
        });
        $("tm-company-retry").addEventListener("click", function () { loadAll(); });

        $("tm-confirm-cancel").addEventListener("click", function () { settleConfirm(false); });
        $("tm-confirm-close").addEventListener("click", function () { settleConfirm(false); });
        $("tm-confirm-ok").addEventListener("click", function () { settleConfirm(true); });

        [["tm-invite-modal", closeInvite],
         ["tm-confirm", function () { settleConfirm(false); }]].forEach(function (pair) {
            var node = $(pair[0]);
            if (!node) return;
            node.addEventListener("click", function (event) {
                if (event.target === event.currentTarget) pair[1]();
            });
        });

        var retry = $("tm-retry");
        if (retry) retry.addEventListener("click", function () { loadAll(); });

        /* kw-a11y supplies the focus trap and focus restore but not Escape,
           which every page wires for itself. Topmost dialog closes first. */
        document.addEventListener("keydown", function (event) {
            if (event.key !== "Escape") return;
            if (window.kwDialog.isOpen($("tm-confirm"))) { settleConfirm(false); return; }
            if (window.kwDialog.isOpen($("tm-invite-modal"))) closeInvite();
        });

        if (typeof window.kwRadioGroup === "function") window.kwRadioGroup(document);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { wire(); loadAll(); });
    } else {
        wire();
        loadAll();
    }
})();
