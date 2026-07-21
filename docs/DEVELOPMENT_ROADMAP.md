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
> | 4L | Platform-admin controls | **Staging verified; production-readiness package prepared; production blocked** |
> | 4M | Production launch audit and remediation | Complete |
>
> ---

### Phase 4L update - Platform-admin controls

The initial read-only backend is implemented with a separate database-backed
platform-admin allowlist, per-request fail-closed authorization, dedicated
cross-tenant repositories, five GET-only endpoints, and audit-before-response
enforcement. Tenant roles and JWT claims do not grant platform access.

The separate read-only frontend is also implemented with a dedicated platform
shell, a fresh `/me` authorization gate on every page, an allowlisted GET-only
client, in-memory request cancellation/state clearing, exact company counts,
the server-paginated company directory, and safe company billing/AI-credit
detail views. The ordinary tenant sidebar does not expose platform navigation.

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
- CRM updates
- Analytics permissions
- Billing guards
- Integration route validation with external calls mocked

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
I. Grace period and failed-payment recovery .. Implemented
J. (future phases) .......................... Not started
