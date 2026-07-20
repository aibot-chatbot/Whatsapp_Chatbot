# Platform Admin Phase 2.5: Staging Bootstrap and Manual API Verification

## Status and scope

**Completed successfully in staging; not deployed to production.** Migrations
023, 024, and 025 and the Phase 2 read-only backend were manually verified in
staging. The bootstrap mapping was revoked at the end of the test and remains
present with `is_active = false`. It must not be reactivated without a separate
approved change.

Nothing in this runbook changes `users.role`. A tenant `owner`, `admin`, or
`member` role never grants platform access. The application must validate an
active application user and refresh an active `platform_admin_users` mapping on
every protected request because `service_role` has `BYPASSRLS`.

Do not use this runbook in production. Do not paste access tokens, passwords,
service keys, provider payloads, or unredacted API bodies into evidence.

## Completed staging verification summary

The retained staging evidence was reviewed and records the following safe
identifiers and outcomes:

| Area | Verified staging result |
|---|---|
| Protected internal company | `company_id = 29`, `Olympic Edu Sdn Bhd` |
| Approved internal user | `user_id = 32`, `aibot@iomaths.com` |
| Application-user state | Status remained `active` |
| Tenant role | Remained `admin`; no role change was made |
| Bootstrap mapping | `platform_admin_user_id = 1`, initially active |
| Bootstrap creator | `created_by_user_id IS NULL` |
| Post-bootstrap verification | Passed |
| Five approved GET endpoints | All returned HTTP 200 |
| Audit events | Exactly five matching events with expected actions/resources |
| Audit metadata | Only approved safe fields; no raw search text or prohibited data |
| Revocation | Set `is_active = false` and explicitly updated `updated_at` |
| Next request after revocation | HTTP 403, `platform_admin_access_denied` |
| Final mapping state | Row remains present and inactive |
| Production | No deployment or data change |

The successful requests were:

- `GET /api/platform-admin/me`
- `GET /api/platform-admin/companies`
- `GET /api/platform-admin/companies/29`
- `GET /api/platform-admin/companies/29/subscription`
- `GET /api/platform-admin/companies/29/ai-credit-usage`

The verified audit matrix was:

| Action | Resource type | Resource ID |
|---|---|---|
| `platform_admin.identity.read` | `platform_admin` | `1` |
| `platform_admin.company.list` | `company` | `NULL` |
| `platform_admin.company.read` | `company` | `29` |
| `platform_admin.company.subscription.read` | `company_subscription` | `29` |
| `platform_admin.company.ai_credit_usage.read` | `company_ai_credit_usage` | `29` |

Exactly five corresponding audit events were verified. Their actions, resource
types, resource IDs, metadata, and timestamps matched the approved endpoint
matrix. Metadata contained no tokens, secrets, prompts, messages, credentials,
or raw search text. No live tokens or unredacted API bodies are recorded here.

## Confirmed identification columns

The verified schema documentation and current repositories use these exact
columns:

| Identification | Table and column |
|---|---|
| User ID | `public.users.id` |
| Email | `public.users.email` |
| User status | `public.users.status` |
| Tenant role, informational only | `public.users.role` |
| User company ID | `public.users.company_id` |
| Company ID | `public.companies.id` |
| Company name | `public.companies.company_name` |
| Company status | `public.companies.status` |

`users.id`, `users.company_id`, and `companies.id` are BIGINT. The repository
does not contain an `is_internal`, deletion-protection, or operational-owner
column. Internal designation, lifecycle protection, and named ownership must
therefore be approved and recorded outside these tables before bootstrap.

## Protected internal-company requirements

The selected company must satisfy all of the following before any INSERT:

1. It is dedicated to internal SaaS operations and is not a customer tenant.
2. `companies.status = 'active'`.
3. It is explicitly excluded from every tenant deletion and offboarding
   workflow, including manual support procedures.
4. A named operational owner and backup owner are recorded in the approval
   system and are accountable for its lifecycle.
5. The selected user is a dedicated internal user belonging to that company;
   shared customer or support logins are not acceptable.
6. Deletion is treated as blocked while an active platform-admin mapping exists.
   The current FK behavior is stronger: because `users.company_id` cascades on
   company deletion while `platform_admin_users.user_id` uses `ON DELETE
   RESTRICT`, deletion is blocked while any mapping row exists, active or
   inactive. Never weaken that FK to make deletion succeed.

The approver and second verifier must confirm these operational facts; the SQL
schema cannot infer whether a company is genuinely internal.

## Candidate-selection SQL (SELECT only)

Run only in the staging Supabase SQL Editor. First review safe company
identifiers. This query intentionally does not select contacts or credentials.

```sql
SELECT
    company_row.id AS company_id,
    company_row.company_name,
    company_row.status AS company_status,
    COUNT(DISTINCT user_row.id) AS user_count,
    COUNT(DISTINCT platform_admin.id) AS existing_mapping_count,
    COUNT(DISTINCT platform_admin.id)
        FILTER (WHERE platform_admin.is_active = TRUE) AS active_mapping_count
FROM public.companies AS company_row
LEFT JOIN public.users AS user_row
  ON user_row.company_id = company_row.id
LEFT JOIN public.platform_admin_users AS platform_admin
  ON platform_admin.user_id = user_row.id
WHERE company_row.status = 'active'
GROUP BY
    company_row.id,
    company_row.company_name,
    company_row.status
ORDER BY
    company_row.company_name ASC,
    company_row.id ASC;
```

After external approval identifies the protected company, replace the
placeholder and inspect only users in that company:

```sql
SELECT
    user_row.id AS user_id,
    user_row.email,
    user_row.status AS user_status,
    user_row.role AS tenant_role_for_information_only,
    user_row.company_id,
    company_row.company_name,
    company_row.status AS company_status,
    platform_admin.id AS existing_platform_admin_user_id,
    platform_admin.is_active AS existing_mapping_is_active,
    platform_admin.created_at AS existing_mapping_created_at,
    platform_admin.updated_at AS existing_mapping_updated_at
FROM public.users AS user_row
JOIN public.companies AS company_row
  ON company_row.id = user_row.company_id
LEFT JOIN public.platform_admin_users AS platform_admin
  ON platform_admin.user_id = user_row.id
WHERE user_row.company_id = <PROTECTED_INTERNAL_COMPANY_ID>
ORDER BY
    user_row.email ASC,
    user_row.id ASC;
```

Finally, verify the exact approved identity before opening the bootstrap change
window:

```sql
SELECT
    user_row.id AS user_id,
    user_row.email,
    user_row.status AS user_status,
    user_row.role AS tenant_role_before_bootstrap,
    user_row.company_id,
    company_row.company_name,
    company_row.status AS company_status,
    platform_admin.id AS existing_platform_admin_user_id,
    platform_admin.is_active AS existing_mapping_is_active
FROM public.users AS user_row
JOIN public.companies AS company_row
  ON company_row.id = user_row.company_id
LEFT JOIN public.platform_admin_users AS platform_admin
  ON platform_admin.user_id = user_row.id
WHERE user_row.id = <APPROVED_INTERNAL_USER_ID>
  AND lower(btrim(user_row.email)) =
      lower(btrim('<APPROVED_INTERNAL_USER_EMAIL>'))
  AND user_row.company_id = <PROTECTED_INTERNAL_COMPANY_ID>;
```

Require exactly one row, active user and company statuses, a normal tenant role
of `owner`, `admin`, or `member`, and a null existing mapping ID. Save the
tenant role shown here so the post-bootstrap output can be compared to it.

## Exact staging bootstrap SQL template (do not execute without approval)

Replace all three placeholders manually. A second verifier must compare them
with the approval record before execution. Run the complete block as one SQL
Editor operation. It deliberately has no `ON CONFLICT` clause: an existing or
racing mapping must fail visibly.

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

Require exactly one returned row with `is_active = true` and
`created_by_user_id IS NULL`. On any exception, record the error, confirm the
transaction rolled back, and stop. Do not add conflict suppression, repair SQL,
or any update to `users.role`.

## Post-bootstrap verification SQL

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
    user_row.role AS tenant_role_after_bootstrap,
    user_row.company_id,
    company_row.company_name,
    company_row.status AS company_status
FROM public.platform_admin_users AS platform_admin
JOIN public.users AS user_row
  ON user_row.id = platform_admin.user_id
JOIN public.companies AS company_row
  ON company_row.id = user_row.company_id
WHERE platform_admin.user_id = <APPROVED_INTERNAL_USER_ID>
  AND lower(btrim(user_row.email)) =
      lower(btrim('<APPROVED_INTERNAL_USER_EMAIL>'))
  AND company_row.id = <PROTECTED_INTERNAL_COMPANY_ID>;
```

Require exactly one row. Compare `tenant_role_after_bootstrap` with the saved
`tenant_role_before_bootstrap`; they must be identical. Also require active
user, company, and mapping statuses, the approved IDs/email, and a null creator.

## Immediate-revocation SQL

Revocation is the final destructive-access test in the verification sequence.
It preserves the row and audit attribution and explicitly maintains the
application-managed timestamp. Never replace it with DELETE.

```sql
BEGIN;

UPDATE public.platform_admin_users
SET
    is_active = FALSE,
    updated_at = NOW()
WHERE user_id = <APPROVED_INTERNAL_USER_ID>
  AND is_active = TRUE
RETURNING
    id AS platform_admin_user_id,
    user_id,
    is_active,
    created_at,
    updated_at,
    created_by_user_id;

COMMIT;
```

Require exactly one returned row with `is_active = false`, then make the next
API request immediately. It must return `403 platform_admin_access_denied`.
Reactivation is a separate privileged change and is intentionally not included.

## Manual staging API verification checklist

Record a test-window start and end in UTC. Use the staging backend base URL and
the approved user's normal application JWT. Do not expose the JWT in tickets,
screenshots, shell output, or retained command history. Retain only response
status, stable error code, endpoint template, timestamp, and redacted structural
notes.

### Pre-bootstrap denials

- [ ] Without `Authorization`, `GET /api/platform-admin/me` returns 401.
- [ ] An active ordinary tenant `admin` with no mapping returns
      `403 platform_admin_access_denied`.
- [ ] An active ordinary tenant `owner` with no mapping returns the same 403.
- [ ] Confirm neither role receives platform access merely because of
      `users.role`.

### Five successful requests with the active mapping

Use `<TARGET_STAGING_COMPANY_ID>` from the approved test plan. It may be a test
tenant; it must not be taken from the JWT company claim.

- [ ] `GET /api/platform-admin/me` returns 200 and only the safe user/mapping
      identity shape.
- [ ] `GET /api/platform-admin/companies?limit=25&offset=0&sort_by=id&sort_order=asc&search=<SAFE_SEARCH_CANARY>`
      returns 200 with pagination. Use a unique non-sensitive canary and record
      it for the metadata-leak query below.
- [ ] `GET /api/platform-admin/companies/<TARGET_STAGING_COMPANY_ID>` returns
      200 for the path company, irrespective of the JWT tenant company.
- [ ] `GET /api/platform-admin/companies/<TARGET_STAGING_COMPANY_ID>/subscription`
      returns 200; absence of a subscription is represented safely rather than
      creating one.
- [ ] `GET /api/platform-admin/companies/<TARGET_STAGING_COMPANY_ID>/ai-credit-usage`
      returns 200; a missing balance reports `initialized = false` and performs
      no initialization write.

Do not exercise mutation, export, impersonation, messaging, reconciliation,
credit-adjustment, frontend, Flow Builder, or Broadcast behavior.

### Additional denial and revocation tests

- [ ] Use an approved inactive-user test step: deactivate the dedicated
      application user through the established staging account-status workflow,
      confirm the next request returns `403 account_inactive` before platform
      mapping evaluation, and restore the user to active. This reversible status
      test requires explicit approval and evidence; do not improvise SQL.
- [ ] Execute the approved immediate-revocation SQL above as the final mapping
      test. Confirm the next request returns
      `403 platform_admin_access_denied`.
- [ ] The revoked row remains present with `is_active = false`; this is also the
      inactive-mapping denial test.
- [ ] Confirm two consecutive requests before revocation were allowed and the
      first request after revocation was denied, demonstrating per-request
      database refresh.
- [ ] Retain the passing automated same-user role-change test as the required
      evidence that changing a valid JWT tenant-role claim does not alter
      platform access. Do not modify `users.role` or sign ad hoc staging JWTs for
      this runbook.

Changing `users.role` is prohibited in this runbook. Role independence is
manually demonstrated by the mapped internal user being allowed while ordinary
tenant admins and owners are denied. The same-user JWT role-change case remains
covered by the passing automated Phase 2 tests. A manual same-user role-change
test would require a separate approved tenant-role change or a controlled token
fixture; do not perform it as part of this bootstrap.

## Audit verification SQL and checklist

Run the following after the five successful requests and before revocation.
Use a UTC window that contains only those five requests.

### Event detail

```sql
SELECT
    audit_event.id AS audit_event_id,
    audit_event.platform_admin_user_id,
    audit_event.action,
    audit_event.resource_type,
    audit_event.resource_id,
    audit_event.metadata,
    audit_event.created_at
FROM public.platform_admin_audit_events AS audit_event
WHERE audit_event.platform_admin_user_id = <PLATFORM_ADMIN_USER_ID>
  AND audit_event.created_at >= '<TEST_WINDOW_START_UTC>'::timestamptz
  AND audit_event.created_at < '<TEST_WINDOW_END_UTC>'::timestamptz
ORDER BY audit_event.created_at ASC, audit_event.id ASC;
```

Require five rows in request order. Each timestamp must fall inside the window.

### One event per successful endpoint

```sql
WITH expected(action, resource_type, resource_id) AS (
    VALUES
        ('platform_admin.identity.read',
         'platform_admin', '<PLATFORM_ADMIN_USER_ID>'::text),
        ('platform_admin.company.list',
         'company', NULL::text),
        ('platform_admin.company.read',
         'company', '<TARGET_STAGING_COMPANY_ID>'::text),
        ('platform_admin.company.subscription.read',
         'company_subscription', '<TARGET_STAGING_COMPANY_ID>'::text),
        ('platform_admin.company.ai_credit_usage.read',
         'company_ai_credit_usage', '<TARGET_STAGING_COMPANY_ID>'::text)
), scoped_events AS (
    SELECT *
    FROM public.platform_admin_audit_events
    WHERE platform_admin_user_id = <PLATFORM_ADMIN_USER_ID>
      AND created_at >= '<TEST_WINDOW_START_UTC>'::timestamptz
      AND created_at < '<TEST_WINDOW_END_UTC>'::timestamptz
)
SELECT
    expected.action,
    expected.resource_type,
    expected.resource_id,
    COUNT(scoped_events.id) AS actual_count,
    COUNT(scoped_events.id) = 1 AS exactly_one_event
FROM expected
LEFT JOIN scoped_events
  ON scoped_events.action = expected.action
 AND scoped_events.resource_type = expected.resource_type
 AND scoped_events.resource_id IS NOT DISTINCT FROM expected.resource_id
GROUP BY
    expected.action,
    expected.resource_type,
    expected.resource_id
ORDER BY expected.action;
```

Every `exactly_one_event` value must be true.

### Metadata allowlist and redaction checks

```sql
WITH scoped_events AS (
    SELECT *
    FROM public.platform_admin_audit_events
    WHERE platform_admin_user_id = <PLATFORM_ADMIN_USER_ID>
      AND created_at >= '<TEST_WINDOW_START_UTC>'::timestamptz
      AND created_at < '<TEST_WINDOW_END_UTC>'::timestamptz
)
SELECT
    id AS audit_event_id,
    metadata - ARRAY[
        'outcome',
        'endpoint',
        'http_method',
        'limit',
        'offset',
        'sort_by',
        'sort_order',
        'search_applied',
        'status_filter',
        'returned_count',
        'period_start',
        'period_end'
    ]::text[] AS unexpected_metadata,
    metadata::text ~* '"[^"]*(authorization|cookie|token|secret|password|credential|api_key|service_role|signature|payload|prompt|message)[^"]*"[[:space:]]*:'
        AS has_prohibited_key,
    position(
        lower('<SAFE_SEARCH_CANARY>')
        IN lower(metadata::text)
    ) > 0 AS contains_raw_search_canary
FROM scoped_events
ORDER BY created_at ASC, id ASC;
```

For every row, `unexpected_metadata` must be `{}`, `has_prohibited_key` must be
false, and `contains_raw_search_canary` must be false. Manually confirm the list
event contains `search_applied: true` but not the search value. Metadata must not
contain authorization data, JWTs, secrets, credentials, prompts, messages, raw
exceptions, or Supabase payloads.

### Append-only posture

```sql
SELECT
    role_name,
    has_table_privilege(
        role_name,
        'public.platform_admin_audit_events',
        'SELECT'
    ) AS can_select,
    has_table_privilege(
        role_name,
        'public.platform_admin_audit_events',
        'INSERT'
    ) AS can_insert,
    has_table_privilege(
        role_name,
        'public.platform_admin_audit_events',
        'UPDATE'
    ) AS can_update,
    has_table_privilege(
        role_name,
        'public.platform_admin_audit_events',
        'DELETE'
    ) AS can_delete
FROM unnest(ARRAY['anon', 'authenticated', 'service_role']) AS role_name
ORDER BY role_name;

SELECT
    policyname,
    roles,
    cmd,
    qual,
    with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename = 'platform_admin_audit_events'
ORDER BY policyname;
```

Confirm `service_role` has SELECT/INSERT but not UPDATE/DELETE, clients have no
effective access, and no UPDATE or DELETE policy exists. Verification requires
only SELECTs; never update or delete an audit event. Remember that owners and
superusers remain stronger than ordinary grants and that `service_role`
bypasses RLS, so application authorization and operational ownership controls
remain mandatory.

Authorization failures without an active mapping do not create database audit
events because there is no valid audit actor FK. Retain sanitized application
security logs for those denials instead.

## Evidence to retain

Store the following in the approved restricted evidence system:

- staging Supabase project identifier/ref and backend base-environment name;
- backend Git commit hash and this runbook's Git commit hash;
- SHA-256 hashes of migrations 023, 024, and 025;
- protected internal company ID/name and approved internal user ID/email;
- the pre-bootstrap tenant role and matching post-bootstrap tenant role;
- change ticket, approver, operator, second verifier, operational owner, backup
  owner, and revocation owner;
- UTC change window and test windows;
- candidate SELECT output and bootstrap `RETURNING` output;
- post-bootstrap verification output;
- endpoint/status/error-code log only, with response bodies redacted;
- audit detail, expected-count, metadata-redaction, and privilege outputs;
- inactive-user denial evidence, if separately approved;
- immediate-revocation SQL output and next-request denial result;
- every deviation, exception, retry, and approval decision.

Do not retain JWTs, authorization headers, cookies, password hashes, service
keys, raw customer data, unredacted tenant responses, prompts, or messages.

Suggested local evidence commands:

```powershell
git rev-parse HEAD
Get-FileHash data\023_create_platform_admin_users.sql -Algorithm SHA256
Get-FileHash data\024_create_platform_admin_audit_events.sql -Algorithm SHA256
Get-FileHash data\025_enable_platform_admin_rls.sql -Algorithm SHA256
```

## Approval disposition

The one-time staging bootstrap and verification were approved and completed.
The detailed approver, operator, second-verifier, hashes, and redacted outputs
remain in the restricted evidence system rather than this repository. Any
reactivation or additional staging mapping requires a new approved change.

The completed staging exercise used:

- protected internal company 29;
- approved internal user 32;
- platform-admin mapping 1, now inactive.

Production remains blocked by all Phase 1.5 gates: production executor and
ownership approval, protected-company lifecycle controls, production bootstrap
approval, audit metadata/redaction rules, retention/archival policy, and the
append-only enforcement decision beyond grants. Phase 2.5 staging evidence does
not approve production deployment.

## Documentation disposition

This file is the Phase 2.5 operator runbook and redacted completed-verification
record. It is linked from:

- `docs/PLATFORM_ADMIN_PHASE_1_5_SECURITY_AND_STAGING.md`;
- `docs/PLATFORM_ADMIN_PHASE_2_DESIGN.md`;
- `docs/FEATURE_STATUS.md` and `docs/DEVELOPMENT_ROADMAP.md` only if the feature
  status materially changes.

Do not store live SQL output or sensitive API bodies in the Git repository.
