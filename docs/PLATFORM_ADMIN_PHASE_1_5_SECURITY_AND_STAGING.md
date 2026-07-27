# Platform Admin Phase 1.5: Security and Staging Deployment Review

## Status and scope

**Verified complete in staging; production blocked.** Migrations 023, 024, and
025 were applied successfully and verified in staging only. Migration 025 has
been promoted from `data/drafts/` into the numbered migration sequence. No
platform-admin bootstrap data was created, and nothing was applied to production.

This phase does not change tenant roles, authentication middleware, APIs,
frontend pages, Flow Builder, or Broadcast.

Platform access must eventually require both an authenticated application user
and an active row in `public.platform_admin_users`. The tenant `users.role`
value—whether `owner`, `admin`, or `member`—must never grant platform access.

## Verified staging evidence

The completed staging inspection recorded all of the following:

Historical clarification: this table describes the Phase 1.5 staging state for
migrations 023 through 025. Migration 026 was added later and is documented in
the Phase 4 production-readiness package as the expected append-only trigger on
`platform_admin_audit_events`.

| Area | Verified staging result |
|---|---|
| Migration 023 | Applied successfully |
| Migration 024 | Applied successfully |
| Migration 025 | RLS migration applied successfully |
| `platform_admin_users` RLS | Enabled, not forced |
| `platform_admin_audit_events` RLS | Enabled, not forced |
| Ownership | Both tables owned by `postgres` |
| Client policies | No policy for `anon` or `authenticated` on either table |
| `platform_admin_users` policies | `service_role` SELECT, INSERT, and UPDATE only |
| `platform_admin_audit_events` policies | `service_role` SELECT and INSERT only |
| Destructive policies | No DELETE policy on either table; no audit UPDATE policy |
| `anon` effective privileges | All false on both tables |
| `authenticated` effective privileges | All false on both tables |
| `service_role` on admin users | SELECT/INSERT/UPDATE true; DELETE false |
| `service_role` on audit events | SELECT/INSERT true; UPDATE/DELETE false |
| RLS bypass | `service_role` has `BYPASSRLS`; policies do not constrain it |
| Schema objects | Identity columns, FKs, checks, and indexes verified |
| Supporting security state | Ownership and identity-sequence privileges verified |
| Triggers | No triggers on either table |

This evidence verifies the intended staging schema and effective privilege
matrix. It does not authorize production deployment or replace the future
server-side requirement for an active `platform_admin_users` row.

## Security findings

### Grants and exposure

Migration 023 revokes all table and identity-sequence privileges from `PUBLIC`,
`anon`, `authenticated`, and `service_role`, then grants `service_role`:

- table `SELECT`, `INSERT`, and `UPDATE`
- identity-sequence `USAGE`
- no table `DELETE`

Migration 024 performs the same revocations and grants `service_role`:

- table `SELECT` and `INSERT`
- identity-sequence `USAGE`
- no table `UPDATE` or `DELETE`

This is a sound direct-grant baseline. It does not by itself prove effective
access because role membership, default ACLs, object ownership, superuser status,
and `BYPASSRLS` can change effective authority. The Phase 1.5 inspection SQL
reports each of those inputs.

### Ownership and default privileges

The migration executor becomes the owner of the new tables and identity
sequences. Owners retain implicit control regardless of ordinary grants and
normally bypass RLS unless `FORCE ROW LEVEL SECURITY` is used. The approved
executor identity must therefore be recorded and must not be an application
login.

Default privileges are applied when an object is created, before the explicit
REVOKE statements later in each migration. The explicit revocations remove
direct privileges for `PUBLIC`, `anon`, `authenticated`, and `service_role`
before the intended minimum grants are added back. All default ACLs and inherited
roles must still be inspected for unexpected principals.

### RLS staging outcome

RLS was enabled successfully on both staging tables as defense in depth. It is
not forced, no policies exist for `anon` or `authenticated`, and direct client
grants remain revoked.

The finalized `data/025_enable_platform_admin_rls.sql` contains operation-specific
`service_role` policies matching the table grants. Staging confirmed that
`service_role` has `BYPASSRLS`; these policies document intent but do not
constrain that role. RLS therefore does not replace the Phase 2 server-side
active-platform-admin authorization check.

Do not use `FORCE ROW LEVEL SECURITY` without a separate operational review; it
can affect owners, migrations, support access, and recovery workflows.

### Audit append-only protection

Migration 024 provides application-level append-only behavior by withholding
`UPDATE` and `DELETE` from `service_role`, `anon`, `authenticated`, and `PUBLIC`.
It also prevents actor deletion through the audit FK.

This is not absolute database-level immutability:

- the table owner and superusers can still update or delete rows;
- an inherited role may supply privileges;
- a later grant or default-privilege change can weaken the posture;
- a service role with broad owner-like membership must be treated as privileged.

For stronger enforcement, prefer a dedicated NOLOGIN/NO BYPASSRLS backend role
with only the required table operations. A trigger that rejects UPDATE/DELETE is
an alternative, but it complicates retention, archival, incident response, and
schema ownership. Either option requires explicit approval.

Historical clarification: this section reflects the Phase 1.5 decision point.
Migration 026 later implemented Option C, a database trigger that rejects
UPDATE and DELETE on `platform_admin_audit_events`. The current production
approval, retention, and maintenance implications are tracked in
`docs/PLATFORM_ADMIN_PHASE_4_PRODUCTION_READINESS.md`.

### Rerun and partial-migration safety

All three migrations are safely rerunnable when the target is absent or already
has the exact expected definition:

- `CREATE TABLE IF NOT EXISTS` avoids duplicate table creation;
- comments, revocations, and grants are repeatable;
- `CREATE INDEX IF NOT EXISTS` makes both audit indexes repeatable;
- migration 025 repeats `ENABLE ROW LEVEL SECURITY` safely and replaces each
  named policy through `DROP POLICY IF EXISTS` followed by `CREATE POLICY`.

They intentionally do not repair a conflicting pre-existing table. Preflight
must stop deployment if either target table or identity-sequence name exists
before the first application.

When each file is executed inside its own transaction, any failure rolls back
that file. If an earlier migration commits and a later migration fails, retain
the successful earlier state, roll back only the failed transaction, diagnose,
and rerun the failed migration. Do not improvise ALTER statements or drop earlier
tables merely to clear the failure.

### Migration defects

One verified grant defect was found and corrected in both migrations. `GRANT` is
additive: granting a subset to `service_role` did not remove broader direct
privileges supplied by a default ACL. Both migrations now revoke all direct
table and sequence privileges from `service_role` before granting back only the
intended minimum set. This makes migration 024's direct-grant append-only claim
deterministic and prevents unintended DELETE on migration 023's table.

This correction does not remove privileges inherited through role membership or
owner/superuser authority; the inspection and approval steps remain required.

The `users.company_id ON DELETE CASCADE` and
`platform_admin_users.user_id ON DELETE RESTRICT` interaction is an intentional
operational constraint, not a SQL defect: deleting a platform administrator's
company will be blocked. Platform administrators must belong to a protected
internal company.

## Inspection SQL

The SELECT-only `docs/platform_admin_phase_1_5_security_inspection.sql` was used
to verify staging. Run it again before and after any separately approved
production deployment. It reports:

- environment identity and target-object collisions;
- relevant role attributes and memberships;
- columns and identity state;
- ownership and RLS flags;
- direct ACL entries and effective privileges;
- default and schema privileges;
- RLS policies;
- constraints, indexes, and unexpected triggers.

Save every result set with the staging approval evidence.

## First-platform-admin bootstrap runbook

This runbook requires a separately approved bootstrap change window. The three
migrations are verified in staging, but protected-company designation and
bootstrap authorization are still outstanding. Do not create bootstrap data
until both are approved.

### 1. Approval evidence before mutation

Create an external approval record containing:

- staging or production project identifier;
- change ticket and approver;
- operator identity;
- approved internal user email and expected numeric user ID;
- protected internal company ID and name;
- confirmation that the company is excluded from tenant deletion workflows;
- timestamp and migration commit hash;
- rollback and emergency-revocation owner.

Do not place secrets, password hashes, tokens, or service keys in this record.

### 2. Read-only candidate verification

Replace all angle-bracket placeholders, then run this SELECT separately:

```sql
SELECT
    user_row.id AS user_id,
    user_row.email,
    user_row.full_name,
    user_row.status AS user_status,
    user_row.role AS tenant_role_for_information_only,
    user_row.company_id,
    company_row.company_name,
    company_row.status AS company_status,
    existing_admin.id AS existing_platform_admin_id,
    existing_admin.is_active AS existing_platform_admin_is_active
FROM public.users AS user_row
JOIN public.companies AS company_row
  ON company_row.id = user_row.company_id
LEFT JOIN public.platform_admin_users AS existing_admin
  ON existing_admin.user_id = user_row.id
WHERE user_row.id = <APPROVED_INTERNAL_USER_ID>
  AND lower(user_row.email) = lower('<APPROVED_INTERNAL_EMAIL>')
  AND user_row.company_id = <PROTECTED_INTERNAL_COMPANY_ID>;
```

Require exactly one row, `user_status = 'active'`, the approved company, and
`existing_platform_admin_id IS NULL`. The displayed tenant role is not an
authorization input and must not be changed.

### 3. Bootstrap insert

After a second operator confirms the SELECT output against the approval record,
run the following in the approved environment. Do not add `ON CONFLICT DO
NOTHING`; a duplicate must fail visibly.

```sql
BEGIN;

INSERT INTO public.platform_admin_users (
    user_id,
    is_active,
    created_at,
    updated_at,
    created_by_user_id
)
SELECT
    user_row.id,
    TRUE,
    NOW(),
    NOW(),
    NULL
FROM public.users AS user_row
JOIN public.companies AS company_row
  ON company_row.id = user_row.company_id
WHERE user_row.id = <APPROVED_INTERNAL_USER_ID>
  AND lower(user_row.email) = lower('<APPROVED_INTERNAL_EMAIL>')
  AND user_row.status = 'active'
  AND user_row.company_id = <PROTECTED_INTERNAL_COMPANY_ID>
  AND company_row.id = <PROTECTED_INTERNAL_COMPANY_ID>
RETURNING id, user_id, is_active, created_at, updated_at, created_by_user_id;

COMMIT;
```

Require exactly one returned row. If no row is returned or any value differs,
do not continue; record the failure and investigate.

### 4. Read-only mapping verification

```sql
SELECT
    platform_admin.id AS platform_admin_user_id,
    platform_admin.user_id,
    platform_admin.is_active,
    platform_admin.created_at,
    platform_admin.updated_at,
    platform_admin.created_by_user_id,
    user_row.email,
    user_row.status AS user_status,
    user_row.role AS tenant_role_for_information_only,
    company_row.id AS company_id,
    company_row.company_name,
    company_row.status AS company_status
FROM public.platform_admin_users AS platform_admin
JOIN public.users AS user_row
  ON user_row.id = platform_admin.user_id
JOIN public.companies AS company_row
  ON company_row.id = user_row.company_id
WHERE platform_admin.user_id = <APPROVED_INTERNAL_USER_ID>;
```

Attach the result to the external approval record. Confirm that no tenant role
was changed.

### 5. Emergency revocation

Revocation preserves identity and audit attribution. It must never delete the
mapping or modify `users.role`.

```sql
UPDATE public.platform_admin_users
SET
    is_active = FALSE,
    updated_at = NOW()
WHERE user_id = <APPROVED_INTERNAL_USER_ID>
  AND is_active = TRUE
RETURNING id, user_id, is_active, updated_at;
```

Require exactly one returned row and record the operator, approver, reason,
timestamp, and output externally. Phase 2 authorization must fail closed as soon
as `is_active` becomes false.

## Staging deployment record and reusable checklist

The schema, ownership, RLS, policy, grant, index, sequence, and trigger checks
below were completed successfully where marked. Items concerning rerun testing,
rollback exercises, evidence storage, or future production approval remain
unchecked unless separately recorded.

### Authorization and preflight

- [ ] Confirm in writing that the target is staging, never production.
- [ ] Record the Git commit and SHA-256 hashes of migrations 023, 024, and 025.
- [ ] Run the Phase 1 and Phase 1.5 SELECT-only inspection scripts.
- [ ] Confirm both target tables and both target sequences are absent.
- [ ] Confirm `anon`, `authenticated`, and `service_role` exist.
- [ ] Record the migration executor, expected object owner, role memberships,
      default ACLs, public-schema ACLs, and `service_role.rolbypassrls`.
- [x] Approved and applied migration 025 in staging.

Suggested local review commands:

```powershell
Get-FileHash data\023_create_platform_admin_users.sql -Algorithm SHA256
Get-FileHash data\024_create_platform_admin_audit_events.sql -Algorithm SHA256
Get-FileHash data\025_enable_platform_admin_rls.sql -Algorithm SHA256
Get-Content data\023_create_platform_admin_users.sql
Get-Content data\024_create_platform_admin_audit_events.sql
Get-Content data\025_enable_platform_admin_rls.sql
git diff --check
```

### Migration 023

- [x] Migration 023 applied successfully in staging.
- [ ] Stop and `ROLLBACK` on any error; do not patch the live table ad hoc.
- [x] Reran the Phase 1.5 inspection SQL.
- [x] Verified the identity PK, user FKs, constraints/indexes, `postgres`
      ownership, sequence privileges, and absence of triggers.
- [x] Confirmed effective table privileges: `anon` and `authenticated` all false;
      `service_role` SELECT/INSERT/UPDATE true and DELETE false.
- [x] Confirmed RLS is enabled and not forced after migration 025.

### Migration 024

- [x] Migration 024 applied successfully in staging.
- [ ] Stop and `ROLLBACK` on any error.
- [x] Reran the Phase 1.5 inspection SQL.
- [x] Verified the identity PK, actor FK, checks, `postgres` ownership, sequence
      privileges, and absence of unexpected triggers.
- [x] Verified actor and resource timeline indexes exactly match migration 024.
- [x] Confirmed effective table privileges: `anon` and `authenticated` all false;
      `service_role` SELECT/INSERT true and UPDATE/DELETE false.
- [x] Confirmed only `service_role` has identity-sequence USAGE among the three
      application-facing roles.

### Completed RLS staging step

- [x] Applied `data/025_enable_platform_admin_rls.sql` in staging.
- [x] Verified RLS enabled and not forced on both tables.
- [x] Verified no policies exist for `anon` or `authenticated`.
- [x] Verified the service-role policy operation matrix.
- [x] Recorded that `service_role` policies do not constrain a role with
      `BYPASSRLS`.

### Rerun and failure handling

- [ ] Capture the inspection output, rerun migrations 023 and 024 in order, and
      confirm the second run succeeds without changing catalog definitions.
- [ ] If a file fails inside its transaction, issue `ROLLBACK`, preserve the
      exact error, and compare the catalog with the last successful checkpoint.
- [ ] If 023 committed and 024 failed, leave 023 intact and repair only the cause
      of the 024 failure through reviewed migration changes.
- [ ] On a disposable staging clone only, test dependency-aware rollback order
      inside a transaction: audit events first, platform-admin users second, then
      `ROLLBACK` so no objects are permanently removed.

Rollback-order test for a disposable staging clone only:

```sql
BEGIN;
DROP TABLE public.platform_admin_audit_events;
DROP TABLE public.platform_admin_users;
ROLLBACK;
```

Do not run the rollback-order test in production or a shared environment with
active bootstrap data.

### Completion evidence

- [ ] Save all preflight and post-migration result sets.
- [ ] Save migration transaction results and hashes.
- [ ] Record every deviation and approval.
- [ ] Do not proceed to production. Production deployment requires a separate
      reviewed request after staging evidence and all decisions below are closed.

## Production gates requiring approval

Staging verification is complete, but production deployment remains blocked
until all of the following are approved:

1. **Protected internal company:** designate the company, exclude it from tenant
   deletion, and assign lifecycle ownership.
2. **First-platform-admin bootstrap:** approve the internal user, operator,
   approver, second verifier, evidence system, and emergency revocation owner.
3. **Audit metadata:** approve an allowlist, maximum size, secret/PII redaction,
   and handling for malformed or excessive metadata.
4. **Retention and archival:** define retention duration, archival destination,
   legal/security holds, deletion authority, and evidence requirements.
5. **Append-only enforcement beyond grants:** accept grant-based protection or approve a
   dedicated NOLOGIN/NO BYPASSRLS database role or rejection trigger.
6. **Production executor and ownership:** approve the production migration
   executor, expected `postgres` ownership, monitoring, and recovery procedure.

## Phase 2.5 successor runbook

The staging-only bootstrap and manual API verification procedure is recorded in
`docs/PLATFORM_ADMIN_PHASE_2_5_STAGING_BOOTSTRAP_AND_API_VERIFICATION.md`.
Phase 2.5 verification completed successfully: all five endpoints returned 200,
the five expected audit events were verified, and immediate revocation denied
the next request. The mapping row remains present and inactive. This evidence
does not authorize production deployment.
