# Platform Admin Emergency Revocation

## Purpose and authority

This runbook contains production containment templates for an already approved
platform-admin deployment. It does not authorize their execution now. The
staging mapping remains inactive, production has no platform-admin deployment,
and no SQL is run by this documentation task.

Revocation changes `platform_admin_users.is_active` to false and explicitly
updates `updated_at`. Never delete a mapping and never modify `users.role` to
grant or revoke platform access.

The named production revocation owner or incident commander may invoke this
runbook for suspected credential compromise, unauthorized access, audit
failure, privilege/policy drift, internal-company risk, offboarding, or an
uncontrolled platform endpoint. Emergency execution requires two people when
available; urgent containment must not wait for the second person if the
approved incident policy permits single-operator emergency action. Retrospective
approval and evidence are then mandatory.

## Before execution

1. Declare an incident/change and record UTC time, reason, incident commander,
   operator, verifier, target production project reference, and communication
   channel.
2. Independently verify the Supabase organization/project reference and
   database name. Do not use a project selected only from browser history.
3. Choose **targeted revocation** unless the actor is unknown, exposure may
   affect multiple mappings, or database privileges/policies cannot be trusted.
4. Preserve available request IDs, sanitized authorization/error logs, audit
   IDs/time range, release hashes, and database logs. Never copy tokens,
   authorization headers, raw response bodies, prompts, messages, or secrets.
5. Confirm an approved SQL executor is available. Do not paste credentials into
   the incident record or terminal history.

## Targeted revocation

Replace all placeholders and have the verifier compare them with the incident
record. The predicates deliberately require both mapping and user IDs.

```sql
BEGIN;

UPDATE public.platform_admin_users
SET
    is_active = FALSE,
    updated_at = NOW()
WHERE id = <PLATFORM_ADMIN_USER_ID>
  AND user_id = <APPLICATION_USER_ID>
  AND is_active = TRUE
RETURNING
    id AS platform_admin_user_id,
    user_id,
    is_active,
    updated_at;

COMMIT;
```

Require exactly one returned row with `is_active = false`. Zero rows is not
success: verify whether the mapping was already inactive, identifiers are
wrong, or the environment is wrong. More than one row is impossible with the
primary key and indicates the executed SQL differed from this template.

## Global platform-access revocation

Use only when the affected actor cannot be bounded, unexpected access exposure
exists, or the platform authorization/audit boundary is untrustworthy.

```sql
BEGIN;

UPDATE public.platform_admin_users
SET
    is_active = FALSE,
    updated_at = NOW()
WHERE is_active = TRUE
RETURNING
    id AS platform_admin_user_id,
    user_id,
    is_active,
    updated_at;

COMMIT;
```

Record the expected active-mapping count before execution when time permits and
compare it with returned rows. Global revocation does not delete mappings or
audit history. Reactivation is never part of this incident runbook.

## Verification

### Database verification

```sql
SELECT
    platform_admin.id AS platform_admin_user_id,
    platform_admin.user_id,
    platform_admin.is_active,
    platform_admin.updated_at,
    user_row.status AS application_user_status,
    user_row.company_id
FROM public.platform_admin_users AS platform_admin
JOIN public.users AS user_row
  ON user_row.id = platform_admin.user_id
WHERE platform_admin.id = <PLATFORM_ADMIN_USER_ID>
  AND platform_admin.user_id = <APPLICATION_USER_ID>;
```

For global revocation, also require this count to be zero:

```sql
SELECT COUNT(*) AS active_platform_admin_mappings
FROM public.platform_admin_users
WHERE is_active = TRUE;
```

### Application verification

- Make the next request with the affected user's existing normal application
  session. It must return HTTP 403 with code
  `platform_admin_access_denied`.
- Refresh each open platform page. It must show **Access Denied** and no prior
  identity, company, subscription, or AI-credit data.
- Verify an ordinary tenant endpoint still follows normal tenant authorization;
  mapping revocation must not modify tenant role behavior.
- If the application user itself is compromised or offboarded, use the existing
  approved account-disable and session-containment process in addition to the
  mapping revocation. Phase 2 authentication reloads user status on requests,
  but session/token handling must follow the main incident runbook.

## When database revocation is unavailable

If Supabase or the approved SQL path is unavailable:

1. Roll back or disable routing to the platform-enabled backend artifact using
   the approved deployment-platform procedure.
2. Deny `/api/platform-admin/*` at the approved gateway/load-balancer layer if
   that controlled capability exists.
3. Roll back the static platform frontend artifact to reduce discovery, while
   recognizing that frontend hiding is not authorization.
4. Preserve fail-closed 503/403 evidence and continue attempts to revoke the
   mapping through the database owner.
5. Do not weaken authorization, bypass auditing, or use tenant roles as a
   temporary control.

The backend route rollback/gateway deny is containment, not proof of database
revocation. Complete and verify SQL revocation as soon as the database is
available.

## Scenario-specific containment

### Audit insertion failure

- Alert on the first `platform_admin_audit_unavailable`.
- Confirm the API withheld tenant data and did not return a successful response.
- Revoke active mapping(s) if the failure persists beyond a single transient
  request or integrity is uncertain.
- Inspect sequence privileges, INSERT grant, table availability, constraints,
  archive/maintenance activity, and service health without logging payloads.
- Do not disable audit-before-response or retry automatically.

### Unexpected access exposure

- Perform global revocation.
- Roll back/deny the platform backend routes and preserve request/database logs.
- Verify tenant admin/owner accounts without mappings are denied.
- Compare deployed commits, environment variables without values, route table,
  mapping rows, user statuses, privileges, policies, and role memberships with
  approved evidence.

### `service_role` privilege drift

- Perform global revocation before privilege repair.
- Capture direct ACLs, inherited memberships, default ACLs, owner, BYPASSRLS,
  sequence privileges, and grantors.
- Do not run ad hoc REVOKE/GRANT statements. Apply the reviewed privilege repair
  or approved migration in a separate database change and rerun the complete
  inspection matrix.

### RLS policy mismatch

- Perform global revocation.
- Record `relrowsecurity`, `relforcerowsecurity`, all target policies, role
  attributes, and effective privileges.
- Treat unexpected client policies, DELETE policies, or audit UPDATE policies
  as security exposure. Repair only through an approved migration/reapplication
  plan and staging evidence.

### Protected internal company deletion attempt

- Stop the tenant deletion/offboarding workflow immediately.
- Revoke active platform mappings for affected users.
- Preserve FK errors and workflow/audit records.
- Confirm the mapping rows remain present and the company has not been changed
  to a customer lifecycle state.
- Escalate to the internal-company operational owner, backup, database owner,
  and security owner.

## Recovery and reactivation

Do not reactivate during incident containment. Recovery requires:

- documented root cause and impact;
- confirmed audit integrity and preserved evidence;
- restored expected grants, ownership, RLS policies, append-only control, and
  application release hashes;
- active approved application user and protected internal company;
- security owner, operational owner, change approver, operator, and second
  verifier approval;
- a new time-bounded change window and exact reactivation SQL review;
- immediate endpoint/audit/denial tests and a pre-approved final active/inactive
  state.

If a replacement user is required, use the production bootstrap approval path;
do not reuse a customer user, change `users.role`, delete the old mapping, or
overwrite audit attribution.

## Evidence and closure

Retain:

- incident/change ID, reason, severity, UTC timeline, operator, verifier,
  commander, and approvers;
- production project reference and release/migration hashes;
- targeted/global revocation output with nonessential identity fields redacted;
- database and next-request verification results;
- sanitized logs, relevant audit event IDs/ranges, and preservation manifests;
- privilege/policy/trigger drift results;
- account/session containment actions;
- root cause, scope, remediation, reactivation decision, and follow-up owners.

Never retain live tokens, authorization headers, credentials, prompts,
messages, provider payloads, raw search text, or unredacted platform response
bodies in the incident record.
