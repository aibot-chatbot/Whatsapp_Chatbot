(function () {
    "use strict";

    const ui = window.PlatformAdminShell;
    const api = window.PlatformAdminHelpApi;

    // An article is called out for review once real dissent exists, not on a
    // single stray vote.
    const NEEDS_REVIEW_MIN_UNHELPFUL = 2;
    // New articles land at the bottom of the list instead of colliding on the
    // server-side sort_order default of 0.
    const SORT_ORDER_STEP = 10;

    const state = {
        articles: [],
        editingId: null,
        pending: false,
        focusKey: null
    };
    const nodes = {};

    function el(tag, className, text) {
        return ui.element(tag, className, text);
    }

    function categoryLabel(value) {
        const match = api.CATEGORIES.find(function (item) { return item.value === value; });
        return match ? match.label : "Uncategorised";
    }

    function count(value) {
        return Number.isSafeInteger(value) && value >= 0 ? value : 0;
    }

    function needsReview(article) {
        const unhelpful = count(article.unhelpful_count);
        return unhelpful >= NEEDS_REVIEW_MIN_UNHELPFUL && unhelpful > count(article.helpful_count);
    }

    function orderedArticles() {
        return state.articles.slice().sort(function (left, right) {
            if (left.sort_order !== right.sort_order) return left.sort_order - right.sort_order;
            return left.id - right.id;
        });
    }

    function messageFor(error) {
        const messages = {
            help_article_not_found: "That article no longer exists. The list has been refreshed.",
            help_article_slug_exists: "Another article already uses that URL slug. Choose a different one.",
            invalid_category: "Choose a category from the list.",
            invalid_title: "Title is required and must be " + api.TITLE_MAX_LENGTH + " characters or fewer.",
            invalid_body: "Body is required and must be " + api.BODY_MAX_LENGTH + " characters or fewer.",
            invalid_slug: "Slug must be lowercase letters, numbers and single hyphens, for example connect-a-number.",
            invalid_sort_order: "That position is out of range.",
            invalid_is_published: "Choose a valid published state.",
            invalid_article_id: "That article reference is not valid.",
            invalid_request: "Nothing was changed.",
            no_change: "Nothing was changed."
        };
        return messages[error && error.code] || "Help article authoring is temporarily unavailable. Retry in a moment.";
    }

    function isAuthorizationFailure(error) {
        const category = error && error.category;
        return category === "unauthenticated" || category === "access_denied";
    }

    function setFormStatus(message, isError) {
        if (!nodes.formStatus) return;
        nodes.formStatus.textContent = message;
        nodes.formStatus.classList.toggle("platform-error", isError === true);
    }

    function setListStatus(message, isError) {
        if (!nodes.listStatus) return;
        nodes.listStatus.textContent = message;
        nodes.listStatus.classList.toggle("platform-error", isError === true);
    }

    function focusByKey(key) {
        if (!key) return;
        // The table and the mobile card list both render a control per action, so
        // pick the one that is actually visible at this viewport width.
        const candidates = nodes.results
            ? nodes.results.querySelectorAll('[data-focus-key="' + key + '"]')
            : [];
        for (const candidate of candidates) {
            if (!candidate.disabled && candidate.offsetParent !== null) {
                candidate.focus();
                return;
            }
        }
        if (nodes.listStatus) nodes.listStatus.focus();
    }

    function pageHeader() {
        const header = el("header", "platform-page-header");
        const copy = el("div");
        copy.append(
            el("p", "platform-eyebrow", "Help centre content"),
            el("h1", "", "Help Articles"),
            el("p", "platform-muted", "Author the self-service help centre every tenant reads. Published articles are visible to every tenant on every plan; drafts are visible only here. Article bodies are shown as plain prose, so write them without markup.")
        );
        header.append(copy);
        return header;
    }

    function summaryCard(label, id) {
        const card = el("section", "platform-card");
        const value = el("strong", "platform-card-value", "0");
        value.id = id;
        card.append(el("span", "platform-card-label", label), value);
        return card;
    }

    function summaryGrid() {
        const grid = el("div", "platform-summary-grid");
        nodes.publishedCount = summaryCard("Published", "platform-help-published-count");
        nodes.draftCount = summaryCard("Drafts", "platform-help-draft-count");
        nodes.reviewCount = summaryCard("Needs review", "platform-help-review-count");
        grid.append(nodes.publishedCount, nodes.draftCount, nodes.reviewCount);
        return grid;
    }

    function labelledField(labelText, id, control, hintText) {
        const field = el("div", "platform-field");
        const label = el("label", "", labelText);
        label.htmlFor = id;
        control.id = id;
        field.append(label, control);
        if (hintText) {
            const hint = el("p", "platform-note", hintText);
            hint.id = id + "-hint";
            control.setAttribute("aria-describedby", hint.id);
            field.append(hint);
        }
        return field;
    }

    function attachCounter(input, maxLength, unitLabel) {
        const counter = el("span", "platform-help-counter");
        counter.setAttribute("aria-hidden", "true");
        const notice = el("p", "platform-help-limit");
        notice.setAttribute("role", "status");
        function update() {
            const used = input.value.length;
            counter.textContent = used + " / " + maxLength;
            counter.classList.toggle("platform-help-counter-full", used >= maxLength);
            notice.textContent = used >= maxLength
                ? unitLabel + " has reached its " + maxLength + " character limit. Further text will not be added."
                : "";
        }
        input.addEventListener("input", update);
        update();
        return { counter: counter, notice: notice, update: update };
    }

    function categorySelect() {
        const select = el("select", "platform-input");
        api.CATEGORIES.forEach(function (item) {
            const option = el("option", "", item.label);
            option.value = item.value;
            select.append(option);
        });
        return select;
    }

    function buildEditorFields(form) {
        nodes.category = categorySelect();
        form.append(labelledField("Category", "platform-help-category", nodes.category, "Matches the categories tenants browse by on the support page."));

        nodes.title = el("input", "platform-input");
        nodes.title.type = "text";
        nodes.title.required = true;
        nodes.title.maxLength = api.TITLE_MAX_LENGTH;
        nodes.title.autocomplete = "off";
        const titleField = labelledField("Title", "platform-help-title", nodes.title, "Up to " + api.TITLE_MAX_LENGTH + " characters.");
        const titleCounter = attachCounter(nodes.title, api.TITLE_MAX_LENGTH, "Title");
        nodes.titleCounter = titleCounter;
        titleField.append(titleCounter.counter, titleCounter.notice);
        form.append(titleField);

        nodes.slug = el("input", "platform-input");
        nodes.slug.type = "text";
        nodes.slug.maxLength = api.SLUG_MAX_LENGTH;
        nodes.slug.autocomplete = "off";
        form.append(labelledField("URL slug (optional)", "platform-help-slug", nodes.slug, "Lowercase letters, numbers and single hyphens. Leave blank to let the server derive one from the title."));

        nodes.body = el("textarea", "platform-input platform-help-body");
        nodes.body.required = true;
        nodes.body.maxLength = api.BODY_MAX_LENGTH;
        nodes.body.rows = 10;
        const bodyField = labelledField("Body", "platform-help-body-input", nodes.body, "Up to " + api.BODY_MAX_LENGTH + " characters of plain prose. Headings, links and code blocks are not rendered.");
        const bodyCounter = attachCounter(nodes.body, api.BODY_MAX_LENGTH, "Body");
        nodes.bodyCounter = bodyCounter;
        bodyField.append(bodyCounter.counter, bodyCounter.notice);
        form.append(bodyField);
    }

    function buildPublishToggle() {
        const wrap = el("div", "platform-help-checkbox");
        nodes.publish = el("input");
        nodes.publish.type = "checkbox";
        nodes.publish.id = "platform-help-publish";
        const label = el("label", "", "Publish this article");
        label.htmlFor = "platform-help-publish";
        const hint = el("p", "platform-note", "Leave unticked to save it as a draft that no tenant can see.");
        hint.id = "platform-help-publish-hint";
        nodes.publish.setAttribute("aria-describedby", hint.id);
        wrap.append(nodes.publish, label, hint);
        return wrap;
    }

    function editorPanel() {
        const section = el("section", "platform-panel");
        nodes.editorHeading = el("h2", "", "Create an article");
        section.append(nodes.editorHeading);

        const form = el("form", "platform-help-form");
        form.noValidate = true;
        buildEditorFields(form);
        form.append(buildPublishToggle());

        nodes.formError = el("p", "platform-inline-error");
        nodes.formError.id = "platform-help-form-error";
        nodes.formError.setAttribute("role", "alert");

        const actions = el("div", "platform-help-actions platform-help-form-actions");
        nodes.submit = el("button", "platform-button platform-button-primary", "Create article");
        nodes.submit.type = "submit";
        nodes.cancel = el("button", "platform-button", "Cancel edit");
        nodes.cancel.type = "button";
        nodes.cancel.hidden = true;
        nodes.cancel.addEventListener("click", function () { stopEditing(true); });
        actions.append(nodes.submit, nodes.cancel);

        nodes.formStatus = el("p", "platform-form-status");
        nodes.formStatus.setAttribute("aria-live", "polite");

        form.append(nodes.formError, actions);
        form.addEventListener("submit", submitEditor);
        section.append(form, nodes.formStatus);
        nodes.form = form;
        return section;
    }

    function listPanel() {
        const section = el("section", "platform-panel");
        section.append(
            el("h2", "", "All articles"),
            el("p", "platform-muted", "Ordered exactly as tenants see them. “Needs review” marks an article with at least " + NEEDS_REVIEW_MIN_UNHELPFUL + " “didn’t help” votes and more of them than “helped” votes.")
        );
        nodes.listStatus = el("p", "platform-form-status");
        nodes.listStatus.setAttribute("aria-live", "polite");
        nodes.listStatus.tabIndex = -1;
        nodes.results = el("div", "platform-support-results");
        section.append(nodes.listStatus, nodes.results);
        return section;
    }

    function buildPage() {
        const root = document.getElementById("platform-page-content");
        if (!root) return;
        root.replaceChildren(pageHeader(), summaryGrid(), editorPanel(), listPanel());
    }

    function stateBadge(article) {
        const published = article.is_published === true;
        const badge = el(
            "span",
            "platform-status " + (published ? "platform-help-published" : "platform-help-draft"),
            published ? "Published" : "Draft"
        );
        return badge;
    }

    function actionButton(label, accessibleName, focusKey, handler, className) {
        const button = el("button", "platform-button" + (className ? " " + className : ""), label);
        button.type = "button";
        button.setAttribute("aria-label", accessibleName);
        button.dataset.focusKey = focusKey;
        button.addEventListener("click", handler);
        return button;
    }

    function rowActions(article, index, total) {
        const wrap = el("div", "platform-help-actions");
        const title = article.title || "Untitled article";
        const published = article.is_published === true;

        wrap.append(actionButton(
            "Edit", "Edit article: " + title, "edit-" + article.id,
            function () { startEditing(article.id); }
        ));
        wrap.append(actionButton(
            published ? "Unpublish" : "Publish",
            (published ? "Unpublish" : "Publish") + " article: " + title,
            "publish-" + article.id,
            function () { togglePublished(article); }
        ));

        const up = actionButton("Move up", "Move up: " + title, "up-" + article.id, function () { moveArticle(article, -1); });
        up.disabled = index === 0;
        if (up.disabled) up.title = "Already first.";
        const down = actionButton("Move down", "Move down: " + title, "down-" + article.id, function () { moveArticle(article, 1); });
        down.disabled = index === total - 1;
        if (down.disabled) down.title = "Already last.";
        wrap.append(up, down);

        wrap.append(actionButton(
            "Delete", "Delete article: " + title, "delete-" + article.id,
            function () { deleteArticle(article); }, "platform-help-danger"
        ));
        return wrap;
    }

    function reviewFlag(article) {
        const cell = el("div", "platform-help-votes");
        cell.append(
            el("span", "platform-help-count", count(article.helpful_count) + " helped"),
            el("span", "platform-help-count", count(article.unhelpful_count) + " didn’t help")
        );
        if (needsReview(article)) cell.append(el("span", "platform-help-flag", "Needs review"));
        return cell;
    }

    function articleTable(ordered) {
        const wrap = el("div", "platform-table-wrap");
        const table = el("table", "platform-table");
        const head = el("thead");
        const headRow = el("tr");
        ["Title", "Category", "State", "Feedback", "Updated", "Actions"].forEach(function (label) {
            const cell = el("th", "", label);
            cell.scope = "col";
            headRow.append(cell);
        });
        head.append(headRow);
        const body = el("tbody");
        ordered.forEach(function (article, index) {
            const row = el("tr");
            const titleCell = el("td", "platform-help-title-cell");
            titleCell.append(
                el("strong", "", article.title || "Untitled article"),
                el("span", "platform-help-slug", article.slug || "no slug")
            );
            const stateCell = el("td");
            stateCell.append(stateBadge(article));
            const feedbackCell = el("td");
            feedbackCell.append(reviewFlag(article));
            const actionCell = el("td");
            actionCell.append(rowActions(article, index, ordered.length));
            row.append(
                titleCell,
                el("td", "", categoryLabel(article.category)),
                stateCell,
                feedbackCell,
                el("td", "", ui.formatDate(article.updated_at)),
                actionCell
            );
            body.append(row);
        });
        table.append(head, body);
        wrap.append(table);
        return wrap;
    }

    function articleCards(ordered) {
        const list = el("div", "platform-help-cards");
        list.setAttribute("aria-label", "Help article cards");
        ordered.forEach(function (article, index) {
            const card = el("article", "platform-mobile-data-card");
            const header = el("div", "platform-mobile-card-header");
            header.append(el("h3", "", article.title || "Untitled article"), stateBadge(article));
            const details = el("dl");
            [
                ["Category", categoryLabel(article.category)],
                ["Slug", article.slug || "no slug"],
                ["Updated", ui.formatDate(article.updated_at)]
            ].forEach(function (pair) {
                const row = el("div", "platform-mobile-data-row");
                row.append(el("dt", "", pair[0]), el("dd", "", pair[1]));
                details.append(row);
            });
            card.append(header, details, reviewFlag(article), rowActions(article, index, ordered.length));
            list.append(card);
        });
        return list;
    }

    function renderSummary() {
        const published = state.articles.filter(function (item) { return item.is_published === true; }).length;
        const review = state.articles.filter(needsReview).length;
        nodes.publishedCount.querySelector("strong").textContent = String(published);
        nodes.draftCount.querySelector("strong").textContent = String(state.articles.length - published);
        nodes.reviewCount.querySelector("strong").textContent = String(review);
    }

    function renderList(statusMessage) {
        renderSummary();
        const ordered = orderedArticles();
        if (ordered.length === 0) {
            nodes.results.replaceChildren(el(
                "p",
                "platform-empty",
                "No help articles yet. The first article you create appears here, and tenants see it as soon as it is published."
            ));
        } else {
            nodes.results.replaceChildren(articleTable(ordered), articleCards(ordered));
        }
        const published = ordered.filter(function (item) { return item.is_published === true; }).length;
        setListStatus(statusMessage || (
            ordered.length + (ordered.length === 1 ? " article" : " articles") + ", " +
            published + " published and " + (ordered.length - published) + " draft."
        ));
        focusByKey(state.focusKey);
        state.focusKey = null;
    }

    function fillForm(article) {
        nodes.category.value = article.category;
        nodes.title.value = article.title || "";
        nodes.slug.value = article.slug || "";
        nodes.body.value = article.body || "";
        nodes.publish.checked = article.is_published === true;
        nodes.titleCounter.update();
        nodes.bodyCounter.update();
    }

    function startEditing(articleId) {
        const article = state.articles.find(function (item) { return item.id === articleId; });
        if (!article) return;
        state.editingId = articleId;
        fillForm(article);
        nodes.editorHeading.textContent = "Edit “" + (article.title || "Untitled article") + "”";
        nodes.submit.textContent = "Save changes";
        nodes.cancel.hidden = false;
        nodes.formError.textContent = "";
        setFormStatus("Editing an existing article. Saving overwrites it for every tenant.");
        nodes.title.focus();
    }

    function stopEditing(announce) {
        state.editingId = null;
        nodes.form.reset();
        nodes.titleCounter.update();
        nodes.bodyCounter.update();
        nodes.editorHeading.textContent = "Create an article";
        nodes.submit.textContent = "Create article";
        nodes.cancel.hidden = true;
        nodes.formError.textContent = "";
        if (announce) {
            setFormStatus("Edit cancelled. The form is back to creating a new article.");
            nodes.title.focus();
        }
    }

    function readEditor() {
        return {
            category: nodes.category.value,
            title: nodes.title.value.trim(),
            slug: nodes.slug.value.trim(),
            body: nodes.body.value.trim()
        };
    }

    function validateEditor(fields) {
        if (!fields.title) return { field: nodes.title, message: "Enter a title." };
        if (fields.title.length > api.TITLE_MAX_LENGTH) {
            return { field: nodes.title, message: "Title must be " + api.TITLE_MAX_LENGTH + " characters or fewer." };
        }
        if (!fields.body) return { field: nodes.body, message: "Enter the article body." };
        if (fields.body.length > api.BODY_MAX_LENGTH) {
            return { field: nodes.body, message: "Body must be " + api.BODY_MAX_LENGTH + " characters or fewer." };
        }
        if (fields.slug && !api.SLUG_PATTERN.test(fields.slug)) {
            return { field: nodes.slug, message: "Slug must be lowercase letters, numbers and single hyphens, for example connect-a-number." };
        }
        return null;
    }

    function showFieldError(problem) {
        nodes.formError.textContent = problem.message;
        problem.field.setAttribute("aria-invalid", "true");
        problem.field.setAttribute("aria-describedby", problem.field.id + "-hint " + nodes.formError.id);
        problem.field.focus();
    }

    function clearFieldErrors() {
        [nodes.title, nodes.body, nodes.slug].forEach(function (field) {
            field.removeAttribute("aria-invalid");
            field.setAttribute("aria-describedby", field.id + "-hint");
        });
        nodes.formError.textContent = "";
    }

    function nextSortOrder() {
        const highest = state.articles.reduce(function (best, item) {
            return Number.isSafeInteger(item.sort_order) && item.sort_order > best ? item.sort_order : best;
        }, 0);
        return highest + SORT_ORDER_STEP;
    }

    // Saving the form can flip what every tenant sees, in either direction, so
    // both directions ask before they happen.
    function confirmVisibilityChange(editingId, title, willPublish) {
        const existing = editingId === null
            ? null
            : state.articles.find(function (item) { return item.id === editingId; });
        const wasPublished = existing ? existing.is_published === true : false;
        if (willPublish === wasPublished) return true;
        return window.confirm(willPublish
            ? "Publish “" + title + "”? It becomes visible in the help centre for every tenant immediately."
            : "Unpublish “" + title + "”? It disappears from the help centre for every tenant immediately. Its feedback counts are kept.");
    }

    async function submitEditor(event) {
        event.preventDefault();
        if (state.pending) return;
        clearFieldErrors();
        const fields = readEditor();
        const problem = validateEditor(fields);
        if (problem) {
            showFieldError(problem);
            return;
        }
        const editingId = state.editingId;
        const payload = {
            category: fields.category,
            title: fields.title,
            body: fields.body,
            is_published: nodes.publish.checked === true
        };
        if (fields.slug) payload.slug = fields.slug;
        if (editingId === null) payload.sort_order = nextSortOrder();
        if (!confirmVisibilityChange(editingId, fields.title, payload.is_published)) return;

        await runMutation(
            nodes.submit,
            editingId === null ? "help-article-create" : "help-article-update-" + editingId,
            function (signal) {
                return editingId === null
                    ? api.createArticle(payload, { signal: signal })
                    : api.updateArticle(editingId, payload, { signal: signal });
            },
            editingId === null ? "Saving new article..." : "Saving changes...",
            editingId === null ? "Article created." : "Article saved.",
            function () { stopEditing(false); }
        );
    }

    async function runMutation(button, key, factory, pendingText, successText, onSuccess) {
        state.pending = true;
        if (button) button.disabled = true;
        setFormStatus(pendingText);
        try {
            await ui.runRequest(key, factory);
            if (typeof onSuccess === "function") onSuccess();
            setFormStatus(successText);
            await load({ recoverableOnFailure: true, statusMessage: successText });
        } catch (error) {
            if (!ui.handleError(error)) setFormStatus(messageFor(error), true);
        } finally {
            state.pending = false;
            if (button && button.isConnected) button.disabled = false;
        }
    }

    function togglePublished(article) {
        if (state.pending) return;
        const title = article.title || "Untitled article";
        const publishing = article.is_published !== true;
        const question = publishing
            ? "Publish “" + title + "”? It becomes visible in the help centre for every tenant immediately."
            : "Unpublish “" + title + "”? It disappears from the help centre for every tenant immediately. Its feedback counts are kept.";
        if (!window.confirm(question)) return;
        state.focusKey = "publish-" + article.id;
        runMutation(
            null,
            "help-article-publish-" + article.id,
            function (signal) { return api.updateArticle(article.id, { is_published: publishing }, { signal: signal }); },
            publishing ? "Publishing article..." : "Unpublishing article...",
            publishing ? "Article published. Every tenant can see it now." : "Article unpublished. It is a draft again."
        );
    }

    // ponytail: a swap is two sequential PATCH calls, so a failure between them
    // leaves the two rows sharing a sort_order and falling back to id order.
    // Nothing is corrupted and a retry fixes it; making it atomic needs a batch
    // reorder endpoint that the slice-5 API contract does not have.
    function reorderWrites(article, target, direction) {
        const from = article.sort_order;
        const to = target.sort_order;
        if (from !== to) {
            return [
                { id: article.id, sort_order: to },
                { id: target.id, sort_order: from }
            ];
        }
        if (direction > 0) return [{ id: article.id, sort_order: to + 1 }];
        if (to > 0) return [{ id: article.id, sort_order: to - 1 }];
        return [{ id: target.id, sort_order: from + 1 }];
    }

    async function moveArticle(article, direction) {
        if (state.pending) return;
        const ordered = orderedArticles();
        const index = ordered.findIndex(function (item) { return item.id === article.id; });
        const target = ordered[index + direction];
        if (!target) return;
        const writes = reorderWrites(article, target, direction);
        state.focusKey = (direction < 0 ? "up-" : "down-") + article.id;
        state.pending = true;
        setListStatus("Reordering articles...");
        try {
            for (const write of writes) {
                await ui.runRequest(
                    "help-article-order-" + write.id,
                    function (signal) { return api.updateArticle(write.id, { sort_order: write.sort_order }, { signal: signal }); }
                );
            }
            state.pending = false;
            await load({
                recoverableOnFailure: true,
                statusMessage: "Moved “" + (article.title || "Untitled article") + "” " + (direction < 0 ? "up" : "down") + "."
            });
        } catch (error) {
            state.pending = false;
            if (ui.handleError(error)) return;
            await load({
                recoverableOnFailure: true,
                statusMessage: "The new order was only partly applied. This is the current order - try the move again."
            });
        }
    }

    function deleteArticle(article) {
        if (state.pending) return;
        const title = article.title || "Untitled article";
        if (!window.confirm(
            "Delete “" + title + "”? The article and its helpful / didn’t-help counts are removed for every tenant immediately. This cannot be undone."
        )) return;
        if (state.editingId === article.id) stopEditing(false);
        // The clicked button is about to be removed, so send focus to the list
        // status line, which is where the outcome is announced.
        state.focusKey = "deleted-row";
        runMutation(
            null,
            "help-article-delete-" + article.id,
            function (signal) { return api.removeArticle(article.id, { signal: signal }); },
            "Deleting article...",
            "Article deleted."
        );
    }

    function renderRecoverableError() {
        nodes.results.replaceChildren();
        setListStatus("The article list could not be refreshed. Retry to load the current state.", true);
        const retry = el("button", "platform-button platform-button-primary", "Retry");
        retry.type = "button";
        retry.addEventListener("click", async function () {
            retry.disabled = true;
            try {
                await load({ recoverableOnFailure: true });
            } catch (error) {
                if (!ui.handleError(error)) renderRecoverableError();
            }
        });
        nodes.results.append(retry);
        retry.focus();
    }

    async function load(options) {
        const config = options || {};
        nodes.results.setAttribute("aria-busy", "true");
        let articles;
        try {
            articles = await ui.runRequest("help-articles", function (signal) {
                return api.listArticles({ signal: signal });
            });
        } catch (error) {
            nodes.results.setAttribute("aria-busy", "false");
            if (config.recoverableOnFailure && !isAuthorizationFailure(error)) {
                renderRecoverableError();
                return false;
            }
            throw error;
        }
        state.articles = articles.filter(function (item) {
            return item && Number.isSafeInteger(item.id);
        });
        nodes.results.setAttribute("aria-busy", "false");
        renderList(config.statusMessage);
        return true;
    }

    async function initialize() {
        buildPage();
        setListStatus("Loading help articles...");
        try {
            await load();
        } catch (error) {
            if (!ui.handleError(error)) renderRecoverableError();
        }
    }

    PlatformAdminShell.start({ onAuthorized: initialize });
}());
