
        /* ══════════════════════════════════════════════════════════════
           Support page behaviour.

           Inline on purpose, not extracted to assets/js/support.js: two
           source-contract assertions read the support fetch calls out of
           this file, so moving them breaks the suite.

           Every node below is built with createElement + textContent.
           Nothing on this page ever assigns markup from a string.
           ══════════════════════════════════════════════════════════════ */
        (function () {
            "use strict";

            var ARTICLES_ENDPOINT = "/api/help/articles";
            var SEARCH_DEBOUNCE_MS = 160;
            var DESCRIPTION_LIMIT = 2000;

            var CATEGORY_LABELS = {
                technical: "Technical",
                account: "Account",
                chatbot: "Chatbot",
                integration: "Integration",
                billing_question: "Billing",
                ai_credits: "AI credits",
                other: "Other"
            };
            var ALLOWED_CATEGORIES = Object.keys(CATEGORY_LABELS);

            function byId(id) { return document.getElementById(id); }

            function each(selector, fn) {
                Array.prototype.forEach.call(document.querySelectorAll(selector), fn);
            }

            function element(tag, className, text) {
                var node = document.createElement(tag);
                if (className) node.className = className;
                if (text !== undefined && text !== null) node.textContent = String(text);
                return node;
            }

            var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

            function bringIntoView(node) {
                node.scrollIntoView({
                    behavior: reduceMotion.matches ? "auto" : "smooth",
                    block: "start"
                });
            }

            /* Signed-in identity is display-only; the server resolves ownership. */
            function parseStoredUser() {
                try {
                    var parsed = JSON.parse(sessionStorage.getItem("user") || "null");
                    return parsed && typeof parsed === "object" ? parsed : null;
                } catch (_) {
                    return null;
                }
            }

            var storedUser = parseStoredUser();
            var fullName = storedUser && typeof storedUser.full_name === "string" ? storedUser.full_name.trim() : "";
            var storedEmail = storedUser && typeof storedUser.email === "string" ? storedUser.email.trim() : "";
            var displayName = fullName || "Signed in";
            var email = storedEmail || "Account details unavailable";

            byId("sup-trail-account").textContent = displayName;
            byId("sup-trail-email").textContent = email;

            /* ── Region handles ─────────────────────────────────────── */
            var query = byId("sup-query");
            var resultCount = byId("sup-result-count");
            var skeleton = byId("sup-skeleton");
            var articlesError = byId("sup-articles-error");
            var articleList = byId("sup-article-list");
            var reader = byId("sup-reader");
            var readerTitle = byId("sup-reader-title");
            var readerBody = byId("sup-reader-body");
            var voteRow = byId("sup-vote");
            var deadEnd = byId("sup-deadend");
            var deadEndTitle = byId("sup-deadend-title");
            var deadEndWhy = byId("sup-deadend-why");
            var escalation = byId("sup-escalation");
            var escalationTitle = byId("sup-escalation-title");
            var escalationStatus = byId("sup-escalation-status");
            var escalationForm = byId("support-request-form");
            var escCategory = byId("sup-category");
            var escSubject = byId("sup-subject");
            var escDescription = byId("sup-description");
            var submitButton = byId("sup-submit");
            var historyWrap = byId("sup-history");
            var historyEmpty = byId("sup-history-empty");
            var historyCount = byId("sup-history-count");
            var historyList = byId("support-history-list");
            var historyDetail = byId("support-history-detail");

            var articles = [];
            var articlesReady = false;
            var activeCategory = "all";
            var currentArticle = null;
            /* ── Article loading ────────────────────────────────────────
               The response is not trusted: a row missing a title or a body
               is dropped rather than rendered as an empty clickable row. */
            function usableArticle(raw) {
                return raw
                    && typeof raw === "object"
                    && typeof raw.title === "string" && raw.title.trim()
                    && typeof raw.body === "string" && raw.body.trim();
            }

            function normalizeArticle(raw, index) {
                var category = typeof raw.category === "string" ? raw.category.trim() : "";
                var order = Number.isFinite(raw.sort_order) ? raw.sort_order : index;
                return {
                    key: typeof raw.slug === "string" && raw.slug ? raw.slug : "article-" + index,
                    /* The feedback endpoint is keyed by the numeric id, so it has
                       to survive normalisation. Null when the row omits it, which
                       disables the vote for that article rather than posting to
                       /feedback with an undefined path segment. */
                    id: Number.isSafeInteger(raw.id) && raw.id > 0 ? raw.id : null,
                    category: category,
                    label: CATEGORY_LABELS[category] || "General",
                    title: raw.title.trim(),
                    paragraphs: raw.body.trim().split(/\n\s*\n/).filter(Boolean),
                    haystack: (raw.title + " " + raw.body).toLowerCase(),
                    order: order
                };
            }

            function setArticleRegion(state) {
                skeleton.hidden = state !== "loading";
                articlesError.hidden = state !== "error";
                if (state !== "ready") {
                    articleList.hidden = true;
                    reader.hidden = true;
                }
                if (state === "loading") resultCount.textContent = "Loading";
                if (state === "error") resultCount.textContent = "Unavailable";
            }

            async function loadArticles() {
                articlesReady = false;
                setArticleRegion("loading");
                deadEnd.hidden = true;
                try {
                    var response = await authenticatedFetch(ARTICLES_ENDPOINT, {
                        method: "GET",
                        headers: { "Accept": "application/json" }
                    });
                    var result = await response.json().catch(function () { return null; });
                    if (!response.ok || !result || result.status !== "success") {
                        setArticleRegion("error");
                        return;
                    }
                    var rows = result.data && Array.isArray(result.data.articles) ? result.data.articles : [];
                    articles = rows.filter(usableArticle).map(normalizeArticle).sort(function (a, b) {
                        return a.order - b.order;
                    });
                    articlesReady = true;
                    setArticleRegion("ready");
                    renderArticleList();
                } catch (_) {
                    setArticleRegion("error");
                }
            }

            /* ── List and filtering ─────────────────────────────────── */
            function matchingArticles() {
                var term = query.value.trim().toLowerCase();
                return articles.filter(function (article) {
                    if (activeCategory !== "all" && article.category !== activeCategory) return false;
                    return !term || article.haystack.indexOf(term) !== -1;
                });
            }

            function renderArticleList() {
                if (!articlesReady) return;
                var matches = matchingArticles();
                articleList.replaceChildren();
                matches.forEach(function (article) {
                    var row = element("button", "art");
                    row.type = "button";
                    row.append(
                        element("span", "art-t", article.title),
                        element("span", "art-c", article.label)
                    );
                    row.addEventListener("click", function () { openArticle(article); });
                    articleList.append(row);
                });

                resultCount.textContent = matches.length + (matches.length === 1 ? " article" : " articles");
                reader.hidden = true;
                articleList.hidden = matches.length === 0;

                if (matches.length === 0) {
                    var term = query.value.trim();
                    deadEndWhy.textContent = term
                        ? "Nothing matched “" + term + "”. A member of the support team can pick this up."
                        : "There is nothing to show in this category yet. A member of the support team can pick this up.";
                    deadEnd.hidden = false;
                } else {
                    deadEnd.hidden = true;
                }
            }

            /* ── Reader and the helpfulness vote ────────────────────── */
            /* Recording the vote is a side effect, never a gate. A user who
               says "this did not help" must reach a human whether or not the
               vote reaches the server, so every failure path here is silent
               and the handoff below runs regardless. */
            function recordVote(article, helpful) {
                if (!article || !article.id) return;
                try {
                    var pending = authenticatedFetch(
                        "/api/help/articles/" + String(article.id) + "/feedback",
                        {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ was_helpful: helpful })
                        }
                    );
                    if (pending && typeof pending.catch === "function") {
                        pending.catch(function () { });
                    }
                } catch (_) { /* the handoff matters, the tally does not */ }
            }

            function voteButton(label, helpful) {
                var button = element("button", "kw-btn cr-press", label);
                button.type = "button";
                button.addEventListener("click", function () {
                    recordVote(currentArticle, helpful);
                    if (helpful) {
                        voteRow.replaceChildren(element("span", "vote-done", "Thanks — marked as helpful."));
                        return;
                    }
                    voteRow.replaceChildren(element("span", "vote-q", "Understood — handing this to a person below."));
                    deadEndWhy.textContent = "“" + (currentArticle ? currentArticle.title : "That article") +
                        "” did not solve it. A member of the support team can pick this up.";
                    deadEnd.hidden = false;
                    bringIntoView(deadEnd);
                    deadEndTitle.focus();
                });
                return button;
            }

            function openArticle(article) {
                currentArticle = article;

                readerTitle.textContent = article.title;
                readerBody.replaceChildren();
                article.paragraphs.forEach(function (paragraph) {
                    readerBody.append(element("p", "", paragraph));
                });
                voteRow.replaceChildren(
                    element("span", "vote-q", "Did this answer your question?"),
                    voteButton("Yes, it helped", true),
                    voteButton("No, still stuck", false)
                );

                articleList.hidden = true;
                deadEnd.hidden = true;
                reader.hidden = false;
                readerTitle.focus();
            }

            byId("sup-reader-back").addEventListener("click", function () {
                reader.hidden = true;
                renderArticleList();
                query.focus();
            });

            byId("sup-retry-articles").addEventListener("click", loadArticles);

            /* ── Escalation ─────────────────────────────────────────── */
            function showEscalationStatus(message, state) {
                escalationStatus.textContent = message;
                escalationStatus.className = "esc-status" + (state ? " " + state : "");
            }

            function openEscalation() {
                deadEnd.hidden = true;
                escalation.hidden = false;
                showEscalationStatus("", "");
                if (!escSubject.value.trim() && currentArticle) {
                    escSubject.value = currentArticle.title;
                }
                bringIntoView(escalation);
                escalationTitle.focus();
            }

            byId("sup-open-escalation").addEventListener("click", openEscalation);
            byId("sup-deadend-escalate").addEventListener("click", openEscalation);
            byId("sup-error-escalate").addEventListener("click", openEscalation);

            byId("sup-keep-looking").addEventListener("click", function () {
                deadEnd.hidden = true;
                query.focus();
            });

            byId("sup-cancel").addEventListener("click", function () {
                escalation.hidden = true;
                query.focus();
            });

            /* ── Search and category chips ──────────────────────────── */
            var searchTimer = null;
            query.addEventListener("input", function () {
                window.clearTimeout(searchTimer);
                searchTimer = window.setTimeout(function () {
                    renderArticleList();
                }, SEARCH_DEBOUNCE_MS);
            });

            each("#sup-chips .chip", function (chip) {
                chip.addEventListener("click", function () {
                    activeCategory = chip.getAttribute("data-cat");
                    each("#sup-chips .chip", function (other) {
                        other.setAttribute("aria-pressed", String(other === chip));
                    });
                    renderArticleList();
                });
            });

            /* ── Support history ────────────────────────────────────── */
            var historySequence = 0;

            function formatDate(value) {
                if (!value) return "Not available";
                var date = new Date(value);
                if (Number.isNaN(date.getTime())) return String(value);
                return date.toLocaleString();
            }

            function statusPill(status) {
                var known = ["new", "reviewed", "closed"];
                var safe = known.indexOf(status) === -1 ? "closed" : status;
                return element("span", "pill pill-" + safe, String(status || "unknown"));
            }

            function renderHistoryList(requests) {
                historyList.replaceChildren();
                historyEmpty.hidden = requests.length > 0;
                historyWrap.hidden = requests.length === 0;
                historyCount.textContent = requests.length
                    ? requests.filter(function (item) { return item.status !== "closed"; }).length + " open"
                    : "None yet";

                requests.forEach(function (item) {
                    var button = element("button", "tick");
                    button.type = "button";
                    button.setAttribute("aria-pressed", "false");
                    button.append(
                        element("span", "tick-ref", "#" + item.request_id),
                        element("div", "tick-t", item.title || "Support request"),
                        statusPill(item.status)
                    );
                    button.addEventListener("click", function () {
                        Array.prototype.forEach.call(historyList.children, function (sibling) {
                            sibling.setAttribute("aria-pressed", "false");
                        });
                        button.setAttribute("aria-pressed", "true");
                        loadSupportRequestDetail(item.request_id);
                    });
                    historyList.append(button);
                });
            }

            function renderHistoryDetail(data) {
                var requestData = data && data.request ? data.request : null;
                var replies = data && Array.isArray(data.replies) ? data.replies : [];

                historyDetail.replaceChildren();
                if (!requestData) {
                    historyDetail.append(element("p", "", "Select a request to view its conversation."));
                    return;
                }

                historyDetail.append(element("h4", "", requestData.title || "Support request"));

                var definitions = element("dl", "dl");
                [
                    ["Reference", "#" + requestData.request_id],
                    ["Status", requestData.status],
                    ["Category", CATEGORY_LABELS[requestData.category] || requestData.category],
                    ["Sent", formatDate(requestData.created_at)],
                    ["Updated", formatDate(requestData.updated_at)]
                ].forEach(function (pair) {
                    definitions.append(
                        element("dt", "", pair[0]),
                        element("dd", "", pair[1] || "Not available")
                    );
                });
                historyDetail.append(definitions);

                historyDetail.append(
                    element("p", "reply-meta", "Your message"),
                    element("p", "", requestData.redacted_description || "Not available")
                );

                historyDetail.append(element("p", "reply-meta", "Tenant-visible replies"));
                if (!replies.length) {
                    historyDetail.append(element("p", "", "No replies yet."));
                    return;
                }
                replies.forEach(function (reply) {
                    var block = element("div", "reply");
                    block.append(
                        element("p", "reply-meta", "Platform support — " + formatDate(reply.created_at)),
                        element("p", "", reply.redacted_body)
                    );
                    historyDetail.append(block);
                });
            }

            async function loadSupportHistory() {
                var sequence = ++historySequence;
                historyCount.textContent = "Loading";
                // The empty state may be on screen from a previous pass; the
                // loading line lives inside the panel it hides.
                historyEmpty.hidden = true;
                historyWrap.hidden = false;
                historyList.textContent = "Loading support requests...";
                try {
                    var response = await authenticatedFetch("/api/support/requests?limit=25&offset=0", {
                        method: "GET",
                        headers: { "Accept": "application/json" }
                    });
                    var result = await response.json().catch(function () { return null; });
                    if (sequence !== historySequence) return;
                    if (!response.ok || !result || result.status !== "success") {
                        historyCount.textContent = "Unavailable";
                        historyList.textContent = "Support history could not be loaded.";
                        return;
                    }
                    renderHistoryList((result.data && result.data.requests) || []);
                } catch (_) {
                    if (sequence !== historySequence) return;
                    historyCount.textContent = "Unavailable";
                    historyList.textContent = "Support history could not be loaded.";
                }
            }

            async function loadSupportRequestDetail(requestId) {
                var sequence = ++historySequence;
                historyDetail.textContent = "Loading support conversation...";
                try {
                    var response = await authenticatedFetch("/api/support/requests/" + String(requestId), {
                        method: "GET",
                        headers: { "Accept": "application/json" }
                    });
                    var result = await response.json().catch(function () { return null; });
                    if (sequence !== historySequence) return;
                    if (!response.ok || !result || result.status !== "success") {
                        historyDetail.textContent = "Support conversation could not be loaded.";
                        return;
                    }
                    renderHistoryDetail(result.data);
                } catch (_) {
                    if (sequence === historySequence) {
                        historyDetail.textContent = "Support conversation could not be loaded.";
                    }
                }
            }

            /* ── Submission ─────────────────────────────────────────── */
            function validationProblem(payload) {
                if (ALLOWED_CATEGORIES.indexOf(payload.category) === -1) {
                    return "Select a valid support category.";
                }
                if (!payload.title || payload.title.length > 160) {
                    return "Subject must contain 1 to 160 characters.";
                }
                if (!escDescription.value.trim()) {
                    return "Describe what is happening before sending.";
                }
                if (payload.redacted_description.length > DESCRIPTION_LIMIT) {
                    return "The description is over " + DESCRIPTION_LIMIT + " characters. Shorten it and try again.";
                }
                return "";
            }

            function rejectionMessage(result) {
                var code = result && result.code;
                if (code === "invalid_category") return "Select a valid support category.";
                if (code === "invalid_title") return "Review the subject: it is empty, too long, or contains wording the intake rejects.";
                if (code === "invalid_redacted_description") {
                    return "Review the description: it is empty, too long, or contains wording the intake rejects, such as passwords or payment references.";
                }
                if (code === "unsupported_field") {
                    return "This page is out of date with the support intake. Reload the page and try again.";
                }
                if (code === "tenant_support_unavailable") return "Support intake is temporarily unavailable. Please try again shortly.";
                return "Support request could not be submitted.";
            }

            escalationForm.addEventListener("submit", async function (event) {
                event.preventDefault();

                var values = {
                    category: escCategory.value.trim(),
                    title: escSubject.value.trim(),
                    redacted_description: escDescription.value.trim()
                };

                var problem = validationProblem(values);
                if (problem) {
                    showEscalationStatus(problem, "is-bad");
                    return;
                }

                submitButton.disabled = true;
                submitButton.textContent = "Sending...";
                showEscalationStatus("Sending your request...", "");
                try {
                    var response = await authenticatedFetch("/api/support/requests", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(values)
                    });
                    var result = await response.json().catch(function () { return null; });
                    if (response.status === 429) {
                        showEscalationStatus("Too many requests for now. Please try again later.", "is-bad");
                        return;
                    }
                    if (!response.ok) {
                        showEscalationStatus(rejectionMessage(result), "is-bad");
                        return;
                    }
                    var newRequestId = result && result.data && result.data.request_id;
                    if (!Number.isSafeInteger(newRequestId) || newRequestId <= 0) {
                        showEscalationStatus("Support request could not be confirmed.", "is-bad");
                        return;
                    }
                    showEscalationStatus("Sent — reference #" + newRequestId + ". It is listed below.", "is-ok");
                    escalationForm.reset();
                    loadSupportHistory();
                } catch (_) {
                    showEscalationStatus("Support request could not be submitted.", "is-bad");
                } finally {
                    submitButton.disabled = false;
                    submitButton.textContent = "Send to support";
                }
            });

            loadArticles();
            loadSupportHistory();
        })();
    