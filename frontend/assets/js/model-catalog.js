/**
 * Model catalogue + plan gating.
 *
 * Lifted behaviour-for-behaviour out of frontend/model_settings.html so the
 * Behaviour Studio and any other caller share one copy. This is billing
 * enforcement surface: which models a tenant may select follows from their
 * subscription, and a second hand-typed copy would eventually disagree with the
 * first. The server enforces the same rule independently — this only decides
 * what is offered.
 *
 * Pure of the DOM on purpose. Callers own their own markup and read these
 * answers; nothing here touches an element id.
 *
 * window.modelCatalog:
 *   load()                        -> {options, readOnly, accessAllowed, denialReason, access}
 *   isModelAllowed(model, state)  -> boolean
 *   hasAnyAccess(state)           -> boolean
 *   allowedProviders(state)       -> [{key, label, models}]
 */
(function () {
    "use strict";

    var TIER_RANK = { economy: 0, standard: 1, premium: 2 };

    function isActiveTrial(state) {
        return state.accessState === "active_trial"
            || Boolean(state.access && state.access.status === "trialing");
    }

    function isPaidPlan(state) {
        var access = state.access;
        if (!access || !access.plan) return false;
        if (access.status !== "active") return false;
        var code = String(access.plan.code || "").toLowerCase();
        return code === "essential" || code === "advanced" || code === "pro";
    }

    function getMaxModelTier(state) {
        var access = state.access;
        if (!access || !access.plan) return null;
        // A trial has one fixed model regardless of the plan attached to it.
        if (access.status === "trialing") return null;
        return access.plan.model_access_tier || "economy";
    }

    function isModelAllowed(model, state) {
        if (state.accessAllowed === false) return false;
        if (Array.isArray(model.plans)) {
            if (!state.access) return false;
            var planCode = isActiveTrial(state) ? "free"
                : String((state.access.plan || {}).code || "").toLowerCase();
            return (isActiveTrial(state) || isPaidPlan(state))
                && model.plans.indexOf(planCode) >= 0;
        }
        // No subscription data and not a trial catalogue: show everything and
        // let the server be the authority. Hiding on missing data would lock a
        // tenant out of their own plan because one request failed.
        if (!state.access && !state.readOnly) return true;

        if (isActiveTrial(state)) {
            return model.access === "trial_only";
        }

        if (isPaidPlan(state)) {
            if (model.access === "trial_only") return false;
            var maxTier = getMaxModelTier(state);
            if (!maxTier) return false;
            var maxRank = TIER_RANK[maxTier] !== undefined ? TIER_RANK[maxTier] : -1;
            var modelRank = TIER_RANK[model.tier] !== undefined ? TIER_RANK[model.tier] : -1;
            return modelRank >= 0 && modelRank <= maxRank;
        }

        return false;
    }

    function hasAnyAccess(state) {
        if (state.accessAllowed === false) return false;
        if (state.readOnly) return true;
        return isActiveTrial(state) || isPaidPlan(state);
    }

    /** Providers that still have at least one selectable model. */
    function allowedProviders(state) {
        return Object.keys(state.options || {})
            .map(function (key) {
                var info = state.options[key] || {};
                var models = (info.models || []).filter(function (m) {
                    return isModelAllowed(m, state);
                });
                return { key: key, label: info.label || key, models: models };
            })
            .filter(function (provider) {
                return provider.models.length > 0;
            });
    }

    async function load() {
        var state = {
            options: {},
            readOnly: false,
            accessAllowed: true,
            accessState: null,
            denialReason: null,
            access: null
        };

        // Both requests are independent; a failure in either leaves its own
        // field at the permissive default rather than blocking the page.
        var results = await Promise.allSettled([
            authenticatedFetch("/api/ai-models").then(function (r) { return r.json(); }),
            authenticatedFetch("/api/billing/subscription").then(function (r) { return r.json(); })
        ]);

        var catalogue = results[0];
        if (catalogue.status === "fulfilled" && catalogue.value && catalogue.value.status === "success") {
            state.options = catalogue.value.data || {};
            state.readOnly = catalogue.value.read_only === true;
            state.accessAllowed = catalogue.value.access_allowed !== false;
            state.accessState = catalogue.value.access_state || null;
            state.denialReason = catalogue.value.denial_reason || null;
        }

        var subscription = results[1];
        if (subscription.status === "fulfilled" && subscription.value && subscription.value.status === "success") {
            state.access = subscription.value.data || null;
        }

        return state;
    }

    window.modelCatalog = {
        load: load,
        isModelAllowed: isModelAllowed,
        hasAnyAccess: hasAnyAccess,
        allowedProviders: allowedProviders,
        isActiveTrial: isActiveTrial,
        isPaidPlan: isPaidPlan,
        getMaxModelTier: getMaxModelTier
    };
})();
