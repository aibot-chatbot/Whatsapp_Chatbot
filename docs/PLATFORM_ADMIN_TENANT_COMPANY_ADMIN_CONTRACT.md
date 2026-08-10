# Platform-admin Tenant and Company Administration Contract

## Status

Platform-admin Tenant and Company Administration Phase 5 is implemented locally.
Migration 036 was applied and verified only in the approved main shared-testing
Supabase with fake/team data. This is not staging verification and does not
establish production readiness.
Platform-admin Tenant and Company Administration Phase 5 and Migration 036 are
applied and verified only to the extent described in this contract; runtime
tenant suspension enforcement is locally tested, while database lifecycle
verification is limited to main shared testing.

This contract records the permanent Phase 5 runtime, database, audit, and
verification boundary. It supersedes the temporary Phase 5 working notes.

## Scope

Phase 5 adds bounded tenant/company administration for authorized platform
admins:

- reuse existing read-only company list/detail, subscription, usage, company
  users, company chatbots, support, and audit surfaces;
- inspect safe tenant configuration and operational state;
- suspend a company by setting `companies.status` from `active` to `inactive`;
- restore a company by setting `companies.status` from `inactive` to `active`;
- audit every approved lifecycle mutation.

Explicitly excluded:

- impersonation;
- company deletion;
- tenant user deletion;
- tenant role administration;
- password reset;
- manual credit adjustment;
- arbitrary subscription or billing mutation;
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
- Telegram, Wasender, and Meta WhatsApp inbound processing;
- broadcasts, including creation, start, worker startup, and per-recipient
  dispatch checks;
- AI chat generation and system/background AI generation;
- billing checkout, top-up, retry, cancellation, undo-cancellation, downgrade,
  and downgrade-clear mutation actions.

## Enforcement Architecture

`app.services.company_status_service.ensure_company_operational(...)` resolves
the authoritative company row from the database using a server-derived company
ID. It requires status `active`; missing, null, unknown, or inactive company
state fails closed with a stable `company_suspended` style application error.

`company_operational_required` protects tenant mutation routes that derive
company authority from the authenticated tenant context. Chatbot, widget,
webhook, and AI paths use direct authoritative checks from server-loaded
chatbot, channel, or bot records.

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

No live tenant-runtime suspension E2E was performed because company 23 has no
users or chatbots and the verification intentionally avoided risking another
tenant. Runtime enforcement is covered by automated local tests.

## Verification Limits

Phase 5 is not staging verified and is not production ready.

Production remains blocked until the normal environment, backup, monitoring,
rollback, executor, and approval evidence exists. Company 29 is protected only
for the approved main shared-testing environment and must not be treated as a
portable staging or production company ID.
