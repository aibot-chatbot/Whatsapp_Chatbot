# Platform-admin Tenant and Company Administration Contract

## Status

Platform-admin Tenant and Company Administration Phase 5 is implemented and
verified for the current milestone in the approved main shared-testing Supabase
with fake/team data. Migration 036 was applied and verified only in the
approved main shared-testing Supabase with fake/team data. This is not staging
verification and does not establish production readiness.
Platform-admin Tenant and Company Administration Phase 5 and Migration 036 are
applied and verified only to the extent described in this contract; runtime
tenant suspension enforcement is covered by automated local tests plus bounded
representative main shared-testing verification.

The current Supabase project used for this evidence is the prototype/shared-testing
environment. Supabase labels its main branch as `PRODUCTION`, but this
project is not the future real production environment. Future staging and
future real production have not been verified for Phase 5.

This contract records the permanent Phase 5 runtime, database, audit, and
verification boundary. It supersedes the temporary Phase 5 working notes.

## Scope

Phase 5 adds bounded tenant/company administration for authorized platform
admins:

- reuse existing read-only company list/detail, subscription, usage, company
  users, company chatbots, support, and audit surfaces;
- inspect safe tenant configuration and operational state;
- investigate company support history from Company Detail using existing
  company-scoped support APIs;
- navigate from Company Detail to the Support Workspace with
  `company_id=<company_id>`;
- navigate from Company Detail to company-related Platform Admin Audit Logs
  with `resource_type=company` and `resource_id=<company_id>`;
- suspend a company by setting `companies.status` from `active` to `inactive`;
- restore a company by setting `companies.status` from `inactive` to `active`;
- audit every approved lifecycle mutation.

Explicitly excluded:

- impersonation;
- company deletion;
- tenant user deletion;
- tenant role administration;
- tenant impersonation;
- arbitrary tenant data access;
- raw tenant messages;
- AI prompts or responses;
- provider payloads;
- API credentials;
- payment secrets;
- unrestricted configuration inspection;
- password reset;
- manual credit adjustment;
- arbitrary subscription or billing mutation;
- financial mutation controls;
- true tenant application audit history;
- Phase 4 platform-admin account-management expansion;
- Phase 6 duplicate monitoring;
- Phase 7 financial mutation controls;
- arbitrary configuration mutation;
- arbitrary SQL execution;
- suspension reason fields;
- staging or production controls.

Platform-admin authority continues to come only from active
`platform_admin_users` mappings. `users.role` never grants platform-admin
authority.

## Suspension Semantics

`companies.status` is the authoritative Phase 5 company operational state:

- `active`: normal tenant operational activity is allowed.
- `inactive`: platform-admin administrative suspension.

Suspension does not deactivate users, change `users.role`, delete users, change
subscription rows, alter AI-credit balances, deactivate or delete chatbots,
delete channel or integration configuration, alter support history, or alter
billing history. Restore changes only company operational status back to
`active`.

Authentication may still establish identity for an active user. Company
suspension authorization is enforced on operational tenant actions, not by
claiming that `token_required` globally rejects every suspended-company read.

Preserved while inactive:

- tenant support submission and support history/detail;
- approved read-only billing history and receipts where the existing
  architecture safely supports them;
- platform-admin inspection, support, billing-history, audit, and investigation
  surfaces;
- legitimate financial reconciliation and accounting callbacks.

Blocked tenant operational areas include:

- workspace and profile mutations;
- current-user profile and password mutations;
- profile create/delete;
- team role and status mutations;
- invitation acceptance and team mutation;
- chatbot and widget state-changing operations, including dashboard widget
  state creation, widget updates, and widget key regeneration;
- public widget response processing;
- Telegram, linked-device WhatsApp, and Meta WhatsApp inbound processing;
- broadcasts, including creation, start, worker startup, and per-recipient
  dispatch checks;
- AI chat generation, `/api/chat/test`, and system/background AI generation;
- chatbot create, edit, archive, restore, permanent delete, and welcome-menu
  generation;
- knowledge PDF upload, active-knowledge changes, supporting-knowledge changes,
  deletion, website scraping, extraction, embedding, unified ingestion,
  refinement submission, and graph mutations;
- implicit-write knowledge reads: missing graph self-healing, refinement
  question generation, and missing README generation;
- CRM mutation routes;
- Telegram, linked-device WhatsApp, and Meta WhatsApp configuration mutations;
- billing checkout, top-up, retry, cancellation, undo-cancellation, downgrade,
  and downgrade-clear mutation actions.

Qualified knowledge reads while inactive:

- an existing knowledge graph remains readable;
- an existing README remains readable;
- a missing graph cannot trigger PDF parsing, embedding generation, chunk
  writes, or graph extraction;
- refinement-question generation is blocked before SSE streaming and AI work;
- a missing README cannot trigger generation or write fallback.

## Enforcement Architecture

`app.services.company_status_service.ensure_company_operational(...)` resolves
the authoritative company row from the database using a server-derived company
ID. It requires status `active`; missing, null, unknown, or inactive company
state fails closed with a stable `company_suspended` style application error.

`company_operational_required` protects tenant mutation and operational routes
that derive company authority from the authenticated tenant context. Chatbot,
widget, webhook, and AI paths use either the route guard or direct
authoritative checks from server-loaded chatbot, channel, or bot records.

System/background AI derives `company_id` from the chatbot record, checks
operational status before provider selection, then passes that bot-derived
company ID into provider/model enforcement so `resolve_ai_access(company_id)`
always runs even outside Flask request context. Flask `g` values cannot
override the bot-derived company ID.

Broadcast dispatch checks company status before worker execution and again
before each recipient send. If a company becomes inactive mid-dispatch, already
sent recipients remain sent, unsent pending recipients are marked failed with a
sanitized reason, no further provider sends occur, and the campaign terminates
failed.

Low-level provider send helpers do not independently query company status.
Normal application entry points are guarded before provider calls, message
writes, usage logging, or AI-credit charging.

The legacy PDF upload entry point is `POST /upload-pdf` in `app/views.py`. It
uses `@token_required`, `@role_required("admin", "owner")`, and
`@company_operational_required`, so suspended-company rejection occurs before
file processing, quota checks, `save_uploaded_pdf`, embeddings, chunk writes,
graph generation, README/history generation, chatbot runtime changes, or
persona derivation.

`POST /api/chat/test` is an operational tenant AI action. It now uses
`@company_operational_required` after authentication and role authorization.
The AI router already blocked provider, usage, and credit work for suspended
companies; the repaired route boundary returns the centralized
`403 company_suspended` contract instead of wrapping the router fallback as
HTTP 200 success.

## Platform-admin Lifecycle API

Platform-admin routes continue to use the dedicated platform-admin guard and
server-derived actor mapping. Browser JSON cannot supply actor IDs, target
status overrides, tenant roles, protected-company overrides, subscription
changes, billing adjustments, or arbitrary confirmation text.

Approved mutation routes:

- `POST /api/platform-admin/companies/<company_id>/suspend`
- `POST /api/platform-admin/companies/<company_id>/restore`

Normal runtime code calls the Migration 036 RPCs. It does not directly update
`companies.status`.

## Migration 036 Database Contract

Migration 036 established:

- `companies.status` is `NOT NULL`;
- default is `'active'`;
- check constraint allows only `active` and `inactive`;
- fail-closed precondition rejects invalid existing values before constraint
  installation;
- `suspend_platform_company(bigint,bigint)`;
- `restore_platform_company(bigint,bigint)`;
- active platform-admin actor validation;
- target company row locking;
- no-op rejection;
- protected-company rejection on suspension;
- status plus `updated_at` as the only company lifecycle mutation;
- atomic platform-admin audit insertion;
- `SECURITY INVOKER`;
- `search_path=pg_catalog`;
- service-role-only RPC execute;
- no protected-company seeding;
- no company ID hardcoding.

`companies` RLS remains disabled and not forced. This was intentional in Phase
5 because the existing backend architecture relies on service-role access and
no compatible RLS policy design was verified for this phase.

Least-privilege table posture verified in main shared testing:

- `anon`: no direct `companies` privileges;
- `authenticated`: no direct `companies` privileges;
- `service_role`: `SELECT`, `INSERT`, and `UPDATE` only;
- `companies_id_seq`: `service_role` `USAGE` only.

## Audit Contract

Approved Phase 5 lifecycle actions:

- `platform_admin.company.suspend`
- `platform_admin.company.restore`

Both use:

- `resource_type = company`;
- `resource_id = target company ID`;
- metadata keys: `endpoint`, `http_method`, `outcome`, `company_id`,
  `old_status`, `new_status`.

Audit metadata must not include company names, emails, suspension reasons,
secrets, raw provider payloads, customer content, raw request bodies, raw
exceptions, or raw audit JSON.

Mutation audit rows are written atomically by the RPCs. Python routes do not
double-audit suspend/restore.

## Main Shared-testing Verification

Migration 036 was applied successfully only in the approved main shared-testing
Supabase with fake/team data.

Structural verification confirmed:

- 25 total companies;
- 25 active companies after test cleanup;
- 0 inactive companies after test cleanup;
- 0 invalid or null company statuses;
- `companies.status` is `NOT NULL`;
- default is `'active'`;
- check constraint allows only `active` and `inactive`;
- `companies` RLS is disabled and not forced;
- `companies` privileges are least-privilege as described above;
- `suspend_platform_company(bigint,bigint)` and
  `restore_platform_company(bigint,bigint)` are owned by `postgres`,
  `SECURITY INVOKER`, use `search_path=pg_catalog`, and are executable only by
  `service_role`;
- the protected-company registry still contains exactly one protected company;
- company 29 remains protected.

Real shared-testing lifecycle E2E used:

- actor platform-admin mapping ID 1;
- test company 23;
- company 23 is non-protected;
- company 23 has 0 users and 0 chatbots.

Verified lifecycle behavior:

- suspend company 23: `active` to `inactive`;
- exactly one suspend audit event was created;
- duplicate suspend was rejected with SQLSTATE `22023` and message
  `Company status is unchanged`;
- duplicate rejection created no extra lifecycle audit row;
- restore company 23: `inactive` to `active`;
- exactly one restore audit event was created;
- company 23 final status is `active`;
- protected company 29 suspend was rejected with SQLSTATE `42501` and message
  `Protected platform-admin company cannot be suspended`;
- company 29 remained active and protected.

Verified audit rows:

- audit event 355: `platform_admin.company.suspend`;
- audit event 356: `platform_admin.company.restore`;
- `resource_type = company`;
- `resource_id = 23`;
- safe fixed lifecycle metadata only.

The initial lifecycle target, company 23, had no users or chatbots, so the
first verification intentionally avoided tenant-runtime mutation checks on
another tenant. Later controlled main shared-testing runtime verification used
approved fake/team company 34, `Autobot Company`, with chatbot 52. Company 34
was non-protected, had one tenant user and one chatbot, and was restored to
`active` after every live test.

Representative runtime verification for company 34 confirmed:

- lifecycle: `active` to `inactive` to `active`;
- audit event 527: `platform_admin.company.suspend`;
- audit event 538: `platform_admin.company.restore`;
- protected company 29 suspend was rejected with HTTP 400 /
  `protected_company`, and company 29 remained active;
- chatbot mutation rejected with HTTP 403 / `company_suspended`, and the
  chatbot row was unchanged;
- `POST /api/knowledge/set-active` rejected with HTTP 403 /
  `company_suspended`, and knowledge state was unchanged;
- `POST /upload-pdf` rejected with HTTP 403 / `company_suspended`, with no new
  knowledge file, chunk, graph, README/history, persona derivation, or chatbot
  runtime change;
- a dummy Telegram connect request rejected with HTTP 403 /
  `company_suspended`, with no provider/channel state change;
- Company Detail, company users, company chatbots, subscription, AI-credit
  usage, AI-credit transactions, billing orders, company-scoped support cases,
  company-scoped tenant support requests, and company-filtered Platform Admin
  audit events remained available to Platform Admins while inactive;
- tenant `GET /api/bots` and `GET /api/support/requests` remained available as
  intended safe read/support paths;
- knowledge graph and README safe reads did not create missing knowledge state;
- company-scoped support cases and tenant support requests returned HTTP 200,
  and suspension did not block intended support investigation/read access.

The final targeted test-chat re-verification again used company 34 and chatbot
52:

- lifecycle: `active` to `inactive` to `active`;
- audit event 541: `platform_admin.company.suspend`;
- audit event 542: `platform_admin.company.restore`;
- `POST /api/chat/test?chatbot_id=52` returned HTTP 403 with
  `status = error` and `code = company_suspended`;
- AI usage rows remained `0` before and after;
- AI-credit transaction count remained `3` before and after;
- included balance remained `20000000` micro-MYR;
- top-up balance remained `0`;
- no provider execution was observed;
- chatbot runtime/configuration remained unchanged.

Final prototype runtime verification reconfirmed the same approved fake/team
target, company 34 `Autobot Company`, chatbot 52 `Auto Bot`, and tenant user
36. The company baseline was active with AI usage 0, AI-credit transaction
count 3, included balance 20000000 micro-MYR, and top-up balance 0.
`POST /api/platform-admin/companies/34/suspend` returned 200 and made the
authoritative company status inactive. While inactive, `PUT /api/bots/52`,
`POST /api/knowledge/set-active?chatbot_id=52`, and
`POST /api/chat/test?chatbot_id=52` each returned HTTP 403 /
`company_suspended`. Provider execution was not reached, AI usage remained
0 -> 0, AI-credit transaction count remained 3 -> 3, included and top-up
balances were unchanged, and chatbot runtime/configuration was unchanged.
`POST /api/platform-admin/companies/34/restore` returned 200 and the final
authoritative company status was active.

CRM mutation was not exercised live because selected fake/team company 34 had
no suitable CRM lead. No risky conversation or customer data was manufactured
for this gate. CRM suspension enforcement is covered by automated local tests.

Lifecycle audit metadata in the company 34 verification remained bounded to
safe lifecycle fields such as `company_id`, `endpoint`, `http_method`,
`old_status`, `new_status`, and `outcome`. Audit event IDs are evidence from
the approved main shared-testing environment only and are not portable across
environments.

The latest live gate directly reconfirmed company 29 is protected, protected
suspend is rejected, company 34 lifecycle works, and no invalid or null company
status was observed. Function ownership and grant internals were not newly
re-introspected during the latest live gate; prior Migration 036 verification
evidence remains the source for those details.

## Company Detail Investigation

Company Detail now provides bounded investigation for:

- company profile and operational state;
- current subscription context;
- AI-credit usage;
- subscription history;
- AI-credit transactions;
- billing orders;
- company users;
- company chatbots and safe configuration summary;
- support history using existing company-scoped support APIs;
- navigation to the Support Workspace with `company_id=<company_id>`;
- navigation to Audit Logs with `resource_type=company` and
  `resource_id=<company_id>`.

The audit integration is company-related Platform Admin activity, not true
tenant application audit history. A general authoritative tenant application
audit-history source does not currently exist; this is not a blocker for the
current Phase 5 milestone.

## Verification Limits

Phase 5 is not staging verified and is not production ready.

Production remains blocked until the normal environment, backup, monitoring,
rollback, executor, and approval evidence exists. Company 29 is protected only
for the approved main shared-testing environment and must not be treated as a
portable staging or production company ID.
