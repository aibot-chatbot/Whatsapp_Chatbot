(function () {
    "use strict";

    const ui = PlatformAdminShell;

    function safeValue(value) {
        return value === null || value === undefined || value === "" ? "Not available" : String(value);
    }

    function definitionItem(label, value, nodeValue) {
        const wrapper = ui.element("div");
        wrapper.append(ui.element("dt", "", label));
        const description = ui.element("dd");
        if (nodeValue) description.append(nodeValue);
        else description.textContent = safeValue(value);
        wrapper.append(description);
        return wrapper;
    }

    function definitionList(items) {
        const list = ui.element("dl", "platform-definition-grid");
        items.forEach(function (item) {
            list.append(definitionItem(item[0], item[1], item[2]));
        });
        return list;
    }

    function parseCompanyId() {
        const raw = new URLSearchParams(window.location.search).get("company_id");
        if (!raw || !/^[1-9][0-9]*$/.test(raw)) return null;
        const parsed = Number(raw);
        return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
    }

    function pageHeader(company) {
        const header = ui.element("header", "platform-page-header");
        const title = ui.element("div");
        title.append(
            ui.element("h1", "", safeValue(company.company_name)),
            ui.element("p", "", "Read-only company, subscription, and AI-credit summary.")
        );
        const back = ui.element("a", "platform-link-button", "Back to companies");
        back.href = "platform-admin-companies.html";
        header.append(title, back);
        return header;
    }

    function companyPanel(company) {
        const panel = ui.element("section", "platform-panel");
        panel.append(ui.element("h2", "", "Company profile"));
        panel.append(definitionList([
            ["Company ID", company.id],
            ["Company name", company.company_name],
            ["Business type", company.business_type],
            ["Status", null, ui.statusBadge(company.status)],
            ["Contact email", company.contact_email],
            ["Contact phone", company.contact_phone],
            ["Created", ui.formatDate(company.created_at)],
            ["Updated", ui.formatDate(company.updated_at)]
        ]));
        return panel;
    }

    function lifecycleErrorMessage(error) {
        const code = error && error.code;
        if (code === "protected_company") return "Protected platform-admin companies cannot be suspended.";
        if (code === "no_change") return "No lifecycle change is required.";
        if (code === "company_not_found") return "The company no longer exists or is unavailable.";
        if (code === "platform_admin_access_denied") return "Your platform-admin access is no longer active.";
        return "The company lifecycle request could not be completed safely.";
    }

    function companyLifecyclePanel(company, reload) {
        const panel = ui.element("section", "platform-panel");
        const title = ui.element("h2", "", "Operational state");
        const status = String(company.status || "").toLowerCase();
        const description = status === "inactive"
            ? "Tenant operational activity is blocked. Platform-admin investigation remains available."
            : "Tenant operational activity is currently allowed.";
        const feedback = ui.element("p", "platform-form-feedback");
        const actions = ui.element("div", "platform-toolbar");
        const button = ui.element(
            "button",
            status === "inactive" ? "platform-button platform-button-primary" : "platform-button platform-button-danger",
            status === "inactive" ? "Restore company" : "Suspend company"
        );
        button.type = "button";
        button.addEventListener("click", async function () {
            const isRestore = status === "inactive";
            const confirmed = window.confirm(
                isRestore
                    ? "Restore tenant operational access for this company?"
                    : "Suspend this company? Tenant operational activity will be blocked while support and history remain available."
            );
            if (!confirmed) return;
            button.disabled = true;
            feedback.textContent = isRestore ? "Restoring company..." : "Suspending company...";
            try {
                await ui.runRequest("company-lifecycle", function (signal) {
                    return isRestore
                        ? PlatformAdminApi.restoreCompany(company.id, { signal: signal })
                        : PlatformAdminApi.suspendCompany(company.id, { signal: signal });
                });
                feedback.textContent = isRestore ? "Company restored." : "Company suspended.";
                try {
                    await reload();
                } catch (refreshError) {
                    if (refreshError && refreshError.category === "access_denied") {
                        ui.handleError(refreshError);
                        return;
                    }
                    feedback.textContent = "The change succeeded, but the refreshed company state could not be loaded. Use Retry to reload safely.";
                    retry.hidden = false;
                }
            } catch (error) {
                if (!ui.handleError(error) && (!error || error.category !== "aborted")) {
                    feedback.textContent = lifecycleErrorMessage(error);
                    button.disabled = false;
                }
            }
        });
        const retry = ui.element("button", "platform-button", "Retry");
        retry.type = "button";
        retry.hidden = true;
        retry.addEventListener("click", reload);
        actions.append(button, retry);
        panel.append(
            title,
            definitionList([
                ["Current state", null, ui.statusBadge(company.status)],
                ["Effect", description]
            ]),
            actions,
            feedback
        );
        return panel;
    }

    function makeInitialListState(extra) {
        return Object.assign({
            loaded: false,
            loading: false,
            limit: 25,
            offset: 0,
            search: "",
            sortBy: "created_at",
            sortOrder: "desc"
        }, extra || {});
    }

    function boundedSearch(value) {
        return String(value || "").slice(0, 100);
    }

    function listToolbar(config) {
        const toolbar = ui.element("div", "platform-toolbar");

        const searchField = ui.element("div", "platform-field");
        const searchLabel = ui.element("label", "", "Search");
        searchLabel.setAttribute("for", config.prefix + "-search");
        const search = ui.element("input", "platform-input");
        search.id = config.prefix + "-search";
        search.type = "search";
        search.maxLength = 100;
        search.value = config.state.search;
        search.placeholder = config.searchPlaceholder;
        search.addEventListener("input", function () {
            config.state.search = boundedSearch(search.value);
        });
        search.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
                config.state.offset = 0;
                config.load();
            }
        });
        searchField.append(searchLabel, search);
        toolbar.append(searchField);

        if (config.stateOptions) {
            const stateField = ui.element("div", "platform-field");
            const stateLabel = ui.element("label", "", "State");
            stateLabel.setAttribute("for", config.prefix + "-state");
            const stateSelect = ui.element("select", "platform-select");
            stateSelect.id = config.prefix + "-state";
            config.stateOptions.forEach(function (item) {
                const option = ui.element("option", "", item.label);
                option.value = item.value;
                if (config.state.state === item.value) option.selected = true;
                stateSelect.append(option);
            });
            stateSelect.addEventListener("change", function () {
                config.state.state = stateSelect.value;
                config.state.offset = 0;
                config.load();
            });
            stateField.append(stateLabel, stateSelect);
            toolbar.append(stateField);
        }

        const sortField = ui.element("div", "platform-field");
        const sortLabel = ui.element("label", "", "Sort by");
        sortLabel.setAttribute("for", config.prefix + "-sort-by");
        const sortSelect = ui.element("select", "platform-select");
        sortSelect.id = config.prefix + "-sort-by";
        config.sortOptions.forEach(function (item) {
            const option = ui.element("option", "", item.label);
            option.value = item.value;
            if (config.state.sortBy === item.value) option.selected = true;
            sortSelect.append(option);
        });
        sortSelect.addEventListener("change", function () {
            config.state.sortBy = sortSelect.value;
            config.state.offset = 0;
            config.load();
        });
        sortField.append(sortLabel, sortSelect);
        toolbar.append(sortField);

        const orderField = ui.element("div", "platform-field");
        const orderLabel = ui.element("label", "", "Sort order");
        orderLabel.setAttribute("for", config.prefix + "-sort-order");
        const orderSelect = ui.element("select", "platform-select");
        orderSelect.id = config.prefix + "-sort-order";
        [["desc", "Descending"], ["asc", "Ascending"]].forEach(function (item) {
            const option = ui.element("option", "", item[1]);
            option.value = item[0];
            if (config.state.sortOrder === item[0]) option.selected = true;
            orderSelect.append(option);
        });
        orderSelect.addEventListener("change", function () {
            config.state.sortOrder = orderSelect.value;
            config.state.offset = 0;
            config.load();
        });
        orderField.append(orderLabel, orderSelect);
        toolbar.append(orderField);

        const limitField = ui.element("div", "platform-field");
        const limitLabel = ui.element("label", "", "Page size");
        limitLabel.setAttribute("for", config.prefix + "-limit");
        const limitSelect = ui.element("select", "platform-select");
        limitSelect.id = config.prefix + "-limit";
        [25, 50, 100].forEach(function (value) {
            const option = ui.element("option", "", String(value));
            option.value = String(value);
            if (config.state.limit === value) option.selected = true;
            limitSelect.append(option);
        });
        limitSelect.addEventListener("change", function () {
            config.state.limit = Number(limitSelect.value);
            config.state.offset = 0;
            config.load();
        });
        limitField.append(limitLabel, limitSelect);
        toolbar.append(limitField);

        const searchButton = ui.element("button", "platform-button platform-button-primary", "Apply search");
        searchButton.type = "button";
        searchButton.addEventListener("click", function () {
            config.state.search = boundedSearch(search.value).trim();
            config.state.offset = 0;
            config.load();
        });
        toolbar.append(searchButton);

        return toolbar;
    }

    function paginationControls(pagination, state, load) {
        const wrapper = ui.element("div", "platform-pagination");
        const summary = ui.element(
            "span", "",
            "Showing " + ui.formatInteger(pagination.returned) + " of " + ui.formatInteger(pagination.total)
        );
        const actions = ui.element("div", "platform-pagination-actions");
        const previous = ui.element("button", "platform-button", "Previous");
        previous.type = "button";
        previous.disabled = state.offset <= 0;
        previous.addEventListener("click", function () {
            state.offset = Math.max(0, state.offset - state.limit);
            load();
        });
        const next = ui.element("button", "platform-button", "Next");
        next.type = "button";
        next.disabled = !pagination.has_more;
        next.addEventListener("click", function () {
            state.offset += state.limit;
            load();
        });
        actions.append(previous, next);
        wrapper.append(summary, actions);
        return wrapper;
    }

    function sectionStateCard(message, retryLabel, retry) {
        const wrapper = ui.element("div", "platform-empty");
        wrapper.append(ui.element("p", "", message));
        if (retry) {
            const button = ui.element("button", "platform-button", retryLabel || "Retry");
            button.type = "button";
            button.addEventListener("click", retry);
            wrapper.append(button);
        }
        return wrapper;
    }

    function renderTable(headers, rows, cardBuilder) {
        const fragment = document.createDocumentFragment();
        const wrap = ui.element("div", "platform-table-wrap");
        const table = ui.element("table", "platform-table");
        const thead = ui.element("thead");
        const headerRow = ui.element("tr");
        headers.forEach(function (label) {
            headerRow.append(ui.element("th", "", label));
        });
        thead.append(headerRow);
        const tbody = ui.element("tbody");
        rows.forEach(function (cells) {
            const tr = ui.element("tr");
            cells.forEach(function (cell) {
                const td = ui.element("td");
                if (cell && cell.nodeType) td.append(cell);
                else td.textContent = safeValue(cell);
                tr.append(td);
            });
            tbody.append(tr);
        });
        table.append(thead, tbody);
        wrap.append(table);
        fragment.append(wrap);

        const cards = ui.element("div", "platform-company-cards");
        rows.forEach(function (cells) {
            cards.append(cardBuilder(cells));
        });
        fragment.append(cards);
        return fragment;
    }

    function rowCard(labels, cells) {
        const card = ui.element("article", "platform-company-card");
        labels.forEach(function (label, index) {
            const item = ui.element("p");
            const strong = ui.element("strong", "", label + ": ");
            item.append(strong);
            const value = cells[index];
            if (value && value.nodeType) item.append(value.cloneNode(true));
            else item.append(document.createTextNode(safeValue(value)));
            card.append(item);
        });
        return card;
    }

    function userRows(users) {
        return users.map(function (user) {
            return [
                user.id,
                user.full_name,
                user.email,
                user.role,
                ui.statusBadge(user.status),
                ui.formatDate(user.created_at),
                ui.formatDate(user.updated_at)
            ];
        });
    }

    function chatbotRows(chatbots) {
        return chatbots.map(function (bot) {
            return [
                bot.id,
                bot.bot_name,
                String(bot.is_active === true),
                ui.statusBadge(bot.status),
                bot.language,
                bot.tone,
                bot.ai_provider,
                bot.model_name,
                ui.formatDate(bot.created_at),
                ui.formatDate(bot.updated_at)
            ];
        });
    }

    function planName(plan) {
        if (!plan) return "Not available";
        return safeValue(plan.name || plan.code);
    }

    function periodText(start, end) {
        const startText = ui.formatDate(start);
        const endText = ui.formatDate(end);
        if (startText === "Not available" && endText === "Not available") {
            return "Not available";
        }
        return startText + " to " + endText;
    }

    function cancellationText(subscription) {
        const values = [
            ["Scheduled", subscription.cancellation_scheduled_at],
            ["Effective", subscription.cancellation_effective_at],
            ["Cancelled", subscription.cancelled_at],
            ["Ends", subscription.ends_at]
        ].map(function (item) {
            const formatted = ui.formatDate(item[1]);
            return formatted === "Not available" ? null : item[0] + ": " + formatted;
        }).filter(Boolean);
        return values.length ? values.join("; ") : "Not available";
    }

    function subscriptionHistoryRows(subscriptions) {
        return subscriptions.map(function (subscription) {
            return [
                ui.statusBadge(subscription.status),
                planName(subscription.plan),
                periodText(subscription.current_period_start, subscription.current_period_end),
                ui.formatDate(subscription.trial_ends_at),
                planName(subscription.pending_plan),
                cancellationText(subscription),
                ui.formatDate(subscription.status_updated_at),
                ui.formatDate(subscription.created_at)
            ];
        });
    }

    function subscriptionHistoryToolbar(state, load) {
        const toolbar = ui.element("div", "platform-toolbar");

        const statusField = ui.element("div", "platform-field");
        const statusLabel = ui.element("label", "", "Status");
        statusLabel.setAttribute("for", "platform-subscription-history-status");
        const statusSelect = ui.element("select", "platform-select");
        statusSelect.id = "platform-subscription-history-status";
        [
            ["", "All statuses"],
            ["trialing", "Trialing"],
            ["active", "Active"],
            ["past_due", "Past due"],
            ["expired", "Expired"],
            ["cancelled", "Cancelled"]
        ].forEach(function (item) {
            const option = ui.element("option", "", item[1]);
            option.value = item[0];
            if (state.status === item[0]) option.selected = true;
            statusSelect.append(option);
        });
        statusSelect.addEventListener("change", function () {
            state.status = statusSelect.value;
            state.offset = 0;
            load();
        });
        statusField.append(statusLabel, statusSelect);
        toolbar.append(statusField);

        const limitField = ui.element("div", "platform-field");
        const limitLabel = ui.element("label", "", "Page size");
        limitLabel.setAttribute("for", "platform-subscription-history-limit");
        const limitSelect = ui.element("select", "platform-select");
        limitSelect.id = "platform-subscription-history-limit";
        [25, 50, 100].forEach(function (value) {
            const option = ui.element("option", "", String(value));
            option.value = String(value);
            if (state.limit === value) option.selected = true;
            limitSelect.append(option);
        });
        limitSelect.addEventListener("change", function () {
            state.limit = Number(limitSelect.value);
            state.offset = 0;
            load();
        });
        limitField.append(limitLabel, limitSelect);
        toolbar.append(limitField);

        return toolbar;
    }

    function subscriptionHistoryPanel(companyId) {
        const state = { loaded: false, loading: false, limit: 25, offset: 0, status: "" };
        const panel = ui.element("section", "platform-panel");
        const header = ui.element("header", "platform-page-header");
        const title = ui.element("div");
        title.append(
            ui.element("h2", "", "Subscription history"),
            ui.element("p", "", "Historical subscription records. This is not a complete event-level transition timeline.")
        );
        const toggle = ui.element("button", "platform-button", "Load subscription history");
        toggle.type = "button";
        header.append(title, toggle);
        const body = ui.element("div");
        body.hidden = true;
        panel.append(header, body);

        function renderLoaded(data) {
            body.replaceChildren();
            body.append(subscriptionHistoryToolbar(state, load));
            const subscriptions = data.subscriptions || [];
            if (!subscriptions.length) {
                body.append(sectionStateCard("No subscription history recorded."));
            } else {
                const headers = [
                    "Status", "Plan", "Current period", "Trial ends",
                    "Pending plan", "Cancellation", "Status updated", "Created"
                ];
                const rows = subscriptionHistoryRows(subscriptions);
                body.append(renderTable(headers, rows, function (cells) {
                    return rowCard(headers, cells);
                }));
            }
            body.append(paginationControls(data.pagination || {}, state, load));
        }

        async function load() {
            state.loaded = true;
            state.loading = true;
            body.hidden = false;
            body.replaceChildren(ui.element("div", "platform-loading", "Loading subscription history..."));
            toggle.textContent = "Hide subscription history";
            try {
                const data = await ui.runRequest("company-subscription-history", function (signal) {
                    return PlatformAdminApi.listCompanySubscriptionHistory(companyId, {
                        limit: state.limit,
                        offset: state.offset,
                        status: state.status,
                        signal: signal,
                    });
                });
                renderLoaded(data);
            } catch (error) {
                if (error && (error.category === "unauthenticated" || error.category === "access_denied")) {
                    ui.handleError(error);
                } else if (error && error.category === "not_found") {
                    showCompanyNotFoundState();
                } else if (!error || error.category !== "aborted") {
                    body.replaceChildren(sectionStateCard(
                        "Subscription history could not be loaded safely.",
                        "Retry",
                        load
                    ));
                }
            } finally {
                state.loading = false;
            }
        }

        toggle.addEventListener("click", function () {
            if (!state.loaded) {
                load();
                return;
            }
            body.hidden = !body.hidden;
            toggle.textContent = body.hidden ? "Show subscription history" : "Hide subscription history";
        });
        return panel;
    }

    function formatSen(value) {
        return Number.isSafeInteger(value) ? String(value) + " sen" : "Not available";
    }

    function billingOrderPlanText(plan) {
        if (!plan) return "Not available";
        if (plan.code && plan.name) return String(plan.code) + " - " + String(plan.name);
        return safeValue(plan.code || plan.name);
    }

    function billingOrderRows(orders) {
        return orders.map(function (order) {
            return [
                ui.formatDate(order.created_at),
                safeValue(order.status),
                formatSen(order.amount_sen),
                billingOrderPlanText(order.new_plan),
                billingOrderPlanText(order.source_plan),
                safeValue(order.activation_status),
                safeValue(order.activation_type),
                order.reconciliation_required === true ? "Yes" : "No",
                ui.formatDate(order.paid_at),
                ui.formatDate(order.credited_at),
                ui.formatDate(order.expires_at),
                ui.formatDate(order.activation_claimed_at),
                ui.formatDate(order.activation_completed_at),
                ui.formatDate(order.credit_granted_at)
            ];
        });
    }

    function billingOrdersToolbar(state, load) {
        const toolbar = ui.element("div", "platform-toolbar");

        const statusField = ui.element("div", "platform-field");
        const statusLabel = ui.element("label", "", "Status");
        statusLabel.setAttribute("for", "platform-billing-orders-status");
        const statusInput = ui.element("input", "platform-input");
        statusInput.id = "platform-billing-orders-status";
        statusInput.type = "text";
        statusInput.maxLength = 20;
        statusInput.value = state.status;
        statusInput.placeholder = "Exact status";
        statusField.append(statusLabel, statusInput);
        toolbar.append(statusField);

        const afterField = ui.element("div", "platform-field");
        const afterLabel = ui.element("label", "", "Created after");
        afterLabel.setAttribute("for", "platform-billing-orders-created-after");
        const afterInput = ui.element("input", "platform-input");
        afterInput.id = "platform-billing-orders-created-after";
        afterInput.type = "text";
        afterInput.value = state.createdAfter;
        afterInput.placeholder = "2026-07-01T00:00:00+00:00";
        afterField.append(afterLabel, afterInput);
        toolbar.append(afterField);

        const beforeField = ui.element("div", "platform-field");
        const beforeLabel = ui.element("label", "", "Created before");
        beforeLabel.setAttribute("for", "platform-billing-orders-created-before");
        const beforeInput = ui.element("input", "platform-input");
        beforeInput.id = "platform-billing-orders-created-before";
        beforeInput.type = "text";
        beforeInput.value = state.createdBefore;
        beforeInput.placeholder = "2026-08-01T00:00:00+00:00";
        beforeField.append(beforeLabel, beforeInput);
        toolbar.append(beforeField);

        const limitField = ui.element("div", "platform-field");
        const limitLabel = ui.element("label", "", "Page size");
        limitLabel.setAttribute("for", "platform-billing-orders-limit");
        const limitSelect = ui.element("select", "platform-select");
        limitSelect.id = "platform-billing-orders-limit";
        [25, 50, 100].forEach(function (value) {
            const option = ui.element("option", "", String(value));
            option.value = String(value);
            if (state.limit === value) option.selected = true;
            limitSelect.append(option);
        });
        limitField.append(limitLabel, limitSelect);
        toolbar.append(limitField);

        const apply = ui.element("button", "platform-button platform-button-primary", "Apply filters");
        apply.type = "button";
        apply.addEventListener("click", function () {
            state.status = statusInput.value.trim();
            state.createdAfter = afterInput.value.trim();
            state.createdBefore = beforeInput.value.trim();
            state.limit = Number(limitSelect.value);
            state.offset = 0;
            load();
        });
        toolbar.append(apply);

        const clear = ui.element("button", "platform-button", "Clear filters");
        clear.type = "button";
        clear.addEventListener("click", function () {
            state.status = "";
            state.createdAfter = "";
            state.createdBefore = "";
            state.limit = 25;
            state.offset = 0;
            load();
        });
        toolbar.append(clear);

        return toolbar;
    }

    function billingOrdersPanel(companyId) {
        const state = {
            loaded: false,
            loading: false,
            limit: 25,
            offset: 0,
            status: "",
            createdAfter: "",
            createdBefore: ""
        };
        const panel = ui.element("section", "platform-panel");
        const header = ui.element("header", "platform-page-header");
        const title = ui.element("div");
        title.append(
            ui.element("h2", "", "Billing orders"),
            ui.element("p", "", "Read-only subscription checkout records. Amounts are shown as integer sen as stored; currency is not returned or inferred.")
        );
        const toggle = ui.element("button", "platform-button", "Load billing orders");
        toggle.type = "button";
        header.append(title, toggle);
        const body = ui.element("div");
        body.hidden = true;
        panel.append(header, body);

        function renderLoaded(data) {
            body.replaceChildren();
            body.append(billingOrdersToolbar(state, load));
            const orders = data.billing_orders || [];
            if (!orders.length) {
                body.append(sectionStateCard("No billing orders recorded."));
            } else {
                const headers = [
                    "Created", "Status", "Amount", "New plan", "Source plan",
                    "Activation status", "Activation type", "Reconciliation required",
                    "Paid", "Credited", "Expires", "Activation claimed",
                    "Activation completed", "Credit granted"
                ];
                const rows = billingOrderRows(orders);
                body.append(renderTable(headers, rows, function (cells) {
                    return rowCard(headers, cells);
                }));
            }
            body.append(paginationControls(data.pagination || {}, state, load));
        }

        async function load() {
            state.loaded = true;
            state.loading = true;
            body.hidden = false;
            body.replaceChildren(ui.element("div", "platform-loading", "Loading billing orders..."));
            toggle.textContent = "Hide billing orders";
            try {
                const data = await ui.runRequest("company-billing-orders", function (signal) {
                    return PlatformAdminApi.listCompanyBillingOrders(companyId, {
                        limit: state.limit,
                        offset: state.offset,
                        status: state.status,
                        createdAfter: state.createdAfter,
                        createdBefore: state.createdBefore,
                        signal: signal,
                    });
                });
                renderLoaded(data);
            } catch (error) {
                if (error && (error.category === "unauthenticated" || error.category === "access_denied")) {
                    ui.handleError(error);
                } else if (error && error.category === "not_found") {
                    showCompanyNotFoundState();
                } else if (!error || error.category !== "aborted") {
                    body.replaceChildren(sectionStateCard(
                        error && error.category === "validation"
                            ? "Billing order filters could not be validated."
                            : "Billing orders could not be loaded safely.",
                        "Retry",
                        load
                    ));
                }
            } finally {
                state.loading = false;
            }
        }

        toggle.addEventListener("click", function () {
            if (!state.loaded) {
                load();
                return;
            }
            body.hidden = !body.hidden;
            toggle.textContent = body.hidden ? "Show billing orders" : "Hide billing orders";
        });
        return panel;
    }

    function transactionTypeLabel(value) {
        if (value === null || value === undefined || value === "") {
            return "Not available";
        }
        return String(value).split("_").map(function (part) {
            return part ? part.charAt(0).toUpperCase() + part.slice(1) : "";
        }).join(" ");
    }

    function aiCreditTransactionRows(transactions) {
        return transactions.map(function (transaction) {
            return [
                ui.formatDate(transaction.created_at),
                transactionTypeLabel(transaction.transaction_type),
                ui.formatMicroMyr(transaction.included_delta_micro_myr),
                ui.formatMicroMyr(transaction.topup_delta_micro_myr),
                ui.formatMicroMyr(transaction.customer_charge_micro_myr),
                ui.formatMicroMyr(transaction.uncovered_charge_micro_myr),
                ui.formatMicroMyr(transaction.included_balance_after_micro_myr),
                ui.formatMicroMyr(transaction.topup_balance_after_micro_myr),
                periodText(transaction.period_start, transaction.period_end)
            ];
        });
    }

    function aiCreditTransactionToolbar(state, load) {
        const toolbar = ui.element("div", "platform-toolbar");

        const typeField = ui.element("div", "platform-field");
        const typeLabel = ui.element("label", "", "Transaction type");
        typeLabel.setAttribute("for", "platform-ai-credit-transactions-type");
        const typeSelect = ui.element("select", "platform-select");
        typeSelect.id = "platform-ai-credit-transactions-type";
        [
            ["", "All transaction types"],
            ["included_credit_grant", "Included credit grant"],
            ["trial_credit_grant", "Trial credit grant"],
            ["usage_debit", "Usage debit"],
            ["topup_purchase", "Top-up purchase"],
            ["refund", "Refund"],
            ["manual_adjustment", "Manual adjustment"],
            ["expiry", "Expiry"],
            ["reversal", "Reversal"]
        ].forEach(function (item) {
            const option = ui.element("option", "", item[1]);
            option.value = item[0];
            if (state.transactionType === item[0]) option.selected = true;
            typeSelect.append(option);
        });
        typeSelect.addEventListener("change", function () {
            state.transactionType = typeSelect.value;
            state.offset = 0;
            load();
        });
        typeField.append(typeLabel, typeSelect);
        toolbar.append(typeField);

        const limitField = ui.element("div", "platform-field");
        const limitLabel = ui.element("label", "", "Page size");
        limitLabel.setAttribute("for", "platform-ai-credit-transactions-limit");
        const limitSelect = ui.element("select", "platform-select");
        limitSelect.id = "platform-ai-credit-transactions-limit";
        [25, 50, 100].forEach(function (value) {
            const option = ui.element("option", "", String(value));
            option.value = String(value);
            if (state.limit === value) option.selected = true;
            limitSelect.append(option);
        });
        limitSelect.addEventListener("change", function () {
            state.limit = Number(limitSelect.value);
            state.offset = 0;
            load();
        });
        limitField.append(limitLabel, limitSelect);
        toolbar.append(limitField);

        return toolbar;
    }

    function aiCreditTransactionsPanel(companyId) {
        const state = { loaded: false, loading: false, limit: 25, offset: 0, transactionType: "" };
        const panel = ui.element("section", "platform-panel");
        const header = ui.element("header", "platform-page-header");
        const title = ui.element("div");
        title.append(
            ui.element("h2", "", "AI-credit transactions"),
            ui.element("p", "", "Read-only credit ledger rows for this company. Provider economics and payment references are excluded.")
        );
        const toggle = ui.element("button", "platform-button", "Load AI-credit transactions");
        toggle.type = "button";
        header.append(title, toggle);
        const body = ui.element("div");
        body.hidden = true;
        panel.append(header, body);

        function renderLoaded(data) {
            body.replaceChildren();
            body.append(aiCreditTransactionToolbar(state, load));
            const transactions = data.transactions || [];
            if (!transactions.length) {
                body.append(sectionStateCard("No AI-credit transactions recorded."));
            } else {
                const headers = [
                    "Created", "Type", "Included delta", "Top-up delta",
                    "Customer charge", "Uncovered", "Included balance after",
                    "Top-up balance after", "Period"
                ];
                const rows = aiCreditTransactionRows(transactions);
                body.append(renderTable(headers, rows, function (cells) {
                    return rowCard(headers, cells);
                }));
            }
            body.append(paginationControls(data.pagination || {}, state, load));
        }

        async function load() {
            state.loaded = true;
            state.loading = true;
            body.hidden = false;
            body.replaceChildren(ui.element("div", "platform-loading", "Loading AI-credit transactions..."));
            toggle.textContent = "Hide AI-credit transactions";
            try {
                const data = await ui.runRequest("company-ai-credit-transactions", function (signal) {
                    return PlatformAdminApi.listCompanyAiCreditTransactions(companyId, {
                        limit: state.limit,
                        offset: state.offset,
                        transactionType: state.transactionType,
                        signal: signal,
                    });
                });
                renderLoaded(data);
            } catch (error) {
                if (error && (error.category === "unauthenticated" || error.category === "access_denied")) {
                    ui.handleError(error);
                } else if (error && error.category === "not_found") {
                    showCompanyNotFoundState();
                } else if (!error || error.category !== "aborted") {
                    body.replaceChildren(sectionStateCard(
                        "AI-credit transactions could not be loaded safely.",
                        "Retry",
                        load
                    ));
                }
            } finally {
                state.loading = false;
            }
        }

        toggle.addEventListener("click", function () {
            if (!state.loaded) {
                load();
                return;
            }
            body.hidden = !body.hidden;
            toggle.textContent = body.hidden ? "Show AI-credit transactions" : "Hide AI-credit transactions";
        });
        return panel;
    }

    function lazyListPanel(config) {
        const panel = ui.element("section", "platform-panel");
        const header = ui.element("header", "platform-page-header");
        const title = ui.element("div");
        title.append(ui.element("h2", "", config.title), ui.element("p", "", config.description));
        const toggle = ui.element("button", "platform-button", "Load " + config.title.toLowerCase());
        toggle.type = "button";
        header.append(title, toggle);
        const body = ui.element("div");
        body.hidden = true;
        panel.append(header, body);

        function renderLoaded(data) {
            body.replaceChildren();
            body.append(listToolbar(Object.assign({}, config, { load: load })));
            const items = data[config.itemsKey] || [];
            if (!items.length) {
                body.append(sectionStateCard(config.emptyText));
            } else {
                const rows = config.rowBuilder(items);
                body.append(renderTable(config.headers, rows, function (cells) {
                    return rowCard(config.headers, cells);
                }));
            }
            body.append(paginationControls(data.pagination || {}, config.state, load));
        }

        async function load() {
            config.state.loaded = true;
            config.state.loading = true;
            body.hidden = false;
            body.replaceChildren(ui.element("div", "platform-loading", "Loading " + config.title.toLowerCase() + "..."));
            toggle.textContent = "Hide " + config.title.toLowerCase();
            try {
                const data = await ui.runRequest(config.operationKey, function (signal) {
                    return config.fetch(signal);
                });
                renderLoaded(data);
            } catch (error) {
                if (error && (error.category === "unauthenticated" || error.category === "access_denied")) {
                    ui.handleError(error);
                } else if (error && error.category === "not_found") {
                    showCompanyNotFoundState();
                } else if (!error || error.category !== "aborted") {
                    body.replaceChildren(sectionStateCard(
                        config.unavailableText,
                        "Retry",
                        load
                    ));
                }
            } finally {
                config.state.loading = false;
            }
        }

        toggle.addEventListener("click", function () {
            if (!config.state.loaded) {
                load();
                return;
            }
            body.hidden = !body.hidden;
            toggle.textContent = (body.hidden ? "Show " : "Hide ") + config.title.toLowerCase();
        });
        return panel;
    }

    function usersPanel(companyId) {
        const state = makeInitialListState();
        return lazyListPanel({
            title: "Users",
            description: "Read-only users belonging to this company.",
            prefix: "platform-users",
            state: state,
            operationKey: "company-users",
            itemsKey: "users",
            emptyText: "No users found for this company.",
            unavailableText: "Users could not be loaded safely.",
            searchPlaceholder: "Search email or full name",
            sortOptions: [
                { value: "created_at", label: "Created" },
                { value: "email", label: "Email" },
                { value: "full_name", label: "Full name" },
                { value: "id", label: "ID" }
            ],
            headers: ["ID", "Full name", "Email", "Role", "Status", "Created", "Updated"],
            rowBuilder: userRows,
            fetch: function (signal) {
                return PlatformAdminApi.listCompanyUsers(companyId, {
                    limit: state.limit, offset: state.offset,
                    search: state.search.trim(), sortBy: state.sortBy,
                    sortOrder: state.sortOrder, signal: signal,
                });
            }
        });
    }

    function chatbotsPanel(companyId) {
        const state = makeInitialListState({ state: "current" });
        return lazyListPanel({
            title: "Chatbots",
            description: "Read-only chatbots belonging to this company.",
            prefix: "platform-chatbots",
            state: state,
            operationKey: "company-chatbots",
            itemsKey: "chatbots",
            emptyText: "No chatbots found for this company state.",
            unavailableText: "Chatbots could not be loaded safely.",
            searchPlaceholder: "Search bot name",
            stateOptions: [
                { value: "current", label: "Current" },
                { value: "archived", label: "Archived" },
                { value: "all", label: "All" }
            ],
            sortOptions: [
                { value: "created_at", label: "Created" },
                { value: "updated_at", label: "Updated" },
                { value: "bot_name", label: "Bot name" },
                { value: "id", label: "ID" }
            ],
            headers: ["ID", "Bot name", "Active", "Status", "Language", "Tone", "Provider", "Model", "Created", "Updated"],
            rowBuilder: chatbotRows,
            fetch: function (signal) {
                return PlatformAdminApi.listCompanyChatbots(companyId, {
                    limit: state.limit, offset: state.offset,
                    search: state.search.trim(), state: state.state,
                    sortBy: state.sortBy, sortOrder: state.sortOrder,
                    signal: signal,
                });
            }
        });
    }

    function formatPlanPrice(plan) {
        if (!plan || plan.price === null || plan.price === undefined || plan.price === "") {
            return "Not available";
        }
        const numeric = Number(plan.price);
        if (!Number.isFinite(numeric)) return "Not available";
        const currency = typeof plan.currency === "string" ? plan.currency : "MYR";
        try {
            return new Intl.NumberFormat(undefined, { style: "currency", currency: currency }).format(numeric);
        } catch (_) {
            return "Not available";
        }
    }

    function subscriptionPanel(subscription) {
        const panel = ui.element("section", "platform-panel");
        panel.append(ui.element("h2", "", "Subscription"));
        if (!subscription) {
            panel.append(ui.element("p", "platform-empty", "No subscription recorded"));
            return panel;
        }
        const plan = subscription.plan || {};
        panel.append(definitionList([
            ["Subscription status", null, ui.statusBadge(subscription.status)],
            ["Plan", plan.name || plan.code],
            ["Plan code", plan.code],
            ["Billing interval", plan.billing_interval],
            ["Price", formatPlanPrice(plan)],
            ["Current period start", ui.formatDate(subscription.current_period_start)],
            ["Current period end", ui.formatDate(subscription.current_period_end)],
            ["Trial ends", ui.formatDate(subscription.trial_ends_at)],
            ["Ends", ui.formatDate(subscription.ends_at)],
            ["Cancelled", ui.formatDate(subscription.cancelled_at)],
            ["Cancellation effective", ui.formatDate(subscription.cancellation_effective_at)],
            ["Pending plan ID", subscription.pending_plan_id]
        ]));
        return panel;
    }

    function aiCreditPanel(summary) {
        const panel = ui.element("section", "platform-panel");
        panel.append(ui.element("h2", "", "AI-credit and usage"));
        const period = summary && summary.period ? summary.period : {};
        const balance = summary && summary.credit_balance ? summary.credit_balance : {};
        const usage = summary && summary.usage ? summary.usage : {};
        const charges = summary && summary.charges ? summary.charges : {};

        panel.append(definitionList([
            ["Period start", ui.formatDate(period.start)],
            ["Period end", ui.formatDate(period.end)]
        ]));

        if (balance.initialized === false) {
            panel.append(ui.element("p", "platform-empty", "AI-credit balance not initialized"));
        } else if (balance.initialized === true) {
            const balanceHeading = ui.element("h3", "", "Credit balance");
            panel.append(balanceHeading, definitionList([
                ["Included balance", ui.formatMicroMyr(balance.included_balance_micro_myr)],
                ["Top-up balance", ui.formatMicroMyr(balance.topup_balance_micro_myr)],
                ["Total balance", ui.formatMicroMyr(balance.total_balance_micro_myr)]
            ]));
        } else {
            panel.append(ui.element("p", "platform-empty", "AI-credit balance unavailable"));
        }

        panel.append(
            ui.element("h3", "", "Current-period usage"),
            definitionList([
                ["Requests", ui.formatInteger(usage.request_count)],
                ["Prompt tokens", ui.formatInteger(usage.prompt_tokens)],
                ["Completion tokens", ui.formatInteger(usage.completion_tokens)],
                ["Total tokens", ui.formatInteger(usage.total_tokens)],
                ["Usage provider cost", ui.formatMicroUsd(usage.provider_cost_micro_usd)]
            ]),
            ui.element("h3", "", "Current-period credit charges"),
            definitionList([
                ["Transactions", ui.formatInteger(charges.transaction_count)],
                ["Customer charge", ui.formatMicroMyr(charges.customer_charge_micro_myr)],
                ["Uncovered charge", ui.formatMicroMyr(charges.uncovered_charge_micro_myr)],
                ["Charge provider cost", ui.formatMicroUsd(charges.provider_cost_micro_usd)]
            ])
        );
        return panel;
    }

    function showLocalState(title, message) {
        const root = document.getElementById("platform-page-content");
        const card = ui.element("section", "platform-state-card");
        const heading = ui.element("h1", "", title);
        heading.tabIndex = -1;
        const back = ui.element("a", "platform-link-button", "Back to companies");
        back.href = "platform-admin-companies.html";
        const actions = ui.element("div", "platform-state-actions");
        if (title.indexOf("Unable") === 0) {
            const retry = ui.element("button", "platform-button platform-button-primary", "Retry");
            retry.type = "button";
            retry.addEventListener("click", initializeCompanyDetail);
            actions.append(retry);
        }
        actions.append(back);
        card.append(heading, ui.element("p", "", message), actions);
        root.replaceChildren(card);
        heading.focus();
    }

    function showCompanyNotFoundState() {
        ui.clearPlatformState();
        const accessState = document.getElementById("platform-access-state");
        const app = document.getElementById("platform-app");
        if (accessState) accessState.hidden = true;
        if (app) app.hidden = false;
        showLocalState("Company Not Found", "The requested company does not exist or is unavailable.");
    }

    async function initializeCompanyDetail() {
        const root = document.getElementById("platform-page-content");
        const companyId = parseCompanyId();
        if (companyId === null) {
            showLocalState("Invalid company", "Select a company from the platform directory.");
            return;
        }

        root.replaceChildren(ui.element("div", "platform-loading", "Loading company..."));
        let company;
        try {
            company = await ui.runRequest("company-detail", function (signal) {
                return PlatformAdminApi.getCompany(companyId, { signal: signal });
            });
        } catch (error) {
            if (error && error.category === "not_found") {
                showLocalState("Company Not Found", "The requested company does not exist or is unavailable.");
            } else if (!ui.handleError(error) && (!error || error.category !== "aborted")) {
                showLocalState("Unable to load company", "The company request could not be completed safely.");
            }
            return;
        }

        async function reload() {
            await initializeCompanyDetail();
        }

        root.replaceChildren(
            pageHeader(company),
            companyPanel(company),
            companyLifecyclePanel(company, reload),
            ui.element("div", "platform-loading", "Loading billing summaries...")
        );
        try {
            const summaries = await Promise.all([
                ui.runRequest("company-subscription", function (signal) {
                    return PlatformAdminApi.getCompanySubscription(companyId, { signal: signal });
                }),
                ui.runRequest("company-ai-credit-usage", function (signal) {
                    return PlatformAdminApi.getCompanyAiCreditUsage(companyId, { signal: signal });
                })
            ]);
            root.replaceChildren(
                pageHeader(company),
                companyPanel(company),
                companyLifecyclePanel(company, reload),
                subscriptionPanel(summaries[0] ? summaries[0].subscription : null),
                subscriptionHistoryPanel(companyId),
                billingOrdersPanel(companyId),
                aiCreditPanel(summaries[1]),
                aiCreditTransactionsPanel(companyId),
                usersPanel(companyId),
                chatbotsPanel(companyId)
            );
        } catch (error) {
            if (!ui.handleError(error) && (!error || error.category !== "aborted")) {
                showLocalState("Unable to load summaries", "Billing summaries could not be loaded safely.");
            }
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        PlatformAdminShell.start({ onAuthorized: initializeCompanyDetail });
    });
}());
