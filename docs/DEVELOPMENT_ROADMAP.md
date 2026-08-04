# Development Roadmap

> **Note:** The roadmap below uses original Phase numbering (1–8) from early development.
> The current billing and subscription work follows Phases 4E–4M:
>
> | Phase | Topic | Status |
> |---|---|---|
> | 4E | Subscription billing history and receipts | Complete |
> | 4F | Production security, tenant isolation, plan enforcement | Complete |
> | 4G | Admin and support operations | Complete |
> | 4H | Customer receipts, exports, usage reporting | Complete |
> | 4I | Renewal, grace period, failed-payment recovery | Complete |
> | 4J | Billing notifications and alerts | Complete |
> | 4K | Advanced billing and AI-usage reporting | Complete |
> | 4L | Platform-admin controls | **Original scope staging verified; current 12-route stack local-only; production blocked** |
> | 4M | Production launch audit and remediation | Complete |
> | 4N | Knowledge Readme compilation & Pop-out viewer | Complete |
>
> ---

### Phase 4L update - Platform-admin controls

The initial read-only backend is implemented with a separate database-backed
platform-admin allowlist, per-request fail-closed authorization, dedicated
cross-tenant repositories, twelve GET-only endpoints, and audit-before-response
enforcement. Tenant roles and JWT claims do not grant platform access. The
later users/chatbots company-inspection endpoints and Platform Operations
overview endpoint, plus the subscription-history and AI-credit transaction-history
investigation endpoints, Audit Logs viewer, and billing-order history endpoint are
application-only and locally tested unless separately staged later. The overview
uses latest-subscription rows per company ordered by `created_at DESC, id DESC`;
Operational Alerts Phase 1 extends the existing dashboard and overview response
only, deriving typed read-only subscription past-due/expired alerts from the
existing attention-company data without adding a route or page.

At the current HEAD, localhost manual verification recorded on 2026-08-03
passed for the complete twelve-route read-only stack: dashboard, operational
alerts, company directory/detail, subscription summary/history, AI-credit usage
and transactions, billing orders, users, chatbots, Support Workspace, Audit Logs,
billing-order audit filters, and local revocation with Access Denied and stale
platform-data clearing. This is local evidence only. The original five
platform-admin endpoints remain the only endpoint set recorded as staging
verified; later extensions remain application-only/local-tested unless separately
staged. Operational Alerts added no endpoint or page, and the billing-order
audit-filter fix added no route or backend behavior change.
The read-only smoke helper was also exercised locally on 2026-08-03 against
localhost: all twelve checks passed with an approved company ID, required-only
checks passed with child checks skipped when no company ID was supplied, and
missing `PLATFORM_ADMIN_TOKEN` failed safely. This is localhost evidence only;
the helper is local/staging-ready but requires an approved environment and
token, and does not change the production-blocked status.
The access request, revocation, replacement, and periodic-review procedure is
documented in `docs/PLATFORM_ADMIN_ACCESS_LIFECYCLE.md`; it is policy-only and
does not authorize mapping changes or production access.
Its evidence checklist covers approval, revocation, smoke checks, audit-log
review, redaction, and environment-specific evidence boundaries.
subscription history lists persisted `company_subscriptions` records and is not
an event-sourced status-transition timeline. Billing-order history lists mutable
`company_subscription_orders` records for company-scoped investigation, displays
`amount_sen` as integer sen as stored, and does not return or infer currency.
AI-credit alerts, billing-order attention alerts, inactive-company alerts,
no-current-chatbot alerts, payment reconciliation, checkout recovery, retry
payment, manual crediting, subscription activation, plan changes,
no-subscription counting, global activity, usage aggregation, charts, exports, audit export, audit
editing/deletion, and write controls remain deferred.

The separate read-only frontend is also implemented with a dedicated platform
shell, a fresh `/me` authorization gate on every page, an allowlisted GET-only
client, in-memory request cancellation/state clearing, the Platform Operations
overview, the server-paginated company directory, safe company billing/AI-credit
detail views, typed subscription operational alerts, and lazy read-only subscription-history, AI-credit transaction-history,
billing-order history, and company users/chatbots sections. A later bounded frontend-only platform-admin
Support Workspace adds a read-only investigation hub that reuses the existing
operations overview and company directory APIs, highlights attention companies,
and links into the existing company detail investigation page without adding a
backend endpoint. It is separate from tenant `support.html` and does not add
ticketing, support-case records, notes, assignment, billing-order history,
audit-log viewing, or write controls. The ordinary
tenant sidebar does not expose platform navigation.
The Audit Logs viewer adds a separate read-only page and one audited backend
endpoint for safe platform-admin audit event summaries. It returns actor mapping
IDs only, omits raw metadata and tenant records, and does not add audit
editing, deletion, export, download, charts, platform-admin user management, or
other write controls.
The Billing Order History section adds a lazy read-only company-detail
investigation surface for safe order status, amount_sen, plan code/name, and
lifecycle timestamp fields only. It excludes payment/gateway/checkout/reference,
idempotency, raw-error, reconciliation, retry, activation, manual-credit,
export/download, chart, and write behavior.
Authenticated tenant pages now use a shared top-right account menu for Profile,
Support, and Logout. Support points to a static authenticated tenant help page
with local self-service guidance and no support-submission backend. Active
platform admins can discover a Platform Administration link only after a lazy live
`/api/platform-admin/me` check. This menu visibility does not replace the
platform page's fresh authorization gate.

Migrations 023, 024, and 025 and all five read-only endpoints are verified in
staging. The five expected audit events and immediate revocation were verified;
the frontend dashboard, company directory, approved company detail, read-only
control set, and post-revocation Access Denied state were also verified in a
staging browser. No stale platform data remained visible after revocation. The
bootstrap mapping remains present and inactive. Production remains blocked by
the documented Phase 1.5 approval gates and has not received any of these
changes.

Phase 4 production-readiness documentation now defines the production
preflight and approval register, protected internal-company and bootstrap
controls, exact 023–026/backend/frontend/bootstrap verification sequence,
rollback and monitoring plans, completed final staging rehearsal evidence,
audit metadata and retention policy, and emergency revocation. Migration 026
now implements the
recommended UPDATE/DELETE rejection trigger and is verified in staging,
including service-role mutation rejection and rollback cleanup. The mapping
remains inactive. No production SQL, bootstrap, deployment, tenant-role change,
or maintenance bypass has been applied; production approvals remain
outstanding.

Production remains blocked: no confirmed staging/online environment is defined
in repository configuration; the latest extensions are not staging-verified; and
production ownership/executor, protected-company/bootstrap, audit
retention/redaction, monitoring, rollback, and backup/restore approvals or
evidence remain pending.

The final Phase 4 staging rehearsal is complete. It verified inactive-state
denial, time-bounded reactivation, dashboard and company read paths, normal
audit INSERTs under migration 026, approved audit metadata, revocation, and
clearing of cross-tenant data. The mapping remains present and inactive, and all
production-specific approval gates remain blocking.

## Roadmap Principles

The roadmap starts from the current implemented system. It does not rebuild working modules without evidence.

Priorities:

1. Security and correctness
2. Tenant isolation
3. Database and RPC traceability
4. Test coverage
5. External integration verification
6. Frontend consistency
7. Deployment readiness
8. Cleanup

## Phase 1 — Security and Authentication Hardening

### Goal

Remove production-sensitive debug behavior and strengthen authentication endpoints.

### Included work

- Remove or safely gate OTP values in logs
- Review raw exception messages returned by routes
- Review JWT storage and logout behavior
- Add rate limiting or equivalent protection for login, registration, and OTP endpoints
- Review invite and password-reset token expiry behavior
- Confirm production CORS settings
- Add focused authentication tests

### Excluded work

- Replacing the authentication architecture
- Migrating to Supabase Auth
- Adding server-side token revocation unless separately approved

### Acceptance criteria

- OTP values never appear in production logs
- Authentication endpoints have abuse controls
- Authentication errors do not expose sensitive details
- Focused authentication tests pass
- Existing billing tests still pass

### Risk

Medium

### Codex delegation

Safe for focused code and test changes. Human approval required for authentication architecture changes.

## Phase 2 — Tenant Isolation and Permission Verification

### Goal

Verify that all company-owned and chatbot-owned operations are properly scoped.

### Included work

- Inventory tenant-owned routes and repositories
- Review every route that accepts a resource ID
- Confirm company scope for conversations, CRM, chatbots, knowledge, integrations, billing, and team operations
- Add negative cross-company access tests
- Review owner/admin/member permissions
- Document unresolved Supabase RLS questions

### Acceptance criteria

- No known route can access another company’s resources
- High-risk repositories have company-scoping tests
- Chatbot ownership checks are consistent
- Permission expectations are documented

### Risk

High

### Codex delegation

Codex may perform static analysis and add tests. Human review is required before changing security boundaries.

## Phase 3 — Database Schema and RPC Version Control

### Goal

Make the repository a reliable source of truth for database behavior.

### Included work

- Export current schema definitions
- Export production RPC definitions
- Organize SQL migrations
- Document tables, fields, enums, and monetary units
- Document deployment order for RPC changes
- Record current RLS policies or confirm that none are enabled

### Acceptance criteria

- All application-used RPCs are version-controlled
- Database setup can be reproduced from documented scripts
- Schema and live environment differences are identified
- No production SQL is applied without review

### Progress recorded 2026-07-25

- Staging migration 028 removed the exact approved set of 36 orphan Agent Actions and two orphan CRM leads. Verification found no remaining orphans and no change to valid rows.
- Staging migration 027 then completed successfully with validated chatbot/conversation foreign keys and value checks, required Agent Action ownership, query and open-lead uniqueness indexes, RLS enabled without policies, and browser-role table and sequence privileges removed.
- Backend access remains service-role-only. The permanent chatbot deletion RPC remains `SECURITY DEFINER`, executable only by `service_role` among the application roles reviewed.
- Production has not been updated. Direct company foreign keys remain deferred until company-deletion semantics are approved.

### Risk

High

### Codex delegation

Codex may prepare documentation and migration drafts. Human Supabase approval is required before applying changes.

## Phase 4 — Core Backend Regression Coverage

### Phase 4C — Cancellation and scheduled downgrade (? Implemented)

- ? POST /api/billing/subscription/cancel — schedule cancellation
- ? POST /api/billing/subscription/undo-cancel — undo pending cancellation
- ? POST /api/billing/subscription/downgrade — schedule paid-plan downgrade
- ? DELETE /api/billing/subscription/downgrade — clear pending downgrade
- ? Cancellation clears pending downgrade (conflict resolution)
- ? Downgrade rejected when cancellation is pending
- ? Lifecycle job processes cancel ? downgrade ? expiry in order
- ? Downgrade execution rechecks usage, transitions to expired with new plan
- ? No AI credit granted during downgrade without payment
- ? Subscription API returns scheduling fields
- ? 34 unit tests passing

### Goal

Expand automated coverage beyond billing.

### Included work

- Authentication routes
- Team and invitation routes
- Chatbot CRUD
- Knowledge route validation
- Conversation access
- CRM updates, including lead assignment feature gating, assignment clearing, refreshed company context, and cross-tenant rejection
- Analytics permissions and signal ownership, including database-refreshed owner/admin enforcement, chatbot-scope rejection, and authoritative chatbot-derived company attribution for new agent actions
- Billing guards
- Integration route validation with external calls mocked

### Progress recorded 2026-07-27

- Escalation listing and exact-ID resolution now require the current database-backed owner/admin role. Resolution changes only the requested detected escalation, is idempotent on retries, and does not resume AI while another pausing escalation remains.
- Automatic CRM conversion now derives company ownership from the chatbot, verifies the conversation belongs to that chatbot, creates staff-attention leads for handoff requests before returning the handoff response, and keeps CRM failure non-blocking for customer messaging. Handoff email ownership also uses the authoritative chatbot company and never falls back to conversation payload ownership.
- Automatic and manual CRM flows reuse only open leads. Closed leads remain historical, and structured unique-conflict recovery reloads the concurrently created open lead.
- Same-action resolution retries cannot resend the AI-resumed notification. Atomic deduplication when two different final actions are resolved concurrently remains deferred to the lifecycle transaction/RPC phase.
- Expanded AI Signal lifecycle states, reviewer/audit fields, direct signal-to-lead linkage, and frontend actions remain deferred. No production database deployment is recorded by this application-only stabilization phase.

### Acceptance criteria

- Every major route group has focused success and failure tests
- Tenant and role failures are covered
- Tests run without live external services
- Full safe suite passes

### Risk

Medium

### Codex delegation

Suitable for phase-level delegation with human diff review.

## Phase 5 — Frontend Regression and Consistency

### Goal

Make major frontend workflows consistent and verifiable.

### Progress recorded 2026-07-22

- Profile Team & Workspace uses authenticated company data and presents compact Company Information and Team Summary cards. `team.html` remains the full Team management interface.
- Members have company-scoped read-only access. Admins and owners may manage invitations, supported member roles, and member statuses.
- Workspace and Team company context is resolved from the refreshed authenticated database user. Browser-supplied `company_id` and `bot_id` values do not determine workspace or Team authorization.
- `/api/workspace` now uses only the company lookup, an exact active-user count, the valid pending-invitation count, and the current subscription's Team-member limit. It no longer depends on full billing usage or chatbot, channel, knowledge, storage, AI-usage, or payment metrics.
- A transient failure in unrelated billing usage no longer blanks the Profile Team & Workspace cards. Manual verification confirmed `/api/workspace` returned HTTP 200 after resend, cancellation, and Profile load.
- Refreshed database roles are authoritative. Missing, blank, or invalid database roles fail closed, and JWT roles are not used as an authorization fallback.
- Direct `POST /api/users` account creation is disabled with HTTP 410. Team onboarding is invitation-only.
- Invitation roles are restricted to `admin` and `member`; `owner` cannot be assigned through an invitation.
- Role changes, status changes, invitation resend, and invitation cancellation use company-scoped fetches and writes.
- Active members plus valid, unexpired pending invitations consume the Team limit. An already-reserved pending invitation may be accepted when usage is exactly at the limit, while acceptance is rejected if the company is already over the limit.
- Expired or malformed pending invitations do not reserve seats. Stale pending invitation rows are refreshed rather than duplicated, and resending rotates the token and expiry.
- Invitation resend submits the invitation ID rather than email. A per-invitation in-flight guard blocks duplicate requests, disables the clicked Resend button during the request, and refreshes both the invitation list and Team usage after success.
- Manual resend verification produced one POST request and one email. Manual cancellation verification returned HTTP 200, removed the invitation, changed pending invitations from 1 to 0, and restored available seats from 2 to 3.
- Invitation URLs use `/accept-invite.html?token=<token>`.
- Password and Google invitation acceptance always join `invitation.company_id` and do not create another company.
- Google frontend configuration is loaded from public `GET /api/auth/google-config`; the invitation page contains no hardcoded Google client ID.
- Backend Google authentication requires a configured `GOOGLE_CLIENT_ID`, an exact token-audience match, a verified Google email, and an invitation-email match. Google unavailability does not prevent password invitation acceptance.
- Flask-Limiter initialization now preserves decorators registered before `create_app()` and enforces them during normal startup. Existing login, OTP, password-reset, checkout, retry, receipt, and export limits are genuinely active when `RATELIMIT_ENABLED=true`.
- Public invitation validation uses `RATELIMIT_INVITE_VALIDATE=30/minute`, password invitation acceptance uses `RATELIMIT_INVITE_ACCEPT=5/minute`, and Google authentication uses `RATELIMIT_GOOGLE_AUTH=10/minute`. Google login, registration, and invitation acceptance share the same Google endpoint limit.
- Rate-limited requests are rejected before protected database writes, invitation acceptance, password hashing beyond the threshold, or external Google verification. Same-IP enforcement, independent IP and endpoint buckets, disabled mode, and test-application isolation were verified.
- Focused workspace, Team, invitation, Google configuration, and tenant-scoping regression coverage is present.
- Latest full automated evidence: 1534 passed, 1 skipped, 143 subtests passed. Python compilation, invitation-page and Team-page JavaScript syntax validation, and diff validation also passed.

### Progress recorded 2026-07-28

- Public landing page (`landing.html`) created to introduce the platform features, pricing, and FAQ. It utilizes the premium glassmorphic dark design of the dashboard and auth pages.
- Dynamic session detection checks for authenticated user tokens and automatically updates CTAs to "Go to Dashboard" when logged in.
- Backend routing configured in `app/views.py` and `app/__init__.py` to serve `landing.html` at the root path (`/`).

### Progress recorded 2026-07-29

- Static authenticated tenant Support page (`support.html`) added as a bounded frontend consistency improvement. It uses the ordinary tenant sidebar and shared account menu, requires login through the existing frontend auth helper, renders account display text safely from session storage, links only to existing local tenant pages, and does not add support forms, ticket creation, email sending, backend routes, configuration, staging changes, or production changes.
- The shared tenant account menu now restores Support as a working destination while keeping Profile, Logout, and lazy live Platform Administration discovery behavior unchanged. Direct contact and support-ticket submission remain deferred until an approved contact destination and backend design exist.
- Public landing-page pricing was aligned with the authoritative subscription plan catalogue used by authenticated Billing. The landing page now renders published plan values from a tested duplicate frontend catalogue module, removes unsupported support-level claims, and keeps logged-out/register plus logged-in/billing CTA behavior covered by local tests. The duplicate module must be updated whenever plan migrations, runtime plan rows, or commercial values change; a public-safe plan catalogue endpoint remains a possible later cleanup. Free stores the economy tier internally but is presented as DeepSeek Only because active trial provider access is direct DeepSeek only. The Pro public description uses neutral application copy because the current runtime database row still contains legacy example wording; correcting that row remains a separate reviewed data-migration decision.

### Deferred risks

- Normal registration and invitation acceptance remain non-atomic multi-write operations. A transactional PostgreSQL/Supabase RPC or equivalent transaction remains required.
- Concurrent invitation creation still ultimately requires database-level uniqueness or transactional protection against duplicate pending invitations.
- Trusted reverse-proxy/client-IP handling remains required so public rate-limit buckets use the intended client address.
- Redis or equivalent shared production limiter storage remains required for consistent multi-worker enforcement.
- Live external Google end-to-end verification remains required.
- Full visual browser verification remains required before Phase 5 can be considered complete.

### Included work

- Authentication pages
- Dashboard
- Chatbots
- Knowledge management
- Conversations
- CRM
- Integrations
- Team
- Profile and billing
- Shared navigation and authenticated request behavior

### Acceptance criteria

- Loading, empty, success, and error states exist for major pages
- Dead controls and broken links are removed
- Conversation search, deep links, copy, and transcript download still work
- Billing return and polling states work
- A documented manual regression checklist exists
- Frontend automated test options are evaluated

### Risk

Medium

### Codex delegation

Suitable for bounded page groups. Human visual review is required.

## Phase 6 — External Integration Verification

### Goal

Verify each supported external integration in a controlled environment.

### Included work

- OpenRouter
- DeepSeek
- Gemini
- Telegram
- Wasender
- Meta WhatsApp
- ToyyibPay

### Acceptance criteria

For each integration:

- Required environment variables are documented
- Connection and disconnection are tested
- Webhook verification is tested
- Failure handling is confirmed
- Credentials are not exposed
- Manual verification evidence is recorded

### Risk

High

### Codex delegation

Codex may prepare scripts and checklists. Live credential use requires human control.

## Phase 7 — Deployment Readiness

### Goal

Prepare a repeatable and secure deployment process.

### Included work

- Production environment checklist
- Dependency validation
- Runtime command
- HTTPS and webhook URL requirements
- Secret management
- Logging and monitoring
- Backup and rollback procedures
- Background worker behavior
- Health checks
- Production configuration review

### Acceptance criteria

- Staging deployment succeeds
- Safe smoke tests pass
- Required external callbacks are reachable
- Secrets are stored outside the repository
- Rollback steps are documented
- Production debug tools are disabled

### Risk

High

### Codex delegation

Codex may generate deployment files and documentation. Human approval is required for live deployment.

## Phase 8 — Cleanup and Maintainability

### Goal

Remove confirmed obsolete files and reduce maintenance overhead.

### Included work

- ~~Review~~ `unused_backup/` (removed)
- Review root-level test and diagnostic scripts
- Review old planning documents
- Review committed PDF data
- Consolidate shared frontend logic
- Remove dead compatibility code

### Acceptance criteria

- Every deletion has reference-search evidence
- Full safe test suite passes after cleanup
- No active page, import, route, or script breaks
- Documentation reflects the cleaned structure

### Risk

Low to medium

### Codex delegation

Suitable after reference checks. Human approval required for bulk deletion.

## Suggested Development Workflow

For each phase:

1. Ask Codex to audit only that phase.
2. Review the phase plan.
3. Allow Codex to implement the complete bounded phase.
4. Run focused and full safe tests.
5. Review the diff.
6. Update `FEATURE_STATUS.md`.
7. Commit the phase with one or a small number of meaningful commits.
