# Platform-admin Tenant Support Intake Review/Conversion Contract

## Status and scope

Runtime code and Migration 031 are implemented and verified only in the main
shared testing Supabase with fake/team data. Browser/API E2E passed locally
after SQL application. This is not staging verification or production
readiness; production remains blocked.

Tenant support submission and the read-only platform-admin intake viewer exist.
Review, close, and conversion routes and frontend controls are implemented
locally and verified against the shared testing database.

## Main shared-testing verification evidence

Migration 031 was applied only to the main shared testing Supabase with
fake/team data. Request 1 was marked reviewed and then converted. Its status
became `converted`, with `converted_platform_support_case_id = 2`.

Internal platform support case 2 was created once. Tenant request events show
`created` with tenant actor, followed by `reviewed` and `converted` with
platform-admin actors. Platform-admin audit rows exist for review and
conversion. Audit metadata uses `http_method` and safe status/case-ID fields
only; it contains no title, description, full body, token, cookie, payment
field, provider payload, or customer content.

The tenant request count was 1 before the operation; the platform case count
became 2 only after conversion; and the platform-admin mapping count remained
1. Tenant-support RLS remained service-role-only. Function EXECUTE privileges
remained `anon = false`, `authenticated = false`, and `service_role = true`.
Both RPCs are `SECURITY INVOKER` with `search_path = pg_catalog`.

## Schema decision

Migration 031 adds a nullable
`tenant_support_requests.converted_platform_support_case_id` foreign key to
`platform_support_cases(id)` with `ON DELETE RESTRICT`. A uniqueness or
equivalent duplicate-conversion guard is required. Events alone are
insufficient for reliable lookup, idempotency, and reconciliation.

## Transaction and RPC contract

Python multi-write sequences are not sufficient. Review/close and conversion
must be atomic future PostgreSQL RPC operations in an approved migration:

- `convert_tenant_support_request(...)`;
- `set_tenant_support_request_status(...)`.

Each operation must lock the request row, validate its current status, and
leave no partial case, event, status, link, or audit changes after failure.
Already-converted requests must be rejected safely or handled idempotently,
according to an approved decision.

## Review and close workflow

The future endpoint is:

```text
PATCH /api/platform-admin/tenant-support-requests/<request_id>
```

The only accepted bodies are:

```json
{ "status": "reviewed" }
```

or:

```json
{ "status": "closed" }
```

The browser must not provide actor, company, requester, assignment, title,
description, audit metadata, or billing fields. The server derives actor and
request identity from the active platform-admin context and stored request.

## Conversion workflow

The future endpoint is:

```text
POST /api/platform-admin/tenant-support-requests/<request_id>/convert
```

Phase 1 conversion accepts an empty body. The server derives company ID,
requester ID, title, redacted description, and the active platform-admin actor
from trusted stored/authenticated context. It then atomically:

1. creates an internal `platform_support_cases` row;
2. creates its initial `platform_support_case_events` row;
3. marks the tenant request `converted`;
4. sets `converted_platform_support_case_id`;
5. appends a `converted` tenant request event with `actor_type = platform_admin`;
6. records platform-admin audit evidence.

No retry may create a duplicate internal case. Optional priority customization
is deferred unless separately approved.

## Actor rules

- The actor must be an active `platform_admin_users` mapping.
- No fake, shared, or fabricated platform-admin actor is permitted.
- The original tenant submission remains attributed to `requester_user_id`.
- Tenant request platform-admin events use `actor_platform_admin_user_id`.
- `tenant_support_audit_events` remains tenant-source only unless separately
  redesigned; platform-admin writes use `platform_admin_audit_events`.

## Audit contract

Implemented actions are:

- `platform_admin.tenant_support_request.review`;
- `platform_admin.tenant_support_request.close`;
- `platform_admin.tenant_support_request.convert`.

Use resource type `tenant_support_requests`. Safe metadata is limited to:

- `endpoint`;
- `http_method`;
- `outcome`;
- `old_status`;
- `new_status`;
- `converted_platform_support_case_id` for conversion only.

Audit evidence must exist before a successful response. Never record titles,
descriptions, raw tenant audit payloads, customer content, secrets, tokens,
cookies, payment fields, provider payloads, or full request bodies.

The runtime audit allowlist includes the three actions above.

## Frontend controls

Controls are available only in the tenant-intake detail panel:

- Mark reviewed;
- Close request;
- Convert to internal case;
- link to the converted internal case.

Write actions require confirmation and must clear stale state after failure or
Access Denied.

## Explicit exclusions

This phase excludes customer messaging, tenant replies, email, attachments,
billing actions, impersonation, exports/charts, direct tenant-user mutation,
assignment, notes added to `tenant_support_requests`, non-atomic conversion,
and production use.

## Approval decisions before staging or production use

Approve the exact status transitions; idempotent retry versus already-converted
rejection; conversion priority behavior; whether all active platform admins may
convert; audit/retention evidence rules; rollback and incident handling; and a
staging verification plan.

## Verification tests

Focused tests cover schema FK and uniqueness protection, RPC source contracts,
row locking and atomicity, status transitions, conversion case/event/request-
link/audit creation, already-converted behavior, route authorization, body
rejection, audit metadata exclusions, frontend controls, and stale-state
clearing.

No staging or production use is authorized by this contract; production remains
blocked.
