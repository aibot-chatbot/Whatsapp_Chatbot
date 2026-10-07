(function () {
    "use strict";
    const $ = id => document.getElementById(id);
    const PLATFORM_LABELS = { chatgpt: "ChatGPT", gemini: "Gemini", perplexity: "Perplexity" };
    const state = { capabilities: null, busy: false };

    function list(value, separator) {
        return value.split(separator).map(item => item.trim()).filter(Boolean);
    }

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
        $("geo-banner-text").textContent = message;
        $("geo-banner").hidden = !message;
        $("geo-banner").classList.toggle("kw-banner-error", Boolean(error));
    }

    function metric(label, value, note) {
        const node = document.createElement("div");
        node.className = "geo-metric";
        const caption = document.createElement("span");
        caption.textContent = label;
        const figure = document.createElement("strong");
        figure.textContent = value;
        node.append(caption, figure);
        if (note) {
            const detail = document.createElement("small");
            detail.textContent = note;
            node.appendChild(detail);
        }
        return node;
    }

    function renderPlatformSummary(metrics, methodology) {
        const root = $("geo-platform-summary");
        const correctedCitationMetric = methodology?.version === "deterministic-v3" || metrics.owned_citation_rate != null;
        root.replaceChildren();
        Object.entries(metrics.platform_summary || {}).forEach(([platform, values]) => {
            const row = document.createElement("article");
            const label = document.createElement("strong");
            label.textContent = PLATFORM_LABELS[platform] || platform;
            const bars = document.createElement("div");
            bars.className = "geo-platform-bars";
            [["Mention", values.mention_rate], ["Citation", correctedCitationMetric ? values.citation_rate : "—"],
                ["Owned source", values.owned_citation_rate ?? values.citation_rate], ["Recommended", values.recommendation_rate]].forEach(([name, value]) => {
                const item = document.createElement("div");
                const text = document.createElement("span");
                text.textContent = value === "—" ? `${name} —` : `${name} ${value}%`;
                const track = document.createElement("i");
                const fill = document.createElement("b");
                fill.style.width = `${Math.max(0, Math.min(100, Number(value) || 0))}%`;
                track.appendChild(fill);
                item.append(text, track);
                bars.appendChild(item);
            });
            const sample = document.createElement("small");
            sample.textContent = `${values.successful_samples}/${values.samples} checks completed`;
            row.append(label, bars, sample);
            root.appendChild(row);
        });
        if (!root.childNodes.length) root.textContent = "No platform evidence is available.";
    }

    function renderFindings(metrics) {
        const root = $("geo-findings");
        root.replaceChildren();
        const findings = metrics.findings || [];
        if (!findings.length) {
            const empty = document.createElement("p");
            empty.className = "geo-finding-empty";
            empty.textContent = "No deterministic gaps were detected in this small sample. Run the same prompt set again later before treating the result as a trend.";
            root.appendChild(empty);
            return;
        }
        findings.forEach((finding, index) => {
            const card = document.createElement("article");
            card.className = `geo-finding geo-finding-${finding.priority || "medium"}`;
            const number = document.createElement("span");
            number.textContent = String(index + 1).padStart(2, "0");
            const body = document.createElement("div");
            const meta = document.createElement("div");
            meta.className = "geo-finding-meta";
            const priority = document.createElement("em");
            priority.textContent = `${finding.priority || "medium"} priority`;
            const target = document.createElement("span");
            target.textContent = finding.metric || "GEO visibility";
            meta.append(priority, target);
            const title = document.createElement("strong");
            title.textContent = finding.title;
            const summary = document.createElement("p");
            summary.textContent = finding.summary;
            body.append(meta, title, summary);
            const actions = document.createElement("ul");
            (finding.actions || []).forEach(action => {
                const item = document.createElement("li");
                item.textContent = action;
                actions.appendChild(item);
            });
            if (actions.childNodes.length) body.appendChild(actions);
            const evidence = document.createElement("small");
            const examples = (finding.evidence || []).map(item => {
                const parts = [];
                if (item.platform || item.prompt) parts.push(`${PLATFORM_LABELS[item.platform] || item.platform || "Source"}: ${item.prompt || "measured answer"}`);
                if (item.competitors?.length) parts.push(`competitors ${item.competitors.join(", ")}`);
                if (item.domains?.length) parts.push(`sources ${item.domains.join(", ")}`);
                if (item.error_code) parts.push(`error ${item.error_code}`);
                return parts.join(" — ");
            }).filter(Boolean);
            if (examples.length) evidence.textContent = `Evidence: ${examples.join(" · ")}`;
            if (evidence.textContent) body.appendChild(evidence);
            card.append(number, body);
            root.appendChild(card);
        });
    }

    function renderMatrix(analysis) {
        const head = $("geo-matrix-head");
        const body = $("geo-matrix-body");
        head.replaceChildren();
        body.replaceChildren();
        const executions = analysis.executions || [];
        const platforms = analysis.platforms || [...new Set(executions.map(row => row.platform))];
        const prompts = analysis.prompts || [...new Set(executions.map(row => row.prompt))];
        const headRow = document.createElement("tr");
        const promptHeading = document.createElement("th");
        promptHeading.scope = "col";
        promptHeading.textContent = "Buyer prompt";
        headRow.appendChild(promptHeading);
        platforms.forEach(platform => {
            const th = document.createElement("th");
            th.scope = "col";
            th.textContent = PLATFORM_LABELS[platform] || platform;
            headRow.appendChild(th);
        });
        head.appendChild(headRow);
        prompts.forEach((prompt, promptIndex) => {
            const row = document.createElement("tr");
            const promptCell = document.createElement("th");
            promptCell.scope = "row";
            promptCell.textContent = prompt;
            row.appendChild(promptCell);
            platforms.forEach(platform => {
                const cell = document.createElement("td");
                const execution = executions.find(item => item.prompt_index === promptIndex && item.platform === platform);
                if (!execution || execution.request_status !== "complete") {
                    cell.className = "geo-cell-failed";
                    cell.textContent = execution ? "Failed" : "No data";
                } else {
                    const signals = [
                        ["Mention", execution.brand_mentioned],
                        ["Cited", (execution.citations || []).length > 0],
                        ["Owned source", (execution.owned_citation_count || 0) > 0],
                        ["Recommended", execution.recommendation_position != null]
                    ];
                    signals.forEach(([label, active]) => {
                        const chip = document.createElement("span");
                        chip.className = active ? "geo-signal is-positive" : "geo-signal";
                        chip.textContent = `${active ? "✓" : "–"} ${label}`;
                        cell.appendChild(chip);
                    });
                }
                row.appendChild(cell);
            });
            body.appendChild(row);
        });
    }

    function renderEvidence(executions) {
        const root = $("geo-evidence");
        root.replaceChildren();
        executions.forEach(execution => {
            const card = document.createElement("article");
            card.className = "geo-execution";
            const head = document.createElement("div");
            head.className = "geo-execution-head";
            const title = document.createElement("strong");
            title.textContent = execution.prompt;
            const meta = document.createElement("span");
            meta.className = "geo-execution-meta";
            meta.textContent = `${PLATFORM_LABELS[execution.platform] || execution.platform} · ${execution.model} · ${execution.request_status}`;
            head.append(title, meta);
            const response = document.createElement("p");
            response.className = "geo-response";
            response.textContent = execution.raw_response || (execution.error_code === "provider_not_configured" ? "Provider API key is not configured." : "This provider check failed.");
            card.append(head, response);
            const citations = document.createElement("div");
            citations.className = "geo-citations";
            (execution.citations || []).forEach((citation, index) => {
                const link = document.createElement("a");
                link.href = citation.url;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = `${index + 1}. ${citation.title || citation.domain || "Source"}`;
                citations.appendChild(link);
            });
            if (citations.childNodes.length) card.appendChild(citations);
            root.appendChild(card);
        });
        if (!root.childNodes.length) root.textContent = "No prompt evidence was stored for this check.";
    }

    function renderResult(analysis) {
        const metrics = analysis.metrics || {};
        const method = analysis.methodology || {};
        const correctedCitationMetric = method.version === "deterministic-v3" || metrics.owned_citation_rate != null;
        const breakdown = metrics.score_breakdown || {};
        const contribution = key => breakdown[key] ? `${breakdown[key].points} / ${breakdown[key].weight} points` : "Not available for older runs";
        $("geo-results").hidden = false;
        $("geo-result-status").textContent = analysis.status || "unknown";
        $("geo-result-context").textContent = `${analysis.brand_name} · ${analysis.country} · ${new Date(analysis.created_at).toLocaleString()}`;
        $("geo-metrics").replaceChildren(
            metric("GEO score", `${metrics.geo_score ?? 0}`, "Deterministic / 100"),
            metric("Mention rate", `${metrics.mention_rate ?? 0}%`, contribution("mention")),
            metric("Citation rate", correctedCitationMetric ? `${metrics.citation_rate ?? 0}%` : "—", correctedCitationMetric ? contribution("citation") : "Not stored in v2 runs"),
            metric("Owned source rate", `${metrics.owned_citation_rate ?? metrics.citation_rate ?? 0}%`, "Diagnostic · not scored"),
            metric("Recommendation", `${metrics.recommendation_rate ?? 0}%`, contribution("recommendation")),
            metric("Share of voice", `${metrics.share_of_voice ?? 0}%`),
            metric("Prompt coverage", `${metrics.prompt_coverage ?? 0}%`)
        );
        renderPlatformSummary(metrics, method);
        renderFindings(metrics);
        renderMatrix(analysis);
        renderEvidence(analysis.executions || []);
        const interval = metrics.mention_rate_confidence_interval || { lower: 0, upper: 100 };
        $("geo-method").textContent = `${method.formula || "Deterministic scoring"}. ${metrics.successful_samples ?? 0}/${metrics.sample_size ?? 0} checks completed; 95% mention-rate interval ${interval.lower}%–${interval.upper}%. ${method.notes || "Small samples can vary between runs."}`;
        $("geo-results").scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function renderHistory(rows) {
        const root = $("geo-history");
        root.replaceChildren();
        if (!rows.length) {
            const empty = document.createElement("p");
            empty.className = "kw-help";
            empty.textContent = "No GEO checks yet.";
            root.appendChild(empty);
            return;
        }
        rows.forEach(row => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "geo-history-button";
            const title = document.createElement("strong");
            title.textContent = row.brand_name;
            const meta = document.createElement("span");
            meta.textContent = `${new Date(row.created_at).toLocaleDateString()} · ${row.status} · score ${row.metrics?.geo_score ?? "—"}`;
            button.append(title, meta);
            button.addEventListener("click", async () => {
                try { renderResult(await json(`/api/geo/analyses/${row.id}`)); }
                catch (error) { banner(error.message, true); }
            });
            root.appendChild(button);
        });
    }

    function selectedPlatforms() {
        return Array.from(document.querySelectorAll('input[name="geo-platform"]:checked')).map(input => input.value);
    }

    function updateExecutionCount() {
        const promptCount = list($("geo-prompts").value, /\r?\n/).length;
        const platformCount = selectedPlatforms().length;
        const count = promptCount * platformCount;
        const limits = state.capabilities?.limits || {};
        const remaining = state.capabilities?.usage?.remaining ?? 0;
        $("geo-prompt-counter").textContent = `${promptCount} / ${limits.prompts ?? "—"}`;
        if (count) {
            $("geo-run-equation").textContent = `${promptCount} question${promptCount === 1 ? "" : "s"} × ${platformCount} AI model${platformCount === 1 ? "" : "s"} = ${count} provider check${count === 1 ? "" : "s"}`;
            $("geo-cost-preview").textContent = `${remaining} checks remain in your monthly allowance.`;
        } else {
            $("geo-run-equation").textContent = "Choose a model and add a question";
            $("geo-cost-preview").textContent = "We will show the exact provider-check cost before you run.";
        }
        $("geo-submit").disabled = state.busy || count === 0 || count > (limits.executions || 0) || count > remaining || promptCount > (limits.prompts || 0);
    }

    function setRunButtonLabel(label) {
        const text = $("geo-submit").querySelector("span");
        if (text) text.textContent = label;
        else $("geo-submit").textContent = label;
    }

    function payload() {
        return {
            brand_name: $("geo-brand").value.trim(),
            aliases: list($("geo-aliases").value, ","),
            competitors: list($("geo-competitors").value, ","),
            owned_domains: list($("geo-domains").value, ","),
            country: $("geo-country").value.trim().toUpperCase(),
            language: $("geo-language").value,
            platforms: selectedPlatforms(),
            prompts: list($("geo-prompts").value, /\r?\n/),
            samples_per_prompt: 1
        };
    }

    function applyCapabilities(capabilities) {
        state.capabilities = capabilities;
        $("geo-plan-pill").textContent = `${capabilities.plan.label} GEO`;
        const limit = capabilities.limits.monthly_executions;
        const used = capabilities.usage.used;
        $("geo-usage-label").textContent = `${used} / ${limit}`;
        $("geo-usage-bar").style.width = `${Math.min(100, used / Math.max(limit, 1) * 100)}%`;
        $("geo-usage-reset").textContent = `${capabilities.usage.remaining} remaining · resets ${new Date(capabilities.usage.resets_at).toLocaleDateString()}`;
        $("geo-prompt-help").textContent = `Up to ${capabilities.limits.prompts} question${capabilities.limits.prompts === 1 ? "" : "s"} per analysis on this plan.`;
        Object.entries(capabilities.platforms || {}).forEach(([platform, access]) => {
            const input = document.querySelector(`input[name="geo-platform"][value="${platform}"]`);
            const label = document.querySelector(`[data-provider="${platform}"]`);
            const row = document.querySelector(`[data-platform-row="${platform}"]`);
            input.checked = access.included && access.configured;
            input.disabled = !access.included || !access.configured;
            row.classList.toggle("is-disabled", input.disabled);
            if (!access.included) {
                label.textContent = "Upgrade";
                label.className = "geo-provider-plan";
            } else if (!access.configured) {
                label.textContent = "Setup required";
                label.className = "geo-provider-off";
            } else {
                label.textContent = "Ready";
                label.className = "geo-provider-ready";
            }
        });
        updateExecutionCount();
    }

    async function loadHistory() {
        const limit = state.capabilities?.limits?.history || 10;
        renderHistory(await json(`/api/geo/analyses?limit=${limit}`));
    }

    async function initialise() {
        banner("");
        try {
            applyCapabilities(await json("/api/geo/capabilities"));
            $("geo-workspace").hidden = false;
            await loadHistory();
        } catch (error) {
            if (error.status === 403 && ["feature_not_available", "no_subscription"].includes(error.code)) {
                $("geo-locked").hidden = false;
                $("geo-plan-pill").textContent = "Upgrade required";
                return;
            }
            banner(error.message, true);
        }
    }

    $("geo-form").addEventListener("submit", async event => {
        event.preventDefault();
        if (state.busy) return;
        const body = payload();
        if (!body.platforms.length) { banner("Configure and choose at least one included AI-search platform.", true); return; }
        state.busy = true;
        $("geo-submit").disabled = true;
        setRunButtonLabel("Collecting evidence…");
        banner("Running provider checks and saving their responses and citations. Keep this page open.", false);
        try {
            const result = await json("/api/geo/analyses", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
            banner(result.status === "complete" ? "Visibility check completed." : "Check completed with provider failures. Review the evidence below.", result.status === "failed");
            renderResult(result);
            applyCapabilities(await json("/api/geo/capabilities"));
            await loadHistory();
        } catch (error) {
            banner(error.message, true);
        } finally {
            state.busy = false;
            setRunButtonLabel("Run GEO analysis");
            updateExecutionCount();
        }
    });
    $("geo-retry").addEventListener("click", initialise);
    $("geo-prompts").addEventListener("input", updateExecutionCount);
    document.querySelectorAll("[data-prompt-example]").forEach(button => button.addEventListener("click", () => {
        const example = button.dataset.promptExample;
        const prompts = list($("geo-prompts").value, /\r?\n/);
        const limit = state.capabilities?.limits?.prompts || 0;
        if (prompts.includes(example)) return;
        if (limit && prompts.length >= limit) {
            banner(`Your plan allows ${limit} question${limit === 1 ? "" : "s"} per analysis. Replace an existing question to use this example.`, true);
            return;
        }
        $("geo-prompts").value = [...prompts, example].join("\n");
        $("geo-prompts").focus();
        updateExecutionCount();
    }));
    document.querySelectorAll('input[name="geo-platform"]').forEach(input => input.addEventListener("change", updateExecutionCount));
    initialise();
})();
