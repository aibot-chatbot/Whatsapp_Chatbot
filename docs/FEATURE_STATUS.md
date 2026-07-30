# Feature Status

## Status Definitions

- **Verified complete**: implemented and supported by current test evidence or recorded successful end-to-end verification
- **Implemented**: coherent implementation exists but verification is incomplete
- **Partially implemented**: required parts are missing or disconnected
- **On hold**: intentionally paused
- **Obsolete**: no longer part of the active system
- **Needs investigation**: evidence is conflicting or insufficient

## Authentication and Account Management

| Feature | Status | Notes |
|---|---|---|
| Registration | Implemented | Backend and frontend flow exist; broader automated coverage is still needed |
| Public Landing Page | Implemented | Clean, glassmorphic landing page introducing project features, FAQ, and subscription pricing aligned with the authoritative billing plan catalogue; dynamic login checks; served as root `/` |
| Login | Implemented | JWT login flow exists |
| Logout | Implemented | Client-side token removal; no server-side revocation |
| Forgot password | Implemented | Requires renewed end-to-end verification |
| Reset password | Implemented | Requires renewed end-to-end verification |
| Password visibility controls | Implemented | Present in authentication flows |
| Email verification / OTP | Implemented | Security review required for OTP logging and production behavior |
| Google authentication | Implemented | Public client configuration loads at runtime; missing `GOOGLE_CLIENT_ID` fails closed, token audience must match exactly, Google email must be verified, and invitation email must match. `RATELIMIT_GOOGLE_AUTH=10/minute` covers Google login, registration, and invitation acceptance; live external Google verification is still required |
| Auth and public-invitation rate limiting | Verified complete | Flask-Limiter decorators registered before `create_app()` are enforced during normal startup. Existing login, OTP, password-reset, checkout, retry, receipt, and export limits are active when enabled; invitation validation is 30/minute and password invitation acceptance is 5/minute by default |
| User profile | Implemented | Profile viewing and update flow exists |
| Authenticated tenant Support page | Implemented | Static authenticated help page exists at `support.html` and is reachable from the shared tenant account menu. It uses local self-service guidance and verified local links only; direct contact, ticket submission, email sending, and support intake remain deferred because no approved destination/backend exists |
| Password change | Implemented | Requires regression coverage |

## Company and Team

| Feature | Status | Notes |
|---|---|---|
| Company creation | Implemented | Created during account onboarding |
| Profile company/workspace summary | Verified complete | Uses only company lookup, exact active-user count, valid pending-invitation count, and the current subscription Team limit. It is independent of full billing, chatbot, channel, knowledge, storage, AI-usage, and payment metrics, so unrelated usage failures do not blank the cards |
| Team member list | Verified complete | Company-scoped read-only access for members uses refreshed database company and role context; admin/owner management actions remain permission-gated |
| Team invitations | Implemented | Onboarding is invitation-only and direct `POST /api/users` returns HTTP 410. Roles are limited to `admin`/`member`. Active members plus valid unexpired pending invitations count toward the limit. Stale rows are refreshed and resend rotates token/expiry. Resend submits invitation ID, blocks duplicate in-flight requests, disables the clicked button, and refreshes invitations and Team usage after success. Password/Google acceptance joins `invitation.company_id`; transactional acceptance remains deferred |
| Role management | Implemented | Writes are company-scoped; refreshed database roles are authoritative with no JWT fallback, and owner accounts are protected |
| Member deactivation | Implemented | Status updates are company-scoped, owner accounts are protected, and reactivation checks the Team limit |

## Chatbots and Configuration

| Feature | Status | Notes |
|---|---|---|
| Chatbot creation | Implemented | Backend and frontend exist |
| Chatbot listing | Implemented | Company-scoped |
| Chatbot editing | Implemented | Requires broader route tests |
| Chatbot deletion | Implemented | Requires deletion-flow verification |
| Prompt configuration | Implemented | Profile and deployment flow exists |
| Model selection | Implemented | Model catalog and settings UI exist |
| Automated menu or flow generation | Implemented | Requires current verification |
| Media Attachments | Implemented | Backend, UI, and webhook dispatch created |

## Knowledge and RAG

| Feature | Status | Notes |
|---|---|---|
| Knowledge file upload | Implemented | External storage and full error-path verification still needed |
| Knowledge file listing | Implemented | Chatbot-scoped |
| Active knowledge selection | Implemented | Current active file behavior exists |
| Supporting knowledge toggle | Implemented | Enabled/disabled knowledge behavior exists |
| Website scraping | Implemented | Single URL scraping requires single_website_scraping feature; batch scraping requires batch_website_scraping; Advanced can scrape single URLs only |
| Knowledge refinement | Implemented | Requires end-to-end verification |
| Chunk storage and retrieval | Implemented | Database/vector configuration requires environment verification |
| RAG response flow | Implemented | Quality and adversarial testing remain |
| Knowledge graph visualization | Implemented | Graph rendering and node/edge CRUD in new_linkdocs.html |
| Knowledge graph editing | Implemented | Add, rename, delete nodes; add, delete edges; focused route tests exist |
| Compiled README generation | Implemented | Automatically updates bot_<id>_readme.md on PDF uploads, graph mutations, and Q&A submissions |
| README popup viewer | Implemented | Modal dialog next to the active PDF file in new_linkdocs.html showing parsed markdown structure |

## AI Providers

| Feature | Status | Notes |
|---|---|---|
| Model catalog | Implemented | Static/catalog-based model definitions |
| OpenRouter routing | Implemented | External API verification required |
| DeepSeek routing | Implemented | External API verification required |
| Gemini usage | Implemented | Used in AI and/or embedding flows; verify exact active paths |
| AI usage logging | Implemented | Integrated with AI-credit charging |
| Provider fallback behavior | Needs investigation | Confirm current failure and fallback rules |

## Messaging Integrations

| Feature | Status | Notes |
|---|---|---|
| Telegram connection | Implemented | Requires controlled live verification |
| Telegram webhook | Implemented | Requires production webhook verification |
| Telegram disconnect/reconnect | Implemented | Requires live regression |
| Wasender connection | Implemented | Requires controlled live verification |
| Wasender webhook | Implemented | Requires live verification |
| Wasender retry worker | Implemented | Operational verification required |
| Meta WhatsApp Embedded Signup | Implemented | Live status depends on Meta app/business approval |
| Meta WhatsApp webhook | Implemented | Production signature and message-flow verification required |
| Message deduplication | Implemented | Repository support exists for supported channels |
| Broadcast campaigns dashboard | Verified complete | Dedicated frontend workspace and CRUD routes verified |
| Broadcast CSV uploading | Verified complete | Client-side CSV parser and pending logs registration verified |
| Broadcast CRM contacts extraction | Verified complete | Extraction of unmasked contacts from active chats verified |
| Broadcast pacing delay sending | Verified complete | Context-propagated background worker sending with 3s delays verified |

## Conversations and CRM

| Feature | Status | Notes |
|---|---|---|
| Conversation list | Implemented | Backend and frontend exist |
| Message history | Implemented | Conversation-scoped |
| Message search | Implemented | Previously reviewed in the conversation interface |
| Inbox auto-polling | Implemented | 3-second interval for escalations, conversations, and messages |
| Agent reply and dispatch | Implemented | Reply via inbox dispatches to WhatsApp, Telegram, Wasender |
| Handoff email notification | Implemented | SMTP-based email to active staff when customer requests human agent |
| Conversation deep links | Implemented | URL synchronization and direct loading were previously reviewed |
| Copy conversation link | Implemented | Previously reviewed |
| Copy transcript | Implemented | Previously reviewed |
| Download transcript | Implemented | Previously reviewed |
| CRM lead list | Implemented | Company/chatbot scoped |
| Lead status | Implemented | Status editing exists |
| Lead priority | Implemented | Priority editing exists |
| Lead assignment | Verified complete | Non-empty assignment uses the authenticated database-backed company context and remains gated by crm_lead_assignment; assignment clearing remains available to all plans; focused route regression tests cover success and rejection paths |
| Lead follow-up | Implemented | Follow-up fields and UI exist |
| CRM filters | Implemented | Status, assignment, and related filtering exist |
| CRM-to-conversation navigation | Implemented | Conversation ID linking was previously reviewed |

## Analytics and Operations

| Feature | Status | Notes |
|---|---|---|
| Dashboard metrics | Implemented | Requires broader regression tests |
| Message charts | Implemented | Data aggregation and frontend display exist |
| Live workflow status | Implemented | Requires runtime verification |
| Dashboard health | Implemented | Requires environment verification |
| Agent insights | Implemented | Server-side owner/admin access uses the database-refreshed role and preserves chatbot ownership checks; new Agent Actions and automatic CRM leads derive company ownership from the authoritative chatbot record. Staging migrations 028 and 027 hardened stored data and service-role-only access. Expanded review/dismissal/linkage lifecycle fields and frontend actions remain deferred; production database migrations remain unapplied. |
| AI-generated reports | Implemented | External model and feature-gate verification required |
| Escalation handling | Implemented | Listing and exact-ID resolution require the current database-backed owner/admin role; resolution is compare-and-set idempotent and leaves unrelated signals unchanged. Same-action retries cannot repeat the AI-resumed notification; atomic deduplication across two different concurrently resolved final actions remains deferred to the lifecycle transaction/RPC phase. Focused regression tests are present; execution remains pending in a repaired test environment. |

## Subscription and AI Credit

| Feature | Status | Notes |
|---|---|---|
| Subscription plans | Implemented | Plan catalogue active for Free trial, Essential (RM39/month), Advanced (RM89/month), and Pro (RM169/month); included AI credits are RM1 Free trial, RM5 Essential, RM20 Advanced, and RM60 Pro. Free stores `model_access_tier=economy` for compatibility, but customer-facing trial access is DeepSeek Only and the active trial provider policy is direct DeepSeek only. Public landing pricing uses a tested duplicate catalogue; the Pro public description is application-only safe copy until `subscription_plans.description` is corrected through a reviewed data migration. |
| Current subscription | Implemented | Company-scoped |
| AI-access policy resolver | Implemented | Central resolve_ai_access() in ai_access_policy.py handles trial/paid/denied states |
| Trial initialization | Implemented | New companies get Free plan + status=trialing + 7-day trial_ends_at |
| Trial provider isolation | Implemented | Active trial uses direct DeepSeek only; no OpenRouter for trials |
| Paid provider isolation | Implemented | Paid plans (Essential/Advanced/Pro) use OpenRouter only; direct DeepSeek denied |
| Bot creation enforcement | Implemented | add_bot() and edit_bot() enforce AI access policy; trial locks provider/model |
| Runtime provider enforcement | Implemented | _route_for_enforcement and _get_system_provider_for_enforcement in ai_router.py |
| ToyyibPay top-up restriction | Implemented | Active trial, Free, expired trial and past_due cannot top up AI credits |
| Provider fallback disabled | Implemented | Cross-provider fallback (deepseek->google->openai) removed for Phase 2B-2A |
| Model-tier enforcement (Phase 2B-2B) | Implemented | Economy/Standard/Premium mapping in model_catalog.py; save-time and runtime enforcement; OpenAI/Gemini/Claude/Qwen/Mistral/xAI classified |
| GraphRAG/background AI cleanup (Phase 2B-2C) | Implemented | GraphRAG routes through ai_router; website knowledge no longer hardcodes Google; AI reports no longer use Gemini fallback; all AI entry points use central provider, subscription, model-tier and credit enforcement |
| Usage summary | Implemented | Usage data exposed in billing UI |
| Default subscription | Implemented | Created during company onboarding; new companies receive Free plan with 7-day trial (status=trialing); expired trials denied AI access |
| Subscription limit enforcement | Implemented | Guard layer with fail-closed fallback; missing subscriptions resolved to Free plan or denied |
| Feature flag enforcement | Implemented | Keys: single_website_scraping, batch_website_scraping, crm_lead_assignment, ai_generated_reports, ai_assisted_menu_generation |
| AI-credit summary | Verified complete | Included in the latest billing test work |
| AI-credit transactions | Verified complete | Included in the latest billing implementation |
| AI-credit usage charging | Implemented | Atomic repository/RPC flow exists; broader integration verification needed |
| ToyyibPay checkout | Verified complete | Latest billing work and focused tests completed |
| ToyyibPay callback | Verified complete | Callback parsing and processing covered by focused tests |
| Order status endpoint | Verified complete | Focused route tests exist |
| Duplicate callback protection | Verified complete | Idempotent callback behavior covered |
| Atomic top-up credit grant | Verified complete | RPC-based design and focused tests exist |
| Billing and top-up frontend | Verified complete | Latest frontend billing work completed and committed |
| Live production payment | Needs investigation | Requires controlled end-to-end production verification |

## Known Verification Evidence

Latest recorded full automated suite:

```text
1534 passed, 1 skipped, 143 subtests passed
```

- Focused workspace, Team, invitation, Google configuration, and tenant-scoping tests passed.
- Rate-limit tests verified normal-startup enforcement, same-IP blocking, independent IP and endpoint buckets, disabled mode, test-application isolation, and rejection before protected writes, invitation acceptance, excess password hashing, or external Google verification.
- Python compilation passed.
- Invitation-page and Team-page JavaScript syntax validation passed.
- Diff validation passed.
- Manual resend verification produced one POST request and one email.
- Manual cancellation verification returned HTTP 200, removed the invitation, changed pending invitations from 1 to 0, and restored available seats from 2 to 3.
- `/api/workspace` returned HTTP 200 after resend, cancellation, and Profile load.
- Live visual browser verification and external Google verification are still required.

## Cross-Cutting Items Requiring Investigation

- Live Supabase row-level security configuration
- Version-controlled definitions for all production RPC functions
- Exact current external integration readiness
- Production deployment configuration
- Full route-level tenant-isolation review
- Frontend automated test strategy
- Current removal readiness of legacy backup files
- Transactional company registration
- Transactional invitation acceptance
- Database-level protection against concurrent duplicate pending invitations
- Trusted reverse-proxy/client-IP handling for public rate-limit keys
- Redis or equivalent shared production limiter storage for multi-worker enforcement

## Document Maintenance

Update this file after:

- Completing a development phase
- Adding or removing a major feature
- Changing an integration
- Changing billing or database behavior
- Completing meaningful verification

Do not record temporary branch names, commit hashes, local paths, or working-tree status here.
## Phase 4E — Subscription Billing History and Customer Receipts

**Status:** Verified complete

- Order history listing with pagination and status filtering
- Order detail API with safe fields
- Printable HTML receipt with "Not a tax invoice" wording
- JSON receipt endpoint
- Billing history and AI-credit CSV exports
- Profile billing history UI with order reference, amount, dates, status badges
- Order detail modal with retry button
- Customer support guidance for manual-review states
- Data accuracy guarantees (amount from order, timestamps consistent, no reversal leakage)

## Phase 4F — Production Security, Tenant Scope and Plan Enforcement Audit

**Status:** Verified complete

- Data-scope matrix: company-scoped vs bot-scoped resources
- Billing/credit authorization: company_id resolved from JWT, client-supplied ignored
- Company-wide billing presentation with shared-credit explanation
- Plan-limit enforcement matrix with guards for all resource types
- Security hardening: authentication, webhook verification, UUID validation
- Reconciliation job safety checks
- Structured monitoring logs for billing lifecycle events
- Health check endpoint
- Phase 4F runbook

## Phase 4G — Admin and Support Operations

**Status:** Verified complete

- Authorization model documented (company owner/admin vs platform admin)
- Support search repositories and API
- Admin order listing with filters
- Admin reconciliation endpoint (idempotent, reuses canonical service)
- AI-credit support inspection
- Auditable credit adjustment RPC design
- Billing support runbook

## Phase 4H — Customer Receipts, Exports, and Usage Reporting

**Status:** Verified complete

- Printable HTML payment receipt
- JSON receipt endpoint
- Canonical receipt building helper
- Billing history CSV export with injection protection
- AI-credit activity CSV export
- AI-credit usage summary API
- Profile UI enhancements (receipt, export, summary cards)
- Email receipt: deferred (no approved email service)
- Migration 014: not required

## Phase 4I — Subscription Renewal, Grace Period, and Failed-Payment Recovery

**Status:** Implemented

## Phase 4J ? Billing Notifications and Customer Communication

**Status: Complete**

- In-app billing notifications with event-key deduplication
- Renewal reminders at 7/3/1-day thresholds and expiry day
- Grace-period started/ending notifications
- Payment confirmed and activation notifications
- AI-credit low/critical/depleted alerts
- Company-scoped notification API
- Notification generation job

## Phase 4K ? Advanced Billing and Usage Reporting

**Status: Complete**

- Monthly billing summaries and trends
- Plan-usage reporting against limits
- CSV exports of all reports
- Integer arithmetic, company isolation

## Phase 4M ? Production Launch Audit and Remediation

**Status: Complete**

- Rate limiting (Flask-Limiter)
- CORS hardening
- Hardcoded URL fix
- Development route isolation
- Auth/billing endpoint rate limits
- Full test suite: 1,084 pass

## Phase 4L - Platform-Admin Read-Only Backend and Frontend

**Status: Verified complete in staging; production blocked**

- Separate active `platform_admin_users` mapping required on every request;
  tenant owner/admin/member roles never grant platform access
- Nine GET-only endpoints for platform identity, operations overview, company directory/detail,
  subscription summary, current-period AI-credit/usage summary, and lazy
  read-only subscription-history, company users, and company chatbots
  inspection. The original five endpoints were verified in staging; the
  operations-overview, users/chatbots, and subscription-history extensions are
  application-only and locally tested unless separately staged later.
- Cross-tenant reads isolated in dedicated platform repositories with explicit
  safe projections and mandatory audit-before-response behavior
- Automated authorization, repository, route, and audit tests added
- Manual staging verification passed for all five endpoints and expected audit
  events, including metadata redaction and immediate revocation
- Separate read-only frontend implemented for platform identity, exact company
  counts, server-paginated company search, company billing/AI-credit detail, and
  lazy read-only subscription-history and company users/chatbots sections. A bounded application-only
  Platform Operations overview now adds one GET-only locally tested dashboard
  endpoint for company counts, latest-subscription status counts, latest-plan
  distribution, and at most 10 past-due/expired attention companies using
  `created_at DESC, id DESC` latest-subscription semantics.
- Frontend performs a fresh `/me` authorization check on every page entry,
  clears cross-tenant state on denial or unavailability, and never trusts tenant
  roles, cached users, JWT claims, local flags, or hidden navigation
- Tenant pages now use a shared top-right account menu for Profile, Support,
  and Logout. Support points to a static authenticated tenant help page with no
  support-submission backend. The optional Platform
  Administration menu item is discovered lazily through a live
  `/api/platform-admin/me` check and is not stored or placed in the tenant
  sidebar.
- Focused frontend source-contract tests cover endpoint restrictions, request
  cancellation, state clearing, safe rendering, accessibility, and responsive
  behavior
- Staging browser verification passed for the dashboard, company directory,
  company detail, read-only controls, tenant-app return path, and logout
- Post-verification revocation was confirmed: refresh showed Access Denied and
  no stale platform data remained visible
- Bootstrap mapping remains present and inactive after the browser verification
  revocation; no production deployment occurred and existing production gates
  remain open
- Phase 4 production-readiness package prepared with preflight/approval gates,
  deployment and rollback procedures, audit metadata/retention policy,
  monitoring, completed final staging rehearsal evidence, and emergency
  revocation runbook
- Migration 026 append-only trigger applied and verified in staging: postgres
  owner, SECURITY INVOKER, fixed pg_catalog search path, minimized function
  EXECUTE, enabled row-level UPDATE/DELETE rejection, and unchanged RLS/grants
- Rollback-only staging verification proved INSERT/SELECT success, stable
  UPDATE/DELETE rejection through service_role, temporary-row removal, and
  rollback of temporary mutation grants; the mapping remained inactive
- Final Phase 4 staging rehearsal completed successfully: inactive-state denial,
  time-bounded reactivation, dashboard/directory/detail and exact-count checks,
  approved audit INSERTs and metadata, and post-revocation state clearing passed
- The rehearsal ended with the mapping present and inactive; refresh showed
  Access Denied with no stale company, subscription, or AI-credit data, and no
  production SQL or deployment occurred
- Production remains blocked pending protected-company/bootstrap/executor
  approvals, exact archive configuration, formal audit-policy approval, backup
  restore evidence, monitoring activation, migration 026 production approval,
  and final go/no-go

## Platform Limitations

| Limitation | Status |
|---|---|
| Platform-admin controls | Original five-endpoint backend/frontend verified in staging; operations-overview, users/chatbots, and subscription-history extensions locally tested only; Phase 4 package prepared; mapping inactive; production approvals/deployment blocked |
| Automatic recurring billing | Deferred (ToyyibPay limitation) |
| Email/SMS delivery | Deferred (no provider) |
| Direct tenant support contact/tickets | Deferred (no approved support contact destination or support-submission backend) |
| PDF receipts | Open (HTML only) |
| Cross-company dashboard | Deferred |
