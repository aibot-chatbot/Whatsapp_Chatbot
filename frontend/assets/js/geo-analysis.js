(function () {
    "use strict";
    const $ = id => document.getElementById(id);
    const PLATFORM_LABELS = {
        chatgpt: "ChatGPT Search", gemini: "Gemini", claude: "Claude", deepseek: "DeepSeek",
        perplexity: "Perplexity"
    };
    const state = { capabilities: null, busy: false, currentAnalysis: null, history: [], keywords: [], monitoring: null };

    function localize(node, key, params, fallback) {
        node.dataset.i18nKey = key;
        node.__omnexaI18nParams = { ...(params || {}) };
        if (window.OmnexaAppPreferences?.text) window.OmnexaAppPreferences.text(node, key, params || {});
        else node.textContent = fallback;
        return node;
    }

    function locale() {
        return window.OmnexaAppPreferences?.getLocale?.() || "en-MY";
    }

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

    function renderPlatformSummary(metrics) {
        const root = $("geo-platform-summary");
        root.replaceChildren();
        Object.entries(metrics.platform_summary || {}).forEach(([platform, values]) => {
            const rolling = metrics.rolling_summary?.platform_summary?.[platform];
            const minimum = rolling?.minimum_reliable_samples || values.minimum_reliable_samples || 3;
            const useRolling = Boolean(rolling && rolling.successful_samples >= minimum);
            const displayValues = useRolling ? rolling : values;
            const row = document.createElement("article");
            row.classList.toggle("is-insufficient", displayValues.successful_samples < minimum);
            const heading = document.createElement("div");
            heading.className = "geo-platform-heading";
            const label = document.createElement("strong");
            label.textContent = PLATFORM_LABELS[platform] || platform;
            const score = document.createElement("b");
            localize(score, "geo.platform.rate", { rate: displayValues.mention_rate ?? 0 }, `${displayValues.mention_rate ?? 0}% mention rate`);
            heading.append(label, score);
            const bars = document.createElement("div");
            bars.className = "geo-platform-bars";
            const averageRank = displayValues.average_mention_rank;
            [[useRolling ? "Rolling mention rate" : "Current mention rate", `${displayValues.mention_rate ?? 0}%`, displayValues.mention_rate],
                ["Average mention rank", averageRank == null ? "No rank evidence" : `#${averageRank}`, displayValues.mention_rank_prominence]].forEach(([name, display, width]) => {
                const item = document.createElement("div");
                const text = document.createElement("span");
                const rateKey = useRolling ? "geo.platform.rolling_rate" : "geo.platform.current_rate";
                if (name.includes("mention rate")) localize(text, rateKey, { rate: displayValues.mention_rate ?? 0 }, `${name} ${display}`);
                else localize(text, "geo.platform.average_rank", { rank: averageRank == null ? "—" : `#${averageRank}` }, `${name} ${display}`);
                const track = document.createElement("i");
                const fill = document.createElement("b");
                fill.style.width = `${Math.max(0, Math.min(100, Number(width) || 0))}%`;
                track.appendChild(fill);
                item.append(text, track);
                bars.appendChild(item);
            });
            const sample = document.createElement("small");
            if (useRolling) {
                localize(sample, "geo.platform.rolling_evidence", { mentioned: displayValues.mentioned_samples,
                    checks: displayValues.successful_samples, analyses: displayValues.analysis_count },
                `Rolling evidence: ${displayValues.mentioned_samples}/${displayValues.successful_samples} mentions across ${displayValues.analysis_count} scans`);
            } else if (values.successful_samples < minimum) {
                localize(sample, "geo.platform.insufficient", { mentioned: values.mentioned_samples,
                    checks: values.successful_samples, minimum },
                `${values.mentioned_samples}/${values.successful_samples} mentions · single-run evidence; repeat later only to build a trend`);
                sample.className = "geo-platform-sample-warning";
            } else {
                localize(sample, "geo.platform.current_evidence", { mentioned: values.mentioned_samples,
                    checks: values.successful_samples }, `${values.mentioned_samples}/${values.successful_samples} mentions in this scan`);
            }
            row.append(heading, bars, sample);
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
            localize(priority, `geo.priority.${finding.priority || "medium"}`, {}, `${finding.priority || "medium"} priority`);
            const platform = document.createElement("span");
            platform.textContent = PLATFORM_LABELS[finding.platform] || finding.platform || "General";
            const score = document.createElement("span");
            score.textContent = finding.score == null ? "No score" : `${finding.score} / 100`;
            meta.append(priority, platform, score);
            const title = document.createElement("strong");
            if (finding.title_key) localize(title, finding.title_key, finding.title_params, finding.title);
            else title.textContent = finding.title;
            const summary = document.createElement("p");
            if (finding.summary_key) localize(summary, finding.summary_key, finding.summary_params, finding.summary);
            else summary.textContent = finding.summary;
            body.append(meta, title, summary);
            const actions = document.createElement("ul");
            const pillars = finding.action_pillars?.length ? finding.action_pillars : (finding.actions || []).map(action => ({ action }));
            if (finding.action_pillars?.length) actions.className = "geo-action-pillars";
            pillars.forEach(pillar => {
                const item = document.createElement("li");
                if (pillar.title) {
                    const pillarTitle = document.createElement("strong");
                    if (pillar.title_key) localize(pillarTitle, pillar.title_key, {}, pillar.title);
                    else pillarTitle.textContent = pillar.title;
                    item.appendChild(pillarTitle);
                }
                const action = document.createElement("p");
                if (pillar.message_key && !pillar.evidence_specific) localize(action, pillar.message_key, pillar.params, pillar.action);
                else action.textContent = pillar.action;
                item.appendChild(action);
                actions.appendChild(item);
            });
            if (actions.childNodes.length) body.appendChild(actions);
            const evidence = document.createElement("small");
            const examples = (finding.evidence || []).map(item => {
                const parts = [];
                if (item.platform || item.prompt) parts.push(`${PLATFORM_LABELS[item.platform] || item.platform || "Source"}: ${item.prompt || "measured answer"}`);
                if (item.domains?.length) parts.push(`sources ${item.domains.join(", ")}`);
                if (item.error_code) parts.push(`error ${item.error_code}`);
                return parts.join(" — ");
            }).filter(Boolean);
            if (examples.length) localize(evidence, "geo.evidence", { examples: examples.join(" · ") }, `Evidence: ${examples.join(" · ")}`);
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
        const prompts = analysis.prompts?.length ? analysis.prompts : [...new Set(executions.map(row => row.prompt))];
        const headRow = document.createElement("tr");
        const promptHeading = document.createElement("th");
        promptHeading.scope = "col";
        const methodology = analysis.methodology;
        const combinedTopic = methodology?.input_type === "keyword_topic"
            || (!methodology?.input_type && methodology?.keywords?.length > 0 && prompts.length === 1);
        localize(promptHeading, combinedTopic ? "geo.matrix.topic" : "geo.matrix.prompt", {}, combinedTopic ? "Keyword topic" : "Buyer prompt");
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
                    localize(cell, execution ? "geo.matrix.failed" : "geo.matrix.no_data", {}, execution ? "Failed" : "No data");
                } else {
                    const mention = document.createElement("span");
                    mention.className = execution.brand_mentioned ? "geo-signal is-positive" : "geo-signal";
                    localize(mention, execution.brand_mentioned ? "geo.matrix.mentioned" : "geo.matrix.not_mentioned", {}, execution.brand_mentioned ? "Mentioned" : "Not mentioned");
                    const rank = document.createElement("span");
                    rank.className = execution.recommendation_position != null ? "geo-signal is-positive" : "geo-signal";
                    const rankKey = execution.recommendation_position != null ? "geo.matrix.rank"
                        : execution.brand_mentioned ? "geo.matrix.rank_unproven" : "geo.matrix.no_rank";
                    const rankParams = execution.recommendation_position != null ? { rank: execution.recommendation_position } : {};
                    localize(rank, rankKey, rankParams, execution.recommendation_position != null
                        ? `Mention rank #${execution.recommendation_position}`
                        : execution.brand_mentioned ? "Mentioned · rank not proven" : "No rank");
                    cell.append(mention, rank);
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
            response.classList.add("notranslate");
            response.setAttribute("translate", "no");
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

    function renderResult(analysis, options = {}) {
        state.currentAnalysis = analysis;
        const metrics = analysis.metrics || {};
        const method = analysis.methodology || {};
        const breakdown = metrics.score_breakdown || {};
        const contribution = key => breakdown[key] ? `${breakdown[key].points} / ${breakdown[key].weight} points` : "Not available for older runs";
        const rolling = metrics.rolling_summary?.overall;
        const minimum = metrics.rolling_summary?.minimum_reliable_samples || metrics.minimum_reliable_samples || 3;
        const hasReliableRolling = Boolean(rolling && rolling.successful_samples >= minimum);
        const rankedMetrics = hasReliableRolling ? rolling : metrics;
        const averageRank = rankedMetrics.average_mention_rank ?? metrics.average_recommendation_position;
        $("geo-results").hidden = false;
        $("geo-result-status").textContent = analysis.status || "unknown";
        localize($("geo-result-context"), "geo.result.context", { brand: analysis.brand_name, country: analysis.country,
            date: new Date(analysis.created_at).toLocaleString(locale()) },
        `${analysis.brand_name} · ${analysis.country} · ${new Date(analysis.created_at).toLocaleString(locale())}`);
        $("geo-metrics").replaceChildren(
            metric("Mention score", `${metrics.geo_score ?? 0}`, "Deterministic / 100"),
            metric("Current mention rate", `${metrics.mention_rate ?? 0}%`, `${metrics.mentioned_samples ?? 0}/${metrics.successful_samples ?? 0} completed checks mentioned the brand`),
            metric("Rolling mention rate", hasReliableRolling ? `${rolling.mention_rate}%` : "Building", hasReliableRolling ? `${rolling.mentioned_samples}/${rolling.successful_samples} mentions across ${rolling.analysis_count} comparable scan${rolling.analysis_count === 1 ? "" : "s"}` : `${rolling?.successful_samples ?? metrics.successful_samples ?? 0}/${minimum} checks collected`),
            metric("Average mention rank", averageRank == null ? "No rank evidence" : `#${averageRank}`, hasReliableRolling ? "Rolling ranked answers" : contribution("mention_rank"))
        );
        renderPlatformSummary(metrics);
        renderFindings(metrics);
        renderMatrix(analysis);
        renderEvidence(analysis.executions || []);
        const interval = metrics.mention_rate_confidence_interval || { lower: 0, upper: 100 };
        const sampleNote = Object.values(metrics.platform_summary || {}).some(item => item.sample_quality === "insufficient")
            ? ` Individual platform results with fewer than ${minimum} checks are directional and marked as insufficient.`
            : "";
        $("geo-method").textContent = `${method.formula || "Mention-focused deterministic scoring"}. ${metrics.successful_samples ?? 0}/${metrics.sample_size ?? 0} checks completed; 95% mention-rate interval ${interval.lower}%–${interval.upper}%.${sampleNote} ${method.notes || "Small samples can vary between runs."}`;
        if (options.scroll !== false) $("geo-results").scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function renderHistory(rows) {
        state.history = rows;
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
            const rank = row.metrics?.average_mention_rank;
            localize(meta, "geo.history.meta", { date: new Date(row.created_at).toLocaleDateString(locale()),
                status: row.status, rate: row.metrics?.mention_rate ?? "—", rank: rank == null ? "—" : `#${rank}` },
            `${new Date(row.created_at).toLocaleDateString(locale())} · ${row.status} · mention ${row.metrics?.mention_rate ?? "—"}% · rank ${rank == null ? "—" : `#${rank}`}`);
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

    function translated(key, params, fallback) {
        const node = document.createElement("span");
        localize(node, key, params || {}, fallback);
        return node.textContent || fallback;
    }

    function keywordLimit() {
        return state.capabilities?.limits?.keywords || 10;
    }

    function clearKeywordError() {
        const error = $("geo-keyword-error");
        error.hidden = true;
        error.textContent = "";
        document.querySelector(".geo-keyword-field")?.classList.remove("has-error");
        $("geo-keyword-input").removeAttribute("aria-invalid");
    }

    function showKeywordError(key, params, fallback) {
        const error = $("geo-keyword-error");
        localize(error, key, params || {}, fallback);
        error.hidden = false;
        document.querySelector(".geo-keyword-field")?.classList.add("has-error");
        $("geo-keyword-input").setAttribute("aria-invalid", "true");
    }

    function normaliseKeyword(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function trackedNames() {
        return [$("geo-brand").value, ...list($("geo-aliases").value, ","), ...list($("geo-competitors").value, ",")]
            .map(value => normaliseKeyword(value).toLocaleLowerCase())
            .filter(Boolean);
    }

    function renderKeywords() {
        const root = $("geo-keyword-list");
        root.replaceChildren();
        state.keywords.forEach((keyword, index) => {
            const chip = document.createElement("span");
            chip.className = "geo-keyword-chip";
            chip.setAttribute("role", "listitem");
            const text = document.createElement("span");
            text.textContent = keyword;
            const remove = document.createElement("button");
            remove.type = "button";
            remove.textContent = "×";
            remove.setAttribute("aria-label", translated("geo.keyword.remove", { keyword }, `Remove ${keyword}`));
            remove.addEventListener("click", () => {
                state.keywords.splice(index, 1);
                clearKeywordError();
                renderKeywords();
                $("geo-keyword-input").focus();
            });
            chip.append(text, remove);
            root.appendChild(chip);
        });
        $("geo-keyword-counter").textContent = `${state.keywords.length} / ${keywordLimit()}`;
        updateExecutionCount();
    }

    function addKeyword(rawValue, options = {}) {
        const keyword = normaliseKeyword(rawValue);
        if (!keyword) return true;
        const limit = keywordLimit();
        if (keyword.length > 80) {
            showKeywordError("geo.keyword.too_long", {}, "Each keyword must contain 80 characters or fewer.");
            return false;
        }
        if (state.keywords.some(item => item.toLocaleLowerCase() === keyword.toLocaleLowerCase())) {
            if (!options.silent) showKeywordError("geo.keyword.duplicate", { keyword }, `“${keyword}” is already added.`);
            return false;
        }
        const containsTrackedName = trackedNames().some(name => {
            const literal = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            return new RegExp(`(?:^|[^\\p{L}\\p{N}_])${literal}(?=$|[^\\p{L}\\p{N}_])`, "iu").test(keyword);
        });
        if (containsTrackedName) {
            showKeywordError("geo.keyword.brand_bias", {}, "Use unbranded category keywords without your brand or competitor names.");
            return false;
        }
        if (state.keywords.length >= limit) {
            showKeywordError("geo.keyword.limit", { limit }, `You can add up to ${limit} keywords.`);
            return false;
        }
        state.keywords.push(keyword);
        clearKeywordError();
        renderKeywords();
        return true;
    }

    function addKeywordBatch(value) {
        const values = String(value || "").split(/[,\r\n]+/).map(normaliseKeyword).filter(Boolean);
        let accepted = true;
        values.forEach(item => { if (!addKeyword(item, { silent: values.length > 1 })) accepted = false; });
        return accepted;
    }

    function flushKeywordInput() {
        const input = $("geo-keyword-input");
        const value = input.value;
        if (!normaliseKeyword(value)) return true;
        if (!addKeywordBatch(value)) return false;
        input.value = "";
        return true;
    }

    function updateExecutionCount() {
        const keywordCount = state.keywords.length;
        const platformCount = selectedPlatforms().length;
        const count = keywordCount * platformCount;
        const limits = state.capabilities?.limits || {};
        const remaining = state.capabilities?.usage?.remaining ?? 0;
        if (count) {
            localize($("geo-run-equation"), "geo.keyword.equation", { keywords: keywordCount, platforms: platformCount, checks: count },
                `Keywords: ${keywordCount} · AI models: ${platformCount} · provider checks: ${count}`);
            localize($("geo-cost-preview"), "geo.keyword.remaining", { remaining },
                `${remaining} checks remain. Each keyword is measured independently on every selected model.`);
        } else {
            localize($("geo-run-equation"), "geo.keyword.empty", {}, "Choose a model and add keywords");
            $("geo-cost-preview").textContent = "We will show the exact provider-check cost before you run.";
        }
        $("geo-submit").disabled = state.busy || count === 0 || count > (limits.executions || 0) || count > remaining || keywordCount > keywordLimit();
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
            keywords: [...state.keywords],
            samples_per_prompt: 1
        };
    }

    function applyCapabilities(capabilities) {
        const firstLoad = !state.capabilities;
        state.capabilities = capabilities;
        $("geo-plan-pill").textContent = `${capabilities.plan.label} GEO`;
        const limit = capabilities.limits.monthly_executions;
        const used = capabilities.usage.used;
        $("geo-usage-label").textContent = `${used} / ${limit}`;
        $("geo-usage-bar").style.width = `${Math.min(100, used / Math.max(limit, 1) * 100)}%`;
        localize($("geo-usage-reset"), "geo.usage.reset", { remaining: capabilities.usage.remaining,
            date: new Date(capabilities.usage.resets_at).toLocaleDateString(locale()) },
        `${capabilities.usage.remaining} remaining · resets ${new Date(capabilities.usage.resets_at).toLocaleDateString(locale())}`);
        localize($("geo-keyword-help"), "geo.keyword.help", { limit: capabilities.limits.keywords || 10 },
            `Add up to ${capabilities.limits.keywords || 10} unbranded category or buyer-intent keywords. Each becomes one natural buyer question sent once to every selected AI model.`);
        const frequencies = new Set(capabilities.limits.monitoring_frequencies || []);
        Array.from($("geo-monitoring-frequency").options).forEach(option => {
            option.hidden = !frequencies.has(option.value);
            option.disabled = !frequencies.has(option.value);
        });
        if (!frequencies.has($("geo-monitoring-frequency").value)) {
            $("geo-monitoring-frequency").value = [...frequencies][0] || "monthly";
        }
        updateMonitoringFields();
        Object.entries(capabilities.platforms || {}).forEach(([platform, access]) => {
            const input = document.querySelector(`input[name="geo-platform"][value="${platform}"]`);
            const label = document.querySelector(`[data-provider="${platform}"]`);
            const row = document.querySelector(`[data-platform-row="${platform}"]`);
            if (!input || !label || !row) return;
            const surfaceOnly = access.mode === "surface_only";
            input.disabled = !access.included || !access.configured || surfaceOnly;
            input.checked = !input.disabled && (firstLoad || input.checked);
            row.classList.toggle("is-disabled", input.disabled);
            if (!access.included) {
                label.textContent = "Upgrade";
                label.className = "geo-provider-plan";
            } else if (surfaceOnly) {
                label.textContent = "Surface only";
                label.className = "geo-provider-surface";
                row.title = access.reason || "No supported public answer API is available.";
            } else if (!access.configured) {
                label.textContent = "Setup required";
                label.className = "geo-provider-off";
            } else {
                label.textContent = "Ready";
                label.className = "geo-provider-ready";
            }
        });
        renderKeywords();
    }

    async function loadHistory() {
        const limit = state.capabilities?.limits?.history || 10;
        renderHistory(await json(`/api/geo/analyses?limit=${limit}`));
    }

    function updateMonitoringFields() {
        const weekly = $("geo-monitoring-frequency").value === "weekly";
        $("geo-monitoring-weekday-field").hidden = !weekly;
        $("geo-monitoring-day-field").hidden = weekly;
    }

    function renderMonitoring(schedule) {
        state.monitoring = schedule;
        $("geo-monitoring-state").textContent = schedule?.enabled ? "Active" : "Off";
        if (!schedule) {
            updateMonitoringFields();
            return;
        }
        $("geo-monitoring-enabled").checked = Boolean(schedule.enabled);
        $("geo-monitoring-frequency").value = schedule.frequency;
        $("geo-monitoring-weekday").value = String(schedule.run_weekday ?? 0);
        $("geo-monitoring-day").value = String(schedule.run_day ?? 1);
        $("geo-monitoring-time").value = String(schedule.run_time || "09:00").slice(0, 5);
        const spec = schedule.spec || {};
        if (spec.brand_name) $("geo-brand").value = spec.brand_name;
        if (spec.country) $("geo-country").value = spec.country;
        if (spec.language) $("geo-language").value = spec.language;
        $("geo-aliases").value = (spec.aliases || []).filter(value => value !== spec.brand_name).join(", ");
        $("geo-competitors").value = (spec.competitors || []).join(", ");
        $("geo-domains").value = (spec.owned_domains || []).join(", ");
        state.keywords = [...(spec.keywords || [])];
        document.querySelectorAll('input[name="geo-platform"]').forEach(input => {
            if (!input.disabled) input.checked = (spec.platforms || []).includes(input.value);
        });
        renderKeywords();
        updateMonitoringFields();
        $("geo-monitoring-next").textContent = schedule.next_run_at
            ? `Next run ${new Date(schedule.next_run_at).toLocaleString(locale())}`
            : "Monitoring is saved but currently disabled.";
    }

    async function loadMonitoring() {
        try {
            renderMonitoring(await json("/api/geo/monitoring"));
        } catch (error) {
            $("geo-monitoring-state").textContent = "Unavailable";
            $("geo-monitoring-next").textContent = error.message;
        }
    }

    async function initialise() {
        banner("");
        try {
            applyCapabilities(await json("/api/geo/capabilities"));
            $("geo-workspace").hidden = false;
            await Promise.all([loadMonitoring(), loadHistory()]);
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
        if (!flushKeywordInput()) {
            $("geo-keyword-input").focus();
            return;
        }
        const body = payload();
        if (!body.platforms.length) { banner("Configure and choose at least one included AI-search platform.", true); return; }
        if (!body.keywords.length) { showKeywordError("geo.keyword.required", {}, "Add at least one search keyword."); $("geo-keyword-input").focus(); return; }
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
    $("geo-monitoring-frequency").addEventListener("change", updateMonitoringFields);
    $("geo-monitoring-form").addEventListener("submit", async event => {
        event.preventDefault();
        if (!flushKeywordInput()) return;
        const spec = payload();
        if (!spec.brand_name || !spec.platforms.length || !spec.keywords.length) {
            banner("Add a brand, at least one keyword and at least one ready AI model before saving monitoring.", true);
            return;
        }
        const button = $("geo-monitoring-save");
        button.disabled = true;
        try {
            const frequency = $("geo-monitoring-frequency").value;
            const result = await json("/api/geo/monitoring", {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    enabled: $("geo-monitoring-enabled").checked,
                    frequency,
                    run_weekday: frequency === "weekly" ? Number($("geo-monitoring-weekday").value) : null,
                    run_day: frequency === "monthly" ? Number($("geo-monitoring-day").value) : null,
                    run_time: $("geo-monitoring-time").value,
                    timezone: "Asia/Kuala_Lumpur",
                    spec
                })
            });
            renderMonitoring(result);
            banner("GEO monitoring schedule saved.", false);
        } catch (error) {
            banner(error.message, true);
        } finally {
            button.disabled = false;
        }
    });
    $("geo-retry").addEventListener("click", initialise);
    $("geo-keyword-box").addEventListener("click", event => {
        if (!event.target.closest("button")) $("geo-keyword-input").focus();
    });
    $("geo-keyword-input").addEventListener("input", clearKeywordError);
    $("geo-keyword-input").addEventListener("keydown", event => {
        const input = event.currentTarget;
        if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            if (flushKeywordInput()) input.value = "";
        } else if (event.key === "Backspace" && !input.value && state.keywords.length) {
            state.keywords.pop();
            clearKeywordError();
            renderKeywords();
        }
    });
    $("geo-keyword-input").addEventListener("paste", event => {
        const pasted = event.clipboardData?.getData("text") || "";
        if (!/[,\r\n]/.test(pasted)) return;
        event.preventDefault();
        addKeywordBatch(pasted);
        event.currentTarget.value = "";
    });
    $("geo-keyword-input").addEventListener("blur", flushKeywordInput);
    document.querySelectorAll("[data-keyword-example]").forEach(button => button.addEventListener("click", () => {
        addKeyword(button.dataset.keywordExample);
        $("geo-keyword-input").focus();
    }));
    document.querySelectorAll('input[name="geo-platform"]').forEach(input => input.addEventListener("change", updateExecutionCount));
    window.addEventListener("omnexa:languagechange", () => {
        if (state.capabilities) applyCapabilities(state.capabilities);
        renderKeywords();
        if (state.history.length) renderHistory(state.history);
        if (state.currentAnalysis) renderResult(state.currentAnalysis, { scroll: false });
    });
    initialise();
})();
