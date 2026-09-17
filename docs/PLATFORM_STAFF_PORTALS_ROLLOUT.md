# Platform staff portal rollout — 7 September 2026

Status: **Activated in shared Supabase; public Admin and Superadmin logins verified on 10 September 2026.** See [the live Fly release evidence](FLY_CHANNEL_READINESS.md) and [public login](https://aibot-chatbot-my.fly.dev/login.html). The dated rollout checks below describe the original local activation. The user approved the prototype and explicitly authorized live Supabase activation on 7 September 2026. This update replaces the platform staff interface with an independent light Admin portal and dark Super Admin portal. Tenant workspace pages retain their existing role model.

## Approved behavior

| Account | Platform role | Modules | Login destination |
| --- | --- | --- | --- |
| `aibot@iomaths.com` | Admin | Billing, Help Desk, Customers | `admin.html` |
| `superadminaibot@iomaths.com` | Super Admin | All platform permissions | `superadmin.html` |

Both assignments are active and verified. The existing Admin password and tenant role were preserved; the new Super Admin uses tenant role `member` and a generated password hash. Plaintext passwords remain outside source, reports and persisted artifacts. Password and Google login resolve the destination from the database mapping, never from email matching, tenant role, request parameters or browser storage. Unmapped tenant users retain `bots.html`; inactive staff and unknown platform roles fail closed.

Admin can read assigned modules, recheck existing payments, work support cases, and submit approval requests. Refunds, manual-payment approval, plan/account changes and suspension requests require a Super Admin decision. Decisions are durable, audited records; they do not automatically execute the requested operation. Super Admin can also manage staff grants, help articles and the existing company suspension/restore operations.

Payment recheck uses the stored company and order IDs with the existing idempotent reconciliation service. It can complete activation of an already paid purchase; it does not create a charge or refund. Pending ToyyibPay orders still require their verified callback. UI status distinguishes a completed reconciliation from pending or manual review.

## Source and validation

Runtime entry points are [Admin](../frontend/admin.html), [Super Admin](../frontend/superadmin.html), the two portal controllers/stylesheets, and the shared auth/API/shell scripts. Existing platform URLs redirect into these portals, preserving valid company IDs. Server logic remains in the existing route/service/repository layers, with the small staff service/repository additions. No dependencies were added.

- Backend agent: 285 focused tests and 469 subtests passed. Login/shared frontend source suite: 71 tests and 14 subtests passed. Auth-session and staff API JavaScript checks passed.
- Final security-fix regression run: `python -m pytest tests/test_platform_staff_access.py tests/test_workspace_team_integration.py tests/test_platform_login_destination.py -q` passed 118 tests and 14 subtests. This overlaps the earlier staff/login checks; totals must not be added together. Existing Google invitation tests now explicitly mock the new staff lookup.
- Mocked Chrome suites: 12 Admin, 9 Super Admin and 3 legacy-link tests passed, each with a clean exit. They cover the approved screens, permission denials, approval failures/success, notes versus replies, assignment, payment outcomes, escaping, responsive layouts, module revocation, delayed ticket saves, search privacy and preserved company links.
- PostgreSQL 18 in a disposable loopback-only cluster: migration 053 applied twice; actual RPC tests passed for role/module/protected-company gates, default-deny staff creation, permission changes, self-demotion denial, decision conflicts and rollback when audit persistence fails. The cluster was stopped after testing.
- Existing help migration 050 applied twice in that same disposable database: 20 articles inserted on first application, zero duplicate inserts on second. This is local PostgreSQL evidence, not live Supabase proof.
- Fresh PostgreSQL 18 database after the security fix: migration 053 applied twice; active staff, sole-Super, NULL and bulk status changes were rejected, ordinary tenant changes and audited revoke-before-deactivate behavior succeeded. Three synchronized two-session tests observed actual lock waits: grant first, status change first, and concurrent Super demotion/account deactivation all preserved the required access invariant. The scratch cluster is stopped.

The shared database uses PostgreSQL 17.6, so the local 18 test does not replace its preflight. Whole-tree whitespace validation still reports a pre-existing blank line at `app/services/email_service.py:522`; that file was not changed by this portal work. Earlier Windows PowerShell 7 process exits were unstable; the final focused commands use Windows PowerShell with clean process exits.

## Authorized activation procedure

Target: Supabase project `parjsxypengvubziwwjp` (AI Chatbot's Project), PostgreSQL 17.6, the current shared-testing environment. Migrations and account setup below are completed. No application deployment or live payment/message operation was performed.

1. Recheck current schema and reviewed file hashes. Apply [050](../data/050_help_articles.sql) if its help tables are still absent, and [053](../data/053_platform_staff_roles_approvals.sql). Migration 050 also publishes 20 existing help articles. Migration 053 adds staff roles/modules, approval storage and service-only transactional RPCs; it deliberately leaves existing mappings unassigned.
2. In one reviewed bootstrap transaction, locate the existing Admin and protected company from current data; create the requested Super Admin application user using a password hash, and assign the two explicit platform roles/modules. Preserve the Admin's current password and tenant role. Do not promote unrelated mappings. The Super Admin should use the existing protected company and a least-privileged tenant role; this application uses `public.users`, not Supabase Auth users.
3. Verify both account destinations and `/api/platform-admin/me`, module grants, denied direct routes and staff protection using the actual target schema. Verify read-only portal pages against the correct local checkout before any deployment. Keep financial or customer-message mutations mocked unless separately authorized.

Migration 052 belongs to the pre-existing tenant support intake changes and was not applied here. Its `escalation_context` column is absent in the shared database. The platform staff migration does not depend on 052; a deployment of the entire dirty working tree must separately reconcile that tenant intake dependency and other unrelated streams.

If activation fails, retain the schema and audit records, restore the previous application deployment as appropriate, and correct the explicit mapping. Do not delete audit history or mass-promote staff as a rollback. Back up and inspect any existing row before changing its assignment.

## Final review evidence

Final browser regression review passed. The strict UI audit selected the actual frontend explicitly and returned 12 findings: 11 externally/delegated button handlers and one textarea styled by global CSS. Source review resolved those detector limitations; the raw audit exit remains 1. An unconfigured root scan misses this repository's frontend and is not valid UI evidence.

Codex Security scan `476211eb-fd11-44a9-a5a6-49f7d3785df4` completed with exit 0 and complete coverage of the frozen 23-file implementation diff. It reported one medium finding, `csf_45ab2abf7bbf69931151a3ad`: a tenant administrator could disable the base account of the sole Super Admin through the existing user-status route. The correct endpoint is `PUT /api/users/<id>/status`; the scanner report's `/api/team` wording is inaccurate.

The fix adds a database status guard to migration 053, so every writer must revoke an active staff mapping through the Super Admin path before deactivating the underlying user. Statement-level locking serializes account status changes with staff grants before user-row locks. The team route returns a controlled 403 for this denial. Independent Codex Security `verify-fix` review returned **fixed**, supported by source tracing, the fresh PostgreSQL tests and observed concurrency waits under READ COMMITTED.

The original scan snapshot remains unchanged and still records its pre-fix finding. Of its 23 scoped files, only migration 053 changed afterward; the focused verification also covered the added user-route error handling and regressions. This is a completed scan plus verified remediation, not a second zero-finding scan. The reviewed source hashes were unchanged at live activation.

Evidence is retained under `C:\Users\Vincent\.codex\visualizations\2026\09\07\01a07976-e816-7c33-a075-09aa364c7843`: `portal-implementation-security-scan/report.md`, `portal-db-test/guard-integration.log`, `portal-db-test/guard-races.log` and `portal-db-test/check_staff_status_races.py`.

## Live activation evidence — 7 September 2026

- Supabase migration calls succeeded for `help_articles_050`, `platform_staff_roles_approvals_053`, and the atomic data migration `bootstrap_requested_platform_staff_accounts`. The bootstrap derives user/company/mapping IDs, rejects changed preconditions and creates an audit event. Its review artifact `portal-staff-bootstrap.sql` contains a hash placeholder, never a credential. Supabase migration history stores the executed generated hash, like the account record, not the plaintext password. The first bootstrap attempt through `execute_sql` failed before any writes because that connector uses `supabase_read_only_user`; the supported migration writer completed it.
- Live SQL confirmed 20 published articles; both verified active accounts and exact requested roles/modules; one bootstrap audit event; both status guards enabled; RLS on the three new tables; denied anonymous/tenant approval-table access and anonymous staff-RPC execution; service-role RPC execution allowed. Supabase advisors returned informational no-policy notices for the service-only tables, consistent with their deliberate denial of direct tenant access.
- Actual password login returned HTTP 200 and `admin.html` / `superadmin.html`. `/me` resolved the expected roles and all three modules. Company, support-case and approval reads returned 200 for both accounts. Staff-management and platform-wide overview returned 403 for Admin and 200 for Super Admin. An initial probe incorrectly expected Admin platform-wide overview to return 200; its 403 is the intended authorization behavior. Admin uses the assigned-module billing overview instead.
- Browser form submissions independently opened the populated light Admin dashboard and dark Super Admin overview using live records. Current entry point: `http://127.0.0.1:8000/login.html`. Running Flask serves this exact checkout and loaded the completed code before verification; no restart was needed.
- This URL works on the user's computer. Existing Cloudflare/ngrok public URLs are unavailable, and Render CLI access returns 401 for an expired token. No hosted application deployment was made. Any public release must first identify the intended host/service and prepare a scoped release from the extensively dirty checkout; unrelated support/payment streams remain separate.

## Super Admin chart enhancement — 7 September 2026

The overview adds plan comparison bars, a subscription status ring with visible
counts, and independent payment follow-up bars. Sources remain the existing
operations/billing overview APIs. Plan/status counts describe latest subscriptions
per company; payment counters describe overlapping order queues, never a combined
total. Each chart shows its source timestamp. Status labels open the existing
filtered subscription list. No backend, schema, dependency or authorization changes
were made.

Validation: the final 13-test Super Admin browser suite passed (30.8 seconds), including
four new tests for proportional bars and status links, zero/malformed/missing data
and escaping, independent source failures/recovery, and 390px/320px layouts with
keyboard, reduced-motion and forced-colors support. JavaScript syntax and scoped
whitespace checks passed. Desktop/mobile screenshots were inspected. The actual
local app displayed live Supabase data: 12 subscriptions (4 active, 4 trialing,
4 expired) and payment queues of 6 pending, 4 failed, 0 reconciliation required.
Those values are a verification snapshot, not hardcoded chart content.

The live Expired status link opened the existing filter and returned four records.
An independent Data Visualization Engineer reviewed the source and desktop/320px
screenshots. Its empty-plan copy correction is covered by the final browser run:
subscriptions with no listed plan are not described as an empty subscription set.
No screen-reader session or color-vision simulator was run.

An immutable two-file chart diff is under the external evidence directory as
`superadmin-charts-security-input`; Codex Security output is in
`superadmin-charts-security-scan`. Scan `a81dbc0f-3f22-4e31-a565-4f25254fdcd4`
completed with exit 0, zero reportable findings and complete coverage of both
changed runtime files. This was an offline source review; the browser and live
application checks above are separate evidence. A threat-architecture worker did
not return, so the scan parent completed and documented its sequential fallback.

After the scan snapshot, only the static empty-plan label and its explanatory
hint changed. An exact source substitution check verified that this was the only
JavaScript difference; the CSS remained byte-identical. That copy correction was
independently reviewed and included in the final 13-test run. The running local
server also served bytes identical to both final source files. Source hashes and
live/browser evidence are retained in `superadmin-charts-verification.json`.
