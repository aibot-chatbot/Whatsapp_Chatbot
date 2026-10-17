/* ══════════════════════════════════════════════════════════════════════
   PROFILE — personal account, security and workspace standing

   Reading order follows the question a signed-in person actually asks:
   "who am I here and how exposed am I?" -> "fix the exposure" -> "correct
   my details" -> "where do I sit in this workspace?" -> "browser prefs".

   No billing. Credits, invoices, orders, plans and top-ups all live on
   billing.html; nothing on this page reads /api/billing.

   Endpoints, all through authenticatedFetch:
     GET  /api/user           me (id, full_name, email, role, phone, and
                              since the widening: status, is_verified,
                              created_at, updated_at)
     PUT  /api/user           full_name, phone
     PUT  /api/user/password  current/new/confirm
     GET  /api/users          the company roster, one row per colleague
     GET  /api/workspace      role, member count, pending invites, seat limit
     GET  /api/user/account-deletion          may this person delete the workspace, or why not
     POST /api/user/account-deletion/code     email the owner a 6-digit confirmation code
     POST /api/user/account-deletion/confirm  { code } delete the workspace, for good

   The roster is the fallback for any account-standing field /api/user
   does not return: it has carried status, is_verified, created_at and
   updated_at for every member since before the widening, so an older
   backend degrades to correct data rather than to blanks.
   ══════════════════════════════════════════════════════════════════════ */

(function () {
    "use strict";

    /* Circumference of the r=33 donut in the shared 74x74 gauge. The
       stylesheet already rotates that svg -90deg; do not rotate it again. */
    var GAUGE_CIRCUMFERENCE = 207.35;

    /* The composition donut is a separate 108x108 component with r=44. */
    var DONUT_RADIUS = 44;
    var DONUT_CIRCUMFERENCE = 2 * Math.PI * DONUT_RADIUS;

    var ROLE_ORDER = ["owner", "admin", "member"];

    /* A privilege ramp of the one accent, not a decorative palette: the
       design system has no second hue to spend here, and the legend
       carries the role name and count so the colour is never the signal. */
    var ROLE_COLOURS = {
        owner: "var(--control-accent)",
        admin: "rgba(62, 156, 137, 0.55)",
        member: "rgba(255, 255, 255, 0.22)"
    };
    var ROLE_FALLBACK_COLOUR = "rgba(255, 255, 255, 0.13)";

    var ROLE_NOTES = {
        owner: "You own this workspace. Only you can transfer it.",
        admin: "You can invite people, change roles and edit company details.",
        member: "You can use the bots. Team management is handled by an admin."
    };

    /* Inline paths, so the page owns its own icons rather than waiting on a
       CDN. All use a 0 0 24 24 viewBox. */
    var ICON_PATHS = {
        check: "m20 6-11 11-5-5",
        alert: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
        shield: "M12 3 4 6v6c0 5 3.4 8.6 8 9.7 4.6-1.1 8-4.7 8-9.7V6z",
        eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7zM12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z",
        eyeOff: "M3 3l18 18M10.6 10.6a3 3 0 0 0 4.2 4.2M9.4 5.3A9.6 9.6 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4M6.2 6.6A17 17 0 0 0 2 12s3.6 7 10 7c1.4 0 2.6-.2 3.8-.7",
        dot: "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"
    };

    var state = {
        user: null,        // merged: /api/user, backfilled from the roster
        roster: null,      // array, or null when the read failed
        workspace: null,   // object, or null when the read failed
        strengthLevel: null,
        deleting: false    // true while the delete request is in flight
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
        path.setAttribute("d", ICON_PATHS[name] || ICON_PATHS.dot);
        svg.appendChild(path);
        return svg;
    }

    function svgEl(tag) {
        return document.createElementNS("http://www.w3.org/2000/svg", tag);
    }

    function show(node, visible) {
        if (node) node.hidden = !visible;
    }

    function asObject(value) {
        if (!value || typeof value !== "object" || Array.isArray(value)) return null;
        return value;
    }

    function trimmed(value) {
        return typeof value === "string" ? value.trim() : "";
    }

    function titleCase(value) {
        var s = String(value || "");
        return s.charAt(0).toUpperCase() + s.slice(1);
    }

    function pluralize(count, singular, plural) {
        return count === 1 ? singular : plural;
    }

    /* Dates follow the viewer's locale rather than a hardcoded en-US. */
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

    /* Calendar months rather than 30-day blocks, so "since 14 Mar" reads
       as a whole number of months on the 14th of every later month. */
    function tenureFrom(value) {
        if (!value) return null;
        var start = new Date(value);
        if (isNaN(start.getTime())) return null;

        var now = new Date();
        if (start > now) return null;

        var days = Math.floor((now - start) / 86400000);
        if (days < 1) return "today";
        if (days < 31) return days + " " + pluralize(days, "day", "days");

        var months = (now.getFullYear() - start.getFullYear()) * 12
            + (now.getMonth() - start.getMonth());
        if (now.getDate() < start.getDate()) months -= 1;
        if (months < 1) months = 1;

        if (months < 12) return months + " " + pluralize(months, "month", "months");

        var years = Math.floor(months / 12);
        var rest = months % 12;
        var text = years + " " + pluralize(years, "year", "years");
        if (rest > 0) text += " " + rest + " " + pluralize(rest, "month", "months");
        return text;
    }

    /* Two initials where a name gives two, one where it does not. Written
       with textContent, so a hostile name is text and never markup. */
    function initialsFor(name) {
        var parts = trimmed(name).split(/\s+/).filter(Boolean);
        if (!parts.length) return "?";
        if (parts.length === 1) return parts[0].charAt(0);
        return parts[0].charAt(0) + parts[parts.length - 1].charAt(0);
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

    function announce(message) {
        var node = $("pro-announce");
        if (node) node.textContent = message;
    }

    function showError(message) {
        var banner = $("pro-error");
        var text = $("pro-error-text");
        if (!banner || !text) return;
        text.textContent = message;
        banner.hidden = false;
        announce(message);
    }

    function clearError() {
        show($("pro-error"), false);
    }

    /* Inline result banner for a form. Never an alert(): a banner is
       styleable, announced, and does not block the main thread. */
    function setFormMessage(bannerId, textId, message, kind) {
        var banner = $(bannerId);
        var text = $(textId);
        if (!banner || !text) return;
        if (!message) {
            banner.hidden = true;
            return;
        }
        banner.className = "kw-banner " + (kind === "error" ? "kw-banner-error" : "kw-banner-success");
        text.textContent = message;
        banner.hidden = false;
        announce(message);
    }

    /* ── security posture ──────────────────────────────────────────── */

    // Security posture scoring.
    // The user owns this maths — these are defaults, marked for their review.
    // Signals available today (no schema change): email verified, recovery phone on
    // file, display name set, account active.
    function computeSecurityPosture(user) {
        var signals = [
            { key: 'verified', label: 'Email address verified',   met: !!user.is_verified,                 fix: null },
            { key: 'phone',    label: 'Recovery phone on file',   met: !!(user.phone && user.phone.trim()), fix: '#profile-phone' },
            { key: 'name',     label: 'Display name set',         met: !!(user.full_name && user.full_name.trim()), fix: '#profile-full-name' },
            { key: 'active',   label: 'Account in good standing', met: user.status === 'active',            fix: null }
        ];
        // TODO(user decision): equal weighting, no cap. Alternatives discussed:
        //   - weight 'verified' double, since an unverified email breaks recovery
        //   - cap the score at 50% while 'verified' is unmet, rather than subtracting
        var met = signals.filter(function (s) { return s.met; }).length;
        var score = Math.round((met / signals.length) * 100);
        return { signals: signals, met: met, total: signals.length, score: score };
    }

    /* Copy for a signal that cannot be fixed from a field on this page. */
    var SIGNAL_UNMET_NOTES = {
        verified: "Check your inbox for the verification link",
        active: "Contact an admin about your account"
    };

    var SIGNAL_MET_STATE = "Done";

    function captionFor(score) {
        if (score >= 100) return "Secure";
        if (score >= 75) return "Good";
        if (score >= 50) return "Fair";
        return "At risk";
    }

    /* ── identity hero ─────────────────────────────────────────────── */

    function buildGauge(posture) {
        var wrap = el("div", "kw-readiness");

        var gauge = el("div", "kw-gauge");
        var svg = svgEl("svg");
        svg.setAttribute("viewBox", "0 0 74 74");
        svg.setAttribute("role", "img");
        svg.setAttribute(
            "aria-label",
            "Account security " + posture.score + " percent: " + posture.met
                + " of " + posture.total + " signals complete"
        );

        var track = svgEl("circle");
        track.setAttribute("cx", "37");
        track.setAttribute("cy", "37");
        track.setAttribute("r", "33");
        track.setAttribute("class", "kw-gauge-track");
        svg.appendChild(track);

        var fill = svgEl("circle");
        fill.setAttribute("cx", "37");
        fill.setAttribute("cy", "37");
        fill.setAttribute("r", "33");
        fill.setAttribute("class", "kw-gauge-fill");
        fill.setAttribute(
            "stroke-dasharray",
            (posture.score / 100 * GAUGE_CIRCUMFERENCE).toFixed(2) + " " + GAUGE_CIRCUMFERENCE
        );
        svg.appendChild(fill);
        gauge.appendChild(svg);

        var label = el("div", "kw-gauge-label");
        label.appendChild(el("span", "kw-gauge-value", posture.score + "%"));
        label.appendChild(el("span", "kw-gauge-caption", captionFor(posture.score)));
        gauge.appendChild(label);
        wrap.appendChild(gauge);

        var body = el("div", "kw-readiness-body");
        body.appendChild(el("div", "kw-readiness-title", "Account security"));

        var figures = el("div", "kw-readiness-figures");
        var done = el("span", "kw-figure");
        done.appendChild(el("span", "kw-dot kw-dot-ready"));
        done.appendChild(el("b", null, String(posture.met)));
        done.appendChild(el("span", null, "Done"));
        figures.appendChild(done);

        var open = posture.total - posture.met;
        var todo = el("span", "kw-figure");
        todo.appendChild(el("span", "kw-dot kw-dot-off"));
        todo.appendChild(el("b", null, String(open)));
        todo.appendChild(el("span", null, "Open"));
        figures.appendChild(todo);
        body.appendChild(figures);

        body.appendChild(el(
            "div",
            "kw-readiness-foot",
            open === 0
                ? "Every signal we can check is in place."
                : open + " " + pluralize(open, "step", "steps") + " left, listed below."
        ));
        wrap.appendChild(body);
        return wrap;
    }

    function renderHero() {
        var user = state.user;
        var hero = $("pro-hero");
        if (!user || !hero) return;

        var name = trimmed(user.full_name) || "Unnamed account";
        var email = trimmed(user.email);

        $("pro-avatar").textContent = initialsFor(user.full_name);
        $("pro-hero-name").textContent = name;
        $("pro-hero-email").textContent = email || "No email on file";

        var tags = $("pro-hero-tags");
        tags.replaceChildren();

        var role = trimmed(user.role).toLowerCase();
        if (role) {
            tags.appendChild(el("span", "pro-tag is-role", titleCase(role)));
        }

        var verified = el("span", "pro-tag " + (user.is_verified ? "is-verified" : "is-unverified"));
        verified.appendChild(icon(user.is_verified ? "check" : "alert", 13));
        verified.appendChild(el("span", null, user.is_verified ? "Verified" : "Unverified"));
        tags.appendChild(verified);

        /* Anything other than active is worth saying out loud rather than
           leaving the reader to infer it from a missing chip. */
        var status = trimmed(user.status).toLowerCase();
        if (status && status !== "active") {
            tags.appendChild(el("span", "pro-tag is-unverified", titleCase(status)));
        }

        var tenure = $("pro-hero-tenure");
        tenure.replaceChildren();
        var since = formatDate(user.created_at);
        if (since) {
            tenure.appendChild(document.createTextNode("Member since "));
            tenure.appendChild(el("b", null, since));
            var age = tenureFrom(user.created_at);
            if (age) {
                tenure.appendChild(document.createTextNode(" · "));
                tenure.appendChild(el("b", null, age));
            }
        } else {
            tenure.appendChild(document.createTextNode("Join date unavailable."));
        }

        var gaugeHost = $("pro-hero-gauge");
        gaugeHost.replaceChildren(buildGauge(computeSecurityPosture(user)));

        show($("pro-hero-skeleton"), false);
        show(hero, true);
    }

    /* ── security signals ──────────────────────────────────────────── */

    function renderSignals() {
        var host = $("pro-signals");
        if (!host) return;

        show($("pro-signals-loading"), false);

        if (!state.user) {
            show(host, false);
            show($("pro-signals-empty"), true);
            return;
        }
        show($("pro-signals-empty"), false);

        var posture = computeSecurityPosture(state.user);
        host.replaceChildren();

        posture.signals.forEach(function (signal) {
            var row = el("li", "pro-signal");
            row.setAttribute("data-signal", signal.key);
            row.setAttribute("data-met", signal.met ? "true" : "false");

            var mark = el("span", "pro-signal-mark");
            mark.setAttribute("aria-hidden", "true");
            mark.appendChild(icon(signal.met ? "check" : "alert", 13));
            row.appendChild(mark);

            row.appendChild(el("span", "pro-signal-label", signal.label));

            if (signal.met) {
                row.appendChild(el("span", "pro-signal-state", SIGNAL_MET_STATE));
            } else if (signal.fix) {
                /* A real control, not a decorative "fix it" label: it moves
                   focus to the field that resolves the signal, so keyboard
                   and pointer users take the same one-step path. */
                var button = el("button", "kw-btn cr-press pro-signal-fix", "Add it now");
                button.type = "button";
                button.setAttribute("data-fix", signal.fix);
                button.setAttribute(
                    "aria-label",
                    signal.label + " is missing. Go to the field that sets it."
                );
                row.appendChild(button);
            } else {
                row.appendChild(el(
                    "span",
                    "pro-signal-state",
                    SIGNAL_UNMET_NOTES[signal.key] || "Not set"
                ));
            }

            host.appendChild(row);
        });

        show(host, true);
    }

    /* ── workspace standing ────────────────────────────────────────── */

    function timelineStep(label, dateText, done, current) {
        var step = el("li", "kw-step" + (done ? " is-done" : "") + (current ? " is-current" : ""));

        var mark = el("span", "kw-step-mark");
        mark.setAttribute("aria-hidden", "true");
        mark.appendChild(icon(done ? "check" : "dot", 12));
        step.appendChild(mark);

        var text = el("div", "pro-step-text");
        text.appendChild(el("span", null, label));
        text.appendChild(el("span", "pro-step-date", dateText));
        step.appendChild(text);
        return step;
    }

    function renderTimeline() {
        var host = $("pro-timeline");
        var user = state.user;
        if (!host || !user) return;

        host.replaceChildren();

        var steps = [
            {
                label: "Account created",
                date: formatDate(user.created_at) || "Date unavailable",
                done: !!user.created_at
            },
            {
                label: "Email verified",
                date: user.is_verified ? "Confirmed" : "Still pending",
                done: !!user.is_verified
            },
            {
                label: "Joined this workspace",
                date: trimmed(user.role) ? "As " + titleCase(user.role) : "Role unavailable",
                done: !!trimmed(user.role)
            },
            {
                label: "Last updated",
                date: formatDate(user.updated_at) || "Never changed",
                done: !!user.updated_at,
                current: true
            }
        ];

        steps.forEach(function (spec, index) {
            if (index > 0) {
                var sep = el("li", "kw-step-sep");
                sep.setAttribute("aria-hidden", "true");
                host.appendChild(sep);
            }
            host.appendChild(timelineStep(spec.label, spec.date, spec.done, spec.current));
        });
    }

    function renderSeats() {
        var block = $("pro-seats-block");
        var host = $("pro-seats");
        var workspace = asObject(state.workspace);

        /* Degrade rather than error: without the workspace read there is no
           honest seat figure, so the meter is dropped and the composition
           below it still renders. */
        if (!block || !host || !workspace) {
            show(block, false);
            return;
        }

        var active = Math.max(Number(workspace.active_member_count || 0), 0);
        var pending = Math.max(Number(workspace.pending_invitation_count || 0), 0);
        var taken = active + pending;
        var limit = workspace.plan_member_limit;
        var unlimited = limit === null || limit === undefined;

        host.replaceChildren();

        var figure = el("div", "pro-seats-figure");
        figure.appendChild(el("span", "pro-seats-used cr-countup", String(taken)));
        figure.appendChild(el(
            "span",
            "pro-seats-limit",
            unlimited ? "seats in use" : "of " + limit + " seats"
        ));
        host.appendChild(figure);

        if (!unlimited && Number(limit) > 0) {
            var ratio = Math.min(taken / Number(limit), 1);
            var bar = el("div", "kw-progress");
            bar.setAttribute("aria-hidden", "true");
            var fill = el("div", "kw-progress-fill");
            if (ratio >= 0.85) fill.classList.add("is-tight");
            /* scaleX, never width: transform-origin is already left center
               in the system sheet and this keeps the bar off the layout. */
            fill.style.transform = "scaleX(" + ratio + ")";
            bar.appendChild(fill);
            host.appendChild(bar);
        }

        var note = el("p", "pro-seats-note");
        if (unlimited) {
            note.textContent = "Your plan has no seat limit.";
        } else {
            var remaining = workspace.remaining_seats;
            if (remaining === null || remaining === undefined) {
                remaining = Math.max(Number(limit) - taken, 0);
            }
            if (remaining <= 0) {
                note.className = "pro-seats-note is-warn";
                note.textContent = "Every seat on this plan is taken.";
            } else {
                note.textContent = remaining + " " + pluralize(remaining, "seat", "seats")
                    + " left. A pending invitation holds a seat until it is accepted or cancelled.";
            }
        }
        host.appendChild(note);
        show(block, true);
    }

    /* Active colleagues grouped by role, in privilege order. */
    function roleBreakdown(roster) {
        var counts = {};
        roster.forEach(function (member) {
            var status = trimmed(member.status).toLowerCase();
            if (status && status !== "active") return;
            var role = trimmed(member.role).toLowerCase() || "member";
            counts[role] = (counts[role] || 0) + 1;
        });

        var keys = Object.keys(counts).sort(function (a, b) {
            var ra = ROLE_ORDER.indexOf(a);
            var rb = ROLE_ORDER.indexOf(b);
            if (ra === -1 && rb === -1) return a < b ? -1 : 1;
            if (ra === -1) return 1;
            if (rb === -1) return -1;
            return ra - rb;
        });

        return keys.map(function (role) {
            return {
                role: role,
                count: counts[role],
                colour: ROLE_COLOURS[role] || ROLE_FALLBACK_COLOUR
            };
        });
    }

    function renderComposition() {
        var host = $("pro-composition");
        if (!host) return;

        var rows = roleBreakdown(state.roster || []);
        var total = rows.reduce(function (sum, row) { return sum + row.count; }, 0);
        host.replaceChildren();
        if (!total) return;

        var myRole = trimmed(state.user && state.user.role).toLowerCase();

        var svg = svgEl("svg");
        svg.setAttribute("viewBox", "0 0 108 108");
        svg.setAttribute("role", "img");
        svg.setAttribute("aria-label", rows.map(function (row) {
            return row.count + " " + pluralize(row.count, titleCase(row.role), titleCase(row.role) + "s");
        }).join(", ") + ", " + total + " active " + pluralize(total, "person", "people") + " in total");

        var track = svgEl("circle");
        track.setAttribute("cx", "54");
        track.setAttribute("cy", "54");
        track.setAttribute("r", String(DONUT_RADIUS));
        track.setAttribute("class", "kw-gauge-track");
        track.setAttribute("stroke-width", "11");
        svg.appendChild(track);

        var consumed = 0;
        rows.forEach(function (row) {
            var length = row.count / total * DONUT_CIRCUMFERENCE;
            var arc = svgEl("circle");
            arc.setAttribute("cx", "54");
            arc.setAttribute("cy", "54");
            arc.setAttribute("r", String(DONUT_RADIUS));
            arc.setAttribute("fill", "none");
            arc.setAttribute("stroke", row.colour);
            arc.setAttribute("stroke-width", "11");
            arc.setAttribute(
                "stroke-dasharray",
                length.toFixed(2) + " " + (DONUT_CIRCUMFERENCE - length).toFixed(2)
            );
            arc.setAttribute("stroke-dashoffset", String(-consumed.toFixed(2)));
            svg.appendChild(arc);
            consumed += length;
        });
        host.appendChild(svg);

        var legend = el("div", "kw-composition-legend");
        rows.forEach(function (row) {
            var isYou = row.role === myRole;
            var line = el("div", "kw-composition-row" + (isYou ? " is-you" : ""));

            var swatch = el("span", "kw-swatch");
            swatch.setAttribute("aria-hidden", "true");
            swatch.style.background = row.colour;
            line.appendChild(swatch);

            var label = el("span", null, titleCase(row.role));
            label.title = titleCase(row.role);
            if (isYou) {
                /* The highlight is a chip and a left rule, not a colour, so
                   it survives for anyone who cannot see the accent. */
                label.appendChild(document.createTextNode(" "));
                label.appendChild(el("span", "pro-you", "You"));
            }
            line.appendChild(label);

            line.appendChild(el("b", null, String(row.count)));
            line.appendChild(el("i", null, Math.round(row.count / total * 100) + "%"));
            legend.appendChild(line);
        });
        host.appendChild(legend);
    }

    function renderStanding() {
        var panel = $("pro-standing");
        show($("pro-standing-loading"), false);

        /* Both reads failing leaves nothing truthful to draw. One failing
           still leaves a useful panel, so only the pair is an error. */
        if (!state.roster && !state.workspace) {
            show(panel, false);
            show($("pro-standing-empty"), false);
            $("pro-standing-error-text").textContent =
                "We could not load your workspace details.";
            show($("pro-standing-error"), true);
            return;
        }
        show($("pro-standing-error"), false);

        var activeCount = roleBreakdown(state.roster || []).reduce(
            function (sum, row) { return sum + row.count; }, 0
        );
        if (!activeCount && !state.workspace) {
            show(panel, false);
            show($("pro-standing-empty"), true);
            return;
        }
        show($("pro-standing-empty"), false);

        var workspace = asObject(state.workspace);
        var role = trimmed(
            (workspace && workspace.current_user_role) || (state.user && state.user.role)
        ).toLowerCase();

        var roleHost = $("pro-role");
        roleHost.replaceChildren();
        roleHost.appendChild(el("span", "pro-role-name", role ? titleCase(role) : "Unknown"));
        roleHost.appendChild(el(
            "span",
            "pro-role-note",
            ROLE_NOTES[role] || "Ask an admin what this role can do."
        ));

        renderTimeline();
        renderSeats();
        renderComposition();

        var pending = workspace ? Math.max(Number(workspace.pending_invitation_count || 0), 0) : null;
        var pendingNode = $("pro-pending");
        if (pending === null) {
            pendingNode.textContent = "Invitation count unavailable right now.";
        } else if (pending === 0) {
            pendingNode.textContent = "No invitations are waiting to be accepted.";
        } else {
            pendingNode.textContent = pending + " " + pluralize(pending, "invitation", "invitations")
                + " " + pluralize(pending, "is", "are") + " still waiting to be accepted.";
        }

        show(panel, true);
    }

    /* ── password strength ─────────────────────────────────────────── */

    /* The four rules the backend enforces, plus a length bonus. Nothing
       here is a gate: the form still validates on submit. */
    function strengthOf(password) {
        var rules = [
            password.length >= 8,
            /[A-Z]/.test(password),
            /[0-9]/.test(password),
            /[^A-Za-z0-9]/.test(password)
        ];
        var met = rules.filter(Boolean).length;
        var roomy = password.length >= 12;
        var ratio = (met + (roomy ? 1 : 0)) / 5;

        var level = "weak";
        if (met === 4) level = roomy ? "strong" : "fair";
        return { ratio: ratio, level: level, complete: met === 4 };
    }

    var STRENGTH_WORDS = { weak: "Weak", fair: "Fair", strong: "Strong" };

    function renderStrength() {
        var input = $("profile-new-password");
        var fill = $("pro-strength-fill");
        var text = $("pro-strength-text");
        if (!input || !fill || !text) return;

        var value = input.value || "";
        if (!value) {
            fill.style.transform = "scaleX(0)";
            fill.className = "kw-progress-fill";
            /* The live region is cleared rather than told "empty": an empty
               string is silent, which is what leaving the field should be. */
            if (state.strengthLevel !== null) {
                text.textContent = "";
                state.strengthLevel = null;
            }
            text.className = "pro-strength-text";
            return;
        }

        var result = strengthOf(value);
        fill.style.transform = "scaleX(" + result.ratio + ")";
        fill.className = "kw-progress-fill"
            + (result.level === "strong" ? "" : " is-" + result.level);
        text.className = "pro-strength-text is-" + result.level;

        /* Only write on a level change. Rewriting a live region on every
           keystroke would make a screen reader unusable here. */
        if (state.strengthLevel !== result.level) {
            state.strengthLevel = result.level;
            text.textContent = STRENGTH_WORDS[result.level];
        }
    }

    /* ── account form ──────────────────────────────────────────────── */

    function fillAccountForm() {
        var user = state.user;
        if (!user) return;
        $("profile-full-name").value = trimmed(user.full_name);
        $("profile-email").value = trimmed(user.email);
        $("profile-phone").value = trimmed(user.phone);
    }

    async function saveAccount() {
        var button = $("pro-account-submit");
        var user = state.user;
        if (!button || !user) return;

        var fullName = trimmed($("profile-full-name").value);
        var phone = trimmed($("profile-phone").value);

        if (!fullName) {
            setFormMessage("pro-account-msg", "pro-account-msg-text",
                "Your full name cannot be empty.", "error");
            $("profile-full-name").focus();
            return;
        }

        var payload = {};
        if (fullName !== trimmed(user.full_name)) payload.full_name = fullName;
        if (phone !== trimmed(user.phone)) payload.phone = phone || null;

        if (!Object.keys(payload).length) {
            setFormMessage("pro-account-msg", "pro-account-msg-text",
                "Nothing has changed yet.", "success");
            return;
        }

        button.disabled = true;
        button.textContent = "Saving…";

        try {
            var res = await authenticatedFetch("/api/user", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            var body = await res.json();

            if (body && body.status === "success") {
                /* A new object rather than a mutation, so nothing else that
                   still holds the old user sees it change underneath. */
                state.user = Object.assign({}, state.user, asObject(body.data) || payload);
                syncStoredUser(state.user);
                fillAccountForm();
                renderHero();
                renderSignals();
                setFormMessage("pro-account-msg", "pro-account-msg-text",
                    body.message || "Your details are saved.", "success");
            } else {
                setFormMessage("pro-account-msg", "pro-account-msg-text",
                    (body && body.message) || "We could not save your details.", "error");
            }
        } catch (_) {
            setFormMessage("pro-account-msg", "pro-account-msg-text",
                "We could not reach the server. Your details are unchanged.", "error");
        }

        button.disabled = false;
        button.textContent = "Save changes";
    }

    /* The sidebar and the account menu read the cached user, so a rename
       that is not written back leaves a stale name in the chrome. */
    function syncStoredUser(user) {
        try {
            var stored = JSON.parse(sessionStorage.getItem("user") || "{}");
            var next = Object.assign({}, stored);
            if (user.full_name) next.full_name = user.full_name;
            if (user.email) next.email = user.email;
            sessionStorage.setItem("user", JSON.stringify(next));
        } catch (_) {
            /* A quota or parse failure here is cosmetic, never fatal. */
        }
    }

    /* ── password form ─────────────────────────────────────────────── */

    function passwordProblem(current, next, confirm) {
        if (!current || !next || !confirm) return "Fill in all three password fields.";
        if (next !== confirm) return "The new passwords do not match.";
        if (next === current) return "Your new password must be different from the current one.";
        if (next.length < 8) return "Your new password must be at least 8 characters.";
        if (!/[A-Z]/.test(next)) return "Your new password needs at least one uppercase letter.";
        if (!/[0-9]/.test(next)) return "Your new password needs at least one number.";
        if (!/[^A-Za-z0-9]/.test(next)) return "Your new password needs at least one special character.";
        return null;
    }

    function resetPasswordForm() {
        ["profile-current-password", "profile-new-password", "profile-confirm-password"]
            .forEach(function (id) {
                var input = $(id);
                if (!input) return;
                input.value = "";
                input.type = "password";
            });

        Array.prototype.forEach.call(
            document.querySelectorAll(".pro-secret-toggle"),
            function (button) { setSecretToggle(button, false); }
        );

        state.strengthLevel = null;
        renderStrength();
    }

    async function changePassword() {
        var button = $("pro-password-submit");
        if (!button) return;

        var current = $("profile-current-password").value;
        var next = $("profile-new-password").value;
        var confirm = $("profile-confirm-password").value;

        var problem = passwordProblem(current, next, confirm);
        if (problem) {
            setFormMessage("pro-password-msg", "pro-password-msg-text", problem, "error");
            $("profile-new-password").focus();
            return;
        }

        button.disabled = true;
        button.textContent = "Updating…";

        try {
            var res = await authenticatedFetch("/api/user/password", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    current_password: current,
                    new_password: next,
                    confirm_password: confirm
                })
            });
            var body = await res.json();

            if (body && body.status === "success") {
                resetPasswordForm();
                setFormMessage("pro-password-msg", "pro-password-msg-text",
                    body.message || "Your password is changed.", "success");
            } else {
                setFormMessage("pro-password-msg", "pro-password-msg-text",
                    (body && body.message) || "We could not change your password.", "error");
            }
        } catch (_) {
            setFormMessage("pro-password-msg", "pro-password-msg-text",
                "We could not reach the server. Your password is unchanged.", "error");
        }

        button.disabled = false;
        button.textContent = "Update password";
    }

    /* ── show / hide a password ────────────────────────────────────── */

    var SECRET_LABELS = {
        "profile-current-password": "current password",
        "profile-new-password": "new password",
        "profile-confirm-password": "confirmed password"
    };

    function setSecretToggle(button, revealed) {
        var id = button.getAttribute("data-secret");
        var input = $(id);
        if (!input) return;

        input.type = revealed ? "text" : "password";
        button.setAttribute("aria-pressed", revealed ? "true" : "false");
        button.setAttribute(
            "aria-label",
            (revealed ? "Hide " : "Show ") + (SECRET_LABELS[id] || "password")
        );
        button.replaceChildren(icon(revealed ? "eyeOff" : "eye", 17));
    }

    /* ── preferences ───────────────────────────────────────────────── */

    var NOTIFICATIONS_KEY = "notifications_enabled";

    function loadPreferences() {
        var box = $("pref-notifications");
        if (!box) return;
        var stored = null;
        try {
            stored = localStorage.getItem(NOTIFICATIONS_KEY);
        } catch (_) {
            /* Private windows can throw on access; the default stands. */
        }
        box.checked = stored !== "false";
    }

    function savePreference() {
        var box = $("pref-notifications");
        if (!box) return;
        try {
            localStorage.setItem(NOTIFICATIONS_KEY, box.checked ? "true" : "false");
            announce(box.checked
                ? "Browser notifications are on for this browser."
                : "Browser notifications are off for this browser.");
        } catch (_) {
            announce("This browser will not save the notification preference.");
        }
    }

    /* ── delete workspace ──────────────────────────────────────────── */

    var DELETE_CODE_LENGTH = 6;

    /* Which single region of the panel to show for what the server said. Self-
       contained on purpose: a test runs this function on its own. Anything
       unexpected falls to "error" or "blocked", never to "eligible", so a
       malformed answer cannot put a delete button in front of someone. */
    function deletionView(body) {
        var reasons = {
            payment_history: "This workspace has payment history that we have to keep, so it cannot be deleted from here.",
            protected: "This workspace is protected, so it cannot be deleted from here.",
            support_records: "This workspace has support records that we have to keep, so it cannot be deleted from here."
        };
        if (!body || typeof body !== "object" || Array.isArray(body) || typeof body.eligible !== "boolean") {
            return { state: "error", message: "We could not check whether this workspace can be deleted." };
        }
        if (body.is_owner === false) return { state: "owner-only", message: "" };
        if (body.eligible === true && body.is_owner === true) return { state: "eligible", message: "" };
        return {
            state: "blocked",
            message: reasons[body.reason_code] || "This workspace cannot be deleted from here."
        };
    }

    function showDeletionState(name) {
        ["loading", "error", "owner-only", "blocked", "eligible"].forEach(function (region) {
            show($("pro-delete-" + region), region === name);
        });
    }

    /* A rate-limit reply is an HTML page rather than JSON, so a body that will
       not parse is an expected case here, not an error. */
    async function readDeletionReply(res) {
        var body = null;
        try {
            body = await res.json();
        } catch (_) {
            body = null;
        }
        return { ok: res.ok && !!body && body.status === "success", status: res.status, body: body };
    }

    function deletionMessage(result) {
        if (result.body && result.body.message) return result.body.message;
        if (result.status === 429) return "Too many attempts. Please wait a little before trying again.";
        /* Never "nothing was changed": a dropped connection can follow a deletion that committed. */
        if (result.status === 0) return "We could not reach the server. Check your connection and try again.";
        return "Something went wrong. Please try again.";
    }

    async function loadDeletion() {
        showDeletionState("loading");

        var body = null;
        try {
            var res = await authenticatedFetch("/api/user/account-deletion");
            body = await res.json();
        } catch (_) {
            body = null;
        }

        var ok = !!body && body.status === "success";
        var view = deletionView(ok ? body : null);

        if (view.state === "error") {
            /* A suspended workspace answers with its own sentence; show it. */
            $("pro-delete-error-text").textContent = (body && body.message) || view.message;
        } else if (view.state === "blocked") {
            $("pro-delete-blocked-text").textContent = view.message;
        } else if (view.state === "eligible") {
            $("pro-delete-company").textContent = trimmed(body.company_name) || "this workspace";
            $("pro-delete-email").textContent = (state.user && trimmed(state.user.email)) || "your account address";
        }
        showDeletionState(view.state);
    }

    /* The dialog is modal, so everything outside it is inert: its message has
       to be written inside it, never to the page-level live region. */
    function setDeleteDialogMessage(message, isError) {
        var node = $("pro-delete-dialog-status");
        if (!node) return;
        node.textContent = message || "";
        node.classList.toggle("is-error", !!isError);
    }

    /* Digits only, at most six; the delete button stays off until all six are there. */
    function syncDeleteConfirm() {
        var input = $("pro-delete-code");
        var button = $("pro-delete-confirm");
        if (!input || !button) return;
        var digits = input.value.replace(/\D/g, "").slice(0, DELETE_CODE_LENGTH);
        if (digits !== input.value) input.value = digits;
        button.disabled = !(digits.length === DELETE_CODE_LENGTH) || state.deleting;
    }

    function openDeleteDialog(message) {
        var dialog = $("pro-delete-dialog");
        var input = $("pro-delete-code");
        if (!dialog || !input) return;
        input.value = "";
        syncDeleteConfirm();
        setDeleteDialogMessage(message, false);
        dialog.showModal();
        input.focus();
    }

    function closeDeleteDialog() {
        var dialog = $("pro-delete-dialog");
        if (dialog && dialog.open) dialog.close();
    }

    async function requestDeletionCode() {
        var button = $("pro-delete-request");
        if (!button) return;

        button.disabled = true;
        button.textContent = "Sending…";
        setFormMessage("pro-delete-msg", "pro-delete-msg-text", "");

        var result;
        try {
            var res = await authenticatedFetch("/api/user/account-deletion/code", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: "{}"
            });
            result = await readDeletionReply(res);
        } catch (_) {
            result = { ok: false, status: 0, body: null };
        }

        button.disabled = false;
        button.textContent = "Email me a code";

        if (result.ok) {
            var email = (state.user && trimmed(state.user.email)) || "your account address";
            openDeleteDialog("We emailed a 6-digit code to " + email + ". It expires in 10 minutes.");
        } else if (result.body && result.body.reason_code) {
            /* The workspace stopped being deletable since the page loaded. */
            loadDeletion();
        } else {
            setFormMessage("pro-delete-msg", "pro-delete-msg-text", deletionMessage(result), "error");
        }
    }

    async function confirmDeletion() {
        var input = $("pro-delete-code");
        var button = $("pro-delete-confirm");
        var cancel = $("pro-delete-cancel");
        if (!input || !button || state.deleting) return;

        var code = input.value.replace(/\D/g, "");
        if (code.length !== DELETE_CODE_LENGTH) return;

        state.deleting = true;
        button.disabled = true;
        if (cancel) cancel.disabled = true;
        button.textContent = "Deleting…";
        setDeleteDialogMessage("Deleting your workspace…", false);

        var result;
        try {
            var res = await authenticatedFetch("/api/user/account-deletion/confirm", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ code: code })
            });
            result = await readDeletionReply(res);
        } catch (_) {
            result = { ok: false, status: 0, body: null };
        }

        if (result.ok) {
            /* The account is gone, so the stored session is worthless: clear it
               exactly as a sign-out does and leave. The login page already
               shows this stored message above its form. */
            try {
                sessionStorage.setItem("deactivated_message", "Your workspace has been permanently deleted.");
            } catch (_) {
                /* Cosmetic only; the redirect below is what matters. */
            }
            logout();
            return;
        }

        state.deleting = false;
        button.textContent = "Delete workspace permanently";
        if (cancel) cancel.disabled = false;
        setDeleteDialogMessage(deletionMessage(result), true);

        var failure = result.body || {};
        if (failure.reason_code) {
            /* No longer deletable: leave the dialog and show the real reason. */
            closeDeleteDialog();
            loadDeletion();
            return;
        }
        if (failure.code === "code_expired" || failure.code === "too_many_attempts") input.value = "";
        syncDeleteConfirm();
        input.focus();
    }

    /* ── load ──────────────────────────────────────────────────────── */

    /* /api/user is being widened to carry the account-standing fields. Until
       every deployment has it, the roster row for the same id is the source
       of truth for anything the widened response omits. */
    function mergeWithRoster(user, roster) {
        if (!user) return null;
        var self = null;
        if (Array.isArray(roster)) {
            self = roster.filter(function (row) {
                return String(row.id) === String(user.id);
            })[0] || null;
        }
        if (!self) return Object.assign({}, user);

        var merged = Object.assign({}, self, user);
        ["status", "is_verified", "created_at", "updated_at"].forEach(function (field) {
            if (merged[field] === undefined || merged[field] === null) {
                merged[field] = self[field];
            }
        });
        return merged;
    }

    function setLoading(isLoading) {
        show($("pro-hero-skeleton"), isLoading);
        show($("pro-signals-loading"), isLoading);
        show($("pro-standing-loading"), isLoading);
        if (isLoading) {
            show($("pro-hero"), false);
            show($("pro-signals"), false);
            show($("pro-standing"), false);
            show($("pro-standing-error"), false);
            show($("pro-standing-empty"), false);
            show($("pro-signals-empty"), false);
        }
    }

    async function load() {
        setLoading(true);
        clearError();

        /* Three independent reads, issued together. Serialising them would
           add two round trips to first paint for no benefit. */
        var results = await Promise.all([
            getJson("/api/user"),
            getJson("/api/users"),
            getJson("/api/workspace")
        ]);

        state.roster = Array.isArray(results[1]) ? results[1] : null;
        state.workspace = asObject(results[2]);
        state.user = mergeWithRoster(asObject(results[0]), state.roster);

        setLoading(false);

        if (!state.user) {
            show($("pro-hero-skeleton"), false);
            showError("We could not load your account. Nothing here is up to date.");
            renderSignals();
            renderStanding();
            return;
        }

        fillAccountForm();
        renderHero();
        renderSignals();
        renderStanding();

        if (window.controlRoomMotion) window.controlRoomMotion.countUpAll(document);
        /* Icons last, and never awaited: lucide is deferred and only serves
           the sidebar, so it must not gate anything above. */
        if (typeof refreshIcons === "function") refreshIcons();
    }

    /* ── wiring ────────────────────────────────────────────────────── */

    function wire() {
        var retry = $("pro-retry");
        if (retry) retry.addEventListener("click", function () { load(); });

        var standingRetry = $("pro-standing-retry");
        if (standingRetry) standingRetry.addEventListener("click", function () { load(); });

        var accountForm = $("pro-account-form");
        if (accountForm) {
            accountForm.addEventListener("submit", function (event) {
                event.preventDefault();
                saveAccount();
            });
        }

        var passwordForm = $("pro-password-form");
        if (passwordForm) {
            passwordForm.addEventListener("submit", function (event) {
                event.preventDefault();
                changePassword();
            });
        }

        var newPassword = $("profile-new-password");
        if (newPassword) newPassword.addEventListener("input", renderStrength);

        Array.prototype.forEach.call(
            document.querySelectorAll(".pro-secret-toggle"),
            function (button) {
                setSecretToggle(button, false);
                button.addEventListener("click", function () {
                    setSecretToggle(button, button.getAttribute("aria-pressed") !== "true");
                });
            }
        );

        /* Delegated: the signal rows are rebuilt on every save, so binding
           per row would leak a listener each time. */
        var signals = $("pro-signals");
        if (signals) {
            signals.addEventListener("click", function (event) {
                var button = event.target.closest("[data-fix]");
                if (!button) return;
                var target = document.querySelector(button.getAttribute("data-fix"));
                if (!target) return;
                target.focus();
                target.scrollIntoView({ block: "center" });
            });
        }

        var notifications = $("pref-notifications");
        if (notifications) notifications.addEventListener("change", savePreference);

        wireDeletion();
    }

    function wireDeletion() {
        var retry = $("pro-delete-retry");
        if (retry) retry.addEventListener("click", function () { loadDeletion(); });

        var request = $("pro-delete-request");
        if (request) request.addEventListener("click", function () { requestDeletionCode(); });

        var code = $("pro-delete-code");
        if (code) code.addEventListener("input", syncDeleteConfirm);

        var form = $("pro-delete-form");
        if (form) {
            form.addEventListener("submit", function (event) {
                event.preventDefault();
                confirmDeletion();
            });
        }

        var cancel = $("pro-delete-cancel");
        if (cancel) cancel.addEventListener("click", closeDeleteDialog);

        var dialog = $("pro-delete-dialog");
        if (dialog) {
            /* Escape must not abandon a delete that is already on its way. */
            dialog.addEventListener("cancel", function (event) {
                if (state.deleting) event.preventDefault();
            });
            /* The code does not linger in the page once the dialog is gone. */
            dialog.addEventListener("close", function () {
                if (code) code.value = "";
                setDeleteDialogMessage("", false);
                if (request && !request.closest("[hidden]")) request.focus();
            });
        }
    }

    function start() {
        wire();
        loadPreferences();
        /* After the account read, so the eligible region can name the email address. */
        load().then(loadDeletion);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
