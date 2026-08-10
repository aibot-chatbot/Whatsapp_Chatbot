# Platform-admin Monitoring Phase 6 Contract

Platform-admin Platform Monitoring Phase 6 is implemented as a read-only
extension of `GET /api/platform-admin/overview`. It adds cross-tenant
operational monitoring for authorized platform admins without adding new
platform-admin mutation routes.

Phase 6 is locally implemented, automatically tested, and runtime-verified
against the approved main shared-testing Supabase with fake/team data plus the
localhost frontend/API. Migration 037 is applied and verified only in that
main shared-testing environment. This is not staging verification and does not
establish production readiness.

## Authorization Boundary

Platform authority continues to come only from active `platform_admin_users`
mappings. Tenant `users.role` never grants platform-admin access. The overview
route remains guarded by the existing platform-admin authorization boundary and
records the existing `platform_admin.operations.overview.read` audit event
before returning data.

Phase 6 is read-only. It does not add impersonation, tenant mutation, billing
adjustment, manual credits, company lifecycle controls inside monitoring cards,
or generic job-health controls.

## Implemented Monitoring Scope

The overview response remains backward compatible and adds bounded nested
sections for:

- Platform Summary: total companies, active companies, inactive companies,
  active users, and the existing subscription summary.
- Support Operations: support cases by status, support cases by priority, open
  case count, tenant support requests by status, and unresolved tenant support
  request count.
- Messaging & Integrations: message delivery status counts, authoritative
  retry backlog, Telegram channel health, Wasender channel health, Meta
  WhatsApp channel health, broadcast campaign status counts, and broadcast
  recipient status counts.
- Billing Attention: billing orders by status, pending order count, failed
  order count, reconciliation-required count, activation status breakdown, and
  NULL activation status preserved separately rather than treated as failure.
- AI Usage & Credits: AI requests by status, seven-day recent request count,
  seven-day token usage, AI-credit transactions by approved type, and depleted
  AI-credit balance company count.
- Platform-admin Activity: seven-day recent audit event count, safe counts by
  approved action, and safe counts by approved resource type. Raw audit
  metadata is not returned.

## Operational Alerts

Existing subscription alerts remain. Phase 6 adds these deterministic
read-only aggregate alert types:

- `support_backlog`
- `billing_orders_pending`
- `billing_reconciliation_required`
- `ai_credit_depleted`
- `messaging_retry_backlog`
- `integration_channel_attention`

Company/subscription alerts retain company-specific context and link to
company investigation. Platform-wide aggregate alerts render as Severity,
Summary, Count, and Investigate. Global aggregate alerts are not forced into
subscription-only fields such as company status, subscription status, plan, or
current period end.

Monitoring cards introduce no mutation controls.

## Query And Performance Contract

The monitoring repository calls one bounded read-only PostgreSQL RPC,
`public.get_platform_admin_monitoring_overview()`, for Phase 6 monitoring
aggregates. It does not use unsupported PostgREST aggregate select syntax,
`SELECT *`, return large global row sets to Python merely for counting, or
expose customer content.

The initial Phase 6 implementation was repaired before completion twice: first
from per-domain exact-count loops, then from grouped PostgREST aggregate
selects after the approved shared-testing PostgREST environment rejected
syntax such as `status,count:id.count()` with HTTP 400. Final monitoring
aggregation is server-side through the Migration 037 RPC. Existing
company/subscription overview reads remain separate from that monitoring RPC.
RPC output is strictly validated, and unsupported aggregate values fail closed
instead of becoming trusted output.

Migration 037 adds only the bounded read-only monitoring aggregate RPC. It
contains no writes or dynamic SQL, does not weaken RLS or table privileges, is
service-role-only executable, and filters platform-admin activity aggregates to
the current approved audit action and resource-type contract. Historical
obsolete audit rows remain immutable audit evidence but are excluded from
monitoring output.

## Retry Backlog Semantics

A message is counted in retry backlog only when all of these persisted facts
are true:

- `sender_type = bot`
- `ai_generated = true`
- `delivery_status = failed`
- `retry_count` is NULL or below the retry limit
- `next_retry_at` is NULL or currently due

All failed messages are not retry backlog.

## Channel Health Semantics

Channel attention counts distinct configured channels requiring attention. A
channel requires attention when it is inactive, disconnected, or in error. A
channel satisfying multiple attention conditions is counted once.

A provider with zero configured channels is a healthy empty monitoring state
and does not create an alert merely because no row exists.

## Security And Redaction

The overview and dashboard must not expose:

- message text
- customer phone numbers
- prompts
- AI responses or model inputs
- raw provider errors
- provider payloads
- webhook payloads
- API keys or tokens
- authorization headers
- payment references
- checkout URLs
- gateway or customer identifiers
- raw reconciliation errors
- raw audit metadata
- request or response bodies

All aggregates are server-derived. Browser-supplied tenant, company, status, or
role data never determines cross-tenant aggregate scope.

## Omitted Metrics

These metrics are intentionally not implemented in Phase 6:

- Support SLA or overdue metrics: no authoritative deadline field exists.
- AI low-balance metric: no approved low-balance threshold exists.
- Generic background job health: no durable authoritative job telemetry exists.
- Provider cost monitoring: intentionally excluded from the dashboard.

## Shared-testing Inspection Evidence

The Phase 6 read-only inspection was run only against the approved main
shared-testing Supabase with fake/team data. It confirmed all relevant
monitoring tables were present, no required candidate fields were missing, the
current dataset was small, and existing schema/indexes were sufficient for the
first implementation. The later PostgREST aggregate incompatibility required
Migration 037 for a bounded monitoring RPC, not an index migration.

Observed values included 25 active companies, 14 active users, two
`in_progress` high-priority platform support cases, one converted tenant
support request, 88 sent and 77 received messages, retry backlog 0, two active
connected Telegram channels, one active connected Wasender channel, no current
Meta WhatsApp health row, no current broadcast campaign or recipient rows, 452
completed AI requests, six AI-credit balance rows, zero depleted balances,
three active subscriptions, four trialing subscriptions, four pending billing
orders, one credited billing order, and zero reconciliation-required orders.

These current counts are verification evidence only, not permanent business
expectations.

## Migration 037 And Runtime Evidence

Migration 037 (`data/037_platform_admin_monitoring_aggregates.sql`) adds
`public.get_platform_admin_monitoring_overview()`. It is owned by `postgres`,
`SECURITY INVOKER`, uses `search_path=pg_catalog`, has no dynamic SQL, writes
no rows, does not change browser-role table access, and is executable only by
`service_role`.

The original PostgREST aggregate implementation failed in shared testing
because REST aggregate select syntax such as `status,count:id.count()` returned
HTTP 400. Migration 037 replaces those unsupported REST aggregate calls with
one bounded read-only RPC for the Phase 6 monitoring aggregates while the
existing company/subscription overview reads remain separate.

Runtime verification in the approved main shared-testing Supabase with
fake/team data plus localhost frontend/API confirmed:

- `GET /api/platform-admin/me` returned 200.
- `POST /rest/v1/rpc/get_platform_admin_monitoring_overview` returned 200.
- `GET /api/platform-admin/overview` returned 200.
- The Platform Operations dashboard rendered successfully.
- The Temporarily Unavailable state no longer appears.

A historical obsolete audit action, `platform_admin.support_case.update`,
initially caused strict Python monitoring validation to reject the RPC output
after the RPC returned HTTP 200. Migration 037 was corrected before
finalization so platform-admin activity aggregates include only current
approved audit actions and current approved resource types. Historical audit
rows were not deleted or modified.

## Verification Evidence

Focused Phase 6 automated tests passed, the broader platform-admin selector
passed, Python compilation passed, JavaScript syntax validation passed, and
`git diff --check` passed. Browser E2E was blocked locally because `npm` was
not available and the Playwright package was absent from local `node_modules`;
no browser pass is claimed.

During Phase 6 verification, a Phase 5 broadcast regression test exposed a
Meta WhatsApp helper-name compatibility issue. The compatibility wrapper
`get_interactive_button_message_input()` was restored around
`get_interactive_button_message()`. The helper preserves the established safety
behavior: maximum three buttons, labels trimmed, empty or NULL labels skipped,
and titles truncated to 20 characters. This was a compatibility repair, not a
Phase 6 monitoring feature or a WhatsApp messaging redesign.
