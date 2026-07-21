# Platform Admin Phase 4: Production Readiness

## Status and scope

**Approval package prepared; production remains blocked.** Migrations 023, 024,
and 025, the read-only backend, the five approved endpoints, audit behavior,
bootstrap, immediate revocation, and the read-only frontend are verified in
staging. Migration 026 is also applied and verified in staging. The staging
mapping remains present and inactive.

This package does not authorize or perform SQL execution, deployment,
bootstrap, mapping reactivation, tenant-role changes, or production access. It
adds no endpoint or mutation feature and does not affect Flow Builder or
Broadcast.

Repository verification for migration 026 completed with 16 focused static
tests passing, 87 platform-admin regression tests and 114 subtests passing, and
the full safe suite at 1,437 passed, 1 skipped, and 125 subtests passed. Live
staging inspection and rollback-only SQL verification also passed.

### Verified migration 026 staging evidence

- Function owner is `postgres`; SECURITY DEFINER is false and fixed
  `search_path=pg_catalog` is present.
- SQLSTATE `55000` and the stable
  `platform_admin_audit_events is append-only` message were verified.
- PUBLIC, anon, authenticated, and service_role have no direct EXECUTE on the
  trigger function.
- `platform_admin_audit_events_reject_mutation` is enabled, attached only to
  `platform_admin_audit_events`, and fires BEFORE UPDATE OR DELETE FOR EACH ROW.
- Table owner remains `postgres`; RLS remains enabled and not forced.
- anon/authenticated retain no table privileges. service_role retains
  SELECT/INSERT only, with UPDATE/DELETE denied.
- RLS policies remain service-role SELECT and INSERT only.
- The rollback-only test proved INSERT/SELECT success and stable trigger
  rejection for UPDATE/DELETE while executing as service_role.
- The temporary audit row and temporary UPDATE/DELETE grants were removed by
  rollback. The platform-admin mapping remained inactive.
- No production SQL or deployment occurred.

Production may proceed only after every approval register item below has a
named approver, dated decision, evidence link, and change ticket. A blank field
is a stop condition, not permission to use a default.

## Approval register

| Gate | Required recorded decision | Owner | Approval state |
|---|---|---|---|
| Production Supabase identity | Project reference, organization, region, database name, endpoint hostname, and environment label independently matched | Database owner | Pending |
| Release artifacts | Backend commit, frontend commit, migration commit, deploy artifact IDs, and SHA-256 hashes for 023–026 | Release manager | Pending |
| Migration executor and ownership | Named executor, execution method, expected `postgres` ownership, recovery operator, and approved window | Database owner | Pending |
| Protected internal company | Approved production company, operational owner, backup, deletion exclusion, and lifecycle controls | SaaS operations owner | Pending |
| Bootstrap identity | Exact internal user ID/email/company, active status, operator, approver, second verifier, and revocation owner | Security owner | Pending |
| Audit metadata policy | Approve `docs/PLATFORM_ADMIN_AUDIT_POLICY.md` without unresolved exceptions | Security and privacy owners | Pending |
| Retention and archive | Exact archive destination/KMS key, 13-month hot retention, seven-year archive, hold and deletion process | Security, legal, and data owners | Pending |
| Append-only enforcement | Staging evidence accepted; approve migration 026 hash, owner, and inclusion in the production change | Database and security owners | Pending |
| Backup and restore | Current backup/PITR state and successful isolated restoration evidence | Database owner | Pending |
| Monitoring | Alert destinations, on-call owners, thresholds, and runbook links enabled before bootstrap | Operations owner | Pending |
| Go/no-go | All evidence reviewed and a written production go decision recorded | Change approver | Pending |

## Production preflight checklist

### Environment and release identity

- [ ] Two people independently open the intended Supabase project from the
      production change record; do not select it from browser history alone.
- [ ] Record the Supabase organization, project reference, project name,
      environment label, region, database endpoint hostname, and database name.
- [ ] Compare the project reference and endpoint hostname with the approved
      backend production configuration without displaying the service key.
- [ ] Run only the SELECT-only inspection described in the deployment runbook
      and record `current_database()`, `current_user`, `session_user`, and
      `server_version`.
- [ ] Confirm the PostgreSQL version is supported by the existing production
      application and matches the version tested in staging, or record and
      approve the difference.
- [ ] Record the approved backend, frontend, migration, and release commit
      hashes. Require a clean, reviewed release commit; branch names are not
      evidence.
- [ ] Compute SHA-256 hashes for migrations 023, 024, 025, and 026 from the
      exact checkout used for deployment and compare them with the approved
      hashes.
- [ ] Confirm the deployment artifacts were built from the recorded commits and
      were not rebuilt from a mutable branch or uncommitted workspace.

### Dependency schema compatibility

- [ ] Confirm `public.users.id` is `BIGINT GENERATED BY DEFAULT AS IDENTITY`,
      non-null, and the primary key.
- [ ] Confirm `public.companies.id` is `BIGINT GENERATED BY DEFAULT AS
      IDENTITY`, non-null, and the primary key.
- [ ] Confirm `public.users.company_id` is `BIGINT` and references
      `public.companies(id)` with `ON UPDATE CASCADE ON DELETE CASCADE`.
- [ ] Confirm production exposes `users.email`, `users.full_name`,
      `users.status`, `users.role`, and `companies.company_name` and
      `companies.status` with the expected names and types.
- [ ] Confirm the approved internal user and company statuses can be represented
      as `active`.
- [ ] Confirm tenant `users.role` remains limited to the existing tenant
      semantics. It is informational only and must never contain or imply
      platform access.
- [ ] Record any schema difference and stop. Do not edit migrations during the
      production window.

### Collisions, ownership, roles, and privileges

- [ ] Confirm the two target tables and their identity sequences do not exist.
      Because production has received no platform-admin migrations, any
      existing object is an unexplained collision and blocks deployment.
- [ ] Record attributes for `anon`, `authenticated`, `service_role`, `postgres`,
      and `supabase_admin`, including LOGIN, SUPERUSER, INHERIT, and BYPASSRLS.
- [ ] Confirm and explicitly record that `service_role` has BYPASSRLS. RLS does
      not replace application authorization.
- [ ] Record direct and inherited role memberships affecting the three
      application-facing roles.
- [ ] Record current owner and RLS state for `users`, `companies`, and, after
      creation, both platform tables and sequences.
- [ ] Approve `postgres` as the expected owner of the new tables and sequences,
      or stop if the executor would produce a different owner.
- [ ] Inspect all default table/sequence privileges for the executor and schema,
      plus `public` schema CREATE/USAGE grants.
- [ ] Inspect direct ACLs and effective SELECT/INSERT/UPDATE/DELETE privileges
      for `anon`, `authenticated`, and `service_role`.
- [ ] Confirm no inherited membership, owner status, default ACL, or schema ACL
      silently broadens the intended grants.

### Expected post-migration security matrix

| Object | anon | authenticated | service_role direct operations | RLS | Expected owner |
|---|---|---|---|---|---|
| `platform_admin_users` | None | None | SELECT, INSERT, UPDATE; no DELETE | Enabled, not forced | `postgres` |
| `platform_admin_audit_events` | None | None | SELECT, INSERT; no UPDATE/DELETE | Enabled, not forced | `postgres` |

The service role's policies mirror these operations, but its BYPASSRLS
attribute means the backend must continue to enforce a fresh active-user and
active-mapping lookup on every request.

### Required post-migration objects

- [ ] Identity primary keys exist on both tables.
- [ ] `platform_admin_users.user_id` is unique and references `users(id)` with
      `ON UPDATE RESTRICT ON DELETE RESTRICT`.
- [ ] `created_by_user_id` references `users(id)` with `ON UPDATE RESTRICT ON
      DELETE SET NULL`.
- [ ] Audit actor FK references `platform_admin_users(id)` with `ON UPDATE
      RESTRICT ON DELETE RESTRICT`.
- [ ] Non-blank action/resource checks and JSON-object metadata check exist.
- [ ] Actor and resource timeline indexes match migration 024.
- [ ] No timestamp-maintenance or unexpected trigger exists. If migration 026
      is approved/applied, the sole expected non-internal trigger is
      `platform_admin_audit_events_reject_mutation`, enabled for row-level
      BEFORE UPDATE OR DELETE.
- [ ] The migration 026 function is owned by the approved executor/`postgres`,
      is SECURITY INVOKER (`prosecdef = false`), has fixed
      `search_path=pg_catalog`, contains the stable SQLSTATE 55000/message, and
      grants no direct EXECUTE to PUBLIC or application-facing roles.
- [ ] No policy exists for `anon` or `authenticated`; no DELETE policy exists;
      no audit UPDATE policy exists.

## Protected internal company production standard

### Selection requirements

The production platform administrator must belong to a dedicated internal
company that:

- is owned and operated by the SaaS provider and is not, and has never been, a
  customer tenant;
- has `companies.status = 'active'` at bootstrap and during active platform
  access;
- has a stable production company ID recorded in the restricted asset and
  access registry;
- has a named operational owner and a named backup from separate accountable
  personnel where practical;
- is excluded from self-service, support, bulk, retention, and automated tenant
  deletion workflows;
- is excluded from customer offboarding, subscription cleanup, test-data purge,
  and inactivity cleanup jobs;
- contains only approved internal identities and no customer bots, channels,
  billing credentials, or customer operational data.

No customer tenant may be repurposed. A display name containing “internal” is
not sufficient evidence of protection.

### Deletion and offboarding controls

- Maintain an explicit protected-company registry consulted by every human and
  automated tenant-deletion workflow.
- Require database-owner and security approval before any company lifecycle
  action. The existing FK interaction should block deletion while any mapping
  row references a company user, including an inactive mapping; this is a last
  line of defense, not the primary workflow control.
- Never delete a platform mapping to make company deletion succeed. Escalate to
  the security owner and use a separately approved identity-transfer plan.
- On user offboarding, first revoke the mapping, explicitly update
  `updated_at`, disable the application user, terminate sessions through the
  normal authentication process, and preserve the mapping and audit records.
- Do not move a platform-admin user into a customer company. Provision and
  approve a replacement internal identity instead.

### Lifecycle review and emergency transfer

- The operational owner and backup review the company, users, mappings,
  deletion exclusions, and monitoring quarterly and after any reorganization,
  ownership change, incident, or offboarding.
- Evidence must include reviewer names, UTC date, company/user/mapping IDs,
  statuses, deletion-exclusion checks, exceptions, and remediation ticket.
- Emergency ownership transfer requires the incident commander and security
  owner to approve a replacement operational owner and, if access is needed, a
  separately approved replacement internal user/mapping. Tenant roles are not
  changed to accomplish the transfer.
- Revoke the outgoing mapping before enabling replacement access whenever
  continuity permits. If overlap is essential, record its exact duration and
  obtain two-person approval.

## Production bootstrap approval record

Before the window, record all of the following in the restricted evidence
system:

1. exact production internal user ID and normalized email;
2. proof the user is an active application user;
3. exact protected internal company ID/name and proof it is active;
4. confirmation the user's existing tenant role is informational and will not
   be modified;
5. named SQL operator;
6. named change approver;
7. named second verifier observing candidate SELECT and INSERT output;
8. named emergency-revocation owner and backup;
9. evidence-system location and change-ticket identifier;
10. approved UTC change-window start/end and communications channel;
11. intended final mapping state: the default recommendation is **inactive
    after verification** unless a separate signed go-live decision requires
    ongoing platform operation;
12. the exact migration/release hashes and backup evidence.

Bootstrap must use `created_by_user_id = NULL`, must require the approved
active user and active protected company inside the `INSERT ... SELECT`, must
return exactly one row, and must not use conflict suppression or modify
`users.role`.

## Append-only enforcement options

| Criterion | A. Current grants | B. Dedicated NOLOGIN/NO BYPASSRLS role | C. UPDATE/DELETE rejection trigger |
|---|---|---|---|
| Security strength | Moderate against ordinary application mistakes; weak against `service_role` privilege drift, owner, membership, or superuser | Strongest separation when the application truly executes as the restricted role; still does not constrain owner/superuser | Strong against application/service-role UPDATE or DELETE because BYPASSRLS does not bypass triggers; owner/superuser can disable it |
| Operational complexity | Low | High: role provisioning, credential/connection or controlled-RPC design, rotation, PostgREST/Supabase compatibility, and incident access | Medium: trigger/function ownership, deployment ordering, monitoring, and a controlled maintenance bypass |
| Retention impact | Deletion remains possible after a later grant or privileged session; no built-in retention workflow | Retention worker needs a separately authorized role/path | Trigger rejects retention deletes until an approved owner maintenance procedure disables/bypasses it |
| Recovery impact | Simple, but easiest to alter accidentally | Recovery must restore role memberships/grants and application connectivity | Restore must include trigger/function; emergency archive/delete needs an owner-run maintenance window |
| Migration impact | None beyond 023–025 | New roles/grants plus an application database-access design and staging cycle | Migration 026 creates the rejection function/trigger and is verified in staging only |
| Drift surface | Direct/inherited grants, default ACLs, owner, superuser, BYPASSRLS | Role grants/memberships, controlled execution path, owner/superuser | Trigger existence/enabled state/function definition, owner/superuser |

### Recommendation

Approve **Option C, the UPDATE/DELETE rejection trigger prepared in
`data/026_enforce_platform_admin_audit_append_only.sql`**, for the initial
production release. Its staging execution and rollback-only verification are
complete; database/security approval for production remains required. It
materially strengthens append-only behavior under the current
`service_role`/BYPASSRLS architecture without introducing a new backend
database authentication path.

Migration 026 uses SECURITY INVOKER because the trigger function reads no
database objects and needs no elevated rights; SECURITY DEFINER would add an
unnecessary privilege boundary. It fixes `search_path` to `pg_catalog`, raises
SQLSTATE `55000` with the stable non-sensitive message
`platform_admin_audit_events is append-only`, fires BEFORE UPDATE OR DELETE for
every row, and revokes direct function execution from PUBLIC, anon,
authenticated, and service_role. It does not affect INSERT/SELECT, RLS,
policies, table grants, existing rows, or retention logic.

The function is owned by the migration executor; the approved production
executor must produce and verify `postgres` ownership. Owners and superusers can
still alter, disable, or drop the trigger. Migration 026 intentionally provides
no maintenance bypass.

### Migration 026 operational impact

- **Retention and archival:** read-only export/archive SELECT remains available.
  Scheduled retention DELETE is intentionally blocked; no purge may begin until
  a separate maintenance design is approved and staging-tested.
- **Recovery:** INSERT-based restoration into an isolated recovery database is
  unaffected. Any process that expects to UPDATE or DELETE restored production
  audit rows will fail and must not bypass the trigger ad hoc.
- **Incident response:** investigators can SELECT/preserve events but cannot
  annotate, correct, quarantine, or delete them in place. Case notes belong in
  the restricted incident system.
- **Privilege drift:** granting UPDATE/DELETE later does not make those
  operations succeed while the trigger is enabled, but such a grant is still a
  critical drift alert.
- **Owner boundary:** table/function owners and superusers can change the
  enforcement object. Their activity, ownership, trigger enabled state,
  definition, and function ACL require continuous evidence and monitoring.
- **Rollback:** do not remove migration 026 merely to restore application
  service; INSERT/SELECT are unaffected. Trigger removal or change requires a
  separate reviewed database migration and incident/retention justification.

Option B is the preferred long-term least-privilege architecture if a future
phase is authorized to change the database connection or controlled-RPC model.
It is not safe to assume that merely creating a NOLOGIN role makes existing
Supabase service-role requests execute as that role.

Migration 026 is applied, inspected, and rollback-tested in staging. Production
deployment remains blocked by production-specific approval of its hash/owner
and all other Phase 4 gates; staging verification is not production approval.

## Production monitoring requirements

Monitoring must be enabled before bootstrap. Alerts must contain request IDs,
timestamps, endpoint templates, status/code, and approved numeric actor/user
identifiers only—never JWTs, authorization headers, raw bodies, search text, or
tenant response data.

| Signal | Initial threshold | Severity and response |
|---|---|---|
| `platform_admin_authorization_unavailable` or `authentication_backend_unavailable` | Any event; page at 3 in 5 minutes | High; verify database/Supabase health and fail-closed behavior |
| Audit insertion failure / `platform_admin_audit_unavailable` | Any event | Critical; tenant data must remain withheld, revoke active mapping if persistence exceeds one request |
| Platform endpoint 5xx | Three consecutive requests or >1% for 5 minutes | High; halt verification/use and inspect backend/database |
| Repeated denied access | 10 denials for one user or gateway source in 5 minutes | High security review; preserve sanitized gateway/auth evidence |
| Inactive-user or inactive-mapping access | Any known internal identity attempt | Medium/high depending on repetition; confirm offboarding and session handling |
| Direct/effective privilege or RLS-policy drift | Any difference from approved matrix | Critical; revoke mapping and halt platform use |
| Audit UPDATE/DELETE statement or trigger rejection | Any | Critical incident; preserve database logs and investigate actor/session |
| Append-only trigger absent/disabled/changed, if selected | Any daily check failure | Critical; revoke mapping until restored |
| Protected-company deletion attempt or FK failure | Any | Critical; stop deletion workflow and notify security/database owners |
| Successful endpoint/audit reconciliation mismatch | Any completed request without its required event | Critical; platform response should already fail closed, investigate immediately |

Run privilege, ownership, RLS, policy, trigger, and migration-hash drift checks
after deployment, daily for the first week, then at least weekly and after any
database role/schema change. Review denied-access and endpoint/audit
reconciliation daily for the first week and at the normal security-review
cadence thereafter.

## Final staging rehearsal — completed

**Completed successfully in staging.** The rehearsal used no production
credentials or data and does not itself approve production.

- It started with mapping ID 1 for user ID 32 present and inactive. The
  platform-admin page showed Access Denied.
- The audit baseline was recorded at `prior_max_audit_id=58` before the
  time-bounded staging-only reactivation.
- The dashboard loaded with exact company counts. The company directory and
  company detail loaded, including company profile, subscription, AI-credit
  balance, usage, and charge sections.
- No mutation, export, payment, subscription-change, credit-adjustment,
  messaging, or impersonation control appeared.
- Migration 026 did not interfere with normal audit INSERT operations. Events
  after the baseline contained only approved action/resource pairs and approved
  metadata fields, with no sensitive data.
- The mapping was revoked again. Database verification confirmed
  `is_active=false`, and the mapping remains present and inactive.
- Refreshing company detail after revocation showed Access Denied. No stale
  company, subscription, or AI-credit data remained visible.
- No production SQL or deployment occurred. No tenant role or maintenance
  bypass was changed or introduced.

Retain the redacted rehearsal evidence with the production change record.
Production remains blocked until every production-specific approval gate is
complete.

## Go/no-go rule

Production is **NO-GO** if any approval is missing, any preflight output differs
from the expected matrix, a migration or artifact hash differs, backup restore
has not been demonstrated, monitoring is not live, migration 026 is not approved
for the production release, the internal company is not protected, or the
bootstrap identity has not passed two-person verification.

The detailed operator sequence is in
`docs/PLATFORM_ADMIN_PRODUCTION_DEPLOYMENT_RUNBOOK.md`; audit requirements are
in `docs/PLATFORM_ADMIN_AUDIT_POLICY.md`; urgent containment is in
`docs/PLATFORM_ADMIN_EMERGENCY_REVOCATION.md`.
