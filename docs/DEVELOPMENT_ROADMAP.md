# Development Roadmap

## Super Admin API Key Management

**Implemented locally.** The [replacement workflow](FEATURE_STATUS.md#super-admin-api-key-management) and migration 088 await review.

## Filter 2 bounded block review — 2026-11-12

**Implemented locally; owner review pending.** Four-second fail-open review and persisted per-message verdict exclusion use the existing agent_actions payload, with no migration or frontend change. Keep production in log mode. The [handoff](CONTENT_REVIEW_BLOCK_HANDOFF.md) records mocked checks, full-suite comparison, security-scan gap and the unfenced pre-verdict reader window.

## Platform-admin safety flags — 2026-11-12

**Implemented locally; review and rollout pending.** Super Admin can inspect metadata-only safety flags, category counts and seven-day Client warning levels. Filtering does not change the seven-day level calculation. No migration, automatic pause or operational write action is included. Focused mocked checks pass; full-suite evidence and remaining verification gaps are in the [handoff report](SAFETY_FLAGS_HANDOFF.md).

## GEO Analysis workspace — 2026-10-07

**Implemented locally; rollout pending.** The first paid-plan GEO workspace is built with
company-scoped storage, prompt-level evidence, native citations, real search-enabled provider
adapters and deterministic metrics. It is available to Essential, Advanced and Pro accounts
and appears after My bots in the workspace navigation. Migration 073, production provider
secrets and live API/browser verification are still required before release.

The workspace sidebar has since been unified across My bots, GEO Analysis, Team, Billing and
Plans. Paid GEO access now follows the canonical active plan code rather than requiring a newly
added JSON flag on an older paid-plan row. Migration 074 raises Pro from 2 to 4 channels; both
database migrations remain pending for the target environment. The runtime plan reader and
Publish screen now recover legacy Pro rows that still report 2, and the base plan seed cannot
restore the obsolete limit. Bot-scoped sidebars keep GEO Analysis in the workspace footer and
reserve the back-arrow icon for returning from a selected bot; workspace pages use the bot icon.

GEO now has a separate plan allowance rather than creating misleading chatbot usage records:
10 / 40 / 120 monthly provider checks on Essential / Advanced / Pro, with 2 / 3 / 4 prompts
per analysis respectively. All three paid plans can use the five live official collectors for ChatGPT Search, Gemini, Claude, DeepSeek and Perplexity. Non-callable consumer surfaces are not shown as analysis options.
Prompt and platform fan-out is reserved atomically before external calls. The initial plan caps are intentionally
small and should be recalibrated from real provider cost and retention data. After rollout,
validate score stability with repeated multilingual prompts and confirm that score movement
correlates with real brand-mention gains for Malaysian businesses.

On 2026-10-14, the scoring contract moved to `deterministic-v5`: 60% mention rate and 40%
mention-rank prominence. Rank uses an explicit numbered or bulleted result position first, then
tracked-entity order; a mention without comparative evidence has no rank. Results with fewer than
three completed platform checks are visibly marked insufficient, while up to five comparable
analyses feed a rolling mention rate and average rank. The workspace shows four concise action
pillars for every measured platform: website/landing-page quality, trusted-platform publishing,
genuine local landmarks and context, and crawler-facing technical fixes. Generated GEO UI now
uses parameterized English, Simplified Chinese and Bahasa Melayu messages, including content
inserted after page load. All HTML entry pages share the Omnexa SVG favicon and an Omnexa browser
title. Older stored analyses retain their historical methodology and remain readable.

## Cloudflare document graph repair — 2026-09-24

**Deployed and verified for scoped checks:** Fly v40 fixes structured graph output,
duplicate extraction and partial-graph display. 341 backend tests, 123 subtests,
4 browser tests and all3 live model probes passed. Original document was absent
at production recheck; security scan remains blocked by saved-login refresh.
See [repair evidence](KNOWLEDGE_GRAPH_FIX_20260924.md).

## Cloudflare plan models — 2026-09-23 (superseded 2026-10-03)

**Superseded by PR #21 (Fly v49):** every paid plan now uses OpenRouter models
(Essential GPT-6 Luna and Gemini 3.8 Flash, Advanced adds Claude Haiku 4.5, Pro
GPT-6.1 Sol, Claude Sonnet 5.5 and Gemini 3.1 Pro); only the 7-day trial stays on
Cloudflare Qwen3 30B. The Fly v37 lineup below is history.

Fly v37 exposed 1/2/3/3 models on Free/Essential/Advanced/Pro, with lower plans on
Cloudflare and Pro on OpenRouter GPT-5.5, Sonnet 4 and Gemini 3.8 Flash.

## Bot Analysis and Agent actions — 2026-09-23

The approved in-system Analysis interface, industry-aware reports, private exports,
durable action observations, website/Telegram tuition trials and scheduling code
are deployed in Flask v38 with report/trial/reminder execution disabled. The release
also closes the bot-ownership update gap and adds industry reports and Pro automation
gates while preserving v37's live Cloudflare/pricing files. Restaurant and clinic booking integrations, formal
enrollment and merchant payments remain outside this first release.

Release checks passed with six backend and one browser failure reproduced on the
preexisting v37 baseline; independent integration review found no blocking issue.
Automated security scanning is blocked
by authentication. Access to the actual Supabase project was restored on
2026-09-23; migrations 062–067 and the n8n private database account are complete.
The user deferred security login and chose to keep new execution flags off.
Migration 068's Pro-only matrix and 069's schema permission are verified. Original
n8n credentials were recovered and their TLS login verified; a database password
reset is unnecessary. Remaining gates are the security scan, automation-service
provisioning, monitoring and cloud runtime validation. Always-running Fly
configurations are prepared within the proposed incremental US$50/month envelope;
24/7 operation, actual resource use, backups/restores and alerts are not yet proven.
See [current delivery state](ANALYSIS_IMPLEMENTATION.md).

## Industry templates — 2026-09-22

The first document-to-industry flow is implemented locally: versioned restaurant,
clinic administration and tuition-centre rules; uncertain/general fallback;
merchant confirmation; explicit correction without re-upload; published-only
prompt integration. It reuses the current upload, persona billing and instructions
page. Local verification passed 4935 tests, 2303 subtests, 28 browser checks and
the isolated PostgreSQL migration check; 7 optional tests skipped. Production
migration 062 and Fly v36 deployment are complete. Actual reservations,
queue tickets, enrollment, reporting and dynamic tool authorization are separate
work, not capabilities granted by this template selection. See
[implementation and verification](INDUSTRY_TEMPLATES.md).

## Website staff replies — 2026-09-22

The missing share-link/widget return path is deployed on Fly v35: staff
compose/send, visitor polling, reload continuity, and paused customer follow-ups.
Migration 061 prevents concurrent first messages from creating duplicate open
sessions. Full tests and read-only production verification passed, with the
Codex Security sign-in blocker recorded. This completes the legacy website handoff reply
path without activating Phase B assignment controls. See
[workflow and evidence](WEB_STAFF_REPLIES.md).

## Human handoff Phase A/B — 2026-09-22

Waiting visibility is deployed on Fly v34. The persistent control API and
migration 060 are deployed, verified and deliberately disabled. Next connect
customer requests, queue UI, assignee-authorized replies and dispatch epochs to
the new control state, then verify the complete flow before enabling it.
See [release evidence and remaining work](HANDOFF_PHASE_AB_RELEASE.md).

## Prepaid subscription terms — 2026-10-19

Implemented locally for the combined Chatbot + GEO plans. Essential, Advanced,
and Pro now support 1-, 3-, 6-, and 12-month upfront purchases using the exact
approved pricing matrix. The checkout, persisted order, callback, reconciliation,
subscription paid-through period, monthly allowance window, authenticated Pricing
and Billing views, public landing page, and public plan metadata are term-aware.
Migration `data/079_prepaid_subscription_terms.sql` is intentionally not claimed
as deployed; apply and verify it before releasing this application code. A
controlled CHIP checkout/callback for each term remains required in the target
environment.

## CHIP payment replacement — 2026-09-15

**Deployed in CHIP LIVE mode on Fly release 20.**
The real RM39 subscription test and deployed Sentry reporting are verified.
Migrations 051/059 are applied; nine approved legacy bills/orders are retired
with payment history preserved. All 4,226 tests passed; three medium security
findings passed targeted fix verification, with two low policy findings retained.
Test payments grant no paid entitlements. [Rollout and evidence](CHIP_PAYMENT_GATEWAY.md).
The separate live key, unpaid live connection check, runtime configuration,
274 deployed file hashes, and billing health are verified. The probe and
abandoned test orders 27/29 were cancelled without charges or grants; unused
ToyyibPay runtime secrets are removed. The user requested live mode before the
deployed top-up test completed. Paid live processing and independent callback
delivery remain unverified; local top-up tests passed.
This supersedes earlier HitPay/ToyyibPay active-gateway descriptions below.


### Client document protection — 2026-09-14

Upload/privacy protections, authoritative R2 storage, and a verified-before-startup
migration are implemented. The user approved R2 billing and a bucket-only token;
the private APAC Standard bucket exists and four Fly secrets are deployed. Final
local checks passed: 359 tests, 108 subtests, 12 runtime-file compilation checks,
and diff checks. Fly v18 is live on the existing single Machine/volume; the marker
confirms 43 migrated files / 8,622,343 bytes. Runtime hashes, health, and synthetic
storage/media checks passed. Anonymous bucket access is denied, synthetic files
were removed, and final remote verification completed with exit 0. This storage
deployment is complete.

Fly `/media/` URLs remain anonymously shareable. Complete erasure, revocable
provider sharing, and database defense in depth remain separate work. Zone WAF
needs a user-controlled domain; R2 does not provide that edge protection. The
Codex Security scan is waived for this task. See the
[document protection review](CLIENT_DOCUMENT_PROTECTION.md) for exact evidence.

### All-channel replacement and Resolve-only handoff — 2026-09-14

The approved prototype is implemented for Telegram, Meta WhatsApp and WASender.
It covers new credentials/phone input, verified replacement, visible failures,
original conversation binding, truthful provider acceptance, Test Lab reset and
final-request Resolve. Migration 058 supersedes the Telegram-only SQL proposal.
Final security and deployment verification are in progress; deployment is already
authorized. Exclusive agent assignment/transfer and SLA scheduling remain separate
features. See [the customer-service guide](BOT_CUSTOMER_SERVICE_LOOP.md).

### Fly release and channel publishing — 2026-09-10

Public hosting, staff password login, dashboard rendering and three enabled
website bot pages are verified at `aibot-chatbot-my.fly.dev`, using paid
organization `personal` (aibot EMAIL). One Machine runs in Singapore with 41
hash-verified runtime files restored on its volume. The initial release passed
205 mocked tests plus 4 subtests and isolated Docker build/boot checks.

Exclusive Telegram ownership guards and migration 055 are deployed for bot 53.
Its callback is connected, the preserved queued update cleared, and the provider
reports no delivery error. The user confirmed a short Telegram test receives a
reply. Wasender setup is deferred until registration at the user's request;
Travel Bot 50 remains selected. Its expired application subscription and pending
renewal status also need resolution before connection. Other
companies require unique Telegram bots; Wasender/Meta require valid configured
sessions/phones. Google OAuth origin setup, background-job handover, original
PDF recovery and a reachable hosted Langflow runtime remain separate gaps.
The configuration-only security scan passed; the earlier seven-path source scan
remains incomplete despite its locally verified packaging fix.
The eight-path Telegram scan completed; its one low-severity legacy-data finding
does not match the verified live channel inventory.
See [release evidence and remaining checks](FLY_CHANNEL_READINESS.md).

### Tenant support 052 rollback

**On hold:** escalation-context/urgency/origin submission. The runtime targets the
pre-052 five-parameter RPC and column projections. Later support conversion,
replies, notifications and authorization remain in place. No database rollback
is required for the reported environment where 052 was never applied.

### Sentry error investigation — 2026-09-09

Server-side reporting and the inspect/reproduce/fix/verify workflow are
implemented locally. The intended Sentry project and private local DSN are
configured; synthetic event delivery and API readback are verified. Deployment
environment configuration and post-deployment observation remain pending.
See [Sentry](SENTRY.md).

### Client-data security review and repair — 2026-09-08

Local authentication, media, CRM input and error-disclosure repairs are implemented
with synthetic regression tests and independent review. Production release remains
pending comprehensive scan coverage, cumulative media quotas and target-environment
checks. Sentry API access is verified but the organization has no accessible projects.
The long source scan was skipped at user request on 2026-09-09; it is not a pass.
See [audit scope and evidence](SECURITY_AUDIT_2026-09-08.md). Existing Langflow
startup work is preserved; no live customer, payment or deployment mutation occurred.

### Guided client setup and channel publishing — 2026-09-07

**Local implementation complete; release verification pending.** The approved
full journey now guides creation, PDF readiness, instructions, testing and explicit
channel choice. Both sidebars keep account controls at the bottom and distinguish
the workspace from the selected bot. Website links preserve their key through
disconnect/reconnect and explain when the hosting address needs attention.

Focused synthetic tests and the first-client review are in
[CLIENT_JOURNEY_REVIEW.md](CLIENT_JOURNEY_REVIEW.md). The 10 September continuation established the permanent Fly origin and restored
volume availability; its scoped security evidence and remaining channel gaps are
in [the release record](FLY_CHANNEL_READINESS.md). The original journey review
made no production changes.

### Approved Admin and Super Admin replacement — 2026-09-07

**Shared Supabase activation completed.** Independent portals, role-based login destinations, individually assigned staff modules, approval records and existing billing/support operations are active for the requested accounts. Local mocked tests, PostgreSQL checks, completed security scan/remediation, live permission checks and both actual browser logins are recorded in [the rollout plan](PLATFORM_STAFF_PORTALS_ROLLOUT.md). Public hosting and both staff password logins were verified on 10 September at
[the Fly login page](https://aibot-chatbot-my.fly.dev/login.html); see
[current deployment evidence](FLY_CHANNEL_READINESS.md).

The Super Admin overview chart enhancement uses the existing plan/status aggregates
and separate payment queues. Status links open existing filtered subscriptions;
current-state counts never imply revenue history or growth. The expanded 13-test
browser suite passes, with live data also rendered by the local application.

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
> | 4L | Platform-admin controls | **Original scope staging verified; later extensions have mixed local and prototype/shared-testing evidence; production blocked** |
> | 4M | Production launch audit and remediation | Complete |
> | 4N | Knowledge Readme compilation & Pop-out viewer | Complete |
> | 4O | Supporting PDF Relevance Validation | Complete for shared-testing/prototype |
>
> ---

### Bot management reliability and UI refresh - 2026-08-11

The bot management workspace now follows the Aveon Control Room v2 Stitch design system with a dense responsive operations layout, search and status filtering, accessible loading/empty/error states, and non-blocking chatbot-limit guidance. The previously disconnected archived-bot frontend is reconnected to authenticated, tenant-scoped backend list/restore/permanent-delete routes. Focused route and frontend regression coverage is current; live Supabase schema verification remains environment-specific, and permanent deletion requires Migration 022 in the target environment.

### Phase 4O - Supporting PDF Relevance Validation

**Status:** Complete for shared-testing/prototype

Supporting PDF Relevance Validation is implemented and manually verified in the
current shared-testing/prototype Supabase environment. When no Primary PDF
exists, the existing PDF upload path still performs normal Primary ingestion
and makes the PDF active. When a Primary PDF already exists, an additional PDF
is first stored as a temporary candidate, extracted locally, semantically
validated against the current Primary, and returned as PASS/FAIL before normal
ingestion is allowed. A PASS requires explicit user confirmation; confirmed
PDFs run through the existing ingestion pipeline as enabled Supporting
knowledge, skip persona derivation, and do not replace the active Primary. A
FAIL or unconfirmed candidate creates no normal `knowledge_files`,
`knowledge_chunks`, GraphRAG, persona, README, or Supporting source.

The relevance engine is `semantic_hybrid_v2` with default
`PDF_SUPPORTING_RELEVANCE_THRESHOLD=0.65`, configurable by environment. It uses
`gemini-embedding-2` at 768 dimensions and validates up to 48 candidate chunks
and 60000 candidate characters. Exact duplicates are blocked separately. The
0.65 value is an initial calibrated application threshold, not probability or
scientific certainty.

Migration 045 adds the candidate table, candidate lifecycle/recovery linkage,
`original_file_name`, indexes, foreign keys, RLS, and access controls.
Migration 046 hardens Supporting PDF candidate-table `service_role` grants to
only SELECT, INSERT, UPDATE, and DELETE. Shared-testing/prototype manual
verification confirmed the Supporting PDF flow, RAG/Test Bot retrieval from
Supporting knowledge, and human-facing UI display of readable filenames instead
of internal UUID-backed storage names.

Known limits remain: the calibration sample is small; historical chunks do not
store per-row embedding-model metadata; validation uses bounded per-chunk
candidate embedding requests and has a small provider cost; candidate cleanup is
opportunistic; and local Playwright coverage is blocked where Chromium is
missing. This does not claim future staging or real production readiness.

### Knowledge Workspace onboarding hardening - 2026-08-26

Website knowledge now requires an enabled active Primary PDF. The requirement
is enforced in both the Knowledge Workspace frontend and the backend website
creation/scraping/ingestion routes. Missing Primary state fails before website
scraping, AI refinement, quota-consuming storage, or website ingestion work;
Supporting PDFs, disabled PDFs, inactive PDFs, and non-PDF active sources do
not satisfy the rule. Existing website sources are not deleted or modified.

The batch website route now propagates authenticated `company_id` into
`scrape_website_urls_batch`, so storage-quota enforcement is not bypassed.
Long-running knowledge operations now show an indeterminate processing panel
with elapsed time, duplicate actions are blocked while processing, and standard
`beforeunload` protection is active only during in-flight processing. Supporting
PDF confirmation remains explicit.

Manual happy-path verification covered the no-Primary website lock, Primary PDF
upload progress, website enablement after Primary creation, website processing,
and website save as Supporting while the Primary remained active. Automated
regression evidence for this hardening pass: broader Knowledge Workspace slice
reported 223 passed with 7 existing warnings, and `git diff --check` passed.
This update does not claim multi-page website ingestion quality/provenance
improvements, staging deployment, or real production readiness.

### AI-credit activity accounting hardening - 2026-08-26

Refine Answers now records explicit billed operation metadata for question
generation and ambiguity verification, and Recent AI Credit Activity displays
those debit rows as "Refine Answers" with model, provider, token counts, MYR
charge, and balance-after details. Several other customer-facing generative
operations no longer reuse the generic Knowledge Training label: Test Scenario
Generation, Persona Derivation, Profile / Knowledge Validation, Website
Knowledge Training, and Knowledge Graph Training now have distinct operation
types and billing-friendly labels.

Central AI-credit accounting now fails closed when enforcement is enabled and a
successful customer-billed provider response cannot become a usage-debit
transaction because usage logging, provider-cost lookup, subscription/balance
state, or usage lookup is unavailable. The trial DeepSeek routing/pricing model
mismatch was corrected to the priced/catalogued `deepseek-v4-flash` path.
Embeddings remain non-customer-billed by current policy and do not appear in
Recent AI Credit Activity. Manual verification passed for Knowledge Workspace
Refine Answers; broader operation-label behavior is covered by automated
accounting/source-contract tests. This note does not claim live verification for
every operation type, staging deployment, or production deployment.
### Insights & Actions workspace - 2026-08-27

The bot-scoped CRM and Reports experiences are now one role-aware control-room workspace at `crm.html`. Its default Today view derives a plain-language action brief only from existing lead and analytics responses; Leads keeps the canonical five-stage pipeline, filtering, inline updates, notes and conversation links; Performance keeps the 7-day chart, AI report generator and lazy PDF export; AI Signals remains owner/admin-only. `reports.html` is a compatibility redirect to the Performance view, preserving `bot_id`. Focused static and mocked desktop/mobile browser coverage is current; live backend, external report-model and live PDF verification remain outstanding.

### Knowledge follow-up and CRM stage automation - 2026-08-27

Added a guarded automation seam for two tenant workflows: successful PDF
indexing emits an idempotent document-review follow-up event, and owner/admin
requests can apply a compare-and-set CRM stage transition with an audit event.
`GET /api/automation/events` exposes tenant-scoped monitoring data. This is a
partial implementation: knowledge events await human review; no automatic
review-completion consumer is implemented. Langflow advice executes during the
request. The local Windows runtime is reachable; cloud runtime deployment is
separate work. The `automation_events` table is defined in Migration
049 and is applied/live-verified in the active Supabase project. Langflow integration is intentionally
opt-in and server-side; no tenant-facing editor is enabled by this change.
The 2026-09-08 reliability update adds a bounded Langflow health probe,
request-identity validation, synchronous-response enforcement, and consultation
metadata on accepted CRM events. Local startup and recovery details are in
`langflow/README.md`; local checks do not establish hosted deployment health.

### HitPay hosted subscription checkout - 2026-09-04

The existing company-scoped subscription checkout now has a dormant,
server-selected HitPay path while ToyyibPay remains the default and historical
callback handler. HitPay uses one platform merchant account and hosted checkout;
the browser cannot select a tenant, gateway, or activation outcome. Signed event
webhooks are verified over the exact raw body, then payment state is re-fetched
from HitPay and matched to the stored provider ID, internal reference, MYR
currency, and exact amount before the existing idempotent subscription
activation and included-credit flow runs.

The current phase covers one-time initial purchases and manual monthly renewals.
Ambiguous create outcomes are searched by internal reference before any retry,
missed events are recovered by the existing reconciliation job, stale terminal
events cannot downgrade paid or credited orders, and `/api/billing/health`
reports degraded HitPay configuration or missing recent reconciliation evidence
without blocking tenant workflows. `data/051_unique_subscription_gateway_order.sql`
is an unapplied additive proposal with a duplicate preflight. Migration 049 is
unrelated and was not changed or applied. Remaining gates are merchant-dashboard
configuration, sandbox checkout/event evidence, a separately approved low-value
FPX/DuitNow production pilot, Migration 051 approval/application, security scan,
and recurring-card validation before any automatic renewal.

### Phase 4L update - Platform-admin controls

Current Superadmin prototype roadmap status after this milestone:

1. Completed current milestone: Phase 1 foundation, Phase 1.5 RLS/security
   foundation, Phase 2 support operations, Phase 3 tenant communication
   baseline, Phase 6 monitoring/visualization dashboard, Phase 5 Tenant /
   Company Administration, bounded Platform Admin Management, and the current
   Phase 7 read-only Billing / Subscription Oversight milestone.
2. Next: move back to broader product or deployment priorities rather than
   starting another Superadmin feature phase. Future proper environment
   deployment is separate work. Financial mutation workflows remain deferred
   and require a separately approved future scope; they are not part of the
   completed Phase 7 read-only milestone.
3. Later: broader Phase 4 Platform Admin User Management expansion. A bounded
   platform-admin mapping-management surface already exists; the broader
   lifecycle expansion remains intentionally deferred.

This roadmap status reflects repository/local and recorded prototype/shared-testing
evidence only where stated. The current Supabase project is
intentionally used as the prototype/shared-testing environment; Supabase labels
its main branch as `PRODUCTION`, but this project is not the future real
production environment. Future staging and future real production are not
verified or deployed for the current Superadmin milestone.

The current Superadmin prototype milestone is runtime-verified complete. Final
Superadmin prototype runtime verification is now represented by the
consolidated hardening verification pass in the prototype/shared-testing
boundary. Focused evidence recorded 310 passed tests and 779 subtests; the
broader focused platform-admin suite recorded 431 passed tests and 991
subtests. That verification covered atomic support-case creation, bounded
support history pagination, pagination regression repairs, platform-admin
recent-activity batching, human-readable assignee identities, inactive
historical assignee safety, and the monitoring-depth audit conclusion that
current Phase 6 is sufficient for prototype/shared-testing.

The initial read-only backend is implemented with a separate database-backed
platform-admin allowlist, per-request fail-closed authorization, dedicated
cross-tenant repositories, a twelve GET-route investigation inventory, and
audit-before-response enforcement. Tenant roles and JWT claims do not grant platform access. The
later users/chatbots company-inspection endpoints and Platform Operations
overview endpoint, plus the subscription-history and AI-credit transaction-history
investigation endpoints, Audit Logs viewer, and billing-order history endpoint are
no longer described with one blanket evidence level: some remain
local/application-tested only, while specific Phase 5, Phase 6, Phase 7, and
later hardening paths have prototype/shared-testing runtime verification where
documented in their respective sections. The overview
uses latest-subscription rows per company ordered by `created_at DESC, id DESC`;
Operational Alerts Phase 1 extends the existing dashboard and overview response
only, deriving typed read-only subscription past-due/expired alerts from the
existing attention-company data without adding a route or page.
The older Phase 2 alert design contract remains historical guidance for
unimplemented alert concepts; Phase 6 later implements a bounded set of
deterministic aggregate alerts while AI low-balance alerts, generic background
job monitoring, provider-cost monitoring, exports, and remediation
controls remain deferred.

In the current local implementation, localhost manual verification recorded on 2026-08-03
passed for the complete twelve-route read-only investigation stack: dashboard, operational
alerts, company directory/detail, subscription summary/history, AI-credit usage
and transactions, billing orders, users, chatbots, Support Workspace, Audit Logs,
billing-order audit filters, and local revocation with Access Denied and stale
platform-data clearing. This is local evidence only. The original five
platform-admin endpoints remain the only endpoint set recorded as staging
verified; later extensions have mixed evidence, including local-only evidence
for some paths and prototype/shared-testing runtime verification for the
specific Phase 5, Phase 6, Phase 7, Migration 043, and Migration 044 paths
documented below. Unless explicitly stated otherwise, those later extensions
are not staging verified and are not production deployed. Operational Alerts added no endpoint or page, and the billing-order
audit-filter fix added no route or backend behavior change.
The complete platform-admin surface additionally includes separately approved
bounded support-case, platform-admin user-management, and company lifecycle
mutation routes; those later mutation routes are not staging verified.
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
Platform-admin User Management Phase 4 is implemented locally with a bounded
directory/detail surface, add-existing-user workflow, and activate/deactivate
controls. Migration 034 is applied and structurally verified only in the
approved main shared-testing Supabase with fake/team data. Company 29 is
explicitly registered as the protected internal company for main shared-testing
only; it is not a staging or production protected-company designation and is
not hardcoded into the application. Shared testing currently has only one
active user in company 29, user 32, and that user already has the sole
platform-admin mapping, so the successful create-mapping shared-testing E2E
remains pending until a second approved active fake/team user exists. Migration
035 is applied and verified only in the approved main shared-testing Supabase
with fake/team data; it corrected only the Phase 4 RPC audit endpoint metadata,
preserved RPC ownership/security/EXECUTE posture, did not create mappings, did
not create Phase 4 mutation audit events merely by application, and did not
alter existing audit rows. No staging verification or production readiness is
claimed.
Migration 044 (`data/044_platform_admin_user_recent_activity_batch.sql`) is
applied and runtime verified in prototype/shared-testing only. It eliminates
the platform-admin directory recent-activity N+1 pattern: before, the
directory used one mapping query, one users query, and N audit queries; now it
uses one mapping query, one users identity batch query, and one
`get_latest_platform_admin_activity` RPC. The
`recent_platform_admin_activity_at` field means latest
`platform_admin_audit_events.created_at` for that platform-admin mapping, or
explicit null when no audit history exists. It is not last login, user
activity, mapping `updated_at`, or account modification time.
Platform-admin Tenant and Company Administration Phase 5 is implemented and
verified for the current milestone in the approved main shared-testing Supabase
with fake/team data. It includes the global company directory, Company Detail
investigation, company users and chatbot/configuration inspection, current
subscription context, subscription history, AI-credit usage and transaction
history, billing-order history, controlled suspend/restore, protected
internal-company safeguard, centralized inactive-company operational
enforcement, Company Detail support-history integration, company-filtered
Support Workspace navigation, and company-related Platform Admin audit
navigation. Migration 036 is applied and verified only in the approved main
shared-testing Supabase with fake/team data: `companies.status` is constrained
to non-null `active`/`inactive`, companies table privileges were tightened to
no browser-role direct access and service_role `SELECT`, `INSERT`, and
`UPDATE` only, and the suspend/restore RPCs remain service-role-only
`SECURITY INVOKER` functions with `search_path=pg_catalog`.
Shared-testing lifecycle evidence includes the earlier company 23
suspend/restore cleanup with audit events 355 and 356, plus controlled runtime
verification on approved fake/team company 34, `Autobot Company`, chatbot 52.
Company 34 was suspended and restored twice and left active: audit events
527/538 covered the representative runtime matrix, and audit events 541/542
covered the final targeted `/api/chat/test` repair check. Representative live
checks verified chatbot mutation, knowledge mutation, `POST /upload-pdf`,
Telegram config mutation, and `/api/chat/test` reject suspended companies with
`403 company_suspended` while preserving intended Platform Admin reads, tenant
support/history reads, and safe knowledge graph/README reads. The final
test-chat check confirmed no provider execution, no AI usage, no AI-credit
impact, and unchanged chatbot runtime/configuration. Protected company 29
rejected suspend with `protected_company` and remained active. CRM mutation was
not exercised live because company 34 had no suitable CRM lead and no risky
conversation/customer data was manufactured; local automated CRM enforcement
coverage exists. Phase 5 does not provide tenant impersonation, arbitrary
tenant data access, raw tenant messages, AI prompts/responses, provider
payloads, API credentials, payment secrets, unrestricted configuration
inspection, financial mutations, true tenant application audit history, Phase 4
account-management expansion, duplicate Phase 6 monitoring, or Phase 7
financial mutation controls. No staging verification or production readiness
is claimed.
Platform-admin Platform Monitoring Phase 6 is implemented locally as a
read-only extension of `GET /api/platform-admin/overview`; no new
platform-admin mutation routes were added.
The overview now includes platform summary, support operations, messaging and
integration health, billing attention, AI usage and credits, and
platform-admin activity aggregates, plus deterministic aggregate alerts for
support backlog, pending/reconciliation-required billing orders, depleted
AI-credit balances, retry backlog, and integration channel attention. Existing
subscription alerts remain. Read-only inspection in the approved main
shared-testing Supabase with fake/team data confirmed all required monitoring
tables and fields exist and current index coverage is sufficient for the first
implementation. The original PostgREST aggregate implementation failed in
shared testing because REST aggregate select syntax such as
`status,count:id.count()` returned HTTP 400, so Migration 037 was introduced
and verified only in the approved main shared-testing Supabase with fake/team
data. Migration 037 adds one bounded read-only
`public.get_platform_admin_monitoring_overview()` RPC, executable only by
service_role, with `SECURITY INVOKER`, `search_path=pg_catalog`, no writes,
no dynamic SQL, no RLS/table-privilege weakening, and platform-admin activity
filtered to current approved audit actions and resource types. Existing
company/subscription overview reads remain separate from the monitoring RPC.
Runtime verification against the approved main shared-testing Supabase plus
localhost frontend/API returned 200 for `/api/platform-admin/me`, the
monitoring RPC, and `/api/platform-admin/overview`; the Platform Operations
dashboard rendered and the Temporarily Unavailable state disappeared.
The current milestone also verifies the local repository/source tests and the
full Platform Admin browser suite. The dashboard is intentionally a concise
operations summary rather than a full analytics explorer; detailed
investigation remains on the Companies, Company Detail, Support, Billing, and
Audit Logs pages. It preserves safe aggregate visibility into company counts,
active users, support workload/status, operational alerts, messaging
delivery/channel health, retry backlog, AI request/token activity, depleted
AI-credit balance signals, billing/order attention, companies requiring
attention, and aggregate platform-admin activity. The Superadmin UI polish
also makes Dashboard, Companies, Company Detail, Support, Billing, Audit Logs,
and Platform Admin Management visually consistent with shared page hierarchy,
cards/panels/tables, clearer filters, mobile card alternatives, responsive
behavior, and reduced dashboard information density. This is not staging
verification and does not establish production readiness. Unsupported
aggregate values fail closed.
The final monitoring-depth audit concluded that this Phase 6 coverage is
sufficient for the current prototype/shared-testing milestone. Deeper
monitoring/observability, durable background job/run monitoring, formal
SLA/SLO/alert definitions, recent messaging-failure trend depth, provider/model
AI failure depth, centralized structured logs/metrics, staging verification,
and production deployment verification remain deferred production or optional
hardening work, not current prototype defects.
Platform-admin Billing & Subscription Oversight Phase 7 is implemented for the
current read-only milestone as a platform-admin Billing & Subscriptions surface.
Migration 038 is applied and verified only in the approved main shared-testing
Supabase with fake/team data. No additional Phase 7 billing migration beyond
Migration 038 was required; Migration 043 belongs to the later atomic
support-case creation hardening. Migration 038 adds `public.get_platform_admin_billing_overview()`,
`public.get_platform_admin_billing_companies(integer, integer, text, text,
boolean)`, and updates `public.get_platform_admin_monitoring_overview()` so
Phase 7 read actions and resource types are counted in Platform-admin Activity.
All three functions are owned by `postgres`, are `SECURITY INVOKER`, use
`search_path=pg_catalog`, and are executable only by `service_role`. Local
runtime verification returned 200 for `/api/platform-admin/me`,
`/api/platform-admin/overview`, `/api/platform-admin/billing/overview`, and
`/api/platform-admin/billing/companies?limit=25&offset=0`; the Platform Billing
& Subscriptions frontend rendered successfully. The directory includes
companies without subscriptions using the null-subscription contract, applies
status/plan/attention filters in PostgreSQL, counts before pagination, orders
by `company_id ASC`, and applies `LIMIT/OFFSET` inside PostgreSQL. This is not
staging verification and does not establish production readiness.
Subscription history lists persisted `company_subscriptions` records and is not
an event-sourced status-transition timeline. Billing-order history lists mutable
`company_subscription_orders` records for company-scoped investigation, displays
`amount_sen` as integer sen as stored, and does not return or infer currency.
The final frontend hardening keeps desktop tables, adds mobile Billing overview
and Tenant Billing Directory cards below 767px, adds explicit accessible labels
for Subscription status, Plan code, and Attention filters, preserves safe text
rendering for hostile Billing values, and verifies mobile View Company
navigation to `platform-admin-company.html?company_id=<id>`. Latest local
evidence includes 54 frontend source tests with 14 subtests, a 5-test Billing
browser group, and a 70-test full Platform Admin browser suite. A broader Phase
7 regression scope previously passed with 153 tests and 271 subtests. The
latest responsive/accessibility hardening is local/browser evidence only and is
not staging or production verification.
Phase 6 implements only the approved aggregate alerts for support backlog,
pending and reconciliation-required billing orders, depleted AI-credit
balances, retry backlog, and integration channel attention. AI low-balance
alerts remain deferred because no threshold is approved; generic background
job monitoring remains deferred because no durable telemetry exists; provider-
cost monitoring, inactive-company and no-current-chatbot alert variants,
payment reconciliation actions, checkout recovery, retry payment, manual
crediting, subscription activation, plan changes, no-subscription counting,
global activity drilldowns, charts, exports, audit export, audit editing/
deletion, and overview remediation/write controls remain deferred.
Phase 7 keeps manual AI-credit adjustment, payment reconciliation mutation,
refund, subscription correction/override, manual plan change, direct balance
editing, payment retry mutation, manual credit reversal, and billing
impersonation/remediation controls deferred.

The separate read-only frontend is also implemented with a dedicated platform
shell, a fresh `/me` authorization gate on every page, an allowlisted
GET/POST/PATCH client, in-memory request cancellation/state clearing, the Platform Operations
overview, the server-paginated company directory, safe company billing/AI-credit
detail views, typed subscription operational alerts, and lazy read-only subscription-history, AI-credit transaction-history,
billing-order history, and company users/chatbots sections. A later bounded frontend-only platform-admin
Support Workspace adds tenant investigation with controlled internal case
operations. It reuses the existing
operations overview and company directory APIs, highlights attention companies,
and links into the existing company detail investigation page.
Support Cases Phase 1 is implemented for internal platform-admin use and is
verified in the main shared testing Supabase with fake/team data; this is not
staging or production verification. The feature adds bounded internal case create/list/detail,
redacted notes, status/priority updates, append-only case events, and audited
writes. It is separate from tenant `support.html` and does not add customer
messaging, impersonation, billing actions, exports, charts, or production use
in Phase 2.
Platform-admin Support Case Operations Phase 2 is implemented and verified only
in the main shared testing Supabase with fake/team data. It adds
assignment/reassignment/unassignment to active platform-admin mappings,
explicit status transitions, priority updates, internal-note creation, and an
ordered activity timeline. Migration 032 executed successfully in main
shared-testing only; fake/team verification covered least-privilege grants,
RLS/policies, service-role-only RPC execution, assignment/status/priority/note
mutations, no-op and invalid-transition rejection without extra event/audit
rows, and close/reopen `closed_at` behavior. This is not staging or production
verification.
Current support hardening is complete for prototype/shared-testing. Migration
043 (`data/043_atomic_platform_support_case_creation.sql`) transactionally
creates the `platform_support_cases` row, initial
`platform_support_case_events` row, and `platform_admin_audit_events` create
audit through `public.create_platform_support_case(...)`; the application
service does not insert a duplicate create audit. Support-case detail history
uses bounded `event_limit`/`event_offset` pagination with default 25 and
maximum 100. Tenant-visible replies use bounded `limit`/`offset` pagination
with default 25 and maximum 100. Reply notification lookup is restricted to
reply IDs on the returned page. Frontend Load More appends events using `id`,
replies using `reply_id`, and notifications using `notification_id`.
Support-case and reply-list not-found reads return the intended 404 instead of
an audit-validation 503. Assignee display now uses safe `user_full_name` and
`user_email` fields while assignment continues to submit
`platform_admin_users.id` mapping IDs; inactive historical current assignees
remain visible with a safe fallback but cannot be selected as new assignments.
Platform-admin Tenant Communication Phase 3 and Migration 033 are verified only
in the main shared-testing Supabase with fake/team data. It adds tenant-visible reply creation/listing for converted
support cases, tenant request history/detail with public replies, safe
`tenant_reply_created` activity, safe reply audit metadata, and a pending
`in_app` support notification outbox. This is not staging verification and does
not establish production readiness. Existing billing
notification and email helpers were not reused for support delivery, and
attachments are deferred because the available media attachment subsystem is a
public bot-media mechanism rather than private support storage.
SQL execution requires project/ref/environment preflight evidence recorded in
the platform-admin access lifecycle. Future SQL is limited to confirmed
local/dev, the approved main shared-testing environment with fake/team data, or
approved staging targets. Production remains blocked.
Tenant support submission is governed by
`docs/TENANT_SUPPORT_SUBMISSION_CONTRACT.md`. The backend endpoint is
implemented locally and the bounded frontend form is implemented locally.
Migration 030 is applied and verified only in the main shared testing Supabase
with fake/team data; local browser/API E2E verification passed with fake data.
This is not staging verification or production readiness, and the migration
does not modify the verified platform-admin support-case tables.
The read-only platform-admin tenant-support intake viewer is implemented locally
under `docs/PLATFORM_ADMIN_TENANT_SUPPORT_INTAKE_VIEWER_CONTRACT.md` with two
GET-only routes and a separate Support Workspace section. No SQL was required;
Migration 030 remains verified only in the main shared testing Supabase with
fake/team data. This is not staging verification or production readiness.
Tenant Support Intake Review/Conversion is implemented locally under
`docs/PLATFORM_ADMIN_TENANT_SUPPORT_CONVERSION_CONTRACT.md` and verified only
in the main shared testing Supabase with fake/team data. Migration 031 was
applied there and browser/API E2E passed locally: request 1 was reviewed then
converted, creating internal case 2 once. This is not staging verification or
production readiness, and production remains blocked. RLS/EXECUTE, audit
metadata, RPC security, and the mapping baseline remained safe.
Customer contact, SLA, escalation automation, analytics, bulk actions, and
other future concepts remain deferred
under `docs/PLATFORM_ADMIN_SUPPORT_WORKFLOW_CONTRACT.md`. The ordinary
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
Authenticated tenant pages now use a shared sidebar account menu below Billing
for Profile, Support, and Logout. Support now includes the local backend
submission endpoint and a bounded frontend request form plus local request
history/detail with tenant-visible replies. Migration 030 and local browser/API
E2E verification are recorded only in the main shared testing Supabase with
fake/team data; Phase 3 and Migration 033 are verified only in the main
shared-testing Supabase with fake/team data and are not staging verification or
production readiness. Active platform admins can discover a Platform
Administration link only after a lazy live `/api/platform-admin/me` check. This
menu visibility does not replace the platform page's fresh authorization gate.

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
- Automatic and manual CRM flows reuse only open leads. Terminal leads (`won`/`lost`, with the legacy `closed` alias normalized at the API boundary) remain historical, and structured unique-conflict recovery reloads the concurrently created open lead.
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

- Static authenticated tenant Support page (`support.html`) added as a bounded frontend consistency improvement. It uses the ordinary tenant sidebar and shared account menu, requires login through the existing frontend auth helper, renders account display text safely from session storage, and links to existing local tenant pages.
- The shared tenant account menu now restores Support as a working destination while keeping Profile, Logout, and lazy live Platform Administration discovery behavior unchanged. Tenant support submission is implemented locally through the bounded endpoint/form contract; migration 030, database/browser E2E verification, messaging, email, and production use remain pending or blocked.
- Public landing-page pricing was aligned with the authoritative subscription plan catalogue used by authenticated Billing. The landing page now renders published plan values from a tested duplicate frontend catalogue module, removes unsupported support-level claims, and keeps logged-out/register plus logged-in/billing CTA behavior covered by local tests. The duplicate module must be updated whenever plan migrations, runtime plan rows, or commercial values change; a public-safe plan catalogue endpoint remains a possible later cleanup. Free stores the economy tier internally but is presented as DeepSeek Only because active trial provider access is direct DeepSeek only. The Pro public description uses neutral application copy because the current runtime database row still contains legacy example wording; correcting that row remains a separate reviewed data-migration decision.

### Tenant sidebar account-menu integration - 2026-08-26

The top-right authenticated tenant account control moved under Billing in the
left sidebar. Shared tenant sidebar pages inherit the placement globally through
the shared sidebar/account component, and `bots.html` keeps its custom rail but
uses the same account-menu pattern. Expanded sidebars render Profile, Support,
Platform Administration when live-authorized, and Logout as an in-flow submenu
aligned with the native sidebar visual hierarchy; collapsed sidebars keep a
compact flyout, and the Bots mobile drawer preserves account access. Safe text
rendering, logout behavior, outside-click/Escape close, lazy live
`/api/platform-admin/me` Platform Administration discovery, and single
account-menu rendering are preserved. Shadow DOM icon-load ordering was fixed
so account action Lucide icons render reliably.

Manual desktop verification passed for Bots and shared-sidebar pages, including
submenu alignment, Profile/Support/Logout icons, no top-right duplicate, and
account placement below Billing. Automated static/frontend regression passed;
local Playwright runtime remains pending where Chromium is unavailable.

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
