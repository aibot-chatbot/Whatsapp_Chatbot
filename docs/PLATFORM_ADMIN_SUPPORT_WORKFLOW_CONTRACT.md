# Platform-admin Support Workflow Contract

## Status and Scope

Support Cases Phase 1 is applied and verified only in the main shared-testing
Supabase with fake/team data. Platform-admin Support Case Operations Phase 2 is
implemented and verified only in the main shared-testing Supabase with
fake/team data. Migration 032 executed successfully there.
No staging or production readiness is claimed for Phase 2.
Production remains blocked.

The workspace is internal to authorized platform administrators. It supports
case listing/detail, redacted case creation, assignment, status transitions,
priority updates, internal notes, and a server-provided activity timeline. It
does not send tenant replies, email, notifications, attachments, billing
actions, impersonation, exports, analytics, SLA timers, escalation automation,
bulk actions, or tenant suspension controls.
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
existing conversion mapping is present.

The browser renders the timeline from server facts only. Relevant events
include case creation, conversion-created case events, assignment changes,
priority changes, status changes, reopening, resolution, closure, and internal
note creation.

## HTTP Surface

The Phase 2 platform-admin endpoints are:

- `GET /api/platform-admin/support-case-assignees`
- `PATCH /api/platform-admin/support-cases/<case_id>/assignment`
- `PATCH /api/platform-admin/support-cases/<case_id>/status`
- `PATCH /api/platform-admin/support-cases/<case_id>/priority`
- `POST /api/platform-admin/support-cases/<case_id>/notes`

All routes are protected by the existing platform-admin blueprint guard. Request
bodies are strict and unknown fields are rejected.

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
