# Platform-admin User Management Phase 4 Contract

Status: Migration 034 is applied and structurally verified only in the approved
main shared-testing Supabase with fake/team data. The protected-company registry
contains company 29 only for that main shared-testing environment. Migration
035 is applied and verified only in the approved main shared-testing Supabase
with fake/team data. It corrected only the Phase 4 RPC audit endpoint metadata,
did not create mappings, did not create Phase 4 mutation audit events merely by
application, preserved RPC ownership/security/EXECUTE posture, and did not
alter existing audit rows. The bounded runtime user-management implementation
is local application code and test coverage; staging verification and
production readiness are not claimed.

This contract records the approved and implemented boundary for platform-admin
user management and the remaining verification/deployment limits. It is based
on the repository migrations, routes, repositories, tests, and documentation
currently present for `platform_admin_users`, `users`, and
`platform_admin_audit_events`.

## Existing Repository Evidence

- `platform_admin_users` exists from Migration 023 as a separate SaaS-operator
  allowlist. Its columns are `id`, `user_id`, `is_active`, `created_at`,
  `updated_at`, and nullable `created_by_user_id`.
- `platform_admin_users.user_id` is unique and references `users(id)` with
  `ON UPDATE RESTRICT ON DELETE RESTRICT`.
- `platform_admin_users.created_by_user_id` references `users(id)` with
  `ON UPDATE RESTRICT ON DELETE SET NULL`.
- `platform_admin_users.updated_at` is application-managed. Migration 023
  explicitly states that no timestamp trigger is installed.
- Migrations 023 and 025 grant `service_role` direct `SELECT`, `INSERT`, and
  `UPDATE` on `platform_admin_users`; `anon` and `authenticated` receive no
  table or sequence privileges.
- Migration 025 enables RLS on `platform_admin_users` and creates only
  service-role policies for `SELECT`, `INSERT`, and `UPDATE`. There are no
  `anon` or `authenticated` policies and no `DELETE` policy.
- `platform_admin_audit_events` exists from Migration 024 and is append-only
  through Migration 026's mutation-rejection trigger.
- The current platform-admin blueprint uses the existing platform-admin guard
  for every `/api/platform-admin/*` route.
- The guard validates an active `platform_admin_users` mapping for the
  authenticated `users.id`. It does not authorize platform access from
  `users.role`.
- At the initial Phase 4 inspection, no platform-admin user-management route,
  page, RPC, or dedicated invitation workflow existed. Phase 4 now implements
  the bounded directory/detail routes, add-existing-user RPC workflow,
  activation/deactivation RPC workflow, and dedicated frontend page. A
  dedicated platform-admin invitation workflow remains deferred.
- Existing tenant invitation code is company-scoped and grants tenant roles
  `admin` or `member`; it is not a platform-admin invitation model.
- The repository exposes `users.created_at`, `users.updated_at`, `status`,
  `email`, and `full_name`, but no reliable `last_login` or `last_seen` field
  was found in the inspected code and migrations.
- Existing bootstrap and production-readiness documentation requires a
  protected internal company. At the initial Phase 4 inspection, the
  implemented database schema did not contain an authoritative
  protected/internal/platform/system company designation. Migration 034
  subsequently introduced the dedicated `platform_admin_protected_companies`
  registry. Historical staging evidence naming `company_id = 29` is not a
  reusable database rule.

## Main Shared-testing Inspection Evidence

The read-only Phase 4 inspection was run in the approved main shared-testing
Supabase with fake/team data. This is not staging verification and does not
establish production readiness.

Verified existing database boundary:

- `platform_admin_users` has exactly the expected existing columns.
- `platform_admin_users` and `platform_admin_audit_events` are owned by
  `postgres`.
- RLS is enabled and not forced.
- Only service-role policies exist.
- Direct table and sequence privileges remain service-role-only as designed.
- `platform_admin_audit_events` has the existing UPDATE/DELETE rejection
  trigger.
- `require_active_platform_admin_mapping(bigint)` is owned by `postgres`, is
  `SECURITY INVOKER`, uses `search_path=pg_catalog`, is not executable by
  `anon` or `authenticated`, and is executable by `service_role`.
- No existing platform-admin create, activate, deactivate, invite, or bootstrap
  management RPC exists.
- Active platform-admin mappings: 1.
- Inactive platform-admin mappings: 0.
- Total platform-admin mappings: 1.
- Null creator mappings: 1.
- Missing creator rows: 0.
- Linked creator rows: 0.
- `created_by_user_id` correctly references `users(id)`.
- The existing mapping belongs to `company_id = 29`.
- Mapping/user/company integrity counts are all zero:
  `missing_user_count = 0`, `null_company_count = 0`, and
  `missing_company_count = 0`.
- `users.company_id` references `companies(id)`.

Protected internal-company inspection and resolution:

- `companies` exposes no authoritative protected/internal/platform/system
  designation in the inspected schema.
- The only matching company fields were `id` and `business_type`.
- No company constraint establishes an internal or protected company.
- The inspected `users` constraints do not establish an authoritative protected
  internal-company rule.
- `company_id = 29` was not treated as protected merely because the current
  bootstrap platform admin belongs to it. It was later explicitly approved and
  registered as the protected internal company for main shared-testing only.
- Migration 034 introduced the authoritative registry used for this
  environment-specific designation.
- Because there is currently exactly one active platform admin in shared
  testing, a future deactivation of that mapping must be rejected by
  final-active-admin protection.
- Company 29 currently has only one active user, user 32, and that user already
  has the existing platform-admin mapping. The successful shared-testing
  create-mapping E2E remains pending until a second approved active fake/team
  user exists in company 29.

## Authorization Model

Platform access is granted only by an active row in
`public.platform_admin_users`. The tenant-scoped `users.role` value never grants
platform-admin access, even when the role is `owner` or `admin`.

All future Phase 4 routes must use the existing platform-admin blueprint guard.
The application must resolve the actor from refreshed authentication and the
active mapping stored in `g.platform_admin_user`; browser-supplied actor IDs,
company IDs, role values, mapping IDs, or privilege claims are never trusted.

Service-role credentials remain a backend-only capability. The frontend must
not receive service-role keys, table mutation privileges, or generic user
mutation endpoints.

## Read Model

The platform-admin directory and detail surface may return only safe fields that
exist today or are explicitly derived from existing authoritative records.

Allowed mapping fields:

- `platform_admin_user_id`: `platform_admin_users.id`.
- `user_id`: `platform_admin_users.user_id`.
- `is_active`: `platform_admin_users.is_active`.
- `created_at`: `platform_admin_users.created_at`.
- `updated_at`: `platform_admin_users.updated_at`.
- `created_by_user_id`: nullable `platform_admin_users.created_by_user_id`.

Allowed safe user identity projection, if joined server-side:

- `user_email`: `users.email`.
- `user_full_name`: `users.full_name`.
- `user_status`: `users.status`.

Allowed safe creator projection, if joined server-side:

- `creator_user_id`: the nullable `created_by_user_id`.
- `creator_email`: `users.email` for the creator user when the row still
  exists.
- `creator_full_name`: `users.full_name` for the creator user when the row
  still exists.

The first bootstrap mapping may have no creator. A missing creator row after
`ON DELETE SET NULL` must be displayed as `Bootstrap/unknown` or equivalent
non-sensitive text, not as an error and not as a guessed actor.

Do not expose password hashes, tokens, raw JWT claims, tenant role authority,
invitation tokens, raw audit metadata, arbitrary user profile fields, payment
data, or company administration controls in this read model.

## Last-login and Activity Semantics

No reliable `last_login` or `last_seen` field was found in the repository
evidence inspected for this contract. `users.updated_at` must not be presented
as login evidence.

Until an authoritative login/activity source exists, Phase 4 should display
only a clearly named recent platform-admin activity value derived from
`platform_admin_audit_events`:

- `recent_platform_admin_activity_at`: the maximum
  `platform_admin_audit_events.created_at` for the mapping.
- Optional safe activity summary: audit action names and counts only, without
  raw metadata bodies.

This means audited platform-admin application activity. It does not mean login,
browser presence, last seen, or tenant activity.

## Create, Bootstrap, and Invite Decision

The safest supported initial Phase 4 create path is adding an existing active
internal application user to `platform_admin_users` through a trusted backend
RPC. This preserves the existing account lifecycle and avoids reusing
tenant-team invitation semantics for platform access.

The contract distinguishes three paths:

- Add existing user: implemented through the bounded RPC/runtime workflow. The
  user must already exist in `users`, must be active under the existing
  authentication model, must belong to the approved protected internal company
  used for platform-admin identities, and must not already have a
  platform-admin mapping. Ordinary tenant-company users cannot be added to
  `platform_admin_users`. The target user's `users.role` remains irrelevant to
  platform authorization. This contract does not invent a protected company ID.
- Create new user account: deferred. The existing account-creation flows are
  tenant/company-oriented and require a separate approved design before they can
  create platform-admin identities.
- Send invitation: deferred. The existing invitation tables and routes are
  tenant company-scoped and grant tenant roles only. They must not be reused for
  platform-admin access without a separate platform-admin invitation contract.

Initial protected-company bootstrap remains an operational procedure outside
the runtime management UI. Migration 034 provides the registry and RPCs, but it
does not expose registry mutation through application runtime.

## Protected Internal-company Design Decision

Repository inspection found historical operational requirements for a protected
internal company, including staging bootstrap and production-readiness
runbooks. The initial inspection did not find an implemented schema object,
migration, route, environment variable, trigger, policy, or RPC that
authoritatively designates a protected internal company. The alternatives below
were evaluated as design rationale; the dedicated registry approach was
selected and Migration 034 implemented it. Company 29 was registered only for
the approved main shared-testing Supabase with fake/team data, and no portable
company ID is hardcoded.

Candidate approaches:

| Approach | Database enforcement | Tenant promotion risk | Company deletion behavior | Bootstrap/recovery | Auditability | Portability | Hardcoded ID risk |
|---|---|---|---|---|---|---|---|
| A. Dedicated platform-admin protected-company registry | Strong: create RPC can require a matching active registry row and FK to `companies(id)` | Lowest: ordinary tenant companies are excluded unless explicitly registered | Strong: registry FK and mutation rules can block deletion or require explicit lifecycle handling | Clear: bootstrap can register the protected company, then create mappings through approved RPCs | Strong: registry changes can be audited as platform-admin access-control changes | Good: each environment can register its own protected company without sharing IDs | Low |
| B. Explicit protected/internal marker on `companies` | Moderate: create RPC can require the marker, but the marker lives on a broad tenant table | Higher: accidental or unauthorized marker edits could promote a tenant company | Moderate: deletion workflows must learn to respect the marker everywhere | Simple to query, but recovery depends on broad company-update controls | Moderate: only strong if all marker changes are audited and restricted | Good if marker is migrated consistently | Low |
| C. Environment/configuration-only company ID | Weak inside the database: RPC cannot enforce it unless trusted config is injected safely | Highest: stale or wrong configuration can elevate the wrong tenant | Weak: database deletion/offboarding cannot see the config by itself | Operationally simple but fragile during restore, staging, and incident recovery | Weak: config changes are outside database audit unless separately controlled | Poor: IDs differ by environment and drift easily | High |

Decision implemented: dedicated database-authoritative protected-company
registry. The registry is service-role-only, explicit per environment, and
referenced by the create-mapping RPC. Do not hardcode `company_id = 29`; it is
approved main shared-testing evidence only.

## Activation and Deactivation Workflow

Allowed state changes:

- `inactive -> active`
- `active -> inactive`

No-op activation or deactivation must be rejected with a stable sanitized
application error. Phase 4 should not treat no-ops as successful idempotent
writes because each approved access change must produce meaningful audit
evidence.

Platform-admin mappings are not deleted by normal application operations.
Deactivation preserves audit attribution and historical access records.

## Final Active Platform-admin Protection

Migration 034 implements mutation protections that prevent the system from
being left with zero active platform-admin mappings. A Python count-then-update
sequence is not sufficient.

Migration 034 implements:

- Mutation RPCs that run in one PostgreSQL transaction.
- Actor validation through an active `platform_admin_users` mapping.
- Actor mapping and target mapping row locking.
- Active-count decision serialization with a table-level lock:
  `LOCK TABLE public.platform_admin_users IN SHARE ROW EXCLUSIVE MODE`, or an
  equivalently strong transaction-scoped lock.
- Rejection when deactivation targets the final active mapping.
- Self-deactivation rejection.
- `platform_admin_audit_events` insertion in the same transaction as the
  mapping mutation.

The RPC must fail closed if audit insertion fails. A mapping state change
without its audit event must not be possible.

## Self-deactivation Decision

Self-deactivation is rejected by default. This fail-safe rule prevents an actor
from removing their own access during the same request and avoids ambiguous UI
recovery behavior.

Self-deactivation may be reconsidered only after an explicit approval and a
separate recovery design. The final-active-admin protection still applies even
if self-deactivation is later allowed.

## Creator Attribution

`platform_admin_users.created_by_user_id` currently points to `users.id`, not to
`platform_admin_users.id`. This is sufficient for safe creator attribution when
displayed as a nullable application user reference.

The create RPC sets `created_by_user_id` to the actor mapping's `user_id`, not
to a browser-supplied value. The UI may display safe creator email/full name
when the creator user row is still available. It must not infer platform
authority from the creator user's tenant role.

## Audit Actions

Approved/implemented bounded Phase 4 audit actions:

- `platform_admin.user.list`
- `platform_admin.user.read`
- `platform_admin.user.create`
- `platform_admin.user.activate`
- `platform_admin.user.deactivate`

The preferred resource type is `platform_admin_users`.

Safe metadata may include:

- endpoint
- http_method
- outcome
- target_platform_admin_user_id
- target_user_id
- old_is_active
- new_is_active

Resource ID semantics:

- `platform_admin.user.list`: `resource_id` is `NULL`.
- `platform_admin.user.read`: `resource_id` is the target mapping ID.
- `platform_admin.user.create`: `resource_id` is the newly created mapping ID.
- `platform_admin.user.activate`: `resource_id` is the target mapping ID.
- `platform_admin.user.deactivate`: `resource_id` is the target mapping ID.

`docs/PLATFORM_ADMIN_AUDIT_POLICY.md` extends the approved action and metadata
schema for these Phase 4 operations. Runtime mutations must not write duplicate
Python audit rows for create, activate, or deactivate because the Migration 034
RPCs write those rows atomically.

Audit metadata must exclude passwords, password hashes, tokens, cookies,
authorization headers, raw request bodies, tenant role authority, invitation
tokens, arbitrary user profile fields, secrets, and raw exception details.

## Database and RPC Design

Migration 034 is applied and structurally verified only in the approved main
shared-testing Supabase with fake/team data. It provides the approved
platform-admin mapping-management RPCs, final-active-admin protection, audit
schemas for user-management mutation actions, and a database-authoritative
protected-company registry.

Migration 035 is an applied and verified corrective migration that replaces
`create_platform_admin_user_mapping(bigint,bigint)` and
`set_platform_admin_user_active(bigint,bigint,boolean)` without changing their
business or security behavior. Its only intended behavior change is to write
the approved audit endpoint templates
`/api/platform-admin/platform-admin-users` and
`/api/platform-admin/platform-admin-users/<platform_admin_user_id>/active`
instead of the shortened endpoint metadata emitted by the already-applied
Migration 034 RPC bodies. Migration 035 does not alter existing audit rows, and
the old shortened audit endpoint strings are absent from the verified current
main shared-testing RPC definitions. Migration 035 is not staging verified or
production ready.

No new columns were required for the initial add-existing-user and
activate/deactivate workflow based on the current `platform_admin_users`
evidence. Migration 034 defines only the minimal additional database objects
needed for atomic writes and verification:

- A database-authoritative dedicated protected-company registry.
- Optional index on `platform_admin_users(is_active, updated_at DESC, id DESC)`
  if the directory needs active/inactive filtering at scale.
- Optional index on `platform_admin_users(created_by_user_id)` if creator lookup
  becomes a common query.
- `create_platform_admin_user_mapping(...)` RPC for adding an existing active
  protected-internal-company user to the allowlist.
- `set_platform_admin_user_active(...)` RPC for activation and deactivation.
- Any small helper functions required by the RPC call chain.

Every mutation RPC must:

- be atomic;
- validate the active actor mapping;
- lock relevant mapping rows for the transaction;
- enforce final-active-admin protection;
- reject no-op changes;
- reject self-deactivation unless separately approved;
- prevent arbitrary browser-supplied actor/company/role data;
- reject ordinary tenant-company users and block creation when the protected
  internal-company identifier cannot be resolved authoritatively;
- validate target user existence, active status, and protected-company
  membership;
- reject deactivation of the current shared-testing mapping while it is the
  only active mapping;
- write audit evidence atomically;
- use `SECURITY INVOKER`;
- use `SET search_path = pg_catalog`;
- be executable only by `service_role`.

## RLS and Privilege Model

The existing service-role-only backend access model remains the boundary.
`anon` and `authenticated` must not receive direct table, sequence, or RPC
execution privileges for platform-admin user management.

The application must continue to check platform-admin authorization before
calling privileged Supabase operations. `service_role` can bypass RLS in
Supabase, so RLS policies document the intended envelope but do not replace
server-side authorization.

## Frontend Boundary

Phase 4 adds a dedicated platform-admin user-management page. It is clearly
limited to platform-admin mappings.

Allowed controls:

- list platform-admin mappings;
- inspect active/inactive state;
- show safe creator information;
- show recent audited platform-admin activity if available;
- add an existing approved internal user to the mapping table after explicit
  confirmation;
- activate or deactivate mappings through bounded controls.

Excluded controls:

- tenant user role editing;
- generic user administration;
- password resets;
- impersonation;
- deleting tenant users;
- deleting platform-admin mappings;
- billing actions;
- company suspension;
- production or staging deployment actions.

## Testing Requirements

Phase 4 implementation tests must cover:

- platform-admin guard authorization;
- tenant roles never granting platform access;
- safe directory and detail projections;
- active/inactive filtering;
- invalid IDs and boolean IDs;
- no-op activation/deactivation rejection;
- final-active-admin protection;
- concurrent final-active-admin protection;
- self-deactivation rejection;
- inactive actor rejection;
- atomic audit writes;
- audit metadata redaction;
- RLS, table grants, sequence grants, function security mode, safe search path,
  and EXECUTE privileges;
- frontend safe rendering;
- no generic user-management controls;
- no tenant user role mutation, password reset, impersonation, billing, company
  suspension, or deletion controls.

## Verification Boundary

The temporary read-only inspection and bootstrap helper scripts used during the
Migration 034 design and shared-testing bootstrap review have been retired after
successful review. The retained manual RPC verification package is
`tmp/platform_admin_user_management_034_rpc_verification.sql`.

Running verification scripts in a named environment is a manual inspection step,
not a staging or production readiness claim. No staging or production readiness
is claimed by this contract.

## Main Shared-testing Verification And Pending RPC E2E

Migration 034 has been applied and structurally verified only in the approved
main shared-testing Supabase with fake/team data. The verified post-apply and
post-bootstrap baseline is:

- `protected_company_count = 1`
- `company_29_registry_count = 1`
- `active_platform_admin_count = 1`
- `inactive_platform_admin_count = 0`
- `total_platform_admin_count = 1`
- the existing mapping belongs to company 29
- active user in company 29 is `user_id = 32`
- user 32 is already the existing platform admin
- `create_mapping_rpc_exists = true`
- `set_active_rpc_exists = true`
- `mapping_integrity_issue_count = 0`
- Phase 4 mutation audit count after registry bootstrap is 0
- Migration 035 corrected the two Phase 4 RPC audit endpoint templates
- both corrected RPCs remain owned by `postgres`, `SECURITY INVOKER`, use
  `search_path=pg_catalog`, are not executable by `anon` or `authenticated`,
  and are executable by `service_role`
- old shortened audit endpoint strings are absent

Company 29 is explicitly designated only for the approved main shared-testing
Supabase with fake/team data. It is not a staging or production protected
company, and the application must not hardcode 29 as a portable protected
company ID.

Prepared SQL artifacts:

- `tmp/platform_admin_user_management_034_rpc_verification.sql`: retained
  manual RPC verification package for the later second-user shared-testing E2E.
  It records the current shared-testing facts, uses explicit placeholders for
  actor, existing mapped user, missing user, and second approved user IDs, wraps
  the checks in `BEGIN`/`ROLLBACK`, and must not be executed until a second
  approved active fake/team user exists in company 29.

Planned RPC tests after a second approved active fake/team user exists:

A. Creation rejection:

- Target user from a non-protected company must fail.
- Missing target user must fail.
- Inactive target user must fail.
- Duplicate mapping must fail.

B. Creation success:

- Use only an approved fake/team active user belonging to the protected company.
- Create exactly one new active mapping.
- Creator attribution must use the actor mapping's `user_id`.
- `platform_admin.user.create` audit event must be inserted exactly once.

C. Activation/deactivation:

- No-op activation/deactivation must fail.
- Self-deactivation must fail.
- Deactivating the final active admin must fail.
- Activation of an ineligible user must fail.
- Valid activation/deactivation must update `updated_at` and audit exactly
  once.

D. Atomicity:

- After every rejected RPC, verify there are no partial mapping rows.
- After every rejected RPC, verify there are no partial
  `platform_admin.user.create`, `platform_admin.user.activate`, or
  `platform_admin.user.deactivate` audit rows.

E. Security:

- `anon` cannot EXECUTE the Phase 4 RPCs.
- `authenticated` cannot EXECUTE the Phase 4 RPCs.
- `service_role` can EXECUTE the Phase 4 RPCs.
- `platform_admin_protected_companies` remains SELECT-only to `service_role`.
- `users.role` never controls platform-admin access.

Do not perform the full shared-testing RPC E2E package until a second approved
active fake/team user exists in company 29 and the operator has filled and
reviewed the required placeholders.

Current shared-testing limitation: company 29 currently contains only one active
user, user 32, and user 32 already has the sole platform-admin mapping. The
successful `create_platform_admin_user_mapping` shared-testing E2E remains
pending until a second approved active fake/team user exists in company 29. The
local repository, service, route, frontend, and source-contract tests cover the
success path with mocks/fixtures without fabricating shared-testing data.
