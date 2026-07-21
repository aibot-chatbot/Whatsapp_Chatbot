# Platform Admin Production Deployment Runbook

## Status

**Prepared, not authorized, and not executed.** Production currently has no
platform-admin migrations, bootstrap data, backend, or frontend deployment. The
staging mapping remains inactive. This runbook is executable only after every
gate in `docs/PLATFORM_ADMIN_PHASE_4_PRODUCTION_READINESS.md` is approved.

Do not modify `users.role`, create customer-tenant mappings, disable audit
enforcement, change Flow Builder/Broadcast, or introduce endpoints/mutations
during this window.

## Required change record

Before the window, fill these values in the restricted change record—not in
this repository:

```text
PRODUCTION_SUPABASE_ORGANIZATION=
PRODUCTION_SUPABASE_PROJECT_REFERENCE=
PRODUCTION_REGION=
PRODUCTION_DATABASE_NAME=
PRODUCTION_DATABASE_HOSTNAME=
CHANGE_TICKET=
CHANGE_WINDOW_START_UTC=
CHANGE_WINDOW_END_UTC=
MIGRATION_EXECUTOR=
EXPECTED_OWNER=postgres
DATABASE_RECOVERY_OPERATOR=
BACKEND_COMMIT=
FRONTEND_COMMIT=
MIGRATION_COMMIT=
BACKEND_ARTIFACT_ID=
FRONTEND_ARTIFACT_ID=
MIGRATION_023_SHA256=
MIGRATION_024_SHA256=
MIGRATION_025_SHA256=
MIGRATION_026_SHA256=
BACKUP_ID_AND_UTC_TIME=
ISOLATED_RESTORE_EVIDENCE=
PROTECTED_INTERNAL_COMPANY_ID=
APPROVED_INTERNAL_USER_ID=
APPROVED_INTERNAL_USER_EMAIL=
PLATFORM_ADMIN_MAPPING_FINAL_STATE=inactive
OPERATOR=
APPROVER=
SECOND_VERIFIER=
REVOCATION_OWNER=
MONITORING_OWNER=
EVIDENCE_LOCATION=
APPEND_ONLY_OPTION=
```

Never record a JWT, database password, service-role key, authorization header,
or unredacted API body.

## Release and migration hash commands

Run from a clean checkout of the approved release commit:

```powershell
git status --short
git rev-parse HEAD
git log -1 --format="%H %cI %s" -- app
git log -1 --format="%H %cI %s" -- frontend
git log -1 --format="%H %cI %s" -- data/023_create_platform_admin_users.sql data/024_create_platform_admin_audit_events.sql data/025_enable_platform_admin_rls.sql data/026_enforce_platform_admin_audit_append_only.sql
Get-FileHash data\023_create_platform_admin_users.sql -Algorithm SHA256
Get-FileHash data\024_create_platform_admin_audit_events.sql -Algorithm SHA256
Get-FileHash data\025_enable_platform_admin_rls.sql -Algorithm SHA256
Get-FileHash data\026_enforce_platform_admin_audit_append_only.sql -Algorithm SHA256
Get-FileHash docs\platform_admin_phase_1_5_security_inspection.sql -Algorithm SHA256
Get-FileHash docs\platform_admin_phase_4_append_only_inspection.sql -Algorithm SHA256
Get-FileHash docs\platform_admin_phase_4_append_only_staging_verification.sql -Algorithm SHA256
```

Require an empty `git status --short`. Compare every hash with the approval
record. Stop on any mismatch; do not regenerate approvals during the window.

## Backup and restore gate

- [ ] Confirm production automated backups and point-in-time recovery are
      enabled, healthy, and cover a timestamp immediately before the window.
- [ ] Create/record the approved pre-change backup or recovery point using the
      production database owner's standard process.
- [ ] Verify encryption, retention, region, access, and restore permissions.
- [ ] Restore the relevant backup into an isolated non-production recovery
      project/database using the standard recovery process.
- [ ] In the isolated restore, verify `users`/`companies` schema, representative
      row counts, constraints, and application-critical health checks.
- [ ] Record backup/recovery IDs, UTC timestamps, operator/verifier, restore
      duration, checksums where available, and validation result.
- [ ] Delete or retain the isolated restore only under the approved recovery
      evidence/data-handling policy.

No successful isolated restore evidence means NO-GO.

## Read-only production preflight SQL

### Project identity and dependencies

The Supabase project reference is not reliably supplied by ordinary PostgreSQL
SQL. Record it from the approved Supabase control plane and compare it with the
configured production hostname. Then run:

```sql
SELECT
    current_database() AS database_name,
    current_user AS current_user,
    session_user AS session_user,
    current_setting('server_version') AS postgres_version,
    current_setting('server_version_num') AS postgres_version_number,
    NOW() AS checked_at;

SELECT
    table_name,
    ordinal_position,
    column_name,
    data_type,
    udt_name,
    is_nullable,
    column_default,
    is_identity,
    identity_generation
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (
      (table_name = 'users' AND column_name IN (
          'id', 'company_id', 'email', 'full_name', 'status', 'role'
      ))
      OR
      (table_name = 'companies' AND column_name IN (
          'id', 'company_name', 'status'
      ))
  )
ORDER BY table_name, ordinal_position;

SELECT
    relation.relname AS table_name,
    constraint_row.conname AS constraint_name,
    constraint_row.contype AS constraint_type,
    pg_get_constraintdef(constraint_row.oid, true) AS definition
FROM pg_constraint AS constraint_row
JOIN pg_class AS relation
  ON relation.oid = constraint_row.conrelid
JOIN pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relname IN ('users', 'companies')
  AND (
      constraint_row.contype IN ('p', 'f')
      OR pg_get_constraintdef(constraint_row.oid, true) ILIKE '%company_id%'
  )
ORDER BY table_name, constraint_name;
```

Require the exact dependency types/constraints recorded in the Phase 4
readiness checklist. Stop on a mismatch.

### Collision check

```sql
SELECT
    to_regclass('public.platform_admin_users') AS platform_admin_users,
    to_regclass('public.platform_admin_users_id_seq') AS platform_admin_users_id_seq,
    to_regclass('public.platform_admin_audit_events') AS platform_admin_audit_events,
    to_regclass('public.platform_admin_audit_events_id_seq') AS platform_admin_audit_events_id_seq;
```

All four values must be null before migration 023. Any non-null value blocks
deployment and requires collision investigation; do not rely on `IF NOT EXISTS`
to accept an unknown object.

### Full security inspection

Open `docs/platform_admin_phase_1_5_security_inspection.sql`, verify its SHA-256
against the approved release, and execute it unchanged in the production SQL
Editor. It is SELECT-only and reports:

- environment identity and collisions;
- role attributes, BYPASSRLS, and memberships;
- ownership and RLS;
- direct/effective table and sequence privileges;
- default and schema privileges;
- policies, columns, constraints, indexes, and triggers.

Save every result set. Before 023, target-object queries should be empty or
null. Review non-target role/default/schema output even when targets are absent.

## Production deployment sequence

### 0. Go/no-go and freeze

1. Approver confirms every readiness gate, backup/restore, monitoring, evidence
   location, protected company, bootstrap identity, and append-only decision.
2. Operator and second verifier independently confirm production project and
   release hashes.
3. Start the UTC change window and announce a platform-admin deployment freeze.
4. Ensure no unrelated database migration or backend/frontend deployment runs
   concurrently.

### 1. Apply migration 023

In the production Supabase SQL Editor, paste the exact approved contents of
`data/023_create_platform_admin_users.sql` between `BEGIN;` and `COMMIT;` and run
as one operation:

```sql
BEGIN;
-- Exact, hash-verified contents of data/023_create_platform_admin_users.sql
COMMIT;
```

Do not edit object names, grants, ownership, constraints, or add bootstrap data.
Record start/end UTC time and the SQL Editor result.

Verify immediately:

```sql
SELECT
    column_name, data_type, is_nullable, column_default,
    is_identity, identity_generation
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'platform_admin_users'
ORDER BY ordinal_position;

SELECT
    constraint_row.conname,
    constraint_row.contype,
    pg_get_constraintdef(constraint_row.oid, true) AS definition
FROM pg_constraint AS constraint_row
WHERE constraint_row.conrelid = 'public.platform_admin_users'::regclass
ORDER BY constraint_row.conname;

SELECT
    pg_get_userbyid(relation.relowner) AS owner,
    relation.relrowsecurity AS rls_enabled,
    relation.relforcerowsecurity AS rls_forced
FROM pg_class AS relation
WHERE relation.oid = 'public.platform_admin_users'::regclass;
```

Expected: six columns with BIGINT identity ID; unique/FK constraints exactly as
023; owner `postgres`; RLS false until 025. Run the full inspection script and
confirm effective privileges: anon/authenticated all false; service_role
SELECT/INSERT/UPDATE true and DELETE false; sequence USAGE true only as intended.

### 2. Apply migration 024

Only after 023 verification, run the exact hash-approved 024 file in one
transaction:

```sql
BEGIN;
-- Exact, hash-verified contents of data/024_create_platform_admin_audit_events.sql
COMMIT;
```

Verify immediately:

```sql
SELECT
    column_name, data_type, is_nullable, column_default,
    is_identity, identity_generation
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'platform_admin_audit_events'
ORDER BY ordinal_position;

SELECT
    constraint_row.conname,
    constraint_row.contype,
    pg_get_constraintdef(constraint_row.oid, true) AS definition
FROM pg_constraint AS constraint_row
WHERE constraint_row.conrelid = 'public.platform_admin_audit_events'::regclass
ORDER BY constraint_row.conname;

SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'platform_admin_audit_events'
ORDER BY indexname;
```

Expected: identity PK, actor FK, three checks, actor/resource timeline indexes,
owner `postgres`, and RLS false until 025. Full inspection must show
anon/authenticated all false; service_role SELECT/INSERT true and UPDATE/DELETE
false; intended sequence USAGE only.

### 3. Apply migration 025

Only after 024 verification, run the exact hash-approved 025 file in one
transaction:

```sql
BEGIN;
-- Exact, hash-verified contents of data/025_enable_platform_admin_rls.sql
COMMIT;
```

Verify RLS and policies:

```sql
SELECT
    relation.relname AS table_name,
    pg_get_userbyid(relation.relowner) AS owner,
    relation.relrowsecurity AS rls_enabled,
    relation.relforcerowsecurity AS rls_forced
FROM pg_class AS relation
JOIN pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relname IN (
      'platform_admin_users',
      'platform_admin_audit_events'
  )
ORDER BY relation.relname;

SELECT
    tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN (
      'platform_admin_users',
      'platform_admin_audit_events'
  )
ORDER BY tablename, policyname;
```

Require both tables RLS-enabled/not forced, exactly three service-role policies
on users (SELECT/INSERT/UPDATE), exactly two on audit events (SELECT/INSERT), no
client policies, no DELETE policies, and no audit UPDATE policy. Rerun the full
inspection script and compare all output with the approved matrix.

### 4. Apply migration 026

Migration 026 passed the documented staging inspection and rollback-only
verification. After production-specific hash/owner/change approval, run its
exact hash-verified contents in one production transaction:

```sql
BEGIN;
-- Exact, hash-verified contents of data/026_enforce_platform_admin_audit_append_only.sql
COMMIT;
```

Run `docs/platform_admin_phase_4_append_only_inspection.sql` unchanged. Require:

- function owner `postgres` from the approved executor;
- SECURITY INVOKER (`security_definer = false`);
- fixed `search_path=pg_catalog` and exact function definition;
- no direct EXECUTE for PUBLIC, anon, authenticated, or service_role;
- one enabled non-internal BEFORE UPDATE OR DELETE row trigger on
  `platform_admin_audit_events`;
- unchanged owner, RLS state, policies, direct/effective table grants, and
  sequence privileges from migrations 023–025.

Do not run the mutation-based rollback verification in production. Retain its
successful staging evidence instead. Do not write a trigger, role, or
maintenance bypass ad hoc in the production SQL Editor.

### 5. Deploy backend

The repository does not define a single production hosting command. Attach the
approved hosting-platform command/procedure to the change ticket before the
window; do not invent it during deployment.

1. Deploy the immutable backend artifact built from `BACKEND_COMMIT`.
2. Verify artifact ID/hash and environment label without printing environment
   values or secrets.
3. Confirm health checks and ordinary tenant authentication endpoints.
4. Confirm the route table exposes only the five approved GET platform routes.
5. With no mapping yet, verify an active ordinary tenant admin and owner each
   receive `403 platform_admin_access_denied` from `/api/platform-admin/me`.
6. Monitor authentication/authorization/audit/5xx alerts. Do not bootstrap if
   tenant denial or health checks fail.

### 6. Deploy frontend

1. Deploy the immutable static artifact built from `FRONTEND_COMMIT` through the
   approved hosting procedure.
2. Verify artifact ID/hash and cache/CDN version.
3. Confirm the ordinary tenant sidebar contains no platform link.
4. Confirm the platform URL starts in Checking Access and an unmapped tenant
   admin/owner reaches Access Denied with no platform data.
5. Verify Return to Tenant App resolves to `bots.html` and normal logout still
   follows the existing session mechanism.

Do not treat frontend hiding as authorization.

### 7. Read-only bootstrap candidate verification

Replace placeholders and run this SELECT only:

```sql
SELECT
    user_row.id AS user_id,
    user_row.email,
    user_row.full_name,
    user_row.status AS user_status,
    user_row.role AS tenant_role_before_bootstrap,
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
  AND lower(btrim(user_row.email)) =
      lower(btrim('<APPROVED_INTERNAL_USER_EMAIL>'))
  AND user_row.company_id = <PROTECTED_INTERNAL_COMPANY_ID>;
```

Require exactly one active user, active protected company, approved ID/email,
tenant role `owner`/`admin`/`member` for information only, and no existing
mapping. The second verifier compares output with the approval record.

### 8. Bootstrap the approved production user

Run exactly one transaction. Do not use `ON CONFLICT`, modify `users.role`, or
insert any other user.

```sql
BEGIN;

DO $$
BEGIN
    IF (
        SELECT COUNT(*)
        FROM public.users AS user_row
        JOIN public.companies AS company_row
          ON company_row.id = user_row.company_id
        WHERE user_row.id = <APPROVED_INTERNAL_USER_ID>
          AND lower(btrim(user_row.email)) =
              lower(btrim('<APPROVED_INTERNAL_USER_EMAIL>'))
          AND user_row.company_id = <PROTECTED_INTERNAL_COMPANY_ID>
          AND user_row.status = 'active'
          AND user_row.role IN ('owner', 'admin', 'member')
          AND company_row.status = 'active'
    ) <> 1 THEN
        RAISE EXCEPTION
            'Bootstrap identity, active status, tenant role, or protected company did not match approval';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.platform_admin_users AS platform_admin
        WHERE platform_admin.user_id = <APPROVED_INTERNAL_USER_ID>
    ) THEN
        RAISE EXCEPTION
            'A platform-admin mapping already exists for the approved user';
    END IF;
END
$$;

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
  AND lower(btrim(user_row.email)) =
      lower(btrim('<APPROVED_INTERNAL_USER_EMAIL>'))
  AND user_row.company_id = <PROTECTED_INTERNAL_COMPANY_ID>
  AND user_row.status = 'active'
  AND user_row.role IN ('owner', 'admin', 'member')
  AND company_row.status = 'active'
RETURNING
    id AS platform_admin_user_id,
    user_id,
    is_active,
    created_at,
    updated_at,
    created_by_user_id;

COMMIT;
```

Require exactly one returned active mapping with null creator. Save redacted
output and immediately run the post-bootstrap SELECT from the Phase 2.5
runbook. Confirm `users.role` is unchanged.

### 9. Verify the five endpoints and audit events

Record a UTC baseline and current maximum audit ID before requests:

```sql
SELECT
    NOW() AS verification_started_at,
    COALESCE(MAX(id), 0) AS prior_max_audit_id
FROM public.platform_admin_audit_events;
```

Using the approved user's normal production application session, issue exactly
one request to each endpoint in this order and retain status/code plus redacted
shape validation only:

1. `GET /api/platform-admin/me`
2. `GET /api/platform-admin/companies?limit=1&offset=0&sort_by=id&sort_order=asc`
3. `GET /api/platform-admin/companies/<PROTECTED_INTERNAL_COMPANY_ID>`
4. `GET /api/platform-admin/companies/<PROTECTED_INTERNAL_COMPANY_ID>/subscription`
5. `GET /api/platform-admin/companies/<PROTECTED_INTERNAL_COMPANY_ID>/ai-credit-usage`

All must return 200 with the stable success/data envelope. Do not retain live
tokens or unredacted bodies.

Verify exactly five new events for the mapping after the baseline:

```sql
SELECT
    id,
    platform_admin_user_id,
    action,
    resource_type,
    resource_id,
    metadata,
    created_at
FROM public.platform_admin_audit_events
WHERE platform_admin_user_id = <PLATFORM_ADMIN_USER_ID>
  AND id > <PRIOR_MAX_AUDIT_ID>
ORDER BY id;
```

Expected ordered action/resource pairs are those in
`docs/PLATFORM_ADMIN_AUDIT_POLICY.md`. Require exactly five rows, correct
resource IDs, `outcome=success`, fixed endpoint templates, GET method, expected
list/period metadata, and timestamps within the window.

Check for unsupported top-level keys:

```sql
SELECT event.id, metadata_key.key AS unsupported_key
FROM public.platform_admin_audit_events AS event
CROSS JOIN LATERAL jsonb_object_keys(event.metadata) AS metadata_key(key)
WHERE event.platform_admin_user_id = <PLATFORM_ADMIN_USER_ID>
  AND event.id > <PRIOR_MAX_AUDIT_ID>
  AND metadata_key.key NOT IN (
      'outcome', 'endpoint', 'http_method', 'limit', 'offset',
      'sort_by', 'sort_order', 'search_applied', 'status_filter',
      'returned_count', 'period_start', 'period_end'
  );
```

Require zero rows. A security reviewer must also confirm metadata contains no
tokens, credentials, prompts, messages, payloads, PII, or raw search text. No
audit UPDATE/DELETE is needed or allowed.

### 10. Verify frontend and tenant denial

- Load dashboard, company directory, and the approved internal company detail.
- Verify labels, identity, exact counts, directory controls, profile,
  subscription, AI-credit/usage, Return to Tenant App, and Logout.
- Verify no mutation/export/impersonation/messaging/payment/subscription-change/
  credit-adjustment control exists.
- Use separate active tenant admin and owner users with no mappings. Each must
  receive the same 403 code and no platform UI/data.
- Account for the additional expected audit events generated by successful UI
  requests and validate them under the audit policy.

### 11. Verify revocation and final mapping state

Run the targeted revocation transaction from
`docs/PLATFORM_ADMIN_EMERGENCY_REVOCATION.md`. Require one inactive returned row.
The next endpoint request and browser refresh must show 403 Access Denied and no
stale data.

**Default production decision: leave the mapping inactive after verification.**
Ongoing active production access requires a separate signed go-live decision
and separately reviewed reactivation; it is not implicit in this deployment.
Record the final database state and decision.

### 12. Post-deployment monitoring and closure

1. Rerun the full inspection SQL and append-only trigger checks if selected.
2. Compare ownership, grants, memberships, default ACLs, sequence privileges,
   RLS, policies, constraints, indexes, and triggers with approval evidence.
3. Confirm authorization, audit-failure, 5xx, denial, drift, and protected-
   company deletion alerts are live and routed to named on-call owners.
4. Monitor continuously during the window and heightened cadence for seven
   days, even while the mapping is inactive.
5. Attach migration results/hashes, artifact IDs, redacted bootstrap/API/UI/
   audit/revocation output, monitoring screenshots without sensitive data,
   deviations, and final mapping state.
6. Approver records go-live closure or rollback/incident disposition.

## Failure handling and rollback strategy

### Migration transaction failure

- Stop immediately. A correctly wrapped migration should roll back as one
  transaction; verify target objects and ACLs with the inspection SQL.
- Do not rerun blindly. Determine whether SQL Editor execution actually wrapped
  the full file and whether any object survived.
- If partial state exists, keep backend/frontend undeployed and mapping absent.
  Prepare a reviewed forward-repair or cleanup change; do not improvise DROP or
  ALTER statements in the window.
- Preserve error/result output without secrets and record the failed hash.

### Backend deployment failure

- Do not deploy frontend or bootstrap.
- Roll back to the previously approved backend artifact through the hosting
  platform's recorded procedure.
- Leave created tables/RLS inert. With no mapping and no platform backend,
  schema removal is unnecessary and riskier than retention.
- Recheck ordinary tenant health and close/extend the change under approval.

### Frontend deployment failure

- Do not bootstrap.
- Roll back the static artifact/CDN release to its recorded predecessor.
- The backend remains protected by application authorization; verify ordinary
  tenant denial and no mapping.
- Do not add a tenant-sidebar link as a workaround.

### Bootstrap failure

- The transaction must roll back. Verify no mapping exists for the approved
  user and `users.role` is unchanged.
- Stop on identity/status/company mismatch or duplicate mapping. Do not add
  conflict suppression, update an unknown mapping, or choose another user.
- Backend/frontend may remain deployed but inaccessible; resolve through a new
  approved bootstrap window.

### Audit failure

- Require sanitized 503 and confirmation that tenant data was withheld.
- Revoke the mapping if active and follow the emergency audit-failure path.
- Inspect INSERT/sequence privileges, constraints, service/database health,
  append-only control, and drift. Never disable audit-before-response.

### Unexpected access exposure

- Globally revoke mappings, roll back/deny platform backend routes, preserve
  evidence, and open a security incident.
- Test tenant admin/owner denial, compare artifacts/configuration without
  revealing values, and inspect mappings, user status, role memberships, grants,
  policies, RLS, owner, and trigger state.

### Emergency revocation

- Use targeted revocation when bounded; global revocation when uncertain.
- Require next-request 403 and cleared browser data. Preserve mapping/audit rows.
- Do not reactivate inside the incident.

### `service_role` privilege drift

- Revoke mappings and stop platform use.
- Capture direct/effective grants, memberships, default ACLs, owner, sequence
  privileges, schema grants, and BYPASSRLS.
- Repair only through a reviewed database change, then rerun full inspection
  and staging-equivalent tests.

### RLS policy mismatch

- Revoke mappings and stop. Unexpected client, DELETE, or audit UPDATE policies
  are security exposure.
- Record the mismatch and apply only an approved policy repair/reapplication.
  RLS still does not constrain BYPASSRLS service_role.

### Backup restore

- Prefer forward repair for isolated platform objects when data integrity is
  understood. Do not restore the entire production database merely to remove
  unused empty tables.
- Use point-in-time/full restore only for confirmed broader corruption or data
  loss under incident commander/database-owner approval.
- Restore first to isolation, validate integrity and recovery point, plan the
  production cutover, preserve post-backup evidence, and communicate expected
  data loss/downtime. Never overwrite production directly from an unverified
  backup.

## Abort criteria

Abort and leave/no longer leave mappings inactive on any wrong project,
schema/object collision, hash mismatch, missing approval, unsuccessful restore,
unexpected owner/grant/membership/RLS/policy/trigger, tenant admin/owner access,
audit mismatch/failure, raw sensitive output, unmonitored deployment, or
failure to demonstrate immediate revocation.
