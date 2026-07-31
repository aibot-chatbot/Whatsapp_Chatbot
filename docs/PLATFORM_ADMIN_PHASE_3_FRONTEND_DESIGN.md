# Platform Admin Phase 3: Read-Only Frontend Design

## Status and scope

**Verified complete in staging; production blocked.** The platform-admin
database migrations, five read-only backend endpoints, and Phase 3 frontend
are verified in staging. The approved mapping was temporarily reactivated for
browser verification, then revoked again. The mapping row remains present and
inactive. Production deployment remains blocked.

A later application-only extension added two additional read-only company-detail
inspection endpoints and lazy frontend sections for users and chatbots. A
subsequent bounded application-only operations phase added
`GET /api/platform-admin/overview` for read-only company counts,
latest-subscription status counts, latest-subscription plan distribution, and
at most 10 past-due/expired attention companies. These extensions are locally
tested only unless separately staged and recorded. A later bounded
application-only investigation phase added one lazy read-only subscription
history endpoint and frontend section. It lists persisted
`company_subscriptions` records only; it is not an event-sourced timeline and
does not claim every status transition is preserved as a separate row. A later
application-only AI-credit investigation phase added one lazy read-only
AI-credit transaction-history endpoint and frontend section for persisted
`ai_credit_transactions` ledger rows. It excludes provider economics, payment
references, idempotency keys, AI-usage-log links, subscription IDs,
descriptions, and raw ledger row payloads. A later application-only audit-log
viewer phase added one read-only audit-log endpoint and page for safe
platform-admin audit event summaries only; it returns actor mapping IDs only
and omits raw metadata, tenant records, exports, downloads, charts, audit
editing, and audit deletion. The current application-only billing-order
history phase adds one lazy company-detail investigation section and one
GET-only endpoint for safe `company_subscription_orders` fields. Billing orders
are mutable operational records rather than an event-sourced payment timeline;
the section shows `amount_sen` as integer sen only and does not return or infer
currency. The current application-only Operational Alerts Phase 1 extends the
existing dashboard and `/api/platform-admin/overview` response only; it adds no
endpoint and no page.

The original Phase 3 frontend pass did not add endpoints, reactivate a mapping,
change users.role, alter migrations, or deploy anything. Subsequent
application-only extensions added seven GET-only endpoints for users, chatbots,
the operations overview, subscription history, AI-credit transaction history,
audit-log viewing, and billing-order history. Flow Builder, Broadcast,
tenant administration,
impersonation, exports, messaging, reconciliation, credit adjustments, and
subscription changes remain out of scope.

## Final implementation notes

- Three standalone pages implement the dashboard, company directory, and
  company detail information architecture described below.
- A dedicated shell performs a fresh `/api/platform-admin/me` check before any
  page controller can request company data. Platform authorization is never
  inferred from tenant roles, JWT claims, cached users, or local UI flags.
- The client originally exposed the five Phase 3 GET operations. Subsequent
  application-only read-only extensions added the operations overview plus two
  lazy company-detail inspection operations for company users and chatbots, and
  lazy subscription-history, AI-credit transaction-history, and billing-order
  history operations. All twelve operations use the normal
  authenticated session token mechanism.
- An in-memory request registry, abort controllers, and a monotonically
  increasing page epoch prevent replaced or late requests from restoring
  cleared cross-tenant data.
- API-derived values are rendered through DOM text properties. Platform data
  is not placed in browser storage, URLs, logs, or raw error messages; only the
  validated numeric company ID is used in detail-page navigation.
- The dashboard performs one audited `GET /api/platform-admin/overview` request
  after `/me`. It reports company counts, latest-subscription status counts,
  latest-subscription plan distribution, and past-due/expired attention
  companies plus typed read-only operational alerts derived from that same
  attention data. Operational Alerts Phase 1 includes only subscription
  past-due and expired alerts. It does not include no-subscription counting,
  inactive-company alerts, platform-wide AI-credit alerts, billing-order
  attention alerts, no-current-chatbot alerts, order review, global activity,
  usage aggregation, charts, exports, or write controls.
- Focused source-contract coverage is implemented in
  `tests/test_platform_admin_frontend.py`. The browser-based staging pass is
  also complete.
- Executable local browser regression coverage now runs through Playwright
  against the actual static frontend pages and JavaScript. The browser tests
  serve `frontend/` locally, mock `/api/platform-admin/*` responses, and do not
  require Supabase, real JWTs, staging data, or production data.
- A subsequent tenant-application UI hardening pass added a shared
  `tenant-account-menu` component for authenticated tenant pages. It moves
  Profile and Logout out of the ordinary tenant sidebar while preserving the
  platform-admin console's own **Return to Tenant App** control. The optional
  **Platform Administration** menu item is discovered lazily with a live
  `GET /api/platform-admin/me` request when the menu opens; this visibility
  check is convenience-only and does not replace the fresh `/me` gate on
  `platform-admin.html`.
- The shared account menu now includes **Support**, pointing to
  `frontend/support.html`. This destination is a static authenticated tenant
  help page with self-service guidance and local account/product links only. It
  has no support-submission backend, ticket creation, email sending, external
  contact link, platform-admin authorization behavior, or cross-tenant data.
- A later bounded frontend-only platform-admin extension added a distinct
  **Support Workspace** at `frontend/platform-admin-support.html`. It is not the
  tenant Support page. It runs through the same fresh `/api/platform-admin/me`
  page gate, reuses only the existing `GET /api/platform-admin/overview` and
  `GET /api/platform-admin/companies` APIs, highlights attention companies, and
  links to `platform-admin-company.html?company_id=<id>` for existing read-only
  company investigation. It adds no backend endpoint, keeps the platform-admin
  backend inventory at ten GET-only routes, and does not add ticketing, case
  notes, assignment, billing-order history, audit-log viewing, messaging,
  impersonation, reconciliation, subscription changes, AI-credit adjustments,
  exports, or other write controls.
- A later bounded read-only platform-admin extension added **Audit Logs** at
  `frontend/platform-admin-audit-events.html`. It runs through the same fresh
  `/api/platform-admin/me` page gate, uses the new
  `GET /api/platform-admin/audit-events` endpoint, displays only safe audit
  event summaries with actor mapping IDs, and keeps the platform-admin backend
  inventory at eleven GET-only routes. It adds no audit editing, deletion,
  export, download, charts, raw metadata viewer, platform-admin user
  management, or other write controls.
- The current bounded read-only platform-admin extension adds **Billing
  orders** as a lazy company-detail section backed by
  `GET /api/platform-admin/companies/<company_id>/billing-orders`, bringing the
  platform-admin backend inventory to exactly twelve GET-only routes. It is
  company-context only, support-investigation oriented, and application-only
  unless later staged. It returns `amount_sen` as integer sen only, never
  returns or infers currency, and excludes payment/gateway/checkout/reference,
  idempotency, raw-error, reconciliation, retry, activation, manual-credit,
  export, download, chart, and write behavior.

## Verification evidence

- Current local mocked Playwright platform-admin browser suite: 45 passed after
  the billing-order history extension. It
  covers the
  original Phase 3 flows plus the later lazy read-only users/chatbots company
  inspection extension, the lazy read-only subscription-history section, and
  the lazy read-only AI-credit transaction-history section, the lazy read-only
  billing-order history section, the operations overview dashboard, the Support
  Workspace, and the Audit Logs page, including
  safe rendering, child-list 404 stale-state clearing, active sibling-request
  cancellation, late-response suppression, one overview request after `/me`,
  empty attention state, stale overview clearing on denial/unavailability,
  `/me` before audit-event reads, audit-log pagination and filters, metadata
  allowlist rendering, stale audit-row clearing, sen-only amount display,
  billing-order filter/pagination requests, child 404 stale-state clearing, and
  stale billing-order response suppression.
  These local mocked tests do not prove staging or production behavior.
- Historical local mocked Playwright platform-admin browser suite result before
  the users/chatbots extension: 18 passed.
  `tests/browser/platform-admin.spec.js` covers access gating, denial and
  unavailable states, stale-data clearing, request lifecycle, dashboard overview,
  directory controls, detail loading order, safe text rendering, navigation,
  role-independence, and read-only boundary checks.
- Current local mocked Playwright tenant account-menu browser suite: 25 passed.
  `tests/browser/tenant-account-menu.spec.js` covers shared placement,
  sidebar cleanup, keyboard and outside-click behavior, lazy platform-admin
  discovery, 401/403/503/network outcomes, duplicate-request suppression,
  reload rechecks, local-role/flag non-authority, navigation, mobile
  sidebar/menu collision prevention, late-rendered sidebar mounting,
  dashboard date/account-menu responsive overlap prevention, readable mobile
  date display, temporary open-state layout adjustment and restoration after
  closing, public/platform page exclusion, and read-only boundaries.
- Current focused platform-admin frontend source-contract suite: 41 passed,
  10 subtests passed.
- Current focused platform-admin Python suite: 159 passed, 396 subtests passed.
- Earlier recorded combined platform-admin backend/frontend and
  authentication/security regressions: 88 passed, 114 subtests passed.
- Earlier recorded full safe suite: 1,421 passed, 1 skipped, 125 subtests
  passed.
- All five dedicated platform-admin JavaScript files pass the available Node.js
  syntax check.

Local browser command:

```powershell
& 'C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' node_modules\@playwright\test\cli.js test --reporter=line
```

In this repository, Playwright is configured to launch the locally installed
Chrome channel and a test-owned static server. Browser binaries are not stored
in the repository. pnpm is the recorded package manager for this test
infrastructure. In a normal developer shell with Node on `PATH`,
`pnpm run test:platform-admin-browser -- --reporter=line` can be used. CI still
needs a Windows or Linux browser/runtime decision before these tests can be
required in automated pipelines.

Tenant account-menu browser command:

```powershell
& 'C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' node_modules\@playwright\test\cli.js test tenant-account-menu.spec.js --reporter=line
```

In a normal developer shell with Node on `PATH`,
`pnpm run test:tenant-account-menu-browser -- --reporter=line` can be used.

### Completed staging browser verification

The approved staging mapping was temporarily reactivated solely for this
verification. No live token, API response body, screenshot, or sensitive
customer information is recorded here.

- The platform dashboard loaded and displayed the **Platform Administration**
  label, **Internal / Read Only** badge, authorized operator identity, and exact
  total, active, and inactive company counts.
- The company directory loaded with search, status filtering, sort field, sort
  order, page size, company rows, and working **View details** links.
- The approved staging company detail loaded its safe company profile,
  subscription summary, and AI-credit/usage sections.
- No mutation, export, impersonation, messaging, subscription-change, payment,
  or credit-adjustment controls were present.
- **Return to Tenant App** and **Logout** controls were present.
- The mapping was revoked immediately after testing. Refreshing the dashboard
  then showed the fixed **Access Denied** state, with no stale platform data
  remaining visible.
- The mapping row remains present and inactive. Nothing was deployed to
  production.

Production remains blocked by the Phase 1.5 gates: production executor and
ownership approval, protected-company lifecycle controls, production bootstrap
approval, audit metadata/redaction rules, retention/archival policy, and the
append-only enforcement decision beyond grants.

Historical clarification: the append-only decision language reflects the Phase
3 status at the time. Migration 026 later implemented Option C, a
staging-verified database trigger that rejects UPDATE and DELETE on
`platform_admin_audit_events`; see the Phase 4 production-readiness document
for the current production gate.

## Current frontend findings

### Application structure and routing

The frontend is a static multi-page application under `frontend/`. Each page is
a standalone HTML document with mostly inline page CSS and JavaScript. Shared
assets are limited to:

- `frontend/assets/js/auth.js` for session checks and authenticated fetches;
- `frontend/assets/js/shared-ui.js` for a small set of UI helpers;
- `frontend/assets/css/shared-glass.css` for cards, buttons, and shared visuals;
- `frontend/sidebar-component.js` for the tenant navigation custom element.

There is no frontend router, bundler, or component framework. Navigation uses
relative `.html` links and query parameters such as `?bot_id=<id>`. Flask's
non-API 404 fallback serves files from `frontend/`; API 404s are kept separate.

### Authentication and token storage

Successful password and Google login store these values in `sessionStorage`:

- `token` — the application JWT;
- `user` — a cached user object;
- `isLoggedIn` — a UI session marker.

`requireLogin()` checks only that a token exists and redirects to `login.html`
when it does not. `authenticatedFetch()` reads the same session token and adds
the `Authorization: Bearer <token>` header. It invokes logout on HTTP 401 and
recognizes the existing deactivated-account 403 message. `logout()` removes the
token, cached user, and login marker before redirecting.

The cached `sessionStorage.user.role` is used by `requireAdminOrOwner()` and the
tenant sidebar to hide or redirect tenant-only UI. That mechanism is a
presentation convenience, not authoritative security, and must never be used
for platform access. No platform claim or platform flag should be stored in
either session or local storage.

### Navigation

Most authenticated pages render `<chatbot-sidebar>`. The component determines
the current static page from `window.location.pathname`, propagates `bot_id`,
and conditionally renders tenant items from the cached tenant role. It includes
tenant Billing, Team Members, Flow Builder, Broadcast, and bot-scoped links.

This component is unsuitable for the platform surface because it:

- is visually and structurally tenant-oriented;
- uses a locally cached tenant role for menu visibility;
- propagates tenant bot context;
- exposes tenant operations that are unrelated to platform administration.

### API and response handling

Pages call `authenticatedFetch()` directly and interpret the backend's
`status`/`data` response convention themselves. Loading, empty, and error states
are implemented per page. Some existing pages render backend `message` values
or log caught errors with `console.error`; the platform surface must instead map
known status/code combinations to fixed public messages and must not log API
bodies, authorization headers, raw errors, or Supabase details.

### Tables, pagination, search, and modals

- CRM supplies the clearest responsive table/filter styling, with native
  controls, table wrappers, empty rows, and keyboard handlers.
- Profile billing history demonstrates offset/limit pagination and
  `pagination.has_more`, although it uses a Load More pattern rather than page
  navigation.
- Bots and billing sections demonstrate explicit loading, empty, and generic
  failure panels.
- Modals are page-specific rather than shared. The initial platform frontend
  needs no modal because it has no mutation or edit action.
- Search patterns are inconsistent and mostly client-side. The platform company
  directory must use the backend's server-side search and validation.

### Responsive and accessibility conventions

Existing pages generally switch the body to a column layout around 768px,
reduce content padding, wrap toolbars, and place tables in horizontally
scrollable containers. Some pages use `aria-live`, native labels, dialog roles,
and keyboard handlers, but these conventions are not centralized.

Phase 3 should reuse the visual language while improving consistency: semantic
landmarks, visible focus, native buttons/links, `aria-live` status regions,
`aria-sort` on sortable headers, and a deliberate mobile directory layout.

## Recommended information architecture

Create a separate three-page static surface:

| Frontend page | Purpose | Backend calls after authorization |
|---|---|---|
| `platform-admin.html` | Platform operations dashboard | `/me`; `/overview` |
| `platform-admin-companies.html` | Paginated company directory | `/me`; `/companies` |
| `platform-admin-company.html?company_id=<id>` | Company, subscription, AI-credit detail, lazy subscription-history and AI-credit transaction inspection, and lazy read-only users/chatbots inspection | `/me`; company detail; subscription; AI-credit usage; lazy subscription history; lazy AI-credit transactions; lazy users; lazy chatbots |
| `platform-admin-support.html` | Read-only Support Workspace investigation hub | `/me`; `/overview`; bounded `/companies` lookup |
| `platform-admin-audit-events.html` | Read-only Audit Logs viewer for safe platform-admin audit event summaries | `/me`; `/audit-events` |

Every page independently runs the `/api/platform-admin/me` authorization gate
before revealing the platform shell or making any company request. A static
HTML URL being discoverable is not a grant of access.

### Entry and tenant navigation

The safest initial entry is a separately distributed internal URL to
`platform-admin.html`. Do not add a platform link to the ordinary tenant sidebar
in the first implementation. Adding such a link would either trust local role
state or require `/me` checks across ordinary tenant pages, creating unnecessary
denials and audit events.

If a tenant-navigation entry is considered later, it may appear only after a
successful live `/me` response in that page session. Hidden menu state remains
non-authoritative, and the destination must repeat the `/me` check.

### Dedicated navigation and visual identity

Use a dedicated platform shell, not `<chatbot-sidebar>`. It should display:

- a shield/building mark and the exact label **Platform Administration**;
- a persistent **Internal / Read Only** badge;
- Dashboard and Companies links only;
- the authorized platform identity from `/me` after the gate succeeds;
- a clear **Return to Tenant App** link to `bots.html`;
- an explicit Logout button that clears in-memory platform state and invokes
  the normal logout mechanism.

Use a distinct accent from tenant administration while retaining the existing
Outfit typography and dark glass-card system. Do not render links for tenant
billing administration, Flow Builder, Broadcast, impersonation, export, credit
adjustment, subscription changes, reconciliation, or messaging.

## Authorization and page-entry design

All platform documents begin in a blocking `checking_access` state. Company
content must not exist in the visible DOM before authorization succeeds.

```text
require normal login token
  -> GET /api/platform-admin/me with the normal session JWT
  -> 200: store identity in memory and reveal platform shell
  -> 401: clear platform state, perform normal logout, go to login
  -> 403: clear platform state and show stable access-denied screen
  -> 503/network: clear platform state and show unavailable screen
```

The frontend must not decode the JWT, inspect `sessionStorage.user.role`, read a
platform flag, or infer access from a previously visible link. Only a current
200 response from `/me` opens the page.

The identity response is held in JavaScript memory only. Each platform page
reload or cross-page navigation repeats `/me`; no platform authorization result
is persisted.

## Page designs

### A. Platform operations dashboard

Header:

- **Platform operations**;
- read-only overview of tenant and subscription health;
- company directory navigation.

Operations summary uses `GET /api/platform-admin/overview` only after `/me`.
The backend counts latest subscriptions per company using the same latest-row
semantics as company detail: `created_at DESC`, then `id DESC`. The dashboard
renders total/active/inactive companies, trialing/active/past-due/expired
subscription counts, plan distribution, and a past-due/expired attention list
linking to existing company detail pages. Do not calculate revenue, order
review, subscription-order reconciliation, no-subscription counts, AI-credit
balances, resource-limit proximity, global audit activity, usage aggregation,
charts, exports, or write controls.

Operational Alerts Phase 1 extends this same dashboard and overview response
without adding a new endpoint or page. It converts the existing
past-due/expired attention-company rows into typed read-only alert rows:
`subscription_past_due` with warning severity and `subscription_expired` with
critical severity. Alerts link only to
`platform-admin-company.html?company_id=<id>` for existing investigation. The
Support Workspace remains unchanged and may continue consuming
`attention_companies`. AI-credit alerts, billing-order attention alerts,
inactive-company alerts, no-current-chatbot alerts, charts, exports, write
actions, reconciliation, checkout recovery, retry payment, manual crediting,
activation, plan changes, messaging, ticketing, and impersonation remain
deferred.

The original Phase 3 dashboard intentionally avoided adding a backend aggregate
endpoint and used company-list requests for local UI counts. That behavior is
historical. The current operations overview extension uses one audited
read-only endpoint for the dashboard summary instead of three company-list count
requests. Company totals remain explicit backend values; do not assume total
equals active plus inactive because the schema does not enforce a two-status
check.

### B. Company directory

Controls:

- search input, trimmed and limited to 100 characters;
- status: All, Active, or Inactive;
- sort field: Created, Company Name, Status, or ID;
- sort order: Ascending or Descending;
- page size: 25, 50, or 100;
- Previous and Next controls derived from backend pagination.

Backend parameters remain authoritative:

- `limit`: 1–100, default 25;
- `offset`: non-negative, default 0;
- `status`: omitted, `active`, or `inactive`;
- `sort_by`: `created_at`, `company_name`, `status`, or `id`;
- `sort_order`: `asc` or `desc`;
- `search`: 1–100 trimmed characters when present.

Do not silently clamp or translate invalid values outside that contract. Search
is debounced by 350 milliseconds, resets offset to zero, and aborts the prior
list request. The raw search text stays in memory and is not written to storage,
console logs, analytics, or audit metadata. Non-sensitive status/sort/page state
may use URL parameters; search should not enter browser history.

Desktop table columns:

- ID;
- company name;
- business type;
- status;
- contact email;
- created date;
- a single **View details** link.

No row selection, action menu, edit button, delete button, export, or bulk
control is present. On narrow screens, use labelled stacked rows/cards rather
than forcing users to interpret an excessively wide table.

Pagination text should expose `returned`, `total`, and the visible range without
recomputing server totals. Disable navigation while a request is in flight and
when no previous/next page exists.

### C. Company detail

Read `company_id` from the page query, accept only a positive safe integer, and
use that value for all three backend resource paths. Never substitute the JWT
company ID, cached tenant company, company name, or list position.

Request order:

1. authorize with `/me`;
2. load `/companies/<company_id>`;
3. only after company existence succeeds, load subscription and AI-credit usage
   in parallel for the same ID.

This prevents secondary requests for an invalid/missing company and makes the
selected path ID auditable.

Company profile section:

- ID, company name, business type, status;
- safe contact email and phone returned by the detail endpoint;
- created and updated timestamps.

Subscription section:

- safe plan code/name, billing interval, currency, and price;
- subscription status and period/trial dates;
- cancellation or pending-plan state exposed by the backend;
- explicit status badges for trialing, active, past due, expired, and cancelled.

There is no Change Plan, Cancel, Retry, Reconcile, Checkout, or external payment
link. A null subscription renders **No subscription recorded**, not a failure.

AI-credit and usage section:

- resolved period start/end;
- initialized state;
- included, top-up, and total balance in integer micro-MYR-derived display;
- request count and prompt/completion/total tokens;
- customer charge and uncovered charge in micro-MYR-derived display;
- provider cost in micro-USD-derived display.

When `initialized = false`, display **AI-credit balance not initialized** and do
not present zero as an available initialized balance. Never offer initialization
or top-up. Validate numeric values before formatting and show an unavailable
placeholder rather than guessing when a value is malformed or outside safe
JavaScript integer handling.

## Shared frontend components

Implement small dedicated modules rather than adding another large inline page:

- platform navigation/shell custom element;
- authorization gate and full-page state renderer;
- fixed status badge;
- loading skeleton/panel;
- empty/error panel with optional manual Retry;
- company directory table/card renderer;
- pagination control;
- read-only definition-list/detail card;
- safe date, integer, micro-MYR, and micro-USD formatters.

Subsequent shared tenant-account component:

- `frontend/assets/js/shared-ui.js` defines `tenant-account-menu`.
- `bots.html` renders the component in its existing top-right action area.
- Confirmed sidebar-backed authenticated pages receive a top-right menu mounted
  outside the sidebar: `index.html`, `crm.html`, `flows.html`,
  `media_attachments.html`, `meta_templates.html`, `integration.html`,
  `model_settings.html`, `new_linkdocs.html`, `broadcast.html`,
  `conversations.html`, `pricing.html`, `profile.html`, `reports.html`,
  `team.html`, `testbot.html`, and `new_prompt.html`.
- `new_prompt.html` includes the required shared/auth/sidebar dependencies and
  renders `<chatbot-sidebar>` through its React bundle; it is source-contract
  verified. It is not part of the executable browser menu suite because the
  current file depends on external React UMD scripts. Browser coverage includes
  `bots.html`, `index.html`, and `profile.html`.
- Bot-scoped pages preserve the previous Profile `bot_id` query behavior where
  appropriate.
- The menu renders user name/email with DOM text properties only. It may read
  `sessionStorage.user` for display text, but never for platform-admin
  authorization.
- Support points to `support.html`, a static authenticated tenant help page.
  It is available to authenticated tenant users independently of tenant role,
  contains no support-submission backend, and remains unrelated to
  platform-admin authorization.
- The **Platform Administration** item is hidden by default and appears only
  after a live `GET /api/platform-admin/me` returns HTTP 200. HTTP 403, HTTP
  503, network failure, tenant owner/admin/member roles, and forged storage
  flags keep the item hidden. HTTP 401 uses the normal logout behavior.
- The result is cached only in memory for the current page instance. It is not
  written to `localStorage`, `sessionStorage`, URLs, analytics, or logs.
- The ordinary tenant sidebar intentionally has no platform-admin link. Menu
  visibility reduces clutter for authorized operators, but backend
  authorization and the platform page's fresh `/me` gate remain mandatory.

Use `textContent`, DOM property assignment, and fixed templates for API-derived
values. Do not concatenate API fields into `innerHTML`, event-handler strings,
URLs, CSS, or log messages. Links containing company IDs must be built from a
validated integer with `URLSearchParams`.

No modal is required in the initial read-only surface. A dedicated detail page
is clearer, keyboard-friendlier, and avoids implying an edit workflow.

### Subsequent read-only company users/chatbots extension

After Phase 3 staging verification, the platform-admin company-detail page was
extended locally with two lazy read-only sections:

- **Users** calls `GET /api/platform-admin/companies/<company_id>/users` only
  after `/me` succeeds and the company detail request confirms the requested
  company exists. It renders only ID, full name, email, tenant role, status, and
  created/updated timestamps.
- **Chatbots** calls `GET /api/platform-admin/companies/<company_id>/chatbots`
  only after the same authorization and company validation path. It renders only
  ID, bot name, active flag, status, language, tone, AI provider, model name,
  and created/updated timestamps.

Both sections are lazy-loaded by explicit operator action, have independent
loading/empty/unavailable states, use server-side pagination and allowlisted
sorting, keep search text in page memory only, and provide no mutation, export,
impersonation, messaging, user-management, role/status-change, chatbot-edit,
delete/restore, subscription-change, payment, or credit-adjustment controls.
This extension is application-only and locally tested unless a later approved
staging verification record is added.

### Subsequent read-only subscription-history extension

After the users/chatbots and operations-overview additions, a bounded
application-only extension added
`GET /api/platform-admin/companies/<company_id>/subscription-history` and a
lazy **Subscription history** section below the current subscription summary.
The section loads only after `/me` succeeds and company detail confirms the
company exists, and only when the operator opens the section. It supports
server pagination and an optional status filter for `trialing`, `active`,
`past_due`, `expired`, and `cancelled`.

The response lists persisted `company_subscriptions` records ordered by
`created_at DESC, id DESC`. It is not an event-sourced audit timeline and must
not be described as proof that every individual status transition is preserved
as a separate row. Plan enrichment exposes only plan code and name for the
current and pending plan references on the historical row. It intentionally
omits current plan price, currency, billing interval, included AI credit,
feature flags, and model tier because current plan-table commercial values are
not guaranteed to represent historical terms.

At the time of the subscription-history extension, billing orders, exports,
charts, reconciliation, activation, refund, retry-payment, plan-change,
cancellation, renewal, and credit-adjustment controls remained deferred and out
of scope. A later billing-order history phase added only the read-only,
company-scoped list described below; all write and recovery controls remain
deferred.

### Subsequent read-only AI-credit transaction-history extension

After the subscription-history addition, a bounded application-only extension
added `GET /api/platform-admin/companies/<company_id>/ai-credit-transactions`
and a lazy **AI-credit transactions** section below the current AI-credit
summary. The section loads only after `/me` succeeds and company detail
confirms the company exists, and only when the operator opens the section. It
supports server pagination and an optional transaction-type filter for the
staging-verified ledger domain:

- `included_credit_grant`;
- `trial_credit_grant`;
- `usage_debit`;
- `topup_purchase`;
- `refund`;
- `manual_adjustment`;
- `expiry`;
- `reversal`.

The response lists safe fields from persisted `ai_credit_transactions` records
ordered by `created_at DESC, id DESC`. It intentionally excludes provider
cost, FX rate, markup basis points, payment reference, idempotency key,
description, AI-usage-log ID, subscription ID, reversal ID, and company ID.
The staging inspection verified the table schema, transaction type check
domain, and existing `(company_id, created_at DESC)` index; the endpoint itself
is application-only and locally tested unless a later approved staging
verification record is added. No migration was added.

### Subsequent read-only billing-order history extension

After the audit-log viewer addition, a bounded application-only extension added
`GET /api/platform-admin/companies/<company_id>/billing-orders` and a lazy
**Billing orders** section near the subscription investigation area on
`platform-admin-company.html`.

The section loads only after `/me` succeeds, company detail confirms the company
exists, and the operator clicks **Load billing orders**. It supports server
pagination, optional exact length-bounded status filtering without a stored
status enum assumption, optional timezone-aware created-after/created-before
filters, request cancellation, late-response suppression, independent
empty/unavailable/validation states, and full-page stale-data clearing when a
child request returns `company_not_found`.

The response is reconstructed from safe `company_subscription_orders` fields
only. It includes `id`, `status`, `amount_sen`, safe `new_plan` and
`source_plan` `{code, name}` objects where resolvable, activation state/type,
the reconciliation-required boolean, and safe lifecycle timestamps. It does not
return `company_id`, subscription/user IDs, order references, gateway IDs,
checkout URLs, payment references, payment gateway, idempotency keys, billing
period keys, activation sequence keys, reconciliation attempts, raw errors,
payloads, or currency. The UI displays amounts as integer sen (for example,
`3900 sen`) and must not display RM/MYR or infer any currency.

## API client design

Create a dedicated platform API client that wraps the existing authenticated
session mechanism but accepts only the twelve GET operations. It must not expose a
generic mutation method or arbitrary platform URL.

Required operations:

```text
getMe({ signal })
getOverview({ signal })
listCompanies({ limit, offset, search, status, sortBy, sortOrder, signal })
getCompany(companyId, { signal })
getCompanySubscription(companyId, { signal })
listCompanySubscriptionHistory(companyId, {
  limit,
  offset,
  status,
  signal
})
getCompanyAiCreditUsage(companyId, { signal })
listCompanyAiCreditTransactions(companyId, {
  limit,
  offset,
  transactionType,
  signal
})
listCompanyBillingOrders(companyId, {
  limit,
  offset,
  status,
  createdAfter,
  createdBefore,
  signal
})
listCompanyUsers(companyId, {
  limit,
  offset,
  search,
  sortBy,
  sortOrder,
  signal
})
listCompanyChatbots(companyId, {
  limit,
  offset,
  search,
  state,
  sortBy,
  sortOrder,
  signal
})
listAuditEvents({
  limit,
  offset,
  action,
  resourceType,
  actorUserId,
  resourceId,
  createdAfter,
  createdBefore,
  signal
})
```

Every operation:

- uses the current `sessionStorage.token` through the normal authenticated
  session mechanism;
- sends `Authorization: Bearer ...` and no token in query parameters;
- uses method GET and no body;
- accepts an `AbortSignal`;
- parses only the expected `status`/`data` envelope;
- maps errors to status, stable code, and a fixed UI category;
- discards raw response details after classification;
- never logs response bodies, headers, JWTs, raw exceptions, or Supabase data.

### Stable status handling

| HTTP | Frontend behavior |
|---:|---|
| 400 | Show a fixed validation message beside the relevant control; do not clamp or retry |
| 401 | Clear platform state and invoke normal logout/login flow |
| 403 | Abort all platform requests, clear all company data, show Access Denied |
| 404 | On detail only, show Company Not Found and a directory return link |
| 503 | Clear cross-tenant content, show Temporarily Unavailable, permit manual retry only |
| Network | Treat as unavailable without rendering raw exception text |

Do not silently retry `platform_admin_audit_unavailable` or any other 503. An
automatic retry could create ambiguous audit outcomes and unexpected traffic.

### Cancellation, duplicate prevention, and stale responses

Maintain an in-memory request registry keyed by operation. A new request for the
same key aborts its predecessor. Disable controls during the active request so
double clicks cannot issue duplicates. On `pagehide`, logout, access denial, or
navigation, abort every controller.

Maintain a monotonically increasing page/session epoch. Response handlers may
render only if their captured epoch still matches. If any request returns 401
or 403, increment the epoch before clearing the DOM so a late concurrent 200
cannot restore revoked data. Apply the same full-page clearing rule to 503 to
avoid leaving stale cross-tenant information visible.

## Frontend security requirements

1. `/me` is the only frontend platform-access gate and runs on every page entry.
2. Never authorize from JWT decoding, `users.role`, cached user data, a local
   platform flag, URL knowledge, or hidden navigation.
3. Never place platform identity, authorization state, company responses, or
   filters containing user input in local/session storage.
4. Keep cross-tenant responses only in active-page memory and clear rendered
   data on denial, logout, 503, pagehide, and revoked-session detection.
5. Use only the twelve approved GET endpoint builders; no `/api/admin/billing`
   reuse.
6. Validate the company query ID before constructing any API path.
7. Render API values as text, not HTML.
8. Map fixed error messages from status/code; never display raw API messages,
   stack traces, provider payloads, or Supabase errors.
9. Do not log headers, tokens, bodies, company data, search text, or exceptions.
10. Do not include payment credentials, external customer identifiers, checkout
    URLs, provider payloads, secrets, or unsupported fields.
11. Do not cache platform responses in service workers, IndexedDB, Cache API,
    local storage, session storage, or persistent application globals.
12. Treat menu hiding and read-only labels as presentation only; backend
    authorization remains mandatory for every request.

## UI state model

| State | Required presentation and behavior |
|---|---|
| Initial authorization | Full-page neutral skeleton; platform data/nav hidden until `/me` returns 200 |
| Loading | Labelled skeleton or spinner with `aria-live=polite`; retain no previous tenant row during replacement |
| Access denied | Fixed 403 screen, no platform data, Return to Tenant App action |
| Unauthenticated | Clear state and follow normal login/logout behavior |
| Backend unavailable | Fixed 503 screen, no raw message or stale company data, manual Retry and Return actions |
| Empty company list | Explain that no companies match; preserve filters and provide Clear Filters |
| Missing company | Fixed 404 Company Not Found state; do not request billing panels |
| Missing subscription | Neutral No subscription recorded panel |
| Uninitialized AI credit | Neutral Not initialized panel; no zero-balance or initialization claim |
| Past due | Warning badge and dates; no recovery action |
| Expired/cancelled | Inactive badge and dates; no renew/change action |
| Mapping revoked mid-session | Next request's 403 aborts all requests, clears DOM/in-memory data, and shows Access Denied |
| Logout/page exit | Abort requests and clear all platform state before navigation |

All retry controls are explicit buttons. Focus moves to the resulting state
heading after a full-page transition. Status changes are announced without
stealing focus during ordinary loading.

## Test plan

### Authorization and state tests

- Ordinary tenant admin receives 403 and never sees platform content.
- Ordinary tenant owner receives the same result.
- Active mapped member receives 200 and can enter, proving tenant role is not
  the grant.
- Forged cached role, local platform flag, or hidden-menu manipulation does not
  bypass `/me`.
- No company request occurs until `/me` succeeds.
- Revoking the mapping makes the next request deny, aborts concurrent work, and
  clears identity/company data.
- Two page entries make two `/me` calls; access is not cached across pages.
- Logout clears token through the existing mechanism and clears platform memory
  and DOM state.

### API integration tests

- Every platform request carries the existing session token in the Bearer
  header and never places it in a URL/body.
- Only the twelve approved GET endpoint builders exist.
- Detail, subscription, and AI usage all use the validated page company ID, not
  the JWT/cached company ID.
- Invalid company IDs are rejected locally without an API call.
- Pagination preserves backend `limit`, `offset`, `total`, and `has_more`.
- Search debounce sends the final trimmed value once and cancels the prior
  request.
- Status, sort field, and sort order use only backend allowlists.
- Duplicate interactions do not create duplicate in-flight requests.
- 400, 401, 403, 404, 503, abort, and network conditions enter their fixed
  states.
- No 503 is automatically retried.

### Rendering and security tests

- API strings containing HTML/script syntax render as text.
- Raw API messages, Supabase details, tokens, secrets, provider payloads, and
  authorization headers never appear in DOM or console calls.
- Audit-related 503 responses never expose previously fetched tenant data.
- Missing subscription and uninitialized balance states are distinct from
  errors and from a true zero initialized balance.
- Past-due, expired, cancelled, active, and trialing labels are correct.
- There are no forms or controls for mutation, impersonation, export, messaging,
  credit adjustment, reconciliation, or subscription changes.
- Source-contract tests reject `/api/admin/billing`, non-GET methods,
  `select('*')` concepts, JWT decoding, tenant-role authorization, or platform
  access flags in storage.

### Accessibility and responsive tests

- All functionality is usable by keyboard in logical tab order.
- Skip link, landmarks, headings, control labels, visible focus, `aria-live`,
  and `aria-sort` are present and meaningful.
- Access-denied, unavailable, empty, and missing states receive appropriate
  focus and screen-reader announcements.
- Directory controls and company cards work at 320px, 768px, tablet, and desktop
  widths without clipped actions or inaccessible horizontal content.
- Reduced-motion preferences disable nonessential transitions.

Historical note: the original Phase 3 plan assumed Python source-contract
tests plus recorded manual keyboard/responsive verification, and treated
Playwright or another browser runner as a separate tooling decision rather than
an implicit Phase 3 dependency.

Subsequent test-infrastructure hardening approved and added Playwright as the
local executable browser regression layer. The browser suite complements, and
does not replace, the Python source-contract tests or the recorded staging
browser verification. It serves the real frontend files locally and mocks
`/api/platform-admin/*` responses, so it proves local frontend behavior against
controlled responses but does not prove staging or production behavior. CI
enforcement remains deferred until a Node and browser runtime is selected.

## Exact expected implementation files

### New frontend files

- `frontend/platform-admin.html`
- `frontend/platform-admin-companies.html`
- `frontend/platform-admin-company.html`
- `frontend/assets/css/platform-admin.css`
- `frontend/assets/js/platform-admin-api.js`
- `frontend/assets/js/platform-admin-shell.js`
- `frontend/assets/js/platform-admin-dashboard.js`
- `frontend/assets/js/platform-admin-companies.js`
- `frontend/assets/js/platform-admin-company.js`

Subsequent application-only platform-admin frontend extensions added:

- `frontend/platform-admin-support.html`
- `frontend/assets/js/platform-admin-support.js`
- `frontend/platform-admin-audit-events.html`
- `frontend/assets/js/platform-admin-audit-events.js`

`platform-admin-shell.js` should own the dedicated custom navigation element,
authorization gate, request registry, state clearing, and logout/pagehide hooks.
The three page controllers should contain only page-specific orchestration and
rendering.

### New tests

- `tests/test_platform_admin_frontend.py`

The test file should inspect the HTML/JS contracts and mock request outcomes for
authorization ordering, endpoint allowlists, safe rendering, state clearing,
read-only controls, and responsive/accessibility markers.

### Subsequently added browser-test infrastructure

- `package.json`
- `pnpm-lock.yaml`
- `playwright.config.js`
- `tests/browser/platform-admin-static-server.js`
- `tests/browser/platform-admin.spec.js`
- `tests/browser/tenant-account-menu.spec.js`

These files provide local mocked Playwright regressions for the existing
read-only frontend and shared tenant account menu. They are test infrastructure
only and do not add platform routes, write controls, staging access, or
production verification.

### Subsequently added shared account-menu files

- `frontend/assets/js/shared-ui.js` — shared `tenant-account-menu` custom
  element and lazy platform-admin menu discovery.
- `frontend/bots.html` — uses the shared component instead of the previous
  page-local account dropdown.
- `frontend/sidebar-component.js` — keeps Team and Billing tenant navigation,
  but no longer renders Profile or Logout.
- `tests/test_tenant_account_menu_frontend.py` — source-contract coverage for
  the shared menu and sidebar cleanup.

### Existing files expected to remain unchanged

- `frontend/sidebar-component.js` — no platform link in ordinary tenant nav;
  later shared account-menu work also moved Profile and Logout out of the
  sidebar while preserving Team and Billing navigation;
- `frontend/assets/js/auth.js` — reuse the existing token/logout mechanism;
- Phase 3's original frontend-only pass left backend routes, services,
  repositories, decorators, and migrations unchanged. The later operations
  overview extension changed backend routes, services, and repositories only to
  add the audited GET-only `/api/platform-admin/overview`; decorators,
  migrations, SQL, staging, and production remain unchanged;
- Flow Builder and Broadcast files.

`docs/FEATURE_STATUS.md`, `docs/DEVELOPMENT_ROADMAP.md`, and this design
document were updated with implementation status. Manual staging UI
verification remains a separate approved activity.

## Risks and unresolved decisions

| Risk or decision | Recommendation |
|---|---|
| Local tenant role mistaken for platform access | Dedicated `/me` gate; never call `requireAdminOrOwner()` |
| Discoverable static platform URL | Accept discovery; backend gate protects data and UI stays hidden before 200 |
| Platform link in tenant sidebar | Omit initially; reconsider only with live access confirmation and audit-volume review |
| Dashboard count audit volume | Current dashboard uses one audited `/api/platform-admin/overview` request; do not add extra aggregate endpoints without approval |
| Concurrent response after revocation | Abort registry plus session epoch before clearing state |
| Search text in browser history/storage | Keep search in page memory only |
| API string injection | DOM text rendering and validated numeric URL construction |
| Raw errors exposed by existing page patterns | Dedicated fixed error mapper; no raw `body.message` or `console.error` data |
| Stale cross-tenant data after 503 | Clear the entire platform view before unavailable state |
| Contact email/phone visibility | Confirm internal support need; fields are backend-approved but can be omitted from UI |
| JavaScript integer precision for monetary micros | Validate safe integers; never silently round malformed/unsafe values |
| Browser-test framework was originally deferred | Playwright was later approved and added for local mocked regressions; CI enforcement still needs a selected Node/browser runtime |
| Staging mapping inactive | Browser verification is complete and the mapping was revoked again; any later access requires separate approval |
| Production access | Remains blocked by all Phase 1.5 production gates |

## Completed implementation sequence

1. Add the platform-only CSS, shell, authorization gate, and API client tests.
2. Implement the dashboard and verify access-denied/unavailable transitions.
3. Implement the server-paginated company directory and cancellation logic.
4. Implement company detail with sequential existence then parallel safe reads.
5. Add source-contract, rendering, state, accessibility, and responsive tests.
6. Run the full safe suite and complete the approved staging browser
   verification; revoke the temporary mapping immediately afterward.

Suggested implementation commit message:

`feat(platform-admin): add phase 3 read-only frontend`
