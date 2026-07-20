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
        actions.append(back);
        card.append(heading, ui.element("p", "", message), actions);
        root.replaceChildren(card);
        heading.focus();
    }

    async function initializeCompanyDetail() {
        const root = document.getElementById("platform-page-content");
        const companyId = parseCompanyId();
        if (companyId === null) {
            showLocalState("Invalid company", "Select a company from the platform directory.");
            return;
        }

        root.replaceChildren(ui.element("div", "platform-loading", "Loading company…"));
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

        root.replaceChildren(pageHeader(company), companyPanel(company), ui.element("div", "platform-loading", "Loading billing summaries…"));
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
                subscriptionPanel(summaries[0] ? summaries[0].subscription : null),
                aiCreditPanel(summaries[1])
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
