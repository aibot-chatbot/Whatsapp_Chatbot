(function () {
    "use strict";
    const $ = id => document.getElementById(id);
    let busy = false;
    let requestKey = null;

    async function json(url, options) {
        const response = await authenticatedFetch(url, options);
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(body.message || "Request failed. Please try again.");
            error.status = response.status;
            error.code = body.code;
            throw error;
        }
        return body.data;
    }

    function banner(message, error) {
        $("route-banner-text").textContent = message;
        $("route-banner").hidden = !message;
        $("route-banner").classList.toggle("kw-banner-error", Boolean(error));
    }

    function setBusy(value) {
        busy = value;
        $("route-submit").disabled = value;
        ["route-prompt", "route-country", "route-language"].forEach(id => { $(id).disabled = value; });
        $("route-submit").querySelector("span").textContent = value ? "Running two searches…" : "Run route comparison";
    }

    function renderPath(id, values) {
        const root = $(id);
        root.replaceChildren();
        (values || []).forEach((value, index) => {
            const span = document.createElement("span");
            span.textContent = value;
            root.appendChild(span);
            if (index < values.length - 1) {
                const arrow = document.createElement("i");
                arrow.textContent = "→";
                root.appendChild(arrow);
            }
        });
    }

    function renderCitations(id, citations) {
        const root = $(id);
        root.replaceChildren();
        if (!citations?.length) {
            const empty = document.createElement("span");
            empty.textContent = "No provider citation returned.";
            root.appendChild(empty);
            return;
        }
        citations.forEach((citation, index) => {
            const link = document.createElement("a");
            link.href = citation.url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = `${index + 1}. ${citation.domain || citation.title || citation.url}`;
            root.appendChild(link);
        });
    }

    function renderRoute(prefix, result) {
        const complete = result.request_status === "complete";
        const status = $(`route-${prefix}-status`);
        status.textContent = complete ? "Complete" : (result.error_code || "Failed").replaceAll("_", " ");
        status.className = complete ? "is-complete" : "is-failed";
        $(`route-${prefix}-card`).classList.toggle("is-failed", !complete);
        $(`route-${prefix}-model`).textContent = result.model || "—";
        $(`route-${prefix}-latency`).textContent = Number.isFinite(result.latency_ms) ? `${result.latency_ms} ms` : "—";
        $(`route-${prefix}-citation-count`).textContent = String(result.citations?.length || 0);
        $(`route-${prefix}-cost`).textContent = Number.isFinite(result.cost_usd) ? `$${result.cost_usd.toFixed(5)}` : "Not reported";
        const failureMessages = {
            provider_empty_response: "OpenRouter completed the request but returned no visible answer. Please retry with a shorter question.",
            provider_output_truncated: "OpenRouter used the output budget before producing its final answer. Please retry with a shorter question.",
            provider_http_401: "The provider rejected the configured API key.",
            provider_http_402: "The provider account has insufficient API credit.",
            provider_http_429: "The provider rate limit was reached. Please wait and retry.",
            provider_moderation_block: "The provider's safety filter refused this prompt. Change the wording before you run it again."
        };
        $(`route-${prefix}-answer`).textContent = result.raw_response
            || failureMessages[result.error_code]
            || "The provider could not return an answer. Check the status above and retry.";
        renderPath(`route-${prefix}-path`, result.provider_metadata?.route || []);
        renderCitations(`route-${prefix}-citations`, result.citations || []);
    }

    function render(data) {
        $("route-results").hidden = false;
        $("route-result-context").textContent = `“${data.prompt}” · ${data.country} · ${data.language.toUpperCase()}`;
        $("route-answer-overlap").textContent = `${data.comparison.answer_term_overlap_percent}%`;
        $("route-source-overlap").textContent = `${data.comparison.citation_domain_overlap_percent}%`;
        renderRoute("direct", data.direct);
        renderRoute("openrouter", data.openrouter);
        const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        $("route-results").scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    }

    async function initialise() {
        try {
            const capabilities = await json("/api/geo/capabilities");
            const comparison = capabilities.comparison || {};
            if (!comparison.enabled) {
                const missing = [];
                if (!comparison.direct_openai_configured) missing.push("OPENAI_API_KEY");
                if (!comparison.openrouter_configured) missing.push("OPENROUTER_API_KEY");
                banner(`Comparison setup required: add ${missing.join(" and ")} to the backend environment.`, true);
                $("route-submit").disabled = true;
            }
        } catch (error) {
            banner(error.status === 403 ? "This comparison is available to Essential, Advanced and Pro workspaces." : error.message, true);
            $("route-submit").disabled = true;
        }
    }

    $("route-prompt").addEventListener("input", () => {
        $("route-prompt-count").textContent = $("route-prompt").value.length;
        if (!busy) requestKey = null;
    });
    ["route-country", "route-language"].forEach(id => {
        $(id).addEventListener("change", () => { if (!busy) requestKey = null; });
    });
    $("route-form").addEventListener("submit", async event => {
        event.preventDefault();
        if (busy) return;
        requestKey ||= crypto.randomUUID();
        setBusy(true);
        banner("Running the same prompt through both routes. This reserves two monthly provider checks.", false);
        try {
            const data = await json("/api/geo/provider-comparison", {
                method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": requestKey },
                body: JSON.stringify({ prompt: $("route-prompt").value.trim(),
                    country: $("route-country").value.trim().toUpperCase(), language: $("route-language").value })
            });
            render(data);
            requestKey = null;
            banner("Comparison complete. Two provider checks were recorded. Review the evidence below.", false);
        } catch (error) {
            banner(error.message, true);
        } finally {
            setBusy(false);
        }
    });
    $("route-prompt-count").textContent = $("route-prompt").value.length;
    initialise();
})();
