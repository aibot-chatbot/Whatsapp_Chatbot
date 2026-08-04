# Platform Admin Access Lifecycle and Review Procedure

## 1. Purpose and scope

This procedure defines how separately authorized platform-admin access should be
requested, approved, reviewed, revoked, and replaced. It applies to localhost,
any future approved staging environment, and any future production request.

The current platform-admin surface is read-only. This document is policy and
procedure only; it does not create access, run SQL, manage mappings, add routes,
or authorize deployment. The latest 12-route stack remains localhost-tested
only unless separately staged, and production remains blocked.

## 2. Platform-admin access principles

- `users.role` never grants platform access. Tenant `owner`, `admin`, and
  `member` roles are informational for this purpose.
- An active `platform_admin_users` mapping and an active application user are
  required for every protected request.
- Platform access is separate from tenant administration and must not be
  inferred from JWT claims, cached roles, hidden navigation, or local flags.
- Shared accounts are prohibited. Each operator requires an individually
  attributable internal identity.
- Grant the minimum read-only access needed for the stated investigation.
- Prefer temporary access for verification, with an explicit expiry or
  revocation time.
- Keep platform-admin identities in an approved internal company; do not use a
  customer tenant as a substitute.

## 3. Access request process

Every request should record, before access is enabled:

1. Requester identity and accountable operational owner.
2. Business reason and investigation scope.
3. Approved internal company and internal application user.
4. Requested duration, expiry, and whether access is temporary.
5. Read-only resources required; the default scope is the existing platform
   investigation surface only.
6. Named approver and emergency-revocation owner.
7. A second verifier for any future production request.
8. Change ticket, evidence location, and planned verification steps.

Approval must confirm that the user and company are active, internal, approved,
and not subject to customer offboarding or automated tenant deletion. No tenant
role change is part of this process.

## 4. Bootstrap process boundary

Bootstrap is currently limited to localhost procedure rehearsal and any future
separately approved staging exercise. The latest 12-route stack has not been
staging-verified. Production bootstrap is blocked.

No SQL should be run without a named approved executor, change window, second
verifier, backup/recovery evidence, and explicit approval. Do not create,
reactivate, repair, or delete a mapping as an ad hoc troubleshooting step.

## 5. Revocation process

For planned or temporary revocation:

1. Deactivate the mapping through the approved operational procedure.
2. Immediately request `/api/platform-admin/me` with the affected session.
3. Require Access Denied and the stable access-denied outcome.
4. Refresh any open platform page and verify company, subscription, credit,
   billing, support, and audit data are no longer visible.
5. Record only redacted status, timestamp, endpoint template, and outcome.
6. Preserve the mapping and audit records; do not delete them to revoke access.

The existing containment procedure is documented in
`docs/PLATFORM_ADMIN_EMERGENCY_REVOCATION.md`.

## 6. Replacement process

Replacement is required when an operator leaves, changes responsibilities, or
no longer needs platform access.

- Reconfirm the business reason and internal-company assignment.
- Deactivate the outgoing mapping before enabling the replacement whenever
  continuity permits.
- Obtain separate approval for the replacement identity and duration.
- Verify the replacement identity is individually attributable and not shared.
- Run the same denial/allowance and stale-data checks required for the change.
- Record the old mapping's revocation and the replacement approval together,
  without recording tokens or customer data.

## 7. Periodic access review

- Localhost or future staging: review active and inactive mappings monthly while
  verification work is ongoing.
- Future production: perform a formal review at least quarterly and after any
  ownership change, incident, reorganization, or operator offboarding.

The review owner should compare approved requests with current mappings, user
and company status, scope, expiry, operational owner, and revocation owner.
Evidence should include reviewer, UTC date, decision, exceptions, and follow-up
ticket. Unneeded access must be revoked and rechecked immediately.

## 8. Emergency revocation

Use the targeted or global containment steps in
`docs/PLATFORM_ADMIN_EMERGENCY_REVOCATION.md` when an actor, environment, or
exposure is uncertain. Prefer targeted revocation when the affected identity is
known; use global revocation when the scope cannot be bounded. Gateway or route
denial is containment only and does not replace database-state verification in
an approved deployed environment.

## 9. Audit and evidence requirements

Retain only redacted evidence sufficient to prove authorization, denial,
revocation, and review outcomes:

- Never record JWTs, bearer tokens, cookies, passwords, service keys, or secrets.
- Never record full response bodies, prompts, messages, provider payloads, or
  raw exceptions.
- Do not record sensitive customer data or unnecessary personal data.
- Record endpoint templates, HTTP status, stable error code, UTC timestamp,
  mapping reference where approved, and a safe structural result.
- Store evidence only in the approved restricted evidence location.

## 10. Explicit non-goals

This procedure does not introduce:

- a platform-admin management UI;
- write controls or mapping-management routes;
- production bootstrap or deployment;
- impersonation;
- support tickets, cases, notes, or assignment workflow;
- exports, reconciliation, payment retry, manual credit, or plan changes.

## 11. Checklist templates

### Access request checklist

- [ ] Requester and operational owner identified.
- [ ] Business reason and read-only scope recorded.
- [ ] Internal company and internal user approved.
- [ ] Duration, expiry, approver, and revocation owner recorded.
- [ ] Second verifier named for any future production request.
- [ ] Change ticket and restricted evidence location recorded.
- [ ] No tenant-role change requested.

### Access revocation checklist

- [ ] Correct mapping and environment confirmed.
- [ ] Mapping deactivated through the approved procedure.
- [ ] `/api/platform-admin/me` returns Access Denied.
- [ ] Open pages clear stale platform data after refresh.
- [ ] Redacted timestamp, endpoint, status, and outcome retained.
- [ ] No mapping or audit row deleted.

### Periodic review checklist

- [ ] Active and inactive mappings compared with approved requests.
- [ ] User and internal-company status confirmed.
- [ ] Scope, expiry, owner, and revocation owner reviewed.
- [ ] Unneeded or expired access revoked and rechecked.
- [ ] Exceptions assigned to a ticket with an owner and due date.
- [ ] Reviewer, UTC date, decision, and restricted evidence location recorded.

### Audit and verification evidence checklist

- [ ] **Access approval:** requester, business reason, approved internal
      company/user, read-only scope, duration, approver, and ticket recorded.
- [ ] **Revocation:** environment, mapping reference where approved, UTC time,
      `/api/platform-admin/me` denial, and stale-data clearing outcome recorded.
- [ ] **Smoke check:** base environment label, UTC time, checked route count,
      pass/fail summary, optional-child-check status, and script version recorded.
- [ ] **Audit log:** expected action/resource pairs, event count, safe metadata
      checks, and any audit-unavailable outcome recorded without raw events.
- [ ] **Forbidden content check:** no tokens, cookies, authorization headers,
      secrets, full response bodies, raw payloads, or sensitive customer data.
- [ ] **Localhost boundary:** local results prove only local behavior and do
      not establish staging or production verification.
- [ ] **Staging boundary:** future staging evidence requires a confirmed host,
      approved Supabase environment, approved operator/token, and redacted
      environment-specific results; the current 12-route stack is not recorded
      as staging-verified.
- [ ] **Production boundary:** production evidence requires named approvals,
      backup/restore, monitoring, retention, deployment, and go/no-go records;
      production remains blocked until those gates are closed.

The detailed audit metadata, redaction, retention, and archival policy is in
`docs/PLATFORM_ADMIN_AUDIT_POLICY.md`.
