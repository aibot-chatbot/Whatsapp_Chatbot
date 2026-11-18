
        // Icons are decoration. refreshIcons() (shared-ui.js) no-ops when the
        // CDN has not loaded, so a blocked or slow icon script can never abort
        // this block and prevent the data from loading.
        refreshIcons();

        requireLogin();
        
        function showToast(msg, duration = 4000) {
            const toast = document.getElementById("redirect-toast");
            if (toast) {
                toast.textContent = msg;
                toast.classList.add("show");
                if (window.toastTimeout) clearTimeout(window.toastTimeout);
                window.toastTimeout = setTimeout(() => {
                    toast.classList.remove("show");
                }, duration);
                toast.onclick = () => { toast.classList.remove("show"); };
            }
        }

        // Show redirect permission message as toast
        (function() {
            var msg = sessionStorage.getItem("redirect_message");
            if (msg) {
                sessionStorage.removeItem("redirect_message");
                showToast(msg);
            }
        })();

        document.addEventListener("DOMContentLoaded", () => {
            loadChatbotUsage();
            fetchBots();
            setupGridDelegation();
            setupPermanentDeleteConfirmation();
            document.getElementById("bot-details-form").addEventListener("submit", (event) => {
                event.preventDefault();
                if (editingBotId === null) createBot();
                else updateBot(editingBotId);
            });
            document.getElementById("bot-name").addEventListener("input", () => {
                if (document.getElementById("bot-name").value.trim()) {
                    document.getElementById("bot-name").removeAttribute("aria-invalid");
                    document.getElementById("bot-name-error").hidden = true;
                }
            });
        });

        let chatbotEntitlement = {
            loaded: false,
            used: 0,
            limit: null
        };
        let currentBotView = "active";
        let loadedBots = [];
        let botsRequestGeneration = 0;
        let selectedPermanentDeleteBotId = null;
        let selectedPermanentDeleteBotName = "";
        let permanentDeleteConfirmationTouched = false;
        let lastDialogTrigger = null;
        let editingBotId = null;
        let botSubmitPending = false;

        function openDialog(dialogId, preferredSelector) {
            const dialog = document.getElementById(dialogId);
            if (!dialog) return;
            lastDialogTrigger = document.activeElement;
            dialog.classList.add("show");
            const target = (preferredSelector && dialog.querySelector(preferredSelector))
                || dialog.querySelector('input, textarea, select, button:not([disabled])');
            window.requestAnimationFrame(() => target?.focus());
        }

        function closeDialog(dialogId) {
            document.getElementById(dialogId)?.classList.remove("show");
            if (lastDialogTrigger && typeof lastDialogTrigger.focus === "function") {
                lastDialogTrigger.focus();
            }
            lastDialogTrigger = null;
        }

        document.addEventListener("keydown", (event) => {
            const dialog = document.querySelector(".modal-overlay.show");
            if (!dialog) return;
            if (event.key === "Escape") {
                if (dialog.id === "create-modal") closeCreateModal();
                if (dialog.id === "delete-modal") closeDeleteModal();
                if (dialog.id === "permanent-delete-modal") closePermanentDeleteModal();
                return;
            }
            if (event.key !== "Tab") return;
            const focusable = [...dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href]')];
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });

        function getChatbotLimitMessage() {
            return "Chatbot limit reached. Archive an existing bot or upgrade your plan to create more bots.";
        }

        function getRestoreLimitMessage() {
            return "Chatbot limit reached. Archive another active bot or upgrade your plan before restoring this bot.";
        }

        function isChatbotLimitReached() {
            if (!chatbotEntitlement.loaded || chatbotEntitlement.limit === null) {
                return false;
            }
            return chatbotEntitlement.used >= chatbotEntitlement.limit;
        }

        function canCreateChatbot() {
            return chatbotEntitlement.loaded && !isChatbotLimitReached();
        }

        function applyChatbotLimitState() {
            const loading = !chatbotEntitlement.loaded;
            const limitReached = isChatbotLimitReached();
            const blocked = loading || limitReached;
            document.querySelectorAll('[data-create-bot-trigger="true"]').forEach((button) => {
                button.disabled = blocked;
                button.title = loading ? "Checking chatbot limit..." : (blocked ? getChatbotLimitMessage() : "Create Bot");
            });
            const helper = document.getElementById("chatbot-limit-helper");
            if (helper) {
                helper.textContent = limitReached ? getChatbotLimitMessage() : "";
                helper.style.display = limitReached ? "block" : "none";
            }
            const usage = document.getElementById("plan-usage-count");
            if (usage) {
                usage.textContent = loading
                    ? "—"
                    : `${chatbotEntitlement.used}/${chatbotEntitlement.limit === null ? "∞" : chatbotEntitlement.limit}`;
            }
        }

        async function loadChatbotUsage() {
            try {
                const response = await authenticatedFetch("/api/billing/usage");
                const result = await response.json();
                const chatbots = result.status === "success" && result.data && result.data.usage
                    ? result.data.usage.chatbots
                    : null;

                if (!chatbots) {
                    chatbotEntitlement = { loaded: false, used: 0, limit: null };
                    applyChatbotLimitState();
                    return;
                }

                const used = Number(chatbots.used || 0);
                const rawLimit = chatbots.limit;
                const limit = rawLimit === null || rawLimit === undefined ? null : Number(rawLimit);

                chatbotEntitlement = {
                    loaded: true,
                    used: Number.isFinite(used) ? used : 0,
                    limit: limit !== null && Number.isFinite(limit) ? limit : null
                };
                applyChatbotLimitState();
            } catch (error) {
                console.error("Failed to load chatbot usage:", error);
                chatbotEntitlement = { loaded: false, used: 0, limit: null };
                applyChatbotLimitState();
            }
        }

        function setupGridDelegation() {
            const grid = document.getElementById("bots-grid");
            grid.addEventListener("click", (e) => {
                const restoreBtn = e.target.closest(".restore-btn");
                if (restoreBtn) {
                    e.stopPropagation();
                    const botId = restoreBtn.getAttribute("data-bot-id");
                    restoreBot(botId);
                    return;
                }

                const permanentDeleteBtn = e.target.closest(".permanent-delete-btn");
                if (permanentDeleteBtn) {
                    e.stopPropagation();
                    const botId = permanentDeleteBtn.getAttribute("data-bot-id");
                    const botName = permanentDeleteBtn.getAttribute("data-bot-name") || "";
                    openPermanentDeleteModal(botId, botName);
                    return;
                }

                const editBtn = e.target.closest(".edit-btn");
                if (editBtn) {
                    e.stopPropagation();
                    const botId = editBtn.getAttribute("data-bot-id");
                    openEditBot(botId);
                    return;
                }

                const deleteBtn = e.target.closest(".delete-btn");
                if (deleteBtn) {
                    e.stopPropagation();
                    const botId = deleteBtn.getAttribute("data-bot-id");
                    deleteBot(botId);
                    return;
                }

            });
        }

        function setBotView(view) {
            currentBotView = view === "archived" ? "archived" : "active";
            updateBotViewTabs();
            applyChatbotLimitState();
            fetchBots();
        }

        function updateBotViewTabs() {
            const activeTab = document.getElementById("active-bots-tab");
            const archivedTab = document.getElementById("archived-bots-tab");
            const message = document.getElementById("bot-view-message");

            if (activeTab) {
                activeTab.setAttribute("aria-selected", String(currentBotView === "active"));
            }
            if (archivedTab) {
                archivedTab.setAttribute("aria-selected", String(currentBotView === "archived"));
            }
            if (message) {
                message.textContent = currentBotView === "archived"
                    ? "Archived bots are preserved and cannot be edited until restored."
                    : "Active bots can be opened, edited, or archived.";
            }
            const viewLabel = document.getElementById("current-view-label");
            if (viewLabel) viewLabel.textContent = currentBotView === "archived" ? "Archived" : "Active";
            const filter = document.getElementById("bot-status-filter");
            if (filter) filter.disabled = currentBotView === "archived";
        }

        async function fetchBots() {
            const grid = document.getElementById("bots-grid");
            const requestGeneration = ++botsRequestGeneration;
            const requestedView = currentBotView;
            loadedBots = [];
            const visibleCount = document.getElementById("visible-bot-count");
            if (visibleCount) visibleCount.textContent = "0";
            updateBotViewTabs();
            grid.innerHTML = `<div class="loading-state" aria-label="Loading bots">
                <div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div>
            </div>`;
            const apiStatus = document.getElementById("api-status-label");
            if (apiStatus) apiStatus.textContent = "Checking";
            refreshIcons();

            {
                const endpoint = requestedView === "archived" ? "/api/bots/archived" : "/api/bots";

                // Transient failures are retried with backoff rather than shown
                // to the user. The skeleton stays on screen throughout, so a
                // blip reads as "still loading" instead of "broken, press this".
                const outcome = await resilientLoad.loadJson(endpoint, {
                    onRetry(info) {
                        if (requestGeneration !== botsRequestGeneration) return;
                        showLoadingRetry(info);
                    }
                });

                if (requestGeneration !== botsRequestGeneration || requestedView !== currentBotView) return;

                if (!outcome.ok) {
                    loadedBots = [];
                    if (apiStatus) apiStatus.textContent = outcome.status === 0 ? "Offline" : "Unavailable";
                    renderLoadFailure(outcome);
                    return;
                }

                const bots = outcome.data;
                loadedBots = Array.isArray(bots) ? bots : [];
                if (apiStatus) apiStatus.textContent = "Online";
                if (visibleCount) visibleCount.textContent = String(loadedBots.length);

                if (!bots || bots.length === 0) {
                    if (currentBotView === "archived") {
                        grid.innerHTML = `
                            <div class="empty-state">
                                <div class="empty-icon">
                                    <i data-lucide="archive" style="width: 48px; height: 48px; color: var(--primary);"></i>
                                </div>
                                <h2>No Archived Bots</h2>
                                <p>Archived bots will appear here after you remove them from active use.</p>
                            </div>
                        `;
                        refreshIcons();
                        applyChatbotLimitState();
                        return;
                    }

                    grid.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-icon">
                                <i data-lucide="bot" style="width: 48px; height: 48px; color: var(--primary);"></i>
                            </div>
                            <h2>Create your first bot</h2>
                            <p>Start with a name. We will guide you through adding knowledge, checking replies, and choosing where to publish.</p>
                            <button class="create-btn" onclick="openCreateModal()" data-create-bot-trigger="true">
                                <i data-lucide="plus"></i> Create Your First Bot
                            </button>
                        </div>
                    `;
                    refreshIcons();
                    applyChatbotLimitState();
                    omnexaTour.offer(0);

                    return;
                }

                renderFilteredBots();
                if (currentBotView === "active") omnexaTour.offer(loadedBots.length);

            }
        }

        /* Keeps the skeleton on screen while resilientLoad backs off, and says
           what is happening. Silence through a multi-second backoff reads as a
           hang, which is what sends people to the reload button. */
        function showLoadingRetry(info) {
            const grid = document.getElementById("bots-grid");
            if (!grid) return;

            let note = document.getElementById("bots-retry-note");
            if (!note) {
                grid.innerHTML = `<div class="loading-state" aria-label="Loading bots">
                    <div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div>
                </div>
                <p id="bots-retry-note" class="panel-context" role="status"></p>`;
                note = document.getElementById("bots-retry-note");
            }
            if (note) {
                note.textContent = `Still loading. Retrying (${info.attempt} of ${info.of})…`;
            }
            const apiStatus = document.getElementById("api-status-label");
            if (apiStatus) apiStatus.textContent = "Retrying";
        }

        /* Reached only once automatic recovery has genuinely failed, or at once
           for a terminal answer that no amount of retrying can change. The two
           are worded differently because they need different actions. */
        function renderLoadFailure(outcome) {
            const grid = document.getElementById("bots-grid");
            if (!grid) return;

            const heading = outcome.terminal ? "We could not load your bots" : "Still cannot reach the server";
            const detail = outcome.terminal
                ? escapeHtml(outcome.message || "The bot service did not return a usable response.")
                : `We tried ${outcome.attempts} times. ${escapeHtml(outcome.message || "")}`;

            grid.innerHTML = `<div class="empty-state" role="alert">
                <div class="empty-icon"><i data-lucide="${outcome.status === 0 ? "wifi-off" : "triangle-alert"}" style="width:32px;height:32px;color:var(--warning);"></i></div>
                <h2>${heading}</h2>
                <p>${detail}</p>
                <button class="cancel-btn" onclick="fetchBots()"><i data-lucide="refresh-cw"></i> Try again</button>
            </div>`;
            refreshIcons();
        }

        function renderFilteredBots() {
            const grid = document.getElementById("bots-grid");
            const query = (document.getElementById("bot-search")?.value || "").trim().toLowerCase();
            const status = document.getElementById("bot-status-filter")?.value || "all";
            const bots = loadedBots.filter((bot) => {
                const searchable = `${bot.bot_name || ""} ${bot.bot_description || ""} ${bot.language || ""} ${bot.config_tone || ""}`.toLowerCase();
                const matchesSearch = !query || searchable.includes(query);
                const matchesStatus = currentBotView === "archived" || status === "all"
                    || (status === "active" ? Boolean(bot.is_active) : !bot.is_active);
                return matchesSearch && matchesStatus;
            });
            const visibleCount = document.getElementById("visible-bot-count");
            if (visibleCount) visibleCount.textContent = String(bots.length);
            if (!bots.length) {
                grid.innerHTML = `<div class="empty-state">
                    <div class="empty-icon"><i data-lucide="search-x" style="width:32px;height:32px;color:var(--primary);"></i></div>
                    <h2>No matching bots</h2><p>Clear the search or status filter to see the full list.</p>
                </div>`;
            } else {
                grid.innerHTML = bots.map(bot => renderBotCard(bot, currentBotView === "archived")).join("");
            }
            refreshIcons();
            applyChatbotLimitState();
        }

        function renderBotCard(bot, archived) {
            const statusLabel = archived ? "Archived" : (bot.is_active ? "Active" : "Inactive");
            const statusClass = archived ? "inactive-badge" : (bot.is_active ? "active-badge" : "inactive-badge");
            const safeBotId = escapeHtmlAttribute(bot.id);
            const actions = archived
                ? `
                    <button class="action-btn restore-btn" data-bot-id="${safeBotId}">
                        <i data-lucide="rotate-ccw" style="width: 16px; height: 16px; pointer-events: none;"></i> Restore
                    </button>
                    <button class="action-btn permanent-delete-btn" data-bot-id="${safeBotId}" data-bot-name="${escapeHtmlAttribute(bot.bot_name || "")}">
                        <i data-lucide="trash-2" style="width: 16px; height: 16px; pointer-events: none;"></i> Permanently Delete
                    </button>
                `
                : `
                    <a class="action-btn open-bot-link" href="index.html?bot_id=${encodeURIComponent(bot.id)}" aria-label="Open bot: ${escapeHtmlAttribute(bot.bot_name || "Unnamed Bot")}">Open bot</a>
                    <button class="action-btn edit-btn" data-bot-id="${safeBotId}">
                        <i data-lucide="edit-2" style="width: 16px; height: 16px; pointer-events: none;"></i> Edit
                    </button>
                    <button class="action-btn delete-btn" data-bot-id="${safeBotId}">
                        <i data-lucide="archive" style="width: 16px; height: 16px; pointer-events: none;"></i> Archive
                    </button>
                `;

            return `<article class="glass-card" data-bot-id="${safeBotId}" data-bot-view="${archived ? "archived" : "active"}">
                <div class="bot-identity">
                    <div class="bot-icon"><i data-lucide="${archived ? "archive" : "bot"}" style="width:20px;height:20px;color:var(--primary);"></i></div>
                    <div class="bot-copy">
                        <div class="bot-title">${escapeHtml(bot.bot_name || "Unnamed Bot")}</div>
                        <div class="bot-desc">${escapeHtml(bot.bot_description || "No description provided.")}</div>
                    </div>
                </div>
                <div class="bot-meta-container">
                    <div class="bot-meta">${escapeHtml(bot.language || "Language not set")}</div>
                    <div class="bot-meta">${escapeHtml(bot.config_tone || "Tone not set")}</div>
                </div>
                <span class="badge ${statusClass}">${statusLabel}</span>
                <div class="bot-actions">${actions}</div>
            </article>`;
        }

        function escapeHtml(value) {
            return String(value)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        function escapeHtmlAttribute(value) {
            return String(value)
                .replace(/&/g, "&amp;")
                .replace(/"/g, "&quot;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;");
        }

        function openCreateModal() {
            if (!canCreateChatbot()) {
                showToast(chatbotEntitlement.loaded ? getChatbotLimitMessage() : "Checking chatbot limit. Please try again in a moment.");
                applyChatbotLimitState();
                return;
            }

            document.getElementById("bot-name").value = "";
            document.getElementById("bot-description").value = "";
            document.getElementById("bot-language").value = "English";

            editingBotId = null;
            resetBotFormFeedback();
            document.querySelector("#create-modal h2").innerText = "Name your bot";
            document.getElementById("bot-form-intro").textContent = "Start with a name. Next, add a PDF for your bot to learn from.";

            const createBtn = document.querySelector("#create-modal .create-btn");
            createBtn.textContent = "Create and continue";

            openDialog("create-modal", "#bot-name");
        }

        function closeCreateModal() {
            if (botSubmitPending) return;
            closeDialog("create-modal");
        }

        function resetBotFormFeedback() {
            document.getElementById("bot-name").removeAttribute("aria-invalid");
            document.getElementById("bot-name-error").hidden = true;
            document.getElementById("bot-form-error").hidden = true;
        }

        function validateBotName() {
            resetBotFormFeedback();
            const name = document.getElementById("bot-name");
            if (name.value.trim()) return true;
            name.setAttribute("aria-invalid", "true");
            document.getElementById("bot-name-error").hidden = false;
            name.focus();
            return false;
        }

        function setBotFormPending(pending) {
            botSubmitPending = pending;
            const form = document.getElementById("bot-details-form");
            form.setAttribute("aria-busy", String(pending));
            form.querySelectorAll("input, textarea, button").forEach(control => { control.disabled = pending; });
            document.getElementById("submit-create-btn").textContent = pending
                ? (editingBotId === null ? "Creating…" : "Saving…")
                : (editingBotId === null ? "Create and continue" : "Save changes");
        }

        function showBotFormError(message) {
            const error = document.getElementById("bot-form-error");
            error.textContent = message;
            error.hidden = false;
        }

        async function createBot() {
            if (botSubmitPending) return;
            if (!canCreateChatbot()) {
                showToast(chatbotEntitlement.loaded ? getChatbotLimitMessage() : "Checking chatbot limit. Please try again in a moment.");
                applyChatbotLimitState();
                return;
            }

            const botName = document.getElementById("bot-name").value.trim();
            const botDescription = document.getElementById("bot-description").value.trim();
            const botLanguage = document.getElementById("bot-language").value.trim();

            if (!validateBotName()) return;
            setBotFormPending(true);

            try {
                const response = await authenticatedFetch("/api/bots", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        bot_name: botName,
                        bot_description: botDescription,
                        language: botLanguage
                    })
                });

                const result = await response.json();

                if (result.status === "success") {
                    sessionStorage.setItem("selectedBotId", result.data.id);
                    window.location.href = `new_linkdocs.html?bot_id=${encodeURIComponent(result.data.id)}&setup=1`;
                } else {
                    showBotFormError(result.message || "Could not create your bot. Try again.");
                }
            } catch (error) {
                console.error("Error creating bot:", error);
                showBotFormError("Could not create your bot. Your details are still here. Try again.");
            } finally {
                setBotFormPending(false);
            }
        }

        // ===== DELETE BOT =====

        let selectedDeleteBotId = null;

        function deleteBot(botId) {
            selectedDeleteBotId = botId;
            openDialog("delete-modal", ".cancel-btn");
        }

        function closeDeleteModal() {
            selectedDeleteBotId = null;
            closeDialog("delete-modal");
        }

        async function confirmDeleteBot() {
            if (!selectedDeleteBotId) return;

            const response = await authenticatedFetch(`/api/bots/${selectedDeleteBotId}`, {
                method: "DELETE"
            });

            const result = await response.json();

            if (result.status === "success") {
                closeDeleteModal();
                await loadChatbotUsage();
                applyChatbotLimitState();
                fetchBots();
            } else {
                alert(result.message || "Failed to archive bot");
            }
        }

        async function restoreBot(botId) {
            if (!botId) return;

            const response = await authenticatedFetch(`/api/bots/${botId}/restore`, {
                method: "POST"
            });

            const result = await response.json();

            if (result.status === "success") {
                await loadChatbotUsage();
                currentBotView = "active";
                updateBotViewTabs();
                applyChatbotLimitState();
                fetchBots();
            } else if (result.code === "chatbot_limit") {
                alert(getRestoreLimitMessage());
            } else {
                alert(result.message || "Failed to restore bot");
            }
        }

        function openPermanentDeleteModal(botId, botName) {
            selectedPermanentDeleteBotId = botId;
            selectedPermanentDeleteBotName = botName || "";
            const helper = document.getElementById("permanent-delete-helper");
            if (helper) helper.textContent = `Type "${selectedPermanentDeleteBotName}" to enable permanent delete.`;
            resetPermanentDeleteConfirmation();
            openDialog("permanent-delete-modal", "#permanent-delete-confirm-name");
        }

        function closePermanentDeleteModal() {
            selectedPermanentDeleteBotId = null;
            selectedPermanentDeleteBotName = "";
            resetPermanentDeleteConfirmation();
            closeDialog("permanent-delete-modal");
        }

        function setupPermanentDeleteConfirmation() {
            const input = document.getElementById("permanent-delete-confirm-name");
            if (!input) return;
            input.addEventListener("input", function() {
                permanentDeleteConfirmationTouched = true;
                updatePermanentDeleteButtonState(true);
            });
        }

        function resetPermanentDeleteConfirmation() {
            permanentDeleteConfirmationTouched = false;
            const input = document.getElementById("permanent-delete-confirm-name");
            const button = document.getElementById("permanent-delete-confirm-btn");
            if (input) input.value = "";
            if (button) button.disabled = true;
            hidePermanentDeleteError();
        }

        function getPermanentDeleteTypedName() {
            const input = document.getElementById("permanent-delete-confirm-name");
            return input ? input.value.trim() : "";
        }

        function isPermanentDeleteNameExactMatch() {
            return getPermanentDeleteTypedName() === selectedPermanentDeleteBotName;
        }

        function showPermanentDeleteError() {
            const error = document.getElementById("permanent-delete-error");
            if (error) error.style.display = "block";
        }

        function hidePermanentDeleteError() {
            const error = document.getElementById("permanent-delete-error");
            if (error) error.style.display = "none";
        }

        function updatePermanentDeleteButtonState(showErrorWhenInvalid) {
            const button = document.getElementById("permanent-delete-confirm-btn");
            const matches = isPermanentDeleteNameExactMatch();
            if (button) button.disabled = !matches;
            if (matches) {
                hidePermanentDeleteError();
            } else if (showErrorWhenInvalid && permanentDeleteConfirmationTouched) {
                showPermanentDeleteError();
            }
            return !!matches;
        }

        function validatePermanentDeleteName(showErrorWhenInvalid = false) {
            return updatePermanentDeleteButtonState(showErrorWhenInvalid);
        }

        async function confirmPermanentDeleteBot() {
            if (!selectedPermanentDeleteBotId) return;

            permanentDeleteConfirmationTouched = true;
            if (!validatePermanentDeleteName(true)) {
                showPermanentDeleteError();
                return;
            }

            const response = await authenticatedFetch(`/api/bots/${selectedPermanentDeleteBotId}/permanent`, {
                method: "DELETE",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    confirm_bot_name: getPermanentDeleteTypedName()
                })
            });

            const result = await response.json();

            if (result.status === "success") {
                closePermanentDeleteModal();
                await loadChatbotUsage();
                applyChatbotLimitState();
                fetchBots();
            } else {
                alert(result.message || "Failed to permanently delete bot");
            }
        }

        // ===== EDIT BOT =====

        async function openEditBot(botId) {
            if (botSubmitPending) return;
            let bot;
            try {
                const response = await authenticatedFetch(`/api/bots/${botId}`);
                const result = await response.json();
                if (result.status !== "success") throw new Error("Could not load bot details.");
                bot = result.data;
            } catch (_) {
                showToast("Could not load bot details. Try again.");
                return;
            }

            document.getElementById("bot-name").value = bot.bot_name || "";
            document.getElementById("bot-description").value = bot.bot_description || "";
            document.getElementById("bot-language").value = bot.language || "English";

            editingBotId = botId;
            resetBotFormFeedback();
            document.querySelector("#create-modal h2").innerText = "Edit bot details";
            document.getElementById("bot-form-intro").textContent = "Update how this bot appears in your workspace.";

            openDialog("create-modal", "#bot-name");

            const createBtn = document.querySelector("#create-modal .create-btn");
            createBtn.textContent = "Save changes";
        }

        async function updateBot(botId) {
            if (botSubmitPending || !validateBotName()) return;
            const botName = document.getElementById("bot-name").value.trim();
            const botDescription = document.getElementById("bot-description").value.trim();
            const botLanguage = document.getElementById("bot-language").value.trim();

            setBotFormPending(true);
            try {
                const response = await authenticatedFetch(`/api/bots/${botId}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        bot_name: botName,
                        bot_description: botDescription,
                        language: botLanguage
                    })
                });
                const result = await response.json();
                if (result.status === "success") {
                    setBotFormPending(false);
                    closeCreateModal();
                    showToast("Bot details saved.");
                    fetchBots();
                } else {
                    showBotFormError(result.message || "Could not save bot details. Try again.");
                }
            } catch (_) {
                showBotFormError("Could not save bot details. Your changes are still here. Try again.");
            } finally {
                setBotFormPending(false);
            }
        }

    