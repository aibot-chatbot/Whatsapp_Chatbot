# Platform-admin Support Workflow Contract

## Status and Scope

Support Cases Phase 1 is applied and verified only in the main shared-testing
Supabase with fake/team data. Platform-admin Support Case Operations Phase 2 is
implemented and verified only in the main shared-testing Supabase with
fake/team data. Migration 032 executed successfully there.
No staging or production readiness is claimed for Phase 2.
Platform-admin Tenant Communication Phase 3 and Migration 033 are applied and
verified only in the main shared-testing Supabase with fake/team data.
This is not staging verification and does not establish production readiness.
Production remains blocked.

Current prototype hardening is complete. Migration 043
(`data/043_atomic_platform_support_case_creation.sql`) is applied and runtime
verified in prototype/shared-testing only. It creates the support case, initial
support-case event, and platform-admin audit event atomically through
`public.create_platform_support_case(...)`. Migration 044 belongs to the
platform-admin user directory recent-activity batching work, not support-case
mutation semantics, and is also applied/runtime verified only in
prototype/shared-testing.

The workspace is internal to authorized platform administrators. It supports
case listing/detail, redacted case creation, assignment, status transitions,
priority updates, internal notes, tenant-visible replies for converted tenant
requests, pending in-app support notification outbox records, and a
server-provided activity timeline. It does not send external email, expose
internal notes to tenants, support attachments, billing actions, impersonation,
exports, analytics, SLA timers, escalation automation, bulk actions, or tenant
suspension controls.
Billing actions remain excluded.

## Lifecycle

Allowed statuses are:

- `open`
- `in_progress`
- `waiting_for_tenant`
- `resolved`
- `closed`

Allowed transitions are:

- `open` to `in_progress`, `waiting_for_tenant`, or `resolved`
- `in_progress` to `waiting_for_tenant` or `resolved`
- `waiting_for_tenant` to `in_progress` or `resolved`
- `resolved` to `closed` or `in_progress`
- `closed` to `in_progress`

No-op transitions are rejected. Reopening a `resolved` or `closed` case must
return it to `in_progress`.

## Priority Model

Allowed priorities are:

- `low`
- `normal`
- `high`
- `urgent`

`normal` remains the safe default. This phase makes no SLA or escalation claim.
No-op priority changes are rejected.

## Assignment Rules

Cases may be assigned, reassigned, or unassigned through
`assigned_platform_admin_user_id`. The value is a `platform_admin_users.id`
mapping, not a tenant `users.role` value. Assignment to tenant users, inactive
platform-admin mappings, arbitrary user IDs, or fabricated IDs must be rejected
by the trusted backend RPC.

Assignment changes record old and new mapping IDs in support-case activity and
safe platform-admin audit metadata. No tenant email, name, token, role, or raw
authorization detail is recorded.
Inactive platform-admin mappings are not valid assignees.

`GET /api/platform-admin/support-case-assignees` returns only active
assignable platform-admin mappings with the safe projection `id`, `user_id`,
`is_active`, `user_full_name`, and `user_email`. The identity fields are for
display only; assignment payloads continue to use `platform_admin_users.id`
mapping IDs. If a case is historically assigned to an inactive mapping, the
frontend keeps that current mapping visible with a safe `Platform Admin #<id>`
fallback and a disabled current option, but it is not added to the active
assignee directory and cannot be selected as a new assignment.

## Internal Notes

Internal notes are stored as append-only `platform_support_case_events` with
`event_type = 'note_added'` and `redacted_note`. Notes require non-empty
trimmed content and are limited to 2000 characters. They are visible only from
platform-admin routes and must never be serialized through tenant support
routes or templates.

Normal application operations do not edit or delete notes. Note bodies appear
in the internal case timeline, but full note content is not duplicated into
general audit metadata.

## Activity Timeline

`GET /api/platform-admin/support-cases/<case_id>` returns the authoritative
case, append-only case events ordered by `created_at ASC, id ASC`, available
next status transitions, and the original tenant request linkage when the
existing conversion mapping is present. Timeline events are paginated with
`event_limit` and `event_offset`; the default limit is 25 and the maximum
limit is 100. The response preserves the `events` field and adds
`events_pagination` with `limit`, `offset`, `returned`, `total`, and
`has_more`.

The browser renders the timeline from server facts only. Relevant events
include case creation, conversion-created case events, assignment changes,
priority changes, status changes, reopening, resolution, closure, and internal
note creation. Phase 3 adds `tenant_reply_created` case events linked to the
tenant-visible reply ID. Reply text is stored in `tenant_support_replies`, not
in internal-note fields or audit metadata.

## Tenant-visible Replies

Phase 3 introduces a dedicated tenant-visible reply model:

- `tenant_support_replies` stores append-only public support replies.
- Replies are anchored to both `tenant_support_requests.id` and
  `platform_support_cases.id`.
- The authoritative linkage is the existing
  `tenant_support_requests.converted_platform_support_case_id` mapping.
- Platform admins may create replies only for internal cases converted from a
  tenant support request. Manually created internal cases without that mapping
  cannot receive tenant-visible replies in Phase 3.
- Company ID, request ID, case ID, and platform-admin mapping ID are derived by
  the trusted backend/RPC, never accepted from the browser.
- Reply bodies are trimmed, redacted text with a 4000 character maximum.
- Tenant-facing routes return safe public reply fields only: reply ID, request
  ID, author type, redacted body, and created timestamp.

`GET /api/platform-admin/support-cases/<case_id>/replies` paginates
tenant-visible replies with `limit` and `offset`; the default limit is 25 and
the maximum limit is 100. The response preserves `replies` and adds
`pagination` with `limit`, `offset`, `returned`, `total`, and `has_more`.
Notification lookup is restricted to notification rows whose `reply_id` is in
the returned reply page; an empty reply page skips notification database
access.

Internal notes remain in `platform_support_case_events.redacted_note` and are
never serialized through tenant support routes or templates.

## Notification and Attachment Boundary

Phase 3 creates one pending `in_app` support notification/outbox row for each
tenant-visible reply inside the same RPC transaction. This is durable delivery
tracking, not proof of delivered email or browser notification. The outbox
tracks `pending`, `sent`, and `failed` states, retry count, safe failure code,
and timestamps without storing provider payloads or reply bodies in generic
metadata.

No approved support email provider abstraction exists in this repository.
External email delivery is deferred. The existing email helpers are
provider-coupled account/invite/system notification functions and are not used
for support replies.

Attachments are deferred. The existing media attachment subsystem is a
public-URL bot media library for chatbot/broadcast delivery and is not suitable
for private support-case files.

## HTTP Surface

The Phase 2 platform-admin endpoints are:

- `GET /api/platform-admin/support-case-assignees`
- `PATCH /api/platform-admin/support-cases/<case_id>/assignment`
- `PATCH /api/platform-admin/support-cases/<case_id>/status`
- `PATCH /api/platform-admin/support-cases/<case_id>/priority`
- `POST /api/platform-admin/support-cases/<case_id>/notes`

The Phase 3 platform-admin endpoints are:

- `GET /api/platform-admin/support-cases/<case_id>/replies`
- `POST /api/platform-admin/support-cases/<case_id>/replies`

The Phase 3 tenant endpoints are:

- `GET /api/support/requests`
- `GET /api/support/requests/<request_id>`

Platform-admin routes are protected by the existing platform-admin blueprint
guard. Tenant support routes use `token_required` plus refreshed
database-backed company/requester context and do not trust browser-supplied
company IDs. Request bodies are strict and unknown fields are rejected.

## Database and RPC Contract

Migration 032 extends the existing support-case tables instead of creating
parallel abstractions. It adds assignee-change event columns, the
`waiting_for_tenant` status, assignment event type support, indexes, and four
trusted mutation RPCs:

- `assign_platform_support_case(...)`
- `set_platform_support_case_status(...)`
- `set_platform_support_case_priority(...)`
- `add_platform_support_case_note(...)`

Each RPC locks the case row, validates the active platform-admin actor, performs
the case update, appends one support-case event, and inserts the platform-admin
audit event atomically. Mutation RPC execute privilege is revoked from `anon`
and `authenticated` and granted only to `service_role`.

Migration 032 also resets direct table and sequence grants for support-case
objects. Expected effective privileges after Migration 032:

| Object | Role | Required privileges | Must not have |
|---|---|---|---|
| `platform_support_cases` | `service_role` | `SELECT`, `INSERT`, `UPDATE` | `DELETE`, `TRUNCATE`, `TRIGGER`, `REFERENCES` |
| `platform_support_case_events` | `service_role` | `SELECT`, `INSERT` | `UPDATE`, `DELETE`, `TRUNCATE`, `TRIGGER`, `REFERENCES` |
| `platform_support_cases_id_seq` | `service_role` | `USAGE` | `SELECT`, `UPDATE` |
| `platform_support_case_events_id_seq` | `service_role` | `USAGE` | `SELECT`, `UPDATE` |
| support-case tables and sequences | `anon`, `authenticated` | none | all direct privileges |
| support-case mutation/helper RPCs | `service_role` | `EXECUTE` on approved call-chain functions only | execution by `anon` or `authenticated` |

RLS remains enabled on both support-case tables. No `anon` or `authenticated`
policies are approved for these tables.

Migration 032 must not be applied automatically to any other environment.
Verification requires actual Supabase execution output from the named
environment.

Migration 043 adds `public.create_platform_support_case(bigint, bigint, text,
text, text, text)` for initial support-case creation. The RPC validates the
active platform-admin actor, inserts the `platform_support_cases` row, appends
the initial `platform_support_case_events` row with `event_type = created`,
and inserts the `platform_admin_audit_events` row with action
`platform_admin.support_case.create` in one transaction. The application
service calls this RPC and does not insert a second create audit event. The
function is `SECURITY INVOKER`; execute privilege is revoked from `PUBLIC`,
`anon`, and `authenticated`, and granted only to `service_role`.

Migration 033 adds Phase 3 support communication objects and one trusted
mutation RPC:

- `tenant_support_replies`
- `tenant_support_reply_notifications`
- `platform_support_case_events.tenant_support_reply_id`
- `create_platform_support_case_reply(...)`

`create_platform_support_case_reply(...)` validates the active platform-admin
actor through the locked Phase 2 mapping helper, locks the internal case and
converted tenant request rows, verifies company linkage, inserts one
tenant-visible reply, updates the case timestamp, appends one
`tenant_reply_created` case event, inserts one safe platform-admin audit event,
and creates one pending `in_app` notification/outbox row atomically. Any event,
audit, or outbox insertion failure rolls back the reply and case update.

Migration 033 also enforces reply and outbox linkage at the database layer.
Every tenant-visible reply must match the authoritative converted request tuple
`tenant_support_requests(id, converted_platform_support_case_id, company_id)`
and the support case tuple `platform_support_cases(id, company_id)`.
Notification/outbox rows must match their referenced reply on `reply_id`,
`request_id`, `platform_support_case_id`, and `company_id`.
`tenant_reply_created` case events must use the composite
`platform_support_case_events(tenant_support_reply_id, case_id)` to
`tenant_support_replies(id, platform_support_case_id)` foreign key, and the
event consistency check requires a non-null reply ID only for
`tenant_reply_created` events while requiring it to be null for every other
case event type.

Tenant-visible replies are append-only. Notification ownership/linkage fields
are immutable after insertion: `reply_id`, `request_id`,
`platform_support_case_id`, `company_id`, `channel`, and `idempotency_key`
cannot be updated. Only delivery fields may change: `status`,
`attempt_count`, `last_attempt_at`, `delivered_at`, `failure_code`, and
`updated_at`.

Expected effective privileges after Migration 033:

| Object | Role | Required privileges | Must not have |
|---|---|---|---|
| `tenant_support_replies` | `service_role` | `SELECT`, `INSERT` | `UPDATE`, `DELETE`, `TRUNCATE`, `TRIGGER`, `REFERENCES` |
| `tenant_support_reply_notifications` | `service_role` | `SELECT`, `INSERT`, `UPDATE` | `DELETE`, `TRUNCATE`, `TRIGGER`, `REFERENCES` |
| reply/outbox identity sequences | `service_role` | `USAGE` | `SELECT`, `UPDATE` |
| reply/outbox tables and sequences | `anon`, `authenticated` | none | all direct privileges |
| `create_platform_support_case_reply(...)` | `service_role` | `EXECUTE` | execution by `anon` or `authenticated` |

RLS must be enabled on both new tables, with service-role-only policies. Direct
browser table mutation remains prohibited.

## Phase 3 Manual Schema Inspection SQL

Run before Migration 033 in any future environment:

```sql
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in (
    'tenant_support_replies',
    'tenant_support_reply_notifications',
    'support_threads',
    'platform_admin_messages'
  )
order by table_name;

select table_name, column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
  and table_name in (
    'tenant_support_requests',
    'platform_support_cases',
    'platform_support_case_events',
    'tenant_support_replies',
    'tenant_support_reply_notifications'
  )
order by table_name, ordinal_position;

select conrelid::regclass::text as table_name,
       conname,
       pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid in (
  'public.tenant_support_requests'::regclass,
  'public.platform_support_cases'::regclass,
  'public.platform_support_case_events'::regclass
)
order by table_name, conname;

select schemaname, tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename in (
    'tenant_support_requests',
    'platform_support_cases',
    'platform_support_case_events'
  )
order by tablename, indexname;

select p.proname,
       p.prosecdef as security_definer,
       p.proconfig,
       p.proacl
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in (
    'require_active_platform_admin_mapping',
    'create_platform_support_case_reply'
  )
order by p.proname;

select grantee, table_name, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in (
    'tenant_support_replies',
    'tenant_support_reply_notifications',
    'platform_support_case_events'
  )
  and grantee in ('service_role', 'anon', 'authenticated')
order by table_name, grantee, privilege_type;
```

Confirm before execution that `platform_support_case_events_type_check` is the
Migration 032 definition including `assignment_changed`, that
`tenant_support_requests_converted_case_fkey` and
`ux_tenant_support_requests_converted_case` exist, and that no existing
tenant-visible reply, notification, message, attachment, or support-thread
model already occupies the names introduced by Migration 033.

## Phase 3 Manual Verification SQL

Run only after applying Migration 033 in an approved fake/team data
environment:

```sql
select public.create_platform_support_case_reply(
  :case_id,
  :actor_mapping_id,
  'Safe tenant-visible reply from fake/team verification.'
);

select id, request_id, platform_support_case_id, company_id, author_type,
       visibility_status, redacted_body, created_at
from public.tenant_support_replies
where platform_support_case_id = :case_id
order by created_at asc, id asc;

select event_type, actor_platform_admin_user_id, tenant_support_reply_id,
       redacted_note, created_at
from public.platform_support_case_events
where case_id = :case_id
order by created_at asc, id asc;

select reply_id, channel, status, attempt_count, failure_code, created_at
from public.tenant_support_reply_notifications
where platform_support_case_id = :case_id
order by created_at asc, id asc;

select action, resource_type, resource_id, metadata
from public.platform_admin_audit_events
where action = 'platform_admin.support_case.reply.create'
order by created_at desc, id desc
limit 5;
```

Expected results: the RPC returns one reply, refreshed case, one
`tenant_reply_created` event, and one pending `in_app` notification; tenant
request and case company IDs match; audit metadata contains safe identifiers
and notification status only; reply body is absent from audit metadata; invalid
case IDs, cases without converted tenant requests, inactive actors, empty
replies, oversized replies, and linkage mismatches fail without partial rows.

## Manual Schema Inspection SQL

```sql
-- 1. Existing support-case columns affected by Migration 032.
select table_name, column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
  and table_name in ('platform_support_cases', 'platform_support_case_events')
order by table_name, ordinal_position;

-- 2. Existing constraints that Migration 032 must preserve, replace, or extend.
select conrelid::regclass::text as table_name,
       conname,
       pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid in (
  'public.platform_support_cases'::regclass,
  'public.platform_support_case_events'::regclass
)
  and conname in (
    'platform_support_cases_status_check',
    'platform_support_cases_priority_check',
    'platform_support_cases_closed_at_check',
    'platform_support_case_events_type_check',
    'platform_support_case_events_status_check',
    'platform_support_case_events_priority_check',
    'platform_support_case_events_note_length_check',
    'platform_support_case_events_old_assignee_fkey',
    'platform_support_case_events_new_assignee_fkey'
  )
order by table_name, conname;

-- 3. Indexes expected before and after Migration 032.
select schemaname, tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename in ('platform_support_cases', 'platform_support_case_events')
  and indexname in (
    'ix_platform_support_cases_company_updated',
    'ix_platform_support_cases_status_priority',
    'ix_platform_support_case_events_case_created',
    'ix_platform_support_cases_assignee_updated'
  )
order by tablename, indexname;

-- 4. RLS and policy posture.
select c.relname as table_name, c.relrowsecurity, c.relforcerowsecurity
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('platform_support_cases', 'platform_support_case_events');

select schemaname, tablename, policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'public'
  and tablename in ('platform_support_cases', 'platform_support_case_events')
order by tablename, policyname;

-- 5. Table and sequence privileges after Migration 032.
select grantee, table_name, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in ('platform_support_cases', 'platform_support_case_events')
  and grantee in ('service_role', 'anon', 'authenticated')
order by table_name, grantee, privilege_type;

select grantee, object_name, object_type, privilege_type
from information_schema.usage_privileges
where object_schema = 'public'
  and object_name in (
    'platform_support_cases_id_seq',
    'platform_support_case_events_id_seq'
  )
  and grantee in ('service_role', 'anon', 'authenticated')
order by object_name, grantee, privilege_type;

-- 6. RPC existence, security mode, safe search path, and privileges.
select p.proname,
       p.prosecdef as security_definer,
       p.proconfig,
       p.proacl
from pg_proc
join pg_namespace n on n.oid = p.pronamespace
where pronamespace = 'public'::regnamespace
  and p.proname in (
    'require_active_platform_admin_mapping',
    'assign_platform_support_case',
    'set_platform_support_case_status',
    'set_platform_support_case_priority',
    'add_platform_support_case_note'
  )
order by proname;
```

Before applying Migration 032 in any future environment, confirm these existing
constraint names and definitions:

- `platform_support_cases_status_check`: currently allows only `open`,
  `in_progress`, `resolved`, and `closed`; Migration 032 replaces it to add
  `waiting_for_tenant`.
- `platform_support_cases_priority_check`: allows only `low`, `normal`,
  `high`, and `urgent`; Migration 032 must preserve this model.
- `platform_support_cases_closed_at_check`: requires `closed_at` to be non-null
  exactly when `status = 'closed'`; Migration 032 status RPC relies on this.
- `platform_support_case_events_type_check`: currently allows `created`,
  `note_added`, `status_changed`, and `priority_changed`; Migration 032 replaces
  it to add `assignment_changed`.
- `platform_support_case_events_status_check`: currently mirrors the old status
  set; Migration 032 replaces it to include `waiting_for_tenant`.
- `platform_support_case_events_priority_check` and
  `platform_support_case_events_note_length_check`: must remain compatible and
  unchanged in meaning.
- `platform_support_case_events_old_assignee_fkey` and
  `platform_support_case_events_new_assignee_fkey`: should be absent before
  Migration 032 or already match `platform_admin_users(id) ON DELETE RESTRICT`
  if the migration has already been applied in a local/dev database.

## Manual Verification SQL

Run only with fake/team data in an approved shared-testing or staging database:

```sql
select status, priority, assigned_platform_admin_user_id
from public.platform_support_cases
where id = :case_id;

select public.assign_platform_support_case(:case_id, :actor_mapping_id, :assignee_mapping_id);
select public.set_platform_support_case_status(:case_id, :actor_mapping_id, 'in_progress');
select public.set_platform_support_case_priority(:case_id, :actor_mapping_id, 'high');
select public.add_platform_support_case_note(:case_id, :actor_mapping_id, 'Safe internal test note');

select event_type, actor_platform_admin_user_id, old_status, new_status,
       old_priority, new_priority,
       old_assigned_platform_admin_user_id, new_assigned_platform_admin_user_id,
       redacted_note is not null as has_note
from public.platform_support_case_events
where case_id = :case_id
order by created_at asc, id asc;

select action, resource_type, resource_id, metadata
from public.platform_admin_audit_events
where resource_id = :case_id::text
  and action like 'platform_admin.support_case.%'
order by created_at desc, id desc;
```

Expected results: each mutation returns a JSON object with `case` and `event`;
the case row reflects the latest authoritative state; one matching support-case
event exists per mutation; matching platform-admin audit rows exist; invalid
transitions/no-op changes raise errors; `anon` and `authenticated` do not have
RPC execute privileges.

## Main Shared-testing Verification

Migration 032 was applied and verified only in the main shared-testing Supabase
with fake/team data. This is not staging verification or production readiness.

Verified structural results:

- Migration 032 executed successfully.
- `platform_support_case_events.old_assigned_platform_admin_user_id` and
  `new_assigned_platform_admin_user_id` exist as nullable `BIGINT` columns.
- Support-case status constraints include `waiting_for_tenant`.
- Support-case event types include `assignment_changed`.
- New assignee event foreign keys reference `platform_admin_users(id)` with
  `ON DELETE RESTRICT`.
- `ix_platform_support_cases_assignee_updated` exists.
- RLS remains enabled and not forced on support-case tables.
- Only `service_role` policies exist on support-case tables.
- Table privileges match the least-privilege matrix in this contract.
- Only `service_role` has support-case identity sequence `USAGE`.
- All support-case helper and mutation functions are `SECURITY INVOKER`, use
  `search_path=pg_catalog`, and are executable only by `service_role`.

Verified fake/team mutation test:

- Case ID: `2`.
- Actor mapping ID: `1`.
- Assignee mapping ID: `1`.
- Assignment succeeded.
- Status `open` to `in_progress` succeeded.
- Priority `normal` to `high` succeeded.
- Internal note creation succeeded.
- Duplicate assignment was rejected with no event or audit row.
- Duplicate priority was rejected with no event or audit row.
- Invalid `in_progress` to `closed` transition was rejected with no event or
  audit row.
- `in_progress` to `resolved` to `closed` to `in_progress` succeeded.
- `closed_at` was populated on close and cleared on reopen.
- Final case state is `in_progress`, high priority, assigned mapping `1`, and
  `closed_at = NULL`.
- Eight ordered case events exist, including the original `created` event.
- Seven matching Phase 2 mutation audit events exist.
- Internal note content was not duplicated into audit metadata.

## Verification Evidence

Local focused tests for Phase 2 were run on August 6, 2026:

```text
python -m pytest -q tests\test_platform_admin_support_cases.py tests\test_platform_admin_support_case_operations_migration.py tests\test_platform_admin_routes.py tests\test_platform_admin_frontend.py tests\test_platform_admin_support_workflow_docs.py tests\test_tenant_support_routes.py
110 passed, 171 subtests passed

python -m pytest -q tests -k "platform_admin or tenant_support"
268 passed, 1608 deselected, 699 subtests passed

playwright test platform-admin.spec.js
Full run: 46 passed, 1 company-detail timeout.
Isolated rerun of the failed company-detail test: 1 passed.
Interpretation: transient/flaky browser timeout, not a clean 47-pass full run.
```

The local test evidence above remains local repository verification. The main
shared-testing evidence is limited to fake/team Supabase data and does not
establish staging or production readiness.

Local focused tests for Phase 3 were run on August 6, 2026:

```text
python -m pytest -q tests\test_platform_admin_tenant_communication_migration.py tests\test_platform_admin_support_cases.py tests\test_platform_admin_routes.py tests\test_tenant_support_routes.py tests\test_tenant_support_repository.py tests\test_platform_admin_frontend.py
112 passed, 137 subtests passed
```

## Phase 3 Main Shared-testing Verification

Migration 033 was applied successfully only in the main shared-testing Supabase
with fake/team data. This is not staging verification and does not establish
production readiness. Staging and production remain blocked.

Structural verification confirmed `tenant_support_replies`,
`tenant_support_reply_notifications`, and
`platform_support_case_events.tenant_support_reply_id` exist. RLS is enabled
and not forced on both Phase 3 tables. Only `service_role` policies exist.
`tenant_support_replies` grants `service_role` `SELECT` and `INSERT` only.
`tenant_support_reply_notifications` grants `service_role` `SELECT`, `INSERT`,
and `UPDATE` only. Reply and notification identity sequences grant
`service_role` `USAGE` only. `anon` and `authenticated` have no approved direct
access.

`create_platform_support_case_reply` is owned by `postgres`, is
`SECURITY INVOKER`, uses `search_path=pg_catalog`, and is executable only by
`service_role`. The two trigger functions are `SECURITY INVOKER`, use
`search_path=pg_catalog`, and are not directly executable by application roles.

Database integrity verification confirmed reply request/case/company linkage
is enforced, notification linkage matches its referenced reply tuple,
`tenant_reply_created` event linkage uses the composite
`(tenant_support_reply_id, case_id)` foreign key, and the old weaker
single-column reply foreign key is absent. `tenant_reply_created` requires a
non-null reply ID, and all other case event types require a null reply ID.
Tenant-visible replies are append-only. Notification ownership fields are
immutable, while approved notification delivery fields remain updatable.

The fake/team success-path verification used tenant request ID 1, platform
support case ID 2, company ID 1, active platform-admin mapping ID 1, reply ID
1, event ID 13, notification ID 1, and audit event ID 354. The successful RPC
created exactly one tenant-visible reply, one `tenant_reply_created` event, one
pending `in_app` notification, and one platform-admin audit event.

The returned and stored linkage was consistent: request 1, case 2, company 1,
platform-admin mapping 1, `author_type = platform_admin`,
`visibility_status = visible`, `channel = in_app`, initial notification
`status = pending`, and initial `attempt_count = 0`.

Audit verification confirmed action
`platform_admin.support_case.reply.create`, resource type
`tenant_support_replies`, resource ID 1, and safe linkage and delivery metadata
only. The audit event did not include reply body, internal note, provider
payload, or raw failure detail.

Protection verification confirmed reply `UPDATE` and reply `DELETE` were
rejected with SQLSTATE `55000`, notification ownership-field update was
rejected with SQLSTATE `55000`, and an approved delivery update succeeded with
`status = failed`, `attempt_count = 1`,
`failure_code = test_delivery_failure`, `last_attempt_at` set, and
`delivered_at` remaining null.

Atomic rejection verification confirmed invalid case was rejected with
`P0002 Support case not found`, a case without a converted tenant request was
rejected with `P0002 Converted tenant support request not found`, an
invalid/inactive platform-admin mapping was rejected with
`42501 Active platform-admin mapping is required`, and an empty reply was
rejected with `22023 Invalid tenant-visible reply`. Final counts remained
exactly one reply, one notification, one `tenant_reply_created` event, and one
reply audit event.

The local test evidence above remains local repository verification. The Phase
3 database evidence above is limited to fake/team data in main shared-testing
and does not establish staging or production readiness.
