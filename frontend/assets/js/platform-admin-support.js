(function () {
    "use strict";

    const ui = PlatformAdminShell;
    const state = {
        results: null,
        error: null,
        searchInput: null,
        searchButton: null,
        loadSequence: 0,
        caseResults: null,
        caseDetail: null,
        caseError: null,
        tenantRequestResults: null,
        tenantRequestDetail: null,
        tenantRequestError: null,
        tenantRequestLoadSequence: 0,
        tenantRequestConversionCaseId: null
    };

    function safeValue(value) {
        return value === null || value === undefined || value === "" ? "Not available" : String(value);
    }

    function companyLink(companyId, label) {
        if (!Number.isSafeInteger(companyId) || companyId <= 0) {
            return ui.element("span", "", safeValue(label || "Unavailable"));
        }
        const params = new URLSearchParams();
        params.set("company_id", String(companyId));
        const link = ui.element("a", "platform-link-button", label || "Investigate");
        link.href = "platform-admin-company.html?" + params.toString();
        return link;
    }

    function internalSupportCaseLink(caseId) {
        if (!Number.isSafeInteger(caseId) || caseId <= 0) {
            return ui.element("span", "", "Unavailable");
        }
        const link = ui.element("a", "platform-link-button", "Open internal case #" + String(caseId));
        link.href = "platform-admin-support.html?case_id=" + String(caseId);
        return link;
    }

    function clearTenantRequestState() {
        state.tenantRequestConversionCaseId = null;
        if (state.tenantRequestResults) state.tenantRequestResults.replaceChildren();
        if (state.tenantRequestDetail) state.tenantRequestDetail.replaceChildren();
    }

    function panel(title, description) {
        const section = ui.element("section", "platform-panel");
        section.append(ui.element("h2", "", title));
        if (description) section.append(ui.element("p", "platform-note", description));
        return section;
    }

    function renderQuickNavigation() {
        const nav = ui.element("nav", "platform-support-actions");
        nav.setAttribute("aria-label", "Support workspace quick navigation");
        const companies = ui.element("a", "platform-link-button", "View all companies");
        companies.href = "platform-admin-companies.html";
        const dashboard = ui.element("a", "platform-link-button", "Return to dashboard");
        dashboard.href = "platform-admin.html";
        nav.append(companies, dashboard);
        return nav;
    }

    function attentionReason(company) {
        const status = company && company.subscription_status;
        if (status === "past_due") return "Past due subscription";
        if (status === "expired") return "Expired subscription";
        return "Requires review";
    }

    function table(headers, rows, captionText) {
        const wrap = ui.element("div", "platform-table-wrap");
        const tableNode = ui.element("table", "platform-table");
        const caption = ui.element("caption", "platform-skip-link", captionText);
        const head = ui.element("thead");
        const headerRow = ui.element("tr");
        headers.forEach(function (label) {
            const th = ui.element("th", "", label);
            th.scope = "col";
            headerRow.append(th);
        });
        head.append(headerRow);
        const body = ui.element("tbody");
        rows.forEach(function (cells) {
            const row = ui.element("tr");
            cells.forEach(function (cell) {
                const td = ui.element("td");
                if (cell && cell.nodeType) td.append(cell);
                else td.textContent = safeValue(cell);
                row.append(td);
            });
            body.append(row);
        });
        tableNode.append(caption, head, body);
        wrap.append(tableNode);
        return wrap;
    }

    function cardLine(label, value) {
        const line = ui.element("div");
        line.append(ui.element("dt", "", label));
        const dd = ui.element("dd");
        if (value && value.nodeType) dd.append(value);
        else dd.textContent = safeValue(value);
        line.append(dd);
        return line;
    }

    function mobileCards(items, type) {
        const cards = ui.element("div", "platform-company-cards");
        cards.setAttribute("aria-label", type + " cards");
        items.forEach(function (item) {
            const article = ui.element("article", "platform-company-card");
            article.append(ui.element("h3", "", safeValue(item.company_name || item.name)));
            const details = ui.element("dl", "platform-definition-grid");
            if (type === "attention company") {
                details.append(
                    cardLine("Company ID", item.company_id),
                    cardLine("Subscription status", item.subscription_status),
                    cardLine("Plan", item.plan_name || item.plan_code),
                    cardLine("Reason", attentionReason(item)),
                    cardLine("Investigate", companyLink(item.company_id, "Open investigation"))
                );
            } else {
                details.append(
                    cardLine("Company ID", item.id),
                    cardLine("Business type", item.business_type),
                    cardLine("Status", item.status),
                    cardLine("Contact email", item.contact_email),
                    cardLine("Investigate", companyLink(item.id, "Open investigation"))
                );
            }
            article.append(details);
            cards.append(article);
        });
        return cards;
    }

    function renderAttention(overview) {
        const section = panel(
            "Companies requiring attention",
            "Read-only signals from the platform operations overview. Open a company to inspect details before deciding next steps."
        );
        const companies = overview && Array.isArray(overview.attention_companies)
            ? overview.attention_companies
            : [];
        if (companies.length === 0) {
            section.append(ui.element("p", "platform-empty", "No companies currently require attention."));
            return section;
        }
        const rows = companies.map(function (company) {
            return [
                company.company_id,
                company.company_name,
                ui.statusBadge(company.subscription_status),
                company.plan_name || company.plan_code,
                attentionReason(company),
                companyLink(company.company_id, "Investigate")
            ];
        });
        section.append(table(
            ["Company ID", "Company", "Subscription", "Plan", "Reason", "Action"],
            rows,
            "Companies requiring support attention"
        ));
        section.append(mobileCards(companies, "attention company"));
        return section;
    }

    function renderLookupEmpty(message) {
        if (!state.results) return;
        state.results.replaceChildren(ui.element("p", "platform-empty", message));
        state.results.setAttribute("aria-busy", "false");
    }

    function renderLookupResults(data) {
        const companies = data && Array.isArray(data.companies) ? data.companies : [];
        const pagination = data && data.pagination ? data.pagination : {};
        if (companies.length === 0) {
            renderLookupEmpty("No company search results found.");
            return;
        }
        const rows = companies.map(function (company) {
            return [
                company.id,
                company.company_name,
                company.business_type,
                ui.statusBadge(company.status),
                company.contact_email,
                ui.formatDate(company.created_at),
                companyLink(company.id, "Investigate")
            ];
        });
        const fragment = document.createDocumentFragment();
        fragment.append(table(
            ["ID", "Company", "Business type", "Status", "Contact email", "Created", "Action"],
            rows,
            "Company lookup results"
        ));
        fragment.append(mobileCards(companies, "company result"));
        fragment.append(ui.element(
            "p",
            "platform-note",
            "Showing " + safeValue(pagination.returned) + " of " + safeValue(pagination.total) + " matching companies."
        ));
        state.results.replaceChildren(fragment);
        state.results.setAttribute("aria-busy", "false");
    }

    async function searchCompanies() {
        const sequence = ++state.loadSequence;
        const search = state.searchInput ? state.searchInput.value.trim() : "";
        if (!search) {
            if (state.error) state.error.textContent = "Enter a company name or ID before searching.";
            renderLookupEmpty("Company results will appear after an intentional search.");
            return;
        }
        if (search.length > 100) {
            if (state.error) state.error.textContent = "Search must contain 100 characters or fewer.";
            return;
        }
        if (state.error) state.error.textContent = "";
        state.results.replaceChildren(ui.element("div", "platform-loading", "Loading company results..."));
        state.results.setAttribute("aria-busy", "true");
        try {
            const data = await ui.runRequest("support-company-lookup", function (signal) {
                return PlatformAdminApi.listCompanies({
                    limit: 25,
                    offset: 0,
                    search: search,
                    status: undefined,
                    sortBy: "company_name",
                    sortOrder: "asc",
                    signal: signal
                });
            });
            if (sequence === state.loadSequence) renderLookupResults(data);
        } catch (error) {
            if (error && error.category === "validation") {
                state.results.replaceChildren();
                state.results.setAttribute("aria-busy", "false");
                if (state.error) state.error.textContent = "The company lookup could not be validated.";
            } else if (!ui.handleError(error) && (!error || error.category !== "aborted")) {
                state.results.replaceChildren(ui.element("p", "platform-empty", "Company lookup is temporarily unavailable."));
                state.results.setAttribute("aria-busy", "false");
            }
        } finally {
            if (sequence === state.loadSequence && state.results) {
                state.results.setAttribute("aria-busy", "false");
            }
        }
    }

    function renderLookup() {
        const section = panel(
            "Company lookup",
            "Search for one tenant company, then open the existing read-only company investigation page."
        );
        const form = ui.element("form", "platform-support-search");
        form.setAttribute("role", "search");
        const field = ui.element("div", "platform-field");
        const label = ui.element("label", "", "Company name or ID");
        label.htmlFor = "platform-support-company-search";
        state.searchInput = ui.element("input", "platform-input");
        state.searchInput.id = "platform-support-company-search";
        state.searchInput.type = "search";
        state.searchInput.maxLength = 100;
        state.searchInput.autocomplete = "off";
        field.append(label, state.searchInput);
        state.searchButton = ui.element("button", "platform-button platform-button-primary", "Search companies");
        state.searchButton.type = "submit";
        form.append(field, state.searchButton);
        form.addEventListener("submit", function (event) {
            event.preventDefault();
            searchCompanies();
        });
        state.error = ui.element("p", "platform-inline-error");
        state.error.setAttribute("aria-live", "polite");
        state.results = ui.element("div", "platform-support-results");
        state.results.setAttribute("aria-live", "polite");
        renderLookupEmpty("Company results will appear after an intentional search.");
        section.append(form, state.error, state.results);
        return section;
    }

    function selectField(labelText, id, values, selected) {
        const field = ui.element("div", "platform-field");
        const label = ui.element("label", "", labelText);
        label.htmlFor = id;
        const select = ui.element("select", "platform-input");
        select.id = id;
        values.forEach(function (value) {
            const option = ui.element("option", "", value.label);
            option.value = value.value;
            option.selected = value.value === selected;
            select.append(option);
        });
        field.append(label, select);
        return { field: field, input: select };
    }

    function renderCaseDetail(data) {
        if (!state.caseDetail) return;
        const current = data && data.case ? data.case : null;
        if (!current) {
            state.caseDetail.replaceChildren(ui.element("p", "platform-empty", "Select a support case to inspect it."));
            return;
        }
        const section = panel(
            "Internal support case detail",
            "Internal platform notes only. This view contains no customer conversation or external communication controls."
        );
        section.append(
            ui.element("h3", "", safeValue(current.title)),
            cardLine("Case ID", current.id),
            cardLine("Company ID", current.company_id),
            cardLine("Status", current.status),
            cardLine("Priority", current.priority),
            cardLine("Redacted summary", current.redacted_summary),
            cardLine("Updated", ui.formatDate(current.updated_at))
        );
        const events = Array.isArray(data.events) ? data.events : [];
        section.append(ui.element("h3", "", "Append-only case events"));
        if (!events.length) section.append(ui.element("p", "platform-empty", "No case events recorded."));
        else section.append(table(
            ["Event", "Actor mapping", "Status", "Priority", "Redacted note", "Created"],
            events.map(function (event) {
                return [event.event_type, event.actor_platform_admin_user_id,
                    event.new_status || event.old_status, event.new_priority || event.old_priority,
                    event.redacted_note, ui.formatDate(event.created_at)];
            }),
            "Support-case events"
        ));

        const controls = ui.element("div", "platform-support-actions");
        const status = selectField("Status", "platform-support-case-status", [
            { value: "open", label: "Open" },
            { value: "in_progress", label: "In progress" },
            { value: "resolved", label: "Resolved" },
            { value: "closed", label: "Closed" }
        ], current.status);
        const priority = selectField("Priority", "platform-support-case-priority", [
            { value: "low", label: "Low" },
            { value: "normal", label: "Normal" },
            { value: "high", label: "High" },
            { value: "urgent", label: "Urgent" }
        ], current.priority);
        const update = ui.element("button", "platform-button platform-button-primary", "Update case");
        update.type = "button";
        update.addEventListener("click", async function () {
            try {
                await ui.runRequest("support-case-update", function (signal) {
                    return PlatformAdminApi.updateSupportCase(current.id, {
                        status: status.input.value, priority: priority.input.value
                    }, { signal: signal });
                });
                await openSupportCase(current.id);
                await loadSupportCases();
            } catch (error) {
                if (!ui.handleError(error) && state.caseError) state.caseError.textContent = "The case could not be updated.";
            }
        });
        controls.append(status.field, priority.field, update);
        section.append(controls);

        const noteForm = ui.element("form", "platform-support-search");
        const noteField = ui.element("div", "platform-field");
        const noteLabel = ui.element("label", "", "Redacted internal note");
        const noteInput = ui.element("textarea", "platform-input");
        noteInput.maxLength = 2000;
        noteInput.required = true;
        noteField.append(noteLabel, noteInput);
        const noteButton = ui.element("button", "platform-button", "Add internal note");
        noteButton.type = "submit";
        noteForm.append(noteField, noteButton);
        noteForm.addEventListener("submit", async function (event) {
            event.preventDefault();
            try {
                await ui.runRequest("support-case-note", function (signal) {
                    return PlatformAdminApi.addSupportCaseNote(current.id, {
                        redacted_note: noteInput.value
                    }, { signal: signal });
                });
                noteInput.value = "";
                await openSupportCase(current.id);
            } catch (error) {
                if (!ui.handleError(error) && state.caseError) state.caseError.textContent = "The internal note could not be added.";
            }
        });
        section.append(noteForm);
        state.caseDetail.replaceChildren(section);
    }

    async function openSupportCase(caseId) {
        try {
            const data = await ui.runRequest("support-case-detail", function (signal) {
                return PlatformAdminApi.getSupportCase(caseId, { signal: signal });
            });
            renderCaseDetail(data);
        } catch (error) {
            if (!ui.handleError(error) && state.caseError) state.caseError.textContent = "The support case could not be loaded.";
        }
    }

    async function loadSupportCases() {
        try {
            const data = await ui.runRequest("support-case-list", function (signal) {
                return PlatformAdminApi.listSupportCases({ limit: 25, offset: 0, signal: signal });
            });
            const cases = data && Array.isArray(data.cases) ? data.cases : [];
            if (!state.caseResults) return;
            if (!cases.length) {
                state.caseResults.replaceChildren(ui.element("p", "platform-empty", "No internal support cases found."));
                return;
            }
            state.caseResults.replaceChildren(table(
                ["ID", "Company", "Title", "Status", "Priority", "Updated", "Action"],
                cases.map(function (item) {
                    const button = ui.element("button", "platform-link-button", "Open case");
                    button.type = "button";
                    button.addEventListener("click", function () { openSupportCase(item.id); });
                    return [item.id, item.company_id, item.title, item.status, item.priority,
                        ui.formatDate(item.updated_at), button];
                }),
                "Internal support cases"
            ));
        } catch (error) {
            if (!ui.handleError(error) && state.caseError) state.caseError.textContent = "Support cases are temporarily unavailable.";
        }
    }

    function renderTenantRequestDetail(data) {
        if (!state.tenantRequestDetail) return;
        const current = data && data.request ? data.request : null;
        if (!current) {
            state.tenantRequestDetail.replaceChildren(ui.element("p", "platform-empty", "Select a tenant-submitted request to inspect it."));
            return;
        }
        const section = panel(
            "Tenant-submitted support request detail",
            "Read-only intake review. Title and redacted description are rendered as text only."
        );
        section.append(
            cardLine("Request ID", current.request_id),
            cardLine("Company", companyLink(current.company_id, "Open company investigation")),
            cardLine("Requester user ID", current.requester_user_id),
            cardLine("Category", current.category),
            cardLine("Status", current.status),
            cardLine("Priority", current.priority),
            cardLine("Source", current.source),
            cardLine("Title", current.title),
            cardLine("Redacted description", current.redacted_description),
            cardLine("Created", ui.formatDate(current.created_at)),
            cardLine("Updated", ui.formatDate(current.updated_at))
        );
        const events = Array.isArray(data.events) ? data.events : [];
        section.append(ui.element("h3", "", "Tenant request events"));
        section.append(events.length ? table(
            ["Event", "Actor type", "Created"],
            events.map(function (event) {
                return [event.event_type, event.actor_type, ui.formatDate(event.created_at)];
            }),
            "Tenant support request events"
        ) : ui.element("p", "platform-empty", "No request events recorded."));
        if (state.tenantRequestConversionCaseId) {
            section.append(cardLine(
                "Converted internal case",
                internalSupportCaseLink(state.tenantRequestConversionCaseId)
            ));
        }
        if (current.status === "new" || current.status === "reviewed") {
            const controls = ui.element("div", "platform-support-actions");
            if (current.status === "new") {
                controls.append(tenantRequestActionButton(
                    "Mark reviewed", function () {
                        updateTenantRequestStatus(current.request_id, "reviewed");
                    }
                ));
            }
            controls.append(tenantRequestActionButton(
                "Close request", function () {
                    updateTenantRequestStatus(current.request_id, "closed");
                }
            ));
            controls.append(tenantRequestActionButton(
                "Convert to internal case", function () {
                    convertTenantRequest(current.request_id);
                }
            ));
            section.append(controls);
        }
        state.tenantRequestDetail.replaceChildren(section);
    }

    function tenantRequestActionButton(label, action) {
        const button = ui.element("button", "platform-button", label);
        button.type = "button";
        button.addEventListener("click", action);
        return button;
    }

    async function updateTenantRequestStatus(requestId, status) {
        if (!window.confirm("Confirm changing this tenant support request to " + status + "?")) return;
        try {
            await ui.runRequest("tenant-support-request-status", function (signal) {
                return PlatformAdminApi.updateTenantSupportRequest(
                    requestId, { status: status }, { signal: signal }
                );
            });
            await loadTenantSupportRequests();
            await openTenantSupportRequest(requestId);
        } catch (error) {
            clearTenantRequestState();
            if (!ui.handleError(error) && state.tenantRequestError) {
                state.tenantRequestError.textContent = "The tenant support request could not be updated.";
            }
        }
    }

    async function convertTenantRequest(requestId) {
        if (!window.confirm("Convert this tenant support request into an internal support case?")) return;
        try {
            const data = await ui.runRequest("tenant-support-request-convert", function (signal) {
                return PlatformAdminApi.convertTenantSupportRequest(requestId, { signal: signal });
            });
            state.tenantRequestConversionCaseId = data && data.converted_platform_support_case_id;
            await loadTenantSupportRequests();
            await openTenantSupportRequest(requestId);
        } catch (error) {
            clearTenantRequestState();
            if (!ui.handleError(error) && state.tenantRequestError) {
                state.tenantRequestError.textContent = "The tenant support request could not be converted.";
            }
        }
    }

    async function openTenantSupportRequest(requestId) {
        const sequence = ++state.tenantRequestLoadSequence;
        try {
            const data = await ui.runRequest("tenant-support-request-detail", function (signal) {
                return PlatformAdminApi.getTenantSupportRequest(requestId, { signal: signal });
            });
            if (sequence === state.tenantRequestLoadSequence) renderTenantRequestDetail(data);
        } catch (error) {
            if (sequence === state.tenantRequestLoadSequence && state.tenantRequestDetail) {
                state.tenantRequestDetail.replaceChildren();
                state.tenantRequestConversionCaseId = null;
            }
            if (!ui.handleError(error) && state.tenantRequestError) {
                state.tenantRequestError.textContent = "The tenant support request could not be loaded.";
            }
        }
    }

    async function loadTenantSupportRequests() {
        const sequence = ++state.tenantRequestLoadSequence;
        if (state.tenantRequestResults) {
            state.tenantRequestResults.replaceChildren(ui.element("div", "platform-loading", "Loading tenant-submitted support requests..."));
            state.tenantRequestResults.setAttribute("aria-busy", "true");
        }
        try {
            const data = await ui.runRequest("tenant-support-request-list", function (signal) {
                return PlatformAdminApi.listTenantSupportRequests({ limit: 25, offset: 0, signal: signal });
            });
            if (sequence !== state.tenantRequestLoadSequence || !state.tenantRequestResults) return;
            const requests = data && Array.isArray(data.requests) ? data.requests : [];
            if (!requests.length) {
                state.tenantRequestResults.replaceChildren(ui.element("p", "platform-empty", "No tenant-submitted support requests found."));
                return;
            }
            state.tenantRequestResults.replaceChildren(table(
                ["ID", "Company", "Requester", "Category", "Status", "Priority", "Created", "Action"],
                requests.map(function (item) {
                    const button = ui.element("button", "platform-link-button", "Open request");
                    button.type = "button";
                    button.addEventListener("click", function () { openTenantSupportRequest(item.request_id); });
                    return [item.request_id, companyLink(item.company_id, String(item.company_id)),
                        item.requester_user_id, item.category, item.status, item.priority,
                        ui.formatDate(item.created_at), button];
                }),
                "Tenant-submitted support requests"
            ));
        } catch (error) {
            if (sequence === state.tenantRequestLoadSequence && state.tenantRequestResults) {
                state.tenantRequestResults.replaceChildren();
            }
            if (!ui.handleError(error) && state.tenantRequestError) {
                state.tenantRequestError.textContent = "Tenant support requests are temporarily unavailable.";
            }
        } finally {
            if (sequence === state.tenantRequestLoadSequence && state.tenantRequestResults) {
                state.tenantRequestResults.setAttribute("aria-busy", "false");
            }
        }
    }

    function renderTenantSupportRequests() {
        const section = panel(
            "Tenant-submitted support requests",
            "Read-only intake review. Approved review, close, and conversion controls are available after Migration 031 is applied. Assignment, replies, billing, exports, charts, messaging, email, attachments, and impersonation remain excluded."
        );
        state.tenantRequestError = ui.element("p", "platform-inline-error");
        state.tenantRequestError.setAttribute("aria-live", "polite");
        state.tenantRequestResults = ui.element("div", "platform-support-results");
        state.tenantRequestResults.setAttribute("aria-live", "polite");
        state.tenantRequestResults.setAttribute("aria-busy", "true");
        state.tenantRequestDetail = ui.element("div", "platform-support-results");
        state.tenantRequestDetail.append(ui.element("p", "platform-empty", "Select a tenant-submitted request to inspect it."));
        section.append(state.tenantRequestError, state.tenantRequestResults, state.tenantRequestDetail);
        return section;
    }

    function renderSupportCases() {
        const section = panel(
            "Internal support cases",
            "Localhost-only internal tracking for redacted investigation notes. Cases are not customer-facing."
        );
        state.caseError = ui.element("p", "platform-inline-error");
        state.caseError.setAttribute("aria-live", "polite");
        const form = ui.element("form", "platform-support-search");
        const company = ui.element("input", "platform-input");
        company.type = "number"; company.min = "1"; company.required = true;
        const title = ui.element("input", "platform-input");
        title.maxLength = 160; title.required = true;
        const summary = ui.element("textarea", "platform-input");
        summary.maxLength = 2000; summary.required = true;
        const companyField = ui.element("div", "platform-field");
        const companyLabel = ui.element("label", "", "Company ID"); companyLabel.append(company); companyField.append(companyLabel);
        const titleField = ui.element("div", "platform-field");
        const titleLabel = ui.element("label", "", "Case title"); titleLabel.append(title); titleField.append(titleLabel);
        const summaryField = ui.element("div", "platform-field");
        const summaryLabel = ui.element("label", "", "Redacted summary"); summaryLabel.append(summary); summaryField.append(summaryLabel);
        const create = ui.element("button", "platform-button platform-button-primary", "Create internal case");
        create.type = "submit";
        form.append(companyField, titleField, summaryField, create);
        form.addEventListener("submit", async function (event) {
            event.preventDefault();
            try {
                const data = await ui.runRequest("support-case-create", function (signal) {
                    return PlatformAdminApi.createSupportCase({
                        company_id: Number(company.value), title: title.value,
                        redacted_summary: summary.value
                    }, { signal: signal });
                });
                company.value = ""; title.value = ""; summary.value = "";
                await loadSupportCases();
                if (data && data.case) await openSupportCase(data.case.id);
            } catch (error) {
                if (!ui.handleError(error) && state.caseError) state.caseError.textContent = "The support case could not be created.";
            }
        });
        state.caseResults = ui.element("div", "platform-support-results");
        state.caseDetail = ui.element("div", "platform-support-results");
        state.caseResults.append(ui.element("p", "platform-loading", "Loading internal support cases..."));
        state.caseDetail.append(ui.element("p", "platform-empty", "Select a support case to inspect it."));
        section.append(form, state.caseError, state.caseResults, state.caseDetail);
        return section;
    }

    function renderWorkspaceSkeleton() {
        const root = document.getElementById("platform-page-content");
        const header = ui.element("header", "platform-page-header");
        const titleGroup = ui.element("div");
        titleGroup.append(
            ui.element("h1", "", "Support Workspace"),
            ui.element("p", "", "Read-only tenant investigation for platform administrators. This workspace does not message tenants, but may perform approved internal review, close, and conversion actions after Migration 031 is applied.")
        );
        header.append(titleGroup, renderQuickNavigation());
        root.replaceChildren(
            header,
            ui.element("div", "platform-loading", "Loading support workspace...")
        );
    }

    async function initializeSupportWorkspace() {
        renderWorkspaceSkeleton();
        const root = document.getElementById("platform-page-content");
        try {
            const overview = await ui.runRequest("support-overview", function (signal) {
                return PlatformAdminApi.getOverview({ signal: signal });
            });
            root.replaceChildren(
                root.firstChild,
                renderAttention(overview),
                renderLookup(),
                renderSupportCases(),
                renderTenantSupportRequests()
            );
            await loadSupportCases();
            await loadTenantSupportRequests();
        } catch (error) {
            if (!ui.handleError(error) && (!error || error.category !== "aborted")) {
                root.replaceChildren(ui.element("p", "platform-empty", "Support workspace data is temporarily unavailable."));
            }
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        PlatformAdminShell.start({ onAuthorized: initializeSupportWorkspace });
    });
}());
