# Platform-admin Billing & Subscription Oversight Contract

## Status

Platform-admin Billing & Subscription Oversight Phase 7 is implemented as a
read-only platform-admin surface. Migration 038 is applied and verified only in
the approved main shared-testing Supabase with fake/team data. This is not
staging verification and does not establish production readiness.

Local runtime verification against the approved main shared-testing Supabase
confirmed:

- `GET /api/platform-admin/me` returned 200.
- `GET /api/platform-admin/overview` returned 200.
- `GET /api/platform-admin/billing/overview` returned 200.
- `GET /api/platform-admin/billing/companies?limit=25&offset=0` returned 200.
- The underlying billing overview, billing company directory, subscription-status
  filtered directory, attention-filtered directory, and replaced monitoring RPC
  returned successfully.
- The Platform Billing & Subscriptions frontend rendered the overview sections
  and Tenant Billing Directory.
- No financial mutation controls are present.

A separate transient tenant-side Supabase HTTP/2 `RemoteProtocolError` occurred
during `/api/billing/usage` and `/api/bots` loading before the platform-admin
runtime checks. It is not recorded as a Phase 7 failure without reproducible
evidence that Phase 7 caused it.

## Authorization

Platform authority remains based only on active `platform_admin_users` mappings.
Tenant `users.role` never grants platform-admin access. Browser-supplied actor,
role, company authority, status override, or financial mutation intent is never
trusted.

## Implemented Surface

Phase 7 adds a dedicated Platform Billing & Subscriptions page and two read-only
routes:

- `GET /api/platform-admin/billing/overview`
- `GET /api/platform-admin/billing/companies`

Company billing investigation reuses the existing platform-admin company detail
views for subscription history, AI-credit usage, AI-credit transactions, and
billing-order history.

No financial mutation route or control is added.

## Migration 038

`data/038_platform_admin_billing_oversight.sql` creates or replaces:

- `public.get_platform_admin_billing_overview()`
- `public.get_platform_admin_billing_companies(integer, integer, text, text, boolean)`
- `public.get_platform_admin_monitoring_overview()`

All three verified functions are owned by `postgres`, are `SECURITY INVOKER`,
use `search_path=pg_catalog`, deny `anon` and `authenticated` execution, and
have `EXECUTE` granted only to `service_role`.

Migration 038 contains no dynamic SQL, no writes, no table grant weakening, and
no RLS weakening. It updates the existing Phase 6 monitoring RPC only to include
the Phase 7 billing read actions and resource types in Platform-admin Activity.
Migration 037 remains immutable historical migration source.

## Billing Overview

The overview RPC returns safe aggregate sections only:

- subscriptions by status;
- subscriptions by plan;
- active plan catalogue with integer `price_sen`;
- subscription orders by status;
- pending and failed subscription-order counts;
- reconciliation-required count;
- activation status and activation type breakdowns;
- NULL activation status/type counts kept separately;
- AI-credit top-up orders by status, pending, failed, and credited counts;
- AI-credit balance-row count, depleted-company count, included balance, top-up
  balance, and approved transaction-type counts;
- AI usage request-status counts and bounded seven-day request/token summary;
- billing notifications by type, severity, and read state only;
- subscription lifecycle counts for pending plan changes, scheduled
  cancellations, and both-state rows.

Subscription orders and AI-credit top-up orders remain separate operational
domains. NULL activation state is not treated as failed.

## Tenant Billing Directory

The billing company directory is database-side and bounded:

- starts from the approved company population;
- includes companies with and without subscriptions;
- left-joins latest subscription, plan, AI-credit balance, subscription-order
  attention, and top-up attention summaries;
- applies subscription status, plan, and attention filters in PostgreSQL;
- counts the filtered population before pagination;
- orders by `company_id ASC`;
- applies `LIMIT` and `OFFSET` in PostgreSQL.

The directory returns only:

- `company_id`;
- `company_name`;
- `company_status`;
- `current_plan` with `code` and `name`, or null;
- `subscription_status`, or null;
- `current_period_start`, or null;
- `current_period_end`, or null;
- `pending_plan_change`;
- `cancellation_scheduled`;
- `ai_credit_total_balance_micro_myr`;
- subscription-order attention counts;
- top-up-order attention counts.

The SQL does not return a frontend URL. The local frontend constructs the safe
company investigation link from the validated company ID.

## Null Subscription Contract

Companies without a subscription use the authoritative null contract:

- `subscription_status = null`
- `current_plan = null`
- `current_period_start = null`
- `current_period_end = null`
- `pending_plan_change = false`
- `cancellation_scheduled = false`

Do not invent a synthetic subscription status. No fake status such as `none`,
`free`, `unconfigured`, or `missing` is invented.
AI-credit balance and billing/top-up attention may still be present for these
companies.

## Frontend

The Platform Billing & Subscriptions page renders:

- Subscription status;
- Plan distribution;
- Active plan catalogue;
- Subscription order attention;
- AI-credit top-up attention;
- AI Credit Overview;
- MYR-formatted AI-credit balances;
- Billing Notifications;
- Subscription lifecycle;
- Tenant Billing Directory.

The page has loading, empty, unavailable, and authorization-loss handling. It
contains no financial action buttons.

## Audit

Phase 7 read actions:

- `platform_admin.billing.overview.read`
- `platform_admin.billing.company_list`

Resource types:

- `platform_billing_overview`
- `platform_billing_companies`

Audit metadata is limited to safe read context: outcome, endpoint, HTTP method,
generated timestamp, pagination, returned count, and filter-applied booleans.
No financial values, company names, payment identifiers, gateway details, raw
filters, or raw row payloads are stored in Phase 7 audit metadata.

Migration 038 extends the Phase 6 monitoring RPC allowlist so these actions and
resource types appear in Platform-admin Activity aggregates.

## Deferred Financial Mutations

The following remain deferred:

- manual AI-credit adjustment;
- payment reconciliation mutation;
- refund;
- subscription correction or override;
- manual plan change;
- direct balance editing;
- payment retry mutation;
- manual credit reversal;
- billing impersonation or remediation controls.

Phase 7 is read-only.

## Privacy And Security Exclusions

Phase 7 must not expose:

- payment references;
- checkout URLs;
- gateway identifiers;
- idempotency keys;
- raw gateway or callback payloads;
- raw reconciliation errors;
- raw provider errors;
- payment credentials;
- provider cost;
- raw prompts or responses;
- raw audit metadata;
- arbitrary customer personal data.

Approved company name remains allowed in the tenant billing directory because it
is already part of the platform-admin company directory safe projection.

## Performance

The final architecture uses:

- one bounded billing-overview RPC;
- one bounded billing-company-directory RPC;
- no Python 10,000-row directory scan;
- no per-company N+1 billing-directory aggregation;
- PostgreSQL-side filtering, counting, and pagination;
- stable `company_id ASC` ordering;
- separate lazy-loaded company-detail histories for detailed investigation.

It is not an unrestricted global analytics surface.
