(function () {
    "use strict";

    const ui = PlatformAdminShell;
    const ALLOWED_STATUSES = new Set(["", "active", "inactive"]);
    const ALLOWED_SORT_FIELDS = new Set(["created_at", "company_name", "status", "id"]);
    const ALLOWED_SORT_ORDERS = new Set(["asc", "desc"]);
    const ALLOWED_LIMITS = new Set([25, 50, 100]);
    const state = {
        search: "",
        status: "",
        sortBy: "created_at",
        sortOrder: "desc",
        limit: 25,
        offset: 0,
        pagination: null,
        debounceTimer: null,
        loadSequence: 0,
        controls: [],
        results: null,
        error: null
    };

    function safeValue(value) {
        return value === null || value === undefined || value === "" ? "Not available" : String(value);
    }

    function field(label, control) {
        const wrapper = ui.element("div", "platform-field");
        const labelNode = ui.element("label", "", label);
        labelNode.htmlFor = control.id;
        wrapper.append(labelNode, control);
        return wrapper;
    }

    function option(value, label) {
        const node = ui.element("option", "", label);
        node.value = value;
        return node;
    }

    function companyLink(companyId) {
        if (!Number.isSafeInteger(companyId) || companyId <= 0) return null;
        const params = new URLSearchParams();
        params.set("company_id", String(companyId));
        const link = ui.element("a", "", "View details");
        link.href = "platform-admin-company.html?" + params.toString();
        return link;
    }

    function setControlsDisabled(disabled) {
        state.controls.forEach(function (control) {
            control.disabled = disabled;
        });
    }

    function renderLoading() {
        state.results.replaceChildren(ui.element("div", "platform-loading", "Loading companies…"));
        state.results.setAttribute("aria-busy", "true");
    }

    function renderEmpty() {
        const empty = ui.element("div", "platform-empty");
        empty.append(
            ui.element("h2", "", "No companies found"),
            ui.element("p", "", "No companies match the current directory filters.")
        );
        const clear = ui.element("button", "platform-button", "Clear filters");
        clear.type = "button";
        clear.addEventListener("click", function () {
            state.search = "";
            state.status = "";
            state.sortBy = "created_at";
            state.sortOrder = "desc";
            state.offset = 0;
            buildDirectory();
            loadCompanies();
        });
        empty.append(clear);
        state.results.replaceChildren(empty);
        state.results.setAttribute("aria-busy", "false");
    }

    function appendTableCell(row, value) {
        row.append(ui.element("td", "", safeValue(value)));
    }

    function renderDesktopTable(companies) {
        const wrap = ui.element("div", "platform-table-wrap");
        const table = ui.element("table", "platform-table");
        const caption = ui.element("caption", "", "Platform company directory");
        caption.className = "platform-skip-link";
        const head = ui.element("thead");
        const headerRow = ui.element("tr");
        [
            ["ID", "id"],
            ["Company name", "company_name"],
            ["Business type", null],
            ["Status", "status"],
            ["Contact email", null],
            ["Created", "created_at"],
            ["Details", null]
        ].forEach(function (definition) {
            const th = ui.element("th", "", definition[0]);
            th.scope = "col";
            if (definition[1]) {
                th.setAttribute(
                    "aria-sort",
                    state.sortBy === definition[1]
                        ? (state.sortOrder === "asc" ? "ascending" : "descending")
                        : "none"
                );
            }
            headerRow.append(th);
        });
        head.append(headerRow);
        const body = ui.element("tbody");
        companies.forEach(function (company) {
            const row = ui.element("tr");
            appendTableCell(row, company.id);
            appendTableCell(row, company.company_name);
            appendTableCell(row, company.business_type);
            const statusCell = ui.element("td");
            statusCell.append(ui.statusBadge(company.status));
            row.append(statusCell);
            appendTableCell(row, company.contact_email);
            appendTableCell(row, ui.formatDate(company.created_at));
            const detailCell = ui.element("td");
            const link = companyLink(company.id);
            detailCell.append(link || ui.element("span", "", "Unavailable"));
            row.append(detailCell);
            body.append(row);
        });
        table.append(caption, head, body);
        wrap.append(table);
        return wrap;
    }

    function cardLine(label, value) {
        const line = ui.element("div");
        line.append(ui.element("dt", "", label), ui.element("dd", "", safeValue(value)));
        return line;
    }

    function renderMobileCards(companies) {
        const cards = ui.element("div", "platform-company-cards");
        cards.setAttribute("aria-label", "Company cards");
        companies.forEach(function (company) {
            const article = ui.element("article", "platform-company-card");
            article.append(ui.element("h2", "", safeValue(company.company_name)));
            const details = ui.element("dl", "platform-definition-grid");
            details.append(
                cardLine("ID", company.id),
                cardLine("Business type", company.business_type),
                cardLine("Contact email", company.contact_email),
                cardLine("Created", ui.formatDate(company.created_at))
            );
            const statusLine = ui.element("div");
            statusLine.append(ui.element("dt", "", "Status"));
            const statusValue = ui.element("dd");
            statusValue.append(ui.statusBadge(company.status));
            statusLine.append(statusValue);
            details.append(statusLine);
            article.append(details);
            const link = companyLink(company.id);
            if (link) {
                link.className = "platform-link-button";
                article.append(link);
            }
            cards.append(article);
        });
        return cards;
    }

    function validPagination(pagination) {
        return pagination
            && Number.isSafeInteger(pagination.limit) && pagination.limit > 0
            && Number.isSafeInteger(pagination.offset) && pagination.offset >= 0
            && Number.isSafeInteger(pagination.returned) && pagination.returned >= 0
            && Number.isSafeInteger(pagination.total) && pagination.total >= 0
            && typeof pagination.has_more === "boolean";
    }

    function renderCompanies(result) {
        const companies = result && Array.isArray(result.companies) ? result.companies : null;
        const pagination = result ? result.pagination : null;
        if (!companies || !validPagination(pagination)) {
            const error = new Error("unavailable");
            error.category = "unavailable";
            throw error;
        }
        state.pagination = pagination;
        if (companies.length === 0) {
            renderEmpty();
            return;
        }

        const fragment = document.createDocumentFragment();
        fragment.append(renderDesktopTable(companies), renderMobileCards(companies));
        const start = pagination.offset + 1;
        const end = pagination.offset + pagination.returned;
        const paginationBar = ui.element("div", "platform-pagination");
        const summary = ui.element(
            "p",
            "platform-note",
            "Showing " + start + "–" + end + " of " + pagination.total + " companies"
        );
        const actions = ui.element("div", "platform-pagination-actions");
        const previous = ui.element("button", "platform-button", "Previous");
        previous.type = "button";
        previous.disabled = pagination.offset === 0;
        previous.addEventListener("click", function () {
            state.offset = Math.max(0, pagination.offset - pagination.limit);
            loadCompanies();
        });
        const next = ui.element("button", "platform-button", "Next");
        next.type = "button";
        next.disabled = !pagination.has_more;
        next.addEventListener("click", function () {
            state.offset = pagination.offset + pagination.limit;
            loadCompanies();
        });
        actions.append(previous, next);
        paginationBar.append(summary, actions);
        fragment.append(paginationBar);
        state.results.replaceChildren(fragment);
        state.results.setAttribute("aria-busy", "false");
    }

    async function loadCompanies() {
        const sequence = ++state.loadSequence;
        setControlsDisabled(true);
        state.error.textContent = "";
        renderLoading();
        try {
            const result = await ui.runRequest("company-list", function (signal) {
                return PlatformAdminApi.listCompanies({
                    limit: state.limit,
                    offset: state.offset,
                    search: state.search || undefined,
                    status: state.status || undefined,
                    sortBy: state.sortBy,
                    sortOrder: state.sortOrder,
                    signal: signal
                });
            });
            renderCompanies(result);
        } catch (error) {
            if (error && error.category === "validation") {
                state.results.replaceChildren();
                state.results.setAttribute("aria-busy", "false");
                state.error.textContent = "The directory filters are invalid. Review the controls and try again.";
            } else {
                ui.handleError(error);
            }
        } finally {
            if (sequence === state.loadSequence) setControlsDisabled(false);
        }
    }

    function buildDirectory() {
        const root = document.getElementById("platform-page-content");
        root.replaceChildren();
        const header = ui.element("header", "platform-page-header");
        const title = ui.element("div");
        title.append(
            ui.element("h1", "", "Company directory"),
            ui.element("p", "", "Search and inspect tenant companies without changing their data.")
        );
        header.append(title);

        const panel = ui.element("section", "platform-panel");
        const toolbar = ui.element("div", "platform-toolbar");
        const search = ui.element("input", "platform-input");
        search.id = "platform-company-search";
        search.type = "search";
        search.maxLength = 100;
        search.autocomplete = "off";
        search.value = state.search;
        search.addEventListener("input", function () {
            window.clearTimeout(state.debounceTimer);
            const value = search.value.trim();
            state.debounceTimer = window.setTimeout(function () {
                state.search = value;
                state.offset = 0;
                loadCompanies();
            }, 350);
        });

        const status = ui.element("select", "platform-select");
        status.id = "platform-company-status";
        status.append(option("", "All"), option("active", "Active"), option("inactive", "Inactive"));
        status.value = state.status;
        status.addEventListener("change", function () {
            if (!ALLOWED_STATUSES.has(status.value)) return;
            state.status = status.value;
            state.offset = 0;
            loadCompanies();
        });

        const sort = ui.element("select", "platform-select");
        sort.id = "platform-company-sort";
        sort.append(
            option("created_at", "Created"),
            option("company_name", "Company Name"),
            option("status", "Status"),
            option("id", "ID")
        );
        sort.value = state.sortBy;
        sort.addEventListener("change", function () {
            if (!ALLOWED_SORT_FIELDS.has(sort.value)) return;
            state.sortBy = sort.value;
            state.offset = 0;
            loadCompanies();
        });

        const order = ui.element("select", "platform-select");
        order.id = "platform-company-sort-order";
        order.append(option("desc", "Descending"), option("asc", "Ascending"));
        order.value = state.sortOrder;
        order.addEventListener("change", function () {
            if (!ALLOWED_SORT_ORDERS.has(order.value)) return;
            state.sortOrder = order.value;
            state.offset = 0;
            loadCompanies();
        });

        const limit = ui.element("select", "platform-select");
        limit.id = "platform-company-page-size";
        limit.append(option("25", "25"), option("50", "50"), option("100", "100"));
        limit.value = String(state.limit);
        limit.addEventListener("change", function () {
            const parsed = Number(limit.value);
            if (!ALLOWED_LIMITS.has(parsed)) return;
            state.limit = parsed;
            state.offset = 0;
            loadCompanies();
        });

        toolbar.append(
            field("Search companies", search),
            field("Status", status),
            field("Sort field", sort),
            field("Sort order", order),
            field("Page size", limit)
        );
        state.error = ui.element("p", "platform-inline-error");
        state.error.setAttribute("aria-live", "polite");
        state.results = ui.element("div");
        state.results.setAttribute("aria-live", "polite");
        panel.append(toolbar, state.error, state.results);
        root.append(header, panel);
        state.controls = [search, status, sort, order, limit];
    }

    async function initializeDirectory() {
        buildDirectory();
        await loadCompanies();
    }

    document.addEventListener("DOMContentLoaded", function () {
        PlatformAdminShell.start({ onAuthorized: initializeDirectory });
    });
}());
