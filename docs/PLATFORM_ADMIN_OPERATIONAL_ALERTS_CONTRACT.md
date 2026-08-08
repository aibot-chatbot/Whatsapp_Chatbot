# Platform-admin Operational Alerts Contract

## Status and scope

This is a design contract for future read-only operational alerts. Operational
Alerts Phase 1 is implemented locally through the existing `/overview` response.
Phase 2 is deferred until each definition, threshold, false-positive rule, and
safe field set is approved. The current 12-route platform-admin stack remains
localhost-verified only; production remains blocked.

## Phase 1 implemented alerts

Phase 1 currently supports only:

- `subscription_past_due`
- `subscription_expired`

These alerts are derived from existing latest-subscription attention data. They
provide investigation context only and do not perform remediation.

## Response contract

The existing `GET /api/platform-admin/overview` response contains:

```text
operational_alerts.alerts
operational_alerts.summary
operational_alerts.limits.max_alerts
```

Alert rows may contain a type, severity, company identity/status, concise
summary, safe investigation details, and a company-detail investigation link.
The current maximum is 10 alerts unless separately approved.

## Alert principles

- Alerts are read-only observations only.
- No remediation buttons or write controls are permitted.
- Alerts must not initiate payment, reconciliation, checkout, manual credit,
  plan changes, or other operational actions.
- Responses must exclude payment references, gateway data, checkout data,
  secrets, customer content, and unnecessary sensitive payloads.
- A company-detail link is allowed only for read-only investigation.
- Alert generation must remain bounded and fail closed on invalid source data.

## Deferred Phase 2 candidates

All candidates below are deferred. They are not implemented alert types.

| Alert | Required source data | Proposed safe fields | False-positive risk and exclusion rule | Query likely? | Why deferred |
|---|---|---|---|---|---|
| `ai_credit_low` | Current company balance, active period, approved threshold | Company ID/name, severity, balance band, period end | High if no balance row, expired period, or threshold is not applicable. Exclude companies without an active credit period. | Yes, bounded cross-company balance query | Threshold and period semantics are not yet approved. |
| `ai_credit_depleted` | Current included plus top-up balance and active period | Company ID/name, severity, depleted status, period end | Medium if a missing/stale balance is treated as zero. Require an initialized active balance before alerting. | Yes, bounded cross-company balance query | The overview has no current cross-company balance scan or approved missing-row rule. |
| `company_inactive` | Company status and approved inactivity meaning | Company ID/name, status, last safe update timestamp | High because inactive may be intentional or administrative. Exclude explicitly approved dormant/onboarding states. | Yes, per-company selection beyond current counts | Status meaning and operator action boundary are not approved. |
| `no_current_chatbot` | Company membership plus current chatbot state | Company ID/name, current chatbot count | Medium because some companies may intentionally have no chatbot. Exclude onboarding, paused, or non-chatbot plans if approved. | Yes, cross-company chatbot aggregate | No current cross-company chatbot count exists in the overview. |
| `billing_order_requires_attention` | Safe order status and a formally defined attention predicate | Company ID/name, order status, activation status, safe timestamps | High because `reconciliation_required` can imply payment remediation. Exclude gateway/reference/payment data and any action suggestion. | Yes, cross-company order query | Definition risks creating an implicit reconciliation workflow. |
| `no_subscription_recorded` | Company list matched against latest subscription records | Company ID/name, subscription-recorded boolean | High for free, onboarding, test, or intentionally unsubscribed companies. Exclude approved non-billing states. | Yes, missing-record matching query | No approved business rule identifies which companies must have subscriptions. |

Each candidate requires an approved exclusion rule before implementation. No
candidate should expose raw balances, payment identifiers, customer data, or
remediation instructions.

## Explicit exclusions

This contract does not introduce:

- write controls or remediation actions;
- retry, reconcile, checkout, payment links, or payment operations;
- manual credit or plan changes;
- impersonation;
- exports or charts;
- new platform-admin routes.

## Approval checklist

Before implementing any Phase 2 alert:

- [ ] Alert definition approved.
- [ ] Threshold or predicate approved.
- [ ] False-positive and exclusion rule approved.
- [ ] Safe fields and redaction boundary approved.
- [ ] Bounded query and failure behavior reviewed.
- [ ] Focused service, repository, route, frontend, and browser tests planned.
- [ ] Feature status, roadmap, and relevant policy documentation updated.
- [ ] Local verification completed before any separately approved staging test.

Phase 2 remains a design contract only. It does not claim staging verification
or production readiness.
