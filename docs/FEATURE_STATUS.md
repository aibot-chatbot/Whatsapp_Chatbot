# Feature Status

## WhatChimp WhatsApp channel — 2026-10-14

**Partially implemented; LIVE since 2026-10-15 as Fly v69 (`feat/whatchimp-channel`, on top of
release d3d71a2); migration 079 is applied in production.** A business that already runs its WhatsApp number on
WhatChimp (a Cloud API platform) connects it from the Publish page in three steps: paste the
WhatChimp API key, tap the number (listed from WhatChimp's `/user/myInfo`, so no ID is typed),
paste the generated link into WhatChimp. `/connect` re-checks that the key owns the number
before the row is activated through `activate_verified_channel`, so WhatChimp counts toward the
company's shared channel slots. AI replies, real tappable reply buttons, media attachments,
staff replies, handoff pause, booking capture and dashboard health all treat `whatchimp` like
the other WhatsApp channels. The API key is never returned to the browser or logged.

Not done: the inbound parser reads the WhatsApp Cloud API envelope and is **unconfirmed
against a real WhatChimp delivery** (an unreadable delivery logs only its field names);
broadcasts do not offer WhatChimp (Cloud API numbers need approved templates outside the
24-hour window); failed sends are saved as failed but no retry worker re-sends them; platform
admin monitoring does not list WhatChimp.

## Sales conversation skill — 2026-10-09

**Implemented locally on `feat/sales-conversation-skill` (from live release 5561369); not
deployed, and migration 077 has not been applied.** All plans. Every reply prompt now carries a
four-step sales conversation (Understand → Recommend → Confirm → Close), replies in the
customer's language, and replaces the fixed "not in the provided company materials" sentence
with an honest, varied "the team will need to confirm" reply. Inventing facts is still
forbidden. Chat history in the prompt grows from 6 to 10 messages.

The model keeps a per-conversation customer needs card (goal, who it is for, budget, timing,
quantity, preferences, worries, stage) by ending a reply with a hidden `<<NEEDS {...}>>` line,
parsed by the same scanner as `<<BOOKING>>`. `needs_card_service.py` strips it from every reply,
keeps only allow-listed short text, ignores a note the customer typed, writes
`conversations.customer_needs` scoped by conversation and chatbot, and re-checks the card
before rendering it into the next prompt as notes, not instructions. No extra model call is
made. The stage only advises the model: an actual booking still needs the customer's explicit
confirmation, the `<<BOOKING>>` line and the server's seat check. Until 077 is applied, cards
are not stored (each failed write is logged) and replies are unaffected.

Not done: knowledge search still uses only the latest message (follow-ups such as "how much is
that one?" can miss the right chunk); greetings still get the free fixed menu; the needs card
is not yet shown to staff in the inbox; `needs_card_service.stage_guidance` is left for the
owner's own stage rules.

## GEO Analysis workspace — 2026-10-07

**Implemented locally; not deployed, and migration 073 has not been applied.** Essential,
Advanced and Pro workspaces now include a company-scoped GEO Analysis page between My bots
and Team. It runs prompts against direct search-enabled OpenAI, Gemini, Anthropic Claude,
DeepSeek and Perplexity APIs
adapters, preserves each raw execution and native citation, and reports a documented
deterministic score instead of accepting an LLM-generated score.

Follow-up on 2026-10-07: all five workspace entry pages now render the same shared sidebar.
GEO access is resolved from the canonical active subscription plan code, so an existing
Essential, Advanced or Pro account is not incorrectly locked merely because its plan JSON
predates the GEO feature flag. Migration 074 raises the Pro channel limit from 2 to 4; it is
prepared locally and has not been applied to a live database. Until rollout, the plan repository
and Publish screen recover a legacy Pro row that still reports 2, while the base seed now
preserves 4 on idempotent reruns. Workspace pages use a bot icon for My bots; bot-scoped pages
keep the back arrow and place GEO Analysis with the workspace links in the sidebar footer.

The Peec-inspired, Omnexa-native workspace now exposes plan usage, platform comparisons,
a prompt-by-platform evidence matrix and deterministic evidence-linked findings. Essential is
limited to 10 provider checks/month and 2 prompts/analysis; Advanced to 40 checks/month and
3 prompts/analysis; Pro to 120 checks/month and 4 prompts/analysis. All three paid plans can use
ChatGPT Search, Gemini, Claude, DeepSeek and Perplexity. Non-callable consumer surfaces are not shown as analysis options. One provider check means one prompt sent to one live AI-search API; all tiers use
one sample per prompt during the starter rollout.

The primary results expose only the mention score, current and rolling mention rates, and average
mention rank, separated by platform, plus sample size and a 95% mention-rate confidence indicator.
`deterministic-v5` marks platform results with fewer than three completed checks as insufficient,
combines up to five comparable analyses for a rolling rate, and only assigns a rank when an explicit
answer list or tracked-entity ordering provides rank evidence. An unopposed prose mention is no
longer presented as rank #1.
Provider failures remain visible and are excluded from successful-sample denominators. The
server derives the company from the authenticated user, caps one request at 20 provider
executions, caps the request stream at 32 KiB, limits provider answers to 150–1,500 output
tokens (700 by default), and rate-limits creation to 5 per hour and 20 per day per company.
Free workspaces receive a plan-lock response; all roles inside an operational paid company can
view and run the shared company analysis.

Migration `data/075_geo_analysis.sql` creates the company-scoped analyses, executions and
citations tables with service-role-only access and paid-plan feature flags. It also provides an
advisory-lock-backed reservation function so simultaneous requests cannot exceed the monthly
provider-check allowance. Apply it before
deploying the code, followed by `data/076_pro_four_channels.sql`. Configure at least one provider key; missing providers are shown as
unavailable rather than silently simulated. Local verification uses mocked provider responses;
live provider calls, production migration and browser layout remain deployment gates. GEO calls
use their separate plan allowance and do not debit the chatbot AI wallet because that ledger
requires a chatbot id.

Scoring follow-up on 2026-10-14 upgrades the methodology to `deterministic-v5`: 60% mention rate
plus 40% mention-rank prominence. Mention rank uses explicit result-list position first and
tracked-brand order only when comparative evidence exists. Citation, sentiment and share-of-voice
signals no longer affect the score or primary results. Each measured platform receives its own
mark and four deterministic, prompt-linked action pillars without another LLM call: build a
clear website or landing page, publish original posts on relevant trusted platforms, add genuine
local landmarks and Malaysian context, and fix technical access for search and AI crawlers.

Frontend follow-up on 2026-10-14 gives every HTML entry page one shared SVG favicon and an
Omnexa-labelled browser title. Shared localization now observes content and accessibility
attributes inserted after page load, supports open shadow roots, and lets generated UI use
structured parameterized messages that re-render when the language changes. GEO-generated
metrics, evidence labels, matrix states, history metadata and the four action pillars use this
structured path; business names, prompts and raw provider answers remain unmodified evidence.

Security follow-up for this renovation moved the Gemini key from the request URL into the
`x-goog-api-key` header, covered chunked bodies with the stream limit, and pinned the GEO
page/shared-sidebar Lucide fallback with SHA-384 Subresource Integrity.

## Service bookings and the living CSV — 2026-10-02

**Built and tested on branch `feat/service-bookings-csv`. Not committed, not deployed, and
migration 072 is not applied anywhere.** A chatbot with the per-bot switch on collects a
booking, reservation or appointment request in chat. It is recorded as `requested`; staff
confirm, edit or cancel it on the new Bookings page (`/bookings.html`, sidebar → Customer
activity). One CSV per company is rewritten in place at
`reports/<company_id>/bookings/bookings.csv` after every change and is never saved under a new
name. The Bookings page downloads a fresh copy built from the database. The owner gets a short
email with a link, at most one per company per 30 minutes.

How it stays honest and bounded:
- The model ends its reply with a hidden `<<BOOKING {...}>>` line once the customer has
  explicitly confirmed. The server removes it from every reply (switch on or off, valid or
  not) and takes company, chatbot, conversation, channel and phone from its own records,
  never from the model.
- The customer is told "sent to the team, not confirmed until they reply" only when a booking
  row really exists; otherwise they are told to contact the team. The model is told never to
  claim confirmation. Dashboard test chats strip the marker but record nothing and email no one.
- Limits: 3 chat requests per conversation per hour and 20 per company per hour, so made-up
  web-widget conversations cannot flood the queue, the owner's inbox or storage writes. Replays
  of an open request return it quietly; a cancelled or completed request can be asked again.
- The CSV reads 1000-row pages (PostgREST silently cuts one response at 1000) up to the 5000
  newest rows and logs when it is cut. Cells that could start a spreadsheet formula are
  neutralised. The web-widget session id is never stored (it grants access to that chat).
- Customer text is rendered with `textContent` only; the tenant always comes from the token.

Migration `data/072_service_bookings.sql` (with a rollback) is prepared for review. It creates
`service_bookings` and `chatbots.booking_intake_enabled` (default off), keeps the table closed to
everyone but the service, lets the service change only the staff-editable columns, and marks the
personal-data columns. It was applied, exercised and rolled back on a throwaway PostgreSQL 18.
**Apply it before deploying the code.** Until then the code treats a missing flag as "off".

Checks: **442 tests pass** across the feature, the receipt email and the sidebar page list. The
full backend suite is **5,997 passed, 48 skipped, 6 failed**; those six (trial-routing and
pricing-label tests) fail identically on the unmodified base commit `95a06ba`, so none are new.
Independent database, Python and security reviews were run and their blocking findings fixed.
The page was not opened in a browser (no Playwright launch worked), so its layout has only been
checked in code.

Open decisions: how long booking personal data is kept and how a customer's erasure request is
handled (the privacy page promises both; nothing automates them); whether notices should move off
the shared Gmail account (its daily quota also serves sign-in and billing mail; the other mail
senders still start TLS without verifying the server certificate); whether `member` users may
cancel and export (today they can, as with conversations).

## Bot Analysis and Agent actions — 2026-09-23

**Code and schema deployed; execution disabled by user choice.** Analysis sits below
Conversations for the selected Bot. Owner/admin report requests use that Bot's
confirmed industry, role, authorized documents and source-backed business records.
Web, PDF and Excel share an immutable snapshot. Non-clinic operations reports can
analyze bounded customer-question samples with message IDs; clinic reports exclude
customer/document free text. Unavailable revenue is never estimated from fees.

Website and Telegram trial booking use real sessions, capacity locks, explicit
confirmation and versioned cancellation; Telegram customers start with `/trial`.
Other industries record customer intent without inventing a confirmed reservation.
Report, trial, schedule, recording and reminder execution remains disabled.
Flask v38 is healthy: `c3282e1` combines the bot-ownership fix and industry/Pro gates
from `91542de` with the existing v37 Cloudflare/pricing files. All 316 runtime hashes
match the build snapshot; the 12 retained v37 files are unchanged. Migration 068's
Pro-only flag matrix and 069's n8n schema permission are verified in production.
The original n8n database password was recovered and verified over TLS 1.3; no reset
is needed. n8n, Langflow and the report Worker are still not running.

Latest combined checks: **5,380 backend tests and 2,330 subtests passed, 35 skipped**;
six failures reproduced on the v37 baseline. **25 browser checks passed** with one
existing pricing-label expectation failure. Automated security remains incomplete
because saved-login refresh failed. See the latest deployment evidence below.

The earlier v36 independent staged-snapshot suite passed **5,255 tests, 34 skipped,
2,303 subtests**. The latest report/export regressions passed **117 tests** after
the final industry transition guard; **20 browser checks** and isolated PostgreSQL checks
also passed. Codex Security stopped before scanning because sign-in refresh failed;
OCR has no configured endpoint. Supabase access to the configured production
project was restored on 2026-09-23; live schema/ACL checks passed. Langflow has an
empty app and 2 GB volume; secret upload was rejected by automatic approval, so
it has not started. The temporary builder/cache was deleted with user approval.
No real customer message or paid model smoke was performed. See [delivery evidence](ANALYSIS_IMPLEMENTATION.md),
[data boundaries](ANALYSIS_DATA_PROTECTION.md) and [deployment gates](../deploy/agent-automation/README.md).

## Industry templates — 2026-09-22

**Deployed in Fly v36; real-model classification accuracy remains unverified.** A primary document's
existing persona call can suggest restaurant, clinic administration, tuition
centre or a general fallback. The merchant reviews evidence and explicitly
confirms the selection; fixed versioned rules then reach both default and custom
reply prompts. New uploads and explicit re-review keep the previous confirmed
industry effective. Migration 062 is applied and its constraint validated in production.
The working-tree suite passed **4935 tests, 7 skipped, 2303 subtests**; **28 browser
tests** and the isolated PostgreSQL migration check passed. Codex Security was
blocked by sign-in refresh before scanning any file. No booking, clinical,
payment or enrollment tool is enabled. See
[workflow and verification](INDUSTRY_TEMPLATES.md).

## Website staff replies — 2026-09-22

**Deployed and verified on Fly v35.** Conversations can save a
human reply for the original share-link/widget visitor; visitor polling receives
it and retains the same session on reload. Pending handoffs suppress AI while
customer follow-ups are saved. Migration 061 enforces one open visitor session.
Full working-tree tests passed 4828 tests, 6 skipped and 2303 subtests; 19 browser
checks passed, and all 290 deployed runtime hashes matched. The live widget and
polling endpoints passed read-only browser checks; no real customer send was used.
Phase B remains disabled. Codex Security authentication blocked its scan. See
[workflow, boundaries and release evidence](WEB_STAFF_REPLIES.md).

## Human handoff Phase A/B — 2026-09-22

**Phase A deployed and verified on Fly v34; Phase B schema/API deployed but
disabled.** The dashboard shows waiting requests, links to the filtered queue,
and distinguishes unavailable counts from zero. Migration 060 and its validated
message-author FK are live. Seven staff APIs include atomic control updates and
same-chatbot/tenant checks. Full working-tree tests passed: 4771 tests, 5 skipped,
2303 subtests; all 289 deployed runtime hashes matched. The complete new
claim/reply/automatic-send workflow is not connected, so the handoff flag stays
off. Codex Security authentication blocked its scan; no security pass is claimed.
See [release evidence and activation limits](HANDOFF_PHASE_AB_RELEASE.md).

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


## Client document protection — 2026-09-14

**Deployed and verified on Fly v18 with private R2 storage.** Upload limits,
PDF size/signature validation, no-store responses, safe errors, and deleted-cache
guards now accompany authoritative private R2 storage for originals, candidates,
README/history, and media. The user approved R2 recurring billing and a bucket-only
token. `aibot-client-documents` exists in APAC Standard with public access disabled;
four Fly secrets are deployed. The migration marker confirms 43 files totaling
8,622,343 bytes on the existing single Machine/volume; local originals are preserved.
Final local verification:
**359 tests and 108 subtests passed**; 12 runtime files compiled and diff checks passed.

The live image/runtime hashes, health, synthetic storage/media checks, and anonymous
bucket-access denial passed. Final remote verification completed with exit 0;
synthetic files were removed, leaving 43 objects.
Existing Fly `/media/` URLs remain anonymously shareable with providers. R2 does not
add zone WAF protection, and deletion/AI-provider limits remain explicit. The user
waived the Codex Security scan; no scan pass is claimed. See the
[document protection review](CLIENT_DOCUMENT_PROTECTION.md) for release evidence.

## All-channel replacement and customer-service handoff — 2026-09-14

**Implemented; final release verification in progress.** The user approved the
cross-channel prototype and deployment to the existing Fly site. Telegram token
replacement and Meta/WASender phone-number replacement retain the previous
connection until verification succeeds. Failed/pending attempts remain visible.
Original conversation identities are preserved; staff sends require provider
acceptance, and AI resumes only after the final blocking Resolve. Test Lab Clear
resets only its test session. Migration 058 supplies shared atomic activation,
quota and resolution guards. Current checks and deployment evidence are recorded
in the [customer-service guide](BOT_CUSTOMER_SERVICE_LOOP.md).

## Fly deployment and channel publishing — 2026-09-10

**Verified complete for public hosting and staff password login; channel rollout
partially implemented.** [Live login](https://aibot-chatbot-my.fly.dev/login.html)
runs in the user's paid **aibot EMAIL** organization (`personal`). Admin and
Superadmin reach their separate portals; live API authorization and dashboard
charts were checked in Chrome. Three enabled website bots (35, 50, 53) are
publicly reachable. The single Singapore Machine retains 41 restored runtime
files on its writable volume, verified by hashes after deployment.

The user selected bot 53 as sole owner of a Telegram identity shared by several
company records. Exclusive ownership guards and the database index are deployed;
the bot callback is connected, with zero pending updates and no provider error.
Wasender has only an orphaned row and its provider session is logged out; Meta
has no channel records. The user selected Travel Bot 50 for Wasender, then deferred
setup until registration is ready. Its expired application subscription and
pending renewal status must also be resolved before connecting.
The user confirmed bot 53 replies to a short Telegram test; other channels
have not been message-tested. Google OAuth still needs the live origin configured;
background billing/retry/Langflow jobs remain disabled pending runtime handover.
The configuration-only security scan passed with zero findings; the earlier
source scan remains incomplete and is not superseded. The eight-path Telegram
scan completed with one low-severity legacy-data finding whose prerequisite is
absent from the verified live channel inventory. See
[current release evidence](FLY_CHANNEL_READINESS.md) for exact checks and gaps.

## Tenant support legacy-schema compatibility

**Verified complete for local mocked compatibility; live verification not performed.**
Runtime submission again uses the
five-parameter request RPC. Admin detail/converted-case reads do not request
`escalation_context`. Tenant urgency, origin and browsing-trail submission are
on hold; existing row priority/source, conversion, replies and notifications remain.
Migration 052 and its rollback are retained unchanged and are not executed.
Targeted Python: 303 passed / 248 subtests; targeted Playwright: 132 passed.
Full Python: 3,694 passed / 1 skipped / 2,139 subtests; full Playwright: 347 passed.
Compilation and whitespace checks passed. Sentry and Codex Security tools were
unavailable for this rollback; no deployment or live database check was performed.

## Sentry server error reporting — 2026-09-09

**Verified complete for local server reporting; deployment pending.** Opt-in Flask, shared handled-error,
Python error-log and thread capture strips private payloads before transmission.
Real-SDK tests use an in-memory transport. The Flask project
`whastapp_chatbot_project` is connected locally and a synthetic event was confirmed
through Sentry's API. Browser error reporting and
automatic recurring investigation are outside scope. See [setup and repair
workflow](SENTRY.md).

## Client-data security repairs — 2026-09-08

**Implemented locally; release security verification remains incomplete.** Reset
and signup OTP budgets, pending-signup credential integrity, safe media serving,
unique upload names, bounded CRM JSON and sensitive-error handling have adversarial
regressions. Follow-up keyword XSS, billing-role and body-limit fixes are included.
Sentry API authentication and live database permission metadata were checked; Sentry
returns no accessible projects. Comprehensive scanning was skipped at user request
on 2026-09-09 with incomplete coverage. Cumulative media quotas and deployment remain open. See [audit scope and evidence](SECURITY_AUDIT_2026-09-08.md).

## Guided first-client bot setup — 2026-09-07

**Implemented; public deployment remains unverified.** New bots continue directly
to Add knowledge → Review instructions → Test replies → Publish. Workspace and
selected-bot navigation are distinct, with account controls at the bottom. Four
publishing options have equal treatment and require a choice; new website records
start disabled. Saving or reconnecting preserves the public key. Address metadata
distinguishes configured HTTPS, temporary, local and invalid URLs without claiming
availability. Focused mocked backend/browser checks and manual synthetic interaction
are recorded in [the client journey review](CLIENT_JOURNEY_REVIEW.md), including
the security result and unrelated baseline test failures. The Fly hostname and running origin were verified on 10 September; a custom
Cloudflare domain remains optional. See [live release evidence](FLY_CHANNEL_READINESS.md).

## Approved platform staff redesign — 2026-09-07

**Activated in shared Supabase; public staff logins verified on 10 September.** The independent light Admin portal and dark Super Admin portal use server-assigned platform roles/modules, database-selected login destinations, audited approval decisions and existing billing/support services. Migrations 050/053 and the two requested account assignments are active. Both browser logins now load live records through [the public Fly application](https://aibot-chatbot-my.fly.dev/login.html), with the correct role-specific destinations and permission checks. See [original rollout](PLATFORM_STAFF_PORTALS_ROLLOUT.md) and [current deployment evidence](FLY_CHANNEL_READINESS.md).

Super Admin overview now includes current subscriptions by plan, subscription status,
and payment follow-up charts using the existing authenticated aggregates. Visible
counts, source timestamps, status filter links, missing-data states and mobile
layouts are covered by the 13-test Super Admin browser suite. No schema or API
changes were needed; chart security review is recorded in the rollout evidence.

## Status Definitions

- **Verified complete**: implemented and supported by current test evidence or recorded successful end-to-end verification
- **Implemented**: coherent implementation exists but verification is incomplete
- **Partially implemented**: required parts are missing or disconnected
- **On hold**: intentionally paused
- **Obsolete**: no longer part of the active system
- **Needs investigation**: evidence is conflicting or insufficient

## Superadmin Environment Boundary

The current Supabase project is intentionally used as the prototype/shared-testing
environment for Superadmin development and team verification. Supabase
labels its main branch as `PRODUCTION`, but this project is not the future real
production environment. Future staging and future real production have not been
verified or deployed for the current Superadmin milestone.

The current Superadmin prototype milestone is runtime-verified complete in that
prototype/shared-testing environment. Completed current Superadmin scope
includes the foundation/security work, Support Case Operations, Tenant
Communication, bounded Platform Admin Management, Tenant / Company
Administration, Platform Monitoring, and read-only Billing & Subscription
Oversight. Broader Phase 4 Platform Admin account-management expansion remains
deferred and is not required for the current prototype milestone.

Repository/database reconciliation confirmed that Superadmin migrations 029
through 038 are already represented in the current prototype/shared-testing
database. Do not reapply migrations 029-038. Migration 043
(`data/043_atomic_platform_support_case_creation.sql`) and Migration 044
(`data/044_platform_admin_user_recent_activity_batch.sql`) are applied and
runtime verified in prototype/shared-testing only. They are not staging
verified and are not production deployed.

Final Superadmin prototype runtime verification is now represented by the
consolidated hardening verification pass: focused evidence recorded 310 passed
tests and 779 subtests, and the broader focused platform-admin suite recorded
431 passed tests and 991 subtests. The pass covered atomic support-case
creation, bounded support history pagination, pagination regression repairs,
platform-admin recent-activity batching, human-readable assignee identities,
inactive historical assignee safety, and the monitoring-depth audit conclusion
that current Phase 6 is sufficient for prototype/shared-testing.

## Authentication and Account Management

| Feature | Status | Notes |
|---|---|---|
| Registration | Implemented | Backend and frontend flow exist; broader automated coverage is still needed |
| Public Landing Page | Implemented | Clean, glassmorphic landing page introducing project features, FAQ, and subscription pricing aligned with the authoritative billing plan catalogue; dynamic login checks; served as root `/` |
| Public Legal Pages | Implemented | Privacy Policy (English and Bahasa Malaysia, 21 sections each) and Terms & Conditions (17 clauses) served without sign-in at `/privacy.html` and `/terms.html`; linked from the landing footer and the registration consent line. Mocked source and serving tests pass; not yet checked in a live browser. Pending owner input: privacy contact email (marked `data-todo="contact-email"`) and the operator-name spelling |
| Login | Implemented | JWT login flow exists |
| Logout | Implemented | Client-side token removal; no server-side revocation |
| Forgot password | Implemented | Requires renewed end-to-end verification |
| Reset password | Implemented | Requires renewed end-to-end verification |
| Password visibility controls | Implemented | Present in authentication flows |
| Email verification / OTP | Implemented | Security review required for OTP logging and production behavior |
| Google authentication | Implemented | Public client configuration loads at runtime; missing `GOOGLE_CLIENT_ID` fails closed, token audience must match exactly, Google email must be verified, and invitation email must match. `RATELIMIT_GOOGLE_AUTH=10/minute` covers Google login, registration, and invitation acceptance; live external Google verification is still required |
| Auth and public-invitation rate limiting | Verified complete | Flask-Limiter decorators registered before `create_app()` are enforced during normal startup. Existing login, OTP, password-reset, checkout, retry, receipt, and export limits are active when enabled; invitation validation is 30/minute and password invitation acceptance is 5/minute by default |
| User profile | Implemented | Profile viewing and update flow exists |
| Authenticated tenant Support page | Implemented | `support.html` is authenticated, reachable from the shared tenant sidebar account menu, submits only category, title, and redacted description to `POST /api/support/requests`, and now includes request history/detail with tenant-visible replies from safe tenant endpoints. Migration 030 is verified only in the main shared testing Supabase with fake/team data. Phase 3 tenant communication and Migration 033 are verified only in the main shared-testing Supabase with fake/team data. Email, attachments, billing actions, impersonation, exports, charts, staging readiness, and production use remain excluded |
| Password change | Implemented | Requires regression coverage |
| Tenant account menu / navigation | Implemented | The workspace and selected-bot sidebars are distinct; account controls are in the bottom footer while navigation scrolls. Existing Profile, Support, Logout and server-authorized platform discovery remain shared. Focused desktop/mobile placement and navigation tests plus manual synthetic account access passed on 2026-09-07. The wider legacy account suite still has ten classified baseline/stale-fixture failures, including an existing shadow-icon initialization issue; see [the client journey review](CLIENT_JOURNEY_REVIEW.md). |

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
| Chatbot archive, restore, and permanent deletion | Verified complete | Active and archived lists are company-scoped; authenticated archive listing plus admin/owner restore and permanent-delete routes are covered by focused route tests. Permanent deletion still depends on Migration 022 being deployed in the target Supabase environment |
| Chatbot editing | Implemented | Requires broader route tests |
| Chatbot deletion | Implemented | Requires deletion-flow verification |
| Prompt configuration | Implemented | Profile and deployment flow exists. `frontend/new_prompt.html` was rebuilt on 2026-08-17 as a vanilla-DOM four-step wizard (Profile → Knowledge → Validate → Deploy) on the control-room design system, replacing the React 18 UMD page loaded from unpkg without SRI. No endpoint or payload changed; the deploy precondition that `handleDeployToLiveBot` previously enforced only after the click (active profile + active primary knowledge + passing `/api/match/check`) is now shown up front via a disabled button and a named blocker, and any profile change or save clears the stored validation. Covered by `tests/browser/bot-config.spec.js` (mocked APIs — no live-backend verification). Dead `extraction*` state that the old render never referenced was removed |
| Profile editor (tone, optional websites) | Implemented | On 2026-08-18 three defects in `frontend/new_prompt.html` were fixed. (1) Tone was a three-option `<select>` (`Friendly`/`Professional`/`Formal`), but the column is free text and `persona_derivation_service` writes arbitrary phrasing such as `"Clear, professional"`. Opening Edit reset the control to blank, and because `bot_config_fields.merge_persona_write` treats a present-but-blank persona field as a deliberate delete, saving silently wiped the stored tone and its provenance. It is now a free-text input with a `<datalist>` of suggestions, so any stored value round-trips. (2) Supporting websites reported `Needs attention` when empty; they are genuinely optional (many clients have no site) and never gated deployment, so the row now reads `Optional` with a neutral pill. (3) `_row_to_profile` did not forward `updated_at`, which `save_profile` already stamps on every write, so the library's "Last updated" column was always blank; it is now returned (additive, no existing key changed). The page's `api()` helper also no longer reports a non-JSON error body (an unhandled Flask 500 returns HTML) as a network failure. Covered by `tests/browser/bot-config.spec.js`; both new cases were confirmed failing before the fix. Note: profile saves can still fail at the database layer while migrations `039`/`040` remain unapplied — see the persona rows above |
| Profile/knowledge match validation | Implemented | `POST /api/match/check` is an LLM topical-alignment check: it asks whether the active profile's persona describes the same business as the active primary knowledge, and returns `{match, reason}`. It is **not** a malware, safe-content or PII scan. On 2026-08-17 the frontend was corrected and automated. Both `frontend/index.html` and `frontend/new_prompt.html` previously compared `knowledge.validation_status` (a display label such as `"Profile validated"`) against machine values, so the Dashboard's Validate step could never leave "Needs attention", and Bot config held the result only in memory so a reload forgot it. Both now read the tri-state `knowledge.match_result`, which `dashboard_health_service` already returned from `chatbots.last_match_result`; that service additionally forwards `match_reason` so a failure states why. Both pages now run the check automatically when both inputs exist and the stored result is NULL — the state the backend already sets on upload, on active-knowledge change and in `set_active_profile` — at most once per page load, and on the Dashboard only for admin/owner because the endpoint is `@role_required`. A `false` or unavailable result is surfaced for the user to act on and is never retried automatically. Note this spends AI credits without an explicit click, since the check runs through `ai_router.generate_system_response` |
| Behaviour Studio (merged Tune AI + Message Style + Test Bot) | Implemented | On 2026-08-18 the three Behaviour pages were merged into `frontend/behaviour.html`, a three-tab studio (1 Model, 2 Message experience, 3 Test lab) on the control-room design system. They had remained on the legacy glass system (Outfit, `--bg:#050b18`, `--primary:#3b82f6`) while the dashboard, bot config and knowledge screens moved to control-room, so half the tenant surface looked like a different product. Merging is justified by the data: Model and Message experience both write `PUT /api/bots/{id}`, and `bot_service.edit_bot` is key-presence based so partial payloads already merged safely. **Temperature was replaced with Answer style** — three named outcomes (Precise 0.2, Balanced 0.7, Creative 0.9) that say what each is for rather than exposing a sampling parameter. The raw value survives inside a collapsed Advanced disclosure, and a stored value that is not one of the three shows as a selected `Custom (n)` card so existing settings are never silently moved; the cards follow the number, so the two cannot disagree the way the mockups' side-by-side mode-cards-plus-slider would. **Test lab gained an Active setup strip** that names the profile, knowledge, model and menu in use and warns when `deployed_profile_name` is blank — the case where `rag_service.get_deployed_settings` falls back to `DEFAULT_SETTINGS` and the bot answers convincingly as someone else. One save and one dirty state now cover both editable tabs, with a `beforeunload` guard. Plan gating moved verbatim into `assets/js/model-catalog.js` rather than being retyped, since it is billing-enforcement surface. Tabs are URL-addressable (`?tab=`); `model_settings.html`, `message_style.html` and `testbot.html` are now redirects preserving `bot_id`, and the sidebar keeps its three familiar labels. No endpoint or payload changed. Covered by `tests/browser/behaviour.spec.js` (27 cases, mocked APIs — no live-backend verification) |
| Test lab: business-matched scenarios | Implemented | On 2026-08-18 the Test lab's *Try a scenario* list stopped being a fixed clinic-flavoured set ("Hi, I need to move my appointment on Friday") and is now derived per bot from its own active document via `GET /api/testbot/scenarios` → `app/services/test_scenario_service.py`. The old list was unusable for the half of the tenant base that takes no bookings: a shop testing "reschedule my appointment" learns nothing about the bot it is about to deploy. Four slots are generated, in a fixed order, following the pre-deployment set a support assistant is normally checked against — the most common request, one fact that must be retrieved correctly, one request that is out of scope and must be declined rather than invented, and one message too vague to answer. The first two prove the bot is useful; the last two prove it is safe. Slot keys are assigned server-side **by position**, so a model that invents its own key cannot change which icon or slot a row gets. Asking for a human is never derived (`HANDOFF_SCENARIO` in `app/routes/testbot_routes.py`): it means the same for every business, so it is appended last and survives an empty document and an exhausted AI balance. Failure degrades rather than blocks — no document, no readable text, a billing limit or an unusable reply all fall back to a business-neutral set plus a `note` saying why and what to do about it. The LLM call happens only after a document and its chunks are found, so nothing is billed when there is nothing to read, and the result is cached in `sessionStorage` per bot with an explicit Refresh. Text from the document is stripped of control and bidi characters before display, since a poisoned document could otherwise reorder what the operator reads before pressing Send. Covered by `tests/test_test_scenario_service.py` (10 cases on the pure parse path) and `tests/browser/behaviour.spec.js` |
| Test lab: live reply buttons | Implemented | On 2026-08-18 the Test lab began rendering the reply buttons a channel would send, so the welcome menu configured on Message experience can be tapped and tested rather than only described. A reply may end with `[BUTTONS: A | B | C]` — appended by `chat_logic_service.handle_greeting` from the saved `welcome_menu_labels`, and asked for by `rag_service`'s prompt on broad questions. Every channel strips it via `message_style_utils.parse_buttons_tag` before sending; the Test lab did not, so it printed the raw tag in the transcript, the one place a customer never sees it. `behaviour.js` now ports that parser (tag at the end, `|`-separated, labels capped at 20 characters and 3 buttons) and renders the labels as buttons under the bubble. Tapping one sends the label as the next message, which is exactly what the backend receives from a channel: Telegram returns it as `callback_data`, WhatsApp as `button_reply.title`. Buttons follow **saved** state, not the draft, because the reply came from the server reading the saved row. With quick replies off no buttons are drawn and a note says how many were not sent — the toggle's real cost, otherwise invisible. Older keyboards stay tappable as they do in Telegram, but are disabled while a request is in flight so two taps cannot interleave. Covered by four cases in `tests/browser/behaviour.spec.js` |
| Message experience preview: numbered fallback removed | Fixed | The preview claimed that turning quick replies off made the bot say "Reply with 1 for available times, or 2 to speak with our team." No such reply exists: `parse_buttons_tag` strips the tag whether or not buttons are sent, and nothing in either channel renumbers the options. An operator could therefore switch buttons off believing customers still got a numbered menu, when in fact the choice survives only inside the sentence. The preview now says what actually happens — "No buttons. The customer types their answer instead." — matching what the Test lab shows for the same setting |
| Test lab: `chatbot_id` query parameter | Fixed | The merged Test lab called `/api/testbot/context` and `/api/testbot/chat` with `?bot_id=`, but `app/routes/testbot_routes.py` reads `chatbot_id` and answers `400 chatbot_id is required`. The chat path rendered that message as the bot's reply, which is the error operators reported; the context path swallowed it and reported "Nothing is deployed yet" for every bot, deployed or not. Both now send `chatbot_id`. A failed context lookup no longer claims the bot is undeployed — it says the setup could not be checked, because sending someone to redeploy a healthy bot is worse than admitting the lookup failed. The mock in `tests/browser/behaviour.spec.js` now returns the same 400 the route does, so a wrong parameter name cannot pass again |
| Behaviour Studio: access-denied state | Fixed | The merge dropped the Phase 1 staging fix that `model_settings.html` carried: a 403/404 on the bot load bounced the operator to `bots.html` with no explanation. `behaviour.js` now shows "Chatbot not found or you do not have access." in place, hides the tabs and footer (nothing behind them is readable), and sets `botLoadFailed` so no `PUT` can follow a failed load. `tests/test_staging_phase1_regressions.py::TestModelSettingsAccessDeniedState` was retargeted from the redirect stub to `behaviour.js`, and the behaviour spec exercises the 403 end to end |
| Model selection | Implemented | Model catalog and settings UI exist |
| Flow Builder runtime | Implemented | Flow Builder remains part of the active chatbot system. Backend flow save/fetch routes, V3 draft/published persistence, AI Router interception, Test Bot integration, flow execution, safe AI/RAG handoff, and legacy `flow_data` compatibility are covered by `tests/test_flow_builder_runtime.py`; broader UI and live-channel flow verification remain needed |
| Knowledge follow-up and CRM stage automation | Partially implemented | Tenant-scoped automation event creation, idempotent knowledge-document review events after successful PDF indexing, compare-and-set CRM stage transitions, monitoring endpoint (`/api/automation/events`), operator health endpoint (`/api/automation/health`), and owner/admin CRM automation endpoint are implemented. Migration `data/049_automation_events.sql` was applied and live-verified on 2026-09-03 in the active Supabase project; event persistence remains advisory so user workflows stay fail-open if the table later becomes unavailable. Langflow advice runs during requests; knowledge review events still require human approval and no review-completion consumer is implemented. The local Windows runtime is reachable; hosted runtime deployment remains separate work. The 2026-09-08 update adds Langflow-aware health, matching request identity, synchronous-response enforcement, and CRM consultation metadata. Langflow remains opt-in and does not bypass existing tenant, billing, or Flow Builder boundaries; see `langflow/README.md` for local startup and recovery |
| Media Attachments | Implemented | Backend, UI, and webhook dispatch created |
| Persona field unification (migration 039) | Partially implemented | `bot_config_fields.py` makes the canonical/legacy column mapping single-source and writes NULL into the deprecated `business_objective`/`response_style`/`prompt_text` mirrors. Migration `data/039_unify_bot_config_persona_fields.sql` is unapplied everywhere and its mandatory SELECT-only preflight `scripts/bot_configs_persona_unification_preflight.sql` is unrun; section 10 must be exported to the restricted archive before applying because divergent legacy values become unrecoverable. Deploying the code before the migration fails every `bot_configs` write with `23502`. See `docs/KNOWLEDGE_INGESTION_AND_DERIVED_PERSONA.md` |
| Derived persona from ingested documents | Partially implemented | `persona_derivation_service.py` fills `company_name`, `business_description`, and `tone` from the client's uploaded PDF after `POST /upload-pdf`, through `ai_router` so billing and tier enforcement apply; a non-JSON reply writes nothing. 73+32+14 focused tests pass plus real-browser `tests/browser/testbot-persona.spec.js`. Blocked from delivering its stated benefit: `rag_service.get_deployed_settings` returns `DEFAULT_SETTINGS` when `chatbots.deployed_profile_name` is blank, so an undeployed bot still replies "Your Company" — exactly the never-opened-the-form population targeted. A test pins the gap; closing it is separate create-RPC/promotion work. Residual stored prompt-injection risk: up to 1000 characters of document-chosen prose reach the serving system prompt as asserted company fact (structural newline/control-character lever closed, semantic lever open). Whether `tone` should be excluded from placeholder-matching is an open design call |
| Persona provenance and client override | Implemented | `bot_configs.persona_provenance` jsonb tags each derivable field `client_entered` or `derived` in the same INSERT/UPDATE as the value, so the two cannot disagree. A client edit flips the marker to `client_entered` and re-ingestion never overwrites it. Partial profile saves preserve omitted persona fields by key presence; `custom_prompt`, `bot_name`, `additional_instructions`, and `out_of_scope_reply` are still full-replaced. Migration `data/040_bot_config_persona_provenance.sql` is unapplied everywhere and must be applied before the code or every settings/profile save fails with `PGRST204`. No backfill by design: pre-existing rows read as unknown and are adjudicated by value. Client procedure documented in `docs/KNOWLEDGE_INGESTION_AND_DERIVED_PERSONA.md` |
| Message style & welcome menu buttons | Implemented | Welcome-menu buttons always render regardless of the interactive-buttons toggle (per product decision). The `[BUTTONS: ...]` tag is now stripped from the reply before markdown formatting on both Telegram and WhatsApp so buttons reliably render. Welcome-menu AI generation is capped at 3 labels to match the UI. Regression tests added in `tests/test_message_style_buttons.py` |


## Knowledge and RAG

| Feature | Status | Notes |
|---|---|---|
| Knowledge file upload | Implemented | External storage and full error-path verification still needed |
| Knowledge file listing | Implemented | Chatbot-scoped |
| Active knowledge selection | Implemented | Current active file behavior exists |
| Supporting knowledge toggle | Implemented | Enabled/disabled knowledge behavior exists |
| Supporting PDF relevance validation | Verified complete | Additional PDFs use candidate preflight when a Primary PDF exists: local extraction, `semantic_hybrid_v2`, bounded temporary candidate embeddings against stored Primary embeddings, and the environment-configurable `PDF_SUPPORTING_RELEVANCE_THRESHOLD` default of `0.65`. Exact duplicates are blocked separately. PASS requires explicit confirmation before Supporting ingestion; FAIL creates no normal knowledge files, chunks, GraphRAG, persona, README, or Supporting source. Confirmed Supporting PDFs remain enabled and non-active, preserve the Primary, skip persona derivation, and use `source_pdf_candidate_id` for idempotency/recovery. `original_file_name`/`display_name` keep human-facing UI names readable. Migration 045 creates the candidate/data-linkage structure; Migration 046 hardens candidate `service_role` privileges. Shared-testing/prototype manual verification passed, including Supporting RAG/Test Bot retrieval. Future staging/real production are not claimed. Known limits remain: small threshold sample, no per-row historical embedding-model metadata, bounded per-chunk validation embedding requests with small provider cost, opportunistic candidate cleanup, and local Playwright blocked where Chromium is missing |
| Website scraping | Implemented | Single URL scraping requires single_website_scraping feature; batch scraping requires batch_website_scraping; Advanced can scrape single URLs only |
| Website source prerequisite | Verified complete | Website knowledge can only be added when the chatbot has an enabled active Primary PDF. Server-side enforcement covers `/api/knowledge/scrape`, `/api/knowledge/scrape-analyze`, `/api/knowledge/scrape-batch`, `/api/knowledge/scrape-extract`, `/api/knowledge/scrape-embed`, and `/api/knowledge/ingest`; missing Primary returns HTTP 409 with `code=primary_pdf_required`. Supporting, disabled, inactive, and website sources do not satisfy the rule. The frontend keeps website controls disabled until an active Primary PDF exists, and existing website sources are not deleted or changed by this rule |
| Knowledge processing feedback | Verified complete | Primary PDF upload, Supporting PDF validation, Supporting confirmation, and website processing show a compact indeterminate progress state with a visible elapsed timer updating once per second. No fake percentage or ETA is shown. Duplicate action protection remains active while processing, a standard browser `beforeunload` warning is installed only while a long-running knowledge operation is in flight, processing state clears on success/failure, and Supporting PASS still requires explicit confirmation |
| Knowledge refinement | Implemented | Requires end-to-end verification |
| Chunk storage and retrieval | Implemented | Database/vector configuration requires environment verification |
| RAG response flow | Implemented | Quality and adversarial testing remain |
| Knowledge graph visualization | Implemented | Graph rendering and node/edge CRUD in new_linkdocs.html |
| Knowledge graph editing | Implemented | Add, rename, delete nodes; add, delete edges; focused route tests exist |
| Single-call website ingestion (`POST /api/knowledge/ingest`) | Partially implemented | Composes analyze→scrape→extract→embed in one call with per-source per-stage progress, partial success, and no roll-back of ingested siblings; reuses the four staged services, which are unchanged. 41+19 focused route tests pass. **Review verdict BLOCK — do not enable behind a proxy.** (i) The synchronous run cannot finish in any realistic proxy window: 40s of timeout budget per page (Jina 25s then static 15s) x up to 10 sources x 5 default pages is ~35 minutes before LLM and embedding calls, and over two hours at the `max_pages` ceiling of 20; `requests`' timeout is a between-bytes read gap, not a wall clock, so per-page cost is genuinely unbounded. A proxy kill loses the report, and with no idempotency key a retry re-scrapes, re-charges storage, and re-runs the billed extraction. (ii) A source can report `succeeded` with zero chunks persisted — `save_refined_knowledge_chunks` writes the quota-consuming `knowledge_files` row first and then swallows every chunking/embedding failure. (iii) **Websites only; it does not accept uploaded documents.** See `docs/KNOWLEDGE_INGESTION_AND_DERIVED_PERSONA.md` |
| Website scraping storage-quota enforcement | Verified complete | Staged website storage paths now pass authenticated `company_id` through before storage work, including `/api/knowledge/scrape`, `/api/knowledge/scrape-embed`, and `/api/knowledge/scrape-batch`; the batch route calls `scrape_website_urls_batch(..., company_id=g.company_id)` so the service's storage-quota check is not bypassed. Focused route/frontend tests passed, the broader Knowledge Workspace regression reported 223 passed with 7 existing warnings, and `git diff --check` passed |
| Conversation graph memory and keyword recall | Partially implemented | `conversation_graph_nodes` persists facts learned mid-chat (name, contact, interest) and recalls them beside the vector path; the producer reuses the existing pure-regex extractor, so no LLM call and no billing change. 35 tests plus 16 subtests pass. Blocked: (i) migration `data/041_conversation_graph_nodes.sql` cannot be certified without running `scripts/conversation_graph_nodes_preflight.sql` — `chatbots` and `conversations` have no `CREATE TABLE` in this repository, and a pre-existing relation would make `CREATE TABLE IF NOT EXISTS` a silent no-op; (ii) the write path is not tenant-filtered — the upsert conflict target is `(conversation_id, label)` and `chatbot_id` is a payload column, so a mismatched pair re-tenants another chatbot's PII row. Unreachable today only because `conversation_id` is server-derived; (iii) recall is exact-match on a single normalised ASCII token, so "what's my phone number" does not find a fact stored under `contact`, and only `name`/`contact`/`interest` are extracted (no order numbers); (iv) raw customer name, email, and phone are persisted with no expiry, in a codebase that had deliberately avoided persisting these values |
| Compiled README generation | Implemented | Automatically updates bot_<id>_readme.md on PDF uploads, graph mutations, and Q&A submissions |
| README popup viewer | Verified complete | Modal dialog next to the active PDF file in new_linkdocs.html showing parsed markdown with search, results count, next/prev navigation buttons, and scroll focus |

## AI Providers

| Feature | Status | Notes |
|---|---|---|
| Model catalog | Implemented | Static/catalog-based model definitions |
| OpenRouter routing | Implemented | External API verification required |
| DeepSeek routing | Implemented | External API verification required |
| Gemini usage | Implemented | Current hardcoded runtime use is Gemini `gemini-embedding-2` for vector generation and semantic retrieval. Customer-facing generative usage is routed through the central AI router and selected model policy; no hardcoded Gemini generative bypass is currently known |
| AI usage logging | Implemented | Integrated with AI-credit charging |
| Provider fallback behavior | Implemented | Cross-provider fallback is disabled; selected-provider failures return the safe generic chatbot failure response without trying another provider |

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
| CRM lead list | Implemented | The bot-scoped list now lives in the combined Insights & Actions workspace with a plain-language daily brief, pipeline filters, inline updates, a lead detail dialog, and conversation links. Mocked desktop/mobile browser coverage is current; live backend verification remains outstanding. |
| Lead status | Implemented | Canonical stages are `new`, `contacted`, `qualified`, `won`, and `lost`; the combined Insights & Actions workspace and company-wide conversations pipeline use the same vocabulary. API reads and writes accept `in_progress`/`closed` aliases during the compatibility window. Migration 047 widens the database check; live schema application and browser verification remain outstanding. |
| Lead priority | Implemented | Priority editing exists |
| Lead assignment | Verified complete | Non-empty assignment uses the authenticated database-backed company context and remains gated by crm_lead_assignment; assignment clearing remains available to all plans; focused route regression tests cover success and rejection paths |
| Lead follow-up | Implemented | Follow-up fields and UI exist |
| CRM filters | Implemented | Stage, priority, follow-up, and text filtering exist in the combined Insights & Actions workspace; the company-wide conversations pipeline keeps its own filters. |
| CRM-to-conversation navigation | Implemented | Conversation ID linking was previously reviewed |

## Analytics and Operations

| Feature | Status | Notes |
|---|---|---|
| Dashboard metrics | Implemented | Requires broader regression tests |
| Message charts | Implemented | Data aggregation and responsive frontend display exist in Dashboard and the Insights & Actions Performance view; the latter has mocked desktop/mobile browser coverage. |
| Live workflow status | Implemented | Requires runtime verification |
| Dashboard health | Implemented | Requires environment verification |
| Agent insights | Implemented | Server-side owner/admin access uses the database-refreshed role and preserves chatbot ownership checks; the combined workspace hides the Signals view from members and lazily loads it for owners/admins. New Agent Actions and automatic CRM leads derive company ownership from the authoritative chatbot record. Staging migrations 028 and 027 hardened stored data and service-role-only access. Expanded review/dismissal/linkage lifecycle fields and frontend actions remain deferred; production database migrations remain unapplied. |
| AI-generated reports | Implemented | The report generator and lazy PDF export now live in the combined Performance view; `reports.html` preserves old links by redirecting there. External model, feature-gate, and live PDF verification remain outstanding. |
| Escalation handling | Implemented | Listing and exact-ID resolution require the current database-backed owner/admin role; resolution is compare-and-set idempotent and leaves unrelated signals unchanged. Same-action retries cannot repeat the AI-resumed notification; atomic deduplication across two different concurrently resolved final actions remains deferred to the lifecycle transaction/RPC phase. Focused regression tests are present; execution remains pending in a repaired test environment. |

## Subscription and AI Credit

| Feature | Status | Notes |
|---|---|---|
| Subscription plans and prepaid terms | Implemented locally; migration pending | The combined Chatbot + GEO catalogue offers Essential, Advanced, and Pro for 1, 3, 6, or 12 months. The exact full-term charges are server-owned; CHIP receives the complete upfront amount. Longer terms extend the paid-through date while included AI credit and usage allowances continue to reset monthly. Existing orders default to one month and keep their historical charged amount. The public landing page and authenticated Pricing/Billing views share the same published term matrix. Migration `data/079_prepaid_subscription_terms.sql` must be applied before deployment. Free stores `model_access_tier=economy` for compatibility and remains direct-DeepSeek-only. |
| Current subscription | Implemented | Company-scoped |
| Prepaid-term checkout integrity | Implemented locally; live verification pending | Checkout accepts only 1, 3, 6, or 12, looks up the exact integer-sen amount server-side, persists term and monthly equivalent in order schema v3, binds retries to the same amount and term, and activates the matching paid-through period. Callback and reconciliation fail closed for malformed v3 orders. |
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
| AI-credit usage charging and activity labels | Verified complete | Recent AI Credit Activity is transaction-ledger driven. Customer-billed generative operations now use distinct operation metadata instead of unrelated features collapsing into `knowledge_extraction`: Refine Answers records `knowledge_refinement_questions` and `knowledge_refinement_verification`, both displayed as "Refine Answers"; billing labels also distinguish Test Scenario Generation, Persona Derivation, Profile / Knowledge Validation, Website Knowledge Training, and Knowledge Graph Training, with a generic fallback for unknown future types. When AI-credit enforcement is enabled, central accounting fails closed if usage logging fails, provider cost is unknown, or subscription/balance/usage state cannot support a debit, so successful customer-billed AI should not silently complete without a `usage_debit`. Trial DeepSeek routing is aligned to the priced/catalogued `deepseek-v4-flash` model. Embeddings remain intentionally outside customer AI-credit debit activity. Verification: focused accounting/billing/pricing 97 passed, 6 skipped; broader AI access + Knowledge Workspace 288 passed; billing + knowledge route slice 151 passed; persona/menu/scenario/report slice 159 passed; AI access enforcement 151 passed; `git diff --check` passed; manual Refine Answers billing verification passed. No staging or production deployment is claimed. |
| ToyyibPay checkout | Verified complete | Latest billing work and focused tests completed |
| ToyyibPay callback | Verified complete | Callback parsing and processing covered by focused tests |
| HitPay hosted subscription checkout | Implemented | Server-selected dormant rollout path supports local-order-first hosted checkout, exact-raw-body HMAC event verification, authoritative status re-fetch, exact MYR amount/reference binding, guarded duplicate/stale-event handling, missed-webhook reconciliation, canary tenant selection, and operator-visible degraded health. ToyyibPay remains the default/fallback. Automatic renewal, merchant-dashboard setup, sandbox/live payment verification, Migration 051 application, and production enablement remain blocked pending separate approval and evidence. Migration 049 is unrelated and was not changed or applied by this work. |
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
- Live shape of `public.bot_configs`, `public.chatbots`, and `public.conversations` (no `CREATE TABLE` for any of them exists in this repository; migrations 039/040/041 all depend on catalog captures that have not been taken)
- Retention and data-subject-deletion policy for customer PII persisted in `conversation_graph_nodes`
- Wall-clock bounding and idempotency for synchronous multi-page scraping requests
- Whether a `derived` persona value should be fenced in the serving system prompt the way retrieved chunks are

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
- Email receipt: Implemented (2026-09-30). The first confirmation of a paid plan order or a credited AI-credit top-up emails the purchaser (`created_by_user_id`) a receipt through the existing SMTP sender (`receipt_email_service`), owner copied when a different person, owner as fallback. Sent at most once per order: a replayed callback does not resend, and a failed send is not retried (the receipt stays viewable and printable in Billing). Mocked-SMTP tests only; the sender is temporary and is to be replaced later
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

**Status: Original scope staging verified; later extensions have mixed local
and prototype/shared-testing evidence; production blocked**

The original five platform-admin endpoints retain their historical staging
verification. Later extensions have mixed evidence: some remain
local/application-tested only, while Phase 5, Phase 6, Phase 7, and later
hardening paths have prototype/shared-testing runtime verification where
explicitly recorded. Unless explicitly stated otherwise, later extensions are
not staging verified and are not production deployed. At the current local
implementation, localhost manual verification recorded on 2026-08-03 passed for
the full current twelve-route read-only investigation stack: dashboard, operational alerts,
company directory/detail, subscription summary/history, AI-credit usage and
transactions, billing orders, users, chatbots, Support Workspace, Audit Logs,
billing-order audit filters, and local revocation with Access Denied and stale
platform-data clearing. This does not establish staging verification or
production readiness. The complete platform-admin surface additionally includes
separately approved bounded support-case, platform-admin user-management, and
company lifecycle mutation routes; those later mutation routes are not staging
verified.

- Separate active `platform_admin_users` mapping required on every request;
  tenant owner/admin/member roles never grant platform access
- Twelve GET-only investigation endpoints for platform identity, operations overview, company directory/detail,
  subscription summary, current-period AI-credit/usage summary, and lazy
  read-only subscription-history, AI-credit transaction history, billing-order history,
  company users, company chatbots, and audit-log
  inspection. The original five endpoints were verified in staging; later
  operations-overview, users/chatbots, subscription-history, AI-credit
  transaction-history, billing-order history, and audit-log viewer extensions
  have mixed local and prototype/shared-testing evidence where explicitly
  recorded, and are not automatically staging verified or production deployed.
- Cross-tenant reads isolated in dedicated platform repositories with explicit
  safe projections and mandatory audit-before-response behavior
- Automated authorization, repository, route, and audit tests added
- Manual staging verification passed for all five endpoints and expected audit
  events, including metadata redaction and immediate revocation
- Separate read-only frontend implemented for platform identity, exact company
  counts, server-paginated company search, company billing/AI-credit detail, and
  lazy read-only subscription-history, AI-credit transaction-history, and company users/chatbots sections. A bounded application-only
  Platform Operations overview now adds one GET-only locally tested dashboard
  endpoint for company counts, latest-subscription status counts, latest-plan
  distribution, and at most 10 past-due/expired attention companies using
  `created_at DESC, id DESC` latest-subscription semantics. Operational Alerts
  Phase 1 extends this same dashboard and `/overview` response with typed
  read-only subscription past-due/expired alerts derived from existing
  attention data. Phase 6 later adds deterministic aggregate alerts for
  support backlog, pending and reconciliation-required billing orders,
  depleted AI-credit balances, retry backlog, and integration channel
  attention without adding a mutation route. AI low-balance alerts remain
  deferred because no threshold is approved; generic background job monitoring
  remains deferred because no durable telemetry exists; provider-cost
  monitoring, inactive-company and no-current-chatbot alert variants, charts,
  exports, and overview remediation/write actions remain deferred. The older
  Phase 2 alert definitions and approval gates are recorded in
  `docs/PLATFORM_ADMIN_OPERATIONAL_ALERTS_CONTRACT.md`.
- A separate platform-admin Support Workspace is implemented as tenant
  investigation with controlled internal case operations. It is distinct from tenant `support.html`, reuses only
  existing `/overview` and `/companies` APIs after the fresh `/me` gate, and
  links operators into existing company investigation pages. Support Cases
  Phase 1 is implemented for internal platform-admin use and verified in the
  main shared testing Supabase with fake/team data; this is not staging or
  production verification. Platform-admin Support Case Operations Phase 2 is
  implemented and verified only in the main shared testing Supabase with
  fake/team data. It adds operation-specific assignment, status, priority, and
  internal-note controls, a server-provided case timeline, and Migration 032
  trusted RPCs for atomic mutation/event/audit writes. Verified fake/team
  evidence covers assignment, status/priority changes, internal notes,
  no-op/invalid-transition rejection without extra event/audit rows,
  close/reopen `closed_at` behavior, least-privilege grants, RLS/policies, and
  service-role-only RPC execution. This is not staging or production
  verification. Platform-admin Tenant Communication Phase 3 is verified only
  in the main shared-testing Supabase with fake/team data: it adds tenant-visible reply composer/history, tenant support
  request history/detail, `tenant_reply_created` activity, safe reply audit
  metadata, and pending in-app support notification outbox records through
  Migration 033. This is not staging verification and does not establish
  production readiness. Live chat, external email, attachments, impersonation, billing
  actions, exports, charts, SLA timers, escalation automation, and production
  use remain blocked. The workflow contract is documented in
  `docs/PLATFORM_ADMIN_SUPPORT_WORKFLOW_CONTRACT.md`.
  Current prototype hardening is complete: Migration 043
  (`data/043_atomic_platform_support_case_creation.sql`) creates
  `platform_support_cases`, the initial `platform_support_case_events` row,
  and the `platform_admin_audit_events` create audit atomically through
  `public.create_platform_support_case(...)`; the application service no
  longer performs duplicate application-side create/audit inserts. Support-case
  detail history is bounded with `event_limit`/`event_offset` (default 25,
  maximum 100), tenant-visible replies use `limit`/`offset` (default 25,
  maximum 100), and reply-notification reads are restricted to notification
  rows linked to reply IDs on the returned page. Frontend Load More appends
  timeline events by `id`, replies by `reply_id`, and notifications by
  `notification_id`; not-found support-case and reply-list reads return the
  intended 404 instead of an audit-validation 503. The assignee endpoint now
  returns only `id`, `user_id`, `is_active`, `user_full_name`, and
  `user_email`; assignment still submits `platform_admin_users.id` mapping IDs,
  active mappings are the only selectable assignees, and inactive historical
  current assignees remain visible with a safe fallback without becoming
  assignable.
  SQL execution requires project/ref/environment preflight evidence. Migration
  029 controlled application/rollback evidence is recorded in the access
  lifecycle for the Supabase project that was labeled main/PRODUCTION; under
  the current environment interpretation, that evidence belongs to the
  prototype/shared-testing boundary and does not establish deployment to the
  future real production environment. Future SQL/testing is limited to
  confirmed local/dev, the approved prototype/shared-testing environment with
  fake/team data, or approved staging targets. Future real production remains
  blocked.
  Tenant support submission is governed by
  `docs/TENANT_SUPPORT_SUBMISSION_CONTRACT.md`; its backend endpoint and
  bounded frontend form are implemented locally. Migration 030 is applied and
  verified only in the main shared testing Supabase with fake/team data, and
  local browser/API E2E verification passed with fake data. This is not staging
  verification or production readiness; the platform-admin support-case tables
  and mappings were not modified.
  The read-only tenant-support intake viewer is implemented locally under
  `docs/PLATFORM_ADMIN_TENANT_SUPPORT_INTAKE_VIEWER_CONTRACT.md` with two
  GET-only routes and a separate Support Workspace section. No SQL was required;
  Migration 030 remains verified only in the main shared testing Supabase with
  fake/team data. This is not staging verification or production readiness.
  Tenant Support Intake Review/Conversion is implemented locally and verified
  only in the main shared testing Supabase with fake/team data. Migration 031
  was applied there and browser/API E2E passed locally: request 1 was reviewed
  then converted, producing internal case 2 exactly once. This is not staging
  verification or production readiness; production remains blocked.
- A separate platform-admin Audit Logs viewer is implemented as a read-only,
  application-only local extension. It adds one audited GET-only endpoint,
  `GET /api/platform-admin/audit-events`, displays actor mapping IDs and safe
  metadata summaries only, and does not expose raw metadata, tenant records,
  exports, downloads, charts, audit editing, audit deletion, or platform-admin
  user management. The original investigation inventory remains twelve
  GET-only routes; Support Cases now adds operation-specific bounded
  GET/POST/PATCH paths. Phase 2 and Phase 3 are verified only in the main
  shared-testing Supabase with fake/team data.
- A bounded platform-admin Billing Order History section is implemented as a
  read-only, application-only local extension on company detail. It adds one
  audited GET-only endpoint,
  `GET /api/platform-admin/companies/<company_id>/billing-orders`, lists safe
  mutable `company_subscription_orders` records only, displays `amount_sen` as
  integer sen as stored, returns no currency and infers no MYR, and excludes
  payment/gateway/checkout/reference, idempotency, raw-error, reconciliation,
  retry, activation, manual-credit, export/download, chart, and write behavior.
  The current read-only investigation inventory is twelve GET-only routes. The
  complete platform-admin surface additionally includes operation-specific
  bounded support-case, user-management, and company lifecycle mutation paths.
  Phase 2, Phase 3, Phase 4, and Phase 5 shared-testing evidence remains
  environment-scoped and does not establish staging or production readiness.
  The billing-order audit-filter fix changed frontend filtering only; it added
  no route or backend behavior change.
- Frontend performs a fresh `/me` authorization check on every page entry,
  clears cross-tenant state on denial or unavailability, and never trusts tenant
  roles, cached users, JWT claims, local flags, or hidden navigation
- Tenant pages now use a shared sidebar account menu below Billing for Profile,
  Support, and Logout. Support points to an authenticated tenant help page with
  a bounded local support-submission form. The optional Platform Administration
  menu item is discovered lazily through a live `/api/platform-admin/me` check,
  is not stored client-side, and remains hidden unless the backend authorizes
  it.
- Focused frontend source-contract tests cover endpoint restrictions, request
  cancellation, state clearing, safe rendering, accessibility, and responsive
  behavior
- `scripts/platform_admin_smoke_check.py` provides a read-only local/staging-
  ready HTTP smoke check for the current twelve-route investigation stack. It accepts the
  bearer token only from the environment, never prints response bodies or
  credentials, and does not establish staging verification or production
  readiness.
- Access request, revocation, replacement, and periodic-review procedure is
  documented in `docs/PLATFORM_ADMIN_ACCESS_LIFECYCLE.md`; it adds no access,
  mapping management, write controls, or production authorization.
- Platform-admin User Management Phase 4 is implemented locally with bounded
  directory/detail, add-existing-user, activate, and deactivate workflows.
  Migration 034 is applied and structurally verified only in the approved main
  shared-testing Supabase with fake/team data. Company 29 is explicitly
  registered as the protected internal company for main shared-testing only;
  it is not a staging or production designation and is not hardcoded into the
  application. Shared testing currently has only one active user in company 29,
  user 32, and that user already has the sole platform-admin mapping, so the
  successful create-mapping shared-testing E2E remains pending until a second
  approved active fake/team user exists. Migration 035 is applied and verified
  only in the approved main shared-testing Supabase with fake/team data; it
  corrected only the Phase 4 RPC audit endpoint metadata, preserved RPC
  ownership/security/EXECUTE posture, did not create mappings, did not create
  Phase 4 mutation audit events merely by application, and did not alter
  existing audit rows. Staging verification and production readiness remain
  blocked. Migration 044
  (`data/044_platform_admin_user_recent_activity_batch.sql`) is applied and
  runtime verified in prototype/shared-testing only. It eliminates the
  platform-admin directory recent-activity N+1 pattern: before, the directory
  used one mapping query, one users query, and N audit queries; now it uses one
  mapping query, one users identity batch query, and one
  `get_latest_platform_admin_activity` RPC. The
  `recent_platform_admin_activity_at` field means the latest
  `platform_admin_audit_events.created_at` for that platform-admin mapping, or
  explicit null when no audit activity exists. It is not last login, user
  activity, mapping `updated_at`, or account modification time.
- Platform-admin Tenant and Company Administration Phase 5 is implemented and
  verified for the current milestone in the approved main shared-testing
  Supabase with fake/team data. It includes the global company directory,
  Company Detail investigation, company users and chatbot/configuration
  inspection, current subscription context, subscription history, AI-credit
  usage and transaction history, billing-order history, controlled
  suspend/restore, protected internal-company safeguard, centralized inactive-
  company operational enforcement, Company Detail support-history integration,
  company-filtered Support Workspace navigation, and company-related Platform
  Admin audit navigation. Migration 036 is applied and verified only in the
  approved main shared-testing Supabase with fake/team data. It constrains
  `companies.status` to non-null `active`/`inactive`, keeps `companies` RLS
  disabled and not forced, tightens direct companies privileges to no browser-
  role access and service_role `SELECT`, `INSERT`, and `UPDATE` only, and
  exposes service-role-only `SECURITY INVOKER` suspend/restore RPCs with
  `search_path=pg_catalog`.
  Shared-testing lifecycle evidence includes the earlier company 23
  suspend/restore cleanup with audit events 355 and 356, plus controlled
  runtime verification on approved fake/team company 34, `Autobot Company`,
  chatbot 52. Company 34 was suspended and restored twice and left active:
  audit events 527/538 covered the representative runtime matrix, and audit
  events 541/542 covered the final targeted `/api/chat/test` repair check.
  Representative live checks verified chatbot mutation, knowledge mutation,
  `POST /upload-pdf`, Telegram config mutation, and `/api/chat/test` reject
  suspended companies with `403 company_suspended` while preserving intended
  Platform Admin reads, tenant support/history reads, and safe knowledge
  graph/README reads. PDF upload rejection occurs before file processing,
  quota checks, `save_uploaded_pdf`, embeddings, chunks, graph generation,
  README/history generation, chatbot runtime changes, and persona derivation.
  The final test-chat check confirmed AI usage rows stayed `0`, AI-credit
  transaction count stayed `3`, included balance stayed `20000000` micro-MYR,
  top-up balance stayed `0`, no provider execution occurred, and chatbot
  runtime/configuration was unchanged. Protected company 29 rejected suspend
  with `protected_company` and remained active. CRM mutation was not exercised
  live because company 34 had no suitable CRM lead and no risky data was
  manufactured; local automated CRM enforcement coverage exists. Phase 5 does
  not provide tenant impersonation, arbitrary tenant data access, raw tenant
  messages, AI prompts/responses, provider payloads, API credentials, payment
  secrets, unrestricted configuration inspection, financial mutations, true
  tenant application audit history, Phase 4 account-management expansion,
  duplicate Phase 6 monitoring, or Phase 7 financial mutation controls.
  Staging verification and production readiness remain blocked.
- Platform-admin Platform Monitoring Phase 6 is implemented locally as a
  read-only extension of `GET /api/platform-admin/overview`; no new
  platform-admin mutation routes were added.
  It adds platform summary, support operations, messaging and integration
  health, billing attention, AI usage and credits, and platform-admin activity
  aggregates, plus deterministic aggregate alerts for support backlog, pending
  and reconciliation-required billing orders, depleted AI-credit balances,
  retry backlog, and integration channel attention. Existing subscription
  alerts remain. Read-only inspection in the approved main shared-testing
  Supabase with fake/team data confirmed all required monitoring tables and
  fields exist and current index coverage is sufficient for the first
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
  The current milestone also verifies the local repository/source tests and a
  full Platform Admin browser suite for the visual dashboard and Superadmin UI
  polish. The dashboard is intentionally a concise operations summary rather
  than a full analytics explorer: detailed investigation remains on Companies,
  Company Detail, Support, Billing, and Audit Logs. It preserves read-only
  aggregate visibility into company counts, active users, support workload,
  support status, operational alerts, messaging delivery/channel health, retry
  backlog, AI request/token activity, depleted AI-credit balance signals,
  billing/order attention, companies requiring attention, and aggregate
  platform-admin activity. It deliberately excludes unsupported SLA/overdue
  metrics, generic failed-job monitoring, fabricated trends, real-time online
  users, detailed provider incident telemetry, financial mutation controls, raw
  message content, AI prompt/response content, raw audit metadata, and raw
  financial/provider payloads. The Superadmin workspace now has a more
  consistent operational UI across Dashboard, Companies, Company Detail,
  Support, Billing, Audit Logs, and Platform Admin Management, including shared
  page hierarchy, improved panels/tables/cards, clearer filters, mobile card
  alternatives, responsive behavior, and reduced dashboard information density.
  This is not staging verification and does not establish production readiness.
  Unsupported aggregate values fail closed.
- Platform-admin Billing & Subscription Oversight Phase 7 is implemented for
  the current read-only milestone as a Platform Billing & Subscriptions page with
  `GET /api/platform-admin/billing/overview` and
  `GET /api/platform-admin/billing/companies`. Migration 038 is applied and
  verified only in the approved main shared-testing Supabase with fake/team
  data. No additional Phase 7 billing migration beyond Migration 038 was
  required; Migration 043 belongs to the later atomic support-case creation
  hardening. Migration 038 adds
  `public.get_platform_admin_billing_overview()`,
  `public.get_platform_admin_billing_companies(integer, integer, text, text,
  boolean)`, and updates `public.get_platform_admin_monitoring_overview()` so
  `platform_admin.billing.overview.read`, `platform_admin.billing.company_list`,
  `platform_billing_overview`, and `platform_billing_companies` are included in
  Platform-admin Activity. Local runtime verification returned 200 for
  `/api/platform-admin/me`, `/api/platform-admin/overview`,
  `/api/platform-admin/billing/overview`, and
  `/api/platform-admin/billing/companies?limit=25&offset=0`; the frontend
  rendered Subscription status, Plan distribution, Active plan catalogue,
  Subscription order attention, AI-credit top-up attention, AI Credit Overview
  with MYR-formatted balances, Billing Notifications, Subscription lifecycle,
  and Tenant Billing Directory. Companies without subscriptions are included
  with `subscription_status = null`, `current_plan = null`, null period dates,
  and false pending/cancellation flags. Filtering, counting, stable
  `company_id ASC` ordering, and pagination happen inside PostgreSQL.
  Responsive/accessibility hardening was verified locally through source and
  Playwright browser tests: desktop tables remain available, mobile Billing
  overview and Tenant Billing Directory cards remain visible below 767px, the
  directory filters have explicit labels for Subscription status, Plan code,
  and Attention, hostile Billing values render as text, and mobile View Company
  navigation opens `platform-admin-company.html?company_id=<id>`. Latest focused
  evidence is 54 frontend source tests with 14 subtests, a 5-test Billing
  browser group, and a 70-test full Platform Admin browser suite. A broader
  Phase 7 regression scope previously passed with 153 tests and 271 subtests.
  Phase 7 remains read-only: manual AI-credit adjustment, payment
  reconciliation mutation, refund, subscription correction/override, manual
  plan change, direct balance editing, payment retry mutation, manual credit
  reversal, and billing impersonation/remediation controls remain deferred.
  Direct balance editing is not appropriate for this milestone. Subscription
  history is persisted `company_subscriptions` records, not a true
  event-sourced plan/status transition history. This is not staging
  verification and does not establish production readiness.
- The lifecycle document now includes a redacted access, revocation, smoke,
  audit-log, and localhost/staging/production evidence checklist; it does not
  change the current local-only verification boundary.
- Local smoke evidence recorded on 2026-08-03 against localhost
  (`http://127.0.0.1:8000`): all twelve checks passed with an approved company
  ID; the four required checks passed and child checks were correctly skipped
  without a company ID; and removing `PLATFORM_ADMIN_TOKEN` failed safely with
  the required configuration error. This remains localhost evidence only and
  requires an approved environment and token for any local/staging use.

### Local read-only investigation coverage checklist

This checklist describes the current localhost-only investigation surface. It
does not establish staging verification or production readiness; production
remains blocked.

| Route | Purpose and safe read-only coverage | Intentionally excluded |
|---|---|---|
| `/me` | Confirm current platform-admin identity and active mapping shape | Tenant-role authority, token details, mapping management |
| `/overview` | Show company/subscription summaries and typed operational alerts; the Super Admin overview now visualizes plan and status counts | Writes, exports, global activity, remediation |
| `/audit-events` | List safe audit-event summaries, filters, actor mapping IDs, and approved metadata fields | Raw payloads, secrets, exports, editing, deletion, retention controls |
| `/companies` | Search, filter, sort, and page safe company directory fields | Customer content, mutations, bulk actions, deletion, export |
| `/companies/<company_id>` | Inspect safe company profile and status fields | Full tenant records, impersonation, edits, customer content |
| `/companies/<company_id>/subscription` | Read current subscription summary and safe plan fields | Activation, plan changes, cancellation, payment actions |
| `/companies/<company_id>/subscription-history` | Read persisted subscription history rows and safe plan/status fields | Guaranteed event-sourced timeline, reconciliation, lifecycle changes |
| `/companies/<company_id>/ai-credit-usage` | Read current-period balance, usage summary, and safe period fields | Credit adjustment, charging, provider economics, raw usage payloads |
| `/companies/<company_id>/ai-credit-transactions` | Read safe ledger deltas, balances, transaction types, and periods | Manual credit, reversal, payment references, provider payloads |
| `/companies/<company_id>/billing-orders` | Read safe order status, amount-in-sen, plan, activation, and lifecycle timestamps | Payment/gateway details, checkout, retry, reconciliation, manual credit |
| `/companies/<company_id>/users` | Read safe company-user identity, role, status, and timestamps | User management, role changes, credentials, invitations |
| `/companies/<company_id>/chatbots` | Read safe chatbot identity, state, configuration summary, and timestamps | Bot edits, messaging, credentials, deployment, customer content |
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

Additional current blockers are the absence of a confirmed staging/online
environment in repository configuration, lack of staging verification for the
latest extensions, pending production ownership/executor approval, and pending
monitoring, rollback, and backup evidence.

## Guided Knowledge Ingestion, Derived Persona, and Conversation Memory

**Status: Implemented locally; unmerged; three of four workstreams blocked;
migrations unapplied everywhere**

All of this work exists in the working tree only. No migration in the
`039` → `040` → `041` sequence has been applied to any environment, and two of
the three have a mandatory SELECT-only preflight that has not been run. Full
detail, including the client-facing override procedure and the operator
migration runbook, is in `docs/KNOWLEDGE_INGESTION_AND_DERIVED_PERSONA.md`.

- `POST /api/knowledge/ingest` runs the four website-scraping stages in one
  call with per-source per-stage progress and partial success. Gated on
  `batch_website_scraping` and the knowledge-file quota, checked before the
  billed extraction. Review verdict is BLOCK on three grounds: no wall-clock
  bound and no idempotency key on a synchronous run that can exceed any proxy
  window; a source that reports `succeeded` with zero chunks persisted while
  storage is charged; and websites only, with no uploaded-document support.
  The earlier staged batch-route storage-quota skip has been fixed by passing
  authenticated `company_id` into `scrape_website_urls_batch`, but the
  synchronous/idempotency and zero-chunk-success limitations remain.
- Persona derivation fills `company_name`, `business_description`, and `tone`
  from the client's own uploaded document, tagging each `client_entered` or
  `derived` in `bot_configs.persona_provenance`. A client edit flips the marker
  and re-ingestion then leaves the value alone permanently. The override
  procedure is the one clean, shippable part of this work.
- The derived persona does not reach generated replies for a bot whose
  `chatbots.deployed_profile_name` is blank, which is the population the feature
  targets. A residual stored prompt-injection risk remains: the structural lever
  is closed, the semantic one is not.
- Conversation graph memory persists mid-chat facts and recalls them by exact
  keyword beside the vector path, adding no LLM call and no billing change.
  Blocked on an uncertified migration, a write path that is not tenant-filtered,
  single-ASCII-token exact-match recall, and unexpiring raw customer PII.
- Recorded focused test evidence at the current working tree: 73 + 32 + 14
  persona, 35 (plus 16 subtests) conversation memory, 41 + 19 ingestion routes.
  Real-browser Playwright coverage for the derived persona exists as
  `tests/browser/testbot-persona.spec.js`. This is local evidence against a
  working tree; it is not staging verification and not production readiness.

## Platform Limitations

| Limitation | Status |
|---|---|
| Single-call website ingestion | Blocked. Synchronous run is unbounded and non-idempotent; `succeeded` can mean zero chunks persisted; websites only, no uploaded documents |
| Derived persona reaching replies | Blocked for bots with a blank `chatbots.deployed_profile_name`; requires separate create-RPC/promotion work |
| Conversation memory recall quality | Exact match on a single ASCII token; only `name`, `contact`, and `interest` are extracted |
| Conversation memory PII retention | No expiry; cleanup only by conversation or chatbot cascade |
| Migrations 039/040/041 | Unapplied everywhere; two mandatory preflights unrun |
| Platform-admin controls | Original five-endpoint backend/frontend verified in staging. Later extensions have mixed evidence: some remain local/application-tested only, while Phase 5, Phase 6, Phase 7, and Migration 043/044 hardening paths have prototype/shared-testing runtime verification where explicitly recorded. Later extensions are not automatically staging verified, and real production remains blocked |
| Platform-admin Support Workspace | Implemented as tenant investigation with controlled internal case operations; Support Cases Phase 2/Migration 032 and Tenant Communication Phase 3/Migration 033 are verified only in main shared testing Supabase with fake/team data. No live chat, generic messaging, impersonation, billing actions, exports, charts, SLA automation, staging readiness, or production use |
| Platform-admin Tenant and Company Administration | Implemented and verified for the current milestone in main shared-testing Supabase with fake/team data. Includes company directory/detail investigation, users/chatbots, subscription and AI-credit context/history, billing orders, support-history integration, company-filtered audit navigation, controlled suspend/restore, protected-company safeguard, and centralized inactive-company enforcement. Company 34 (`Autobot Company`, chatbot 52) was suspended/restored and left active; representative chatbot, knowledge, PDF upload, Telegram config, and `/api/chat/test` inactive checks returned `403 company_suspended` without side effects. Company 29 protected suspend returned `protected_company` and remained active. CRM mutation was not live-tested because no suitable CRM lead existed; local coverage exists. It does not provide tenant impersonation, true tenant application audit history, financial mutations, staging readiness, or production use |
| Platform-admin Tenant Communication | Verified only in main shared-testing Supabase with fake/team data; Migration 033 adds tenant-visible replies, `tenant_reply_created` case events, safe reply audit metadata, and a pending in-app support notification outbox. This is not staging verification and does not establish production readiness; email and attachments remain deferred |
| Automatic recurring billing | Deferred pending HitPay recurring-card event, cancellation, and correlation validation; FPX, DuitNow, and Touch 'n Go remain manual renewal methods |
| Email/SMS delivery | Deferred (no provider) |
| Direct tenant support contact/tickets | Implemented locally as bounded submission plus tenant-visible reply history for the signed-in requester; no live chat, email, attachments, staging readiness, or production use |
| Platform-admin tenant support intake viewer | Implemented locally as separate read-only GET list/detail routes and Support Workspace section; no mutation, conversion, reply, export, staging verification, or production use |
| Platform-admin tenant support intake review/conversion | Runtime code and Migration 031 verified only in main shared testing Supabase with fake/team data; case 2 conversion, safe audit metadata, service-role-only RLS/EXECUTE, and mapping baseline verified; not staging or production-ready |
| PDF receipts | Open (HTML only) |
| Cross-company dashboard | Bounded read-only operational aggregates now feed Super Admin plan/status charts and payment follow-up bars through the existing operations/billing overview APIs. Browser tests and the local application with live Supabase records are verified; see the 7 September rollout evidence. Generic/unrestricted cross-company analytics, arbitrary global drilldowns, unrestricted exports, unrestricted tenant browsing, and generic remediation/write controls remain deferred |
