# Platform-admin Tenant Support Intake Viewer Contract

## Status and scope

Viewer Phase 1 is implemented locally as two read-only GET routes and a
separate Support Workspace section. It requires no SQL because Migration 030
already stores tenant support requests, request events, and tenant audit events.

Migration 030 and the tenant submission flow were verified only in the main
shared testing Supabase with fake/team data. This is not staging verification
or production readiness.

## Implemented endpoints

```text
GET /api/platform-admin/tenant-support-requests
GET /api/platform-admin/tenant-support-requests/<request_id>
```

These remain separate from:

```text
/api/platform-admin/support-cases
```

## Separation from internal support cases

Tenant requests and internal platform-admin cases have different actor models.
Tenant requests use `requester_user_id` and tenant actor events. Internal cases
use active `platform_admin_users` mappings and internal notes/events.

Phase 1 does not automatically convert a tenant request into a
`platform_support_case`.

## Authorization contract

Use the existing `platform_admin_required` guard and active database-backed
platform-admin authorization. Tenant users cannot access these endpoints.
Tenant `owner`, `admin`, and `member` roles never grant platform-admin access.
Browser state, localStorage, cached users, and JWT role claims cannot bypass
the refreshed database mapping check.

## Read-only boundary

The viewer is list/detail only and adds no `POST`, `PATCH`, `PUT`, or `DELETE`
route. It provides no status update, assignment, conversion, notes, customer
reply, email, attachment, billing action, impersonation, export, or chart.

## Safe list projection

The list may return only:

- `request_id`;
- `company_id`;
- `requester_user_id`;
- `category`;
- `status`;
- `priority`;
- `source`;
- `created_at`, `updated_at`, and `closed_at`.

The list must not return titles, redacted descriptions, raw audit metadata,
payment data, secrets, or provider payloads.

## Safe detail projection

Detail may return all safe list fields plus `title` and
`redacted_description`. An optional event summary may include only
`event_type`, `actor_type`, and `created_at`.

Title and description must be rendered as text only. They must never be placed
in platform-admin audit metadata. Raw tenant audit payloads remain excluded.

## Filters and pagination

The list may support `company_id`, `category`, `status`, `limit`, and `offset`.
All filters require server-side validation. IDs must be positive integers and
the page size must have an approved maximum, such as 100.

## Audit contract

Use these allowlisted actions:

- `platform_admin.tenant_support_request.list`;
- `platform_admin.tenant_support_request.read`.

Both use resource type `tenant_support_requests`. Safe list metadata may
include only endpoint, method, outcome, limit, offset, returned count,
`company_filter_applied`, `category_filter_applied`, and
`status_filter_applied`.

Detail audit metadata must not include title, description, full request bodies,
or tenant audit payloads. Audit insertion is required before returning a
successful protected response.

## Frontend placement

The implemented viewer has a separate section inside
`platform-admin-support.html` labeled **Tenant-submitted support requests**.
A validated `company_id` links to the existing company investigation page. A
safe detail panel displays approved fields as text only. No mutation controls
are permitted.

## Approval decisions before staging or production use

Approve the following before staging or production use:

- whether redacted descriptions may be shown to all active platform admins;
- whether displaying `requester_user_id` is acceptable;
- whether event summaries are needed in Phase 1;
- whether all active platform admins may view all tenant requests;
- retention and privacy treatment for submitted text and evidence.

## Implementation verification tests

Focused backend and frontend tests cover authentication, GET-only behavior,
filter/pagination, safe projections, audit metadata, raw tenant-audit
exclusion, no-mutation routes, stale-detail clearing, safe text rendering,
validated company links, and absent mutation controls.

## Explicit exclusions

- no tenant inbox or history;
- no customer messaging or platform-admin reply;
- no email;
- no attachments;
- no automatic conversion;
- no billing action;
- no impersonation;
- no export or chart;
- no mutation of `tenant_support_requests` in Phase 1.

No staging or production claim is made; production remains blocked.
