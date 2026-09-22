(function () {
    "use strict";
    const $ = id => document.getElementById(id);
    const time = value => new Date(value).toLocaleString("en-MY", {timeZone: "Asia/Kuala_Lumpur"});
    function el(tag, text) { const node = document.createElement(tag); if (text != null) node.textContent = text; return node; }
    let blocked = false, initialized = false, updateBlocked = () => {};
    window.WidgetTuition = {
        setBlocked(value) { blocked = value; updateBlocked(); },
        init(publicKey, sessionToken) {
            if (initialized) return;
            initialized = true;
            const dialog = $("trial-dialog"), form = $("trial-prepare-form"), participantForm = $("trial-participant-form");
            let catalog = {participants: [], sessions: [], bookings: []}, pending = null, bookingId = null, busy = false, participantKey = null;
            const cancelKeys = new Map();
            function status(message, error = false) { $("trial-status").textContent = message; $("trial-status").dataset.error = String(error); }
            async function api(action, fields = {}) {
                const response = await fetch(`/api/widget/${encodeURIComponent(publicKey)}/tuition`, {method: "POST", credentials: "omit", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action, session_id_token: sessionToken, ...fields})});
                const body = await response.json();
                if (!response.ok) { const error = new Error(body.message || "Trial booking is unavailable."); error.code = body.code; error.status = response.status; throw error; }
                return body.data;
            }
            function clearReview() { pending = null; $("trial-review").hidden = true; }
            function controls() {
                dialog.querySelectorAll("button").forEach(button => { if (button.id !== "close-trials") button.disabled = busy || blocked; });
                form.elements.participant_id.disabled = busy || blocked || !!bookingId;
                form.elements.session_id.disabled = busy || blocked;
                participantForm.elements.label.disabled = busy || blocked || !!bookingId;
                participantForm.querySelector("button").disabled = busy || blocked || !!bookingId;
            }
            updateBlocked = () => { if (blocked) { clearReview(); status("A staff member is handling this conversation. Ask them to help with your trial.", true); } controls(); };
            function showError(error) {
                if (error.code === "tuition_human_controlled") { blocked = true; updateBlocked(); return; }
                if (error.status === 409) { clearReview(); status("The session changed or has no available places. Review the latest sessions and confirm again." + (bookingId ? " Your original booking is unchanged." : " No new booking was confirmed."), true); }
                else status(error.message || "The response could not be confirmed. Retry the same action or refresh your bookings.", true);
            }
            async function act(task) {
                if (busy || blocked) return;
                busy = true; controls();
                try { await task(); } catch (error) { showError(error); }
                finally { busy = false; controls(); if (pending && !blocked) $("trial-confirm").focus(); }
            }
            function sessionLabel(session) { return `${session.course_name || "Trial lesson"} · ${session.class_name || "Class"} · ${time(session.starts_at)}`; }
            function render() {
                const selectedParticipant = form.elements.participant_id.value, selectedSession = form.elements.session_id.value;
                form.elements.participant_id.replaceChildren(new Option("Choose a participant", ""));
                for (const row of catalog.participants) form.elements.participant_id.add(new Option(row.label, row.id));
                if (catalog.participants.some(row => row.id === selectedParticipant)) form.elements.participant_id.value = selectedParticipant;
                form.elements.session_id.replaceChildren(new Option(catalog.sessions.length ? "Choose a session" : "No upcoming sessions", ""));
                for (const row of catalog.sessions) {
                    const option = new Option(`${sessionLabel(row)} · ${row.available_trial_seats} places`, row.id);
                    option.disabled = row.available_trial_seats <= 0; form.elements.session_id.add(option);
                }
                if (catalog.sessions.some(row => row.id === selectedSession && row.available_trial_seats > 0)) form.elements.session_id.value = selectedSession;
                $("trial-bookings").replaceChildren();
                for (const booking of catalog.bookings) {
                    const article = el("article"); article.className = "trial-booking";
                    const session = catalog.sessions.find(row => row.id === booking.session_id);
                    article.append(el("strong", booking.participant_label || catalog.participants.find(row => row.id === booking.participant_id)?.label || "Participant"), el("p", `${booking.status} · ${session ? sessionLabel(session) : "Session " + booking.session_id}`), el("p", "Booking " + booking.id));
                    if (booking.status === "confirmed") {
                        const change = el("button", "Change session"), cancel = el("button", "Cancel booking"); change.type = cancel.type = "button";
                        change.addEventListener("click", () => {
                            clearReview(); bookingId = booking.id; form.elements.participant_id.value = booking.participant_id; form.elements.session_id.value = "";
                            $("trial-reschedule-note").textContent = "Changing booking " + booking.id + ". Your original place stays reserved until the new session is confirmed.";
                            $("trial-reschedule-note").hidden = $("trial-new").hidden = false;
                            controls(); form.elements.session_id.focus();
                        });
                        cancel.addEventListener("click", () => {
                            clearReview(); cancelKeys.set(booking.id, cancelKeys.get(booking.id) || crypto.randomUUID());
                            pending = {action: "cancel", booking_id: booking.id, client_message_id: cancelKeys.get(booking.id), expected_version: booking.version};
                            $("trial-review-details").replaceChildren(el("p", `Cancel booking ${booking.id} for ${booking.participant_label || "this participant"}? This releases the reserved place.`));
                            $("trial-confirm").textContent = "Confirm cancellation"; $("trial-review").hidden = false; $("trial-confirm").focus();
                        });
                        article.append(change, cancel);
                    }
                    $("trial-bookings").append(article);
                }
                if (!catalog.bookings.length) $("trial-bookings").append(el("p", "No bookings in this chat session."));
                controls();
            }
            async function load() {
                const data = await api("list");
                if (!data || !Array.isArray(data.sessions) || !Array.isArray(data.participants) || !Array.isArray(data.bookings)) throw new Error("Trial records are unavailable.");
                catalog = data; render();
            }
            function resetBooking() { clearReview(); bookingId = null; $("trial-reschedule-note").hidden = $("trial-new").hidden = true; controls(); }
            participantForm.addEventListener("submit", event => {
                event.preventDefault();
                const label = participantForm.elements.label.value.trim(); if (!label) return;
                participantKey ||= crypto.randomUUID();
                act(async () => {
                    const participant = await api("participant", {label, client_key: participantKey});
                    participantKey = null; participantForm.reset();
                    catalog.participants = [...catalog.participants.filter(row => row.id !== participant.id), participant]; render();
                    form.elements.participant_id.value = participant.id;
                    clearReview(); status("Participant added to this chat. Choose a trial session.");
                });
            });
            participantForm.elements.label.addEventListener("input", () => { if (!busy) participantKey = null; });
            form.addEventListener("change", clearReview);
            form.addEventListener("submit", event => {
                event.preventDefault();
                act(async () => {
                    clearReview();
                    const result = await api("prepare", {participant_id: form.elements.participant_id.value, session_id: form.elements.session_id.value, ...(bookingId ? {booking_id: bookingId} : {}), reminder_consent: false});
                    if (result.reserved !== false || !result.confirmation_token || !result.participant || !result.session) throw new Error("Unable to review this booking. Refresh and try again.");
                    pending = {action: "confirm", confirmation_token: result.confirmation_token, expires_at: result.expires_at};
                    const session = {...catalog.sessions.find(row => row.id === result.session.id), ...result.session};
                    $("trial-review-details").replaceChildren(el("h3", bookingId ? "Confirm your new session" : "Confirm your trial"), el("p", result.participant.label), el("p", `${sessionLabel(session)} – ${time(session.ends_at)}`), el("p", `No place reserved yet. Confirm before ${time(result.expires_at)}.`));
                    $("trial-confirm").textContent = bookingId ? "Confirm new session" : "Confirm booking"; $("trial-review").hidden = false;
                    status("Review these details. A place is reserved only after you confirm."); $("trial-confirm").focus();
                });
            });
            $("trial-confirm").addEventListener("click", () => act(async () => {
                if (!pending) return;
                const command = {...pending};
                if (command.action === "confirm" && (!Number.isFinite(Date.parse(command.expires_at)) || Date.parse(command.expires_at) <= Date.now())) { clearReview(); status("This confirmation expired. Review the session again.", true); return; }
                const result = await api(command.action, command.action === "confirm" ? {confirmation_token: command.confirmation_token} : {booking_id: command.booking_id, client_message_id: command.client_message_id, expected_version: command.expected_version});
                const booking = command.action === "confirm" ? result.booking : result;
                if (!booking?.id || booking.status !== (command.action === "confirm" ? "confirmed" : "cancelled")) throw new Error("The booking result was not confirmed. Refresh your bookings before trying again.");
                resetBooking();
                catalog.bookings = [booking, ...catalog.bookings.filter(row => row.id !== booking.id)]; render();
                const message = `${command.action === "confirm" ? "Booking confirmed" : "Booking cancelled"}. Reference: ${booking.id}.`;
                status(message);
                try { await load(); } catch (_) { status(message + " Refresh to update the session list."); }
            }));
            $("trial-back").addEventListener("click", clearReview);
            $("trial-new").addEventListener("click", resetBooking);
            $("trial-refresh").addEventListener("click", () => act(async () => { clearReview(); await load(); status("Trial records refreshed."); }));
            $("close-trials").addEventListener("click", () => dialog.close());
            $("open-trials").addEventListener("click", () => { dialog.showModal(); if (blocked) updateBlocked(); else act(async () => { await load(); status("Choose a participant and a session to review."); }); });
            // A read-only capability probe. Disabled or unconfirmed industries get no entry.
            load().then(() => { $("trial-entry").hidden = false; updateBlocked(); }).catch(() => {});
        }
    };
})();
