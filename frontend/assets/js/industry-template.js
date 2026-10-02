/* Industry confirmation is independent of profile and channel publication. */
window.IndustryTemplatePanel = (() => {
    "use strict";

    function init({ chatbotId, fetch: authenticatedFetch }) {
        const node = name => document.getElementById(`bc-industry-${name}`);
        const endpoint = `/api/settings/industry-template?chatbot_id=${encodeURIComponent(chatbotId)}`;
        const select = node("select");
        let data = null;
        let busy = false;
        let loaded = false;
        let stale = false;
        let action = "";

        function confirmed() {
            return Boolean(data?.draft && data?.published && data.draft.proposal_id === data.published.proposal_id);
        }

        function selectedTemplate() {
            return data?.templates.find(template => template.id === select.value);
        }

        function list(name, values, fallback) {
            const items = Array.isArray(values) ? values.filter(value => typeof value === "string" && value.trim()) : [];
            node(name).replaceChildren(...(items.length ? items : [fallback]).map(value => {
                const item = document.createElement("li");
                item.textContent = value;
                return item;
            }));
        }

        function controls() {
            node("panel").setAttribute("aria-busy", String(busy));
            node("fields").disabled = busy || !loaded || stale || !data?.draft || data.can_confirm !== true;
            node("confirm").disabled = node("fields").disabled || !selectedTemplate();
            node("confirm").textContent = action === "confirm" ? "Applying…" : "Confirm and apply industry";
            node("change").hidden = !confirmed();
            node("change").disabled = busy || !loaded || stale;
            node("change").textContent = action === "review" ? "Preparing…" : "Change industry";
            node("reload").disabled = busy;
        }

        function preview() {
            const template = selectedTemplate();
            node("description").textContent = template?.description || "Choose an industry to review its guidance before confirming.";
            node("details").hidden = !template;
            list("questions", template?.questions, "No suggested questions.");
            list("checklist", template?.required_information, "No additional checklist.");
            list("unavailable", template?.unavailable_actions, "No additional actions listed.");
            controls();
        }

        function render(next) {
            next = {
                ...next,
                draft: typeof next.draft?.proposal_id === "string" && next.draft.proposal_id.trim() ? next.draft : null,
                published: next.templates.some(template => template.id === next.published?.template_id) ? next.published : null
            };
            const previousSelection = data?.draft?.proposal_id === next.draft?.proposal_id ? select.value : "";
            data = next;
            const draft = data.draft;
            const published = data.published;
            const active = data.templates.find(template => template.id === published?.template_id);
            node("published").textContent = published
                ? `Currently applied: ${active?.name || "Industry guidance"}.`
                : "No industry guidance has been applied.";
            node("status").textContent = !draft
                ? "No industry suggestion is ready. Upload a readable primary document, then reload the suggestion."
                : confirmed()
                    ? "Industry guidance is confirmed and applied."
                    : draft.status === "suggested"
                        ? "Suggested industry — review and confirm before it affects replies."
                        : "We could not confidently identify one industry. Choose the best fit and review its guidance before confirming.";
            if (draft && !confirmed() && data.can_confirm !== true) {
                node("status").textContent += " Confirmation is unavailable for this suggestion.";
            }
            node("source").textContent = typeof draft?.source_path === "string"
                ? draft.source_path.split(/[\\/]/).pop() : "No source document available";
            list("evidence", draft?.evidence, "No supporting evidence was returned.");
            select.replaceChildren(new Option("Choose an industry", ""), ...data.templates.map(template => new Option(template.name, template.id)));
            const selection = previousSelection || draft?.template_id || "";
            select.value = data.templates.some(template => template.id === selection) ? selection : "";
            preview();
        }

        function errorMessage(status, confirming) {
            if (status === 409) return "The document or suggestion changed. Reload the industry suggestion before confirming again.";
            if (status === 503) return "Industry suggestions are unavailable right now. Try again or reload the suggestion.";
            if (status === 403) return "You do not have permission to confirm this industry suggestion.";
            if (status === 400) return "This industry choice could not be applied. Review your selection and try again.";
            return confirming
                ? "We could not confirm the industry guidance. Your choice is kept; try again."
                : "We could not load the industry suggestion. Reload to try again.";
        }

        async function request(url, options) {
            const response = await authenticatedFetch(url, options);
            const body = await response.json().catch(() => null);
            if (!response.ok || body?.status !== "success" || !body.data || !Array.isArray(body.data.templates)) {
                const error = new Error("Industry request failed");
                error.status = response.status;
                throw error;
            }
            return body.data;
        }

        async function load() {
            if (busy) return;
            busy = true;
            loaded = false;
            node("error").textContent = "";
            controls();
            try {
                const next = await request(endpoint);
                loaded = true;
                stale = false;
                render(next);
            } catch (error) {
                node("status").textContent = "Industry suggestion could not be checked.";
                node("error").textContent = errorMessage(error.status, false);
            } finally {
                busy = false;
                controls();
            }
        }

        async function confirm(event) {
            event.preventDefault();
            if (busy || !loaded || stale || !data?.draft || data.can_confirm !== true || !selectedTemplate()) return;
            busy = true;
            action = "confirm";
            node("error").textContent = "";
            controls();
            try {
                const next = await request(endpoint.replace("?", "/confirm?"), {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ proposal_id: data.draft.proposal_id, template_id: select.value })
                });
                render(next);
                node("status").textContent = "Industry guidance is confirmed and applied to replies.";
            } catch (error) {
                stale = error.status === 409;
                if (error.status === 403) loaded = false;
                node("error").textContent = errorMessage(error.status, true);
            } finally {
                busy = false;
                action = "";
                controls();
            }
        }

        async function review() {
            if (busy || !loaded || stale || !confirmed()) return;
            const currentIndustry = data.published.template_id;
            busy = true;
            action = "review";
            node("error").textContent = "";
            controls();
            try {
                const next = await request(endpoint.replace("?", "/review?"), {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ proposal_id: data.draft.proposal_id })
                });
                render(next);
                if (data.templates.some(template => template.id === currentIndustry)) select.value = currentIndustry;
                preview();
                node("status").textContent = "Choose an industry and confirm the change. The currently applied guidance stays active until you confirm.";
            } catch (error) {
                stale = error.status === 409;
                if (error.status === 403) loaded = false;
                node("error").textContent = [400, 403, 409, 503].includes(error.status)
                    ? errorMessage(error.status, false)
                    : "We could not prepare a new industry draft. Your applied guidance stays active; try again.";
            } finally {
                busy = false;
                action = "";
                controls();
            }
        }

        select.addEventListener("change", preview);
        node("form").addEventListener("submit", confirm);
        node("reload").addEventListener("click", load);
        node("change").addEventListener("click", review);
        load();
    }

    return { init };
})();
