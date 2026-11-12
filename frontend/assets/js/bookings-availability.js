(function () {
    "use strict";

    /* pure:start - no DOM, no network; tests/test_bookings_availability_frontend.py runs this block in Node. */
    const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const HHMM = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
    const OTHER_PRICE_LABELS = { quote: "Quote only", none: "No price shown" };
    const WEEKDAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const TIME_FORMAT = new Intl.DateTimeFormat("en-GB", {
        weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
        hour12: false, timeZone: "Asia/Kuala_Lumpur"
    });

    function formatMyr(microMyr) {
        const sen = Math.round(Number(microMyr) / 10000);
        const ringgit = String(Math.floor(sen / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        return "RM " + ringgit + "." + String(sen % 100).padStart(2, "0");
    }

    function priceLabel(pkg) {
        const priced = pkg.price_mode === "fixed" || pkg.price_mode === "per_person";
        if (priced && pkg.price_micro_myr != null) {
            return formatMyr(pkg.price_micro_myr) + (pkg.price_mode === "per_person" ? " per person" : "");
        }
        return OTHER_PRICE_LABELS[pkg.price_mode] || "No price shown";
    }

    function seatsLabel(slot) {
        return slot.booked_seats + " of " + slot.capacity + " seats booked";
    }

    // One opening-hours row per weekday from the editor; closed days are left out.
    function hoursPayload(rows) {
        const hours = [];
        for (const row of rows) {
            if (!row.open) continue;
            const day = DAYS[row.weekday - 1] || "That day";
            const every = Number(row.every);
            if (!HHMM.test(row.start || "") || !HHMM.test(row.end || "")) {
                return { hours: null, error: day + ": write the hours like 09:30." };
            }
            if (row.end <= row.start) {
                return { hours: null, error: day + ": closing time must be after opening time." };
            }
            if (!Number.isInteger(every) || every < 5 || every > 1440) {
                return { hours: null, error: day + ": choose a gap of 5 to 1440 minutes between times." };
            }
            hours.push({ weekday: row.weekday, start: row.start, end: row.end, interval_minutes: every });
        }
        return { hours: hours, error: null };
    }

    // <input type="datetime-local"> gives "2026-10-10T15:00"; the API takes Malaysia local time.
    function apiMoment(localValue) {
        return String(localValue || "").replace("T", " ").slice(0, 16);
    }

    function timeLabel(iso) {
        return TIME_FORMAT.format(new Date(iso));
    }

    // "2026-10-20" (a Malaysia date) as "Tue 20 Oct 2026". Built by hand, not with Intl, so it reads
    // the same in every browser; read as UTC so it never shifts a day.
    function dateLabel(ymd) {
        const day = new Date(String(ymd) + "T00:00:00Z");
        return WEEKDAY_NAMES[day.getUTCDay()] + " " + day.getUTCDate() + " " + MONTH_NAMES[day.getUTCMonth()] + " " + day.getUTCFullYear();
    }
    /* pure:end */

    const state = { data: null, editing: null, isAdmin: false, generation: 0 };

    function $(id) { return document.getElementById(id); }

    function el(tag, className, content) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (content != null) node.textContent = content;
        return node;
    }

    // The same bot bookings.js resolved; it sends you to My bots when there is none.
    function chatbotId() {
        return parsePositiveSafeInteger(new URLSearchParams(location.search).get("bot_id") || sessionStorage.getItem("selectedBotId"));
    }

    function note(message) {
        const node = $("av-note");
        node.textContent = message || "";
        node.hidden = !message;
    }

    async function request(method, url, body) {
        let response;
        try {
            response = await authenticatedFetch(url, {
                method: method,
                headers: body === undefined ? undefined : { "Content-Type": "application/json" },
                body: body === undefined ? undefined : JSON.stringify(body)
            });
        } catch (_) {
            return { ok: false, status: 0, message: "Could not reach the server. Check your connection and try again." };
        }
        let payload = null;
        try { payload = await response.json(); } catch (_) { payload = null; }
        const ok = response.ok && payload !== null && payload.status === "success";
        return { ok: ok, status: response.status, data: ok ? payload.data : null,
                 code: payload && payload.code, message: (payload && payload.message) || "That did not work. Please try again." };
    }

    // --- rendering ----------------------------------------------------------------------

    function showLocked(locked) {
        $("av-locked").hidden = !locked;
        $("av-content").hidden = locked;
    }

    function packageSummary(pkg) {
        const count = pkg.seats_per_slot;
        const seats = pkg.seats_by_party
            ? count + (count === 1 ? " seat" : " seats") + " per time (one per person)"
            : count + (count === 1 ? " booking" : " bookings") + " per time";
        return pkg.duration_minutes + " min · " + priceLabel(pkg) + " · " + seats + (pkg.enabled ? "" : " · switched off");
    }

    function renderPackages() {
        const list = $("av-packages");
        list.replaceChildren();
        const packages = state.data.packages || [];
        if (packages.length === 0) {
            list.appendChild(el("li", "kw-help", "No packages yet. Add what customers can book, like a haircut or a class."));
        }
        packages.forEach(function (pkg) {
            const item = el("li", "av-row");
            const text = el("div");
            text.appendChild(el("strong", null, pkg.name));
            text.appendChild(el("span", "kw-help av-row-sub", packageSummary(pkg)));
            item.appendChild(text);
            const edit = el("button", "kw-btn cr-press", "Edit");
            edit.type = "button";
            edit.disabled = !state.isAdmin;
            edit.setAttribute("aria-label", "Edit " + pkg.name);
            edit.addEventListener("click", function () { openPackage(pkg); });
            item.appendChild(edit);
            list.appendChild(item);
        });
        const select = $("av-slot-package");
        select.replaceChildren();
        packages.filter(function (pkg) { return pkg.enabled; }).forEach(function (pkg) {
            select.appendChild(new Option(pkg.name, String(pkg.id)));
        });
        $("av-slot-form").hidden = select.options.length === 0;
    }

    function renderClosures() {
        const list = $("av-closures");
        list.replaceChildren();
        const closures = state.data.closures || [];
        if (closures.length === 0) list.appendChild(el("li", "kw-help", "No closed dates coming up."));
        closures.forEach(function (closure) {
            const item = el("li", "av-row");
            const text = el("div");
            text.appendChild(el("strong", null, dateLabel(closure.closed_on)));
            text.appendChild(el("span", "kw-help av-row-sub", closure.reason || "Closed all day"));
            item.appendChild(text);
            const remove = el("button", "kw-btn cr-press", "Reopen");
            remove.type = "button";
            remove.disabled = !state.isAdmin;
            remove.setAttribute("aria-label", "Reopen " + closure.closed_on);
            remove.addEventListener("click", function () { removeClosure(closure); });
            item.appendChild(remove);
            list.appendChild(item);
        });
    }

    function renderSlots() {
        const list = $("av-slots");
        list.replaceChildren();
        const names = {};
        (state.data.packages || []).forEach(function (pkg) { names[pkg.id] = pkg.name; });
        const slots = state.data.slots || [];
        if (slots.length === 0) list.appendChild(el("li", "kw-help", "No bookable times in the next 14 days. Set weekly hours on a package."));
        slots.forEach(function (slot) {
            const item = el("li", "av-row" + (slot.status === "closed" ? " av-row-closed" : ""));
            const text = el("div");
            text.appendChild(el("strong", null, timeLabel(slot.starts_at) + " · " + (names[slot.package_id] || "Package")));
            text.appendChild(el("span", "kw-help av-row-sub",
                seatsLabel(slot) + (slot.status === "closed" ? " · closed" : "")));
            item.appendChild(text);
            const toggle = el("button", "kw-btn cr-press", slot.status === "closed" ? "Open" : "Close");
            toggle.type = "button";
            toggle.disabled = !state.isAdmin;
            toggle.addEventListener("click", function () { toggleSlot(slot); });
            item.appendChild(toggle);
            list.appendChild(item);
        });
    }

    function render() {
        $("av-auto-confirm").checked = state.data.auto_confirm !== false;
        $("av-auto-confirm").disabled = !state.isAdmin;
        renderPackages();
        renderClosures();
        renderSlots();
    }

    async function load() {
        const id = chatbotId();
        const generation = ++state.generation;
        note("");
        if (!id) { showLocked(false); $("av-content").hidden = true; return; }
        const result = await request("GET", "/api/bookings/availability?chatbot_id=" + id);
        if (generation !== state.generation) return;
        if (result.code === "feature_not_available") { showLocked(true); return; }
        showLocked(false);
        if (!result.ok) { $("av-content").hidden = true; note(result.message); return; }
        state.data = result.data;
        render();
        if (!state.isAdmin) note("Only an owner or admin can change packages and times.");
    }

    async function afterWrite(result, doneMessage) {
        if (!result.ok) { note(result.message); return false; }
        await load();
        note(doneMessage);
        return true;
    }

    // --- package editor ---------------------------------------------------------------------

    function hourRows() {
        return DAYS.map(function (_, index) {
            const day = index + 1;
            return { weekday: day, open: $("av-day-" + day + "-open").checked, start: $("av-day-" + day + "-start").value,
                     end: $("av-day-" + day + "-end").value, every: $("av-day-" + day + "-every").value };
        });
    }

    function fillHours(packageId) {
        const blocks = (state.data.hours || []).filter(function (block) { return block.package_id === packageId; });
        DAYS.forEach(function (_, index) {
            const day = index + 1;
            const block = blocks.find(function (item) { return item.weekday === day; });
            $("av-day-" + day + "-open").checked = Boolean(block);
            $("av-day-" + day + "-start").value = block ? String(block.start_time).slice(0, 5) : "09:00";
            $("av-day-" + day + "-end").value = block ? String(block.end_time).slice(0, 5) : "18:00";
            $("av-day-" + day + "-every").value = block ? String(block.interval_minutes) : "60";
        });
    }

    function syncPriceField() {
        const priced = ["fixed", "per_person"].indexOf($("av-pkg-price-mode").value) !== -1;
        $("av-pkg-price-field").hidden = !priced;
    }

    function packageError(message) {
        const node = $("av-pkg-error");
        node.textContent = message || "";
        node.hidden = !message;
    }

    function openPackage(pkg) {
        const defaults = state.data.defaults || {};
        state.editing = pkg || null;
        $("av-pkg-title").textContent = pkg ? "Edit package" : "Add a " + (defaults.label || "booking").toLowerCase() + " package";
        $("av-pkg-name").value = pkg ? pkg.name : "";
        $("av-pkg-duration").value = String(pkg ? pkg.duration_minutes : 60);
        $("av-pkg-price-mode").value = pkg ? pkg.price_mode : (defaults.price_mode || "none");
        $("av-pkg-price").value = pkg && pkg.price_micro_myr != null ? (pkg.price_micro_myr / 1000000).toFixed(2) : "";
        $("av-pkg-seats").value = String(pkg ? pkg.seats_per_slot : (defaults.seats_per_slot || 1));
        $("av-pkg-by-party").checked = pkg ? pkg.seats_by_party : Boolean(defaults.seats_by_party);
        $("av-pkg-enabled").checked = pkg ? pkg.enabled : true;
        fillHours(pkg ? pkg.id : null);
        syncPriceField();
        packageError("");
        window.kwDialog.open($("av-package-modal"), $("av-pkg-name"));
    }

    function closePackage() {
        state.editing = null;
        window.kwDialog.close($("av-package-modal"));
    }

    async function savePackage(event) {
        event.preventDefault();
        const hours = hoursPayload(hourRows());
        if (hours.error) { packageError(hours.error); return; }
        const mode = $("av-pkg-price-mode").value;
        const body = {
            name: $("av-pkg-name").value,
            duration_minutes: Number($("av-pkg-duration").value),
            price_mode: mode,
            price_myr: mode === "fixed" || mode === "per_person" ? $("av-pkg-price").value : null,
            seats_per_slot: Number($("av-pkg-seats").value),
            seats_by_party: $("av-pkg-by-party").checked,
            enabled: $("av-pkg-enabled").checked
        };
        $("av-pkg-save").disabled = true;
        const editing = state.editing;
        const saved = editing
            ? await request("PATCH", "/api/bookings/packages/" + editing.id, Object.assign({ expected_version: editing.version }, body))
            : await request("POST", "/api/bookings/packages", Object.assign({ chatbot_id: chatbotId() }, body));
        let result = saved;
        if (saved.ok) {
            result = await request("PUT", "/api/bookings/packages/" + saved.data.package.id + "/hours", { hours: hours.hours });
        }
        $("av-pkg-save").disabled = false;
        if (!result.ok) { packageError(result.message); return; }
        closePackage();
        await afterWrite(result, "Package saved. Its bookable times are updated.");
    }

    // --- times, closed dates, settings -----------------------------------------------------

    async function toggleSlot(slot) {
        const result = await request("PATCH", "/api/bookings/slots/" + slot.id, {
            chatbot_id: chatbotId(), expected_version: slot.version, status: slot.status === "closed" ? "open" : "closed"
        });
        await afterWrite(result, slot.status === "closed" ? "Time reopened." : "Time closed. Existing bookings are kept.");
    }

    async function addSlot(event) {
        event.preventDefault();
        const seats = $("av-slot-seats").value;
        const result = await request("POST", "/api/bookings/slots", {
            package_id: Number($("av-slot-package").value),
            starts_at: apiMoment($("av-slot-when").value),
            capacity: seats ? Number(seats) : null
        });
        if (await afterWrite(result, "Extra time added.")) $("av-slot-form").reset();
    }

    async function addClosure(event) {
        event.preventDefault();
        const result = await request("POST", "/api/bookings/closures", {
            chatbot_id: chatbotId(), closed_on: $("av-closure-date").value, reason: $("av-closure-reason").value || null
        });
        if (await afterWrite(result, "Date closed. Customers can't book that day.")) $("av-closure-form").reset();
    }

    async function removeClosure(closure) {
        const result = await request("DELETE", "/api/bookings/closures/" + closure.id);
        await afterWrite(result, "Date reopened.");
    }

    async function toggleAutoConfirm() {
        const box = $("av-auto-confirm");
        const wanted = box.checked;
        box.disabled = true;
        const result = await request("PUT", "/api/bookings/availability/settings", { chatbot_id: chatbotId(), auto_confirm: wanted });
        box.disabled = !state.isAdmin;
        if (!result.ok) { box.checked = !wanted; note(result.message); return; }
        note(wanted ? "Free seats are now booked instantly." : "Bookings now wait for your team to confirm. The seat is held meanwhile.");
    }

    function start() {
        let role = "";
        try { role = JSON.parse(sessionStorage.getItem("user") || "{}").role || ""; } catch (_) { role = ""; }
        state.isAdmin = role === "owner" || role === "admin";
        $("av-add-package").disabled = !state.isAdmin;
        $("av-add-package").addEventListener("click", function () { openPackage(null); });
        $("av-pkg-form").addEventListener("submit", savePackage);
        $("av-pkg-close").addEventListener("click", closePackage);
        $("av-pkg-cancel").addEventListener("click", closePackage);
        $("av-pkg-price-mode").addEventListener("change", syncPriceField);
        $("av-slot-form").addEventListener("submit", addSlot);
        $("av-closure-form").addEventListener("submit", addClosure);
        $("av-auto-confirm").addEventListener("change", toggleAutoConfirm);
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && window.kwDialog.isOpen($("av-package-modal"))) closePackage();
        });
        load();
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})();
